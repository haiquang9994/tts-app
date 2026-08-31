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

# --- Cú pháp Markdown ---
# Đo bằng thời lượng audio thì gTTS phát âm thành lời các ký tự * _ ~ > < = @
# & % $ ^, và người dùng nghe thấy # đọc là "thăng", * là "sao", ` là "huyền".
#
# Chỉ bỏ những gì THUẦN TUÝ là cú pháp. Các ký tự như % $ = @ vẫn giữ nguyên vì
# chúng là nội dung: "30%" phải đọc là "ba mươi phần trăm", "a = b" là "a bằng
# b". Bỏ chúng đi mới là làm hỏng.
_MD_FENCE = re.compile(r"^\s{0,3}(?:```|~~~).*$", re.MULTILINE)
# Dòng chỉ gồm ký tự kẻ: gạch ngang phân cách, tiêu đề kiểu gạch chân, hàng
# ngăn cách của bảng, và front matter.
_MD_RULE = re.compile(r"^\s{0,3}[-=*_|:\s]{3,}$", re.MULTILINE)
_MD_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_MD_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>\s]+)>")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*\S+.*$", re.MULTILINE)
_MD_FOOTNOTE = re.compile(r"\[\^[^\]]*\]")
_MD_REF_LINK = re.compile(r"\[([^\]]*)\]\[[^\]]*\]")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_HEADING_TAIL = re.compile(r"\s+#+\s*$", re.MULTILINE)
_MD_QUOTE = re.compile(r"^\s{0,3}(?:>\s?)+", re.MULTILINE)
_MD_BULLET = re.compile(r"^\s{0,3}[-*+]\s+", re.MULTILINE)
_MD_ORDERED = re.compile(r"^\s{0,3}\d{1,3}[.)]\s+", re.MULTILINE)
_MD_TASK = re.compile(r"^\s{0,3}\[[ xX]\]\s*", re.MULTILINE)
_MD_MARKS = re.compile(r"[*`~|]+")
# Gạch dưới chỉ là cú pháp khi đứng ở đầu hoặc cuối từ. Trong Ha_Noi hay
# snake_case thì nó thuộc về định danh, xoá đi sẽ dính chữ vào nhau.
_MD_UNDERSCORE = re.compile(r"(?<![^\W_])_+|_+(?![^\W_])")


def strip_markdown(text: str) -> str:
    """Bỏ ký tự cú pháp Markdown để chúng không bị đọc thành lời.

    Chạy trước khi gộp khoảng trắng, vì các quy tắc đầu dòng (tiêu đề, trích
    dẫn, gạch đầu dòng) cần cấu trúc dòng còn nguyên.
    """
    text = _MD_FENCE.sub(" ", text)
    text = _MD_RULE.sub(" ", text)
    text = _MD_REF_DEF.sub(" ", text)

    # Autolink trước khi bỏ thẻ HTML, nếu không <https://...> bị xoá cả URL.
    text = _MD_AUTOLINK.sub(r"\1", text)
    text = _MD_HTML_TAG.sub(" ", text)

    text = _MD_FOOTNOTE.sub(" ", text)
    text = _MD_IMAGE.sub(r"\1", text)
    # Giữ phần chữ của liên kết, bỏ URL: đọc URL lên rất khó nghe.
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_REF_LINK.sub(r"\1", text)

    text = _MD_HEADING.sub("", text)
    text = _MD_HEADING_TAIL.sub("", text)
    text = _MD_QUOTE.sub("", text)
    text = _MD_BULLET.sub("", text)
    text = _MD_ORDERED.sub("", text)
    text = _MD_TASK.sub("", text)

    text = _MD_UNDERSCORE.sub(" ", text)
    return _MD_MARKS.sub(" ", text)


def normalize(text: str) -> str:
    text = strip_markdown(text)
    text = text.replace('"', "")
    text = re.sub(r"\s+", " ", text).strip()
    # Bỏ khoảng trắng thừa trước dấu câu. Cần thiết sau khi lọc Markdown:
    # "và `mã`." thành "và mã ." nếu không dọn.
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)

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
