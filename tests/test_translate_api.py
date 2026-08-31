"""Endpoint dịch. Không chạm mạng: nhà cung cấp luôn được tiêm bản giả."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.limits import RateLimiter
from app.translate import DailyBudget, TranslateError, Translator


def _install(monkeypatch, settings, gemini, budget=None):
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "translator", Translator(settings, gemini=gemini,
                                                       budget=budget))
    monkeypatch.setattr(main, "limiter", RateLimiter(settings.rate_limit_per_minute))


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Trả (client, calls). `calls` ghi lại từng văn bản gửi đi dịch."""
    settings = Settings(cache_dir=tmp_path, gemini_api_key="k")
    calls: list[str] = []

    def gemini(text: str) -> str:
        calls.append(text)
        return text.replace("Hello", "Xin chào").replace("world", "thế giới")

    _install(monkeypatch, settings, gemini)
    with TestClient(main.app) as client:
        yield client, calls


def test_translates_and_returns_text(api):
    client, calls = api
    res = client.post("/api/translate", json={"text": "Hello world."})

    assert res.status_code == 200
    assert res.json() == {"text": "Xin chào thế giới."}
    assert calls == ["Hello world."]


def test_sends_the_whole_document_in_one_call(api):
    """Cắt nhỏ làm system prompt lặp lại mỗi lời gọi và đốt hạn mức request."""
    client, calls = api
    document = "Hello world. " * 40
    client.post("/api/translate", json={"text": document})

    assert len(calls) == 1


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
    def broken(text: str) -> str:
        raise TranslateError("Gemini trả HTTP 500")

    _install(monkeypatch, Settings(cache_dir=tmp_path, gemini_api_key="k"), broken)
    with TestClient(main.app) as client:
        res = client.post("/api/translate", json={"text": "Hello world."})

    # 503 để giao diện biết là tạm thời và giữ nguyên văn bản gốc.
    assert res.status_code == 503


def test_reports_an_exhausted_budget_as_503(tmp_path, monkeypatch):
    def gemini(text: str) -> str:  # pragma: no cover - không được gọi
        raise AssertionError("hết ngân sách thì không được gọi ra ngoài")

    settings = Settings(cache_dir=tmp_path, gemini_api_key="k", gemini_max_per_day=0)
    _install(monkeypatch, settings, gemini, budget=DailyBudget(0))
    with TestClient(main.app) as client:
        res = client.post("/api/translate", json={"text": "Hello world."})

    assert res.status_code == 503


def test_missing_key_is_reported_not_crashed(tmp_path, monkeypatch):
    _install(monkeypatch, Settings(cache_dir=tmp_path, gemini_api_key=""),
             lambda t: "khong duoc goi")
    with TestClient(main.app) as client:
        res = client.post("/api/translate", json={"text": "Hello world."})

    assert res.status_code == 503


def test_rate_limit_applies(tmp_path, monkeypatch):
    settings = Settings(cache_dir=tmp_path, gemini_api_key="k")
    _install(monkeypatch, settings, lambda t: t)
    # burst=0 nữa, vì BURST mặc định là 20 nên chỉ đặt 0/phút thì request đầu
    # tiên vẫn lọt.
    monkeypatch.setattr(main, "limiter", RateLimiter(0, burst=0))
    with TestClient(main.app) as client:
        res = client.post("/api/translate", json={"text": "Hello world."})

    assert res.status_code == 429
    assert res.headers["Retry-After"]
