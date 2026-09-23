# Xử lý văn bản

Ba tầng, chạy theo thứ tự này. Tầng nào cũng có ranh giới hẹp có chủ đích, và mỗi ranh giới đều
được golden test khoá lại theo **cả hai hướng**: thứ phải đổi, và thứ phải giữ nguyên.

```
strip_markdown  →       normalize        →  (chỉ gTTS) speak_paths
   bỏ cú pháp    cắt câu, ngày tháng, @        đọc đường dẫn
```

Kết quả của cả ba tầng **không bao giờ hiển thị cho người dùng** — giao diện luôn giữ text gốc.
Đây là lý do có thể biến đổi văn bản khá mạnh tay mà không ảnh hưởng trải nghiệm đọc trên màn hình.

## 1. `strip_markdown` — bỏ cú pháp Markdown

Người dùng thường dán tài liệu Markdown vào. Không lọc thì TTS đọc luôn ký tự cú pháp: `#` thành
"thăng", `*` thành "sao", `` ` `` thành "huyền".

Xử lý: tiêu đề (cả `#` lẫn kiểu gạch chân `===`, cả đuôi `## Tiêu đề ##`), gạch đầu dòng, danh
sách đánh số (chỉ phần thụt đầu dòng — số thì giữ, xem dưới), ô đánh dấu việc `- [x]`, trích dẫn `>` kể cả lồng nhau, khối code ` ``` ` và `~~~`,
đường kẻ ngang, bảng, in đậm/nghiêng/gạch, liên kết (giữ chữ bỏ URL), liên kết tham chiếu và định
nghĩa của nó, ảnh, chú thích cuối trang, thẻ HTML thật (danh sách cố định: `br`, `div`, `span`, `a`...), autolink.
Chỗ giữ chỗ như `<daemon exe>` không phải thẻ HTML: bỏ hai dấu `<>` nhưng **đọc** phần chữ bên trong.

**Ranh giới — đừng mở rộng bộ lọc này.** Đo bằng thời lượng audio thì gTTS còn phát âm cả
`% $ = @ & ^ < >`, nhưng chúng là **nội dung chứ không phải cú pháp**: "30%" phải đọc thành "ba
mươi phần trăm", "a = b" thành "a bằng b". Bỏ chúng đi mới là làm hỏng. `@` dính chữ có được
tách khoảng trắng ở tầng sau, nhưng cũng không bao giờ bị xoá.

Gạch dưới chỉ bị bỏ khi đứng ở đầu hoặc cuối từ (`_nghiêng_`). Trong `snake_case_name` hay `Ha_Noi`
nó thuộc về định danh — xoá đi sẽ dính chữ vào nhau.

### Danh sách đánh số giữ lại số

Chỉ phần thụt đầu dòng bị bỏ, `1.` thì không: người nghe cần biết đang ở mục mấy. `1)` được chuẩn
hoá thành `1.` vì `_SENTENCE_BREAK` chỉ ngắt nghỉ ở dấu chấm.

Mục danh sách hiếm khi kết thúc bằng dấu câu, mà `normalize` gộp xuống dòng thành khoảng trắng —
nên trước mỗi mục đánh số, câu trước đó được chấm dứt ngay ở tầng này, khi cấu trúc dòng còn
nguyên. Không làm vậy thì `1. nội dung` + `2. nội dung` thành *"nội dung hai"*. Chỉ áp cho danh
sách **đánh số**: ở gạch đầu dòng, hai mục dính nhau chỉ là hai câu đọc liền, không đổi nghĩa.

| Văn bản | Kết quả |
|---|---|
| `1. nội dung` / `2. nội dung` | `1. nội dung. 2. nội dung.` |
| `10) Mục mười` | `10. Mục mười.` |
| `Bước 1. Mở máy` | `Bước 1. Mở máy.` (giữa câu, không phải cú pháp) |

## 2. `normalize` — cắt câu, ngày tháng, dấu `@`

### Cắt câu

Hai quy tắc, cả hai đều hẹp có chủ đích:

- Dấu chấm chỉ kết câu khi **theo sau là khoảng trắng hoặc hết chuỗi**.
- Dấu gạch ngang chỉ ngắt câu khi **đứng riêng giữa hai khoảng trắng**.

Nới rộng bất kỳ quy tắc nào cũng phá đường dẫn file, URL, số phiên bản và số tiền. Chẳng hạn thêm
khoảng trắng sau *mọi* dấu chấm sẽ biến `.claude/features/client-surface.md` thành
`claude/features/client. surface. md` và `3.12.4` thành `3. 12. 4`.

Mỗi mảnh cắt ra được đảm bảo kết thúc bằng dấu câu để TTS ngắt nghỉ đúng chỗ.

### Ngày tháng

`ngày 20/7` bị đọc thành *"ngày 20 7"*: `speak_paths` coi dấu `/` là dải phân cách đường dẫn nên
thay nó bằng khoảng trắng. `normalize` viết lại thành `ngày 20 tháng 7` trước khi tới tầng đó.

Đặt ở `normalize` chứ không phải `speak_paths` vì hai lý do: edge-tts cũng được hưởng, và cache key
tính trên text đã `normalize` nên tự đổi theo — không phải bump `GTTS_VARIANT`/`EDGE_VARIANT`.

Quy tắc nhận dạng ba dạng:

| Dạng | Ví dụ | Kết quả |
|---|---|---|
| Có từ chỉ ngày (`ngày`, `mùng`, `mồng`) đứng trước | `ngày 20/7` | `ngày 20 tháng 7` |
| Có đủ năm bốn chữ số | `20/7/2025` | `20 tháng 7 năm 2025` |
| Khoảng `d/m - d/m` | `20/7 - 25/7` | `ngày 20 tháng 7 đến ngày 25 tháng 7` |
| Khoảng có năm ở một đầu | `7/1 - 5/2/2027` | `ngày 7 tháng 1 đến ngày 5 tháng 2 năm 2027` |

Số 0 đứng đầu bị bỏ (`ngày 05/07` → `ngày 5 tháng 7`) vì gTTS đọc `05` thành *"không năm"*. Ngày
ngoài 1–31 hoặc tháng ngoài 1–12 thì để nguyên.

Với **khoảng ngày**, bản thân cấu trúc `d/m - d/m` đã là bằng chứng: hai cụm ngày/tháng nối nhau
bằng gạch ngang hầu như luôn là một khoảng thời gian, nên không đòi hỏi năm lẫn từ khoá. Chữ "ngày"
được chèn vào đầu nào còn thiếu, còn từ khoá người viết đã gõ thì giữ nguyên (`mùng 7/1 - 5/2/2027`
→ `mùng 7 tháng 1 đến ngày 5 tháng 2 năm 2027`). Năm ở đầu nào thì đọc ở đầu đó.

Dấu gạch **phải** được đọc thành "đến" chứ không giữ lại: `_SENTENCE_BREAK` cắt câu ở gạch ngang
đứng riêng giữa hai khoảng trắng, để nguyên thì một khoảng thời gian bị đọc thành hai câu rời.

Cái giá đã cân nhắc và chấp nhận: `1/2 - 3/4` cũng bị đọc thành *"ngày 1 tháng 2 đến ngày 3 tháng
4"*. Không có cách nào phân biệt hai phân số nối bằng gạch ngang với một khoảng ngày.

Nhưng `d/m` **đứng một mình** thì vẫn không được nới rộng. Tiếng Việt dùng chung dấu `/` cho phân số
và tỷ số, nên `1/2 số học sinh` sẽ bị đọc thành *"1 tháng 2 số học sinh"* — đây mới là ca thường
gặp. Cũng vì vậy mà `Hôm nay 20/7 trời đẹp` **không** được viết lại: bỏ sót một ngày rẻ hơn nhiều
so với đọc sai một phân số.

### Dấu `@` dính chữ

gTTS đánh vần cả cụm khi `@` dính liền hai bên. Đo bằng thời lượng audio:

| Văn bản | Thời lượng |
|---|---|
| `mariadb@blog` | 4.49s |
| `mariadb @ blog` | 2.33s |

Xử lý: chèn khoảng trắng hai bên, **không bao giờ xoá** — `@` là nội dung. Và chỉ khi cả hai bên là
chữ hoặc số: `@username` hay `Giá @ 5` vốn không gây đánh vần nên để nguyên.

Đặt ở `normalize` cùng lý do như ngày tháng: edge-tts cũng được hưởng (đo được là nó không đọc `@`
nên cả hai dạng đều 1.97s — tách ra không hại gì), và cache key tự đổi theo.

## 3. `speak_paths` — đọc đường dẫn (chỉ gTTS)

gTTS đánh vần từng chữ cái khi gặp dấu chấm đứng trước chữ. Đo bằng thời lượng audio:

| Văn bản | Thời lượng |
|---|---|
| `.claude/features/client-surface.md` | 9.31s |
| `chấm claude features client surface chấm md` | 4.01s |
| `config.py` | 3.26s |
| `config chấm py` | 1.54s |

Trong các cụm trông như đường dẫn: `.` thành " chấm ", còn `/ \ _ - :` thành khoảng trắng.

Điều kiện nhận diện đòi hỏi **sau dấu chấm phải là chữ cái**, nên số phiên bản và số tiền
(`3.12.4`, `1.500.000`) không bị đụng tới. Dấu câu ở cuối cụm được tách ra trước khi biến đổi —
nếu không thì `config.py.` bị đọc thành "config chấm py chấm".

Bước này **chỉ áp cho gTTS**, gọi bên trong `gtts_provider`. edge-tts đọc đường dẫn vốn đã ổn.

## Đo lại khi nghi ngờ

Không đoán TTS đọc thế nào — đo bằng thời lượng audio, vì đánh vần thì dài hơn hẳn đọc bình thường:

```bash
docker exec langnghe python -c "
import sys, subprocess, tempfile, os
sys.path.insert(0, '/app')
from app.tts import _gtts_bytes

def dur(text):
    d = _gtts_bytes(text)
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
        f.write(d); p = f.name
    out = subprocess.run(['sox', '--i', '-D', p], capture_output=True, text=True)
    os.unlink(p)
    return float(out.stdout.strip())

for t in ['config.py', 'config chấm py']:
    print(f'{dur(t):5.2f}s  {t!r}')
"
```
