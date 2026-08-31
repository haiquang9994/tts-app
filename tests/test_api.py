import base64

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.limits import RateLimiter
from app.tts import Synthesizer


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Trả (client, calls). `calls` ghi lại mọi lần provider bị gọi thật."""
    settings = Settings(cache_dir=tmp_path)
    calls = []

    async def provider(text):
        calls.append(text)
        return b"FAKE-MP3"

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "synthesizer", Synthesizer(settings, primary=provider))
    monkeypatch.setattr(main, "limiter", RateLimiter(settings.rate_limit_per_minute))
    with TestClient(main.app) as client:
        yield client, calls


def test_returns_the_shape_the_frontend_reads(api):
    client, _ = api
    res = client.post("/api/tts", json={"text": "Xin chào. Tôi là Nam."})

    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"text", "base64", "name"}
    assert body["text"] == "Xin chào. Tôi là Nam."
    assert base64.b64decode(body["base64"]) == b"FAKE-MP3"
    assert len(body["name"]) == 32


def test_legacy_path_still_works(api):
    client, _ = api
    res = client.post("/text-to-speech", json={"text": "Xin chào."})
    assert res.status_code == 200
    assert res.json()["text"] == "Xin chào."


def test_provider_receives_normalised_text(api):
    client, calls = api
    client.post("/api/tts", json={"text": "Xin chào.  Tôi tên Nam."})
    assert calls == ["Xin chào. Tôi tên Nam."]


def test_ignores_extra_voice_and_rate_fields(api):
    # API không còn nhận hai trường này; gửi lên cũng không được phép làm hỏng.
    client, calls = api
    res = client.post(
        "/api/tts",
        json={"text": "Xin chào.", "voice": "en-US-JennyNeural", "rate": "+999%"},
    )
    assert res.status_code == 200
    assert calls == ["Xin chào."]


def test_does_not_mangle_file_paths(api):
    client, calls = api
    res = client.post("/api/tts", json={"text": ".claude/features/client-surface.md"})
    assert res.status_code == 200
    assert calls == [".claude/features/client-surface.md."]


def test_second_call_is_served_from_cache(api):
    client, calls = api
    client.post("/api/tts", json={"text": "Xin chào."})
    client.post("/api/tts", json={"text": "Xin chào."})
    assert len(calls) == 1


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_empty_text_returns_422(api, text):
    client, _ = api
    assert client.post("/api/tts", json={"text": text}).status_code == 422


def test_missing_text_field_returns_422(api):
    client, _ = api
    assert client.post("/api/tts", json={}).status_code == 422


def test_oversized_text_returns_413(api):
    client, _ = api
    res = client.post("/api/tts", json={"text": "a" * 1001})
    assert res.status_code == 413


@pytest.mark.parametrize("text", [" - ", "...", "!!!", "--", "  .  "])
def test_punctuation_only_text_returns_422(api, text):
    # Không có chữ hay số nào -> không đáng gọi TTS.
    client, calls = api
    res = client.post("/api/tts", json={"text": text})
    assert res.status_code == 422
    assert calls == []


def test_digits_only_text_is_accepted(api):
    client, _ = api
    assert client.post("/api/tts", json={"text": "2026"}).status_code == 200


def test_tts_failure_returns_503_not_500(tmp_path, monkeypatch):
    settings = Settings(cache_dir=tmp_path)

    async def provider(text):
        raise OSError("cả hai nhà cung cấp đều chặn")

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(
        main, "synthesizer", Synthesizer(settings, primary=provider, fallback=provider)
    )
    monkeypatch.setattr(main, "limiter", RateLimiter(settings.rate_limit_per_minute))
    monkeypatch.setattr("app.tts._RETRY_DELAYS", (0.0,))

    with TestClient(main.app) as client:
        res = client.post("/api/tts", json={"text": "Xin chào."})

    assert res.status_code == 503


def test_rate_limit_returns_429_with_retry_after(tmp_path, monkeypatch):
    settings = Settings(cache_dir=tmp_path)

    async def provider(text):
        return b"FAKE-MP3"

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "synthesizer", Synthesizer(settings, primary=provider))
    monkeypatch.setattr(main, "limiter", RateLimiter(per_minute=60, burst=2))

    with TestClient(main.app) as client:
        codes = [client.post("/api/tts", json={"text": f"Câu {i}."}).status_code for i in range(4)]
        res = client.post("/api/tts", json={"text": "Câu nữa."})

    assert codes[:2] == [200, 200]
    assert 429 in codes
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_healthz_still_works(api):
    client, _ = api
    assert client.get("/healthz").json() == {"status": "ok"}


def test_index_returns_html(api):
    client, _ = api
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


@pytest.mark.parametrize("path", ["/about", "/about/"])
def test_about_accepts_both_path_forms(api, path):
    client, _ = api
    assert client.get(path).status_code == 200
