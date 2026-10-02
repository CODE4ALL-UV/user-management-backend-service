from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
import hashlib
import hmac
import secrets

import requests

# Dependencias para verificar ID token de Google
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
import os

# Importaciones de tu propia arquitectura
from user_management_service.application.use_cases.create_user import CreateUserUseCase
from user_management_service.application.use_cases.login_user import LoginUserUseCase
from user_management_service.application.use_cases import password_reset
from user_management_service.core import mailer
from user_management_service.infrastructure.database.user_repository_impl import UserRepositoryImpl
from neon_storage import get_db

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

# Sin versión: Facebook usa la que tenga fijada la app en su panel. Con una
# versión escrita aquí, el código dejaría de funcionar cuando caducara.
FACEBOOK_GRAPH_URL = "https://graph.facebook.com"

DEFAULT_FRONTEND_URL = "https://code4all-web.onrender.com"


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


def _session_for(db: Session, email: str, name: str) -> dict:
    """Abre sesión con la cuenta de ese correo, o la crea como estudiante.

    Lo comparten Google y Facebook: los dos ya comprobaron el correo.
    """
    repo = UserRepositoryImpl(db)

    user = repo.get_user_by_email(email=email)
    if user:
        from user_management_service.core.security import create_access_token
        token = create_access_token(
            data={
                "sub": str(user.id_usuario),
                "email": user.correo,
                "rol": user.rol,
            }
        )

        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user.id_usuario,
            "email": user.correo,
            "nombre": user.nombre,
            "rol": user.rol,
            "photo_url": getattr(user, "foto_path", None) or "",
        }

    # Una contraseña aleatoria para cumplir el NOT NULL de la tabla. Si algún
    # día quiere entrar con correo y contraseña, la puede cambiar con
    # «¿Olvidaste tu contraseña?».
    random_password = secrets.token_urlsafe(32)

    class _TmpRegister:
        def __init__(self, nombre, correo, password, tipo_discapacidad=None, rol=None):
            self.nombre = nombre
            self.correo = correo
            self.password = password
            self.tipo_discapacidad = tipo_discapacidad
            self.rol = rol

    # Siempre como estudiante: docente y director necesitan su código de
    # invitación, y por esta vía no se pide.
    tmp = _TmpRegister(nombre=name or email.split("@")[0], correo=email, password=random_password, tipo_discapacidad=None, rol="estudiante")

    use_case = CreateUserUseCase(user_repository=repo)
    created = use_case.execute(tmp)

    from user_management_service.core.security import create_access_token
    token = create_access_token(
        data={
            "sub": str(created["id_usuario"]),
            "email": created["correo"],
            "rol": created["rol"],
        }
    )

    return {"access_token": token, "token_type": "bearer", "user_id": created["id_usuario"], "email": created["correo"], "nombre": created["nombre"], "rol": created["rol"]}


@router.post("/google")
def google_sign_in(request_data: IdTokenRequest, db: Session = Depends(get_db)):
    """
    Entrar o registrarse con Google: POST /api/auth/google

    Recibe el access token (web) o el ID token (móvil), comprueba con Google
    que es de esta app y que el correo está verificado, y abre sesión con esa
    cuenta o la crea.
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

        return _session_for(db, email, name)

    except ValueError as e:
        # Errores lanzados por google-auth al verificar el token
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error en servidor: {str(e)}")


class FacebookRequest(BaseModel):
    code: str
    redirect_uri: str


@router.post("/facebook")
def facebook_sign_in(request_data: FacebookRequest, db: Session = Depends(get_db)):
    """
    Entrar o registrarse con Facebook: POST /api/auth/facebook

    La app manda a la persona a Facebook y Facebook la devuelve con un
    `code`. Aquí se canjea ese código por un token usando la clave secreta de
    la app, que nunca sale del servidor. Así el token es por fuerza de
    Code4All: un código de otra app no se puede canjear con nuestra clave.
    """
    app_id = os.getenv("FACEBOOK_APP_ID", "").strip()
    app_secret = os.getenv("FACEBOOK_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El inicio con Facebook no está configurado en el servidor.",
        )

    try:
        exchange = requests.get(
            f"{FACEBOOK_GRAPH_URL}/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "redirect_uri": request_data.redirect_uri,
                "code": request_data.code,
            },
            timeout=10,
        )
        access_token = exchange.json().get("access_token") if exchange.status_code == 200 else None
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Facebook no aceptó el inicio de sesión. Vuelve a intentarlo.",
            )

        # appsecret_proof: Facebook rechaza la llamada si el token no se
        # emitió para esta app.
        proof = hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()
        profile = requests.get(
            f"{FACEBOOK_GRAPH_URL}/me",
            params={
                "fields": "id,name,email",
                "access_token": access_token,
                "appsecret_proof": proof,
            },
            timeout=10,
        )
        if profile.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No se pudo leer tu perfil de Facebook. Vuelve a intentarlo.",
            )
        data = profile.json()
    except HTTPException:
        raise
    except requests.RequestException:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo hablar con Facebook. Vuelve a intentarlo en un momento.",
        )

    # Facebook solo entrega el correo principal, que ya confirmó. Las cuentas
    # abiertas con un teléfono no tienen, y quien no da permiso tampoco.
    email = (data.get("email") or "").strip()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Tu cuenta de Facebook no comparte un correo electrónico. "
                "Entra con Google o regístrate con tu correo."
            ),
        )

    return _session_for(db, email, data.get("name") or "")


class ForgotPasswordRequest(BaseModel):
    correo: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


FORGOT_PASSWORD_REPLY = (
    "Si hay una cuenta con ese correo, te enviamos un enlace para cambiar la "
    "contraseña. Revisa también la carpeta de spam."
)


@router.post("/password/forgot")
def forgot_password(request_data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Pedir el enlace para cambiar la contraseña: POST /api/auth/password/forgot

    Responde lo mismo haya o no una cuenta con ese correo.
    """
    if not mailer.mail_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La recuperación de contraseña no está configurada en el servidor.",
        )

    frontend_url = os.getenv("FRONTEND_URL", "").strip() or DEFAULT_FRONTEND_URL
    password_reset.request_reset(UserRepositoryImpl(db), str(request_data.correo), frontend_url)
    return {"detail": FORGOT_PASSWORD_REPLY}


@router.post("/password/reset")
def reset_password(request_data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """
    Elegir la contraseña nueva con el enlace del correo: POST /api/auth/password/reset
    """
    try:
        password_reset.reset_password(
            UserRepositoryImpl(db), request_data.token, request_data.password
        )
    except password_reset.InvalidResetLink:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enlace ya no sirve: caducó o ya se usó. Pide uno nuevo.",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {"detail": "Listo. Ya puedes iniciar sesión con tu contraseña nueva."}
