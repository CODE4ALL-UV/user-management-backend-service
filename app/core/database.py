import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# Carga obligatoria de las variables del archivo .env
load_dotenv()

def _clean_database_url(raw: str | None) -> str:
    """Deja la cadena de conexion utilizable, o explica que le falta.

    Al copiarla de un archivo .env es facil arrastrar las comillas, y entonces
    SQLAlchemy falla con «Could not parse SQLAlchemy URL», que no dice a nadie
    que el problema son dos comillas. Aqui se quitan y, si aun asi no sirve, se
    dice en castellano que esta mal.
    """
    if raw is None:
        raise ValueError(
            "Falta la variable DATABASE_URL. En Render se escribe en "
            "Environment; en local, en el archivo .env."
        )

    url = raw.strip()

    # Comillas arrastradas al copiar la linea entera del .env.
    for quote in ('"', "'"):
        if len(url) >= 2 and url.startswith(quote) and url.endswith(quote):
            url = url[1:-1].strip()

    if not url:
        raise ValueError(
            "La variable DATABASE_URL esta vacia. Copia la cadena de "
            "conexion de Neon, sin comillas."
        )

    # Algunos paneles dan la forma antigua; SQLAlchemy quiere postgresql://.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    if "://" not in url:
        raise ValueError(
            "DATABASE_URL no parece una cadena de conexion: deberia empezar "
            f"por postgresql://. Llego esto: {url[:24]}..."
        )

    return url


DATABASE_URL = _clean_database_url(os.getenv("DATABASE_URL"))

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
