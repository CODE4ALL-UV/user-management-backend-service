"""Registro, inicio de sesión y cambio de contraseña, de punta a punta.

Se llama a las rutas por HTTP, como la app, y contra la SQLite temporal de las
pruebas: así se ve lo que de verdad queda guardado. Los correos no se envían;
se recogen en una lista.
"""

from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neon_storage.models import Usuario
from user_management_service.application.use_cases import password_reset
from user_management_service.core import mailer
from user_management_service.core.security import (
    decode_access_token,
    get_password_hash,
    verify_password,
)
from user_management_service.infrastructure.database.user_repository_impl import (
    UserRepositoryImpl,
)
from user_management_service.presentation.api import auth_routes

app = FastAPI()
app.include_router(auth_routes.router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # El .env del gateway, si lo hay, no debe cambiar lo que se prueba.
    for name in (
        "DOCENTE_SIGNUP_CODE",
        "DIRECTOR_SIGNUP_CODE",
        "BREVO_API_KEY",
        "MAIL_FROM",
        "MAIL_FROM_NAME",
        "ALLOW_DEV_LOGIN",
        "FRONTEND_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _register(**extra):
    body = {"nombre": "Ana", "correo": "ana@example.com", "password": "clave-de-ana"}
    body.update(extra)
    return client.post("/api/auth/register", json=body)


def _login(email="ana@example.com", password="clave-de-ana"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _saved_user(db_session, correo="ana@example.com", password="clave-de-ana", **extra):
    data = {"nombre": "Ana", "correo": correo, "password": get_password_hash(password)}
    data.update(extra)
    return UserRepositoryImpl(db_session).create_user(data)


# --- Registro ----------------------------------------------------------------


def test_registering_creates_a_student_and_never_returns_the_password(db_session):
    response = _register()

    assert response.status_code == 201
    body = response.json()
    assert body["correo"] == "ana@example.com"
    assert body["nombre"] == "Ana"
    assert body["rol"] == "estudiante"
    assert body["tipo_discapacidad"] is None
    assert "password" not in body
    date.fromisoformat(body["fecha_registro"])

    saved = db_session.query(Usuario).filter_by(correo="ana@example.com").one()
    assert saved.id_usuario == body["id_usuario"]
    assert saved.password != "clave-de-ana"
    assert verify_password("clave-de-ana", saved.password)


def test_registering_the_same_email_twice_is_a_400(db_session):
    assert _register().status_code == 201

    response = _register(nombre="Otra Ana")

    assert response.status_code == 400
    assert "ya se encuentra registrado" in response.json()["detail"]
    assert db_session.query(Usuario).count() == 1


def test_a_teacher_without_the_invitation_code_is_not_registered(db_session, monkeypatch):
    monkeypatch.setenv("DOCENTE_SIGNUP_CODE", "clave-docente")

    response = _register(rol="docente", codigo_invitacion="me-la-invento")

    assert response.status_code == 403
    assert db_session.query(Usuario).count() == 0


def test_a_teacher_with_the_invitation_code_is_registered_as_teacher(db_session, monkeypatch):
    monkeypatch.setenv("DOCENTE_SIGNUP_CODE", "clave-docente")

    response = _register(rol="Docente", codigo_invitacion="clave-docente")

    assert response.status_code == 201
    assert response.json()["rol"] == "docente"


def test_an_invalid_email_is_rejected_before_touching_the_database(db_session):
    response = _register(correo="esto-no-es-un-correo")

    assert response.status_code == 422
    assert db_session.query(Usuario).count() == 0


def test_an_unexpected_failure_while_registering_is_a_500(monkeypatch):
    class Broken:
        def __init__(self, user_repository):
            pass

        def execute(self, data):
            raise RuntimeError("la base no responde")

    monkeypatch.setattr(auth_routes, "CreateUserUseCase", Broken)

    response = _register()

    assert response.status_code == 500
    assert response.json()["detail"] == "Error en el servidor: la base no responde"


# --- Inicio de sesión --------------------------------------------------------


def test_a_registered_person_can_log_in_and_gets_their_role(db_session):
    user = _saved_user(db_session, rol="director", foto_path="/uploads/ana.png")

    response = _login()

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user.id_usuario
    assert body["rol"] == "director"
    assert body["photo_url"] == "/uploads/ana.png"
    claims = decode_access_token(body["access_token"])
    assert claims["sub"] == str(user.id_usuario)
    assert claims["rol"] == "director"


def test_registering_and_then_logging_in_works(db_session):
    _register()

    response = _login()

    assert response.status_code == 200
    assert response.json()["email"] == "ana@example.com"


@pytest.mark.parametrize(
    "email, password",
    [("ana@example.com", "clave-equivocada"), ("nadie@example.com", "clave-de-ana")],
)
def test_a_wrong_password_or_unknown_email_is_a_401(db_session, email, password):
    _saved_user(db_session)

    response = _login(email, password)

    assert response.status_code == 401
    assert response.json()["detail"] == "El correo o la contraseña son incorrectos."


def test_an_account_whose_password_cannot_be_read_gets_a_401(db_session):
    # Una fila antigua con la contraseña sin cifrar: passlib no reconoce el
    # hash y lanza ValueError. No debe acabar en un 500.
    UserRepositoryImpl(db_session).create_user(
        {"nombre": "Vieja", "correo": "vieja@example.com", "password": "texto-plano"}
    )

    response = _login("vieja@example.com", "texto-plano")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_an_unexpected_failure_while_logging_in_is_a_500(monkeypatch):
    class Broken:
        def __init__(self, user_repository):
            pass

        def execute(self, email, password_from_flutter):
            raise RuntimeError("la base no responde")

    monkeypatch.setattr(auth_routes, "LoginUserUseCase", Broken)

    response = _login()

    assert response.status_code == 500
    assert response.json()["detail"] == "Error en el servidor: la base no responde"


# --- Recuperar la contraseña -------------------------------------------------


@pytest.fixture
def mails(monkeypatch):
    sent = []
    monkeypatch.setenv("BREVO_API_KEY", "clave-brevo")
    monkeypatch.setenv("MAIL_FROM", "code4all@example.com")
    monkeypatch.setattr(mailer, "send_mail", lambda **mail: sent.append(mail))
    monkeypatch.setattr(password_reset, "_last_sent", {})
    return sent


def _link_in(mail):
    return mail["text"].split("abre este enlace:\n\n", 1)[1].split("\n", 1)[0]


def test_forgot_password_without_mail_configured_is_a_503(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_mail", lambda **mail: sent.append(mail))

    response = client.post("/api/auth/password/forgot", json={"correo": "ana@example.com"})

    assert response.status_code == 503
    assert "no está configurada" in response.json()["detail"]
    assert sent == []


def test_forgot_password_sends_the_link_to_the_configured_web(db_session, mails, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173/")
    _saved_user(db_session)

    response = client.post("/api/auth/password/forgot", json={"correo": "ana@example.com"})

    assert response.status_code == 200
    assert response.json() == {"detail": auth_routes.FORGOT_PASSWORD_REPLY}
    assert len(mails) == 1
    assert mails[0]["to_email"] == "ana@example.com"
    assert _link_in(mails[0]).startswith("http://localhost:5173/?restablecer=")


def test_forgot_password_points_to_the_published_web_by_default(db_session, mails):
    _saved_user(db_session)

    client.post("/api/auth/password/forgot", json={"correo": "ana@example.com"})

    assert _link_in(mails[0]).startswith(auth_routes.DEFAULT_FRONTEND_URL + "/?restablecer=")


def test_forgot_password_answers_the_same_for_unknown_emails(db_session, mails):
    # Así nadie puede averiguar quién está registrado.
    response = client.post("/api/auth/password/forgot", json={"correo": "nadie@example.com"})

    assert response.status_code == 200
    assert response.json() == {"detail": auth_routes.FORGOT_PASSWORD_REPLY}
    assert mails == []


def test_the_mailed_link_changes_the_password_once(db_session, mails):
    user = _saved_user(db_session)
    client.post("/api/auth/password/forgot", json={"correo": "ana@example.com"})
    token = parse_qs(urlparse(_link_in(mails[0])).query)["restablecer"][0]

    response = client.post("/api/auth/password/reset", json={"token": token, "password": "clave-nueva"})

    assert response.status_code == 200
    assert "Ya puedes iniciar sesión" in response.json()["detail"]
    db_session.expire_all()
    assert verify_password("clave-nueva", db_session.get(Usuario, user.id_usuario).password)
    assert _login(password="clave-nueva").status_code == 200
    assert _login(password="clave-de-ana").status_code == 401

    again = client.post("/api/auth/password/reset", json={"token": token, "password": "otra-clave"})
    assert again.status_code == 400
    assert again.json()["detail"] == "El enlace ya no sirve: caducó o ya se usó. Pide uno nuevo."


def test_a_made_up_link_does_not_change_anything(db_session):
    _saved_user(db_session)

    response = client.post(
        "/api/auth/password/reset", json={"token": "no-es-un-enlace", "password": "clave-nueva"}
    )

    assert response.status_code == 400
    assert "ya no sirve" in response.json()["detail"]
    assert _login().status_code == 200


def test_a_too_short_new_password_is_explained(db_session):
    user = _saved_user(db_session)
    token = password_reset.create_reset_token(user)

    response = client.post("/api/auth/password/reset", json={"token": token, "password": "corta"})

    assert response.status_code == 400
    assert response.json()["detail"] == "La contraseña debe tener al menos 6 caracteres."
    assert _login().status_code == 200


# --- Mayúsculas en el correo -------------------------------------------------


def test_the_email_is_saved_in_lowercase(db_session):
    response = _register(correo="Ana@Example.com")

    assert response.status_code == 201
    assert response.json()["correo"] == "ana@example.com"
    assert db_session.query(Usuario).one().correo == "ana@example.com"


def test_logging_in_ignores_capitals_in_the_email(db_session):
    _register(correo="Ana@Example.com")

    for email in ("ana@example.com", "ANA@EXAMPLE.COM", "Ana@Example.com"):
        assert _login(email=email).status_code == 200


def test_an_account_saved_with_capitals_can_log_in_in_lowercase(db_session):
    # Las cuentas creadas antes de guardar en minúsculas siguen tal cual.
    old = _saved_user(db_session, correo="Ana@Example.com")

    response = _login(email="ana@example.com")

    assert response.status_code == 200
    assert response.json()["user_id"] == old.id_usuario
    # El token lleva el correo como está guardado, que es con el que se
    # firmaron sus ediciones del temario.
    assert decode_access_token(response.json()["access_token"])["email"] == "Ana@Example.com"


def test_the_same_email_with_other_capitals_cannot_be_registered_again(db_session):
    _saved_user(db_session, correo="Ana@Example.com")

    response = _register(correo="ana@example.com", nombre="Otra Ana")

    assert response.status_code == 400
    assert db_session.query(Usuario).count() == 1


def test_google_or_facebook_finds_the_account_registered_with_capitals(db_session):
    old = _saved_user(db_session, correo="Ana@Example.com")

    session = auth_routes._session_for(db_session, "ana@example.com", "Ana")

    assert session["user_id"] == old.id_usuario
    assert db_session.query(Usuario).count() == 1
