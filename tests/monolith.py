"""Carga el monolito (app/ y main.py) en el mismo proceso que el microservicio.

neon_storage importa los modelos como `app.infrastructure.database.models`, y
el monolito, que pone app/ en sys.path, como `infrastructure.database.models`.
Es el mismo archivo con dos nombres: si se ejecutara dos veces, SQLAlchemy
diría que las tablas ya están definidas. Por eso el segundo nombre se apunta
al módulo que ya está cargado, en lugar de cargarlo otra vez.
"""

import importlib
import sys

import neon_storage  # noqa: F401  Deja app/ en sys.path y los modelos cargados.

_SAME_FILE_TWO_NAMES = (
    "infrastructure.database.models",
    "infrastructure.database.connection",
)


def load_main():
    """Devuelve el módulo `main` del monolito, con su `app` de FastAPI."""
    for name in _SAME_FILE_TWO_NAMES:
        sys.modules.setdefault(name, importlib.import_module("app." + name))
    return importlib.import_module("main")
