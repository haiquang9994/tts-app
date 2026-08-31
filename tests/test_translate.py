"""Golden test cho lớp dịch.

Khoá hành vi theo CẢ HAI hướng, giống test_text.py: cái gì phải được bọc để
khỏi bị dịch, và cái gì phải để yên cho máy dịch xử lý. Bọc quá tay làm văn
xuôi tiếng Việt lổn nhổn chữ Anh, bọc thiếu làm hỏng định danh.
"""
from __future__ import annotations

import pytest

from app.translate import (
    _CONCURRENCY,
    QuotaExhausted,
    TranslateError,
    protect,
    restore,
    split_chunks,
    translate,
)


# --- Bọc: những gì PHẢI giữ nguyên tiếng Anh ---

@pytest.mark.parametrize("token, text", [
    ("`config.py`", "Open `config.py` now."),
    ("/api/tts", "Request flow for /api/tts here."),
    ("static/", "Every file under static/ must be readable."),
    ("--no-cache", "Pass the --no-cache flag."),
    ("aiohttp.ClientError", "Both aiohttp.ClientError and others."),
    ("strip_markdown", "The function strip_markdown removes syntax."),
    ("MAX_WORDS_PER_LINE", "Increase MAX_WORDS_PER_LINE to fifty."),
    ("updateButtons", "Call updateButtons after the request."),
    ("StaticFiles", "It makes StaticFiles send a response."),
    ("POST", "Request flow for POST here."),
    ("COPY", "Docker COPY preserves source modes."),
    ("Cloudflare", "Then Cloudflare turns it into an error."),
    ("world-readable", "It must be world-readable or it breaks."),
    ("single-flight", "It collapses duplicates via single-flight."),
])
def test_protect_keeps_code_like_tokens(token, text):
    masked, saved = protect(text)
    assert token not in masked, f"{token!r} phải được thay bằng giữ chỗ"
    assert token in saved.values()


# --- Không bọc: văn xuôi thường phải để máy dịch làm việc ---

@pytest.mark.parametrize("text", [
    "The key boundary is to strip only what is purely syntax.",
    "Stripping them is the bug, not the fix.",
    "Do not guess how the reader will hear something.",
    "Measure it, because spelling out is far longer than reading.",
    "It serves the page and reads the text out loud.",
])
def test_plain_prose_is_left_alone(text):
    masked, saved = protect(text)
    assert masked == text
    assert saved == {}


@pytest.mark.parametrize("token, text", [
    ("frontend", "One service serves the frontend and the API."),
    ("API", "One service serves the frontend and the API."),
])
def test_terms_and_acronyms_are_protected_even_in_prose(token, text):
    """frontend/API trông như văn xuôi nhưng máy dịch làm hỏng cả hai."""
    masked, saved = protect(text)
    assert token in saved.values()
    assert token not in masked


def test_restore_roundtrip():
    text = "Run `npm install`, then call updateButtons for POST /api/tts."
    masked, saved = protect(text)
    assert restore(masked, saved) == text.replace("`", "")


def test_restore_is_case_insensitive():
    """Máy dịch hay viết hoa chữ đầu câu, kể cả khi đó là giữ chỗ."""
    masked, saved = protect("updateButtons runs first.")
    assert restore(masked.upper(), saved).startswith("updateButtons")


def test_placeholder_is_not_protected_again():
    """Hồi quy: giữ chỗ từng khớp mẫu ALL-CAPS nên bị bọc chồng, khôi phục dở dang.

    Quét một lượt duy nhất mới tránh được, nên đây là test khoá cách quét.
    """
    text = "POST /api/tts uses strip_markdown and updateButtons and COPY."
    masked, saved = protect(text)
    assert restore(masked, saved) == text
    # Không giữ chỗ nào lại trỏ tới một giữ chỗ khác.
    assert not any(v.startswith("zq") and v.endswith("qz") for v in saved.values())


# --- Cắt đoạn: MyMemory từ chối truy vấn quá 500 ký tự ---

def test_chunks_never_exceed_limit():
    text = " ".join(f"This is sentence number {i}." for i in range(80))
    for chunk in split_chunks(text, 100):
        assert len(chunk) <= 100


