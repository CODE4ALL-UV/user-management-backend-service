"""Subtítulos de YouTube del monolito (app/), que sigue desplegado hasta el corte.

Ni YouTube ni el traductor se llaman de verdad: se sustituyen por dobles.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from youtube_transcript_api import TranscriptsDisabled

from monolith import load_main

client = TestClient(load_main().app)

# Mismo nombre con el que lo importa el monolito, para no cargar otra copia.
import presentation.api.youtube_routes as youtube_routes  # noqa: E402


def _cues(count):
    return [
        SimpleNamespace(start=float(i), duration=1.5, text=f"line {i}")
        for i in range(count)
    ]


class FakeTranscriptApi:
    transcript = []
    error = None

    def fetch(self, video_id, languages):
        if FakeTranscriptApi.error is not None:
            raise FakeTranscriptApi.error
        return FakeTranscriptApi.transcript


class FakeResponse:
    def __init__(self, payload, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _fake_youtube(monkeypatch):
    FakeTranscriptApi.transcript = _cues(2)
    FakeTranscriptApi.error = None
    monkeypatch.setattr(youtube_routes, "YouTubeTranscriptApi", FakeTranscriptApi)
    monkeypatch.delenv("TRANSLATE_PROVIDER", raising=False)
    monkeypatch.delenv("TRANSLATE_API_KEY", raising=False)


@pytest.fixture
def posts(monkeypatch):
    """Guarda cada llamada al traductor y responde con el texto en mayúsculas."""
    calls = []

    def fake_post(url, params=None, data=None, timeout=None):
        calls.append({"url": url, "params": params, "data": data})
        if "deepl" in url:
            return FakeResponse({"translations": [{"text": t.upper()} for t in data["text"]]})
        texts = [value for key, value in data if key == "q"]
        return FakeResponse(
            {"data": {"translations": [{"translatedText": t.upper()} for t in texts]}}
        )

    monkeypatch.setattr(youtube_routes.requests, "post", fake_post)
    return calls


def _captions(**params):
    return client.get("/api/youtube/captions", params={"video_id": "abc", **params})


def test_returns_the_captions_without_translation_by_default(posts):
    response = _captions()

    assert response.status_code == 200
    assert response.json()["cues"][1] == {"start": 1.0, "duration": 1.5, "text": "line 1"}
    assert posts == []


def test_video_without_transcripts_is_a_404():
    FakeTranscriptApi.error = TranscriptsDisabled("abc")

    assert _captions().status_code == 404


def test_any_other_youtube_error_returns_no_cues():
    FakeTranscriptApi.error = RuntimeError("YouTube no responde")

    assert _captions().json() == {"cues": []}


def test_translates_with_google_in_batches_of_twenty(monkeypatch, posts):
    FakeTranscriptApi.transcript = _cues(25)
    monkeypatch.setenv("TRANSLATE_PROVIDER", "google")
    monkeypatch.setenv("TRANSLATE_API_KEY", "clave")

    cues = _captions(target="fr").json()["cues"]

    assert cues[24]["translated"] == "LINE 24"
    assert [len(call["data"]) for call in posts] == [20, 5]
    assert posts[0]["params"] == {"key": "clave", "target": "fr"}


def test_translates_with_deepl(monkeypatch, posts):
    monkeypatch.setenv("TRANSLATE_PROVIDER", "deepl")
    monkeypatch.setenv("TRANSLATE_API_KEY", "clave")

    cues = _captions().json()["cues"]

    assert [cue["translated"] for cue in cues] == ["LINE 0", "LINE 1"]
    assert posts[0]["url"] == "https://api.deepl.com/v2/translate"
    assert posts[0]["data"]["target_lang"] == "ES"


def test_translation_failure_keeps_the_original_captions(monkeypatch):
    monkeypatch.setattr(
        youtube_routes.requests,
        "post",
        lambda *args, **kwargs: FakeResponse({}, error=RuntimeError("cuota agotada")),
    )
    monkeypatch.setenv("TRANSLATE_PROVIDER", "google")
    monkeypatch.setenv("TRANSLATE_API_KEY", "clave")

    cues = _captions().json()["cues"]

    assert [cue["text"] for cue in cues] == ["line 0", "line 1"]
    assert all("translated" not in cue for cue in cues)
