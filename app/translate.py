"""Dịch văn bản tiếng Anh sang tiếng Việt trước khi đọc.

Tách hẳn khỏi luồng TTS: nút "Dịch" trên giao diện biến đổi ô nhập tại chỗ,
giống nút "Xuống dòng". Nhờ vậy `text.py`, cache audio và hàng đợi không hề
thay đổi, và khi dịch hỏng thì giọng đọc chính vẫn nguyên vẹn.

Nhà cung cấp duy nhất là Gemini. Project từng dùng MyMemory làm lớp dự phòng
miễn phí và đã gỡ bỏ; lý do cùng toàn bộ số đo nằm trong docs/translation.md.
Tóm tắt: máy dịch thống kê không có khái niệm "token này là code", nên
`single-flight` thành "một chuyến bay" và `POST` thành "BÀI". Chống đỡ chuyện
đó cần cả một bộ máy che định danh, cắt đoạn và tách dấu Markdown — mà một mô
hình hiểu chỉ dẫn thì chỉ cần một câu trong prompt.

Không có lớp dự phòng là có chủ đích: hỏng thì báo 503 để người dùng biết, còn
hơn lặng lẽ trả về bản dịch kém hẳn mà họ tưởng là bản tốt.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from . import cache
from .config import Settings

log = logging.getLogger(__name__)

# Định danh biến thể bản dịch, nằm trong khoá cache. Đổi nhà cung cấp hoặc sửa
# prompt theo cách làm kết quả khác đi thì phải đổi giá trị này, nếu không bản
# dịch cũ vẫn bị dùng lại. Tên model đã nằm sẵn trong khoá nên đổi model thì
# không cần đụng tới đây.
GEMINI_VARIANT = "gemini-vi"
_CACHE_SUFFIX = ".txt"

_GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Yêu cầu chú giải song ngữ — "giới hạn tốc độ (rate limit)" — là thứ kéo chất
# lượng lên ngang bản dịch thủ công người dùng vẫn tự làm. Nó là PHONG CÁCH
# chứ không phải năng lực model, nên viết được thành chỉ dẫn.
_SYSTEM_PROMPT = (
    "You are translating technical documentation from English to Vietnamese for a "
    "developer who will read it to judge whether a design is sound.\n"
    "Rules:\n"
    "- Keep in English: identifiers, function names, file paths, CLI commands, "
    "anything inside backticks, HTTP verbs, product names, error codes.\n"
    "- For a technical term that has a common Vietnamese rendering, translate it and "
    "put the English in parentheses on first use, e.g. "
    '"giới hạn tốc độ (rate limit)", "lớp bao bọc (wrapper)".\n'
    "- Preserve the Markdown structure and line breaks exactly as given.\n"
    "- Natural Vietnamese with correct diacritics. Favour the meaning of the sentence "
    "over word-by-word fidelity.\n"
    "- Output only the translation, no preamble."
)

_SECONDS_PER_DAY = 86_400

Fetcher = Callable[[str], str]


class TranslateError(RuntimeError):
    """Không dịch được. Giao diện giữ nguyên văn bản gốc khi gặp lỗi này."""


class DailyBudget:
    """Trần cứng số lần gọi mỗi ngày.

    Đây là lớp chặn CHI PHÍ, độc lập với lớp chặn TRUY CẬP. Cloudflare Access
    quyết định ai vào được; cái này quyết định tiêu được bao nhiêu — nên nó vẫn
    có tác dụng khi Access bị cấu hình sai, hoặc khi chính ta để một vòng lặp
    chạy hỏng.

    Cố ý KHÔNG dùng ProviderGuard: cầu dao đó sinh ra để tránh bị Google chặn,
    còn ở đây ta là khách trả tiền. Ngữ nghĩa "50 lần mỗi ngày" cũng rõ hơn hẳn
    một token bucket nhỏ giọt theo giờ.
    """

    def __init__(self, max_per_day: int, clock=time.time) -> None:
        self._max = max_per_day
        self._clock = clock
        self._day: int | None = None
        self._used = 0

    def _roll_over(self) -> None:
        day = int(self._clock() // _SECONDS_PER_DAY)
        if day != self._day:
            self._day = day
            self._used = 0

    def allow(self) -> bool:
        self._roll_over()
        if self._used >= self._max:
            return False
        self._used += 1
        return True

    def remaining(self) -> int:
        self._roll_over()
        return max(0, self._max - self._used)


def gemini_translate(text: str, *, api_key: str, model: str, timeout: int) -> str:
    """Dịch cả tài liệu bằng MỘT lời gọi.

    Không cắt nhỏ: mô hình hưởng lợi từ ngữ cảnh cả tài liệu, mà cắt nhỏ còn
    làm system prompt bị lặp lại mỗi lời gọi — đo được là đắt hơn 36% với một
    tài liệu đọc hết, đồng thời đốt hạn mức request mỗi ngày.
    """
    body = {
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        # Nhiệt độ thấp: đây là việc dịch, không phải việc sáng tác.
        "generationConfig": {"temperature": 0.2},
    }
    request = urllib.request.Request(
        f"{_GEMINI_ENDPOINT.format(model=model)}?key={urllib.parse.quote(api_key)}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # KHÔNG đưa phần thân lỗi vào thông báo: URL có chứa API key, mà thông
        # báo này đi thẳng vào log.
        raise TranslateError(f"Gemini trả HTTP {exc.code}") from exc

    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as exc:
        # Thường là bị bộ lọc an toàn chặn, hoặc cụt vì hết token đầu ra.
        raise TranslateError(
            f"Gemini không trả về nội dung: {str(payload)[:200]}"
        ) from exc

    out = "".join(p.get("text", "") for p in parts).strip()
    if not out:
        raise TranslateError("Gemini trả về chuỗi rỗng")
    return out


def make_gemini_fetcher(api_key: str, model: str, timeout: int) -> Fetcher:
    """Tách ra để test tiêm bản giả, không chạm mạng."""
    def fetch(text: str) -> str:
        return gemini_translate(text, api_key=api_key, model=model, timeout=timeout)
    return fetch


class Translator:
    """Dịch, có cache đĩa và trần chi phí theo ngày."""

    def __init__(
        self,
        settings: Settings,
        gemini: Fetcher | None = None,
        budget: DailyBudget | None = None,
    ) -> None:
        self._settings = settings
        self._gemini = gemini or make_gemini_fetcher(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.gemini_timeout_seconds,
        )
        self.budget = budget or DailyBudget(settings.gemini_max_per_day)

    async def translate(self, text: str) -> str:
        cache_dir = self._settings.cache_dir
        key = cache.cache_key(text, GEMINI_VARIANT, self._settings.gemini_model)

        cached = cache.read(cache_dir, key, _CACHE_SUFFIX)
        if cached is not None:
            return cached.decode("utf-8")

        if not self._settings.gemini_api_key:
            raise TranslateError("Chưa cấu hình GEMINI_API_KEY")

        # Ngân sách chỉ bị tiêu khi thật sự gọi ra ngoài, nên đọc lại tài liệu
        # cũ không ăn vào trần ngày.
        if not self.budget.allow():
            raise TranslateError(
                f"Hết ngân sách dịch trong ngày "
                f"({self._settings.gemini_max_per_day} lần)"
            )

        try:
            out = await asyncio.to_thread(self._gemini, text)
        except TranslateError:
            raise
        except Exception as exc:
            # Bắt rộng ở đúng ranh giới gọi ra ngoài, cùng lý do như tts.py:
            # lỗi mạng của urllib không nằm trong một cây thừa kế gọn gàng nào.
            raise TranslateError(f"{type(exc).__name__}: {exc}") from exc

        cache.write(cache_dir, key, out.encode("utf-8"), _CACHE_SUFFIX)
        return out
