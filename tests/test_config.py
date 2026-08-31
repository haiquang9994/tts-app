from pathlib import Path

from app.config import DEFAULT_VOICE, VOICES, load_settings


def test_load_settings_dung_mac_dinh_khi_env_rong():
    s = load_settings({})
    assert s.tts_fallback_voice == "vi-VN-HoaiMyNeural"
    assert s.tts_rate == "+20%"
    assert s.tts_max_concurrency == 4
    assert s.tts_timeout_seconds == 30
    assert s.max_text_length == 1000
    assert s.rate_limit_per_minute == 60
    assert s.cache_dir == Path("mp3")
    assert s.cache_max_mb == 512
    assert s.cache_check_every == 50
    assert s.log_level == "INFO"


def test_load_settings_doc_gia_tri_tu_env():
    s = load_settings({"TTS_RATE": "+50%", "MAX_TEXT_LENGTH": "42", "CACHE_DIR": "/data/mp3"})
    assert s.tts_rate == "+50%"
    assert s.max_text_length == 42
    assert s.cache_dir == Path("/data/mp3")


def test_load_settings_bo_qua_so_khong_hop_le_va_lay_mac_dinh():
    s = load_settings({"MAX_TEXT_LENGTH": "khong-phai-so"})
    assert s.max_text_length == 1000


def test_allowlist_giong_dung_hai_giong_tieng_viet():
    assert set(VOICES) == {"vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"}
    assert DEFAULT_VOICE in VOICES
