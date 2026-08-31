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

# Đường dẫn tài nguyên tĩnh xuất hiện trong HTML, để gắn thêm phiên bản.
_DUONG_DAN_TAI_NGUYEN = re.compile(r"/static/[A-Za-z0-9_./-]+?\.(?:js|css|png|svg)")

# HTML đã gắn phiên bản, dựng một lần lúc khởi động.
_TRANG: dict[str, str] = {}


def _bam_noi_dung(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()[:10]


def _gan_phien_ban(html: str) -> str:
    """Thêm ?v=<băm nội dung> vào mọi đường dẫn tĩnh trong HTML.

    Cloudflare cache tài nguyên tĩnh nhiều giờ. Không có bước này thì sau mỗi
    lần deploy người dùng nhận HTML mới nhưng JS/CSS cũ — hai bản lệch nhau và
    trang lỗi. Băm theo nội dung nên URL chỉ đổi khi file thật sự đổi.
    """

    def thay(m: re.Match[str]) -> str:
        p = STATIC_DIR / m.group(0)[len("/static/"):]
        return f"{m.group(0)}?v={_bam_noi_dung(p)}" if p.is_file() else m.group(0)

    return _DUONG_DAN_TAI_NGUYEN.sub(thay, html)


def _nap_trang() -> None:
    for ten in ("index.html", "about.html"):
        _TRANG[ten] = _gan_phien_ban((STATIC_DIR / ten).read_text("utf-8"))


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
    _nap_trang()
    yield


app = FastAPI(title="Tự động đọc", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def header_cache_tai_nguyen(request: Request, call_next):
    """Buộc cache kiểm tra lại tài nguyên tĩnh.

    Lớp bảo vệ thứ hai sau việc gắn ?v= — phòng khi có tài nguyên nào được
    tham chiếu mà không đi qua HTML.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    # Không gọi ra mạng ngoài: healthcheck chỉ để biết tiến trình còn sống,
    # không được đỏ chỉ vì nhà cung cấp TTS đang chập chờn.
    return {"status": "ok"}


@app.get("/")
async def trang_chu() -> HTMLResponse:
    return HTMLResponse(_TRANG["index.html"])


@app.get("/about")
@app.get("/about/")
async def trang_gioi_thieu() -> HTMLResponse:
    return HTMLResponse(_TRANG["about.html"])


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
