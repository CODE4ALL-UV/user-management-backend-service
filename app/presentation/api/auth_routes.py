from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
import secrets

import requests

# Dependencias para verificar ID token de Google
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
import os

# Importaciones de tu propia arquitectura
from application.use_cases.create_user import CreateUserUseCase
from application.use_cases.login_user import LoginUserUseCase
from infrastructure.database.user_repository_impl import UserRepositoryImpl
from infrastructure.database.connection import get_db  # Asegúrate de que esta ruta coincida con la de tu proyecto

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


def _parse_dev_identity(id_token: str) -> tuple[str, str]:
    """Acepta un token local del estilo dev:correo@dominio.com o dev:correo@dominio.com:Nombre."""
    prefix = "dev:"
    if not id_token.startswith(prefix):
        raise ValueError("Token no válido para modo desarrollo")

    payload = id_token[len(prefix):].strip()
    if not payload:
        raise ValueError("El token local está vacío")

    parts = [part.strip() for part in payload.split(":", 2)]
    email = parts[0]
    if "@" not in email:
        raise ValueError("El token local debe incluir un correo válido")

    name = parts[1] if len(parts) > 1 and parts[1] else email.split("@", 1)[0]
    return email, name


def _dev_login_enabled() -> bool:
    """Los tokens `dev:` solo valen si se piden a propósito, en local.

    Sin esta comprobación cualquiera podía enviar `dev:correo` al login con
    Google y entrar con la cuenta de esa persona, también la de la dirección.
    """
    return os.getenv("ALLOW_DEV_LOGIN", "").strip().lower() in {"1", "true", "yes"}


STAFF_ROLES = {"docente", "director"}


def _check_staff_invitation(rol: str | None, code: str | None) -> None:
    """Docente y director solo se registran con el código de su rol.

    Antes el rol se elegía en el formulario y el servidor lo aceptaba tal
    cual: cualquiera podía darse de alta como director y ver a todos los
    estudiantes, o como docente y reescribir el curso.

    Los códigos se configuran en el servidor (DOCENTE_SIGNUP_CODE y
    DIRECTOR_SIGNUP_CODE). Si no hay código para un rol, ese registro queda
    cerrado. El rol de estudiante no necesita nada.
    """
    requested = (rol or "estudiante").strip().lower()
    if requested not in STAFF_ROLES:
        return

    expected = os.getenv(f"{requested.upper()}_SIGNUP_CODE", "").strip()
    given = (code or "").strip()
    if not expected or not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Para registrarte como {requested} necesitas el código de "
                "invitación que entrega la coordinación del curso."
            ),
        )


def _token_kind(token: str) -> str:
    token = (token or '').strip()
    if not token:
        return 'empty'
    if token.startswith('dev:'):
        return 'dev_token'
    if token.startswith('ya29.'):
        return 'access_token'
    if token.count('.') >= 2:
        return 'id_token'
    return 'unknown'


# Estructura de datos que esperamos recibir en el JSON desde Flutter
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    nombre: str
    correo: EmailStr
    password: str
    tipo_discapacidad: int | None = None
    rol: str | None = None
    # Solo para docente o director: el que da la coordinación.
    codigo_invitacion: str | None = None


class IdTokenRequest(BaseModel):
    id_token: str | None = None
    access_token: str | None = None


