"""Las pruebas nunca tocan Neon.

Se fuerza una base SQLite temporal antes de importar nada: si DATABASE_URL
apuntara a Neon, una prueba que borra datos los borraría de verdad.

Los paquetes compartidos (neon_storage, user_management_service) se buscan en
los repos hermanos, así que esto funciona igual con los repos clonados uno al
lado del otro que dentro de services/ del gateway.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

for repo in [REPO_ROOT, *sorted(REPO_ROOT.parent.glob("*-backend-service"))]:
    if str(repo) not in sys.path:
        sys.path.append(str(repo))

_db_file = Path(tempfile.mkdtemp()) / "code4all-test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file.as_posix()}"


@pytest.fixture
def db_session():
    """Una sesión con la base SQLite temporal, con las tablas ya creadas.

    Las tablas se crean igual que al arrancar el servicio. Al terminar se
    borran los usuarios y tipos de discapacidad que dejó la prueba, para que
    ninguna dependa de lo que hizo otra.
    """
    from neon_storage import get_db, prepare_database
    from neon_storage.models import TipoDiscapacidad, Usuario

    sessions = get_db()
    db = next(sessions)
    # Este fixture borra filas: si la sesión no fuera la SQLite de pruebas,
    # mejor no seguir.
    if db.get_bind().url.get_backend_name() != "sqlite":
        sessions.close()
        pytest.fail("Las pruebas solo pueden usar la base SQLite temporal.")

    prepare_database()
    try:
        yield db
    finally:
        db.rollback()
        db.query(Usuario).delete()
        db.query(TipoDiscapacidad).delete()
        db.commit()
        sessions.close()
