from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from passlib.context import CryptContext
import os

# Configuración para el hashing de contraseñas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "secreto_super_inseguro_por_defecto")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

def get_password_hash(password: str) -> str:
    """Convierte la contraseña en un texto encriptado ilegible."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Compara la contraseña que llega de Flutter con la guardada en NeonDB."""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Genera el token JWT que Flutter guardará para mantener la sesión abierta."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """Decodifica y valida un JWT, devolviendo el payload."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except Exception as e:
        raise ValueError(f"Token inválido: {str(e)}")