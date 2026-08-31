# Tự động đọc

Ứng dụng đọc văn bản tiếng Việt thành giọng nói. Dán văn bản hoặc tải lên file `.txt`, app cắt
thành từng dòng, đọc lần lượt và cho phép tạm dừng, nhảy câu, xoá hàng đợi.

Bản chạy thật: https://langnghe.hipingu.health

## Kiến trúc

Một service FastAPI vừa phục vụ file tĩnh vừa lo API. Text đi vào được chuẩn hoá, tra cache MP3
trên đĩa, nếu trượt thì gọi TTS rồi trả về MP3 dạng base64. Hàng đợi nằm ở phía trình duyệt trong
`localStorage`, **server không lưu trạng thái gì** — không database, không session.

```
app/
├── main.py      khởi tạo FastAPI, khai báo route, kiểm tra đầu vào
├── config.py    đọc cấu hình từ biến môi trường
├── text.py      chuẩn hoá câu và viết lại đường dẫn cho dễ đọc
├── tts.py       chuỗi nhà cung cấp TTS, retry, single-flight
├── breaker.py   cầu dao và ngân sách gọi gTTS
├── cache.py     cache MP3 trên đĩa
└── limits.py    rate limit theo IP
static/          HTML, CSS, JS thuần — không build step, không node_modules
```

### Chuỗi nhà cung cấp TTS

1. **gTTS** (Google) — mặc định. Tăng tốc `+20%` bằng hiệu ứng `tempo` của sox, giữ nguyên cao độ.
   Ép bitrate 64kbps vì mặc định sox mã hoá lại ở 32kbps, tức là bước tăng tốc âm thầm làm giảm
   một nửa chất lượng.
2. **edge-tts** (Microsoft, giọng HoaiMy) — dùng khi gTTS hỏng hoặc cầu dao đang mở, không đổi
   tốc độ.

Cả hai chạy hoàn toàn phía server: đó là thư viện Python gọi thẳng ra endpoint của nhà cung cấp,
không cần trình duyệt hay Chromium nào trong container. Người dùng không chọn giọng hay tốc độ —
giao diện không có tuỳ chọn đó.

### Cache hai tầng

Audio của mỗi nhà cung cấp nằm dưới khoá riêng. Tra khoá gTTS trước, chỉ khi cầu dao mở mới tra
tới khoá edge-tts. Nhờ vậy giọng dự phòng không lấn giọng mặc định, mà một đợt Google chặn kéo dài
cũng không khiến mỗi lần nghe lại đều phải gọi ra ngoài.

Cache ghi nguyên tử (ghi file tạm rồi `os.replace`), nên tiến trình chết giữa chừng không bao giờ
để lại MP3 hỏng. Vượt `CACHE_MAX_MB` thì xoá dần file cũ nhất.

### Cầu dao gTTS

`app/breaker.py` — chặn trước khi Google chặn mình:

- **Ngân sách chủ động**: tối đa `GTTS_MAX_PER_MINUTE` lần gọi mỗi phút. Hết lượt thì dùng thẳng
  edge-tts, không chạm tới Google.
- **Phản ứng**: HTTP 429/403 mở cầu dao ngay lập tức, và cũng không retry — cố thêm lúc đó chỉ làm
  bị chặn lâu hơn. Lỗi khác thì đếm, đủ `GTTS_FAILURE_THRESHOLD` lần liên tiếp mới mở.
- **Hồi phục**: sau khoảng nghỉ thì thử đúng một request để dò; hỏng nữa thì khoảng nghỉ nhân đôi,
  tối đa `GTTS_MAX_COOLDOWN_SECONDS`.

Xem trạng thái bằng `GET /api/status`.

### Đọc đường dẫn

gTTS đánh vần từng chữ cái khi gặp dấu chấm đứng trước chữ. Đo bằng thời lượng audio:

| Văn bản | Thời lượng |
|---|---|
| `.claude/features/client-surface.md` | 9.31s |
| `chấm claude features client surface chấm md` | 4.01s |
| `config.py` | 3.26s |
| `config chấm py` | 1.54s |

Hàm `speak_paths` trong `app/text.py` viết lại các cụm trông như đường dẫn: `.` thành " chấm ",
còn `/ \ _ - :` thành khoảng trắng. Chỉ áp cho gTTS — edge-tts đọc đường dẫn vốn đã ổn.

Số phiên bản và số tiền (`3.12.4`, `1.500.000`) **không** bị đụng tới, vì điều kiện nhận diện đòi
hỏi sau dấu chấm phải là chữ cái. Dấu câu cuối cụm cũng được tách ra trước khi biến đổi, nếu không
thì `config.py.` bị đọc thành "config chấm py chấm".

## API

| Endpoint | Mô tả |
|---|---|
| `GET /` | Giao diện |
| `GET /about`, `/about/` | Trang giới thiệu |
| `POST /api/tts` | `{"text": "..."}` → `{"text", "base64", "name"}` |
| `POST /text-to-speech` | Bí danh của `/api/tts` |
| `GET /api/status` | Trạng thái cầu dao gTTS và dung lượng cache |
| `GET /healthz` | Healthcheck cho Docker, luôn 200 khi tiến trình còn sống |

