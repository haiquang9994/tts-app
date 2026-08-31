import pytest

from app.text import normalize

# Câu bình thường vẫn phải tách đúng như bản Django gốc.
TACH_CAU_DUNG = [
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

# Những trường hợp bản Django gốc PHÁ HỎNG. Đây là lý do tồn tại của bản viết lại.
KHONG_DUOC_PHA = [
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


@pytest.mark.parametrize("raw,expected", TACH_CAU_DUNG)
def test_van_tach_cau_binh_thuong_dung(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw,expected", KHONG_DUOC_PHA)
def test_khong_pha_duong_dan_url_va_so(raw, expected):
    assert normalize(raw) == expected


def test_gach_ngang_dung_rieng_moi_ngat_cau():
    assert normalize("Hà Nội — Sài Gòn") == "Hà Nội. Sài Gòn."
    assert normalize("Hà Nội – Sài Gòn") == "Hà Nội. Sài Gòn."
    # Gạch ngang dính liền chữ thì KHÔNG ngắt.
    assert normalize("a-b") == "a-b."


def test_gop_khoang_trang_va_xuong_dong():
    assert normalize("Câu một.\n\n   Câu hai.") == "Câu một. Câu hai."


def test_luon_tra_ve_str():
    assert isinstance(normalize(""), str)
