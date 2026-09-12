"""El seguimiento que hace el director del trabajo docente.

Responde a tres preguntas distintas, y conviene no mezclarlas:

- **Qué ha hecho cada docente**: qué secciones tocó y cuándo. Sale de lo que
  ya se guardaba al editar, no hace falta que nadie lo apunte a mano.
- **Si el contenido está bien**: una revisión por sección, aprobada u
  observada, con su comentario.
- **Cómo lo está haciendo**: una valoración con nota y comentario, guardada
  con su fecha para poder ver si mejora.

Todo esto es solo para el director. Y el rol se comprueba contra la base de
datos, no contra el token: a alguien que deja de ser director se le corta el
acceso en el momento, sin esperar a que caduque su sesión.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.security import decode_access_token
from infrastructure.database.connection import get_db
from infrastructure.database.models import (
    ContentReview,
    CourseOverride,
    TeacherReview,
    Usuario,
)

router = APIRouter(prefix="/api/oversight", tags=["Dirección"])

# Estados en los que puede quedar la revisión de una sección.
APPROVED = "aprobado"
FLAGGED = "observado"
REVIEW_STATES = {APPROVED, FLAGGED}

MIN_SCORE = 1
MAX_SCORE = 5


def require_director(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Usuario:
    """Deja pasar solo a quien es director **ahora mismo**."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta la sesión. Vuelve a iniciar sesión.",
        )

    try:
        payload = decode_access_token(authorization.split(" ")[-1])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión caducó o no es válida.",
        )

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión no identifica a nadie.",
        )

    user = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if user is None or (user.rol or "").lower() != "director":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta sección es solo para la dirección.",
        )

    return user


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


# --- qué ha hecho cada docente ---------------------------------------------


@router.get("/teachers")
def teachers(db: Session = Depends(get_db), _director: Usuario = Depends(require_director)):
    """Los docentes, con lo que han hecho y cómo se les ha valorado.

    Salen todos, también quien no ha tocado nada: ese dato es justo el que el
    director necesita ver.
    """
    docentes = (
        db.query(Usuario)
        .filter(func.lower(Usuario.rol) == "docente")
        .order_by(Usuario.nombre)
        .all()
    )

    # Lo editado sale de lo que ya se guardaba al editar el temario.
    edits = dict(
        (row.updated_by, (int(row.total or 0), row.ultimo))
        for row in db.query(
            CourseOverride.updated_by,
            func.count(CourseOverride.id).label("total"),
            func.max(CourseOverride.updated_at).label("ultimo"),
        )
        .group_by(CourseOverride.updated_by)
        .all()
    )

    out = []
    for docente in docentes:
        mine = edits.get(docente.correo)

        reviews = (
            db.query(TeacherReview)
            .filter(TeacherReview.docente_id == docente.id_usuario)
            .order_by(TeacherReview.created_at.desc())
            .all()
        )
        scores = [r.score for r in reviews]

        out.append(
            {
                "user_id": docente.id_usuario,
                "nombre": docente.nombre,
                "correo": docente.correo,
                "edits": mine[0] if mine else 0,
                "last_edit": _iso(mine[1]) if mine else None,
                "reviews": len(reviews),
                "last_score": scores[0] if scores else None,
                "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
            }
        )

    return {"count": len(out), "teachers": out}


@router.get("/teachers/{user_id}/activity")
def teacher_activity(
    user_id: int,
    db: Session = Depends(get_db),
    _director: Usuario = Depends(require_director),
):
    """Qué secciones ha tocado un docente, y cuándo.

    Es su rastro real de trabajo: no hay que fiarse de lo que diga nadie, sale
    de las propias ediciones guardadas.
    """
    docente = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if docente is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ese docente no existe.",
        )

    rows = (
        db.query(CourseOverride)
        .filter(CourseOverride.updated_by == docente.correo)
        .order_by(CourseOverride.updated_at.desc())
        .all()
    )

    # El estado de revisión de cada sección que tocó, para ver de un vistazo
    # qué le falta por aprobar.
    reviews = dict(
        (row.section_id, row)
        for row in db.query(ContentReview)
        .filter(ContentReview.section_id.in_([r.target_id for r in rows] or [""]))
        .all()
    )

    items = []
    for row in rows:
        review = reviews.get(row.target_id)

        # Una revisión anterior al último cambio ya no dice nada del contenido
        # que hay ahora. Vale más avisarlo que dejar un "aprobado" engañoso.
        stale = bool(
            review
            and review.reviewed_at
            and row.updated_at
            and review.reviewed_at < row.updated_at
        )

        items.append(
            {
                "scope": row.scope,
                "target_id": row.target_id,
                "updated_at": _iso(row.updated_at),
                "review_status": review.status if review else None,
                "review_comment": review.comment if review else None,
                "review_outdated": stale,
            }
        )

    return {
        "user_id": docente.id_usuario,
        "nombre": docente.nombre,
        "correo": docente.correo,
        "count": len(items),
        "items": items,
    }


