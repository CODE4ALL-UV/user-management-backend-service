import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from neon_storage import get_db
from user_management_service.infrastructure.database.user_repository_impl import UserRepositoryImpl

router = APIRouter(prefix="/api/user", tags=["Usuario"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload-photo", status_code=status.HTTP_200_OK)
def upload_photo(
    file: Optional[UploadFile] = File(default=None),
    db: Session = Depends(get_db),
    user_id: Optional[int] = Form(default=None),
    user_id_query: Optional[int] = Query(default=None),
):
    effective_user_id = user_id if user_id is not None else user_id_query
    if effective_user_id is None:
        raise HTTPException(status_code=400, detail="No se recibió el id del usuario")

    if file is None or not getattr(file, "filename", None):
        raise HTTPException(status_code=400, detail="No se recibió ningún archivo")

    extension = Path(file.filename).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Formato no soportado")

    repo = UserRepositoryImpl(db)
    user = repo.get_user_by_id(effective_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    filename = f"{uuid.uuid4().hex}{extension}"
    destination = UPLOAD_DIR / filename

    try:
        contents = file.file.read()
        with destination.open("wb") as f:
            f.write(contents)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo guardar la imagen: {exc}") from exc

    relative_path = f"/uploads/{filename}"
    repo.update_photo_path(user_id=effective_user_id, photo_path=relative_path)

    return {
        "message": "Foto guardada correctamente",
        "photo_url": relative_path,
    }
