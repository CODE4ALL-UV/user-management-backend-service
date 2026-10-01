from abc import ABC, abstractmethod
from typing import Optional, Any

class UserRepository(ABC):
    @abstractmethod
    def get_user_by_email(self, email: str) -> Optional[Any]:
        """Debe buscar un usuario por su correo electrónico."""
        pass

    @abstractmethod
    def get_user_by_id(self, user_id: int) -> Optional[Any]:
        """Debe buscar un usuario por su identificador."""
        pass

    @abstractmethod
    def get_tipo_discapacidad_by_id(self, tipo_id: int) -> Optional[Any]:
        """Debe verificar si el tipo de discapacidad existe en la base de datos."""
        pass

    @abstractmethod
    def create_user(self, user_data: dict) -> Any:
        """Debe guardar un nuevo usuario en la base de datos."""
        pass

    @abstractmethod
    def update_photo_path(self, user_id: int, photo_path: str) -> Any:
        """Debe actualizar la ruta de la foto del usuario."""
        pass