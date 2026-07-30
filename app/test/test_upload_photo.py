from types import SimpleNamespace

from fastapi.testclient import TestClient

from main import app
from presentation.api import upload_routes


client = TestClient(app)


def test_upload_photo_returns_photo_url(monkeypatch):
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
    app.dependency_overrides[upload_routes.get_db] = override_get_db

    response = client.post(
        "/api/user/upload-photo",
        data={"user_id": "7"},
        files={"file": ("avatar.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Foto guardada correctamente"
    assert payload["photo_url"].startswith("/uploads/")
    assert payload["photo_url"].endswith(".png")
