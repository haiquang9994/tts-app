# Tự động đọc

Ứng dụng đọc văn bản tiếng Việt thành giọng nói. Dán văn bản hoặc tải lên file `.txt`, app cắt
thành từng câu, đọc lần lượt và cho phép tạm dừng, nhảy câu.

Bản chạy thật: https://langnghe.hipingu.health

## Kiến trúc

Một service FastAPI vừa phục vụ file tĩnh vừa lo API. Text đi vào được chuẩn hoá, tra cache MP3
trên đĩa, nếu trượt thì gọi TTS rồi trả về MP3 dạng base64. Hàng đợi nằm ở phía trình duyệt trong
`localStorage`, server không lưu trạng thái gì.

Chuỗi nhà cung cấp TTS:

1. **gTTS** (Google) — mặc định. Tăng tốc `+20%` bằng hiệu ứng `tempo` của sox, giữ nguyên cao độ.
2. **edge-tts** (Microsoft, giọng HoaiMy) — dùng khi gTTS hỏng hoặc cầu dao đang mở, không đổi tốc độ.

**Cache hai tầng:** audio của mỗi nhà cung cấp nằm dưới khoá riêng. Tra khoá gTTS trước, chỉ khi
cầu dao mở mới tra tới khoá edge-tts. Nhờ vậy giọng dự phòng không lấn giọng mặc định, mà một đợt
Google chặn kéo dài cũng không khiến mỗi lần nghe lại đều phải gọi ra ngoài.

**Cầu dao gTTS** (`app/breaker.py`) — chặn trước khi Google chặn mình:

- *Ngân sách chủ động*: tối đa `GTTS_MAX_PER_MINUTE` lần gọi mỗi phút. Hết lượt thì dùng thẳng
  edge-tts, không chạm tới Google.
- *Phản ứng*: HTTP 429/403 mở cầu dao ngay lập tức (cố thêm chỉ làm bị chặn lâu hơn, nên cũng
  không retry). Lỗi khác thì đếm, đủ `GTTS_FAILURE_THRESHOLD` lần liên tiếp mới mở.
- *Hồi phục*: sau khoảng nghỉ thì thử đúng một request để dò; hỏng nữa thì khoảng nghỉ nhân đôi,
  tối đa `GTTS_MAX_COOLDOWN_SECONDS`.

Xem trạng thái bằng `GET /api/status`.

**Đọc đường dẫn:** gTTS đánh vần từng chữ cái khi gặp dấu chấm đứng trước chữ, đo được bằng thời
lượng audio — `.claude/features/client-surface.md` mất 9.31 giây. Hàm `speak_paths` viết lại thành
`chấm claude features client surface chấm md` (4.06 giây). Chỉ áp cho gTTS; edge-tts đọc đường dẫn
vốn đã ổn. Số phiên bản và số tiền (`3.12.4`, `1.500.000`) không bị đụng tới vì sau dấu chấm là số
chứ không phải chữ.

Cả hai chạy hoàn toàn phía server, không cần trình duyệt hay Chromium nào trong container.
Người dùng không chọn giọng hay tốc độ — giao diện không có tuỳ chọn đó.

Không database, không ffmpeg (dùng sox nhẹ hơn ~440MB), không build step cho frontend.

## Chạy

```bash
cp .env.example .env
docker compose up -d --build
```

Mặc định phục vụ tại `http://127.0.0.1:8010`. Đổi cổng bằng `APP_PORT` trong `.env`.

## Phát triển

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8010
```

Chạy test:

```bash
.venv/bin/python -m pytest                  # chạy offline, không đánh ra mạng
.venv/bin/python -m pytest -m integration   # đánh thật vào edge-tts
```

Nên chạy bộ integration trước mỗi lần deploy: `edge-tts` dùng endpoint không chính thức của
Microsoft, và test mock không phát hiện được khi endpoint đó thay đổi.

## Cấu hình

Xem `.env.example`. Đáng chú ý:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `APP_PORT` | `8010` | Cổng trên host |
| `TTS_FALLBACK_VOICE` | `vi-VN-HoaiMyNeural` | Giọng edge-tts dùng khi gTTS hỏng |
| `TTS_RATE` | `+20%` | Tốc độ đọc của gTTS, phải có dấu (`+0%` chứ không phải `0%`) |
| `MAX_TEXT_LENGTH` | `1000` | Giới hạn ký tự mỗi request |
| `RATE_LIMIT_PER_MINUTE` | `60` | Hạn mức mỗi IP |
| `CACHE_MAX_MB` | `512` | Vượt ngưỡng thì xoá file cũ nhất |
| `GTTS_MAX_PER_MINUTE` | `20` | Ngân sách gọi gTTS mỗi phút, hết thì dùng edge-tts |
| `GTTS_FAILURE_THRESHOLD` | `3` | Số lần hỏng liên tiếp trước khi mở cầu dao |
| `GTTS_COOLDOWN_SECONDS` | `300` | Khoảng nghỉ khi cầu dao mở |
| `GTTS_MAX_COOLDOWN_SECONDS` | `3600` | Trần của khoảng nghỉ sau khi nhân đôi nhiều lần |

## Lưu ý vận hành

**Cloudflare cache tài nguyên tĩnh 4 tiếng và ghi đè header `Cache-Control` của origin.** Vì vậy
mọi đường dẫn tĩnh trong HTML đều được gắn `?v=<băm nội dung>` lúc khởi động (`_gan_phien_ban`
trong `app/main.py`). Bỏ bước này thì sau mỗi lần deploy người dùng nhận HTML mới nhưng JS/CSS cũ,
và trang lỗi. Băm theo nội dung nên URL chỉ đổi khi file thật sự đổi.

**Ảnh và file tĩnh phải cho mọi user đọc được.** Container chạy `user: "1001:33"`, còn `COPY` giữ
nguyên mode file nguồn. File mode 640 sẽ khiến StaticFiles gửi 200 kèm Content-Length rồi đóng kết
nối không có thân phản hồi, và Cloudflare trả 520. Dockerfile có `chmod -R a+rX` để chặn việc đó;
`tests/test_static_assets.py` kiểm tra ngay từ working tree.

**Không thêm `security_opt: no-new-privileges:true` vào compose trên host này.** Host bật AppArmor;
`no_new_privs` chặn việc chuyển profile AppArmor lúc `exec`, làm mọi binary trong container lỗi
`operation not permitted`. Container vẫn được bảo vệ bằng profile AppArmor mặc định của Docker,
chạy non-root (`user: "1001:33"`), và chỉ bind vào loopback.

`user: "1001:33"` phải khớp chủ sở hữu thư mục `mp3/` trên host (`ubuntu:www-data`). Sai uid thì
container không ghi được cache.

## Triển khai

Domain đi qua Cloudflare Tunnel (container `cloudflared`, `network_mode: host`) trỏ vào
`http://localhost:8000`. Nginx **không** tham gia vào đường đi này.

Chuyển từ bản Django cũ sang:

```bash
pm2 stop "Web Lang Nghe"       # dừng bản cũ đang giữ cổng 8000
sed -i 's/^APP_PORT=.*/APP_PORT=8000/' .env
docker compose up -d
```

Lùi lại:

```bash
docker compose down
pm2 start "Web Lang Nghe"
```

Thư mục cũ `/home/ubuntu/www/langnghe.hipingu.com` giữ nguyên không đụng tới, nên lùi lại chỉ mất
vài giây.
