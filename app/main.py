"""Ứng dụng FastAPI: phục vụ file tĩnh và API chuyển văn bản thành giọng nói."""
from __future__ import annotations

import base64
import hashlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cache
from .config import load_settings
from .limits import RateLimiter, client_ip
from .text import normalize
from .translate import TranslateError, Translator
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
translator = Translator(settings)


_HAS_LETTER_OR_DIGIT = re.compile(r"[^\W_]", re.UNICODE)

# Đường dẫn tài nguyên tĩnh xuất hiện trong HTML, để gắn thêm phiên bản.
_ASSET_PATH_RE = re.compile(r"/static/[A-Za-z0-9_./-]+?\.(?:js|css|png|svg)")

# HTML đã gắn phiên bản, dựng một lần lúc khởi động.
_PAGES: dict[str, str] = {}


def _content_hash(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()[:10]


def _add_asset_versions(html: str) -> str:
    """Thêm ?v=<băm nội dung> vào mọi đường dẫn tĩnh trong HTML.

    Cloudflare cache tài nguyên tĩnh nhiều giờ. Không có bước này thì sau mỗi
    lần deploy người dùng nhận HTML mới nhưng JS/CSS cũ — hai bản lệch nhau và
    trang lỗi. Băm theo nội dung nên URL chỉ đổi khi file thật sự đổi.
    """

    def replace_one(m: re.Match[str]) -> str:
        p = STATIC_DIR / m.group(0)[len("/static/"):]
        return f"{m.group(0)}?v={_content_hash(p)}" if p.is_file() else m.group(0)

    return _ASSET_PATH_RE.sub(replace_one, html)


def _load_pages() -> None:
    for filename in ("index.html", "about.html"):
        _PAGES[filename] = _add_asset_versions((STATIC_DIR / filename).read_text("utf-8"))


class TranslateRequest(BaseModel):
    text: str


class TTSRequest(BaseModel):
    # Không có `voice`/`rate`: giọng và tốc độ do server quyết định, giao diện
    # không cho chọn.
    text: str


def _error(status: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    removed_count = cache.cleanup_tmp(settings.cache_dir)
    if removed_count:
        log.info("Dọn %d file tạm mồ côi lúc khởi động", removed_count)
    cache.enforce_limit(settings.cache_dir, settings.cache_max_mb)
    _load_pages()
    yield


app = FastAPI(title="Tự động đọc", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def static_cache_header(request: Request, call_next):
    """Buộc cache kiểm tra lại tài nguyên tĩnh.

    Lớp bảo vệ thứ hai sau việc gắn ?v= — phòng khi có tài nguyên nào được
    tham chiếu mà không đi qua HTML.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.get("/api/status")
async def status() -> dict:
    """Cờ chẩn đoán: gTTS đang chạy, đang bị chặn, hay hết ngân sách.

    Tách khỏi /healthz vì healthz phải luôn trả 200 cho Docker — nhà cung cấp
    TTS chập chờn không có nghĩa là tiến trình chết.
    """
    files = list(settings.cache_dir.glob("*.mp3"))
    translations = list(settings.cache_dir.glob("*.txt"))
    return {
        "gtts": synthesizer.guard.status(),
        # Đủ để biết container đang chạy chất giọng nào mà không phải nghe thử.
        "audio": {"rate": settings.tts_rate, "speed_mode": settings.tts_speed_mode},
        "translate": {
            # Không bao giờ trả về chính API key, chỉ trả về việc đã cấu hình
            # hay chưa.
            "gemini_configured": bool(settings.gemini_api_key),
            "gemini_model": settings.gemini_model,
            "budget_remaining_today": translator.budget.remaining(),
            "budget_per_day": settings.gemini_max_per_day,
        },
        "cache": {
            "files": len(files),
            "bytes": sum(p.stat().st_size for p in files),
            "translations": len(translations),
        },
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    # Không gọi ra mạng ngoài: healthcheck chỉ để biết tiến trình còn sống,
    # không được đỏ chỉ vì nhà cung cấp TTS đang chập chờn.
    return {"status": "ok"}


@app.get("/")
async def index_page() -> HTMLResponse:
    return HTMLResponse(_PAGES["index.html"])


@app.get("/about")
@app.get("/about/")
async def about_page() -> HTMLResponse:
    return HTMLResponse(_PAGES["about.html"])


@app.post("/api/translate")
async def translate_to_vietnamese(payload: TranslateRequest, request: Request):
    """Dịch sang tiếng Việt để người dùng xem lại trước khi thêm vào hàng đợi.

    Hoàn toàn tách khỏi luồng TTS: hỏng ở đây thì giao diện giữ nguyên văn bản
    gốc và mọi thứ khác chạy như cũ.
    """
    allowed, retry_after = limiter.allow(client_ip(request))
    if not allowed:
        return _error(
            429,
            "Bạn gửi quá nhanh, thử lại sau ít giây.",
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )

    raw = payload.text
    if not raw.strip():
        return _error(422, "Trường 'text' không được rỗng.")
    if len(raw) > settings.max_translate_length:
        return _error(
            413,
            f"Văn bản quá dài để dịch, tối đa {settings.max_translate_length} ký tự.",
        )

    try:
        translated = await translator.translate(raw)
    except TranslateError as exc:
        log.error("Không dịch được: %s", exc)
        return _error(503, "Không dịch được lúc này, thử lại sau ít phút.")

    return {"text": translated}


@app.post("/api/tts")
@app.post("/text-to-speech")
async def text_to_speech(payload: TTSRequest, request: Request):
    allowed, retry_after = limiter.allow(client_ip(request))
    if not allowed:
        return _error(
            429,
            "Bạn gửi quá nhanh, thử lại sau ít giây.",
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )

    raw = payload.text
    if not raw.strip():
        return _error(422, "Trường 'text' không được rỗng.")
    # Kiểm tra thủ công replace_one vì dùng max_length của pydantic, để trả đúng 413
    # replace_one vì 422 lẫn với lỗi schema.
    if len(raw) > settings.max_text_length:
        return _error(413, f"Văn bản quá dài, tối đa {settings.max_text_length} ký tự.")

    final_text = normalize(raw)
    # Không chỉ kiểm tra rỗng: chuỗi toàn dấu câu như " - " chuẩn hoá thành "-."
    # vẫn khác rỗng, mà gọi TTS để đọc một dấu gạch thì chỉ tổ phí.
    if not _HAS_LETTER_OR_DIGIT.search(final_text):
        return _error(422, "Văn bản không có nội dung nào để đọc.")

    try:
        key, data = await synthesizer.get_audio(final_text)
    except TTSError as exc:
        log.error("Không sinh được audio: %s", exc)
        return _error(503, "Dịch vụ đọc đang không phản hồi, thử lại sau ít phút.")

    return {"text": final_text, "base64": base64.b64encode(data).decode(), "name": key}
