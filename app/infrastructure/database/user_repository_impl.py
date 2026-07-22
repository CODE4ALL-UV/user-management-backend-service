from typing import Optional, Any
from sqlalchemy.orm import Session
from domain.repositories.user_repository import UserRepository

# IMPORTANTE: Importamos tu modelo real de SQLAlchemy que apunta a la tabla "usuario"
# Asegúrate de ajustar esta ruta según dónde hayas creado tu clase Usuario
from infrastructure.database.models import Usuario  # O desde donde tengas tu modelo

class UserRepositoryImpl(UserRepository):
    def __init__(self, db_session: Session):
        self.db = db_session

    def get_user_by_email(self, email: str) -> Optional[Any]:
        """Busca un usuario en NeonDB usando la columna 'correo'."""
        return self.db.query(Usuario).filter(Usuario.correo == email).first()

    def create_user(self, user_data: dict) -> Any:
        """Guarda un nuevo usuario en la tabla 'usuario' en NeonDB."""
        # user_data contendrá un diccionario como: 
        # {"nombre": "...", "correo": "...", "password": "...", "tipo_discapacidad": ...}
        
        new_user = Usuario(**user_data)
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return new_user