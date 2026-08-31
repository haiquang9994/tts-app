import pytest

from app.text import normalize, speak_paths

# Câu bình thường phải tách đúng ở dấu chấm.
ORDINARY_SENTENCES = [
    ("Xin chào. Tôi tên là Nam.", "Xin chào. Tôi tên là Nam."),
    ("Câu một. Câu hai. Câu ba.", "Câu một. Câu hai. Câu ba."),
    ("Ừ.", "Ừ."),
    ('Anh nói: "Chào em."', "Anh nói: Chào em."),
    ("Giá 5 , 5 triệu", "Giá 5, 5 triệu."),
    ("Hà Nội - Sài Gòn", "Hà Nội. Sài Gòn."),
    ("Một câu không dấu chấm", "Một câu không dấu chấm."),
    ("", ""),
    ("   ", ""),
]

# Những chuỗi mà quy tắc tách câu nới rộng sẽ phá hỏng. Phải nguyên vẹn.
MUST_NOT_MANGLE = [
    (".claude/features/client-surface.md", ".claude/features/client-surface.md."),
    ("Xem file config.py nhé.", "Xem file config.py nhé."),
    ("Truy cập https://vi.wikipedia.org/wiki/Ha_Noi",
     "Truy cập https://vi.wikipedia.org/wiki/Ha_Noi."),
    ("Phiên bản 3.12.4 ra rồi.", "Phiên bản 3.12.4 ra rồi."),
    ("Giá 1.500.000 đồng.", "Giá 1.500.000 đồng."),
    ("Hà Nội - Sài Gòn dài 1.700 km.", "Hà Nội. Sài Gòn dài 1.700 km."),
    ("A.B.C", "A.B.C."),
    ("client-surface", "client-surface."),
    ("máy chủ e-mail", "máy chủ e-mail."),
]


