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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from . import cache

log = logging.getLogger(__name__)

# Định danh biến thể bản dịch, nằm trong khoá cache. Đổi nhà cung cấp dịch thì
# phải đổi giá trị này, nếu không bản dịch cũ của nhà cũ sẽ bị dùng lại.
# Đổi TERMS hay _PROTECT thì không cần: chúng làm đổi luôn đoạn đã che.
TRANSLATE_VARIANT = "mymemory-en-vi"
_CACHE_SUFFIX = ".txt"

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

# Dấu Markdown đứng đầu đoạn.
#
# ĐO ĐƯỢC: có những đoạn bắt đầu bằng "##" mà MyMemory trả về NGUYÊN VĂN,
# không dịch gì cả. Cùng đoạn đó bỏ "##" đi thì dịch bình thường, lặp lại 3/3
# lần. Nhưng KHÔNG phải mọi đoạn có "##" đều hỏng: đoạn ngắn thì không sao, và
# một tiêu đề dài 130 ký tự toàn văn xuôi cũng không sao. Điều kiện kích hoạt
# chính xác chưa mô tả được — có vẻ cần cả dấu đầu đoạn lẫn nội dung nhiều ký
# hiệu.
#
# Nên việc tách dấu ở đây là phòng thủ: nó vô hại với đoạn vốn đã dịch được, và
# cứu được đoạn hỏng. Cố ý KHÔNG viết test khẳng định kiểu hỏng của MyMemory —
# một test như vậy phụ thuộc vào thứ ta chưa hiểu hết nên sẽ đỏ ngẫu nhiên.
_LEADING_MARKUP = re.compile(
    r"^(?:#{1,6}(?:\s+|$)|[-*+](?:\s+|$)|>\s*|\d{1,3}[.)](?:\s+|$))+"
)

Fetcher = Callable[[str], str]


# Số lời gọi đồng thời. Giữ thấp: đây là dịch vụ miễn phí, bắn 20 request một
# lúc vừa bất lịch sự vừa dễ bị chặn. 4 đủ để một tài liệu dài xong trong vài
# giây thay vì gần một phút.
_CONCURRENCY = 4


class TranslateError(RuntimeError):
    """Dịch vụ dịch không trả về được kết quả."""


