"""El núcleo del monolito (app/core e app/infrastructure/database/connection).

La cadena de conexión que se copia de Neon, las columnas que se añaden a
bases antiguas al arrancar, la sesión que reciben las rutas y los tokens
que firma el servidor. Las bases antiguas se simulan con archivos SQLite
en la carpeta temporal de cada prueba; nunca se toca Neon.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from monolith import load_main

load_main()

import core.database as mono_database  # noqa: E402
import core.security as mono_security  # noqa: E402
import infrastructure.database.connection as mono_connection  # noqa: E402

# --- La cadena de conexión -----------------------------------------------------

NEON = "postgresql+psycopg2://ana:secreto@ep-algo.neon.tech/code4all?sslmode=require"


@pytest.mark.parametrize(
    "raw",
    [
        NEON,
        f'"{NEON}"',
        f"'{NEON}'",
        f"  {NEON}\n",
        # Copiada del panel, partida en varias líneas.
        "postgresql://ana:secreto@ep-algo.neon.tech/\n  code4all?sslmode=require",
        # La forma antigua que dan algunos paneles.
        "postgres://ana:secreto@ep-algo.neon.tech/code4all?sslmode=require",
    ],
)
def test_the_connection_string_is_cleaned_up_to_use_psycopg2(raw):
    assert mono_database._clean_database_url(raw) == NEON


def test_a_connection_string_that_names_its_driver_is_respected():
    url = "postgresql+asyncpg://ana@host/db"

    assert mono_database._clean_database_url(url) == url
    assert mono_database._clean_database_url("sqlite:///code4all.db") == "sqlite:///code4all.db"


@pytest.mark.parametrize(
    "raw, message",
    [
        (None, "Falta la variable DATABASE_URL"),
        ("", "esta vacia"),
        ('  ""  ', "esta vacia"),
        ("?sslmode=require&channel_binding=require", "solo trae la parte final"),
        ("sslmode=require", "solo trae la parte final"),
        ("ep-algo.neon.tech/code4all", "no parece una cadena de conexion"),
    ],
)
def test_a_broken_connection_string_is_explained_in_spanish(raw, message):
    with pytest.raises(ValueError, match=message):
        mono_database._clean_database_url(raw)


# --- Las columnas que se añaden a bases antiguas -------------------------------


@pytest.fixture
def old_engine(monkeypatch, tmp_path):
    """Un motor sobre una base vacía propia, en lugar de la de las pruebas."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'antigua.db').as_posix()}")
    monkeypatch.setattr(mono_database, "engine", engine)
    yield engine
    engine.dispose()


def _columns(engine, table):
    return {column["name"] for column in inspect(engine).get_columns(table)}


def test_an_empty_database_is_left_alone(old_engine):
    mono_database.ensure_user_role_column()
    mono_database.ensure_quiz_answer_columns()

    assert inspect(old_engine).get_table_names() == []


def test_an_old_user_table_gets_the_role_and_photo_columns(old_engine):
    with old_engine.begin() as connection:
        connection.execute(text(
            'CREATE TABLE "Usuario" (id_usuario INTEGER PRIMARY KEY, nombre VARCHAR(100), '
            'correo VARCHAR(100), password VARCHAR(255))'
        ))
        connection.execute(text(
            """INSERT INTO "Usuario" (nombre, correo, password) VALUES ('Ana', 'ana@x.co', 'h')"""
        ))

    mono_database.ensure_user_role_column()

    assert {"rol", "foto_path"} <= _columns(old_engine, "Usuario")
    with old_engine.connect() as connection:
        rol, foto = connection.execute(text('SELECT rol, foto_path FROM "Usuario"')).one()
    # Quien ya estaba registrado sigue siendo estudiante y no tiene foto.
    assert (rol, foto) == ("estudiante", None)


def test_only_the_missing_user_column_is_added(old_engine):
    with old_engine.begin() as connection:
        connection.execute(text(
            'CREATE TABLE "Usuario" (id_usuario INTEGER PRIMARY KEY, rol VARCHAR(20))'
        ))

    mono_database.ensure_user_role_column()
    # Una segunda vez no falla aunque las columnas ya estén.
    mono_database.ensure_user_role_column()

    assert _columns(old_engine, "Usuario") == {"id_usuario", "rol", "foto_path"}


