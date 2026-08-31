"""Cờ chẩn đoán cho gTTS: đang chạy, đang bị chặn, hay hết ngân sách."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.breaker import CLOSED, OPEN, ProviderGuard
from app.config import Settings
from app.limits import RateLimiter
from app.tts import Synthesizer


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = Settings(cache_dir=tmp_path)
    guard = ProviderGuard(max_per_minute=10)

    async def provider(text):
        return b"FAKE-MP3"

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(
        main, "synthesizer", Synthesizer(settings, primary=provider, guard=guard)
    )
    monkeypatch.setattr(main, "limiter", RateLimiter(settings.rate_limit_per_minute))
    with TestClient(main.app) as client:
        yield client, guard


def test_reports_healthy_state(api):
    client, _ = api
    body = client.get("/api/status").json()

    assert body["gtts"]["state"] == CLOSED
    assert body["gtts"]["consecutive_failures"] == 0
    assert body["gtts"]["budget_per_minute"] == 10
    assert body["gtts"]["last_error"] is None


def test_reports_blocked_state_with_reason_and_countdown(api):
    client, guard = api
    guard.record_failure("429 Too Many Requests", blocked=True)
    body = client.get("/api/status").json()

    assert body["gtts"]["state"] == OPEN
    assert body["gtts"]["last_error"] == "429 Too Many Requests"
    assert body["gtts"]["seconds_until_retry"] > 0


def test_budget_drops_as_requests_are_served(api):
    client, _ = api
    before = client.get("/api/status").json()["gtts"]["budget_remaining"]
    client.post("/api/tts", json={"text": "Xin chào."})
    after = client.get("/api/status").json()["gtts"]["budget_remaining"]

    assert after < before


def test_reports_cache_usage(api):
    client, _ = api
    client.post("/api/tts", json={"text": "Xin chào."})
    cache_info = client.get("/api/status").json()["cache"]

    assert cache_info["files"] == 1
    assert cache_info["bytes"] > 0


def test_healthz_stays_green_even_when_gtts_is_blocked(api):
    # healthz phải luôn 200 cho Docker: nhà cung cấp TTS chập chờn không có
    # nghĩa là tiến trình chết.
    client, guard = api
    guard.record_failure("bị chặn", blocked=True)

    assert client.get("/healthz").status_code == 200
    assert client.get("/api/status").json()["gtts"]["state"] == OPEN


def test_status_reports_the_translate_budget(tmp_path, monkeypatch):
    from app.translate import Translator

    settings = Settings(cache_dir=tmp_path, gemini_api_key="k", gemini_max_per_day=7)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "translator", Translator(settings, gemini=lambda t: t))
    with TestClient(main.app) as client:
        body = client.get("/api/status").json()

    assert body["translate"]["gemini_configured"] is True
    assert body["translate"]["budget_per_day"] == 7
    assert body["translate"]["budget_remaining_today"] == 7


def test_status_never_leaks_the_api_key(tmp_path, monkeypatch):
    """/api/status là endpoint chẩn đoán, không phải chỗ để lộ credential."""
    from app.translate import Translator

    secret = "AIza-super-secret-key-value"
    settings = Settings(cache_dir=tmp_path, gemini_api_key=secret)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "translator", Translator(settings, gemini=lambda t: t))
    with TestClient(main.app) as client:
        res = client.get("/api/status")

    assert secret not in res.text
