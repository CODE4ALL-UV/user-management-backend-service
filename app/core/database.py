import os
from sqlalchemy import create_engine
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
