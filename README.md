# Tự động đọc

Ứng dụng đọc văn bản tiếng Việt thành giọng nói. Dán văn bản hoặc tải lên file `.txt`, app cắt
thành từng dòng, đọc lần lượt và cho phép tạm dừng, nhảy câu, xoá hàng đợi.

Bản chạy thật: https://langnghe.hipingu.health

## Chạy

```bash
cp .env.example .env
./deploy.sh
```

Mặc định phục vụ tại `http://127.0.0.1:8010`. Đổi cổng bằng `APP_PORT` trong `.env`.

## Tổng quan

Một service FastAPI vừa phục vụ file tĩnh vừa lo API. Text đi vào được lọc cú pháp Markdown và
chuẩn hoá câu, tra cache MP3 trên đĩa, nếu trượt thì gọi TTS rồi trả về MP3 dạng base64. Hàng đợi
nằm ở phía trình duyệt trong `localStorage` — **server không lưu trạng thái gì**, không database,
không session.

```
app/
├── main.py      khởi tạo FastAPI, khai báo route, kiểm tra đầu vào
├── config.py    đọc cấu hình từ biến môi trường
├── text.py      lọc Markdown, chuẩn hoá câu, viết lại đường dẫn cho dễ đọc
├── tts.py       chuỗi nhà cung cấp TTS, retry, single-flight
├── breaker.py   cầu dao và ngân sách gọi gTTS
├── cache.py     cache MP3 trên đĩa
└── limits.py    rate limit theo IP
static/          HTML, CSS, JS thuần — không build step, không node_modules
docs/            tài liệu chi tiết, xem bên dưới
```

Không database, không ffmpeg (dùng sox nhẹ hơn ~440MB), không build step cho frontend.

## Tài liệu

| File | Nội dung |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Luồng một request, chuỗi nhà cung cấp TTS, cache hai tầng, cầu dao, single-flight |
| [docs/text-processing.md](docs/text-processing.md) | Ba tầng xử lý văn bản và ranh giới của từng tầng, kèm số đo |
| [docs/frontend.md](docs/frontend.md) | Hàng đợi phía client, xử lý lỗi, nút xuống dòng, các ràng buộc phải giữ |
| [docs/api.md](docs/api.md) | Endpoint và mã lỗi |
| [docs/configuration.md](docs/configuration.md) | Biến môi trường |
| [docs/development.md](docs/development.md) | Chạy local, chạy test, quy ước code, cách đổi nhà cung cấp TTS |
| [docs/operations.md](docs/operations.md) | Triển khai, và bốn cạm bẫy đã từng làm hỏng production |

**Nếu bạn chuẩn bị sửa code:** đọc [docs/development.md](docs/development.md) và
[docs/operations.md](docs/operations.md) trước. Cả hai chứa những ràng buộc không suy ra được từ
việc đọc code, và mỗi ràng buộc đều đến từ một sự cố thật.
