from abc import ABC, abstractmethod
from typing import Optional, Any

class UserRepository(ABC):
    @abstractmethod
    def get_user_by_email(self, email: str) -> Optional[Any]:
        """Debe buscar un usuario por su correo electrónico."""
        pass

    @abstractmethod
    def create_user(self, user_data: dict) -> Any:
        """Debe guardar un nuevo usuario en la base de datos."""
        pass