"""Subir la foto de perfil.

La foto es de quien tiene la sesión, tiene que ser una imagen y no puede
pasar de 5 MB. Los archivos de prueba van a una carpeta temporal.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from user_management_service.core.security import create_access_token
from user_management_service.main import app
from user_management_service.presentation.api import upload_routes


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


def test_a_file_of_exactly_the_limit_is_accepted(repo):
    response = _upload(headers=_session(7), content=b"x" * upload_routes.MAX_PHOTO_BYTES)

    assert response.status_code == 200


def test_the_id_can_also_come_in_the_query_but_must_be_the_callers(repo):
    ok = client.post(
        "/api/user/upload-photo?user_id_query=7",
        files={"file": ("avatar.jpg", b"img", "image/jpeg")},
        headers=_session(7),
    )
    other = client.post(
        "/api/user/upload-photo?user_id_query=8",
        files={"file": ("avatar.jpg", b"img", "image/jpeg")},
        headers=_session(7),
    )

    assert ok.status_code == 200
    assert other.status_code == 403
    assert list(repo.saved) == [7]


def test_a_session_without_a_numeric_id_cannot_change_a_photo(repo):
    token = create_access_token(data={"sub": "no-es-un-numero", "email": "u@example.com"})

    response = _upload(headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "La sesión no identifica a nadie."
    assert repo.saved == {}


def test_without_a_file_the_answer_is_400(repo):
    response = client.post("/api/user/upload-photo", data={"user_id": "7"}, headers=_session(7))

    assert response.status_code == 400
    assert response.json()["detail"] == "No se recibió ningún archivo"


@pytest.mark.parametrize("name", ["virus.exe", "foto.gif", "sin-extension"])
def test_only_images_in_known_formats_are_accepted(repo, tmp_path, name):
    response = client.post(
        "/api/user/upload-photo",
        files={"file": (name, b"bytes", "application/octet-stream")},
        headers=_session(7),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Formato no soportado"
    assert list(tmp_path.iterdir()) == []


def test_the_extension_is_checked_without_caring_about_capitals(repo):
    response = client.post(
        "/api/user/upload-photo",
        files={"file": ("FOTO.WEBP", b"bytes", "image/webp")},
        headers=_session(7),
    )

    assert response.status_code == 200
    assert response.json()["photo_url"].endswith(".webp")


def test_the_photo_of_a_deleted_account_is_not_saved(repo, monkeypatch, tmp_path):
    monkeypatch.setattr(repo, "get_user_by_id", lambda self, user_id: None)

    response = _upload(headers=_session(7))

    assert response.status_code == 404
    assert repo.saved == {}
    assert list(tmp_path.iterdir()) == []


def test_if_the_photo_cannot_be_written_the_answer_is_500(repo, monkeypatch, tmp_path):
    # Una carpeta que no existe: abrir el archivo falla.
    monkeypatch.setattr(upload_routes, "UPLOAD_DIR", tmp_path / "no" / "existe")

    response = _upload(headers=_session(7))

    assert response.status_code == 500
    assert response.json()["detail"].startswith("No se pudo guardar la imagen")
    assert repo.saved == {}
