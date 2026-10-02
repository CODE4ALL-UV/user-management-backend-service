"""Quién puede escribir en el temario.

El problema que resuelve: la aplicación guarda el rol en el dispositivo, pero
el dispositivo no es de fiar. Si el servidor creyera un rol que le manda el
cliente, cualquier estudiante podría reescribir el curso de todos con una
petición hecha a mano.

Por eso el rol se lee del token que firma este mismo servidor al iniciar
sesión. El cliente no puede fabricarlo ni cambiarle el rol: no tiene la clave.
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.security import decode_access_token

# auto_error=False para poder dar un mensaje en castellano en vez del 403 seco
# de FastAPI cuando sencillamente no se mandó la cabecera.
_scheme = HTTPBearer(auto_error=False)

# Roles que pueden editar el temario.
EDITOR_ROLES = {"docente", "director"}


class Caller:
    """Quien está haciendo la petición, según el token."""

    def __init__(self, email: str, role: str, user_id: Optional[int] = None):
        self.email = email
        self.role = role
        self.user_id = user_id

    @property
    def can_edit_course(self) -> bool:
        return self.role in EDITOR_ROLES


def current_caller(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_scheme),
) -> Caller:
    """Saca del token quién llama. Falla si no hay token o no vale."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta la sesión. Vuelve a iniciar sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión caducó o no es válida. Vuelve a iniciar sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # El token lo firma este servidor al iniciar sesión: `sub` lleva el id del
    # usuario y `email` su correo.
    email = payload.get("email") or ""
    role = str(payload.get("rol") or payload.get("role") or "").lower()

    user_id = payload.get("sub")
    try:
        user_id = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        user_id = None

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión no identifica a nadie.",
        )

    return Caller(email=email, role=role, user_id=user_id)


def require_course_editor(caller: Caller = Depends(current_caller)) -> Caller:
    """Deja pasar solo a quien puede editar el temario."""
    if not caller.can_edit_course:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un docente puede editar el contenido del curso.",
        )
    return caller
