"""El repositorio de usuarios contra una base de verdad.

Se prueba con la SQLite temporal de las pruebas, con las mismas tablas que
crea el servicio al arrancar: así se ve que las consultas encuentran lo que
deben y que los cambios quedan guardados.
"""

import pytest

from neon_storage.models import TipoDiscapacidad, Usuario
from user_management_service.domain.repositories.user_repository import UserRepository
from user_management_service.infrastructure.database.user_repository_impl import (
    UserRepositoryImpl,
)


def _ana(repo, **extra):
    data = {"nombre": "Ana", "correo": "Ana@example.com", "password": "hash-de-prueba"}
    data.update(extra)
    return repo.create_user(data)


def test_create_user_saves_the_row_and_fills_the_defaults(db_session):
    repo = UserRepositoryImpl(db_session)

    user = _ana(repo)

    assert user.id_usuario is not None
    # La base pone el rol y la fecha de registro si no se mandan.
    assert user.rol == "estudiante"
    assert user.fecha_registro is not None
    assert db_session.query(Usuario).count() == 1


def test_users_are_found_by_email_and_by_id(db_session):
    repo = UserRepositoryImpl(db_session)
    ana = _ana(repo)

    assert repo.get_user_by_email("Ana@example.com").id_usuario == ana.id_usuario
    assert repo.get_user_by_id(ana.id_usuario).correo == "Ana@example.com"
    assert repo.get_user_by_email("nadie@example.com") is None
    assert repo.get_user_by_id(ana.id_usuario + 1000) is None


def test_the_email_search_ignores_capitals_and_spaces(db_session):
    repo = UserRepositoryImpl(db_session)
    ana = _ana(repo)

    assert repo.get_user_by_email("ana@example.com").id_usuario == ana.id_usuario
    assert repo.get_user_by_email("  ANA@EXAMPLE.COM ").id_usuario == ana.id_usuario
    assert repo.get_user_by_email("otra@example.com") is None


def test_the_email_search_prefers_the_exact_match(db_session):
    # Cuentas de antes que solo cambian en mayúsculas: cada una sigue
    # entrando con su correo tal como lo escribió.
    repo = UserRepositoryImpl(db_session)
    upper = _ana(repo)
    lower = _ana(repo, correo="ana@example.com", nombre="Ana minúsculas")

    assert repo.get_user_by_email("ana@example.com").id_usuario == lower.id_usuario
    assert repo.get_user_by_email("Ana@example.com").id_usuario == upper.id_usuario


def test_without_an_exact_match_the_oldest_account_wins(db_session):
    repo = UserRepositoryImpl(db_session)
    lower = _ana(repo, correo="ana@example.com")
    _ana(repo, correo="ANA@example.com")

    assert repo.get_user_by_email("Ana@Example.com").id_usuario == lower.id_usuario


def test_disability_types_are_looked_up_by_id(db_session):
    db_session.add(TipoDiscapacidad(id_tipo=1, nombre="Visual"))
    db_session.commit()
    repo = UserRepositoryImpl(db_session)

    assert repo.get_tipo_discapacidad_by_id(1).nombre == "Visual"
    assert repo.get_tipo_discapacidad_by_id(99) is None


def test_update_password_stores_the_new_hash(db_session):
    repo = UserRepositoryImpl(db_session)
    ana = _ana(repo)

    updated = repo.update_password(ana.id_usuario, "hash-nuevo")

    assert updated.password == "hash-nuevo"
    db_session.expire_all()
    assert repo.get_user_by_id(ana.id_usuario).password == "hash-nuevo"


def test_update_password_of_a_missing_user_fails(db_session):
    repo = UserRepositoryImpl(db_session)

    with pytest.raises(ValueError, match="Usuario no encontrado"):
        repo.update_password(12345, "hash-nuevo")


def test_update_photo_path_stores_the_new_path(db_session):
    repo = UserRepositoryImpl(db_session)
    ana = _ana(repo)

    updated = repo.update_photo_path(ana.id_usuario, "/uploads/ana.png")

    assert updated.foto_path == "/uploads/ana.png"
    db_session.expire_all()
    assert repo.get_user_by_id(ana.id_usuario).foto_path == "/uploads/ana.png"


def test_update_photo_path_of_a_missing_user_fails(db_session):
    repo = UserRepositoryImpl(db_session)

    with pytest.raises(ValueError, match="Usuario no encontrado"):
        repo.update_photo_path(12345, "/uploads/nadie.png")


# --- El contrato -------------------------------------------------------------


class _ContractOnly(UserRepository):
    """Implementa cada método pasando al del contrato, que no hace nada."""

    def get_user_by_email(self, email):
        return super().get_user_by_email(email)

    def get_user_by_id(self, user_id):
        return super().get_user_by_id(user_id)

    def get_tipo_discapacidad_by_id(self, tipo_id):
        return super().get_tipo_discapacidad_by_id(tipo_id)

    def create_user(self, user_data):
        return super().create_user(user_data)

    def update_photo_path(self, user_id, photo_path):
        return super().update_photo_path(user_id, photo_path)

    def update_password(self, user_id, password_hash):
        return super().update_password(user_id, password_hash)


def test_the_repository_contract_cannot_be_used_on_its_own():
    with pytest.raises(TypeError):
        UserRepository()


def test_the_repository_contract_methods_return_nothing():
    repo = _ContractOnly()

    assert repo.get_user_by_email("ana@example.com") is None
    assert repo.get_user_by_id(1) is None
    assert repo.get_tipo_discapacidad_by_id(1) is None
    assert repo.create_user({}) is None
    assert repo.update_photo_path(1, "/uploads/x.png") is None
    assert repo.update_password(1, "hash") is None
