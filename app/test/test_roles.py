from types import SimpleNamespace

from application.use_cases.create_user import CreateUserUseCase


class FakeUserRepository:
    def __init__(self):
        self.created_user = None

    def get_user_by_email(self, email: str):
        return None

    def get_tipo_discapacidad_by_id(self, tipo_id: int):
        return None

    def create_user(self, user_data: dict):
        self.created_user = user_data
        return SimpleNamespace(
            id_usuario=1,
            nombre=user_data["nombre"],
            correo=user_data["correo"],
            tipo_discapacidad=user_data.get("tipo_discapacidad"),
            fecha_registro=None,
            rol=user_data.get("rol", "estudiante"),
        )


def test_create_user_assigns_role_and_saves_it():
    repository = FakeUserRepository()
    use_case = CreateUserUseCase(user_repository=repository)

    user_payload = SimpleNamespace(
        nombre="Ana",
        correo="ana@example.com",
        password="123456",
        tipo_discapacidad=None,
        rol="docente",
    )

    result = use_case.execute(user_payload)

    assert result["rol"] == "docente"
    assert repository.created_user["rol"] == "docente"
