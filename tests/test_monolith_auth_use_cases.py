"""Los casos de uso de registro e inicio de sesión del monolito (app/).

Se prueban solos, con un repositorio de mentira, para ver las reglas sin
pasar por HTTP: el correo repetido, la contraseña que nunca se guarda en
claro, el rol que se normaliza y el token que lleva quién es cada uno.
"""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from monolith import load_main

load_main()

from application.use_cases.create_user import CreateUserUseCase  # noqa: E402
from application.use_cases.login_user import LoginUserUseCase  # noqa: E402
from core.security import (  # noqa: E402
    decode_access_token,
    get_password_hash,
    verify_password,
)

PASSWORD_HASH = get_password_hash("clave-correcta")


class FakeRepo:
    """Una base en memoria con los usuarios que se le den."""

    def __init__(self, *users, disability_types=()):
        self.users = {user.correo: user for user in users}
        self.disability_types = set(disability_types)
        self.created = []

    def get_user_by_email(self, email):
        return self.users.get(email)

    def get_tipo_discapacidad_by_id(self, tipo_id):
        return SimpleNamespace(id_tipo=tipo_id) if tipo_id in self.disability_types else None

    def create_user(self, data):
        self.created.append(data)
        return SimpleNamespace(id_usuario=len(self.created), fecha_registro=date(2026, 10, 14), **data)


def _signup(**extra):
    data = dict(nombre="Ana", correo="ana@x.co", password="clave-segura", tipo_discapacidad=None)
    data.update(extra)
    return SimpleNamespace(**data)


def _user(**extra):
    data = dict(id_usuario=5, correo="ana@x.co", nombre="Ana", rol="docente", password=PASSWORD_HASH)
    data.update(extra)
    return SimpleNamespace(**data)


# --- Registro -------------------------------------------------------------------


def test_creating_a_user_saves_a_hash_and_returns_no_password():
    repo = FakeRepo()

    result = CreateUserUseCase(repo).execute(_signup())

    [saved] = repo.created
    assert saved["password"] != "clave-segura"
    assert verify_password("clave-segura", saved["password"])
    assert result == {
        "id_usuario": 1,
        "nombre": "Ana",
        "correo": "ana@x.co",
        "tipo_discapacidad": None,
        "fecha_registro": "2026-10-14",
        "rol": "estudiante",
    }


def test_a_repeated_email_is_refused_without_saving():
    repo = FakeRepo(_user())

    with pytest.raises(ValueError, match="ya se encuentra registrado"):
        CreateUserUseCase(repo).execute(_signup())

    assert repo.created == []


def test_the_disability_type_is_kept_only_if_it_exists():
    repo = FakeRepo(disability_types={2})

    known = CreateUserUseCase(repo).execute(_signup(correo="a@x.co", tipo_discapacidad=2))
    unknown = CreateUserUseCase(repo).execute(_signup(correo="b@x.co", tipo_discapacidad=7))

    assert known["tipo_discapacidad"] == 2
    assert unknown["tipo_discapacidad"] is None


@pytest.mark.parametrize(
    "rol, expected",
    [
        (None, "estudiante"),
        ("estudiante", "estudiante"),
        (" Docente ", "docente"),
        ("DIRECTOR", "director"),
        ("superusuario", "estudiante"),
    ],
)
def test_the_role_is_normalised_and_unknown_roles_become_student(rol, expected):
    repo = FakeRepo()

    result = CreateUserUseCase(repo).execute(_signup(rol=rol))

    assert result["rol"] == expected
    assert repo.created[0]["rol"] == expected


def test_a_signup_without_a_role_attribute_is_a_student():
    # El registro con Google arma su propio objeto; si no trae rol, estudiante.
    data = SimpleNamespace(nombre="Ana", correo="ana@x.co", password="x", tipo_discapacidad=None)

    assert CreateUserUseCase(FakeRepo()).execute(data)["rol"] == "estudiante"


# --- Inicio de sesión -----------------------------------------------------------


def test_the_right_password_returns_a_token_with_id_email_and_role():
    result = LoginUserUseCase(FakeRepo(_user())).execute("ana@x.co", "clave-correcta")

    assert result["token_type"] == "bearer"
    assert (result["user_id"], result["email"], result["nombre"], result["rol"]) == (
        5,
        "ana@x.co",
        "Ana",
        "docente",
    )
    payload = decode_access_token(result["access_token"])
    assert (payload["sub"], payload["email"], payload["rol"]) == ("5", "ana@x.co", "docente")


@pytest.mark.parametrize("email, password", [("ana@x.co", "otra"), ("nadie@x.co", "clave-correcta")])
def test_a_wrong_password_and_an_unknown_email_fail_the_same_way(email, password):
    with pytest.raises(HTTPException) as error:
        LoginUserUseCase(FakeRepo(_user())).execute(email, password)

    assert error.value.status_code == 401
    assert error.value.detail == "El correo o la contraseña son incorrectos."


@pytest.mark.parametrize(
    "extra, expected",
    [
        ({"foto_path": "/uploads/a.png"}, "/uploads/a.png"),
        # Algunos objetos antiguos llaman photo_path a la foto.
        ({"foto_path": None, "photo_path": "/uploads/b.png"}, "/uploads/b.png"),
        ({"foto_path": ""}, ""),
        ({}, ""),
    ],
)
def test_the_photo_url_comes_from_whichever_field_has_it(extra, expected):
    result = LoginUserUseCase(FakeRepo(_user(**extra))).execute("ana@x.co", "clave-correcta")

    assert result["photo_url"] == expected
