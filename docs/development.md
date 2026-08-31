# Phát triển

## Chuẩn bị

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
sudo apt install sox libsox-fmt-mp3     # cần cho việc tăng tốc gTTS
.venv/bin/uvicorn app.main:app --reload --port 8010
```

Thiếu `sox` thì app vẫn chạy nhưng mọi lời gọi gTTS đều hỏng và rơi sang edge-tts, còn hai
integration test liên quan tự bỏ qua.

## Test

```bash
.venv/bin/python -m pytest                              # toàn bộ, chạy offline
.venv/bin/python -m pytest tests/test_text.py           # một file
.venv/bin/python -m pytest tests/test_text.py::test_strips_markdown_syntax   # một test
.venv/bin/python -m pytest -k markdown                  # lọc theo tên
.venv/bin/python -m pytest -m integration               # đánh thật ra mạng
```

`pytest.ini` đặt `addopts = -m "not integration"`, nên test đánh ra mạng mặc định bị loại. Toàn bộ
test còn lại chạy được offline.

**Nên chạy bộ integration trước mỗi lần deploy.** Cả gTTS lẫn edge-tts đều dùng endpoint không
chính thức, và test mock không bao giờ phát hiện được khi nhà cung cấp đổi giao thức hoặc chặn
server — đó lại đúng là kiểu hỏng đáng lo nhất.

Không có linter hay formatter nào được cấu hình. Kiểm tra cú pháp thủ công:
`node --check static/app.js` và `bash -n deploy.sh`.

## Quy ước code

- **Định danh bằng tiếng Anh**, kể cả tên hàm test.
- **Chú thích bằng tiếng Việt có dấu.**
- Chú thích nên nói *tại sao*, nhất là ở những chỗ code trông lạ. Phần lớn chỗ lạ trong repo này
  đều đến từ một sự cố thật, và chú thích là thứ ngăn người sau "sửa cho gọn" rồi làm hỏng lại.
- Commit theo dạng `<type>(<scope>): <message>` bằng tiếng Anh, thể mệnh lệnh.

## Đổi nhà cung cấp TTS

`app/tts.py` phơi ra kiểu `Provider = Callable[[str], Awaitable[bytes]]`. `Synthesizer` nhận
`primary` và `fallback` qua constructor, nên thay nhà cung cấp là viết một coroutine mới rồi truyền
vào — không phải mổ lại phần còn lại của app. Test tận dụng đúng chỗ này để chạy offline.

Nếu muốn cắt hẳn phụ thuộc mạng thì Piper chạy offline là hướng đi, đổi lại image nặng hơn nhiều
và chất lượng giọng tiếng Việt thấp hơn.

Khi đổi cách sinh audio, **nhớ đổi luôn `GTTS_VARIANT` / `EDGE_VARIANT`** trong `tts.py`. Hai hằng
số đó là thành phần của khoá cache; không đổi thì audio cũ bị dùng nhầm.

## Sửa phần xử lý văn bản

`app/text.py` có golden test khoá hành vi theo **cả hai hướng**: thứ phải đổi, và thứ phải giữ
nguyên. Trước khi nới rộng bất kỳ quy tắc nào, đọc [text-processing.md](text-processing.md) —
mỗi ranh giới hẹp ở đó đều có lý do, và test sẽ chặn lại nếu vượt qua.

Đừng đoán TTS đọc thế nào. Đo bằng thời lượng audio: đánh vần thì dài hơn hẳn đọc bình thường.
Xem đoạn script đo ở cuối [text-processing.md](text-processing.md).

## Test nào tốn tiền

```bash
pytest                  # 206 test offline — miễn phí, chạy thoải mái
pytest -m integration   # gTTS + edge-tts thật — miễn phí, chạy trước mỗi lần deploy
pytest -m paid          # Gemini thật — TỐN TIỀN, chỉ khi cần kiểm chứng nhà cung cấp
```

Mặc định `pytest.ini` loại cả hai marker mạng, nên chạy test bao nhiêu lần cũng không mất gì.

`paid` tách riêng khỏi `integration` vì hạn mức Gemini tính theo **request mỗi ngày**: gộp chung
thì mỗi lần deploy lại đốt một phần hạn mức, và ở gói free chỉ vài lần deploy là hết.

File `tests/test_translate_integration.py` cố ý chỉ có **hai** lời gọi — một lần dịch kiểm tra
mọi tính chất cùng lúc, một lần hỏng kiểm tra đường báo lỗi. Tách thành các test nhỏ dễ đọc hơn
sẽ làm mỗi lần chạy tốn gấp đôi.

Chạy `-m paid` khi: đổi key, đổi model, sửa prompt, hoặc nghi Gemini đã đổi hình dạng phản hồi.
