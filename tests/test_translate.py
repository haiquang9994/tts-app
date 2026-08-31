"""Golden test cho lớp dịch.

Khoá hành vi theo CẢ HAI hướng, giống test_text.py: cái gì phải được bọc để
khỏi bị dịch, và cái gì phải để yên cho máy dịch xử lý. Bọc quá tay làm văn
xuôi tiếng Việt lổn nhổn chữ Anh, bọc thiếu làm hỏng định danh.
"""
from __future__ import annotations

import pytest

from app.translate import (
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
    assert seen == ["One here.", "Two here."]
    assert out == "Một. Hai."


@pytest.mark.asyncio
async def test_translate_restores_protected_terms():
    def fake(chunk: str) -> str:
        # Máy dịch trả về giữ chỗ nguyên vẹn, chỉ dịch phần văn xuôi.
        return chunk.replace("Call", "Gọi").replace("now", "ngay")

    out = await translate("Call updateButtons now.", fetch=fake)
    assert out == "Gọi updateButtons ngay."


@pytest.mark.asyncio
async def test_translate_falls_back_when_placeholder_is_lost():
    """Máy dịch nuốt giữ chỗ thì thà giữ nguyên tiếng Anh còn hơn trả ra rác."""
    def fake(chunk: str) -> str:
        return "Bản dịch đã làm mất giữ chỗ."

    out = await translate("Call updateButtons now.", fetch=fake)
    assert out == "Call updateButtons now."


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
