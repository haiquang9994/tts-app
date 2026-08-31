"""Ứng dụng FastAPI: phục vụ file tĩnh và API chuyển văn bản thành giọng nói."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

from .config import load_settings

BASE_DIR = Path(__file__).resolve().parent.parent

settings = load_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="Tự động đọc", docs_url=None, redoc_url=None)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    # Không gọi ra mạng ngoài: healthcheck chỉ để biết tiến trình còn sống,
    # không được đỏ chỉ vì nhà cung cấp TTS đang chập chờn.
    return {"status": "ok"}
