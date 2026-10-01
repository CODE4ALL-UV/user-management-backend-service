"""Lo que este microservicio aporta al API Gateway.

El gateway (repo Back-end) llama a `register(app)` de cada servicio, y el
`main.py` de este paquete hace lo mismo para arrancarlo solo. Así las rutas se
declaran una sola vez, se arranque como se arranque.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from user_management_service.presentation.api.auth_routes import router as auth_router
from user_management_service.presentation.api.upload_routes import (
    UPLOAD_DIR,
    router as upload_router,
)


def register(app: FastAPI) -> None:
    app.include_router(auth_router)
    app.include_router(upload_router)

    # Las fotos de perfil: el login devuelve `photo_url` como /uploads/<archivo>.
    app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
