"""El seguimiento del director en el monolito: docentes, valoraciones y revisiones.

Todo es solo para el director, y el rol se mira en la base de datos, no en el
token: quien deja de ser director pierde el acceso en el acto. Las pruebas
pasan por la app del monolito (`main.py`) con tokens de su `core.security`.
"""

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from monolith import load_main

main = load_main()

import core.security as mono_security  # noqa: E402  Mismo módulo que usa el monolito.
from infrastructure.database.models import (  # noqa: E402
    ContentReview,
    CourseOverride,
    TeacherReview,
    Usuario,
)

client = TestClient(main.app)


def _wipe(db):
    db.query(TeacherReview).delete()
    db.query(ContentReview).delete()
    db.query(CourseOverride).delete()
    db.commit()


@pytest.fixture(autouse=True)
def _clean_tables(db_session):
    """Cada prueba empieza y termina sin valoraciones, revisiones ni ediciones."""
    _wipe(db_session)
    yield
    db_session.rollback()
    _wipe(db_session)


def _user(db, rol, nombre=None):
    """Crea la cuenta y devuelve la fila y la cabecera con su sesión."""
    email = f"{rol.lower()}-{uuid.uuid4().hex[:8]}@example.com"
    user = Usuario(nombre=nombre or rol.title(), correo=email, password="x", rol=rol)
    db.add(user)
    db.commit()
    token = mono_security.create_access_token(
        {"sub": str(user.id_usuario), "email": email, "rol": rol}
    )
    return user, {"Authorization": f"Bearer {token}"}


def _edit(db, email, target_id, when, scope="section"):
    db.add(
        CourseOverride(
            scope=scope, target_id=target_id, payload="{}", updated_by=email, updated_at=when
        )
    )
    db.commit()


def _review(db, docente_id, score, when, comment="Bien"):
    db.add(TeacherReview(docente_id=docente_id, score=score, comment=comment, created_at=when))
    db.commit()


def _content_review(db, section_id, status, when, comment=""):
    db.add(ContentReview(section_id=section_id, status=status, comment=comment, reviewed_at=when))
    db.commit()


# --- solo el director ----------------------------------------------------------


def test_oversight_needs_a_session():
    response = client.get("/api/oversight/teachers")

    assert response.status_code == 401


def test_a_forged_token_is_refused():
    response = client.get(
        "/api/oversight/teachers", headers={"Authorization": "Bearer no-es-un-token"}
    )

    assert response.status_code == 401


