# Xử lý văn bản

Ba tầng, chạy theo thứ tự này. Tầng nào cũng có ranh giới hẹp có chủ đích, và mỗi ranh giới đều
được golden test khoá lại theo **cả hai hướng**: thứ phải đổi, và thứ phải giữ nguyên.

```
strip_markdown  →  normalize  →  (chỉ gTTS) speak_paths
   bỏ cú pháp       cắt câu          đọc đường dẫn
```

Kết quả của cả ba tầng **không bao giờ hiển thị cho người dùng** — giao diện luôn giữ text gốc.
Đây là lý do có thể biến đổi văn bản khá mạnh tay mà không ảnh hưởng trải nghiệm đọc trên màn hình.

## 1. `strip_markdown` — bỏ cú pháp Markdown

Người dùng thường dán tài liệu Markdown vào. Không lọc thì TTS đọc luôn ký tự cú pháp: `#` thành
"thăng", `*` thành "sao", `` ` `` thành "huyền".

Xử lý: tiêu đề (cả `#` lẫn kiểu gạch chân `===`, cả đuôi `## Tiêu đề ##`), gạch đầu dòng, danh
sách đánh số, ô đánh dấu việc `- [x]`, trích dẫn `>` kể cả lồng nhau, khối code ` ``` ` và `~~~`,
đường kẻ ngang, bảng, in đậm/nghiêng/gạch, liên kết (giữ chữ bỏ URL), liên kết tham chiếu và định
nghĩa của nó, ảnh, chú thích cuối trang, thẻ HTML, autolink.

**Ranh giới — đừng mở rộng bộ lọc này.** Đo bằng thời lượng audio thì gTTS còn phát âm cả
`% $ = @ & ^ < >`, nhưng chúng là **nội dung chứ không phải cú pháp**: "30%" phải đọc thành "ba
mươi phần trăm", "a = b" thành "a bằng b". Bỏ chúng đi mới là làm hỏng.

Gạch dưới chỉ bị bỏ khi đứng ở đầu hoặc cuối từ (`_nghiêng_`). Trong `snake_case_name` hay `Ha_Noi`
nó thuộc về định danh — xoá đi sẽ dính chữ vào nhau.

## 2. `normalize` — cắt câu

Hai quy tắc, cả hai đều hẹp có chủ đích:

- Dấu chấm chỉ kết câu khi **theo sau là khoảng trắng hoặc hết chuỗi**.
- Dấu gạch ngang chỉ ngắt câu khi **đứng riêng giữa hai khoảng trắng**.

Nới rộng bất kỳ quy tắc nào cũng phá đường dẫn file, URL, số phiên bản và số tiền. Chẳng hạn thêm
khoảng trắng sau *mọi* dấu chấm sẽ biến `.claude/features/client-surface.md` thành
`claude/features/client. surface. md` và `3.12.4` thành `3. 12. 4`.

Mỗi mảnh cắt ra được đảm bảo kết thúc bằng dấu câu để TTS ngắt nghỉ đúng chỗ.

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
