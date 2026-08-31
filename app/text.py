"""Chuẩn hoá văn bản trước khi đưa vào TTS.

Mục tiêu duy nhất: cắt văn bản thành từng câu để TTS ngắt nghỉ đúng chỗ.
Kết quả của hàm này KHÔNG hiển thị cho người dùng — giao diện luôn giữ text gốc.

Khác có chủ ý so với bản Django gốc: bản cũ thêm khoảng trắng sau MỌI dấu chấm
và coi MỌI dấu gạch ngang là hết câu, nên nó phá đường dẫn file, URL, số phiên
bản và số tiền:

    .claude/features/client-surface.md -> claude/features/client. surface. md
    Phiên bản 3.12.4                   -> Phiên bản 3. 12. 4
    Giá 1.500.000 đồng                 -> Giá 1. 500. 000 đồng

Quy tắc mới: dấu chấm chỉ kết câu khi theo sau là khoảng trắng hoặc hết chuỗi;
dấu gạch ngang chỉ ngắt câu khi đứng riêng giữa hai khoảng trắng.
"""
from __future__ import annotations

import re

_NGAT_CAU = re.compile(r"(?<=\.)\s+|\s+[-–—]\s+")
_DAU_KET_CAU = (".", "!", "?", ":", ";", ",")


def normalize(text: str) -> str:
    text = text.replace('"', "")
    text = re.sub(r"\s+", " ", text).strip()
    # Bỏ khoảng trắng thừa trước dấu câu: "Giá 5 , 5" -> "Giá 5, 5"
    text = re.sub(r"\s+([,;:])", r"\1", text)

    phan = [p.strip() for p in _NGAT_CAU.split(text) if p and p.strip()]
    # Mỗi mảnh kết thúc bằng dấu câu để TTS ngắt nghỉ giữa các mảnh.
    return " ".join(p if p.endswith(_DAU_KET_CAU) else p + "." for p in phan)
