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
        """Busca la cuenta de ese correo sin distinguir mayúsculas.

        «Ana@...» y «ana@...» son la misma persona: quien se registró de una
        forma tiene que poder entrar escribiéndolo de la otra, o con Google,
        que lo da en minúsculas. Si de antes quedaron dos cuentas que solo se
        diferencian en eso, gana la escrita exactamente igual y, si no, la
        más antigua.
        """
        email = email.strip()
        exact = self.db.query(Usuario).filter(Usuario.correo == email).first()
        if exact is not None:
            return exact
        return (
            self.db.query(Usuario)
            .filter(func.lower(Usuario.correo) == email.lower())
            .order_by(Usuario.id_usuario)
            .first()
        )

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
