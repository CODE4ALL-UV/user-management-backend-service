import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
APP_DIR = PROJECT_ROOT / "app"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

for directory in (PROJECT_ROOT, APP_DIR):
    directory_str = str(directory)
    if directory_str not in sys.path:
        sys.path.insert(0, directory_str)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.database import create_tables, ensure_user_role_column, ensure_quiz_answer_columns
from presentation.api.auth_routes import router as auth_router
from presentation.api.upload_routes import router as upload_router
from presentation.api.director_routes import router as director_router
from presentation.api.youtube_routes import router as youtube_router
from presentation.api.modules_routes import router as modules_router
from presentation.api.sign_routes import router as sign_router
from presentation.api.course_content_routes import router as course_content_router
from presentation.api.analytics_routes import router as analytics_router
from presentation.api.director_oversight_routes import router as oversight_router
from presentation.api.braille_routes import router as braille_router

# Preparar la base al arrancar, pero sin que un fallo tumbe el servicio.
#
# Neon se duerme cuando lleva un rato sin uso. Si justo esta dormida cuando el
# servidor arranca, esto tardaria o fallaria, y sin proteccion el despliegue
# entero se daria por fallido aunque la aplicacion este perfecta. Se registra
# el problema y se sigue: la primera peticion de verdad reabrira la conexion.
try:
    create_tables()
    ensure_user_role_column()
    ensure_quiz_answer_columns()
except Exception as exc:  # pragma: no cover - depende del entorno
    print(f"[arranque] No se pudo preparar la base de datos: {exc}")
    print("[arranque] El servicio arranca igualmente; se reintentara al usarla.")

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
app.include_router(upload_router)
app.include_router(director_router)
app.include_router(youtube_router)
app.include_router(modules_router)
app.include_router(sign_router)
app.include_router(course_content_router)
app.include_router(analytics_router)
app.include_router(oversight_router)
app.include_router(braille_router)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

@app.get("/")
def read_root():
    return {"status": "online", "message": "¡Servidor conectado con éxito! 🚀"}