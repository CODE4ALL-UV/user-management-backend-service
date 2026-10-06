import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
app_dir_str = str(APP_DIR)
if app_dir_str not in sys.path:
    sys.path.insert(0, app_dir_str)

from app.infrastructure.database.connection import get_db
from core.database import create_tables, ensure_quiz_answer_columns, ensure_user_role_column


def prepare_database() -> None:
    create_tables()
    ensure_user_role_column()
    ensure_quiz_answer_columns()
