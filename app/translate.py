"""Dịch văn bản tiếng Anh sang tiếng Việt trước khi đọc.

Tách hẳn khỏi luồng TTS: nút "Dịch" trên giao diện biến đổi ô nhập tại chỗ,
giống nút "Xuống dòng". Nhờ vậy `text.py`, cache audio và hàng đợi không hề
thay đổi, và khi dịch hỏng thì giọng đọc chính vẫn nguyên vẹn.

Dùng MyMemory vì đo được là endpoint dịch miễn phí duy nhất còn chạy: endpoint
không chính thức của Google chặn IP máy chủ này sau khoảng 20 request và không
mở lại sau nhiều phút, còn Bing đã đổi cơ chế chống lạm dụng và trả 401.

Vấn đề cốt lõi của mọi máy dịch thống kê: chúng không có khái niệm "token này
là code". Đo được các lỗi thật:

    single-flight   -> "một chuyến bay"
    POST /api/tts   -> "BÀI /api/tts"
    Docker COPY     -> "BẢN SAO Docker"
    world-readable  -> "đọc được trên toàn thế giới"
    markdown        -> "điểm đánh dấu"

Danh sách từ khoá không chữa được, vì POST và COPY là từ tiếng Anh bình thường
— chỉ ngữ cảnh mới làm chúng thành thuật ngữ. Nên ở đây nhận diện theo HÌNH
DẠNG token: cái gì trông như code thì thay bằng giữ chỗ, dịch xong trả lại.
Cách này bắt được cả định danh chưa từng gặp.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Callable

log = logging.getLogger(__name__)

# MyMemory trả 403 "QUERY LENGTH LIMIT EXCEEDED. MAX ALLOWED QUERY : 500 CHARS".
# Chừa biên vì phần văn bản còn phải cộng thêm tham số khác trong URL.
MAX_QUERY_CHARS = 470

_ENDPOINT = "https://api.mymemory.translated.net/get"
_LANG_PAIR = "en|vi"

# Giữ chỗ phải KHÔNG khớp bất kỳ mẫu nào bên dưới, nếu không nó bị bọc chồng
# lên chính nó và khôi phục sẽ dở dang. Chữ thường + chữ số nên không dính mẫu
# ALL-CAPS, camelCase hay snake_case.
_PLACEHOLDER = "zq{}qz"

# Thuật ngữ không nhận ra được bằng hình dạng: chúng là từ thường viết thường
# hoặc chỉ viết hoa chữ đầu. Mỗi mục ở đây đều là lỗi ĐO ĐƯỢC, không phải đoán.
# Cố ý KHÔNG có "cache": máy dịch trả "bộ nhớ cache" vốn đã đúng, bọc thêm chỉ
# tăng rủi ro giữ nguyên tiếng Anh ở chỗ đáng ra nên dịch.
TERMS: tuple[str, ...] = (
    "world-readable", "single-flight", "no-new-privileges", "edge-tts",
    "lookbehind", "container", "endpoint", "middleware", "frontend", "backend",
    "Cloudflare", "Docker", "Safari", "sox", "ffmpeg", "uvicorn", "pytest",
)

# MỘT biểu thức duy nhất, quét MỘT lượt. Nhiều lượt nối tiếp thì lượt sau bọc
# lại giữ chỗ của lượt trước — lỗi này đã xảy ra thật, xem test hồi quy
# test_placeholder_is_not_protected_again.
_PROTECT = re.compile("|".join((
    r"`[^`]+`",                                # đoạn trong dấu backtick
    r"(?<![\w/])/?[\w.-]+(?:/[\w.-]*)+",       # đường dẫn: static/  /api/tts
    r"(?<!\w)--[A-Za-z][\w-]*",                # cờ dòng lệnh: --no-cache
    r"\b\w+(?:\.\w+)+\b",                      # có dấu chấm: tts.py
    r"\b\w*_\w+\b",                            # snake_case, MAX_WORDS_PER_LINE
    r"\b[a-z]+[A-Z]\w*\b",                     # camelCase: updateButtons
    r"\b[A-Z][a-z]+[A-Z]\w*\b",                # PascalCase: StaticFiles
    r"\b[A-Z][a-z]+(?:-[A-Z][a-z]+)+\b",       # tên header: Content-Length
    r"\b[A-Z][A-Z0-9]+\b",                     # ALL CAPS: POST, COPY, HTTP
    r"(?i:(?<!\w)(?:%s)(?!\w))" % "|".join(
        re.escape(t) for t in sorted(TERMS, key=len, reverse=True)
    ),
)))

Fetcher = Callable[[str], str]


class TranslateError(RuntimeError):
    """Dịch vụ dịch không trả về được kết quả."""


def protect(text: str) -> tuple[str, dict[str, str]]:
    """Thay mọi token trông như code bằng giữ chỗ. Trả về (văn bản, bảng tra)."""
    saved: dict[str, str] = {}
    counter = 0

    def take(match: re.Match[str]) -> str:
        nonlocal counter
        key = _PLACEHOLDER.format(counter)
        saved[key] = match.group(0)
        counter += 1
        return key

    return _PROTECT.sub(take, text), saved


def restore(text: str, saved: dict[str, str]) -> str:
    """Trả token gốc về chỗ cũ, bỏ dấu backtick bao ngoài.

    Không phân biệt hoa thường vì máy dịch hay viết hoa chữ đầu câu, kể cả khi
    chữ đầu câu lại đúng là một giữ chỗ.
    """
    for key in sorted(saved, key=len, reverse=True):
        text = re.sub(re.escape(key), lambda _: saved[key].strip("`"), text, flags=re.I)
    return text


def _hard_split(sentence: str, limit: int) -> list[str]:
    """Cắt một câu dài quá giới hạn theo ranh giới từ."""
    parts: list[str] = []
    current = ""
    for word in sentence.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > limit:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def split_chunks(text: str, limit: int = MAX_QUERY_CHARS) -> list[str]:
    """Cắt theo ranh giới câu, không mảnh nào vượt quá `limit`.

    Cắt cứng giữa câu làm máy dịch mất ngữ cảnh và ghép lại nghe rất gượng, nên
    chỉ cắt cứng khi bản thân một câu đã dài hơn giới hạn.
    """
    chunks: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.;:!?])\s+", text.strip()):
        if not sentence.strip():
            continue
        if len(sentence) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(sentence, limit))
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def translate(
    text: str, *, fetch: Fetcher, limit: int = MAX_QUERY_CHARS
) -> str:
    """Dịch `text` sang tiếng Việt, giữ nguyên các token trông như code."""
    masked, saved = protect(" ".join(text.split()))
    chunks = split_chunks(masked, limit)
    if not chunks:
        return ""

    out: list[str] = []
    for chunk in chunks:
        try:
            translated = await asyncio.to_thread(fetch, chunk)
        except TranslateError:
            raise
        except Exception as exc:
            # Bắt rộng ở đúng ranh giới gọi ra ngoài, cùng lý do như tts.py.
            raise TranslateError(f"{type(exc).__name__}: {exc}") from exc

        expected = [key for key in saved if key in chunk]
        if any(key.lower() not in translated.lower() for key in expected):
            # Máy dịch nuốt mất giữ chỗ thì bản dịch đã hỏng: thà giữ nguyên
            # tiếng Anh còn hơn trả ra câu thiếu định danh.
            log.warning("Bản dịch làm mất giữ chỗ, giữ nguyên đoạn gốc")
            translated = chunk
        out.append(translated.strip())

    return restore(" ".join(out), saved)


def _mymemory(chunk: str, *, email: str, timeout: int) -> str:
    params = {"q": chunk, "langpair": _LANG_PAIR}
    if email:
        # Kèm email nâng hạn mức ẩn danh từ 5.000 lên 50.000 ký tự mỗi ngày.
        params["de"] = email
    request = urllib.request.Request(
        f"{_ENDPOINT}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "langnghe/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)

    if payload.get("quotaFinished"):
        raise TranslateError("MyMemory đã hết hạn mức dịch trong ngày")
    if str(payload.get("responseStatus")) != "200":
        raise TranslateError(
            f"MyMemory từ chối ({payload.get('responseStatus')}): "
            f"{str(payload.get('responseDetails'))[:120]}"
        )
    translated = payload.get("responseData", {}).get("translatedText")
    if not translated:
        raise TranslateError("MyMemory trả về chuỗi rỗng")
    return str(translated)


def make_fetcher(email: str, timeout: int) -> Fetcher:
    """Tạo hàm gọi MyMemory. Tách ra để test tiêm bản giả, không chạm mạng."""
    def fetch(chunk: str) -> str:
        return _mymemory(chunk, email=email, timeout=timeout)
    return fetch
