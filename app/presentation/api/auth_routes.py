from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

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