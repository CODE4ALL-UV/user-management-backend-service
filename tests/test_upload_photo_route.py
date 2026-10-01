from types import SimpleNamespace

from fastapi.testclient import TestClient

from user_management_service.main import app
from user_management_service.presentation.api import upload_routes


client = TestClient(app)


def test_upload_photo_returns_photo_url(monkeypatch, tmp_path):
    class FakeRepo:
        def __init__(self, db):
            self.db = db

        def get_user_by_id(self, user_id):
            return SimpleNamespace(id_usuario=user_id)

        def update_photo_path(self, user_id, photo_path):
            self.saved_photo_path = photo_path
            return None

    def override_get_db():
        yield object()

    monkeypatch.setattr(upload_routes, "UserRepositoryImpl", FakeRepo)
    # La foto de prueba va a una carpeta temporal, no a uploads/ del repo.
    monkeypatch.setattr(upload_routes, "UPLOAD_DIR", tmp_path)
    app.dependency_overrides[upload_routes.get_db] = override_get_db

    try:
        response = client.post(
            "/api/user/upload-photo",
            data={"user_id": "7"},
            files={"file": ("avatar.png", b"fake-image-bytes", "image/png")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Foto guardada correctamente"
    assert payload["photo_url"].startswith("/uploads/")
    assert payload["photo_url"].endswith(".png")
    assert (tmp_path / payload["photo_url"].rsplit("/", 1)[-1]).exists()
