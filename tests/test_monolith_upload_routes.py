"""Subir la foto de perfil en el monolito (app/).

La foto es de quien tiene la sesión: nadie puede cambiar la de otra persona
ni subir sin haber entrado. Además se comprueba qué archivos se aceptan, el
límite de tamaño y que la ruta guardada en la base apunte al archivo.
Los archivos van a una carpeta temporal, nunca a uploads/ del repo.
"""

import pytest
from fastapi.testclient import TestClient

from monolith import load_main

main = load_main()

import presentation.api.upload_routes as mono_upload  # noqa: E402
from core.security import create_access_token, get_password_hash  # noqa: E402
from infrastructure.database.models import Usuario  # noqa: E402

client = TestClient(main.app)

URL = "/api/user/upload-photo"


@pytest.fixture(autouse=True)
def upload_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(mono_upload, "UPLOAD_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def ana(db_session):
    user = Usuario(nombre="Ana", correo="ana@example.com", password="hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _session(user_id, **extra):
    data = {"sub": str(user_id), "email": f"u{user_id}@example.com", "rol": "estudiante"}
    data.update(extra)
    return {"Authorization": f"Bearer {create_access_token(data=data)}"}


def _upload(headers=None, data=None, filename="avatar.png", content=b"bytes-de-imagen", url=URL):
    return client.post(
        url,
        data=data or {},
        files={"file": (filename, content, "image/png")},
        headers=headers or {},
    )


def _saved_photo(db, user):
    db.expire_all()
    return db.get(Usuario, user.id_usuario).foto_path


def test_the_owner_uploads_a_photo_and_it_is_saved(db_session, ana, upload_dir):
    response = _upload(headers=_session(ana.id_usuario), data={"user_id": str(ana.id_usuario)})

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Foto guardada correctamente"
    photo_url = body["photo_url"]
    assert photo_url.startswith("/uploads/") and photo_url.endswith(".png")
    stored = upload_dir / photo_url.rsplit("/", 1)[-1]
    assert stored.read_bytes() == b"bytes-de-imagen"
    assert _saved_photo(db_session, ana) == photo_url


def test_the_new_photo_is_returned_on_the_next_login(db_session, ana):
    ana.password = get_password_hash("clave")
    db_session.commit()
    photo_url = _upload(headers=_session(ana.id_usuario)).json()["photo_url"]

    login = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "clave"})

    assert login.json()["photo_url"] == photo_url


@pytest.mark.parametrize("filename", ["foto.JPG", "foto.jpeg", "foto.webp", "foto.PNG"])
def test_the_supported_formats_are_accepted_whatever_the_capitals(db_session, ana, filename):
    response = _upload(headers=_session(ana.id_usuario), filename=filename)

    assert response.status_code == 200
    assert response.json()["photo_url"].endswith(filename.rsplit(".", 1)[-1].lower())


def test_each_upload_gets_a_new_name(db_session, ana, upload_dir):
    first = _upload(headers=_session(ana.id_usuario)).json()["photo_url"]
    second = _upload(headers=_session(ana.id_usuario)).json()["photo_url"]

    assert first != second
    assert len(list(upload_dir.iterdir())) == 2
    assert _saved_photo(db_session, ana) == second


def test_without_a_session_nobody_can_upload(db_session, ana, upload_dir):
    response = _upload(data={"user_id": str(ana.id_usuario)})

    assert response.status_code == 401
    assert list(upload_dir.iterdir()) == []
    assert _saved_photo(db_session, ana) is None


def test_a_session_without_a_numeric_id_cannot_upload(db_session, ana, upload_dir):
    response = _upload(headers=_session("no-es-un-id"))

    assert response.status_code == 401
    assert response.json()["detail"] == "La sesión no identifica a nadie."
    assert list(upload_dir.iterdir()) == []


@pytest.mark.parametrize("where", ["form", "query"])
def test_nobody_can_change_someone_elses_photo(db_session, ana, upload_dir, where):
    # Antes bastaba con mandar el id de otra persona para cambiarle la foto.
    other_id = ana.id_usuario + 1
    if where == "form":
        response = _upload(headers=_session(other_id), data={"user_id": str(ana.id_usuario)})
    else:
        response = _upload(headers=_session(other_id), url=f"{URL}?user_id_query={ana.id_usuario}")

    assert response.status_code == 403
    assert response.json()["detail"] == "Solo puedes cambiar tu propia foto."
    assert list(upload_dir.iterdir()) == []
    assert _saved_photo(db_session, ana) is None


def test_the_id_in_the_query_is_accepted_when_it_is_the_callers(db_session, ana):
    response = _upload(headers=_session(ana.id_usuario), url=f"{URL}?user_id_query={ana.id_usuario}")

    assert response.status_code == 200


def test_a_request_without_a_file_is_a_400(db_session, ana):
    response = client.post(URL, headers=_session(ana.id_usuario))

    assert response.status_code == 400
    assert response.json()["detail"] == "No se recibió ningún archivo"


@pytest.mark.parametrize("filename", ["foto.gif", "foto.exe", "sin-extension"])
def test_unsupported_formats_are_refused(db_session, ana, upload_dir, filename):
    response = _upload(headers=_session(ana.id_usuario), filename=filename)

    assert response.status_code == 400
    assert response.json()["detail"] == "Formato no soportado"
    assert list(upload_dir.iterdir()) == []


def test_a_session_of_an_account_that_no_longer_exists_is_a_404(db_session, upload_dir):
    response = _upload(headers=_session(987654))

    assert response.status_code == 404
    assert response.json()["detail"] == "Usuario no encontrado"
    assert list(upload_dir.iterdir()) == []


def test_a_photo_over_five_megabytes_is_refused(db_session, ana, upload_dir):
    assert mono_upload.MAX_PHOTO_BYTES == 5 * 1024 * 1024

    response = _upload(
        headers=_session(ana.id_usuario), content=b"x" * (mono_upload.MAX_PHOTO_BYTES + 1)
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "La foto no puede pasar de 5 MB."
    assert list(upload_dir.iterdir()) == []
    assert _saved_photo(db_session, ana) is None


def test_a_photo_of_exactly_five_megabytes_is_accepted(db_session, ana, upload_dir):
    response = _upload(headers=_session(ana.id_usuario), content=b"x" * mono_upload.MAX_PHOTO_BYTES)

    assert response.status_code == 200
    [stored] = upload_dir.iterdir()
    assert stored.stat().st_size == mono_upload.MAX_PHOTO_BYTES


def test_a_failure_writing_the_file_is_a_500_and_the_profile_is_untouched(
    db_session, ana, monkeypatch, tmp_path
):
    monkeypatch.setattr(mono_upload, "UPLOAD_DIR", tmp_path / "no-existe")

    response = _upload(headers=_session(ana.id_usuario))

    assert response.status_code == 500
    assert response.json()["detail"].startswith("No se pudo guardar la imagen:")
    assert _saved_photo(db_session, ana) is None
