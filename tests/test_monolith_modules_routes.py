"""El nombre y los temas de cada módulo en el monolito.

Ya no hay archivos JSON: el módulo vive en la misma fila de CourseOverride
(`scope='module'`) que usa /api/course/overrides, así que editar por un
camino o por el otro da lo mismo. Leer es público; escribir, de docentes.
"""

import json
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from monolith import load_main

main = load_main()

import core.security as mono_security  # noqa: E402  Mismo módulo que usa el monolito.
from infrastructure.database.models import CourseOverride  # noqa: E402

client = TestClient(main.app)


def _wipe(db):
    db.query(CourseOverride).delete()
    db.commit()


@pytest.fixture(autouse=True)
def _clean_tables(db_session):
    """Cada prueba empieza y termina sin módulos editados."""
    _wipe(db_session)
    yield
    db_session.rollback()
    _wipe(db_session)


def _auth(rol):
    """Cabecera con una sesión del rol pedido. Estas rutas no buscan al usuario."""
    email = f"{rol}-{uuid.uuid4().hex[:8]}@example.com"
    token = mono_security.create_access_token({"sub": "1", "email": email, "rol": rol})
    return email, {"Authorization": f"Bearer {token}"}


def _stored(db, target_id, payload):
    db.add(
        CourseOverride(
            scope="module",
            target_id=target_id,
            payload=payload,
            updated_by="ana@example.com",
            updated_at=datetime(2026, 3, 1),
        )
    )
    db.commit()


def _create(headers, **body):
    return client.post("/api/modules/", json=body, headers=headers)


def _rows(db):
    db.expire_all()
    return db.query(CourseOverride).all()


# --- guardar -------------------------------------------------------------------


def test_saving_a_module_without_a_session_is_refused(db_session):
    response = client.post("/api/modules/", json={"module_id": "1", "name": "Intro"})

    assert response.status_code == 401
    assert _rows(db_session) == []


def test_a_student_cannot_rename_a_module(db_session):
    _, student = _auth("estudiante")

    response = _create(student, module_id="1", name="Mío")

    assert response.status_code == 403
    assert _rows(db_session) == []


def test_a_teacher_saves_a_module_in_the_shared_course_table(db_session):
    email, teacher = _auth("docente")

    response = _create(teacher, module_id="1", name="  Primeros pasos  ", topics=["print", "input"])

    assert response.status_code == 201
    assert response.json() == {"id": "1", "name": "Primeros pasos", "topics": ["print", "input"]}
    [row] = _rows(db_session)
    assert (row.scope, row.target_id, row.updated_by) == ("module", "1", email)
    # El nombre se guarda como `title`, que es lo que lee el resto del temario.
    assert json.loads(row.payload) == {"title": "Primeros pasos", "topics": ["print", "input"]}


def test_a_module_saved_without_topics_has_none(db_session):
    _, teacher = _auth("director")

    response = _create(teacher, module_id="2", name="Condicionales")

    assert response.json() == {"id": "2", "name": "Condicionales", "topics": []}
    assert json.loads(_rows(db_session)[0].payload) == {"title": "Condicionales"}


def test_leading_zeros_name_the_same_module(db_session):
    _, teacher = _auth("docente")
    _create(teacher, module_id="1", name="Primero")

    response = _create(teacher, module_id="01", name="Otra vez el primero")

    assert response.status_code == 201
    assert response.json()["id"] == "1"
    rows = _rows(db_session)
    assert len(rows) == 1
    assert json.loads(rows[0].payload)["title"] == "Otra vez el primero"


@pytest.mark.parametrize("module_id", [None, "", "abc", "0", "-1", "m1"])
def test_a_module_is_identified_by_its_number(db_session, module_id):
    _, teacher = _auth("docente")
    body = {"name": "Intro"}
    if module_id is not None:
        body["module_id"] = module_id

    response = _create(teacher, **body)

    assert response.status_code == 400
    assert "no identifica un módulo" in response.json()["detail"]
    assert _rows(db_session) == []


def test_a_module_with_too_much_text_is_not_saved(db_session):
    _, teacher = _auth("docente")

    response = _create(teacher, module_id="1", name="x" * (64 * 1024))

    assert response.status_code == 413
    assert _rows(db_session) == []


# --- leer --------------------------------------------------------------------


def test_reading_a_module_needs_no_session(db_session):
    _stored(db_session, "3", '{"title": "Bucles", "topics": ["for", "while"]}')

    response = client.get("/api/modules/3")

    assert response.status_code == 200
    assert response.json() == {"id": "3", "name": "Bucles", "topics": ["for", "while"]}


def test_an_unedited_module_is_not_found():
    response = client.get("/api/modules/4")

    assert response.status_code == 404


def test_reading_checks_the_module_number():
    response = client.get("/api/modules/abc")

    assert response.status_code == 400


def test_a_module_renamed_from_the_course_editor_reads_the_same_here():
    _, teacher = _auth("docente")
    client.put(
        "/api/course/overrides/module/5",
        json={"content": {"title": "Funciones", "topics": [1, "def"]}},
        headers=teacher,
    )

    response = client.get("/api/modules/05")

    assert response.json() == {"id": "5", "name": "Funciones", "topics": ["1", "def"]}


@pytest.mark.parametrize(
    "payload", ["{esto no es json", "[1, 2]", '{"topics": "no es una lista"}']
)
def test_a_broken_module_reads_as_empty_instead_of_failing(db_session, payload):
    _stored(db_session, "6", payload)

    response = client.get("/api/modules/6")

    assert response.status_code == 200
    assert response.json() == {"id": "6", "name": "", "topics": []}


# --- cambiar solo una parte --------------------------------------------------------


def test_patching_only_the_name_keeps_the_topics(db_session):
    email, teacher = _auth("docente")
    _stored(db_session, "1", '{"title": "Viejo", "topics": ["print"], "color": "azul"}')

    response = client.patch("/api/modules/1", json={"name": " Nuevo "}, headers=teacher)

    assert response.status_code == 200
    assert response.json() == {"id": "1", "name": "Nuevo", "topics": ["print"]}
    [row] = _rows(db_session)
    # Lo que no se manda, incluso lo que esta ruta no conoce, se queda.
    assert json.loads(row.payload) == {"title": "Nuevo", "topics": ["print"], "color": "azul"}
    assert row.updated_by == email


def test_patching_only_the_topics_keeps_the_name(db_session):
    _, teacher = _auth("docente")
    _stored(db_session, "1", '{"title": "Intro", "topics": ["print"]}')

    response = client.patch("/api/modules/1", json={"topics": ["input", "if"]}, headers=teacher)

    assert response.json() == {"id": "1", "name": "Intro", "topics": ["input", "if"]}


def test_patching_a_module_that_was_never_saved_is_not_found(db_session):
    _, teacher = _auth("docente")

    response = client.patch("/api/modules/2", json={"name": "Nada"}, headers=teacher)

    assert response.status_code == 404
    assert _rows(db_session) == []


def test_a_student_cannot_patch_a_module(db_session):
    _, student = _auth("estudiante")
    _stored(db_session, "1", '{"title": "Intro"}')

    response = client.patch("/api/modules/1", json={"name": "Hackeado"}, headers=student)

    assert response.status_code == 403
    assert json.loads(_rows(db_session)[0].payload) == {"title": "Intro"}


def test_patching_checks_the_module_number():
    _, teacher = _auth("docente")

    response = client.patch("/api/modules/uno", json={"name": "Intro"}, headers=teacher)

    assert response.status_code == 400
