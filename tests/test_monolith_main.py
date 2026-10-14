"""La aplicación del monolito (main.py en la raíz), la que sirve Render.

Que arranque con todas sus rutas, que responda en la raíz y, sobre todo,
desde qué páginas deja llamar un navegador (CORS): la web publicada,
localhost para desarrollar y lo que se añada con CORS_ORIGINS, nada más.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from monolith import load_main

main = load_main()

client = TestClient(main.app)

WEB = "https://code4all-web.onrender.com"


def _preflight(app_client, origin):
    return app_client.options(
        "/api/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def _fresh_main():
    """Vuelve a ejecutar main.py como un módulo aparte, sin tocar el cargado."""
    spec = importlib.util.spec_from_file_location("monolith_main_again", main.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_root_says_the_server_is_online():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "online"
    assert "conectado" in response.json()["message"]


def test_every_part_of_the_api_is_mounted():
    paths = set(main.app.openapi()["paths"])

    assert {
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/google",
        "/api/user/upload-photo",
        "/api/director/students",
        "/api/director/performances",
        "/api/director/performances/aggregate",
        "/api/director/performances/average",
    } <= paths
    # Cada uno de los diez routers aporta sus rutas.
    prefixes = {path.split("/")[2] for path in paths if path.startswith("/api/")}
    assert prefixes == {
        "auth", "user", "director", "youtube", "modules",
        "signs", "course", "analytics", "oversight", "braille",
    }


def test_uploaded_photos_are_served_from_the_uploads_folder():
    mount = next(r for r in main.app.routes if getattr(r, "path", None) == "/uploads")

    assert Path(mount.app.directory) == main.UPLOAD_DIR
    assert main.UPLOAD_DIR == Path(main.__file__).resolve().parent / "uploads"
    assert client.get("/uploads/no-existe.png").status_code == 404


@pytest.mark.parametrize(
    "origin",
    [WEB, "http://localhost:5173", "http://127.0.0.1:8080", "http://localhost"],
)
def test_the_published_web_and_localhost_may_call_the_api(origin):
    response = _preflight(client, origin)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    # La sesión viaja en Authorization, no en cookies: sin credenciales.
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize(
    "origin",
    ["https://pagina-cualquiera.com", "http://localhost.evil.com", "https://code4all-web.onrender.com.evil.io"],
)
def test_other_pages_may_not_call_the_api_from_a_browser(origin):
    response = _preflight(client, origin)

    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_adds_extra_pages_without_touching_the_code(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " https://code4all.co/ , ,https://otra.example.org")

    fresh = _fresh_main()

    assert fresh.CORS_ORIGINS == [WEB, "https://code4all.co", "https://otra.example.org"]
    fresh_client = TestClient(fresh.app)
    assert _preflight(fresh_client, "https://code4all.co").headers[
        "access-control-allow-origin"
    ] == "https://code4all.co"
    assert "access-control-allow-origin" not in _preflight(
        fresh_client, "https://pagina-cualquiera.com"
    ).headers


def test_without_cors_origins_only_the_published_web_is_listed(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert _fresh_main().CORS_ORIGINS == [WEB]


def test_main_puts_app_first_on_the_import_path(monkeypatch):
    # Así `core`, `presentation`... son los paquetes de app/ y no otros.
    root = Path(main.__file__).resolve().parent
    ours = {root, root / "app"}
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p).resolve() not in ours])

    _fresh_main()

    assert [Path(p) for p in sys.path[:2]] == [root / "app", root]
