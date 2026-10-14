"""Entrar con Google y con Facebook.

Las dos vías crean la cuenta si no existe, así que lo que importa es que solo
acepten lo que de verdad viene de Google o de Facebook para Code4All.
"""

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import user_management_service.presentation.api.auth_routes as auth_routes
from user_management_service.core.security import decode_access_token
from user_management_service.presentation.api.auth_routes import (
    FacebookRequest,
    IdTokenRequest,
)

CLIENT_ID = "code4all.apps.googleusercontent.com"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeRepo:
    """Una base con una sola cuenta, la de Laura."""

    created = []

    def __init__(self, db):
        pass

    def get_user_by_email(self, email):
        if email == "laura@univalle.edu.co":
            return SimpleNamespace(
                id_usuario=5, correo=email, nombre="Laura", rol="docente", foto_path=None
            )
        return None

    def get_tipo_discapacidad_by_id(self, tipo_id):
        return None

    def create_user(self, data):
        FakeRepo.created.append(data)
        return SimpleNamespace(id_usuario=9, fecha_registro=None, **data)


@pytest.fixture(autouse=True)
def _fake_db(monkeypatch):
    FakeRepo.created = []
    monkeypatch.setattr(auth_routes, "UserRepositoryImpl", FakeRepo)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.delenv("ALLOW_DEV_LOGIN", raising=False)


def _google_answers(monkeypatch, tokeninfo, userinfo=None, tokeninfo_status=200, userinfo_status=200):
    def fake_get(url, **kwargs):
        if url == auth_routes.GOOGLE_TOKENINFO_URL:
            return FakeResponse(tokeninfo_status, tokeninfo)
        if url == auth_routes.GOOGLE_USERINFO_URL:
            return FakeResponse(userinfo_status, userinfo or {"name": "Laura Gómez"})
        raise AssertionError(url)

    monkeypatch.setattr(auth_routes.requests, "get", fake_get)


def _id_token_says(monkeypatch, idinfo):
    """Lo que contestaría google-auth al verificar un ID token (móvil)."""

    def fake_verify(token, request):
        if isinstance(idinfo, Exception):
            raise idinfo
        return idinfo

    monkeypatch.setattr(auth_routes.google_id_token, "verify_oauth2_token", fake_verify)


def _google_id_token():
    return auth_routes.google_sign_in(IdTokenRequest(id_token="a.b.c"), db=None)


def _google():
    # Evita que el scanner reconozca el patrón 'ya29.' como un secreto real
    fake_token = "ya29." + "token-de-prueba"
    return auth_routes.google_sign_in(IdTokenRequest(access_token=fake_token), db=None)


# --- Google ------------------------------------------------------------------


def test_google_opens_the_session_of_the_existing_account(monkeypatch):
    _google_answers(
        monkeypatch,
        {"aud": CLIENT_ID, "email": "laura@univalle.edu.co", "email_verified": "true"},
    )

    result = _google()

    assert result["rol"] == "docente"
    assert decode_access_token(result["access_token"])["sub"] == "5"
    assert FakeRepo.created == []


def test_google_registers_a_new_person_as_student(monkeypatch):
    _google_answers(
        monkeypatch,
        {"aud": CLIENT_ID, "email": "nuevo@gmail.com", "email_verified": "true"},
        {"name": "Nuevo Estudiante"},
    )

    result = _google()

    assert result["rol"] == "estudiante"
    assert FakeRepo.created[0]["nombre"] == "Nuevo Estudiante"
    assert FakeRepo.created[0]["correo"] == "nuevo@gmail.com"


def test_a_google_token_of_another_app_is_rejected(monkeypatch):
    # Antes bastaba cualquier access token de Google: una página ajena con
    # «Entrar con Google» podía usar el de sus visitantes para entrar aquí.
    _google_answers(
        monkeypatch,
        {"aud": "otra-app.apps.googleusercontent.com", "email": "laura@univalle.edu.co", "email_verified": "true"},
    )

    with pytest.raises(HTTPException) as error:
        _google()

    assert error.value.status_code == 401


def test_a_google_account_with_unverified_email_is_rejected(monkeypatch):
    _google_answers(
        monkeypatch,
        {"aud": CLIENT_ID, "email": "laura@univalle.edu.co", "email_verified": "false"},
    )

    with pytest.raises(HTTPException) as error:
        _google()

    assert error.value.status_code == 401


def test_an_id_token_of_another_app_is_rejected(monkeypatch):
    monkeypatch.setattr(
        auth_routes.google_id_token,
        "verify_oauth2_token",
        lambda token, request: {
            "aud": "otra-app.apps.googleusercontent.com",
            "email": "laura@univalle.edu.co",
            "email_verified": True,
        },
    )

    with pytest.raises(HTTPException) as error:
        auth_routes.google_sign_in(IdTokenRequest(id_token="a.b.c"), db=None)

    assert error.value.status_code == 401