def test_a_token_without_a_numeric_id_identifies_nobody():
    token = mono_security.create_access_token(
        {"sub": "laura", "email": "laura@example.com", "rol": "director"}
    )

    response = client.get(
        "/api/oversight/teachers", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "La sesión no identifica a nadie."


@pytest.mark.parametrize("rol", ["estudiante", "docente"])
def test_only_the_director_gets_in(db_session, rol):
    _, headers = _user(db_session, rol)

    response = client.get("/api/oversight/teachers", headers=headers)

    assert response.status_code == 403


def test_the_role_is_checked_against_the_database_not_the_token(db_session):
    director, headers = _user(db_session, "director")
    director.rol = "docente"
    db_session.commit()

    response = client.get("/api/oversight/content", headers=headers)

    assert response.status_code == 403


def test_a_deleted_account_loses_access(db_session):
    token = mono_security.create_access_token(
        {"sub": "987654", "email": "nadie@example.com", "rol": "director"}
    )

    response = client.get(
        "/api/oversight/content", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403


# --- qué ha hecho cada docente ---------------------------------------------------


def test_the_director_sees_every_teacher_with_edits_and_scores(db_session):
    _, director = _user(db_session, "Director")
    ana, _ = _user(db_session, "docente", nombre="Ana")
    beto, _ = _user(db_session, "Docente", nombre="Beto")
    student, _ = _user(db_session, "estudiante", nombre="Carla")
    _edit(db_session, ana.correo, "m1-s1", datetime(2026, 3, 1, 10, 0))
    _edit(db_session, ana.correo, "m1-s2", datetime(2026, 3, 5, 9, 30))
    _review(db_session, ana.id_usuario, 3, datetime(2026, 3, 2))
    _review(db_session, ana.id_usuario, 4, datetime(2026, 3, 9))
    _review(db_session, ana.id_usuario, 4, datetime(2026, 3, 6))

    response = client.get("/api/oversight/teachers", headers=director)

    assert response.status_code == 200
    body = response.json()
    by_id = {t["user_id"]: t for t in body["teachers"]}
    assert body["count"] == len(body["teachers"])
    assert student.id_usuario not in by_id
    assert by_id[ana.id_usuario] == {
        "user_id": ana.id_usuario,
        "nombre": "Ana",
        "correo": ana.correo,
        "edits": 2,
        "last_edit": "2026-03-05T09:30:00",
        "reviews": 3,
        # La última es la más reciente, no la última que se guardó.
        "last_score": 4,
        "avg_score": 3.67,
    }
    # Quien no ha hecho nada también sale: es justo lo que hay que ver.
    assert by_id[beto.id_usuario] == {
        "user_id": beto.id_usuario,
        "nombre": "Beto",
        "correo": beto.correo,
        "edits": 0,
        "last_edit": None,
        "reviews": 0,
        "last_score": None,
        "avg_score": None,
    }
    names = [t["nombre"] for t in body["teachers"]]
    assert names == sorted(names)


def test_the_activity_of_a_missing_teacher_is_not_found(db_session):
    _, director = _user(db_session, "director")

    response = client.get("/api/oversight/teachers/987654/activity", headers=director)

    assert response.status_code == 404


def test_a_teacher_who_touched_nothing_has_an_empty_trail(db_session):
    _, director = _user(db_session, "director")
    ana, _ = _user(db_session, "docente", nombre="Ana")

    response = client.get(
        f"/api/oversight/teachers/{ana.id_usuario}/activity", headers=director
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": ana.id_usuario,
        "nombre": "Ana",
        "correo": ana.correo,
        "count": 0,
        "items": [],
    }


def test_the_trail_flags_reviews_older_than_the_last_edit(db_session):
    _, director = _user(db_session, "director")
    ana, _ = _user(db_session, "docente")
    luis, _ = _user(db_session, "docente")
    _edit(db_session, ana.correo, "m1-s1", datetime(2026, 3, 10))
    _edit(db_session, ana.correo, "m1-s2", datetime(2026, 3, 1))
    _edit(db_session, ana.correo, "m1-s3", datetime(2026, 3, 5))
    _edit(db_session, luis.correo, "m2-s1", datetime(2026, 3, 20))
    # m1-s1 se aprobó antes de reescribirse; m1-s2, después.
    _content_review(db_session, "m1-s1", "aprobado", datetime(2026, 3, 2))
    _content_review(db_session, "m1-s2", "observado", datetime(2026, 3, 3), "Falta un ejemplo")

    response = client.get(
        f"/api/oversight/teachers/{ana.id_usuario}/activity", headers=director
    )

    body = response.json()
    assert body["count"] == 3
    assert body["items"] == [
        {
            "scope": "section",
            "target_id": "m1-s1",
            "updated_at": "2026-03-10T00:00:00",
            "review_status": "aprobado",
            "review_comment": "",
            "review_outdated": True,
        },
        {
            "scope": "section",
            "target_id": "m1-s3",
            "updated_at": "2026-03-05T00:00:00",
            "review_status": None,
            "review_comment": None,
            "review_outdated": False,
        },
        {
            "scope": "section",
            "target_id": "m1-s2",
            "updated_at": "2026-03-01T00:00:00",
            "review_status": "observado",
            "review_comment": "Falta un ejemplo",
            "review_outdated": False,
        },
    ]


# --- valorar al docente ----------------------------------------------------------


def test_the_director_rates_a_teacher_and_the_rating_is_kept(db_session):
    director, headers = _user(db_session, "director")
    ana, _ = _user(db_session, "docente")

    response = client.post(
        "/api/oversight/reviews",
        json={"docente_id": ana.id_usuario, "score": 5, "comment": "  Muy claro  "},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["docente_id"] == ana.id_usuario
    assert body["score"] == 5
    assert body["comment"] == "Muy claro"
    assert body["created_at"]
    row = db_session.query(TeacherReview).one()
    assert (row.docente_id, row.director_id, row.score) == (
        ana.id_usuario,
        director.id_usuario,
        5,
    )


def test_very_long_comments_are_cut(db_session):
    _, headers = _user(db_session, "director")
    ana, _ = _user(db_session, "docente")

    response = client.post(
        "/api/oversight/reviews",
        json={"docente_id": ana.id_usuario, "score": 2, "comment": "a" * 5000},
        headers=headers,
    )

    assert response.status_code == 201
    assert len(response.json()["comment"]) == 4000


@pytest.mark.parametrize("score", [0, 6])
def test_scores_outside_one_to_five_are_invalid(db_session, score):
    _, headers = _user(db_session, "director")
    ana, _ = _user(db_session, "docente")

    response = client.post(
        "/api/oversight/reviews",
        json={"docente_id": ana.id_usuario, "score": score, "comment": "x"},
        headers=headers,
    )

    assert response.status_code == 422
    assert db_session.query(TeacherReview).count() == 0


def test_only_teachers_can_be_rated(db_session):
    _, headers = _user(db_session, "director")
    student, _ = _user(db_session, "estudiante")

    not_a_teacher = client.post(
        "/api/oversight/reviews",
        json={"docente_id": student.id_usuario, "score": 3, "comment": "x"},
        headers=headers,
    )
    missing = client.post(
        "/api/oversight/reviews",
        json={"docente_id": 987654, "score": 3, "comment": "x"},
        headers=headers,
    )

    assert not_a_teacher.status_code == 404
    assert missing.status_code == 404
    assert db_session.query(TeacherReview).count() == 0


def test_a_score_without_a_comment_is_refused(db_session):
    _, headers = _user(db_session, "director")
    ana, _ = _user(db_session, "docente")

    response = client.post(
        "/api/oversight/reviews",
        json={"docente_id": ana.id_usuario, "score": 3, "comment": "   "},
        headers=headers,
    )

    assert response.status_code == 400
    assert db_session.query(TeacherReview).count() == 0


def test_a_teacher_cannot_rate_another_teacher(db_session):
    _, teacher = _user(db_session, "docente")
    ana, _ = _user(db_session, "docente")

    response = client.post(
        "/api/oversight/reviews",
        json={"docente_id": ana.id_usuario, "score": 1, "comment": "x"},
        headers=teacher,
    )

    assert response.status_code == 403


def test_the_rating_history_goes_from_newest_to_oldest(db_session):
    _, headers = _user(db_session, "director")
    ana, _ = _user(db_session, "docente")
    luis, _ = _user(db_session, "docente")
    _review(db_session, ana.id_usuario, 2, datetime(2026, 1, 1), "Flojo")
    _review(db_session, ana.id_usuario, 4, datetime(2026, 2, 1), "Mejor")
    _review(db_session, luis.id_usuario, 5, datetime(2026, 3, 1))

    response = client.get(f"/api/oversight/reviews/{ana.id_usuario}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [(r["score"], r["comment"], r["created_at"]) for r in body["reviews"]] == [
        (4, "Mejor", "2026-02-01T00:00:00"),
        (2, "Flojo", "2026-01-01T00:00:00"),
    ]


# --- revisar el contenido --------------------------------------------------------


def test_the_director_approves_a_section(db_session):
    director, headers = _user(db_session, "director")

    response = client.put(
        "/api/oversight/content/m1-s1",
        json={"section_id": "m1-s1", "status": "aprobado"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["section_id"] == "m1-s1"
    assert body["status"] == "aprobado"
    assert body["comment"] == ""
    assert body["reviewed_at"]
    row = db_session.query(ContentReview).one()
    assert row.director_id == director.id_usuario


def test_reviewing_a_section_again_replaces_the_previous_review(db_session):
    _, first_director = _user(db_session, "director")
    second, second_director = _user(db_session, "director")
    client.put(
        "/api/oversight/content/m1-s1",
        json={"section_id": "m1-s1", "status": "aprobado"},
        headers=first_director,
    )

    response = client.put(
        "/api/oversight/content/m1-s1",
        json={"section_id": "m1-s1", "status": "observado", "comment": " Falta el quiz "},
        headers=second_director,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "observado"
    assert response.json()["comment"] == "Falta el quiz"
    db_session.expire_all()
    rows = db_session.query(ContentReview).all()
    assert len(rows) == 1
    assert (rows[0].status, rows[0].director_id) == ("observado", second.id_usuario)


def test_an_unknown_review_state_is_refused(db_session):
    _, headers = _user(db_session, "director")

    response = client.put(
        "/api/oversight/content/m1-s1",
        json={"section_id": "m1-s1", "status": "regular"},
        headers=headers,
    )

    assert response.status_code == 400
    assert db_session.query(ContentReview).count() == 0


def test_flagging_a_section_needs_an_explanation(db_session):
    _, headers = _user(db_session, "director")

    response = client.put(
        "/api/oversight/content/m1-s1",
        json={"section_id": "m1-s1", "status": "observado", "comment": "  "},
        headers=headers,
    )

    assert response.status_code == 400
    assert db_session.query(ContentReview).count() == 0


def test_a_teacher_cannot_review_content(db_session):
    _, teacher = _user(db_session, "docente")

    response = client.put(
        "/api/oversight/content/m1-s1",
        json={"section_id": "m1-s1", "status": "aprobado"},
        headers=teacher,
    )

    assert response.status_code == 403


def test_the_review_list_flags_sections_edited_after_their_review(db_session):
    _, headers = _user(db_session, "director")
    _edit(db_session, "ana@example.com", "m1-s1", datetime(2026, 3, 10))
    _edit(db_session, "ana@example.com", "m1-s2", datetime(2026, 3, 1))
    # Un módulo con el mismo id no cuenta como edición de la sección.
    _edit(db_session, "ana@example.com", "m1-s3", datetime(2026, 3, 30), scope="module")
    _content_review(db_session, "m1-s1", "aprobado", datetime(2026, 3, 2))
    _content_review(db_session, "m1-s2", "aprobado", datetime(2026, 3, 2))
    _content_review(db_session, "m1-s3", "observado", datetime(2026, 3, 2), "Revisar")
    _content_review(db_session, "m9-s9", "aprobado", datetime(2026, 3, 2))

    response = client.get("/api/oversight/content", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 4
    outdated = {item["section_id"]: item["outdated"] for item in body["items"]}
    assert outdated == {"m1-s1": True, "m1-s2": False, "m1-s3": False, "m9-s9": False}
    m1_s3 = next(item for item in body["items"] if item["section_id"] == "m1-s3")
    assert m1_s3 == {
        "section_id": "m1-s3",
        "status": "observado",
        "comment": "Revisar",
        "reviewed_at": "2026-03-02T00:00:00",
        "outdated": False,
    }
