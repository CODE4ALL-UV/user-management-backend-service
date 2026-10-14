"""Detección de la mano del monolito (app/), que sigue desplegado hasta el corte.

MediaPipe se sustituye por dobles para no descargar el modelo de 7,8 MB. La
foto sí es real: se decodifica con OpenCV, como en producción.
"""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from monolith import load_main

client = TestClient(load_main().app)

# Mismo nombre con el que lo importa el monolito, para no cargar otra copia.
import presentation.api.sign_routes as sign_routes  # noqa: E402


def _png():
    ok, encoded = cv2.imencode(".png", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()


def _post_image(payload, content_type="image/png"):
    return client.post(
        "/api/signs/landmarks", files={"file": ("mano.png", payload, content_type)}
    )


class FakeLandmarker:
    def __init__(self, hand_landmarks, handedness):
        self.result = SimpleNamespace(hand_landmarks=hand_landmarks, handedness=handedness)

    def detect(self, image):
        return self.result


def _hand():
    return [SimpleNamespace(x=i / 100, y=0.5, z=-0.1) for i in range(21)]


class FakeVision:
    """Lo justo de `mediapipe.tasks.python.vision` para crear el detector."""

    created = []
    error = None

    class RunningMode:
        IMAGE = "image"

    class HandLandmarkerOptions:
        def __init__(self, **options):
            self.options = options

    class HandLandmarker:
        @staticmethod
        def create_from_options(options):
            FakeVision.created.append(options)
            if FakeVision.error is not None:
                raise FakeVision.error
            return FakeLandmarker([], [])


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch, tmp_path):
    """Como recién arrancado, y con el modelo en una carpeta temporal."""
    monkeypatch.setattr(sign_routes, "_import_error", None)
    monkeypatch.setattr(sign_routes, "_landmarker", None)
    monkeypatch.setattr(sign_routes, "_landmarker_error", None)
    models = tmp_path / "models"
    monkeypatch.setattr(sign_routes, "MODELS_DIR", models)
    monkeypatch.setattr(sign_routes, "MODEL_PATH", models / "hand_landmarker.task")


@pytest.fixture
def detector(monkeypatch):
    landmarker = FakeLandmarker([_hand()], [[SimpleNamespace(category_name="Left")]])
    monkeypatch.setattr(sign_routes, "_get_landmarker", lambda: landmarker)
    return landmarker


@pytest.fixture
def vision(monkeypatch):
    FakeVision.created = []
    FakeVision.error = None
    monkeypatch.setattr(sign_routes, "vision", FakeVision)
    monkeypatch.setattr(sign_routes, "BaseOptions", lambda model_asset_path: model_asset_path)
    sign_routes.MODELS_DIR.mkdir()
    sign_routes.MODEL_PATH.write_bytes(b"modelo")
    return FakeVision


@pytest.fixture
def downloads(monkeypatch):
    calls = []

    def fake_urlretrieve(url, destination):
        calls.append(url)
        destination.write_bytes(b"modelo")

    monkeypatch.setattr(sign_routes.urllib.request, "urlretrieve", fake_urlretrieve)
    return calls


def test_returns_the_21_points_and_which_hand_it_is(detector):
    response = _post_image(_png())

    assert response.status_code == 200
    hand = response.json()["hands"][0]
    assert hand["handedness"] == "Left"
    assert len(hand["landmarks"]) == 21
    assert hand["landmarks"][2] == {"x": 0.02, "y": 0.5, "z": -0.1}


@pytest.mark.parametrize("handedness", [[], [[]]])
def test_unknown_handedness_is_an_empty_string(detector, handedness):
    detector.result = SimpleNamespace(hand_landmarks=[_hand()], handedness=handedness)

    assert _post_image(_png()).json()["hands"][0]["handedness"] == ""


@pytest.mark.parametrize(
    "payload, content_type, expected",
    [
        (b"hola", "text/plain", 415),
        (b"", "image/jpeg", 400),
        (b"\0" * (4 * 1024 * 1024 + 1), "image/png", 413),
        (b"esto no es una imagen", "image/png", 400),
    ],
    ids=["not-an-image-type", "empty", "over-4-mb", "undecodable"],
)
def test_rejects_what_is_not_a_usable_photo(detector, payload, content_type, expected):
    assert _post_image(payload, content_type).status_code == expected


def test_missing_mediapipe_is_a_503_and_status_says_why(monkeypatch):
    monkeypatch.setattr(sign_routes, "_import_error", "No module named 'mediapipe'")

    assert _post_image(_png()).status_code == 503
    status = client.get("/api/signs/status").json()
    assert status == {
        "available": False,
        "model_ready": False,
        "reason": "Faltan dependencias en el backend: No module named 'mediapipe'",
    }


def test_status_is_available_when_nothing_failed():
    assert client.get("/api/signs/status").json() == {
        "available": True,
        "model_ready": False,
        "reason": None,
    }


def test_detector_is_created_once_and_reused(vision):
    assert sign_routes._get_landmarker() is sign_routes._get_landmarker()
    assert len(vision.created) == 1
    assert vision.created[0].options["num_hands"] == 1


def test_failure_to_create_the_detector_is_remembered(vision):
    vision.error = OSError("libGL.so.1: cannot open shared object file")

    for _ in range(2):
        with pytest.raises(RuntimeError, match="libGL"):
            sign_routes._get_landmarker()
    assert len(vision.created) == 1

    status = client.get("/api/signs/status").json()
    assert status["available"] is False
    assert status["model_ready"] is True
    assert "libGL" in status["reason"]


def test_model_is_downloaded_only_when_missing_or_empty(downloads):
    assert sign_routes._ensure_model().read_bytes() == b"modelo"
    sign_routes._ensure_model()
    assert downloads == [sign_routes.MODEL_URL]

    sign_routes.MODEL_PATH.write_bytes(b"")
    sign_routes._ensure_model()
    assert len(downloads) == 2
