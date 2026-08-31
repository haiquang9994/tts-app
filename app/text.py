"""Chuẩn hoá văn bản trước khi đưa vào TTS.

Mục tiêu duy nhất: cắt văn bản thành từng câu để TTS ngắt nghỉ đúng chỗ.
Kết quả của hàm này KHÔNG hiển thị cho người dùng — giao diện luôn giữ text gốc.

Hai quy tắc, và cả hai đều hẹp có chủ đích:

* Dấu chấm chỉ kết câu khi theo sau là khoảng trắng hoặc hết chuỗi.
* Dấu gạch ngang chỉ ngắt câu khi đứng riêng giữa hai khoảng trắng.
* "d/m" đứng một mình chỉ được đọc thành ngày tháng khi có từ chỉ ngày đứng
  trước hoặc có đủ năm bốn chữ số; riêng khoảng "d/m - d/m" thì bản thân cấu
  trúc đã đủ.

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

# --- Ngày tháng ---
# "ngày 20/7" bị đọc thành "ngày 20 7": speak_paths coi dấu / là dải phân cách
# đường dẫn. Viết lại ngay ở đây, tức là trước cả hai giọng, nên edge-tts cũng
# đọc đúng và cache key — vốn tính trên text đã normalize — tự đổi theo mà
# không phải bump GTTS_VARIANT/EDGE_VARIANT.
#
# Hẹp có chủ đích: chỉ nhận dạng khi có từ chỉ ngày đứng trước, hoặc khi có đủ
# năm bốn chữ số. Bắt mọi "d/m" sẽ đọc sai phân số — "1/2 số học sinh" thành
# "1 tháng 2 số học sinh" — vì tiếng Việt dùng chung dấu / cho cả hai.
_DATE_CUED = re.compile(
    r"\b(ngày|mùng|mồng)\s+(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?![\d/])",
    re.IGNORECASE,
)
# Không có từ chỉ ngày thì phải có năm mới đủ rõ. Lookbehind chặn đoạn giữa của
# một URL: trong ".org/20/7/2025" thì "20/7" chỉ là hai đoạn đường dẫn.
_DATE_WITH_YEAR = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])")

# Khoảng ngày "7/1 - 5/2/2027", "20/7 - 25/7". Ở đây bản thân cấu trúc
# "d/m - d/m" là bằng chứng, không cần năm lẫn từ khoá: hai cụm ngày/tháng nối
# nhau bằng gạch ngang hầu như luôn là một khoảng thời gian.
#
# Cái giá đã cân nhắc và chấp nhận: "1/2 - 3/4" cũng bị đọc thành ngày tháng.
# Không có cách nào phân biệt nó với một khoảng ngày, mà phân số đứng một mình
# — ca thường gặp hơn nhiều — thì vẫn nguyên vẹn vì không có gạch ngang.
#
# Phải chạy TRƯỚC hai quy tắc trên, nếu không _DATE_WITH_YEAR nuốt mất vế phải
# và chỉ còn lại một nửa khoảng.
_DATE_RANGE = re.compile(
    r"(?:(ngày|mùng|mồng)\s+)?(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{4}))?"
    r"\s*[-–—]\s*(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?![\d/])",
    re.IGNORECASE,
)


def _spoken_date(day: str, month: str, year: str | None) -> str | None:
    """Đọc "20/7" thành "20 tháng 7", hoặc None nếu không phải ngày tháng."""
    d, m = int(day), int(month)
    if not (1 <= d <= 31 and 1 <= m <= 12):
        return None
    # int() bỏ luôn số 0 đứng đầu: "05" bị đọc là "không năm" chứ không phải "năm".
    spoken = f"{d} tháng {m}"
    return f"{spoken} năm {year}" if year else spoken


def _rewrite_dates(text: str) -> str:
    def ranged(match: re.Match[str]) -> str:
        cue, day, month, year, day2, month2, year2 = match.groups()
        first = _spoken_date(day, month, year)
        second = _spoken_date(day2, month2, year2)
        if first is None or second is None:
            return match.group(0)
        # Dấu gạch phải thành chữ "đến": _SENTENCE_BREAK cắt câu ở gạch ngang
        # đứng riêng, để nguyên thì một khoảng bị đọc thành hai câu rời.
        # Giữ từ khoá người viết đã gõ, chỉ chèn "ngày" vào chỗ còn thiếu.
        return f"{cue or 'ngày'} {first} đến ngày {second}"

    def cued(match: re.Match[str]) -> str:
        spoken = _spoken_date(match.group(2), match.group(3), match.group(4))
        return match.group(0) if spoken is None else f"{match.group(1)} {spoken}"

    def with_year(match: re.Match[str]) -> str:
        spoken = _spoken_date(*match.groups())
        return match.group(0) if spoken is None else spoken

    text = _DATE_RANGE.sub(ranged, text)
    return _DATE_WITH_YEAR.sub(with_year, _DATE_CUED.sub(cued, text))


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
    text = _rewrite_dates(text)

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