@pytest.mark.parametrize("raw,expected", ORDINARY_SENTENCES)
def test_still_splits_ordinary_sentences(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw,expected", MUST_NOT_MANGLE)
def test_does_not_mangle_paths_urls_or_numbers(raw, expected):
    assert normalize(raw) == expected


def test_only_standalone_dash_breaks_a_sentence():
    assert normalize("Hà Nội — Sài Gòn") == "Hà Nội. Sài Gòn."
    assert normalize("Hà Nội – Sài Gòn") == "Hà Nội. Sài Gòn."
    # Gạch ngang dính liền chữ thì KHÔNG ngắt.
    assert normalize("a-b") == "a-b."


def test_collapses_whitespace_and_newlines():
    assert normalize("Câu một.\n\n   Câu hai.") == "Câu một. Câu hai."


def test_always_returns_a_string():
    assert isinstance(normalize(""), str)


# ---- Ngày tháng: "ngày 20/7" phải đọc là "ngày 20 tháng 7" ----

# gTTS coi "20/7" là đường dẫn, speak_paths đổi dấu / thành khoảng trắng nên
# nghe ra "ngày 20 7". Viết lại ngay trong normalize để cả gTTS lẫn edge-tts
# cùng đọc đúng, và để cache key tự đổi theo mà không phải bump VARIANT.
DATES_TO_SPEAK = [
    ("ngày 20/7", "ngày 20 tháng 7."),
    ("Ngày 20/7 trời đẹp.", "Ngày 20 tháng 7 trời đẹp."),
    ("mùng 2/9", "mùng 2 tháng 9."),
    ("mồng 1/1", "mồng 1 tháng 1."),
    # Số 0 đứng đầu bị đọc thành "không năm", bỏ đi.
    ("ngày 05/07", "ngày 5 tháng 7."),
    ("ngày 20/7/2025", "ngày 20 tháng 7 năm 2025."),
    # Có đủ năm thì tự nó đã là ngày tháng, không cần từ khoá đứng trước.
    ("Hợp đồng ký 20/7/2025.", "Hợp đồng ký 20 tháng 7 năm 2025."),
    # Khoảng ngày: năm ở vế phải là bằng chứng cho cả hai đầu. Dấu gạch được
    # đọc thành "đến", nếu không _SENTENCE_BREAK sẽ cắt khoảng thành hai câu.
    ("7/1 - 5/2/2027", "ngày 7 tháng 1 đến ngày 5 tháng 2 năm 2027."),
    ("Nghỉ lễ 7/1-5/2/2027.", "Nghỉ lễ ngày 7 tháng 1 đến ngày 5 tháng 2 năm 2027."),
    ("20/7/2025 - 25/8/2026",
     "ngày 20 tháng 7 năm 2025 đến ngày 25 tháng 8 năm 2026."),
    # Từ khoá người viết đã gõ thì giữ nguyên, không chèn thêm "ngày" nữa.
    ("ngày 7/1 - 5/2/2027", "ngày 7 tháng 1 đến ngày 5 tháng 2 năm 2027."),
    ("mùng 7/1 – 5/2/2027", "mùng 7 tháng 1 đến ngày 5 tháng 2 năm 2027."),
    # Không đầu nào có năm vẫn là khoảng ngày: bản thân cấu trúc "d/m - d/m"
    # đã là bằng chứng. Cái giá phải trả nằm ngay dưới, ở DATES_TO_LEAVE_ALONE.
    ("20/7 - 25/7", "ngày 20 tháng 7 đến ngày 25 tháng 7."),
    ("Nghỉ từ 5/1 - 9/2.", "Nghỉ từ ngày 5 tháng 1 đến ngày 9 tháng 2."),
]

# Không có từ khoá chỉ ngày và cũng không có năm thì dấu / vẫn là dấu /:
# phân số, tỷ số và đường dẫn đều dùng chung ký tự này.
DATES_TO_LEAVE_ALONE = [
    ("1/2 số học sinh", "1/2 số học sinh."),
    ("Tỷ số 20/7", "Tỷ số 20/7."),
    ("Hôm nay 20/7 trời đẹp.", "Hôm nay 20/7 trời đẹp."),
    # Sai miền giá trị thì không phải ngày tháng.
    ("ngày 20/13", "ngày 20/13."),
    ("ngày 40/7", "ngày 40/7."),
    # Năm phải đủ 4 chữ số; "1/2/3" không rõ là gì nên để nguyên.
    ("ngày 1/2/3", "ngày 1/2/3."),
    # Trong URL, "20/7" chỉ là hai đoạn đường dẫn.
    ("Xem https://vi.wikipedia.org/20/7/2025",
     "Xem https://vi.wikipedia.org/20/7/2025."),
    ("a/b", "a/b."),
    # Sai miền giá trị ở một đầu thì bỏ cả cụm.
    ("7/1 - 40/2/2027", "7/1. 40/2/2027."),
    ("20/7 - 25/13", "20/7. 25/13."),
]


@pytest.mark.parametrize("raw,expected", DATES_TO_SPEAK)
def test_reads_day_slash_month_as_a_date(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw,expected", DATES_TO_LEAVE_ALONE)
def test_leaves_slashes_that_are_not_dates_alone(raw, expected):
    assert normalize(raw) == expected


def test_date_range_reads_a_fraction_pair_as_dates_by_design():
    # Cái giá đã chấp nhận của việc bỏ điều kiện "phải có năm": không có cách
    # nào phân biệt hai phân số nối bằng gạch ngang với một khoảng ngày.
    # Phân số đứng một mình thì vẫn nguyên vẹn — đó mới là ca thường gặp.
    assert normalize("1/2 - 3/4") == "ngày 1 tháng 2 đến ngày 3 tháng 4."
    assert normalize("1/2 số học sinh") == "1/2 số học sinh."


def test_date_range_takes_the_year_from_whichever_end_has_it():
    assert normalize("20/7/2025 - 25/7") == (
        "ngày 20 tháng 7 năm 2025 đến ngày 25 tháng 7."
    )


# ---- speak_paths: viết lại đường dẫn cho gTTS ----

# gTTS đánh vần từng chữ cái khi gặp dấu chấm đứng trước chữ. Đo bằng thời
# lượng audio: ".claude/features/client-surface.md" mất 9.31 giây, còn
# "chấm claude features client surface chấm md" chỉ 4.01 giây.
PATHS_TO_SPEAK = [
    (".claude/features/client-surface.md.", "chấm claude features client surface chấm md."),
    ("config.py.", "config chấm py."),
    ("Xem file config.py nhé.", "Xem file config chấm py nhé."),
    ("Mở app/main.py và sửa dòng 10.", "Mở app main chấm py và sửa dòng 10."),
]

# Những thứ KHÔNG được đụng tới: sau dấu chấm là số chứ không phải chữ.
LEAVE_ALONE = [
    "Phiên bản 3.12.4 ra rồi.",
    "Giá 1.500.000 đồng.",
    "Xin chào. Tôi tên Nam.",
    "client-surface.",
    "Ngày 20-11-2026.",
    "3.14.",
]


@pytest.mark.parametrize("raw,expected", PATHS_TO_SPEAK)
def test_speak_paths_rewrites_paths(raw, expected):
    assert speak_paths(raw) == expected


@pytest.mark.parametrize("raw", LEAVE_ALONE)
def test_speak_paths_leaves_ordinary_text_alone(raw):
    assert speak_paths(raw) == raw


def test_speak_paths_keeps_the_sentence_period():
    # Dấu chấm cuối câu không thuộc đường dẫn; nuốt nó vào thì "config.py."
    # bị đọc thành "config chấm py chấm".
    assert speak_paths("config.py.").endswith("py.")
    assert " chấm" not in speak_paths("config.py.")[-6:]


def test_speak_paths_handles_urls():
    assert speak_paths("Truy cập https://vi.wikipedia.org/wiki/Ha_Noi.") == (
        "Truy cập https vi chấm wikipedia chấm org wiki Ha Noi."
    )


def test_speak_paths_is_idempotent():
    once = speak_paths("config.py.")
    assert speak_paths(once) == once


# ---- strip_markdown: bỏ cú pháp, giữ nội dung ----

# gTTS đọc thành lời các ký tự cú pháp: # là "thăng", * là "sao", ` là "huyền".
MARKDOWN_TO_STRIP = [
    ("# T76 tự động hủy chia sẻ", "T76 tự động hủy chia sẻ."),
    ("## Mục tiêu", "Mục tiêu."),
    ("###### Tiêu đề mức sáu", "Tiêu đề mức sáu."),
    ("## Tiêu đề có đuôi ##", "Tiêu đề có đuôi."),
    ("Nhiệm vụ **T76** trong lộ trình", "Nhiệm vụ T76 trong lộ trình."),
    ("Chữ *nghiêng* và `mã` và ~~gạch~~", "Chữ nghiêng và mã và gạch."),
    ("* Mục thứ nhất", "Mục thứ nhất."),
    ("+ Mục dùng dấu cộng", "Mục dùng dấu cộng."),
    ("1. Mục có số", "Mục có số."),
    ("2) Mục dùng ngoặc", "Mục dùng ngoặc."),
    ("- [x] Việc đã xong", "Việc đã xong."),
    ("- [ ] Việc chưa xong", "Việc chưa xong."),
    ("> Trích dẫn", "Trích dẫn."),
    (">> Trích dẫn lồng nhau", "Trích dẫn lồng nhau."),
    ("| Cột A | Cột B |", "Cột A Cột B."),
    ("Xuống dòng<br>rồi tiếp", "Xuống dòng rồi tiếp."),
    ("Câu có chú thích[^1] ở đây", "Câu có chú thích ở đây."),
    ("Xem [tài liệu][ref] nhé", "Xem tài liệu nhé."),
    ("Xem [tài liệu ở đây](https://example.com/dai) nhé", "Xem tài liệu ở đây nhé."),
    ("![ảnh minh hoạ](https://example.com/a.png) ở dưới", "ảnh minh hoạ ở dưới."),
    ("Chữ _nghiêng_ thôi", "Chữ nghiêng thôi."),
]

# Dòng chỉ có cú pháp thì không còn gì để đọc.
MARKDOWN_LINES_THAT_VANISH = [
    "---",
    "***",
    "___",
    "|-------|-------|",
    "```python",
    "```",
    "~~~",
    "[ref]: https://example.com/rat/dai",
]

# Ký tự là NỘI DUNG chứ không phải cú pháp. gTTS đọc "30%" thành "ba mươi phần
# trăm" và "a = b" thành "a bằng b" — đó là đúng, bỏ đi mới là làm hỏng.
CONTENT_NOT_SYNTAX = [
    "Tăng 30% so với năm ngoái.",
    "Nếu a = b thì đúng.",
    "Giá $5 và 1.500.000 đồng.",
    "Gửi tới a@b.com nhé.",
    "Biến snake_case_name và Ha_Noi.",
    "Đường dẫn app/main.py không đổi.",
    "Phiên bản 3.12.4 ra rồi.",
]


@pytest.mark.parametrize("raw,expected", MARKDOWN_TO_STRIP)
def test_strips_markdown_syntax(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", MARKDOWN_LINES_THAT_VANISH)
def test_syntax_only_lines_become_empty(raw):
    assert normalize(raw) == ""


@pytest.mark.parametrize("raw", CONTENT_NOT_SYNTAX)
def test_keeps_characters_that_carry_meaning(raw):
    assert normalize(raw) == raw


def test_setext_heading_underline_is_dropped():
    assert normalize("Tiêu đề\n=======") == "Tiêu đề."


def test_autolink_keeps_the_url():
    assert normalize("Xem <https://example.com/tai-lieu> nhé.") == (
        "Xem https://example.com/tai-lieu nhé."
    )


def test_no_stray_space_before_punctuation():
    # Bỏ dấu ` để lại khoảng trắng thừa: "và `mã`." thành "và mã ."
    assert normalize("Chữ **đậm** và `mã`.") == "Chữ đậm và mã."


def test_strip_markdown_is_idempotent():
    once = normalize("## Mục tiêu **quan trọng**")
    assert normalize(once) == once