Mã lỗi của `/api/tts`: `413` văn bản quá dài, `422` văn bản rỗng hoặc không có chữ/số nào,
`429` vượt rate limit (kèm `Retry-After`), `503` mọi nhà cung cấp TTS đều hỏng.

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
sudo apt install sox libsox-fmt-mp3     # cần cho việc tăng tốc gTTS
.venv/bin/uvicorn app.main:app --reload --port 8010
```

Chạy test:

```bash
.venv/bin/python -m pytest                  # chạy offline, không đánh ra mạng
.venv/bin/python -m pytest -m integration   # đánh thật vào gTTS và edge-tts
```

**Nên chạy bộ integration trước mỗi lần deploy.** Cả gTTS lẫn edge-tts đều dùng endpoint không
chính thức, và test mock không bao giờ phát hiện được khi nhà cung cấp đổi giao thức hoặc chặn
server — đó lại đúng là kiểu hỏng đáng lo nhất.

## Cấu hình

Xem `.env.example`. Đáng chú ý:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `APP_PORT` | `8010` | Cổng trên host |
| `TTS_RATE` | `+20%` | Tốc độ đọc của gTTS, phải có dấu (`+0%` chứ không phải `0%`) |
| `TTS_FALLBACK_VOICE` | `vi-VN-HoaiMyNeural` | Giọng edge-tts dùng khi gTTS hỏng |
| `MAX_TEXT_LENGTH` | `1000` | Giới hạn ký tự mỗi request |
| `RATE_LIMIT_PER_MINUTE` | `60` | Hạn mức mỗi IP |
| `CACHE_MAX_MB` | `512` | Vượt ngưỡng thì xoá file cũ nhất |
| `GTTS_MAX_PER_MINUTE` | `20` | Ngân sách gọi gTTS mỗi phút, hết thì dùng edge-tts |
| `GTTS_FAILURE_THRESHOLD` | `3` | Số lần hỏng liên tiếp trước khi mở cầu dao |
| `GTTS_COOLDOWN_SECONDS` | `300` | Khoảng nghỉ khi cầu dao mở |
| `GTTS_MAX_COOLDOWN_SECONDS` | `3600` | Trần của khoảng nghỉ sau khi nhân đôi nhiều lần |

Không có secret nào — `.env` chỉ chứa cổng, tốc độ và các ngưỡng.

## Lưu ý vận hành

Bốn điều dưới đây đều đến từ sự cố thật, và đều đã có test hoặc cấu hình chặn tái diễn.

**Tài nguyên tĩnh được gắn phiên bản, đừng gỡ.** Cloudflare cache tài nguyên tĩnh 4 tiếng và ghi
đè header `Cache-Control` của origin, nên không thể dựa vào header để buộc làm mới. Mọi đường dẫn
tĩnh trong HTML được gắn `?v=<băm nội dung>` lúc khởi động (`_add_asset_versions` trong
`app/main.py`). Bỏ bước này thì sau mỗi lần deploy người dùng nhận HTML mới nhưng JS/CSS cũ, hai
bản lệch nhau và trang lỗi. Băm theo nội dung nên URL chỉ đổi khi file thật sự đổi.

**File tĩnh phải cho mọi user đọc được.** Container chạy `user: "1001:33"`, còn `COPY` của Docker
giữ nguyên mode file nguồn. File mode 640 sẽ khiến StaticFiles gửi 200 kèm `Content-Length` rồi
đóng kết nối không có thân phản hồi, và Cloudflare quy ra lỗi 520. Dockerfile có `chmod -R a+rX`
để chặn việc đó; `tests/test_static_assets.py` kiểm tra ngay từ working tree.

**Không thêm `security_opt: no-new-privileges:true` vào compose trên host này.** Host bật AppArmor;
`no_new_privs` chặn việc chuyển profile AppArmor lúc `exec`, làm mọi binary trong container lỗi
`operation not permitted`, kể cả `python`. Container vẫn được bảo vệ bằng profile AppArmor mặc
định của Docker, chạy non-root, và chỉ bind vào loopback.

**`user: "1001:33"` phải khớp chủ sở hữu thư mục `mp3/` trên host** (`ubuntu:www-data`). Sai uid
thì container không ghi được cache.

## Triển khai

Domain đi qua Cloudflare Tunnel (container `cloudflared` chạy `network_mode: host`) trỏ thẳng vào
`http://localhost:8000`. Nginx **không** tham gia vào đường đi này, nên đổi cổng ở đây là đủ,
không cần sửa gì trên dashboard Cloudflare.

```bash
sed -i 's/^APP_PORT=.*/APP_PORT=8000/' .env
docker compose up -d --build
curl -s -o /dev/null -w '%{http_code}\n' https://langnghe.hipingu.health/
```

Vì cloudflared kết nối tới `127.0.0.1`, `request.client.host` là `127.0.0.1` với mọi người dùng —
rate limit lấy IP thật từ header `CF-Connecting-IP`. Tin được header đó vì cổng chỉ bind vào
loopback, không ai từ Internet gọi thẳng vào được.
