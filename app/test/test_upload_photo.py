from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.security import create_access_token
from main import app
from presentation.api import upload_routes


client = TestClient(app)


def _session(user_id: int) -> dict:
    token = create_access_token(
        data={"sub": str(user_id), "email": f"u{user_id}@example.com", "rol": "estudiante"}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def repo(monkeypatch, tmp_path):
    class FakeRepo:
        saved = {}

        def __init__(self, db):
            self.db = db

        def get_user_by_id(self, user_id):
            return SimpleNamespace(id_usuario=user_id)

        def update_photo_path(self, user_id, photo_path):
            FakeRepo.saved[user_id] = photo_path

    def override_get_db():
        yield object()

    monkeypatch.setattr(upload_routes, "UserRepositoryImpl", FakeRepo)
    # La foto de prueba va a una carpeta temporal, no a uploads/ del repo.
    monkeypatch.setattr(upload_routes, "UPLOAD_DIR", tmp_path)
    app.dependency_overrides[upload_routes.get_db] = override_get_db
    yield FakeRepo
    app.dependency_overrides.clear()


def _upload(headers=None, data=None, content=b"fake-image-bytes"):
    return client.post(
        "/api/user/upload-photo",
        data=data or {},
        files={"file": ("avatar.png", content, "image/png")},
        headers=headers or {},
    )


def test_upload_photo_returns_photo_url(repo, tmp_path):
    response = _upload(headers=_session(7), data={"user_id": "7"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Foto guardada correctamente"
    assert payload["photo_url"].startswith("/uploads/")
    assert payload["photo_url"].endswith(".png")
    assert (tmp_path / payload["photo_url"].rsplit("/", 1)[-1]).exists()
    assert repo.saved[7] == payload["photo_url"]


def test_the_photo_goes_to_whoever_has_the_session(repo):
    # Sin id en el formulario, la foto es del dueño de la sesión.
    response = _upload(headers=_session(9))

    assert response.status_code == 200
    assert 9 in repo.saved


def test_without_a_session_nobody_can_change_a_photo(repo):
    # Antes bastaba con mandar cualquier id, sin haber iniciado sesión.
    response = _upload(data={"user_id": "7"})

    assert response.status_code == 401
    assert repo.saved == {}


def test_nobody_can_change_someone_elses_photo(repo):
    response = _upload(headers=_session(7), data={"user_id": "8"})

    assert response.status_code == 403
    assert repo.saved == {}


def test_a_huge_file_is_rejected(repo):
    too_big = b"x" * (upload_routes.MAX_PHOTO_BYTES + 1)

    response = _upload(headers=_session(7), content=too_big)

    assert response.status_code == 413
    assert repo.saved == {}
