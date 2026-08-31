"""Cấu hình đọc từ biến môi trường."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

# Giọng edge-tts hợp lệ. Chỉ dùng để kiểm tra biến môi trường TTS_FALLBACK_VOICE
# — người dùng không chọn được giọng, giao diện không có tuỳ chọn này.
VOICES: dict[str, str] = {
    "vi-VN-HoaiMyNeural": "Nữ (HoaiMy)",
    "vi-VN-NamMinhNeural": "Nam (NamMinh)",
}
DEFAULT_VOICE = "vi-VN-HoaiMyNeural"

# Cách tăng tốc audio gTTS, chọn bằng TTS_SPEED_MODE:
#   tempo    — WSOLA, đọc nhanh hơn nhưng giữ nguyên cao độ.
#   resample — đổi sample rate: nhanh hơn thì giọng cũng cao lên đúng tỉ lệ,
#              nghe "chói" hơn. Về mặt kỹ thuật là méo giọng, nhưng có người
#              thích đúng chất giọng đó nên nó là một lựa chọn, không phải lỗi.
SPEED_MODES: tuple[str, ...] = ("tempo", "resample")
DEFAULT_SPEED_MODE = "tempo"


@dataclass(frozen=True)
class Settings:
    # Giọng edge-tts dùng khi gTTS hỏng. Bản dự phòng KHÔNG đổi tốc độ.
    tts_fallback_voice: str = DEFAULT_VOICE
    # Tốc độ áp cho gTTS qua sox.
    tts_rate: str = "+20%"
    # Cao độ có đổi theo tốc độ hay không — xem SPEED_MODES ở trên.
    tts_speed_mode: str = DEFAULT_SPEED_MODE
    tts_max_concurrency: int = 4
    tts_timeout_seconds: int = 30
    max_text_length: int = 1000
    rate_limit_per_minute: int = 60
    # Giới hạn riêng cho dịch: cả tài liệu đi trong một lời gọi Gemini, nên
    # đây vừa là trần độ dài vừa là trần chi phí cho một lần bấm nút.
    max_translate_length: int = 10000
    # Gemini là nhà cung cấp dịch duy nhất; để trống API key thì /api/translate
    # trả 503. Trần NGÀY là chặn CHI PHÍ, độc lập với chuyện ai đăng nhập được:
    # đặt 0 là tắt hẳn Gemini mà không phải xoá key.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_max_per_day: int = 50
    gemini_timeout_seconds: int = 60
    cache_dir: Path = Path("cache")
    cache_max_mb: int = 512
    cache_check_every: int = 50
    log_level: str = "INFO"
    # Ngân sách gọi gTTS mỗi phút. Hết lượt thì dùng thẳng edge-tts, không
    # chạm tới Google — đây là phần chặn trước khi bị chặn.
    gtts_max_per_minute: int = 20
    gtts_failure_threshold: int = 3
    gtts_cooldown_seconds: int = 300
    gtts_max_cooldown_seconds: int = 3600


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(env[name])
    except (KeyError, ValueError, TypeError):
        return default


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    voice = env.get("TTS_FALLBACK_VOICE", DEFAULT_VOICE)
    if voice not in VOICES:
        voice = DEFAULT_VOICE
    speed_mode = env.get("TTS_SPEED_MODE", DEFAULT_SPEED_MODE)
    if speed_mode not in SPEED_MODES:
        speed_mode = DEFAULT_SPEED_MODE
    return Settings(
        tts_fallback_voice=voice,
        tts_rate=env.get("TTS_RATE", "+20%"),
        tts_speed_mode=speed_mode,
        tts_max_concurrency=_int(env, "TTS_MAX_CONCURRENCY", 4),
        tts_timeout_seconds=_int(env, "TTS_TIMEOUT_SECONDS", 30),
        max_text_length=_int(env, "MAX_TEXT_LENGTH", 1000),
        rate_limit_per_minute=_int(env, "RATE_LIMIT_PER_MINUTE", 60),
        max_translate_length=_int(env, "MAX_TRANSLATE_LENGTH", 10000),
        gemini_api_key=env.get("GEMINI_API_KEY", ""),
        gemini_model=env.get("GEMINI_MODEL", "gemini-flash-lite-latest"),
        gemini_max_per_day=_int(env, "GEMINI_MAX_PER_DAY", 50),
        gemini_timeout_seconds=_int(env, "GEMINI_TIMEOUT_SECONDS", 60),
        cache_dir=Path(env.get("CACHE_DIR", "cache")),
        cache_max_mb=_int(env, "CACHE_MAX_MB", 512),
        cache_check_every=_int(env, "CACHE_CHECK_EVERY", 50),
        log_level=env.get("LOG_LEVEL", "INFO"),
        gtts_max_per_minute=_int(env, "GTTS_MAX_PER_MINUTE", 20),
        gtts_failure_threshold=_int(env, "GTTS_FAILURE_THRESHOLD", 3),
        gtts_cooldown_seconds=_int(env, "GTTS_COOLDOWN_SECONDS", 300),
        gtts_max_cooldown_seconds=_int(env, "GTTS_MAX_COOLDOWN_SECONDS", 3600),
    )
