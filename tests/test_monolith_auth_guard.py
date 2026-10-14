"""Quién llama y si puede editar el temario, en el monolito (app/).

`current_caller` y `require_course_editor` deciden a quién dejan pasar las
rutas del monolito. Se prueban con una aplicación mínima que manda la
cabecera Authorization como lo haría la app, con tokens firmados por el
propio monolito y con tokens caducados, ajenos o incompletos.
"""

from datetime import timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from monolith import load_main

load_main()

import presentation.api.auth_guard as mono_guard  # noqa: E402
from core.security import ALGORITHM, create_access_token  # noqa: E402

app = FastAPI()


@app.get("/whoami")
def whoami(caller: mono_guard.Caller = Depends(mono_guard.current_caller)):
    return {"email": caller.email, "role": caller.role, "user_id": caller.user_id}


@app.get("/course")
def edit_course(caller: mono_guard.Caller = Depends(mono_guard.require_course_editor)):
    return {"editor": caller.email}


client = TestClient(app)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _session(**data):
    return _bearer(create_access_token(data=data))


def test_the_caller_comes_from_the_signed_token():
    response = client.get(
        "/whoami", headers=_session(sub="7", email="ana@example.com", rol="Docente")
    )

    assert response.status_code == 200
    # El rol se normaliza a minúsculas.
    assert response.json() == {"email": "ana@example.com", "role": "docente", "user_id": 7}


def test_the_role_can_also_come_as_role():
    response = client.get("/whoami", headers=_session(sub="7", email="a@x.co", role="DIRECTOR"))

    assert response.json()["role"] == "director"


@pytest.mark.parametrize("sub", [None, "no-es-un-numero"])
def test_a_token_without_a_numeric_id_still_identifies_by_email(sub):
    data = {"email": "ana@example.com", "rol": "estudiante"}
    if sub is not None:
        data["sub"] = sub

    response = client.get("/whoami", headers=_session(**data))

    assert response.status_code == 200
    assert response.json()["user_id"] is None


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer "}, {"Authorization": "Basic abc"}])
def test_without_a_bearer_token_the_session_is_missing(headers):
    response = client.get("/whoami", headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"] == "Falta la sesión. Vuelve a iniciar sesión."
    assert response.headers["www-authenticate"] == "Bearer"


def test_an_expired_token_is_refused():
    token = create_access_token(
        data={"sub": "7", "email": "ana@example.com", "rol": "docente"},
        expires_delta=timedelta(minutes=-1),
    )

    response = client.get("/whoami", headers=_bearer(token))

    assert response.status_code == 401
    assert "caducó" in response.json()["detail"]


def test_a_token_signed_with_another_key_is_refused():
    # Quien no tiene la clave del servidor no puede fabricarse un rol.
    forged = jwt.encode(
        {"sub": "7", "email": "ana@example.com", "rol": "director"},
        "otra-clave-que-no-es-la-del-servidor",
        algorithm=ALGORITHM,
    )

    response = client.get("/course", headers=_bearer(forged))

    assert response.status_code == 401


def test_a_garbage_token_is_refused():
    response = client.get("/whoami", headers=_bearer("esto-no-es-un-jwt"))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_token_without_email_identifies_nobody():
    response = client.get("/whoami", headers=_session(sub="7", rol="docente"))

    assert response.status_code == 401
    assert response.json()["detail"] == "La sesión no identifica a nadie."


@pytest.mark.parametrize("rol", ["docente", "director"])
def test_teachers_and_directors_can_edit_the_course(rol):
    response = client.get("/course", headers=_session(sub="1", email="staff@x.co", rol=rol))

    assert response.status_code == 200
    assert response.json() == {"editor": "staff@x.co"}


@pytest.mark.parametrize("rol", ["estudiante", "", "administrador"])
def test_anyone_else_cannot_edit_the_course(rol):
    response = client.get("/course", headers=_session(sub="1", email="otro@x.co", rol=rol))

    assert response.status_code == 403
    assert response.json()["detail"] == "Solo un docente puede editar el contenido del curso."


def test_without_a_session_the_course_editor_check_is_a_401_not_a_403():
    assert client.get("/course").status_code == 401


def test_caller_knows_whether_it_can_edit_the_course():
    assert mono_guard.Caller("a@x.co", "docente", 1).can_edit_course is True
    assert mono_guard.Caller("a@x.co", "director").can_edit_course is True
    student = mono_guard.Caller("a@x.co", "estudiante")
    assert student.can_edit_course is False
    assert student.user_id is None