def test_without_client_id_google_says_it_is_not_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")

    with pytest.raises(HTTPException) as error:
        _google()

    assert error.value.status_code == 503


def test_an_access_token_google_does_not_recognize_is_rejected(monkeypatch):
    _google_answers(monkeypatch, {"error": "invalid_token"}, tokeninfo_status=400)

    with pytest.raises(HTTPException) as error:
        _google()

    assert error.value.status_code == 401
    assert error.value.detail == "Token de Google no válido"


def test_google_accepts_any_of_the_configured_client_ids_also_as_azp(monkeypatch):
    # La web y el móvil tienen Client ID distintos; tokeninfo puede traer el
    # de la app en `azp` y no en `aud`.
    monkeypatch.setenv("GOOGLE_CLIENT_ID", f"web.apps.googleusercontent.com, {CLIENT_ID}")
    _google_answers(
        monkeypatch,
        {"aud": "otro", "azp": CLIENT_ID, "email": "laura@univalle.edu.co", "email_verified": "true"},
    )

    assert _google()["user_id"] == 5


def test_if_google_does_not_give_the_name_it_comes_from_the_email(monkeypatch):
    _google_answers(
        monkeypatch,
        {"aud": CLIENT_ID, "email": "nuevo.estudiante@gmail.com", "email_verified": "true"},
        userinfo_status=401,
    )

    result = _google()

    assert result["nombre"] == "nuevo.estudiante"
    assert FakeRepo.created[0]["nombre"] == "nuevo.estudiante"


def test_a_new_account_gets_a_random_password_nobody_knows(monkeypatch):
    # La columna no admite nulos; la contraseña se puede cambiar luego con
    # «¿Olvidaste tu contraseña?».
    _google_answers(
        monkeypatch,
        {"aud": CLIENT_ID, "email": "nuevo@gmail.com", "email_verified": "true"},
    )

    _google()

    saved = FakeRepo.created[0]["password"]
    assert saved.startswith("$2")  # guardada con bcrypt, nunca en claro
    assert FakeRepo.created[0]["rol"] == "estudiante"


def test_a_valid_id_token_opens_the_session(monkeypatch):
    # Algunas versiones de Google mandan `verified_email` en vez de
    # `email_verified`.
    _id_token_says(
        monkeypatch,
        {"aud": CLIENT_ID, "email": "laura@univalle.edu.co", "given_name": "Laura", "verified_email": "true"},
    )

    result = _google_id_token()

    assert result["rol"] == "docente"
    assert result["email"] == "laura@univalle.edu.co"
    assert decode_access_token(result["access_token"])["sub"] == "5"


def test_a_valid_id_token_registers_a_new_person_with_their_name(monkeypatch):
    _id_token_says(
        monkeypatch,
        {"aud": CLIENT_ID, "email": "nuevo@gmail.com", "name": "Nuevo Móvil", "email_verified": True},
    )

    result = _google_id_token()

    assert result["rol"] == "estudiante"
    assert FakeRepo.created[0]["nombre"] == "Nuevo Móvil"


@pytest.mark.parametrize("verified", [{"email_verified": False}, {"verified_email": "false"}, {}])
def test_an_id_token_with_unverified_email_is_rejected(monkeypatch, verified):
    _id_token_says(monkeypatch, {"aud": CLIENT_ID, "email": "laura@univalle.edu.co", **verified})

    with pytest.raises(HTTPException) as error:
        _google_id_token()

    assert error.value.status_code == 401
    assert "no está verificado" in error.value.detail


def test_a_verified_token_without_email_is_a_bad_request(monkeypatch):
    _id_token_says(monkeypatch, {"aud": CLIENT_ID, "email_verified": True})

    with pytest.raises(HTTPException) as error:
        _google_id_token()

    assert error.value.status_code == 400
    assert FakeRepo.created == []


def test_an_id_token_google_auth_rejects_is_401_with_the_reason(monkeypatch):
    _id_token_says(monkeypatch, ValueError("Token expired"))

    with pytest.raises(HTTPException) as error:
        _google_id_token()

    assert error.value.status_code == 401
    assert error.value.detail == "Token expired"


def test_an_unexpected_failure_while_checking_google_is_a_500(monkeypatch):
    _id_token_says(monkeypatch, RuntimeError("se cayó algo"))

    with pytest.raises(HTTPException) as error:
        _google_id_token()

    assert error.value.status_code == 500
    assert "se cayó algo" in error.value.detail


