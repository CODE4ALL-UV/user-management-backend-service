"""La analítica del monolito: respuestas, actividades terminadas y resúmenes.

El estudiante solo puede registrar lo suyo, y el id sale del token, no del
cuerpo. Los resúmenes del curso y el borrado son solo para docentes y
dirección. Las pruebas pasan por la app del monolito (`main.py`), con tokens
firmados por su propio `core.security`, sobre la base SQLite temporal.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from monolith import load_main

main = load_main()

import core.security as mono_security  # noqa: E402  Mismo módulo que usa el monolito.
from core.database import SessionLocal  # noqa: E402
from infrastructure.database.connection import get_db  # noqa: E402
from infrastructure.database.models import (  # noqa: E402
    ActivityCompletion,
    QuizAnswer,
    Usuario,
)

client = TestClient(main.app)


def _wipe(db):
    db.query(QuizAnswer).delete()
    db.query(ActivityCompletion).delete()
    db.commit()


@pytest.fixture(autouse=True)
def _clean_tables(db_session):
    """Cada prueba empieza y termina sin respuestas ni actividades guardadas."""
    _wipe(db_session)
    yield
    db_session.rollback()
    _wipe(db_session)


def _user(db, rol, nombre=None):
    """Crea la cuenta y devuelve su id y la cabecera con su sesión."""
    email = f"{rol.lower()}-{uuid.uuid4().hex[:8]}@example.com"
    user = Usuario(nombre=nombre or rol.title(), correo=email, password="x", rol=rol)
    db.add(user)
    db.commit()
    token = mono_security.create_access_token(
        {"sub": str(user.id_usuario), "email": email, "rol": rol}
    )
    return user.id_usuario, {"Authorization": f"Bearer {token}"}


def _attempt(headers, section="m1-s1", activity="quiz", answers=None, **extra):
    body = {
        "section_id": section,
        "activity": activity,
        "answers": answers
        if answers is not None
        else [
            {"question_index": 0, "prompt": "¿2+2?", "correct": True, "elapsed_ms": 4000},
            {"question_index": 1, "prompt": "¿3*3?", "correct": False},
        ],
        **extra,
    }
    return client.post("/api/analytics/attempts", json=body, headers=headers)


def _complete(headers, section="m1-s1", activity="lectura"):
    return client.post(
        "/api/analytics/completions",
        json={"section_id": section, "activity": activity},
        headers=headers,
    )


def _session_that_fails_on_commit():
    """Una sesión real cuyo commit falla como si la cuenta ya no existiera."""
    db = SessionLocal()

    def commit():
        raise IntegrityError("INSERT", {}, Exception("FOREIGN KEY constraint failed"))

    db.commit = commit
    try:
        yield db
    finally:
        db.close()


def _by(items, **keys):
    return next(
        item for item in items if all(item[k] == v for k, v in keys.items())
    )


# --- registrar respuestas ----------------------------------------------------


def test_recording_answers_needs_a_session():
    response = client.post(
        "/api/analytics/attempts",
        json={"section_id": "m1-s1", "activity": "quiz", "answers": []},
    )

    assert response.status_code == 401


def test_a_forged_token_is_refused():
    response = _attempt({"Authorization": "Bearer no-es-un-token"})

    assert response.status_code == 401


def test_a_token_without_email_identifies_nobody():
    token = mono_security.create_access_token({"sub": "1", "rol": "estudiante"})

    response = _attempt({"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_a_student_records_their_answers_under_their_own_id(db_session):
    student_id, student = _user(db_session, "estudiante")

    # Un id en el cuerpo no cuenta: manda el del token.
    response = _attempt(student, section="  m2-s1  ", usuario_id=999)

    assert response.status_code == 201
    assert response.json() == {"recorded": 2}
    rows = db_session.query(QuizAnswer).order_by(QuizAnswer.question_index).all()
    assert [r.usuario_id for r in rows] == [student_id, student_id]
    assert [r.section_id for r in rows] == ["m2-s1", "m2-s1"]
    assert [r.correct for r in rows] == [True, False]
    assert [r.elapsed_ms for r in rows] == [4000, None]


def test_long_prompts_are_cut_and_forgotten_screens_do_not_count_as_time(db_session):
    _, student = _user(db_session, "estudiante")

    response = _attempt(
        student,
        answers=[
            {
                "question_index": 0,
                "prompt": "x" * 800,
                "correct": True,
                "elapsed_ms": 31 * 60 * 1000,
            },
            {
                "question_index": 1,
                "prompt": "y",
                "correct": True,
                "elapsed_ms": 30 * 60 * 1000,
            },
        ],
    )

    assert response.status_code == 201
    rows = db_session.query(QuizAnswer).order_by(QuizAnswer.question_index).all()
    assert len(rows[0].prompt) == 500
    assert rows[0].elapsed_ms is None
    assert rows[1].elapsed_ms == 30 * 60 * 1000


def test_activities_without_questions_do_not_take_answers(db_session):
    _, student = _user(db_session, "estudiante")

    response = _attempt(student, activity="lectura")

    assert response.status_code == 400
    assert "lectura" in response.json()["detail"]
    assert db_session.query(QuizAnswer).count() == 0


def test_an_attempt_must_say_which_section_it_belongs_to(db_session):
    _, student = _user(db_session, "estudiante")

    response = _attempt(student, section="   ")

    assert response.status_code == 400
    assert db_session.query(QuizAnswer).count() == 0


def test_an_attempt_without_answers_is_refused(db_session):
    _, student = _user(db_session, "estudiante")

    response = _attempt(student, answers=[])

    assert response.status_code == 400


def test_an_attempt_with_too_many_answers_is_refused(db_session):
    _, student = _user(db_session, "estudiante")
    answers = [{"question_index": i, "correct": True} for i in range(61)]

    response = _attempt(student, answers=answers)

    assert response.status_code == 413
    assert db_session.query(QuizAnswer).count() == 0


def test_negative_times_and_question_numbers_are_invalid(db_session):
    _, student = _user(db_session, "estudiante")

    negative_time = _attempt(
        student, answers=[{"question_index": 0, "correct": True, "elapsed_ms": -1}]
    )
    negative_index = _attempt(student, answers=[{"question_index": -1, "correct": True}])

    assert negative_time.status_code == 422
    assert negative_index.status_code == 422


def test_answers_from_a_deleted_account_get_a_clear_conflict(db_session, monkeypatch):
    _, student = _user(db_session, "estudiante")
    monkeypatch.setitem(main.app.dependency_overrides, get_db, _session_that_fails_on_commit)

    response = _attempt(student)

    assert response.status_code == 409
    assert "ya no existe" in response.json()["detail"]
    assert db_session.query(QuizAnswer).count() == 0


# --- actividades terminadas --------------------------------------------------


def test_finishing_an_activity_is_noted_once(db_session):
    student_id, student = _user(db_session, "estudiante")

    first = _complete(student, section=" m1-s1 ", activity="video")
    again = _complete(student, section="m1-s1", activity="video")

    assert first.status_code == 200
    assert first.json() == {"recorded": True}
    assert again.json() == {"recorded": False, "detail": "Ya estaba anotada."}
    rows = db_session.query(ActivityCompletion).all()
    assert [(r.usuario_id, r.section_id, r.activity) for r in rows] == [
        (student_id, "m1-s1", "video")
    ]


def test_noting_an_activity_needs_a_session():
    response = client.post(
        "/api/analytics/completions", json={"section_id": "m1-s1", "activity": "lectura"}
    )

    assert response.status_code == 401


def test_an_unknown_activity_is_not_noted(db_session):
    _, student = _user(db_session, "estudiante")

    response = _complete(student, activity="siesta")

    assert response.status_code == 400
    assert db_session.query(ActivityCompletion).count() == 0


def test_a_finished_activity_must_say_its_section(db_session):
    _, student = _user(db_session, "estudiante")

    response = _complete(student, section=" ")

    assert response.status_code == 400


def test_a_clash_while_noting_an_activity_is_not_the_students_problem(
    db_session, monkeypatch
):
    _, student = _user(db_session, "estudiante")
    monkeypatch.setitem(main.app.dependency_overrides, get_db, _session_that_fails_on_commit)

    response = _complete(student)

    assert response.status_code == 200
    assert response.json() == {"recorded": False, "detail": "No se pudo anotar."}
    assert db_session.query(ActivityCompletion).count() == 0


# --- resumen del curso -------------------------------------------------------


def test_a_student_cannot_see_the_course_summary(db_session):
    _, student = _user(db_session, "estudiante")

    assert client.get("/api/analytics/summary", headers=student).status_code == 403
    assert client.get("/api/analytics/summary").status_code == 401


def test_an_empty_summary_says_nobody_has_answered_yet(db_session):
    _, teacher = _user(db_session, "docente")

    response = client.get("/api/analytics/summary", headers=teacher)

    assert response.status_code == 200
    assert response.json() == {
        "total_answers": 0,
        "total_completions": 0,
        "sections": [],
        "questions": [],
        "completions": [],
    }


def test_the_summary_adds_up_sections_questions_and_finished_activities(db_session):
    _, ana = _user(db_session, "estudiante")
    _, luis = _user(db_session, "estudiante")
    _, director = _user(db_session, "director")
    _attempt(ana, section="m1-s1")
    _attempt(
        luis,
        section="m1-s1",
        answers=[
            {"question_index": 0, "prompt": "¿2+2?", "correct": False, "elapsed_ms": 2000},
            {"question_index": 1, "prompt": "¿3*3?", "correct": False},
        ],
    )
    _attempt(ana, section="m2-s1", answers=[{"question_index": 0, "correct": True}])
    _complete(ana, section="m1-s1", activity="lectura")
    _complete(luis, section="m1-s1", activity="lectura")
    _complete(ana, section="m1-s1", activity="quiz")

    body = client.get("/api/analytics/summary", headers=director).json()

    assert body["total_answers"] == 5
    assert body["total_completions"] == 3
    assert _by(body["sections"], section_id="m1-s1") == {
        "section_id": "m1-s1",
        "answered": 4,
        "correct": 1,
        "failed": 3,
        "students": 2,
        "accuracy": 0.25,
        # Solo promedian las respuestas que traen tiempo: (4000 + 2000) / 2.
        "avg_seconds": 3.0,
    }
    assert _by(body["sections"], section_id="m2-s1")["avg_seconds"] is None
    assert _by(body["questions"], section_id="m1-s1", question_index=0) == {
        "section_id": "m1-s1",
        "activity": "quiz",
        "question_index": 0,
        "prompt": "¿2+2?",
        "answered": 2,
        "correct": 1,
        "failed": 1,
        "accuracy": 0.5,
        "avg_seconds": 3.0,
    }
    unanswered_prompt = _by(body["questions"], section_id="m2-s1", question_index=0)
    assert unanswered_prompt["prompt"] == ""
    assert unanswered_prompt["avg_seconds"] is None
    assert _by(body["completions"], section_id="m1-s1", activity="lectura")["students"] == 2
    assert _by(body["completions"], section_id="m1-s1", activity="quiz")["students"] == 1


# --- estudiantes ---------------------------------------------------------------


def test_a_student_cannot_see_the_other_students(db_session):
    _, student = _user(db_session, "estudiante")

    assert client.get("/api/analytics/students", headers=student).status_code == 403


def test_the_teacher_sees_every_student_even_those_who_did_nothing(db_session):
    ana_id, ana = _user(db_session, "estudiante", nombre="Ana")
    beto_id, _ = _user(db_session, "Estudiante", nombre="Beto")
    teacher_id, teacher = _user(db_session, "docente", nombre="Carla")
    _attempt(ana, section="m1-s1")
    _attempt(ana, section="m2-s1", answers=[{"question_index": 0, "correct": True}])
    _complete(ana, activity="lectura")
    _complete(ana, activity="video")

    response = client.get("/api/analytics/students", headers=teacher)

    assert response.status_code == 200
    body = response.json()
    by_id = {s["user_id"]: s for s in body["students"]}
    assert body["count"] == len(body["students"])
    # La docente no es estudiante; el rol se compara sin mayúsculas.
    assert teacher_id not in by_id
    assert by_id[ana_id] == {
        "user_id": ana_id,
        "nombre": "Ana",
        "correo": by_id[ana_id]["correo"],
        "answered": 3,
        "correct": 2,
        "failed": 1,
        "sections_touched": 2,
        "activities_done": 2,
        "accuracy": 0.6667,
    }
    assert by_id[beto_id]["answered"] == 0
    assert by_id[beto_id]["activities_done"] == 0
    assert by_id[beto_id]["accuracy"] == 0.0
    names = [s["nombre"] for s in body["students"]]
    assert names == sorted(names)


# --- borrar lo registrado ------------------------------------------------------


def test_a_student_cannot_clear_the_recorded_answers(db_session):
    _, student = _user(db_session, "estudiante")
    _attempt(student)

    response = client.delete("/api/analytics/attempts", headers=student)

    assert response.status_code == 403
    assert db_session.query(QuizAnswer).count() == 2


def test_the_teacher_clears_one_section_and_leaves_the_rest(db_session):
    _, student = _user(db_session, "estudiante")
    _, teacher = _user(db_session, "docente")
    _attempt(student, section="m1-s1")
    _attempt(student, section="m2-s1")
    _complete(student, section="m1-s1")
    _complete(student, section="m2-s1")

    response = client.delete("/api/analytics/attempts?section_id=m1-s1", headers=teacher)

    assert response.status_code == 200
    assert response.json() == {"removed": 3}
    assert {r.section_id for r in db_session.query(QuizAnswer)} == {"m2-s1"}
    assert {r.section_id for r in db_session.query(ActivityCompletion)} == {"m2-s1"}


def test_the_teacher_can_clear_everything_at_once(db_session):
    _, student = _user(db_session, "estudiante")
    _, teacher = _user(db_session, "docente")
    _attempt(student, section="m1-s1")
    _complete(student, section="m2-s1")

    response = client.delete("/api/analytics/attempts", headers=teacher)

    assert response.json() == {"removed": 3}
    assert db_session.query(QuizAnswer).count() == 0
    assert db_session.query(ActivityCompletion).count() == 0
