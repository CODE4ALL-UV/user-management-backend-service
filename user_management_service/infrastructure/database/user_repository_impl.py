from typing import Optional, Any
from sqlalchemy import func
from sqlalchemy.orm import Session
from user_management_service.domain.repositories.user_repository import UserRepository

# Los modelos viven en neon-storage, la capa de datos que comparten todos los
# microservicios. Las consultas de rendimiento de estudiantes que antes
# estaban aqui pasaron a progress-tracking, que es quien las usa.
from neon_storage.models import Usuario, TipoDiscapacidad


class UserRepositoryImpl(UserRepository):
    def __init__(self, db_session: Session):
        self.db = db_session

    def get_user_by_email(self, email: str) -> Optional[Any]:
        """Busca un usuario en NeonDB usando la columna 'correo'."""
        return self.db.query(Usuario).filter(Usuario.correo == email).first()

    def get_user_by_id(self, user_id: int) -> Optional[Any]:
        return self.db.query(Usuario).filter(Usuario.id_usuario == user_id).first()

    def get_tipo_discapacidad_by_id(self, tipo_id: int) -> Optional[Any]:
        """Busca si el tipo de discapacidad existe en la tabla TipoDiscapacidad."""
        return self.db.query(TipoDiscapacidad).filter(TipoDiscapacidad.id_tipo == tipo_id).first()

    def create_user(self, user_data: dict) -> Any:
        """Guarda un nuevo usuario en la tabla 'usuario' en NeonDB."""
        new_user = Usuario(**user_data)
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return new_user

    def find_by_email_any_case(self, email: str) -> Optional[Any]:
        """Quien olvida la contraseña no siempre recuerda cómo escribió el
        correo: «Ana@...» y «ana@...» son la misma persona."""
        exact = self.get_user_by_email(email)
        if exact is not None:
            return exact
        return (
            self.db.query(Usuario)
            .filter(func.lower(Usuario.correo) == email.strip().lower())
            .first()
        )

    def update_password(self, user_id: int, password_hash: str) -> Any:
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("Usuario no encontrado")

        user.password = password_hash
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_photo_path(self, user_id: int, photo_path: str) -> Any:
        user = self.db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
        if not user:
            raise ValueError("Usuario no encontrado")

        user.foto_path = photo_path
        self.db.commit()
        self.db.refresh(user)
        return user
