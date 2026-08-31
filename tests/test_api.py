import base64

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.limits import RateLimiter
from app.tts import Synthesizer


@pytest.fixture
def moi_truong(tmp_path, monkeypatch):
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


def test_tra_ve_dung_shape_ma_frontend_doc(moi_truong):
    client, _ = moi_truong
    res = client.post("/api/tts", json={"text": "Xin chào. Tôi là Nam."})

    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"text", "base64", "name"}
    assert body["text"] == "Xin chào. Tôi là Nam."
    assert base64.b64decode(body["base64"]) == b"FAKE-MP3"
    assert len(body["name"]) == 32


def test_duong_dan_cu_text_to_speech_van_chay(moi_truong):
    client, _ = moi_truong
    res = client.post("/text-to-speech", json={"text": "Xin chào."})
    assert res.status_code == 200
    assert res.json()["text"] == "Xin chào."


def test_provider_nhan_dung_van_ban_da_chuan_hoa(moi_truong):
    client, calls = moi_truong
    client.post("/api/tts", json={"text": "Xin chào.  Tôi tên Nam."})
    assert calls == ["Xin chào. Tôi tên Nam."]


def test_bo_qua_truong_thua_voice_va_rate(moi_truong):
    # API không còn nhận hai trường này; gửi lên cũng không được phép làm hỏng.
    client, calls = moi_truong
    res = client.post(
        "/api/tts",
        json={"text": "Xin chào.", "voice": "en-US-JennyNeural", "rate": "+999%"},
    )
    assert res.status_code == 200
    assert calls == ["Xin chào."]


def test_khong_pha_duong_dan_file(moi_truong):
    client, calls = moi_truong
    res = client.post("/api/tts", json={"text": ".claude/features/client-surface.md"})
    assert res.status_code == 200
    assert calls == [".claude/features/client-surface.md."]


def test_lan_thu_hai_lay_tu_cache_khong_goi_provider(moi_truong):
    client, calls = moi_truong
    client.post("/api/tts", json={"text": "Xin chào."})
    client.post("/api/tts", json={"text": "Xin chào."})
    assert len(calls) == 1


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_text_rong_tra_422(moi_truong, text):
    client, _ = moi_truong
    assert client.post("/api/tts", json={"text": text}).status_code == 422


def test_thieu_truong_text_tra_422(moi_truong):
    client, _ = moi_truong
    assert client.post("/api/tts", json={}).status_code == 422


def test_text_qua_dai_tra_413(moi_truong):
    client, _ = moi_truong
    res = client.post("/api/tts", json={"text": "a" * 1001})
    assert res.status_code == 413


@pytest.mark.parametrize("text", [" - ", "...", "!!!", "--", "  .  "])
def test_van_ban_toan_dau_cau_tra_422(moi_truong, text):
    # Không có chữ hay số nào -> không đáng gọi TTS.
    client, calls = moi_truong
    res = client.post("/api/tts", json={"text": text})
    assert res.status_code == 422
    assert calls == []


def test_van_ban_chi_co_so_van_duoc_doc(moi_truong):
    client, _ = moi_truong
    assert client.post("/api/tts", json={"text": "2026"}).status_code == 200


def test_tts_hong_tra_503_chu_khong_phai_500(tmp_path, monkeypatch):
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


def test_vuot_rate_limit_tra_429_kem_retry_after(tmp_path, monkeypatch):
    settings = Settings(cache_dir=tmp_path)

    async def provider(text):
        return b"FAKE-MP3"

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "synthesizer", Synthesizer(settings, primary=provider))
    monkeypatch.setattr(main, "limiter", RateLimiter(per_minute=60, burst=2))

    with TestClient(main.app) as client:
        ma = [client.post("/api/tts", json={"text": f"Câu {i}."}).status_code for i in range(4)]
        res = client.post("/api/tts", json={"text": "Câu nữa."})

    assert ma[:2] == [200, 200]
    assert 429 in ma
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_healthz_van_chay(moi_truong):
    client, _ = moi_truong
    assert client.get("/healthz").json() == {"status": "ok"}


def test_trang_chu_tra_ve_html(moi_truong):
    client, _ = moi_truong
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


@pytest.mark.parametrize("path", ["/about", "/about/"])
def test_trang_about_nhan_ca_hai_dang_duong_dan(moi_truong, path):
    client, _ = moi_truong
    assert client.get(path).status_code == 200
