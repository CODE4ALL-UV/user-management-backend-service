import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# Carga obligatoria de las variables del archivo .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("⚠️ No se encontró la variable DATABASE_URL en el archivo .env. Revisa que esté creada y guardada.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def create_tables() -> None:
    """Create all SQLAlchemy model tables."""
    Base.metadata.create_all(bind=engine)


def ensure_user_role_column() -> None:
    """Agrega las columnas necesarias a la tabla Usuario si aún no existen."""
    inspector = inspect(engine)
    if "Usuario" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("Usuario")}

    if "rol" not in columns:
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE "Usuario" ADD COLUMN "rol" VARCHAR(20) DEFAULT \'estudiante\''))

    if "foto_path" not in columns:
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE "Usuario" ADD COLUMN "foto_path" VARCHAR(500) NULL'))


def ensure_quiz_answer_columns() -> None:
    """Agrega a QuizAnswer las columnas nuevas si la tabla ya existia.

    create_all() crea tablas, pero no toca las que ya estan. Sin esto, medir
    el tiempo de respuesta fallaria en cualquier base donde la tabla se creo
    antes de anadir la columna: justo la de quien ya venia usando la app.
    """
    inspector = inspect(engine)
    if "QuizAnswer" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("QuizAnswer")}

    if "elapsed_ms" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text('ALTER TABLE "QuizAnswer" ADD COLUMN "elapsed_ms" INTEGER NULL')
            )
