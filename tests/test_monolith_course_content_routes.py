"""El temario editado en el monolito: leer es público, escribir es de docentes.

Solo se guarda lo que el docente cambia. Las pruebas pasan por la app del
monolito (`main.py`) con tokens de su `core.security` y comprueban lo que
queda en la tabla CourseOverride de la base SQLite temporal.
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
    """Cada prueba empieza y termina con el temario sin editar."""
    _wipe(db_session)
    yield
    db_session.rollback()
    _wipe(db_session)


def _auth(rol):
    """Cabecera con una sesión del rol pedido. Estas rutas no buscan al usuario."""
    email = f"{rol}-{uuid.uuid4().hex[:8]}@example.com"
    token = mono_security.create_access_token({"sub": "1", "email": email, "rol": rol})
    return email, {"Authorization": f"Bearer {token}"}


def _stored(db, scope, target_id, payload, when=None, by="ana@example.com"):
    db.add(
        CourseOverride(
            scope=scope, target_id=target_id, payload=payload, updated_by=by, updated_at=when
        )
    )
    db.commit()


def _save(headers, target_id="m1-s1", content=None, scope="section"):
    return client.put(
        f"/api/course/overrides/{scope}/{target_id}",
        json={"content": content if content is not None else {"title": "Variables"}},
        headers=headers,
    )


# --- leer --------------------------------------------------------------------


def test_reading_an_unedited_course_needs_no_session_and_is_never_cached():
    response = client.get("/api/course/overrides")

    assert response.status_code == 200
    assert response.json() == {"version": "", "count": 0, "items": []}
    assert response.headers["cache-control"] == "no-store"


def test_the_list_brings_every_edit_and_the_latest_change_as_version(db_session):
    _stored(db_session, "section", "m1-s1", '{"title": "Variables"}', datetime(2026, 3, 1))
    _stored(db_session, "module", "1", '{"title": "Primeros pasos"}', datetime(2026, 3, 9))

    body = client.get("/api/course/overrides").json()

    assert body["version"] == "2026-03-09T00:00:00"
    assert body["count"] == 2
    items = {(i["scope"], i["target_id"]): i for i in body["items"]}
    assert items[("section", "m1-s1")] == {
        "scope": "section",
        "target_id": "m1-s1",
        "content": {"title": "Variables"},
        "updated_by": "ana@example.com",
        "updated_at": "2026-03-01T00:00:00",
    }
    assert items[("module", "1")]["content"] == {"title": "Primeros pasos"}


def test_an_unreadable_edit_does_not_break_the_list(db_session):
    _stored(db_session, "section", "m1-s1", "{esto no es json", datetime(2026, 3, 1))
    _stored(db_session, "section", "m1-s2", "[1, 2, 3]", datetime(2026, 3, 2))

    body = client.get("/api/course/overrides").json()

    # Se devuelve vacío y la app enseña el original de esas secciones.
    assert [i["content"] for i in body["items"]] == [{}, {}]


def test_one_edited_section_can_be_read_alone(db_session):
    _stored(db_session, "section", "m1-s1", '{"title": "Variables"}', datetime(2026, 3, 1))

    response = client.get("/api/course/overrides/section/m1-s1")

    assert response.status_code == 200
    assert response.json()["content"] == {"title": "Variables"}


def test_an_unedited_section_is_not_found():
    response = client.get("/api/course/overrides/section/m1-s1")

    assert response.status_code == 404


def test_only_sections_and_modules_exist():
    response = client.get("/api/course/overrides/curso/entero")

    assert response.status_code == 400
    assert "module, section" in response.json()["detail"]


# --- guardar -----------------------------------------------------------------


def test_editing_without_a_session_is_refused(db_session):
    response = client.put(
        "/api/course/overrides/section/m1-s1", json={"content": {"title": "x"}}
    )

    assert response.status_code == 401
    assert db_session.query(CourseOverride).count() == 0


def test_a_student_cannot_edit_the_course(db_session):
    _, student = _auth("estudiante")

    response = _save(student)

    assert response.status_code == 403
    assert db_session.query(CourseOverride).count() == 0


def test_a_teacher_saves_a_section_and_their_email_is_kept(db_session):
    email, teacher = _auth("docente")
    content = {"title": "Variables", "lecturas": ["¿Qué es una variable?"]}

    response = _save(teacher, content=content)

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == content
    assert body["updated_by"] == email
    assert body["updated_at"]
    row = db_session.query(CourseOverride).one()
    assert (row.scope, row.target_id, row.updated_by) == ("section", "m1-s1", email)
    # Se guarda tal cual, sin escapar las tildes.
    assert json.loads(row.payload) == content
    assert "¿Qué" in row.payload


def test_saving_again_replaces_the_edit_instead_of_adding_another(db_session):
    _, teacher = _auth("docente")
    director_email, director = _auth("director")
    _save(teacher, content={"title": "Primera"})

    response = _save(director, content={"title": "Segunda"})

    assert response.status_code == 200
    db_session.expire_all()
    rows = db_session.query(CourseOverride).all()
    assert len(rows) == 1
    assert json.loads(rows[0].payload) == {"title": "Segunda"}
    assert rows[0].updated_by == director_email


def test_an_editor_cannot_save_outside_sections_and_modules(db_session):
    _, teacher = _auth("docente")

    response = _save(teacher, scope="curso")

    assert response.status_code == 400
    assert db_session.query(CourseOverride).count() == 0


def test_saving_must_say_what_is_being_edited(db_session):
    _, teacher = _auth("docente")

    response = _save(teacher, target_id="%20")

    assert response.status_code == 400
    assert db_session.query(CourseOverride).count() == 0


def test_a_section_that_is_too_big_is_not_saved(db_session):
    _, teacher = _auth("docente")

    response = _save(teacher, content={"texto": "x" * (512 * 1024)})

    assert response.status_code == 413
    assert db_session.query(CourseOverride).count() == 0


def test_the_content_must_be_an_object():
    _, teacher = _auth("docente")

    response = client.put(
        "/api/course/overrides/section/m1-s1", json={"content": ["no", "vale"]}, headers=teacher
    )

    assert response.status_code == 422


# --- volver al original ------------------------------------------------------


def test_reverting_removes_the_edit(db_session):
    _, teacher = _auth("docente")
    _save(teacher)

    response = client.delete("/api/course/overrides/section/m1-s1", headers=teacher)

    assert response.status_code == 200
    assert response.json()["reverted"] is True
    assert db_session.query(CourseOverride).count() == 0
    assert client.get("/api/course/overrides/section/m1-s1").status_code == 404


def test_reverting_an_unedited_section_is_harmless():
    _, teacher = _auth("docente")

    response = client.delete("/api/course/overrides/section/m1-s1", headers=teacher)

    assert response.status_code == 200
    assert response.json()["reverted"] is False


def test_a_student_cannot_revert_an_edit(db_session):
    _stored(db_session, "section", "m1-s1", "{}", datetime(2026, 3, 1))
    _, student = _auth("estudiante")

    response = client.delete("/api/course/overrides/section/m1-s1", headers=student)

    assert response.status_code == 403
    assert db_session.query(CourseOverride).count() == 1


def test_reverting_checks_the_scope_too():
    _, teacher = _auth("docente")

    response = client.delete("/api/course/overrides/curso/m1-s1", headers=teacher)

    assert response.status_code == 400


# --- quién puede editar ------------------------------------------------------


@pytest.mark.parametrize("rol", ["docente", "director"])
def test_teachers_and_directors_are_told_they_can_edit(rol):
    email, headers = _auth(rol)

    response = client.get("/api/course/can-edit", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"can_edit": True, "email": email, "rol": rol}


def test_a_student_is_told_they_cannot_edit():
    _, student = _auth("estudiante")

    assert client.get("/api/course/can-edit", headers=student).status_code == 403
    assert client.get("/api/course/can-edit").status_code == 401
