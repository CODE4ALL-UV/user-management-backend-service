import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
APP_DIR = PROJECT_ROOT / "app"

for directory in (PROJECT_ROOT, APP_DIR):
    directory_str = str(directory)
    if directory_str not in sys.path:
        sys.path.insert(0, directory_str)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.database import create_tables, ensure_user_role_column
from presentation.api.auth_routes import router as auth_router

create_tables()
ensure_user_role_column()

app = FastAPI(
    title="User Management Backend Service",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

@app.get("/")
def read_root():
    return {"status": "online", "message": "¡Servidor conectado con éxito! 🚀"}