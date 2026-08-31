"""Chuẩn hoá văn bản trước khi đưa vào TTS.

Chuỗi xử lý này bê nguyên từ bản Django gốc, kể cả những chi tiết trông lạ,
vì nó quyết định app ngắt câu nghe có tự nhiên không. Đừng "sửa cho gọn"
mà không cập nhật golden test trong tests/test_text.py.
"""
from __future__ import annotations

import re

# Chú ý: regex có NHÓM BẮT `(\ )`, nên re.split chèn cả nhóm bắt vào kết quả,
# và trả None ở những chỗ khớp nhánh `-`. Bộ lọc bên dưới phải xử lý None.
_SPLIT = re.compile(r"\.(\ )|\-")


def normalize(text: str) -> str:
    text = re.sub(r"\.", ". ", text)
    text = re.sub(r"\.\ \ ", ". ", text)
    text = re.sub(r"\.\ +\"", '. "', text)
    text = re.sub(r"\ \, ", ", ", text)
    audio_text = re.sub(r"\"", "", text)
    rows = [
        r
        for r in _SPLIT.split(audio_text.strip())
        if r is not None and r.strip() != ""
    ]
    return ". ".join(rows).strip()
