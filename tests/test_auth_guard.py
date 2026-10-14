"""Quién llama y si puede editar el temario.

Los demás microservicios confían en `current_caller` y `require_course_editor`
para saber quién hace la petición. Aquí se prueban con una aplicación mínima,
mandando la cabecera Authorization como lo haría la app.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from user_management_service.auth import (
    Caller,
    current_caller,
    require_course_editor,
)
from user_management_service.core.security import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    decode_access_token,
)

app = FastAPI()


@app.get("/whoami")
def whoami(caller: Caller = Depends(current_caller)):
    return {"email": caller.email, "role": caller.role, "user_id": caller.user_id}


@app.get("/course")
def edit_course(caller: Caller = Depends(require_course_editor)):
    return {"editor": caller.email}


client = TestClient(app)


def _bearer(claims: dict, **kwargs) -> dict:
    return {"Authorization": f"Bearer {create_access_token(claims, **kwargs)}"}


def test_the_caller_comes_from_the_signed_token():
    response = client.get(
        "/whoami",
        headers=_bearer({"sub": "7", "email": "ana@example.com", "rol": "Estudiante"}),
    )

    assert response.status_code == 200
    # El rol se pasa a minúsculas para compararlo sin sorpresas.
    assert response.json() == {"email": "ana@example.com", "role": "estudiante", "user_id": 7}


def test_the_role_can_also_travel_as_role():
    response = client.get(
        "/whoami", headers=_bearer({"sub": "7", "email": "ana@example.com", "role": "DOCENTE"})
    )

    assert response.json()["role"] == "docente"


def test_a_token_without_id_still_identifies_by_email():
    response = client.get("/whoami", headers=_bearer({"email": "ana@example.com"}))

    assert response.status_code == 200
    assert response.json() == {"email": "ana@example.com", "role": "", "user_id": None}


def test_an_id_that_is_not_a_number_is_ignored():
    response = client.get(
        "/whoami", headers=_bearer({"sub": "no-es-un-numero", "email": "ana@example.com"})
    )

    assert response.status_code == 200
    assert response.json()["user_id"] is None


def test_without_a_token_the_answer_is_401_in_spanish():
    response = client.get("/whoami")

    assert response.status_code == 401
    assert response.json()["detail"] == "Falta la sesión. Vuelve a iniciar sesión."
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_forged_token_is_rejected():
    # Firmado con otra clave: el cliente no puede fabricarse un rol.
    forged = jwt.encode(
        {"sub": "1", "email": "ana@example.com", "rol": "director"},
        "otra-clave-que-no-es-la-del-servidor",
        algorithm=ALGORITHM,
    )

    response = client.get("/whoami", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401
    assert "caducó o no es válida" in response.json()["detail"]
    assert response.headers["www-authenticate"] == "Bearer"


def test_an_expired_token_is_rejected():
    response = client.get(
        "/whoami",
        headers=_bearer({"sub": "7", "email": "ana@example.com"}, expires_delta=timedelta(minutes=-1)),
    )

    assert response.status_code == 401
    assert "caducó" in response.json()["detail"]


def test_a_token_that_names_nobody_is_rejected():
    response = client.get("/whoami", headers=_bearer({"sub": "7", "rol": "docente"}))

    assert response.status_code == 401
    assert response.json()["detail"] == "La sesión no identifica a nadie."


@pytest.mark.parametrize("rol", ["docente", "director", "Director"])
def test_teachers_and_directors_can_edit_the_course(rol):
    response = client.get("/course", headers=_bearer({"sub": "1", "email": "d@example.com", "rol": rol}))

    assert response.status_code == 200
    assert response.json() == {"editor": "d@example.com"}


@pytest.mark.parametrize("rol", ["estudiante", "", "administrador"])
def test_anyone_else_cannot_edit_the_course(rol):
    response = client.get("/course", headers=_bearer({"sub": "1", "email": "e@example.com", "rol": rol}))

    assert response.status_code == 403
    assert response.json()["detail"] == "Solo un docente puede editar el contenido del curso."


def test_editing_the_course_without_a_session_is_401_not_403():
    response = client.get("/course")

    assert response.status_code == 401


def test_caller_knows_who_can_edit_the_course():
    assert Caller("d@example.com", "docente").can_edit_course
    assert Caller("d@example.com", "director", user_id=1).can_edit_course
    assert not Caller("e@example.com", "estudiante").can_edit_course


# --- El token ----------------------------------------------------------------


def test_a_token_lasts_what_is_asked_for():
    before = datetime.now(timezone.utc)

    token = create_access_token({"sub": "1"}, expires_delta=timedelta(minutes=5))

    exp = datetime.fromtimestamp(decode_access_token(token)["exp"], tz=timezone.utc)
    assert before + timedelta(minutes=4) < exp <= before + timedelta(minutes=5, seconds=1)


def test_creating_a_token_does_not_change_the_data_passed_in():
    data = {"sub": "1", "email": "ana@example.com"}

    create_access_token(data)

    assert data == {"sub": "1", "email": "ana@example.com"}


def test_decoding_garbage_raises_value_error():
    with pytest.raises(ValueError, match="Token inválido"):
        decode_access_token("esto-no-es-un-token")


def test_a_token_is_signed_with_the_server_key():
    token = create_access_token({"sub": "1"})

    assert jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sub"] == "1"
