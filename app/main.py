"""Ứng dụng FastAPI: phục vụ file tĩnh và API chuyển văn bản thành giọng nói."""
from __future__ import annotations

import base64
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cache
from .config import load_settings
from .limits import RateLimiter, client_ip
from .text import normalize
from .tts import Synthesizer, TTSError

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

settings = load_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

synthesizer = Synthesizer(settings)
limiter = RateLimiter(settings.rate_limit_per_minute)


_CO_CHU_HOAC_SO = re.compile(r"[^\W_]", re.UNICODE)


class TTSRequest(BaseModel):
    # Không có `voice`/`rate`: giọng và tốc độ do server quyết định, giao diện
    # không cho chọn.
    text: str


def _loi(status: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    so_file = cache.cleanup_tmp(settings.cache_dir)
    if so_file:
        log.info("Dọn %d file tạm mồ côi lúc khởi động", so_file)
    cache.enforce_limit(settings.cache_dir, settings.cache_max_mb)
    yield


app = FastAPI(title="Tự động đọc", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    # Không gọi ra mạng ngoài: healthcheck chỉ để biết tiến trình còn sống,
    # không được đỏ chỉ vì nhà cung cấp TTS đang chập chờn.
    return {"status": "ok"}


@app.get("/")
async def trang_chu() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/about")
@app.get("/about/")
async def trang_gioi_thieu() -> FileResponse:
    return FileResponse(STATIC_DIR / "about.html")


@app.post("/api/tts")
@app.post("/text-to-speech")
async def text_to_speech(payload: TTSRequest, request: Request):
    cho_phep, cho_bao_lau = limiter.allow(client_ip(request))
    if not cho_phep:
        return _loi(
            429,
            "Bạn gửi quá nhanh, thử lại sau ít giây.",
            headers={"Retry-After": str(max(1, int(cho_bao_lau) + 1))},
        )

    raw = payload.text
    if not raw.strip():
        return _loi(422, "Trường 'text' không được rỗng.")
    # Kiểm tra thủ công thay vì dùng max_length của pydantic, để trả đúng 413
    # thay vì 422 lẫn với lỗi schema.
    if len(raw) > settings.max_text_length:
        return _loi(413, f"Văn bản quá dài, tối đa {settings.max_text_length} ký tự.")

    final_text = normalize(raw)
    # Không chỉ kiểm tra rỗng: chuỗi toàn dấu câu như " - " chuẩn hoá thành "-."
    # vẫn khác rỗng, mà gọi TTS để đọc một dấu gạch thì chỉ tổ phí.
    if not _CO_CHU_HOAC_SO.search(final_text):
        return _loi(422, "Văn bản không có nội dung nào để đọc.")

    try:
        key, data = await synthesizer.get_audio(final_text)
    except TTSError as exc:
        log.error("Không sinh được audio: %s", exc)
        return _loi(503, "Dịch vụ đọc đang không phản hồi, thử lại sau ít phút.")

    return {"text": final_text, "base64": base64.b64encode(data).decode(), "name": key}