class QuotaExhausted(TranslateError):
    """Hết hạn mức trong ngày.

    Tách riêng để dừng NGAY: các đoạn còn lại chắc chắn cũng hỏng, và trả về
    một tài liệu dịch dở nửa chừng còn khó hiểu hơn là báo lỗi thẳng.
    """


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
    text: str,
    *,
    fetch: Fetcher,
    limit: int = MAX_QUERY_CHARS,
    cache_dir: Path | None = None,
) -> str:
    """Dịch `text` sang tiếng Việt, giữ nguyên các token trông như code.

    Một đoạn hỏng thì giữ nguyên tiếng Anh đoạn đó chứ không bỏ cả bản dịch:
    với tài liệu dài, mất một câu còn hơn mất tất cả. Chỉ khi MỌI đoạn đều
    hỏng mới báo lỗi ra ngoài.

    Cache theo TỪNG ĐOẠN chứ không theo cả văn bản: sửa một câu rồi dán lại
    thì những câu còn nguyên vẫn lấy từ cache, chỉ câu đã sửa mới tốn hạn mức.
    """
    masked, saved = protect(" ".join(text.split()))
    chunks = split_chunks(masked, limit)
    if not chunks:
        return ""

    semaphore = asyncio.Semaphore(_CONCURRENCY)
    failures = 0
    hits = 0
    # Hết hạn mức thì mọi đoạn còn lại chắc chắn cũng hỏng. Cờ này để các đoạn
    # đang xếp hàng ở semaphore bỏ cuộc luôn thay vì vẫn gọi ra ngoài.
    quota_gone = False

    async def translate_one(chunk: str) -> str:
        nonlocal failures, hits, quota_gone
        marker = _LEADING_MARKUP.match(chunk)
        prefix = marker.group(0) if marker else ""
        body = chunk[len(prefix):]
        if not body.strip():
            # Cả đoạn chỉ là dấu Markdown, ví dụ số thứ tự "2." bị tách rời.
            return chunk

        expected = [key for key in saved if key in body]
        last: BaseException | None = None

        # Khoá cache tính trên phần THÂN đã che: đã bao gồm cách đánh số giữ
        # chỗ nên khớp chính xác mới ghép lại đúng, mà bỏ dấu đầu đoạn ra thì
        # cùng một câu ở tiêu đề hay trong văn xuôi vẫn dùng lại được cache.
        key = cache.cache_key(body, TRANSLATE_VARIANT, _LANG_PAIR)
        if cache_dir is not None:
            cached = cache.read(cache_dir, key, _CACHE_SUFFIX)
            if cached is not None:
                hits += 1
                return prefix + cached.decode("utf-8")

        async with semaphore:
            for attempt in range(2):
                if quota_gone:
                    raise QuotaExhausted("MyMemory đã hết hạn mức dịch trong ngày")
                try:
                    translated = await asyncio.to_thread(fetch, body)
                except QuotaExhausted:
                    quota_gone = True
                    raise
                except Exception as exc:
                    # Bắt rộng ở đúng ranh giới gọi ra ngoài, cùng lý do
                    # như tts.py.
                    last = exc
                    continue

                if any(key.lower() not in translated.lower() for key in expected):
                    # Máy dịch nuốt mất giữ chỗ thì bản dịch đã hỏng: câu
                    # thiếu định danh còn tệ hơn câu chưa dịch.
                    last = TranslateError("bản dịch làm mất giữ chỗ")
                    continue

                translated = translated.strip()
                if cache_dir is not None:
                    # Chỉ ghi bản dịch tốt. Đoạn hỏng mà cache lại thì lần sau
                    # vẫn hỏng y như vậy, mà không còn cơ hội gọi lại.
                    cache.write(cache_dir, key, translated.encode("utf-8"), _CACHE_SUFFIX)
                return prefix + translated

        failures += 1
        log.warning("Giữ nguyên tiếng Anh một đoạn: %s", last)
        return chunk

    parts = await asyncio.gather(*(translate_one(c) for c in chunks))
    if failures == len(chunks):
        raise TranslateError(f"mọi đoạn đều hỏng ({len(chunks)} đoạn)")

    log.info("Dịch %d đoạn: %d lấy từ cache, %d hỏng", len(chunks), hits, failures)
    return restore(" ".join(parts), saved)


def _mymemory(chunk: str, *, email: str, timeout: int) -> str:
    params = {"q": chunk, "langpair": _LANG_PAIR}
    if email:
        # Kèm email nâng hạn mức ẩn danh từ 5.000 lên 50.000 ký tự mỗi ngày.
        params["de"] = email
    request = urllib.request.Request(
        f"{_ENDPOINT}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "langnghe/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # ĐO ĐƯỢC: hết hạn mức thì MyMemory trả 429 chứ KHÔNG bật cờ
        # quotaFinished. Không bắt ở đây thì mỗi đoạn còn bị thử lại một lần
        # nữa — 22 đoạn thành 44 request nện vào dịch vụ đang bảo dừng.
        if exc.code == 429:
            raise QuotaExhausted(
                "MyMemory trả 429: hết hạn mức trong ngày hoặc gọi quá nhanh"
            ) from exc
        raise TranslateError(f"MyMemory trả HTTP {exc.code}") from exc

    # Vẫn kiểm tra cờ: tài liệu của họ có nhắc tới nó, chỉ là thực tế đo được
    # thì 429 tới trước.
    if payload.get("quotaFinished"):
        raise QuotaExhausted("MyMemory đã hết hạn mức dịch trong ngày")
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
