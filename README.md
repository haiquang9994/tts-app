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
2. **edge-tts** (Microsoft, giọng HoaiMy) — chỉ dùng khi gTTS hỏng, không đổi tốc độ.

Kết quả từ nhà cung cấp dự phòng **không được ghi vào cache**, để khi gTTS hồi phục thì câu đó
được đọc lại bằng giọng mong muốn.

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