def test_chunks_split_on_sentence_boundary():
    text = "First sentence here. Second sentence here. Third sentence here."
    assert split_chunks(text, 40) == [
        "First sentence here.",
        "Second sentence here.",
        "Third sentence here.",
    ]


def test_chunks_hard_split_a_single_long_sentence():
    """Câu dài hơn giới hạn vẫn phải cắt, nếu không MyMemory trả 403."""
    text = "word " * 60
    chunks = split_chunks(text, 50)
    assert chunks and all(len(c) <= 50 for c in chunks)
    assert "".join(c.replace(" ", "") for c in chunks) == text.replace(" ", "")


def test_chunks_ignore_empty_input():
    assert split_chunks("   ", 100) == []


# --- Dịch ---

@pytest.mark.asyncio
async def test_translate_joins_chunks_in_order():
    seen: list[str] = []

    def fake(chunk: str) -> str:
        seen.append(chunk)
        return {"One here.": "Một.", "Two here.": "Hai."}[chunk]

    out = await translate("One here. Two here.", fetch=fake, limit=12)
    # Chạy song song nên thứ tự GỌI không xác định, nhưng thứ tự GHÉP thì phải.
    assert sorted(seen) == ["One here.", "Two here."]
    assert out == "Một. Hai."


@pytest.mark.asyncio
async def test_translate_restores_protected_terms():
    def fake(chunk: str) -> str:
        # Máy dịch trả về giữ chỗ nguyên vẹn, chỉ dịch phần văn xuôi.
        return chunk.replace("Call", "Gọi").replace("now", "ngay")

    out = await translate("Call updateButtons now.", fetch=fake)
    assert out == "Gọi updateButtons ngay."


@pytest.mark.asyncio
async def test_translate_keeps_english_for_one_bad_chunk():
    """Hỏng một đoạn thì chỉ mất đoạn đó, không mất cả tài liệu.

    Với tài liệu dài, bỏ toàn bộ bản dịch vì một câu là quá đắt.
    """
    def fake(chunk: str) -> str:
        if "updateButtons" in chunk or "zq" in chunk:
            return "Bản dịch đã làm mất giữ chỗ."
        return "Câu thứ hai."

    out = await translate("Call updateButtons now. Second one here.", fetch=fake, limit=25)
    assert "Call updateButtons now." in out
    assert "Câu thứ hai." in out


@pytest.mark.asyncio
async def test_translate_fails_when_every_chunk_is_bad():
    """Trả về y hệt đầu vào kèm 200 làm người dùng tưởng nút không chạy."""
    def fake(chunk: str) -> str:
        return "Bản dịch đã làm mất giữ chỗ."

    with pytest.raises(TranslateError):
        await translate("Call updateButtons now.", fetch=fake)


@pytest.mark.asyncio
async def test_translate_retries_a_chunk_once():
    calls: list[str] = []

    def fake(chunk: str) -> str:
        calls.append(chunk)
        if len(calls) == 1:
            raise OSError("hỏng thoáng qua")
        return "Đã dịch."

    assert await translate("Hello there.", fetch=fake) == "Đã dịch."
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_translate_stops_immediately_when_quota_is_gone():
    """Hết hạn mức thì các đoạn sau chắc chắn cũng hỏng: dừng ngay, đừng đốt thêm."""
    calls: list[str] = []

    def fake(chunk: str) -> str:
        calls.append(chunk)
        raise QuotaExhausted("hết hạn mức")

    text = " ".join(f"Sentence {i} here." for i in range(10))
    with pytest.raises(QuotaExhausted):
        await translate(text, fetch=fake, limit=20)

    # Vài đoạn đầu đã bay rồi thì không thu lại được, nhưng phần còn lại phải
    # dừng — và không đoạn nào được thử lại.
    assert len(calls) <= _CONCURRENCY


@pytest.mark.asyncio
async def test_translate_empty_text_returns_empty():
    def fake(chunk: str) -> str:  # pragma: no cover - không được gọi
        raise AssertionError("không được gọi ra ngoài với text rỗng")

    assert await translate("   ", fetch=fake) == ""


@pytest.mark.asyncio
async def test_translate_wraps_provider_failure():
    def fake(chunk: str) -> str:
        raise OSError("mạng hỏng")

    with pytest.raises(TranslateError):
        await translate("Hello there.", fetch=fake)


# --- Cache: dán lại đoạn cũ thì không được tốn hạn mức ---

