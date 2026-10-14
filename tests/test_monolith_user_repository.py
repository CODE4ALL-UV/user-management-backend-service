"""El repositorio de usuarios del monolito (app/) contra una base de verdad.

Se usa la SQLite temporal de las pruebas, con las tablas que crea el
monolito al arrancar: así se ve que las consultas encuentran lo que deben,
que los cambios quedan guardados y que los agregados de rendimiento cuadran.
"""

from datetime import date

import pytest

from monolith import load_main

load_main()

from domain.repositories.user_repository import UserRepository  # noqa: E402
from infrastructure.database.models import (  # noqa: E402
    StudentPerformance,
    TipoDiscapacidad,
    Usuario,
)
from infrastructure.database.user_repository_impl import UserRepositoryImpl  # noqa: E402


@pytest.fixture
def repo(db_session):
    """El repositorio sobre la sesión de pruebas; al final borra el rendimiento."""
    yield UserRepositoryImpl(db_session)
    db_session.rollback()
    db_session.query(StudentPerformance).delete()
    db_session.commit()


def _ana(repo, **extra):
    data = {"nombre": "Ana", "correo": "ana@example.com", "password": "hash-de-prueba"}
    data.update(extra)
    return repo.create_user(data)


def test_create_user_saves_the_row_and_fills_the_defaults(repo, db_session):
    user = _ana(repo)

    assert user.id_usuario is not None
    assert user.rol == "estudiante"
    assert user.fecha_registro is not None
    assert user.foto_path is None
    assert db_session.query(Usuario).filter_by(correo="ana@example.com").count() == 1


def test_users_are_found_by_exact_email_and_by_id(repo):
    ana = _ana(repo)

    assert repo.get_user_by_email("ana@example.com").id_usuario == ana.id_usuario
    assert repo.get_user_by_id(ana.id_usuario).correo == "ana@example.com"
    assert repo.get_user_by_email("ANA@example.com") is None
    assert repo.get_user_by_email("nadie@example.com") is None
    assert repo.get_user_by_id(ana.id_usuario + 1000) is None


def test_list_students_leaves_out_teachers_and_directors(repo):
    ana = _ana(repo)
    luis = _ana(repo, correo="luis@example.com", nombre="Luis")
    _ana(repo, correo="profe@example.com", rol="docente")
    _ana(repo, correo="direccion@example.com", rol="director")

    students = repo.list_students()

    emails = {s.correo for s in students}
    assert {ana.correo, luis.correo} <= emails
    assert not emails & {"profe@example.com", "direccion@example.com"}
    assert {s.rol for s in students} == {"estudiante"}


def test_disability_types_are_looked_up_by_id(repo, db_session):
    db_session.add(TipoDiscapacidad(id_tipo=3, nombre="Auditiva"))
    db_session.commit()

    assert repo.get_tipo_discapacidad_by_id(3).nombre == "Auditiva"
    assert repo.get_tipo_discapacidad_by_id(99) is None


def test_update_photo_path_stores_the_new_path(repo, db_session):
    ana = _ana(repo)

    updated = repo.update_photo_path(ana.id_usuario, "/uploads/ana.png")

    assert updated.foto_path == "/uploads/ana.png"
    db_session.expire_all()
    assert repo.get_user_by_id(ana.id_usuario).foto_path == "/uploads/ana.png"


def test_update_photo_path_of_a_missing_user_fails(repo):
    with pytest.raises(ValueError, match="Usuario no encontrado"):
        repo.update_photo_path(12345, "/uploads/nadie.png")


# --- Rendimiento ----------------------------------------------------------------


def _performance(repo, usuario_id, lesson, created_at, **scores):
    return repo.create_performance(
        {"usuario_id": usuario_id, "lesson_name": lesson, "created_at": created_at, **scores}
    )


