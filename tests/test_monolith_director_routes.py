"""El panel de la dirección en el monolito (app/): estudiantes y rendimiento.

Estas rutas enseñan datos de todos los estudiantes, así que lo primero es
que solo entre quien es director según la base de datos, no según lo que
diga el cliente. Después, que los listados y los promedios cuadren con lo
guardado. Todo contra la SQLite temporal.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from monolith import load_main

main = load_main()

from core.security import create_access_token  # noqa: E402
from infrastructure.database.models import StudentPerformance, Usuario  # noqa: E402

client = TestClient(main.app)

ENDPOINTS = [
    ("get", "/api/director/students"),
    ("get", "/api/director/performances"),
    ("get", "/api/director/performances/aggregate"),
    ("get", "/api/director/performances/average"),
    ("post", "/api/director/performances"),
]


@pytest.fixture
def db(db_session):
    """La sesión de pruebas, borrando al final el rendimiento que se guardó."""
    yield db_session
    db_session.rollback()
    db_session.query(StudentPerformance).delete()
    db_session.commit()


def _add_user(db, correo, rol="estudiante", **extra):
    user = Usuario(nombre=correo.split("@")[0], correo=correo, password="hash", rol=rol, **extra)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _headers_for(user):
    token = create_access_token(data={"sub": str(user.id_usuario), "email": user.correo, "rol": user.rol})
    return {"Authorization": f"Bearer {token}"}


def _call(method, path, headers=None):
    if method == "post":
        return client.post(path, json={"lesson_name": "Lección permisos"}, headers=headers or {})
    return client.get(path, headers=headers or {})


@pytest.fixture
def director(db):
    return _add_user(db, "direccion@univalle.edu.co", rol="director")


# --- Quién puede entrar --------------------------------------------------------


@pytest.mark.parametrize("method, path", ENDPOINTS)
def test_without_a_token_every_director_route_is_a_401(db, method, path):
    response = _call(method, path)

    assert response.status_code == 401
    assert response.json()["detail"] == "Falta token de autorización"


@pytest.mark.parametrize("method, path", ENDPOINTS)
@pytest.mark.parametrize("rol", ["estudiante", "docente"])
def test_students_and_teachers_cannot_use_the_director_routes(db, method, path, rol):
    user = _add_user(db, f"{rol}@univalle.edu.co", rol=rol)

    response = _call(method, path, _headers_for(user))

    assert response.status_code == 403
    assert response.json()["detail"] == "Requiere rol director"
    assert db.query(StudentPerformance).count() == 0


def test_the_role_is_read_from_the_database_not_from_the_token(db):
    # Un estudiante con un token que dice «director» sigue siendo estudiante.
    student = _add_user(db, "listo@univalle.edu.co")
    token = create_access_token(
        data={"sub": str(student.id_usuario), "email": student.correo, "rol": "director"}
    )

    response = client.get("/api/director/students", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_a_director_token_of_a_deleted_account_is_refused(db, director):
    headers = _headers_for(director)
    db.delete(director)
    db.commit()

    response = client.get("/api/director/students", headers=headers)

    assert response.status_code == 403


def test_an_invalid_token_is_a_401(db):
    response = client.get(
        "/api/director/students", headers={"Authorization": "Bearer no-es-un-jwt"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token inválido"


def test_a_token_without_a_user_id_is_a_401(db):
    token = create_access_token(data={"email": "direccion@univalle.edu.co", "rol": "director"})

    response = client.get(
        "/api/director/students", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token sin usuario"


def test_the_token_is_also_accepted_without_the_bearer_word(db, director):
    # Solo se mira la última palabra de la cabecera.
    token = _headers_for(director)["Authorization"].split(" ")[-1]

    response = client.get("/api/director/students", headers={"Authorization": token})

    assert response.status_code == 200


# --- Lo que ve la dirección ----------------------------------------------------


def test_the_director_sees_only_the_students(db, director):
    ana = _add_user(db, "ana@univalle.edu.co", foto_path="/uploads/ana.png")
    luis = _add_user(db, "luis@univalle.edu.co")
    teacher = _add_user(db, "profe@univalle.edu.co", rol="docente")

    response = client.get("/api/director/students", headers=_headers_for(director))

    assert response.status_code == 200
    students = {s["correo"]: s for s in response.json()}
    assert students["ana@univalle.edu.co"] == {
        "id_usuario": ana.id_usuario,
        "nombre": "ana",
        "correo": "ana@univalle.edu.co",
        "foto_path": "/uploads/ana.png",
    }
    assert students["luis@univalle.edu.co"]["id_usuario"] == luis.id_usuario
    assert students["luis@univalle.edu.co"]["foto_path"] is None
    assert teacher.correo not in students
    assert director.correo not in students
    # Todo lo listado es, según la base, un estudiante.
    listed_ids = [s["id_usuario"] for s in response.json()]
    roles = {u.rol for u in db.query(Usuario).filter(Usuario.id_usuario.in_(listed_ids))}
    assert roles == {"estudiante"}


def test_the_director_records_a_performance(db, director):
    student = _add_user(db, "ana@univalle.edu.co")

    response = client.post(
        "/api/director/performances",
        json={"usuario_id": student.id_usuario, "lesson_name": "Lección guardada", "score": 8, "good": 2},
        headers=_headers_for(director),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["lesson_name"] == "Lección guardada"
    db.expire_all()
    saved = db.get(StudentPerformance, body["id"])
    assert (saved.usuario_id, saved.score, saved.good, saved.failed, saved.excellent) == (
        student.id_usuario,
        8,
        2,
        0,
        0,
    )


def test_a_performance_needs_a_lesson_name(db, director):
    response = client.post(
        "/api/director/performances", json={"score": 3}, headers=_headers_for(director)
    )

    assert response.status_code == 422
    assert db.query(StudentPerformance).count() == 0


def _seed_performances(db, ana, luis):
    # (estudiante, lección, score, failed, good, excellent, fecha)
    seed = [
        (ana, "Variables (dirección)", 10, 1, 2, 3, date(2026, 3, 1)),
        (ana, "Variables (dirección)", 4, 3, 0, 1, date(2026, 3, 5)),
        (luis, "Variables (dirección)", 7, 2, 1, 2, date(2026, 3, 3)),
        (luis, "Bucles (dirección)", 5, 0, 0, 0, date(2026, 2, 1)),
    ]
    db.add_all(
        StudentPerformance(
            usuario_id=user.id_usuario, lesson_name=lesson, score=score, failed=failed,
            good=good, excellent=excellent, created_at=created_at,
        )
        for user, lesson, score, failed, good, excellent, created_at in seed
    )
    db.commit()


def test_performances_are_listed_newest_first(db, director):
    ana = _add_user(db, "ana@univalle.edu.co")
    luis = _add_user(db, "luis@univalle.edu.co")
    _seed_performances(db, ana, luis)

    response = client.get("/api/director/performances", headers=_headers_for(director))

    assert response.status_code == 200
    mine = [r for r in response.json() if r["usuario_id"] in (ana.id_usuario, luis.id_usuario)]
    assert [r["created_at"] for r in mine] == ["2026-03-05", "2026-03-03", "2026-03-01", "2026-02-01"]
    assert mine[0] == {
        "id": mine[0]["id"],
        "usuario_id": ana.id_usuario,
        "lesson_name": "Variables (dirección)",
        "score": 4,
        "failed": 3,
        "good": 0,
        "excellent": 1,
        "created_at": "2026-03-05",
    }


def test_the_aggregate_adds_up_each_lesson(db, director):
    ana = _add_user(db, "ana@univalle.edu.co")
    luis = _add_user(db, "luis@univalle.edu.co")
    _seed_performances(db, ana, luis)

    response = client.get("/api/director/performances/aggregate", headers=_headers_for(director))

    assert response.status_code == 200
    by_lesson = {r["lesson_name"]: r for r in response.json()}
    assert by_lesson["Variables (dirección)"] == {
        "lesson_name": "Variables (dirección)", "score": 21, "failed": 6, "good": 3, "excellent": 6,
    }
    assert by_lesson["Bucles (dirección)"] == {
        "lesson_name": "Bucles (dirección)", "score": 5, "failed": 0, "good": 0, "excellent": 0,
    }


def test_the_average_counts_records_and_distinct_students(db, director):
    ana = _add_user(db, "ana@univalle.edu.co")
    luis = _add_user(db, "luis@univalle.edu.co")
    _seed_performances(db, ana, luis)

    response = client.get("/api/director/performances/average", headers=_headers_for(director))

    assert response.status_code == 200
    by_lesson = {r["lesson_name"]: r for r in response.json()}
    lesson_a = by_lesson["Variables (dirección)"]
    assert lesson_a["avg_score"] == pytest.approx(7.0)
    assert lesson_a["avg_failed"] == pytest.approx(2.0)
    assert lesson_a["avg_good"] == pytest.approx(1.0)
    assert lesson_a["avg_excellent"] == pytest.approx(2.0)
    # Tres registros, pero de dos estudiantes.
    assert (lesson_a["records"], lesson_a["students"]) == (3, 2)
    assert by_lesson["Bucles (dirección)"] == {
        "lesson_name": "Bucles (dirección)", "avg_score": 5.0, "avg_failed": 0.0, "avg_good": 0.0,
        "avg_excellent": 0.0, "records": 1, "students": 1,
    }