@pytest.mark.asyncio
async def test_second_translation_uses_the_cache(tmp_path):
    calls: list[str] = []

    def fake(chunk: str) -> str:
        calls.append(chunk)
        return "Đã dịch."

    first = await translate("Hello there.", fetch=fake, cache_dir=tmp_path)
    second = await translate("Hello there.", fetch=fake, cache_dir=tmp_path)

    assert first == second == "Đã dịch."
    assert len(calls) == 1, "lần dán thứ hai không được gọi ra ngoài"


@pytest.mark.asyncio
async def test_cache_is_per_chunk_not_per_document(tmp_path):
    """Sửa một câu rồi dán lại: chỉ câu đã sửa mới tốn hạn mức."""
    calls: list[str] = []

    def fake(chunk: str) -> str:
        calls.append(chunk)
        return "VI:" + chunk

    await translate("One here. Two here.", fetch=fake, limit=12, cache_dir=tmp_path)
    assert len(calls) == 2

    calls.clear()
    await translate("One here. Three here.", fetch=fake, limit=14, cache_dir=tmp_path)
    assert calls == ["Three here."], "chỉ câu mới được gọi ra ngoài"


@pytest.mark.asyncio
async def test_a_failed_chunk_is_not_cached(tmp_path):
    """Cache đoạn hỏng thì lần sau vẫn hỏng mà không còn cơ hội gọi lại."""
    attempts: list[str] = []

    def broken(chunk: str) -> str:
        attempts.append(chunk)
        raise OSError("mạng hỏng")

    with pytest.raises(TranslateError):
        await translate("Hello there.", fetch=broken, cache_dir=tmp_path)
    assert list(tmp_path.glob("*.txt")) == []

    def working(chunk: str) -> str:
        return "Đã dịch."

    assert await translate("Hello there.", fetch=working, cache_dir=tmp_path) == "Đã dịch."


@pytest.mark.asyncio
async def test_cache_is_optional(tmp_path):
    """Không truyền cache_dir thì không được ghi gì ra đĩa."""
    def fake(chunk: str) -> str:
        return "Đã dịch."

    await translate("Hello there.", fetch=fake)
    assert list(tmp_path.iterdir()) == []


# --- Dấu Markdown đầu đoạn ---

@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["## ", "# ", "- ", "* ", "> ", "1. "])
async def test_leading_markdown_is_not_sent_to_the_translator(prefix):
    """Chuỗi bắt đầu bằng '##' khiến MyMemory trả về nguyên văn, không dịch.

    Đo được trên dịch vụ thật. Tài liệu thiết kế đầy tiêu đề và gạch đầu dòng
    nên phải tách dấu ra trước khi gửi, rồi gắn lại vào bản dịch.
    """
    sent: list[str] = []

    def fake(chunk: str) -> str:
        sent.append(chunk)
        return "Kiến trúc ở đây."

    out = await translate(prefix + "Architecture here.", fetch=fake)

    assert sent == ["Architecture here."], "dấu Markdown không được gửi đi"
    assert out == prefix + "Kiến trúc ở đây.", "dấu Markdown phải được gắn lại"


@pytest.mark.asyncio
@pytest.mark.parametrize("markup", ["2.", "##", "-", "1)"])
async def test_a_chunk_of_only_markup_is_left_alone(markup):
    """Số thứ tự bị tách rời như '2.' thì không có gì để dịch, đừng tốn hạn mức."""
    sent: list[str] = []

    def fake(chunk: str) -> str:
        sent.append(chunk)
        return "khong nen goi"

    assert await translate(markup, fetch=fake) == markup
    assert sent == [], "không được gọi ra ngoài khi đoạn chỉ có dấu Markdown"


@pytest.mark.asyncio
async def test_cache_ignores_the_leading_marker(tmp_path):
    """Cùng một câu ở tiêu đề và trong văn xuôi thì dùng chung cache."""
    calls: list[str] = []

    def fake(chunk: str) -> str:
        calls.append(chunk)
        return "Kiến trúc ở đây."

    await translate("Architecture here.", fetch=fake, cache_dir=tmp_path)
    out = await translate("## Architecture here.", fetch=fake, cache_dir=tmp_path)

    assert len(calls) == 1
    assert out == "## Kiến trúc ở đây."
