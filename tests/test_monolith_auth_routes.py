"""Registro, inicio de sesión y entrada con Google en el monolito (app/).

Es el API que sigue publicado en Render hasta pasar al gateway. Se prueba
con peticiones HTTP de verdad contra la SQLite temporal: qué responde cada
ruta, qué queda guardado y, sobre todo, quién puede entrar y con qué rol.
Google nunca se llama: sus respuestas se simulan.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from monolith import load_main

main = load_main()

import presentation.api.auth_routes as mono_auth  # noqa: E402
from core.security import (  # noqa: E402
    decode_access_token,
    get_password_hash,
    verify_password,
)
from infrastructure.database.models import TipoDiscapacidad, Usuario  # noqa: E402
from infrastructure.database.user_repository_impl import UserRepositoryImpl  # noqa: E402

client = TestClient(main.app)

CLIENT_ID = "code4all.apps.googleusercontent.com"
ACCESS_TOKEN = "ya29.token-de-prueba"
ID_TOKEN = "cabecera.contenido.firma"
PASSWORD = "clave-correcta"
PASSWORD_HASH = get_password_hash(PASSWORD)


def _add_user(db, correo, rol="estudiante", nombre="Ana", **extra):
    user = Usuario(nombre=nombre, correo=correo, password=PASSWORD_HASH, rol=rol, **extra)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _users(db, correo):
    db.expire_all()
    return db.query(Usuario).filter(Usuario.correo == correo).all()


def _register(**fields):
    body = {"nombre": "Ana", "correo": "ana@example.com", "password": "clave-segura"}
    body.update(fields)
    return client.post("/api/auth/register", json=body)


@pytest.fixture(autouse=True)
def _no_signup_codes(monkeypatch):
    # Cada prueba decide qué códigos de invitación hay; ninguno por defecto.
    monkeypatch.delenv("DOCENTE_SIGNUP_CODE", raising=False)
    monkeypatch.delenv("DIRECTOR_SIGNUP_CODE", raising=False)
    monkeypatch.delenv("ALLOW_DEV_LOGIN", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)


# --- Registro ----------------------------------------------------------------


def test_a_student_registers_and_the_password_is_stored_hashed(db_session):
    response = _register()

    assert response.status_code == 201
    body = response.json()
    assert body["correo"] == "ana@example.com"
    assert body["nombre"] == "Ana"
    assert body["rol"] == "estudiante"
    assert body["tipo_discapacidad"] is None
    assert body["fecha_registro"] not in ("", "None")
    assert "password" not in body

    [saved] = _users(db_session, "ana@example.com")
    assert saved.id_usuario == body["id_usuario"]
    assert saved.password != "clave-segura"
    assert verify_password("clave-segura", saved.password)


def test_an_email_can_only_be_registered_once(db_session):
    _add_user(db_session, "ana@example.com")

    response = _register()

    assert response.status_code == 400
    assert "ya se encuentra registrado" in response.json()["detail"]
    assert len(_users(db_session, "ana@example.com")) == 1


def test_a_known_disability_type_is_kept_and_an_unknown_one_is_dropped(db_session):
    db_session.add(TipoDiscapacidad(id_tipo=1, nombre="Visual"))
    db_session.commit()

    known = _register(correo="ana@example.com", tipo_discapacidad=1)
    unknown = _register(correo="luis@example.com", tipo_discapacidad=99)

    assert known.status_code == 201
    assert known.json()["tipo_discapacidad"] == 1
    assert unknown.status_code == 201
    assert unknown.json()["tipo_discapacidad"] is None


def test_a_teacher_cannot_register_without_the_invitation_code(db_session, monkeypatch):
    monkeypatch.setenv("DOCENTE_SIGNUP_CODE", "clave-docente")

    response = _register(rol="docente")

    assert response.status_code == 403
    assert "código de invitación" in response.json()["detail"]
    assert _users(db_session, "ana@example.com") == []


def test_a_teacher_registers_with_the_right_code(db_session, monkeypatch):
    monkeypatch.setenv("DOCENTE_SIGNUP_CODE", "clave-docente")

    wrong = _register(rol="docente", codigo_invitacion="otra-clave")
    right = _register(rol="Docente", codigo_invitacion=" clave-docente ")

    assert wrong.status_code == 403
    assert right.status_code == 201
    assert right.json()["rol"] == "docente"
    [saved] = _users(db_session, "ana@example.com")
    assert saved.rol == "docente"


def test_the_teacher_code_does_not_open_the_director_signup(db_session, monkeypatch):
    monkeypatch.setenv("DOCENTE_SIGNUP_CODE", "clave-docente")

    response = _register(rol="director", codigo_invitacion="clave-docente")

    assert response.status_code == 403
    assert "director" in response.json()["detail"]
    assert _users(db_session, "ana@example.com") == []


def test_director_signup_is_closed_when_no_code_is_configured(db_session):
    # Sin código configurado, ni siquiera un código vacío sirve.
    response = _register(rol="director", codigo_invitacion="")

    assert response.status_code == 403


def test_a_director_registers_with_the_director_code(db_session, monkeypatch):
    monkeypatch.setenv("DIRECTOR_SIGNUP_CODE", "clave-director")

    response = _register(rol="director", codigo_invitacion="clave-director")

    assert response.status_code == 201
    assert response.json()["rol"] == "director"


def test_an_unknown_role_ends_up_as_student(db_session):
    response = _register(rol="administrador")

    assert response.status_code == 201
    assert response.json()["rol"] == "estudiante"


def test_an_invalid_email_is_rejected_before_touching_the_database(db_session):
    response = _register(correo="no-es-un-correo")

    assert response.status_code == 422
    assert db_session.query(Usuario).count() == 0


def test_a_database_failure_while_registering_is_a_server_error(db_session, monkeypatch):
    class BrokenRepo(UserRepositoryImpl):
        def create_user(self, user_data):
            raise RuntimeError("la base no responde")

    monkeypatch.setattr(mono_auth, "UserRepositoryImpl", BrokenRepo)

    response = _register()

    assert response.status_code == 500
    assert response.json()["detail"] == "Error en el servidor: la base no responde"


# --- Inicio de sesión con correo y contraseña ---------------------------------


def _login(email="ana@example.com", password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_with_the_right_password_returns_a_token_with_the_role(db_session):
    user = _add_user(db_session, "ana@example.com", rol="docente", foto_path="/uploads/ana.png")

    response = _login()

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user_id"] == user.id_usuario
    assert body["email"] == "ana@example.com"
    assert body["nombre"] == "Ana"
    assert body["rol"] == "docente"
    assert body["photo_url"] == "/uploads/ana.png"

    payload = decode_access_token(body["access_token"])
    assert payload["sub"] == str(user.id_usuario)
    assert payload["email"] == "ana@example.com"
    assert payload["rol"] == "docente"


def test_login_without_a_photo_returns_an_empty_photo_url(db_session):
    _add_user(db_session, "ana@example.com")

    assert _login().json()["photo_url"] == ""


@pytest.mark.parametrize(
    "email, password",
    [("ana@example.com", "clave-equivocada"), ("nadie@example.com", PASSWORD)],
)
def test_a_wrong_password_or_unknown_email_gets_the_same_401(db_session, email, password):
    _add_user(db_session, "ana@example.com")

    response = _login(email, password)

    assert response.status_code == 401
    # El mensaje es el mismo para no revelar qué correos existen.
    assert response.json()["detail"] == "El correo o la contraseña son incorrectos."
    assert "access_token" not in response.json()


def test_a_password_stored_without_hashing_is_refused_not_accepted(db_session):
    # Una fila antigua con la contraseña en claro: passlib no reconoce el hash
    # y eso se responde como credenciales no válidas, nunca como acceso.
    db_session.add(Usuario(nombre="Viejo", correo="viejo@example.com", password=PASSWORD))
    db_session.commit()

    response = _login("viejo@example.com", PASSWORD)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_database_failure_while_logging_in_is_a_server_error(db_session, monkeypatch):
    class BrokenRepo(UserRepositoryImpl):
        def get_user_by_email(self, email):
            raise RuntimeError("se perdió la conexión")

    monkeypatch.setattr(mono_auth, "UserRepositoryImpl", BrokenRepo)

    response = _login()

    assert response.status_code == 500
    assert response.json()["detail"] == "Error en el servidor: se perdió la conexión"


# --- Entrar con Google ---------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeGoogleHttp:
    """Hace de tokeninfo y userinfo de Google, y apunta lo que se le pidió."""

    def __init__(self, tokeninfo, userinfo=(200, {"name": "Ana Google"})):
        self.tokeninfo = tokeninfo
        self.userinfo = userinfo
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if url == mono_auth.GOOGLE_TOKENINFO_URL:
            return FakeResponse(*self.tokeninfo)
        assert url == mono_auth.GOOGLE_USERINFO_URL
        return FakeResponse(*self.userinfo)


def _tokeninfo(**extra):
    data = {"aud": CLIENT_ID, "email": "ana@gmail.com", "email_verified": "true"}
    data.update(extra)
    return (200, data)


def _use_google_http(monkeypatch, fake):
    monkeypatch.setattr(mono_auth, "requests", SimpleNamespace(get=fake.get))
    return fake


def _use_id_token(monkeypatch, idinfo=None, error=None):
    seen = {}

    def verify(token, request):
        seen["token"] = token
        seen["request"] = request
        if error is not None:
            raise error
        return idinfo

    monkeypatch.setattr(mono_auth, "google_id_token", SimpleNamespace(verify_oauth2_token=verify))
    monkeypatch.setattr(mono_auth, "google_requests", SimpleNamespace(Request=lambda: "transporte"))
    return seen


def _google(**body):
    return client.post("/api/auth/google", json=body)


def test_dev_tokens_are_refused_unless_enabled(db_session, monkeypatch):
    # Con un token dev: cualquiera podía entrar con la cuenta de la dirección.
    _add_user(db_session, "director@univalle.edu.co", rol="director")

    response = _google(id_token="dev:director@univalle.edu.co")

    assert response.status_code == 401
    assert response.json()["detail"] == "Token de Google no válido"


@pytest.mark.parametrize("flag", ["1", "true", " YES "])
def test_an_enabled_dev_token_creates_a_student_account(db_session, monkeypatch, flag):
    monkeypatch.setenv("ALLOW_DEV_LOGIN", flag)

    response = _google(id_token="dev:nuevo@local.test:Juan")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "nuevo@local.test"
    assert body["nombre"] == "Juan"
    assert body["rol"] == "estudiante"
    [saved] = _users(db_session, "nuevo@local.test")
    assert saved.id_usuario == body["user_id"]
    assert saved.rol == "estudiante"
    assert decode_access_token(body["access_token"])["sub"] == str(saved.id_usuario)


def test_a_dev_token_without_a_name_uses_the_start_of_the_email(db_session, monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_LOGIN", "1")

    response = _google(id_token="dev: juan@local.test ")

    assert response.status_code == 200
    assert response.json()["nombre"] == "juan"


@pytest.mark.parametrize(
    "token, message",
    [("dev:   ", "vacío"), ("dev:sin-arroba:Ana", "correo válido")],
)
def test_a_malformed_dev_token_is_a_401(db_session, monkeypatch, token, message):
    monkeypatch.setenv("ALLOW_DEV_LOGIN", "1")

    response = _google(id_token=token)

    assert response.status_code == 401
    assert message in response.json()["detail"]
    assert db_session.query(Usuario).count() == 0


def test_parse_dev_identity_refuses_tokens_without_the_dev_prefix():
    with pytest.raises(ValueError, match="modo desarrollo"):
        mono_auth._parse_dev_identity("ana@local.test")


@pytest.mark.parametrize(
    "token, kind",
    [
        ("", "empty"),
        ("   ", "empty"),
        (None, "empty"),
        ("dev:ana@local.test", "dev_token"),
        (ACCESS_TOKEN, "access_token"),
        (ID_TOKEN, "id_token"),
        ("algo-raro", "unknown"),
    ],
)
def test_each_kind_of_google_token_is_recognised(token, kind):
    assert mono_auth._token_kind(token) == kind


def test_the_access_token_is_preferred_over_the_id_token():
    request = mono_auth.IdTokenRequest(access_token=ACCESS_TOKEN, id_token=ID_TOKEN)

    assert mono_auth._extract_google_token(request) == ACCESS_TOKEN
    assert mono_auth._extract_google_token(mono_auth.IdTokenRequest()) == ""


def test_an_existing_user_enters_with_google_keeping_their_role(db_session, monkeypatch):
    user = _add_user(
        db_session, "ana@gmail.com", rol="director", nombre="Ana", foto_path="/uploads/a.png"
    )
    fake = _use_google_http(monkeypatch, FakeGoogleHttp(_tokeninfo()))

    response = _google(access_token=ACCESS_TOKEN)

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user.id_usuario
    assert body["rol"] == "director"
    assert body["nombre"] == "Ana"
    assert body["photo_url"] == "/uploads/a.png"
    assert decode_access_token(body["access_token"])["rol"] == "director"
    # Se pregunta a tokeninfo para quién es el token, y a userinfo el nombre.
    assert fake.calls[0]["params"] == {"access_token": ACCESS_TOKEN}
    assert fake.calls[1]["headers"] == {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    assert len(_users(db_session, "ana@gmail.com")) == 1


def test_an_existing_user_without_photo_gets_an_empty_photo_url(db_session, monkeypatch):
    _add_user(db_session, "ana@gmail.com")
    _use_google_http(monkeypatch, FakeGoogleHttp(_tokeninfo()))

    assert _google(access_token=ACCESS_TOKEN).json()["photo_url"] == ""


def test_a_new_google_user_is_registered_as_student_with_the_google_name(db_session, monkeypatch):
    _use_google_http(monkeypatch, FakeGoogleHttp(_tokeninfo()))

    response = _google(access_token=ACCESS_TOKEN, id_token=ID_TOKEN)

    assert response.status_code == 200
    body = response.json()
    assert body["nombre"] == "Ana Google"
    assert body["rol"] == "estudiante"
    [saved] = _users(db_session, "ana@gmail.com")
    assert saved.nombre == "Ana Google"
    # Se le pone una contraseña al azar: nadie la conoce, ni siquiera ella.
    assert saved.password and not verify_password("", saved.password)


def test_the_client_id_can_match_the_authorised_party_and_be_one_of_several(
    db_session, monkeypatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", f" otra-app , ,{CLIENT_ID}")
    _use_google_http(
        monkeypatch,
        FakeGoogleHttp(_tokeninfo(aud="algo", azp=CLIENT_ID), userinfo=(200, {"given_name": "Ana"})),
    )

    response = _google(access_token=ACCESS_TOKEN)

    assert response.status_code == 200
    assert response.json()["nombre"] == "Ana"


def test_without_a_google_profile_the_name_comes_from_the_email(db_session, monkeypatch):
    _use_google_http(monkeypatch, FakeGoogleHttp(_tokeninfo(), userinfo=(403, {})))

    response = _google(access_token=ACCESS_TOKEN)

    assert response.status_code == 200
    assert response.json()["nombre"] == "ana"


def test_an_access_token_google_rejects_is_a_401(db_session, monkeypatch):
    _use_google_http(monkeypatch, FakeGoogleHttp((400, {"error": "invalid_token"})))

    response = _google(access_token=ACCESS_TOKEN)

    assert response.status_code == 401
    assert response.json()["detail"] == "Token de Google no válido"


def test_an_access_token_issued_for_another_app_is_refused(db_session, monkeypatch):
    # Una página cualquiera con «Iniciar sesión con Google» no puede usar el
    # token de sus visitantes para entrar en Code4All como ellos.
    _add_user(db_session, "ana@gmail.com", rol="director")
    _use_google_http(monkeypatch, FakeGoogleHttp(_tokeninfo(aud="otra-app", azp="otra-app")))

    response = _google(access_token=ACCESS_TOKEN)

    assert response.status_code == 401
    assert response.json()["detail"] == "Ese inicio de sesión de Google no es de Code4All."


def test_an_unverified_google_email_cannot_enter(db_session, monkeypatch):
    _add_user(db_session, "ana@gmail.com", rol="director")
    _use_google_http(monkeypatch, FakeGoogleHttp(_tokeninfo(email_verified="false")))

    response = _google(access_token=ACCESS_TOKEN)

    assert response.status_code == 401
    assert "no está verificado" in response.json()["detail"]


def test_google_login_is_unavailable_without_a_client_id(db_session, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", " , ")
    fake = _use_google_http(monkeypatch, FakeGoogleHttp(_tokeninfo()))

    response = _google(access_token=ACCESS_TOKEN)

    assert response.status_code == 503
    assert "GOOGLE_CLIENT_ID" in response.json()["detail"]
    assert fake.calls == []


def test_a_valid_id_token_signs_in_the_existing_user(db_session, monkeypatch):
    user = _add_user(db_session, "ana@gmail.com", rol="docente")
    seen = _use_id_token(
        monkeypatch, {"aud": CLIENT_ID, "email": "ana@gmail.com", "email_verified": True}
    )

    response = _google(id_token=ID_TOKEN)

    assert response.status_code == 200
    assert response.json()["user_id"] == user.id_usuario
    assert response.json()["rol"] == "docente"
    assert seen == {"token": ID_TOKEN, "request": "transporte"}


@pytest.mark.parametrize(
    "idinfo",
    [
        {"email_verified": "true", "given_name": "Ana"},
        {"verified_email": True, "name": "Ana"},
        {"verified_email": "TRUE", "name": "Ana"},
    ],
)
def test_the_id_token_verification_flag_can_come_in_several_forms(db_session, monkeypatch, idinfo):
    _use_id_token(monkeypatch, {"aud": CLIENT_ID, "email": "ana@gmail.com", **idinfo})

    response = _google(id_token=ID_TOKEN)

    assert response.status_code == 200
    assert response.json()["nombre"] == "Ana"


@pytest.mark.parametrize(
    "idinfo",
    [
        {"email_verified": False},
        {"email_verified": "false"},
        # Sin ninguna marca de verificación tampoco se entra.
        {},
    ],
)
def test_an_id_token_without_a_verified_email_is_refused(db_session, monkeypatch, idinfo):
    _use_id_token(monkeypatch, {"aud": CLIENT_ID, "email": "ana@gmail.com", **idinfo})

    response = _google(id_token=ID_TOKEN)

    assert response.status_code == 401
    assert db_session.query(Usuario).count() == 0


def test_an_id_token_for_another_app_is_refused(db_session, monkeypatch):
    _use_id_token(
        monkeypatch, {"aud": "otra-app", "email": "ana@gmail.com", "email_verified": True}
    )

    response = _google(id_token=ID_TOKEN)

    assert response.status_code == 401
    assert response.json()["detail"] == "Ese inicio de sesión de Google no es de Code4All."


def test_an_expired_or_forged_id_token_is_a_401(db_session, monkeypatch):
    seen = _use_id_token(monkeypatch, error=ValueError("Token expired"))

    response = _google()

    assert response.status_code == 401
    assert response.json()["detail"] == "Token expired"
    # Sin token se intenta igualmente como ID token, y Google lo rechaza.
    assert seen["token"] == ""


def test_a_verified_id_token_without_email_is_a_400(db_session, monkeypatch):
    _use_id_token(monkeypatch, {"aud": CLIENT_ID, "email_verified": True})

    response = _google(id_token=ID_TOKEN)

    assert response.status_code == 400
    assert "falta email" in response.json()["detail"]


def test_an_unexpected_failure_during_google_login_is_a_server_error(db_session, monkeypatch):
    _use_id_token(monkeypatch, error=RuntimeError("Google no responde"))

    response = _google(id_token=ID_TOKEN)

    assert response.status_code == 500
    assert response.json()["detail"] == "Error en servidor: Google no responde"
