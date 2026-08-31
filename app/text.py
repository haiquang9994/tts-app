"""Chuẩn hoá văn bản trước khi đưa vào TTS.

Mục tiêu duy nhất: cắt văn bản thành từng câu để TTS ngắt nghỉ đúng chỗ.
Kết quả của hàm này KHÔNG hiển thị cho người dùng — giao diện luôn giữ text gốc.

Hai quy tắc, và cả hai đều hẹp có chủ đích:

* Dấu chấm chỉ kết câu khi theo sau là khoảng trắng hoặc hết chuỗi.
* Dấu gạch ngang chỉ ngắt câu khi đứng riêng giữa hai khoảng trắng.

Nới rộng bất kỳ quy tắc nào cũng phá đường dẫn file, URL, số phiên bản và số
tiền — chẳng hạn thêm khoảng trắng sau mọi dấu chấm sẽ biến
".claude/features/client-surface.md" thành "claude/features/client. surface. md"
và "3.12.4" thành "3. 12. 4". Golden test trong tests/test_text.py khoá cả hai
hướng: câu bình thường phải tách đúng, còn những chuỗi trên phải nguyên vẹn.
"""
from __future__ import annotations

import re

_SENTENCE_BREAK = re.compile(r"(?<=\.)\s+|\s+[-–—]\s+")
_CLOSING_PUNCT = (".", "!", "?", ":", ";", ",")

# Cụm trông như đường dẫn hoặc tên file: không có khoảng trắng, và chứa dấu gạch
# chéo hoặc một dấu chấm đứng ngay trước chữ cái. Điều kiện "chữ cái" giữ cho số
# phiên bản và số tiền (3.12.4, 1.500.000) không bị đụng tới.
_PATH_LIKE = re.compile(r"\S*(?:[/\\]\S*|\.[A-Za-z]\S*)")
_PATH_SEPARATORS = re.compile(r"[/\\_\-:]+")
_TRAILING_PUNCT = ".,;:!?"


def normalize(text: str) -> str:
    text = text.replace('"', "")
    text = re.sub(r"\s+", " ", text).strip()
    # Bỏ khoảng trắng thừa trước dấu câu: "Giá 5 , 5" -> "Giá 5, 5"
    text = re.sub(r"\s+([,;:])", r"\1", text)

    parts = [p.strip() for p in _SENTENCE_BREAK.split(text) if p and p.strip()]
    # Mỗi mảnh kết thúc bằng dấu câu để TTS ngắt nghỉ giữa các mảnh.
    return " ".join(p if p.endswith(_CLOSING_PUNCT) else p + "." for p in parts)


def speak_paths(text: str) -> str:
    """Viết lại đường dẫn và tên file cho gTTS đọc được.

    gTTS đánh vần từng chữ cái khi gặp dấu chấm đứng trước chữ, đo được bằng
    thời lượng audio:

        ".claude/features/client-surface.md"           -> 9.31 giây
        "chấm claude features client surface chấm md"  -> 4.01 giây
        "config.py"                                    -> 3.26 giây
        "config chấm py"                               -> 1.54 giây

    Chỉ dùng cho gTTS. edge-tts đọc đường dẫn vốn đã ổn nên không cần bước này.
    """

    def rewrite(match: re.Match[str]) -> str:
        token = match.group(0)

        # Dấu câu ở cuối cụm là dấu kết câu chứ không thuộc đường dẫn. Không
        # tách ra thì "config.py." đọc thành "config chấm py chấm".
        trailing = ""
        while token and token[-1] in _TRAILING_PUNCT:
            trailing = token[-1] + trailing
            token = token[:-1]
        if not token:
            return match.group(0)

        token = _PATH_SEPARATORS.sub(" ", token)
        token = token.replace(".", " chấm ")
        return re.sub(r"\s+", " ", token).strip() + trailing

    return re.sub(r"\s+", " ", _PATH_LIKE.sub(rewrite, text)).strip()