def test_an_old_quiz_answer_table_gets_the_elapsed_time_column(old_engine):
    with old_engine.begin() as connection:
        connection.execute(text(
            'CREATE TABLE "QuizAnswer" (id INTEGER PRIMARY KEY, section_id VARCHAR(40))'
        ))
        connection.execute(text("""INSERT INTO "QuizAnswer" (section_id) VALUES ('m1-s1')"""))

    mono_database.ensure_quiz_answer_columns()
    mono_database.ensure_quiz_answer_columns()

    assert "elapsed_ms" in _columns(old_engine, "QuizAnswer")
    with old_engine.connect() as connection:
        # Lo respondido antes de medir queda sin tiempo, no con cero.
        assert connection.execute(text('SELECT elapsed_ms FROM "QuizAnswer"')).scalar() is None


def test_create_tables_builds_the_whole_schema_and_needs_no_patching(old_engine):
    mono_database.create_tables()
    before = {table: _columns(old_engine, table) for table in ("Usuario", "QuizAnswer")}

    mono_database.ensure_user_role_column()
    mono_database.ensure_quiz_answer_columns()

    assert {"Usuario", "QuizAnswer", "student_performance"} <= set(inspect(old_engine).get_table_names())
    assert {"rol", "foto_path"} <= before["Usuario"]
    assert "elapsed_ms" in before["QuizAnswer"]
    assert {table: _columns(old_engine, table) for table in before} == before


# --- La sesión que reciben las rutas --------------------------------------------


def test_get_db_yields_a_session_on_the_test_database_and_closes_it(monkeypatch):
    closed = []
    real_factory = mono_connection.SessionLocal

    def tracking_factory():
        session = real_factory()
        real_close = session.close
        monkeypatch.setattr(session, "close", lambda: (closed.append(True), real_close()))
        return session

    monkeypatch.setattr(mono_connection, "SessionLocal", tracking_factory)

    sessions = mono_connection.get_db()
    db = next(sessions)

    assert isinstance(db, Session)
    assert db.get_bind().url.get_backend_name() == "sqlite"
    assert closed == []
    sessions.close()
    assert closed == [True]


def test_get_db_closes_the_session_even_if_the_route_fails(monkeypatch):
    closed = []

    class FakeSession:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(mono_connection, "SessionLocal", FakeSession)
    sessions = mono_connection.get_db()
    next(sessions)

    with pytest.raises(RuntimeError):
        sessions.throw(RuntimeError("la ruta falló"))

    assert closed == [True]


# --- Contraseñas y tokens -------------------------------------------------------


def test_passwords_are_hashed_and_only_the_right_one_verifies():
    hashed = mono_security.get_password_hash("clave-correcta")

    assert hashed != "clave-correcta"
    assert hashed.startswith("$2")
    assert mono_security.verify_password("clave-correcta", hashed)
    assert not mono_security.verify_password("clave-equivocada", hashed)
    # Cada hash lleva su propia sal.
    assert mono_security.get_password_hash("clave-correcta") != hashed


def test_a_token_carries_its_data_and_expires_after_the_configured_minutes():
    data = {"sub": "7", "email": "ana@x.co", "rol": "docente"}

    token = mono_security.create_access_token(data)

    payload = mono_security.decode_access_token(token)
    assert {key: payload[key] for key in data} == data
    expected = datetime.now(timezone.utc) + timedelta(minutes=mono_security.ACCESS_TOKEN_EXPIRE_MINUTES)
    assert abs(payload["exp"] - expected.timestamp()) < 60
    # No se modifica el diccionario que se pasó.
    assert "exp" not in data


def test_a_token_can_have_its_own_lifetime():
    token = mono_security.create_access_token({"sub": "7"}, expires_delta=timedelta(minutes=5))

    payload = jwt.decode(token, mono_security.SECRET_KEY, algorithms=[mono_security.ALGORITHM])
    expected = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert abs(payload["exp"] - expected.timestamp()) < 60


@pytest.mark.parametrize(
    "token",
    [
        "no-es-un-jwt",
        jwt.encode({"sub": "7"}, "otra-clave", algorithm="HS256"),
        mono_security.create_access_token({"sub": "7"}, expires_delta=timedelta(seconds=-5)),
    ],
    ids=["basura", "otra-clave", "caducado"],
)
def test_a_garbage_forged_or_expired_token_cannot_be_decoded(token):
    with pytest.raises(ValueError, match="Token inválido"):
        mono_security.decode_access_token(token)
