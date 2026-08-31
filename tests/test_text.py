import pytest

from app.text import normalize

# Cặp (đầu vào, đầu ra) lấy từ việc chạy thật logic của bản Django gốc.
GOLDEN = [
    ("Xin chào. Tôi tên là Nam.", "Xin chào. Tôi tên là Nam."),
    ("Hà Nội - Sài Gòn", "Hà Nội .  Sài Gòn"),
    ('Anh nói: "Chào em."', "Anh nói: Chào em."),
    ("Một câu không dấu chấm", "Một câu không dấu chấm"),
    ("A.B.C", "A. B. C"),
    ("Nhiều...  chấm", "Nhiều.  chấm"),
    ("", ""),
    ("   ", ""),
    ("Câu một. Câu hai. Câu ba.", "Câu một. Câu hai. Câu ba."),
    ("Ừ.", "Ừ."),
    ("Giá 5 , 5 triệu", "Giá 5, 5 triệu"),
]


@pytest.mark.parametrize("raw,expected", GOLDEN)
def test_normalize_khop_hanh_vi_ban_django(raw, expected):
    assert normalize(raw) == expected


def test_normalize_khong_lam_hong_khi_gap_dau_gach_noi_lien_tiep():
    # Nhánh `-` của regex tách câu trả None trong kết quả re.split;
    # bộ lọc bắt buộc phải xử lý None, bỏ đi là vỡ ngay.
    assert normalize("a--b") == "a. b"


def test_normalize_luon_tra_ve_str():
    assert isinstance(normalize(""), str)
