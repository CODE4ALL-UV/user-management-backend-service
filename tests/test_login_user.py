"""Iniciar sesión con correo y contraseña.

Lo que importa: que una contraseña mal escrita o un correo desconocido no
abran nada, y que el token que se entrega lleve quién es y con qué rol.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from user_management_service.application.use_cases.login_user import LoginUserUseCase
from user_management_service.core.security import decode_access_token, get_password_hash

PASSWORD_HASH = get_password_hash("clave-correcta")


class FakeRepo:
    def __init__(self, user=None):
        self.user = user

    def get_user_by_email(self, email):
        if self.user is not None and email == self.user.correo:
            return self.user
        return None


def _laura(**extra):
    data = dict(
        id_usuario=5,
        correo="laura@univalle.edu.co",
        nombre="Laura",
        rol="docente",
        password=PASSWORD_HASH,
    )
    data.update(extra)
    return SimpleNamespace(**data)


def test_the_right_password_opens_a_session_with_the_role():
    result = LoginUserUseCase(FakeRepo(_laura(foto_path="/uploads/laura.png"))).execute(
        "laura@univalle.edu.co", "clave-correcta"
    )

    assert result["token_type"] == "bearer"
    assert result["user_id"] == 5
    assert result["email"] == "laura@univalle.edu.co"
    assert result["nombre"] == "Laura"
    assert result["rol"] == "docente"
    assert result["photo_url"] == "/uploads/laura.png"

    claims = decode_access_token(result["access_token"])
    assert claims["sub"] == "5"
    assert claims["email"] == "laura@univalle.edu.co"
    assert claims["rol"] == "docente"


def test_an_unknown_email_gets_the_same_answer_as_a_wrong_password():
    # Si la respuesta cambiara, se podría saber quién está registrado.
    use_case = LoginUserUseCase(FakeRepo(_laura()))

    with pytest.raises(HTTPException) as unknown:
        use_case.execute("nadie@univalle.edu.co", "clave-correcta")
    with pytest.raises(HTTPException) as wrong:
        use_case.execute("laura@univalle.edu.co", "clave-equivocada")

    assert unknown.value.status_code == wrong.value.status_code == 401
    assert unknown.value.detail == wrong.value.detail


def test_the_photo_can_come_from_the_old_photo_path_field():
    result = LoginUserUseCase(FakeRepo(_laura(photo_path="/uploads/vieja.png"))).execute(
        "laura@univalle.edu.co", "clave-correcta"
    )

    assert result["photo_url"] == "/uploads/vieja.png"


def test_without_a_photo_the_url_is_empty():
    result = LoginUserUseCase(FakeRepo(_laura(foto_path=None))).execute(
        "laura@univalle.edu.co", "clave-correcta"
    )

    assert result["photo_url"] == ""