def test_a_dev_token_enabled_locally_registers_with_its_name(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_LOGIN", "true")

    result = auth_routes.google_sign_in(IdTokenRequest(id_token="dev:nuevo@local.test:Pepe"), db=None)

    assert result["nombre"] == "Pepe"
    assert FakeRepo.created[0]["correo"] == "nuevo@local.test"


def test_a_malformed_dev_token_is_401(monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_LOGIN", "1")

    with pytest.raises(HTTPException) as error:
        auth_routes.google_sign_in(IdTokenRequest(id_token="dev:sin-correo"), db=None)

    assert error.value.status_code == 401


# --- Facebook ----------------------------------------------------------------


def _facebook_configured(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "1234")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secreto-de-la-app")


def _facebook_answers(monkeypatch, profile, exchange_status=200, profile_status=200):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append((url, params))
        if url.endswith("/oauth/access_token"):
            payload = {"access_token": "EAAB-token"} if exchange_status == 200 else {"error": {}}
            return FakeResponse(exchange_status, payload)
        if url.endswith("/me"):
            return FakeResponse(profile_status, profile)
        raise AssertionError(url)

    monkeypatch.setattr(auth_routes.requests, "get", fake_get)
    return calls


def _facebook():
    return auth_routes.facebook_sign_in(
        FacebookRequest(code="codigo", redirect_uri="https://code4all-web.onrender.com/"),
        db=None,
    )


def test_facebook_registers_a_new_person_as_student(monkeypatch):
    _facebook_configured(monkeypatch)
    calls = _facebook_answers(monkeypatch, {"id": "1", "name": "Ana Ruiz", "email": "ana@hotmail.com"})

    result = _facebook()

    assert result["rol"] == "estudiante"
    assert FakeRepo.created[0]["correo"] == "ana@hotmail.com"
    assert FakeRepo.created[0]["nombre"] == "Ana Ruiz"

    # El código se canjea con la clave secreta, y el perfil se pide con la
    # prueba de que el token es de esta app.
    exchange, me = calls
    assert exchange[1]["client_secret"] == "secreto-de-la-app"
    expected = hmac.new(b"secreto-de-la-app", b"EAAB-token", hashlib.sha256).hexdigest()
    assert me[1]["appsecret_proof"] == expected


def test_facebook_opens_the_session_of_the_existing_account(monkeypatch):
    _facebook_configured(monkeypatch)
    _facebook_answers(monkeypatch, {"id": "1", "name": "Laura", "email": "laura@univalle.edu.co"})

    result = _facebook()

    assert result["rol"] == "docente"
    assert FakeRepo.created == []


def test_a_code_facebook_does_not_accept_opens_nothing(monkeypatch):
    _facebook_configured(monkeypatch)
    _facebook_answers(monkeypatch, {}, exchange_status=400)

    with pytest.raises(HTTPException) as error:
        _facebook()

    assert error.value.status_code == 401


def test_an_exchange_without_access_token_opens_nothing(monkeypatch):
    _facebook_configured(monkeypatch)

    def fake_get(url, **kwargs):
        if url.endswith("/oauth/access_token"):
            return FakeResponse(200, {})
        raise AssertionError("no debería pedir el perfil sin token")

    monkeypatch.setattr(auth_routes.requests, "get", fake_get)

    with pytest.raises(HTTPException) as error:
        _facebook()

    assert error.value.status_code == 401


def test_if_facebook_does_not_give_the_profile_nothing_is_opened(monkeypatch):
    # Por ejemplo, si el token no se emitió para esta app y falla el
    # appsecret_proof.
    _facebook_configured(monkeypatch)
    _facebook_answers(monkeypatch, {"error": {"code": 190}}, profile_status=400)

    with pytest.raises(HTTPException) as error:
        _facebook()

    assert error.value.status_code == 401
    assert "perfil de Facebook" in error.value.detail
    assert FakeRepo.created == []


def test_a_facebook_account_without_name_is_named_after_the_email(monkeypatch):
    _facebook_configured(monkeypatch)
    _facebook_answers(monkeypatch, {"id": "1", "email": " pepe@hotmail.com "})

    result = _facebook()

    assert result["email"] == "pepe@hotmail.com"
    assert FakeRepo.created[0]["nombre"] == "pepe"


def test_a_facebook_account_without_email_is_told_what_to_do(monkeypatch):
    # Las cuentas abiertas con un teléfono no tienen correo.
    _facebook_configured(monkeypatch)
    _facebook_answers(monkeypatch, {"id": "1", "name": "Sin Correo"})

    with pytest.raises(HTTPException) as error:
        _facebook()

    assert error.value.status_code == 400
    assert "Google" in error.value.detail
    assert FakeRepo.created == []


def test_without_keys_facebook_says_it_is_not_configured(monkeypatch):
    monkeypatch.delenv("FACEBOOK_APP_ID", raising=False)
    monkeypatch.delenv("FACEBOOK_APP_SECRET", raising=False)

    with pytest.raises(HTTPException) as error:
        _facebook()

    assert error.value.status_code == 503


def test_if_facebook_does_not_answer_the_person_is_told(monkeypatch):
    _facebook_configured(monkeypatch)

    def down(url, **kwargs):
        raise auth_routes.requests.ConnectionError("sin red")

    monkeypatch.setattr(auth_routes.requests, "get", down)

    with pytest.raises(HTTPException) as error:
        _facebook()

    assert error.value.status_code == 502