# --- valorar al docente -----------------------------------------------------


class ReviewIn(BaseModel):
    docente_id: int
    score: int = Field(..., ge=MIN_SCORE, le=MAX_SCORE)
    comment: str = ""


@router.post("/reviews", status_code=status.HTTP_201_CREATED)
def create_review(
    payload: ReviewIn,
    db: Session = Depends(get_db),
    director: Usuario = Depends(require_director),
):
    """Guarda una valoración del docente.

    Se añade al histórico en vez de sustituir la anterior: evaluar sirve para
    ver si alguien mejora, y para eso hacen falta las dos.
    """
    docente = (
        db.query(Usuario).filter(Usuario.id_usuario == payload.docente_id).first()
    )
    if docente is None or (docente.rol or "").lower() != "docente":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ese docente no existe.",
        )

    if not payload.comment.strip():
        # Una nota sin explicación no le dice al docente qué hacer distinto.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Escribe un comentario: la nota sola no explica nada.",
        )

    review = TeacherReview(
        docente_id=docente.id_usuario,
        director_id=director.id_usuario,
        score=payload.score,
        comment=payload.comment.strip()[:4000],
        created_at=datetime.now(timezone.utc),
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    return {
        "id": review.id,
        "docente_id": review.docente_id,
        "score": review.score,
        "comment": review.comment,
        "created_at": _iso(review.created_at),
    }


@router.get("/reviews/{user_id}")
def reviews_of(
    user_id: int,
    db: Session = Depends(get_db),
    _director: Usuario = Depends(require_director),
):
    """El histórico de valoraciones de un docente, de la más nueva a la más vieja."""
    rows = (
        db.query(TeacherReview)
        .filter(TeacherReview.docente_id == user_id)
        .order_by(TeacherReview.created_at.desc())
        .all()
    )

    return {
        "count": len(rows),
        "reviews": [
            {
                "id": row.id,
                "score": row.score,
                "comment": row.comment,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ],
    }


# --- revisar el contenido ---------------------------------------------------


class ContentReviewIn(BaseModel):
    section_id: str
    status: str
    comment: str = ""


@router.put("/content/{section_id}")
def review_content(
    section_id: str,
    payload: ContentReviewIn,
    db: Session = Depends(get_db),
    director: Usuario = Depends(require_director),
):
    """Aprueba u observa el contenido de una sección.

    Solo hay una revisión por sección: lo que importa es el estado actual. Si
    el docente cambia la sección después, la revisión queda marcada como
    anterior al cambio en lugar de seguir diciendo «aprobado».
    """
    if payload.status not in REVIEW_STATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Estado no válido. Solo: {', '.join(sorted(REVIEW_STATES))}.",
        )
    if payload.status == FLAGGED and not payload.comment.strip():
        # Observar sin decir qué está mal deja al docente sin saber qué tocar.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Si pones observaciones, explica cuáles.",
        )

    row = (
        db.query(ContentReview)
        .filter(ContentReview.section_id == section_id)
        .first()
    )
    now = datetime.now(timezone.utc)

    if row is None:
        row = ContentReview(
            section_id=section_id,
            status=payload.status,
            comment=payload.comment.strip()[:4000],
            director_id=director.id_usuario,
            reviewed_at=now,
        )
        db.add(row)
    else:
        row.status = payload.status
        row.comment = payload.comment.strip()[:4000]
        row.director_id = director.id_usuario
        row.reviewed_at = now

    db.commit()
    db.refresh(row)

    return {
        "section_id": row.section_id,
        "status": row.status,
        "comment": row.comment,
        "reviewed_at": _iso(row.reviewed_at),
    }


@router.get("/content")
def content_reviews(
    db: Session = Depends(get_db),
    _director: Usuario = Depends(require_director),
):
    """Todas las revisiones de contenido, con aviso de cuáles se quedaron viejas."""
    rows = db.query(ContentReview).all()

    # Cuándo se tocó por última vez cada sección, para detectar revisiones que
    # el docente ya dejó atrás.
    edits = dict(
        (row.target_id, row.updated_at)
        for row in db.query(CourseOverride)
        .filter(CourseOverride.scope == "section")
        .all()
    )

    items = []
    for row in rows:
        edited_at = edits.get(row.section_id)
        stale = bool(edited_at and row.reviewed_at and row.reviewed_at < edited_at)

        items.append(
            {
                "section_id": row.section_id,
                "status": row.status,
                "comment": row.comment,
                "reviewed_at": _iso(row.reviewed_at),
                "outdated": stale,
            }
        )

    return {"count": len(items), "items": items}
