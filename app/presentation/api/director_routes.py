from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from infrastructure.database.user_repository_impl import UserRepositoryImpl
from infrastructure.database.connection import get_db
from core.security import decode_access_token

router = APIRouter(prefix="/api/director", tags=["Director"])


class PerformanceCreateRequest(BaseModel):
    usuario_id: int | None = None
    lesson_name: str
    score: int = 0
    failed: int = 0
    good: int = 0
    excellent: int = 0


def _require_director(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Simple dependency para validar JWT y confirmar rol director."""
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta token de autorización")

    token = authorization.split(" ")[-1]
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    user_id = int(payload.get("sub")) if payload.get("sub") else None
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin usuario")

    repo = UserRepositoryImpl(db)
    user = repo.get_user_by_id(user_id)
    if not user or getattr(user, "rol", "") != "director":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requiere rol director")

    return user


@router.get("/students")
def get_students(db: Session = Depends(get_db), _director=Depends(_require_director)):
    repo = UserRepositoryImpl(db)
    students = repo.list_students()
    return [{"id_usuario": s.id_usuario, "nombre": s.nombre, "correo": s.correo, "foto_path": getattr(s, "foto_path", None)} for s in students]


@router.get("/performances")
def get_performances(db: Session = Depends(get_db), _director=Depends(_require_director)):
    repo = UserRepositoryImpl(db)
    rows = repo.get_all_performances()
    results = []
    for r in rows:
        results.append({
            "id": r.id,
            "usuario_id": r.usuario_id,
            "lesson_name": r.lesson_name,
            "score": r.score,
            "failed": r.failed,
            "good": r.good,
            "excellent": r.excellent,
            "created_at": str(r.created_at),
        })
    return results


@router.get("/performances/aggregate")
def get_aggregate(db: Session = Depends(get_db), _director=Depends(_require_director)):
    repo = UserRepositoryImpl(db)
    return repo.aggregate_by_lesson()


@router.get("/performances/average")
def get_average(db: Session = Depends(get_db), _director=Depends(_require_director)):
    repo = UserRepositoryImpl(db)
    return repo.aggregate_avg_by_lesson()


@router.post("/performances", status_code=status.HTTP_201_CREATED)
def create_performance(payload: PerformanceCreateRequest, db: Session = Depends(get_db), _director=Depends(_require_director)):
    repo = UserRepositoryImpl(db)
    new = repo.create_performance(payload.dict())
    return {"id": new.id, "lesson_name": new.lesson_name}
