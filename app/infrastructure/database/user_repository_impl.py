from typing import Optional, Any
from sqlalchemy.orm import Session
from domain.repositories.user_repository import UserRepository

# IMPORTANTE: Importamos tu modelo real de SQLAlchemy que apunta a la tabla "usuario"
# Asegúrate de ajustar esta ruta según dónde hayas creado tu clase Usuario
from infrastructure.database.models import Usuario, TipoDiscapacidad  # O desde donde tengas tu modelo

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

    def update_photo_path(self, user_id: int, photo_path: str) -> Any:
        user = self.db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
        if not user:
            raise ValueError("Usuario no encontrado")

        user.foto_path = photo_path
        self.db.commit()
        self.db.refresh(user)
        return user