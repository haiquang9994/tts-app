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


@dataclass(frozen=True)
class Settings:
    # Giọng edge-tts dùng khi gTTS hỏng. Bản dự phòng KHÔNG đổi tốc độ.
    tts_fallback_voice: str = DEFAULT_VOICE
    # Tốc độ áp cho gTTS qua bộ lọc atempo của ffmpeg (giữ nguyên cao độ).
    tts_rate: str = "+20%"
    tts_max_concurrency: int = 4
    tts_timeout_seconds: int = 30
    max_text_length: int = 1000
    rate_limit_per_minute: int = 60
    # Dịch: giới hạn riêng vì mỗi lần dán tốn nhiều request (MyMemory chỉ nhận
    # 470 ký tự một lần) và hạn mức là theo NGÀY, tính chung cho cả máy chủ.
    max_translate_length: int = 10000
    translate_timeout_seconds: int = 20
    # Kèm email nâng hạn mức ẩn danh từ 5.000 lên 50.000 ký tự mỗi ngày.
    translate_email: str = ""
    cache_dir: Path = Path("mp3")
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
    return Settings(
        tts_fallback_voice=voice,
        tts_rate=env.get("TTS_RATE", "+20%"),
        tts_max_concurrency=_int(env, "TTS_MAX_CONCURRENCY", 4),
        tts_timeout_seconds=_int(env, "TTS_TIMEOUT_SECONDS", 30),
        max_text_length=_int(env, "MAX_TEXT_LENGTH", 1000),
        rate_limit_per_minute=_int(env, "RATE_LIMIT_PER_MINUTE", 60),
        max_translate_length=_int(env, "MAX_TRANSLATE_LENGTH", 10000),
        translate_timeout_seconds=_int(env, "TRANSLATE_TIMEOUT_SECONDS", 20),
        translate_email=env.get("TRANSLATE_EMAIL", ""),
        cache_dir=Path(env.get("CACHE_DIR", "mp3")),
        cache_max_mb=_int(env, "CACHE_MAX_MB", 512),
        cache_check_every=_int(env, "CACHE_CHECK_EVERY", 50),
        log_level=env.get("LOG_LEVEL", "INFO"),
        gtts_max_per_minute=_int(env, "GTTS_MAX_PER_MINUTE", 20),
        gtts_failure_threshold=_int(env, "GTTS_FAILURE_THRESHOLD", 3),
        gtts_cooldown_seconds=_int(env, "GTTS_COOLDOWN_SECONDS", 300),
        gtts_max_cooldown_seconds=_int(env, "GTTS_MAX_COOLDOWN_SECONDS", 3600),
    )
