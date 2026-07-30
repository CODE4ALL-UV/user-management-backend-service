from domain.repositories.user_repository import UserRepository
from core.security import verify_password, create_access_token
from fastapi import HTTPException, status

class LoginUserUseCase:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    def execute(self, email: str, password_from_flutter: str) -> dict:
        # 1. Buscar al usuario en NeonDB usando su correo
        user = self.user_repository.get_user_by_email(email=email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="El correo o la contraseña son incorrectos."
            )

        # 2. Verificar que la contraseña coincida con el hash de tu tabla "usuario" (user.password)
        if not verify_password(password_from_flutter, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="El correo o la contraseña son incorrectos."
            )

        # 3. Si todo está perfecto, crear el token JWT usando tus campos reales (id_usuario y correo)
        access_token = create_access_token(
            data={"sub": str(user.id_usuario), "email": user.correo}
        )

        # 4. Devolver respuesta lista para Flutter con tus nombres exactos
        photo_url = getattr(user, "foto_path", None) or getattr(user, "photo_path", None) or ""

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user.id_usuario,
            "email": user.correo,
            "nombre": user.nombre,
            "rol": user.rol,
            "photo_url": photo_url,
        }