def _extract_google_token(request_data: IdTokenRequest) -> str:
    if request_data.access_token:
        return request_data.access_token
    return request_data.id_token or ''


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_endpoint(request_data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Ruta HTTP que consumirá Flutter: POST /api/auth/register
    """
    _check_staff_invitation(request_data.rol, request_data.codigo_invitacion)

    try:
        repo = UserRepositoryImpl(db)
        use_case = CreateUserUseCase(user_repository=repo)
        response_data = use_case.execute(request_data)
        return response_data

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en el servidor: {str(e)}"
        )


@router.post("/login")
def login_endpoint(request_data: LoginRequest, db: Session = Depends(get_db)):
    """
    Ruta HTTP que consumirá Flutter: POST /api/auth/login
    """
    try:
        # 1. Instanciar el repositorio con la sesión real de NeonDB
        repo = UserRepositoryImpl(db)
        
        # 2. Instanciar y ejecutar el Caso de Uso de Login
        use_case = LoginUserUseCase(user_repository=repo)
        response_data = use_case.execute(
            email=request_data.email, 
            password_from_flutter=request_data.password
        )
        
        return response_data

    except HTTPException as e:
        raise e
    except ValueError as e:
        # Si la contraseña es incorrecta o el usuario no existe
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        # Cualquier otro error inesperado
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en el servidor: {str(e)}"
        )


GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _google_client_ids() -> set[str]:
    """Los Client ID de Google de la app. Se pueden poner varios, con comas."""
    raw = os.getenv("GOOGLE_CLIENT_ID", "")
    ids = {part.strip() for part in raw.split(",") if part.strip()}
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El inicio con Google no está configurado en el servidor (falta GOOGLE_CLIENT_ID).",
        )
    return ids


def _google_identity_from_access_token(token: str, client_ids: set[str]) -> tuple[str, str, bool]:
    """Correo, nombre y si Google verificó el correo, a partir de un access token.

    Antes se preguntaba directamente a userinfo, que responde a cualquier
    access token de Google, sea de la app que sea. Una página cualquiera con
    «Iniciar sesión con Google» podía usar el token de sus visitantes para
    entrar en Code4All como ellos. tokeninfo dice para qué app se emitió.
    """
    info = requests.get(GOOGLE_TOKENINFO_URL, params={"access_token": token}, timeout=10)
    if info.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de Google no válido")
    data = info.json()

    if data.get("aud") not in client_ids and data.get("azp") not in client_ids:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ese inicio de sesión de Google no es de Code4All.",
        )

    email = data.get("email")
    verified = str(data.get("email_verified", "")).lower() == "true"

    name = ""
    profile = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if profile.status_code == 200:
        payload = profile.json()
        name = payload.get("name") or payload.get("given_name") or ""

    return email, name, verified


def _google_identity_from_id_token(token: str, client_ids: set[str]) -> tuple[str, str, bool]:
    request = google_requests.Request()
    # verify_oauth2_token sin audience aceptaba ID tokens de cualquier app.
    idinfo = google_id_token.verify_oauth2_token(token, request)
    if idinfo.get("aud") not in client_ids:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ese inicio de sesión de Google no es de Code4All.",
        )

    email = idinfo.get("email")
    name = idinfo.get("name") or idinfo.get("given_name") or ""
    verified = idinfo.get("email_verified")
    if verified is None:
        verified = idinfo.get("verified_email")
    return email, name, verified is True or str(verified).lower() == "true"


@router.post("/google")
def google_sign_in(request_data: IdTokenRequest, db: Session = Depends(get_db)):
    """
    Endpoint que recibe `id_token` proveniente del cliente (Flutter).
    Flujo:
      1) Verificar el id_token con las APIs de Google.
      2) Extraer `email` y `name`.
      3) Si el usuario existe -> generar JWT (login).
      4) Si no existe -> crear usuario (registro) y generar JWT.
    """
    try:
        token_value = _extract_google_token(request_data)
        token_type = _token_kind(token_value)

        if token_type == 'dev_token':
            if not _dev_login_enabled():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token de Google no válido",
                )
            email, name = _parse_dev_identity(token_value)
            email_verified = True
        elif token_type == 'access_token':
            email, name, email_verified = _google_identity_from_access_token(
                token_value, _google_client_ids()
            )
        else:
            email, name, email_verified = _google_identity_from_id_token(
                token_value, _google_client_ids()
            )

        # Antes solo se miraba con el ID token: con un access token entraba
        # también una cuenta de Google con el correo sin verificar.
        if not email_verified:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="El correo de Google no está verificado. Por favor verifica tu cuenta de Google.",
            )

        if not email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID token inválido: falta email")

        repo = UserRepositoryImpl(db)

        # 2) Buscar usuario existente
        existing_user = repo.get_user_by_email(email=email)
        if existing_user:
            # Generar token directamente para el usuario existente
            from core.security import create_access_token
            token = create_access_token(
                data={
                    "sub": str(existing_user.id_usuario),
                    "email": existing_user.correo,
                    "rol": existing_user.rol,
                }
            )

            return {
                "access_token": token,
                "token_type": "bearer",
                "user_id": existing_user.id_usuario,
                "email": existing_user.correo,
                "nombre": existing_user.nombre,
                "rol": existing_user.rol,
                "photo_url": getattr(existing_user, "foto_path", None) or "",
            }

        # 3) Si no existe, registrar uno nuevo usando el caso de uso existente
        # Generar una contraseña aleatoria para cumplir la restricción NOT NULL en la tabla
        random_password = secrets.token_urlsafe(32)

        # Construir un objeto similar al que espera CreateUserUseCase
        class _TmpRegister:
            def __init__(self, nombre, correo, password, tipo_discapacidad=None, rol=None):
                self.nombre = nombre
                self.correo = correo
                self.password = password
                self.tipo_discapacidad = tipo_discapacidad
                self.rol = rol

        tmp = _TmpRegister(nombre=name or email.split("@")[0], correo=email, password=random_password, tipo_discapacidad=None, rol="estudiante")

        use_case = CreateUserUseCase(user_repository=repo)
        created = use_case.execute(tmp)

        # Crear token para el nuevo usuario
        from core.security import create_access_token
        token = create_access_token(
            data={
                "sub": str(created["id_usuario"]),
                "email": created["correo"],
                "rol": created["rol"],
            }
        )

        return {"access_token": token, "token_type": "bearer", "user_id": created["id_usuario"], "email": created["correo"], "nombre": created["nombre"], "rol": created["rol"]}

    except ValueError as e:
        # Errores lanzados por google-auth al verificar el token
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error en servidor: {str(e)}")