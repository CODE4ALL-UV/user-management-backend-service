from passlib.context import CryptContext
from domain.repositories.user_repository import UserRepository

# Configuramos el encriptador de contraseñas con bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class CreateUserUseCase:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    def _normalize_role(self, role_value) -> str:
        if role_value is None:
            return "estudiante"

        normalized_role = str(role_value).strip().lower()
        if normalized_role in {"estudiante", "docente", "director"}:
            return normalized_role

        return "estudiante"

    def execute(self, user_data) -> dict:
        """
        Caso de uso para registrar un nuevo usuario:
        1. Verifica si el correo ya existe.
        2. Encripta la contraseña.
        3. Guarda el usuario en la base de datos NeonDB.
        """
        
        # Opcional pero recomendado: Revisar si el correo ya está registrado
        existing_user = self.user_repository.get_user_by_email(user_data.correo)
        if existing_user:
            raise ValueError("El correo electrónico ya se encuentra registrado.")

        # 1. Encriptar la contraseña antes de guardarla
        hashed_password = pwd_context.hash(user_data.password)

        # 2. Validar que el tipo de discapacidad exista si fue enviado.
        tipo_discapacidad = user_data.tipo_discapacidad
        if tipo_discapacidad is not None:
            tipo_existente = self.user_repository.get_tipo_discapacidad_by_id(tipo_discapacidad)
            if not tipo_existente:
                tipo_discapacidad = None

        # 3. Construir el diccionario respetando los nombres exactos de tu tabla "usuario"
        new_user_dict = {
            "nombre": user_data.nombre,
            "correo": user_data.correo,
            "password": hashed_password,
            "tipo_discapacidad": tipo_discapacidad,
            "rol": self._normalize_role(getattr(user_data, "rol", None))
        }

        # 4. Guardar a través del repositorio
        created_user = self.user_repository.create_user(new_user_dict)

        # 5. Retornar los datos limpios (sin la contraseña por seguridad)
        return {
            "id_usuario": created_user.id_usuario,
            "nombre": created_user.nombre,
            "correo": created_user.correo,
            "tipo_discapacidad": created_user.tipo_discapacidad,
            "fecha_registro": str(created_user.fecha_registro),
            "rol": created_user.rol
        }