def test_create_performance_saves_the_row_with_zero_defaults(repo):
    ana = _ana(repo)

    saved = repo.create_performance({"usuario_id": ana.id_usuario, "lesson_name": "Tipos (repo)"})

    assert saved.id is not None
    assert (saved.score, saved.failed, saved.good, saved.excellent) == (0, 0, 0, 0)
    assert saved.created_at is not None


def test_performances_come_newest_first_and_can_be_filtered_by_student(repo):
    ana = _ana(repo)
    luis = _ana(repo, correo="luis@example.com")
    old = _performance(repo, ana.id_usuario, "Tipos (repo)", date(2026, 1, 1))
    new = _performance(repo, ana.id_usuario, "Tipos (repo)", date(2026, 5, 1))
    middle = _performance(repo, luis.id_usuario, "Tipos (repo)", date(2026, 3, 1))

    mine = {old.id, new.id, middle.id}
    ordered = [p.id for p in repo.get_all_performances() if p.id in mine]

    assert ordered == [new.id, middle.id, old.id]
    assert {p.id for p in repo.get_performances_by_student(ana.id_usuario)} == {old.id, new.id}
    assert [p.id for p in repo.get_performances_by_student(luis.id_usuario)] == [middle.id]


def test_aggregates_add_up_and_average_each_lesson(repo):
    ana = _ana(repo)
    luis = _ana(repo, correo="luis@example.com")
    _performance(repo, ana.id_usuario, "Tipos (repo)", date(2026, 1, 1), score=9, failed=1, good=4, excellent=2)
    _performance(repo, ana.id_usuario, "Tipos (repo)", date(2026, 1, 2), score=3, failed=3, good=0, excellent=0)
    _performance(repo, luis.id_usuario, "Tipos (repo)", date(2026, 1, 3), score=6, failed=2, good=2, excellent=1)
    _performance(repo, None, "Funciones (repo)", date(2026, 1, 4), score=4)

    sums = {row["lesson_name"]: row for row in repo.aggregate_by_lesson()}
    averages = {row["lesson_name"]: row for row in repo.aggregate_avg_by_lesson()}

    assert sums["Tipos (repo)"] == {
        "lesson_name": "Tipos (repo)", "score": 18, "failed": 6, "good": 6, "excellent": 3,
    }
    assert averages["Tipos (repo)"] == {
        "lesson_name": "Tipos (repo)", "avg_score": 6.0, "avg_failed": 2.0, "avg_good": 2.0,
        "avg_excellent": 1.0, "records": 3, "students": 2,
    }
    # Un registro sin estudiante cuenta como registro, pero no como estudiante.
    assert averages["Funciones (repo)"]["records"] == 1
    assert averages["Funciones (repo)"]["students"] == 0
    assert sums["Funciones (repo)"]["score"] == 4


def test_with_no_performances_the_aggregates_are_empty(repo, db_session):
    db_session.query(StudentPerformance).delete()
    db_session.commit()

    assert repo.aggregate_by_lesson() == []
    assert repo.aggregate_avg_by_lesson() == []
    assert repo.get_all_performances() == []


# --- El contrato ------------------------------------------------------------------


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


def test_the_repository_contract_cannot_be_used_on_its_own():
    with pytest.raises(TypeError):
        UserRepository()


def test_the_contract_lists_the_methods_the_use_cases_need():
    assert UserRepository.__abstractmethods__ == {
        "get_user_by_email",
        "get_user_by_id",
        "get_tipo_discapacidad_by_id",
        "create_user",
        "update_photo_path",
    }
    assert issubclass(UserRepositoryImpl, UserRepository)


def test_the_repository_contract_methods_return_nothing():
    repo = _ContractOnly()

    assert repo.get_user_by_email("ana@example.com") is None
    assert repo.get_user_by_id(1) is None
    assert repo.get_tipo_discapacidad_by_id(1) is None
    assert repo.create_user({}) is None
    assert repo.update_photo_path(1, "/uploads/x.png") is None
