from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
import secrets

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


class IdTokenRequest(BaseModel):
    id_token: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_endpoint(request_data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Ruta HTTP que consumirá Flutter: POST /api/auth/register
    """
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
        # 1) Verificar el token con la librería oficial
        request = google_requests.Request()
        # Si configuras GOOGLE_CLIENT_ID en el entorno, lo usamos como audience
        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        if google_client_id:
            idinfo = google_id_token.verify_oauth2_token(request_data.id_token, request, audience=google_client_id)
        else:
            idinfo = google_id_token.verify_oauth2_token(request_data.id_token, request)

        # idinfo contiene campos como 'email', 'name', 'sub' (google user id)
        email = idinfo.get("email")
        name = idinfo.get("name") or idinfo.get("given_name") or ""

        # Verificar que Google indique que el email está verificado
        # Algunos payloads usan 'email_verified' o 'verified_email'
        email_verified = idinfo.get("email_verified") if idinfo.get("email_verified") is not None else idinfo.get("verified_email")
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
            token = create_access_token(data={"sub": str(existing_user.id_usuario), "email": existing_user.correo})

            return {
                "access_token": token,
                "token_type": "bearer",
                "user_id": existing_user.id_usuario,
                "email": existing_user.correo,
                "nombre": existing_user.nombre,
                "rol": existing_user.rol,
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
        token = create_access_token(data={"sub": str(created["id_usuario"]), "email": created["correo"]})

        return {"access_token": token, "token_type": "bearer", "user_id": created["id_usuario"], "email": created["correo"], "nombre": created["nombre"], "rol": created["rol"]}

    except ValueError as e:
        # Errores lanzados por google-auth al verificar el token
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error en servidor: {str(e)}")