"""Registrar una cuenta nueva.

Se comprueba qué se guarda: la contraseña cifrada y nunca en claro, un rol
que exista y un tipo de discapacidad solo si está en la base.
"""

from types import SimpleNamespace

import pytest

from user_management_service.application.use_cases.create_user import CreateUserUseCase
from user_management_service.core.security import verify_password


class FakeUserRepository:
    def __init__(self, existing_emails=(), tipos=()):
        self.created_user = None
        self.existing_emails = set(existing_emails)
        self.tipos = set(tipos)

    def get_user_by_email(self, email: str):
        if email in self.existing_emails:
            return SimpleNamespace(correo=email)
        return None

    def get_tipo_discapacidad_by_id(self, tipo_id: int):
        if tipo_id in self.tipos:
            return SimpleNamespace(id_tipo=tipo_id)
        return None

    def create_user(self, user_data: dict):
        self.created_user = user_data
        return SimpleNamespace(
            id_usuario=1,
            nombre=user_data["nombre"],
            correo=user_data["correo"],
            tipo_discapacidad=user_data.get("tipo_discapacidad"),
            fecha_registro=None,
            rol=user_data.get("rol", "estudiante"),
        )


def _payload(**extra):
    data = dict(
        nombre="Ana",
        correo="ana@example.com",
        password="123456",
        tipo_discapacidad=None,
        rol=None,
    )
    data.update(extra)
    return SimpleNamespace(**data)


def test_create_user_assigns_role_and_saves_it():
    repository = FakeUserRepository()
    use_case = CreateUserUseCase(user_repository=repository)

    user_payload = SimpleNamespace(
        nombre="Ana",
        correo="ana@example.com",
        password="123456",
        tipo_discapacidad=None,
        rol="docente",
    )

    result = use_case.execute(user_payload)

    assert result["rol"] == "docente"
    assert repository.created_user["rol"] == "docente"


def test_the_password_is_saved_hashed_and_not_returned():
    repository = FakeUserRepository()

    result = CreateUserUseCase(repository).execute(_payload(password="clave-secreta"))

    saved = repository.created_user["password"]
    assert saved != "clave-secreta"
    assert verify_password("clave-secreta", saved)
    assert "password" not in result


def test_an_email_already_registered_is_rejected():
    repository = FakeUserRepository(existing_emails={"ana@example.com"})

    with pytest.raises(ValueError, match="ya se encuentra registrado"):
        CreateUserUseCase(repository).execute(_payload())

    assert repository.created_user is None


@pytest.mark.parametrize(
    "rol, saved",
    [
        (None, "estudiante"),
        ("  DIRECTOR ", "director"),
        ("administrador", "estudiante"),
        ("", "estudiante"),
    ],
)
def test_the_role_is_normalized_and_unknown_roles_become_student(rol, saved):
    repository = FakeUserRepository()

    result = CreateUserUseCase(repository).execute(_payload(rol=rol))

    assert repository.created_user["rol"] == saved
    assert result["rol"] == saved


def test_a_payload_without_role_registers_a_student():
    repository = FakeUserRepository()
    payload = _payload()
    del payload.rol

    CreateUserUseCase(repository).execute(payload)

    assert repository.created_user["rol"] == "estudiante"


def test_an_existing_disability_type_is_kept():
    repository = FakeUserRepository(tipos={2})

    result = CreateUserUseCase(repository).execute(_payload(tipo_discapacidad=2))

    assert repository.created_user["tipo_discapacidad"] == 2
    assert result["tipo_discapacidad"] == 2


def test_an_unknown_disability_type_is_dropped_instead_of_failing():
    repository = FakeUserRepository(tipos={2})

    result = CreateUserUseCase(repository).execute(_payload(tipo_discapacidad=99))

    assert repository.created_user["tipo_discapacidad"] is None
    assert result["tipo_discapacidad"] is None
