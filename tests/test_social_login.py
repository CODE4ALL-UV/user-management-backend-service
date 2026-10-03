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


def _google_answers(monkeypatch, tokeninfo, userinfo=None):
    def fake_get(url, **kwargs):
        if url == auth_routes.GOOGLE_TOKENINFO_URL:
            return FakeResponse(200, tokeninfo)
        if url == auth_routes.GOOGLE_USERINFO_URL:
            return FakeResponse(200, userinfo or {"name": "Laura Gómez"})
        raise AssertionError(url)

    monkeypatch.setattr(auth_routes.requests, "get", fake_get)


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


# --- Facebook ----------------------------------------------------------------


def _facebook_configured(monkeypatch):
    monkeypatch.setenv("FACEBOOK_APP_ID", "1234")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "secreto-de-la-app")


def _facebook_answers(monkeypatch, profile, exchange_status=200):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append((url, params))
        if url.endswith("/oauth/access_token"):
            payload = {"access_token": "EAAB-token"} if exchange_status == 200 else {"error": {}}
            return FakeResponse(exchange_status, payload)
        if url.endswith("/me"):
            return FakeResponse(200, profile)
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
