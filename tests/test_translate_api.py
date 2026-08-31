"""Endpoint dịch. Không chạm mạng: fetcher luôn được tiêm bản giả."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.limits import RateLimiter
from app.translate import DailyBudget, TranslateError, Translator


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Trả (client, calls). `calls` ghi lại từng đoạn gửi đi dịch."""
    settings = Settings(cache_dir=tmp_path)
    calls: list[str] = []

    def fetch(chunk: str) -> str:
        calls.append(chunk)
        return chunk.replace("Hello", "Xin chào").replace("world", "thế giới")

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(
        main, "translator",
        Translator(settings, gemini=fetch, mymemory=fetch,
                   budget=DailyBudget(0)),   # tắt Gemini, đo đường MyMemory
    )
    monkeypatch.setattr(main, "limiter", RateLimiter(settings.rate_limit_per_minute))
    with TestClient(main.app) as client:
        yield client, calls


def test_translates_and_returns_text(api):
    client, calls = api
    res = client.post("/api/translate", json={"text": "Hello world."})

    assert res.status_code == 200
    assert res.json() == {"text": "Xin chào thế giới."}
    assert calls == ["Hello world."]


def test_keeps_code_like_tokens_in_english(api):
    client, _ = api
    res = client.post(
        "/api/translate",
        json={"text": "Hello world, run `npm install` for POST /api/tts."},
    )

    body = res.json()["text"]
    assert "npm install" in body
    assert "POST" in body
    assert "/api/tts" in body
    assert "Xin chào" in body


def test_rejects_empty_text(api):
    client, calls = api
    res = client.post("/api/translate", json={"text": "   "})

    assert res.status_code == 422
    assert calls == [], "không được gọi ra ngoài khi text rỗng"


def test_rejects_text_that_is_too_long(api):
    client, calls = api
    # Lấy từ Settings chứ không viết cứng, để đổi mặc định không làm hỏng test.
    res = client.post(
        "/api/translate", json={"text": "a" * (Settings().max_translate_length + 1)}
    )

    # 413 chứ không phải 422: 422 lẫn với lỗi schema của pydantic.
    assert res.status_code == 413
    assert calls == []


def test_reports_provider_failure_as_503(tmp_path, monkeypatch):
    settings = Settings(cache_dir=tmp_path)

    def broken(chunk: str) -> str:
        raise TranslateError("MyMemory đã hết hạn mức dịch trong ngày")

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(
        main, "translator",
        Translator(settings, gemini=broken, mymemory=broken, budget=DailyBudget(0)),
    )
    monkeypatch.setattr(main, "limiter", RateLimiter(settings.rate_limit_per_minute))
    with TestClient(main.app) as client:
        res = client.post("/api/translate", json={"text": "Hello world."})

    # 503 để giao diện biết là tạm thời và giữ nguyên văn bản gốc.
    assert res.status_code == 503


def test_rate_limit_applies(tmp_path, monkeypatch):
    settings = Settings(cache_dir=tmp_path)
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(
        main, "translator",
        Translator(settings, gemini=lambda t: t, mymemory=lambda c: c,
                   budget=DailyBudget(0)),
    )
    # burst=0 nữa, vì BURST mặc định là 20 nên chỉ đặt 0/phút thì request
    # đầu tiên vẫn lọt.
    monkeypatch.setattr(main, "limiter", RateLimiter(0, burst=0))
    with TestClient(main.app) as client:
        res = client.post("/api/translate", json={"text": "Hello world."})

    assert res.status_code == 429
    assert res.headers["Retry-After"]
