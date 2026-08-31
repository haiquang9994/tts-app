# Kiến trúc

Một service duy nhất. FastAPI vừa phục vụ file tĩnh (`StaticFiles` mount ở `/static`) vừa lo API,
nên không cần nginx hay reverse proxy nào trong compose.

## Luồng của một request

```
POST /api/tts {"text": "..."}
  │
  ├─ rate limit theo IP  ──────────────────► 429 nếu vượt
  ├─ kiểm tra độ dài     ──────────────────► 413 nếu quá dài
  ├─ strip_markdown + normalize            ► 422 nếu không còn chữ/số nào
  │
  └─ Synthesizer.get_audio(final_text)
       │
       ├─ tra cache khoá gTTS ──────────────► trúng thì trả luôn
       ├─ single-flight: request trùng nội dung chờ chung một kết quả
       │
       ├─ ProviderGuard.allow()?
       │    ├─ CÓ  → gTTS (speak_paths → gTTS → sox tăng tốc) → ghi cache khoá gTTS
       │    └─ KHÔNG → bỏ qua Google hoàn toàn
       │
       └─ dự phòng: tra cache khoá edge → edge-tts → ghi cache khoá edge
```

Mỗi module có đúng một trách nhiệm và kiểm thử độc lập được: `cache.py` chỉ biết tới đĩa, `tts.py`
chỉ biết tới nhà cung cấp, `text.py` là hàm thuần, `main.py` ghép chúng lại.

## Chuỗi nhà cung cấp TTS

1. **gTTS** (Google) — mặc định. Tăng tốc `+20%` bằng sox.
2. **edge-tts** (Microsoft, giọng HoaiMy) — dùng khi gTTS hỏng hoặc cầu dao đang mở, không đổi
   tốc độ.

Cả hai chạy hoàn toàn phía server: đó là thư viện Python gọi thẳng ra endpoint của nhà cung cấp,
không cần trình duyệt hay Chromium nào trong container. Người dùng **không** chọn được giọng hay
tốc độ — giao diện không có tuỳ chọn đó.

Có hai cách tăng tốc, chọn bằng `TTS_SPEED_MODE`:

| Chế độ | Hiệu ứng sox | Nghe ra sao |
|---|---|---|
| `tempo` (mặc định) | `tempo 1.2` | WSOLA giãn thời gian, cao độ giữ nguyên |
| `resample` | `speed 1.2` | Đổi sample rate: nhanh hơn thì giọng cũng cao lên đúng 1.2 lần |

Về mặt kỹ thuật `resample` làm méo giọng, nhưng có người thích đúng chất giọng đó, nên đây là
một lựa chọn chứ không phải lỗi cần sửa. Hai chế độ có khoá cache khác nhau (`speed_cache_key` trong `tts.py`),
nên đổi biến môi trường là sinh audio mới chứ không phát lại bản cũ; riêng chế độ mặc định giữ
nguyên khoá như hồi chưa có biến này, để cache đã có vẫn dùng được.

`sox` được gọi với `-C 64` để ép bitrate. Bỏ tham số này thì sox (và cả ffmpeg) mã hoá lại ở
32kbps mặc định, tức là bước tăng tốc âm thầm làm giảm một nửa chất lượng audio của gTTS.

## Cache hai tầng

Audio của mỗi nhà cung cấp nằm dưới khoá riêng — `GTTS_VARIANT` và `EDGE_VARIANT` trong `tts.py`
là thành phần của khoá băm.

Tra khoá gTTS trước; chỉ khi cầu dao mở mới tra tới khoá edge-tts. Hai hệ quả đều quan trọng:

- Giọng dự phòng **không lấn** giọng mặc định. Khi gTTS hồi phục, câu đó được đọc lại bằng giọng
  mong muốn chứ không dùng bản edge-tts đã cache.
- Một đợt Google chặn kéo dài **không** khiến mỗi lần nghe lại đều phải gọi ra ngoài.

Cache ghi nguyên tử: ghi ra file `.tmp` rồi `os.replace`. Tiến trình chết giữa chừng chỉ để lại
file `.tmp` vô hại, không bao giờ để lại MP3 hỏng. File `.tmp` mồ côi được dọn lúc khởi động.
Vượt `CACHE_MAX_MB` thì xoá dần file cũ nhất theo `mtime` cho tới khi còn 80% ngưỡng.

## Cầu dao gTTS

`app/breaker.py` — mục tiêu là **chặn trước khi Google chặn mình**.

- **Ngân sách chủ động**: token bucket, tối đa `GTTS_MAX_PER_MINUTE` lần gọi mỗi phút. Hết lượt
  thì dùng thẳng edge-tts, không chạm tới Google. Hết ngân sách **không** tính là hỏng, cầu dao
  vẫn đóng.
- **Phản ứng**: HTTP 429/403 mở cầu dao ngay lập tức và cũng **không retry** — cố thêm lúc đó chỉ
  làm bị chặn lâu hơn. `gTTSError` mang theo đối tượng response nên đọc được mã trạng thái từ
  thuộc tính `rsp`. Lỗi khác thì đếm, đủ `GTTS_FAILURE_THRESHOLD` lần liên tiếp mới mở.
- **Hồi phục**: hết khoảng nghỉ thì chuyển sang *nửa mở*, cho đúng một request dò thử. Thành công
  thì đóng lại và reset; hỏng nữa thì khoảng nghỉ nhân đôi, trần là `GTTS_MAX_COOLDOWN_SECONDS`.

Xem trạng thái bằng `GET /api/status`. Endpoint này tách khỏi `/healthz` có chủ đích: healthz phải
luôn trả 200 cho Docker, vì nhà cung cấp TTS chập chờn không có nghĩa là tiến trình chết.

## Single-flight

`Synthesizer._inflight` là `dict[str, asyncio.Future]` khoá theo cache key. Nhiều request cùng nội
dung đến cùng lúc thì chỉ một cái gọi thật ra ngoài, số còn lại `await` chung future đó. Không có
nó thì hai tab mở cùng nội dung sẽ gọi mạng hai lần và ghi đè lên nhau.

`asyncio.Semaphore(TTS_MAX_CONCURRENCY)` bao quanh mọi lời gọi ra ngoài, ngăn một lượt tải đột
biến biến thành hàng chục kết nối đồng thời — chính là kiểu hành vi dẫn tới bị chặn IP.

## Rate limit

Token bucket trong bộ nhớ, theo IP. Bộ đếm mất khi khởi động lại — chấp nhận được, mục tiêu là
chặn lạm dụng chứ không phải tính cước. Bucket không đụng tới quá 10 phút bị dọn để dict không
phình vô hạn.

**Lấy IP thật:** `cloudflared` chạy `network_mode: host` và kết nối tới `127.0.0.1`, nên
`request.client.host` là `127.0.0.1` với **mọi** người dùng — rate limit theo giá trị đó là vô
dụng. `client_ip()` đọc header `CF-Connecting-IP`. Tin được header đó vì cổng chỉ bind vào
loopback, không ai từ Internet gọi thẳng vào được.
