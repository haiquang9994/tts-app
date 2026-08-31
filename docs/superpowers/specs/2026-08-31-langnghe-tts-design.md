# Thiết kế: Port app "Tự động đọc" sang FastAPI + Docker Compose

- **Ngày:** 2026-08-31
- **Trạng thái:** Chờ duyệt
- **Nguồn:** `/home/ubuntu/www/langnghe.hipingu.com` (Django 3.1, chạy qua pm2)
- **Đích:** `/home/ubuntu/www/langnghe`
- **Đang phục vụ tại:** https://langnghe.hipingu.health

## 1. Bối cảnh

App "Tự động đọc" nhận văn bản tiếng Việt (dán tay hoặc upload `.txt`), cắt thành từng câu, chuyển
thành giọng nói rồi phát tuần tự. Hàng đợi nằm ở phía trình duyệt trong `localStorage`, server chỉ
làm đúng một việc: text vào, MP3 ra.

Bản hiện tại là Django 3.1 + gTTS + pydub/ffmpeg. Những vấn đề cụ thể:

- **Django không được dùng đến.** `models.py` rỗng, `db.sqlite3` chỉ chứa bảng mặc định. Toàn bộ
  ORM, admin, auth, sessions, migrations là gánh nặng không đổi lấy gì.
- **Cache MP3 chỉ ghi, không bao giờ đọc.** `textToSpeech` luôn gọi gTTS rồi ghi đè, kể cả khi file
  đã tồn tại. Kết quả: 1914 file / 138MB tích tụ vô ích, và mỗi lần đọc lại đoạn cũ vẫn phải chờ mạng.
- **Ghi file không nguyên tử.** gTTS lỗi giữa chừng để lại file MP3 hỏng nằm trong cache vĩnh viễn.
- **Endpoint mở hoàn toàn.** `@csrf_exempt`, không giới hạn độ dài, không rate limit, không giới hạn
  số kết nối đồng thời ra ngoài.
- **Tăng tốc bằng cách đổi `frame_rate`** (`sound._spawn` với `frame_rate * 1.2`) làm giọng đọc bị
  lên cao, nghe chói.
- **`SECRET_KEY` của Django bị commit thẳng vào git.**
- `uploadFilePageView` trong `views.py` là code chết, không có route nào trỏ tới.

## 2. Mục tiêu

1. Chạy bằng `docker compose`, một service duy nhất, không phụ thuộc pm2 hay virtualenv trên host.
2. Gọn: bỏ mọi thành phần không dùng đến, giữ image nhỏ nhất có thể.
3. Ổn định: bịt các lỗ hổng ở mục 1, để một sự cố phía nhà cung cấp TTS không kéo sập cả app.
4. Giữ nguyên trải nghiệm cốt lõi: cùng cách nhập liệu, cùng hàng đợi, cùng phím tắt.
5. Chuyển đổi được và lùi lại được mà không đụng vào cấu hình Cloudflare.

## 3. Phạm vi

**Trong phạm vi**

- Viết lại backend bằng FastAPI, bỏ hẳn Django và SQLite.
- Đổi engine TTS từ gTTS sang `edge-tts`; bỏ `pydub` và `ffmpeg`.
- Tách frontend thành file tĩnh, **giữ nguyên logic**, thêm bộ chọn giọng và tốc độ.
- Cache MP3 đọc được thật, ghi nguyên tử, có dọn dẹp.
- Giới hạn độ dài, rate limit, giới hạn kết nối đồng thời.
- `Dockerfile` + `docker-compose.yml` + kịch bản chuyển đổi và lùi lại.
- Test tự động, chạy được offline.

**Ngoài phạm vi**

- Không di chuyển 138MB cache MP3 cũ sang (giọng khác hoàn toàn, cách tính key cũng đổi).
- Không di chuyển `db.sqlite3` (không chứa dữ liệu nghiệp vụ nào).
- Không giữ lịch sử git của repo nguồn — project đích khởi tạo repo mới.
- Không xây fallback đa nhà cung cấp TTS ngay lần này (xem mục 7.1 về việc chừa sẵn chỗ).
- Không đụng vào cấu hình Cloudflare Tunnel.

## 4. Tech stack

| Thành phần | Chọn | Lý do |
|---|---|---|
| Web framework | **FastAPI** | `edge-tts` là async; FastAPI async native nên khớp tự nhiên. Có validation bằng pydantic. Bỏ được toàn bộ phần Django không dùng. |
| ASGI server | **uvicorn** | Chuẩn đi kèm FastAPI, một tiến trình là đủ cho tải của app này. |
| TTS | **edge-tts** | Giọng neural tiếng Việt, hay hơn hẳn gTTS. Có sẵn tham số `rate` nên **bỏ được `pydub` và `ffmpeg`**, và tăng tốc mà không bị lên cao giọng. Miễn phí, không cần API key. |
| Frontend | **HTML/CSS/JS tĩnh** | Không build step, không `node_modules`. Logic hiện tại đã chạy tốt. |
| Lưu trữ | **Hệ thống file** | App không có state nghiệp vụ. Cache MP3 là thứ duy nhất cần lưu. |
| Đóng gói | **python:3.12-slim** | Không cần ffmpeg nên không phải dùng image đầy đủ. |

**Đã cân nhắc và loại:**

- *Starlette thuần* — nhẹ hơn FastAPI vài MB nhưng mất validation và phải tự viết thêm code. Không đáng.
- *Flask / Django 5* — sync, phải bọc `asyncio.run()` quanh mọi lời gọi edge-tts.
- *Piper (offline)* — ổn định nhất về lâu dài vì không phụ thuộc dịch vụ ngoài, nhưng image nặng thêm
  ~250MB và chất lượng giọng tiếng Việt thấp hơn. Mục 7.1 chừa sẵn đường đổi sang nếu cần.

### 4.1 Quản lý dependency

`requirements.txt` với version ghim chính xác (`==`), gồm đúng ba package trực tiếp: `fastapi`,
`uvicorn[standard]`, `edge-tts`. Dependency dành cho phát triển (`pytest`, `pytest-asyncio`, `httpx`)
tách ra `requirements-dev.txt` và **không** đưa vào image.

Version cụ thể do người triển khai ghim tại thời điểm cài (`pip freeze` cho ba package trên và các
dependency bắc cầu chính), không đoán trước trong tài liệu này. Không thêm công cụ quản lý dependency
mới (uv, poetry, pip-tools) — với ba package thì việc ghim tay đơn giản hơn và ai cũng đọc được.

## 5. Kiến trúc

Một service. FastAPI vừa phục vụ file tĩnh (`StaticFiles`) vừa lo API, nên không cần nginx trong compose.

```
Browser ──POST /api/tts──► FastAPI
                              │
                              ├─ kiểm tra đầu vào (độ dài, giọng, tốc độ)
                              ├─ rate limit theo IP
                              ├─ chuẩn hoá text  ──► cache key = md5(final_text|voice|rate)
                              │
                              ├─ cache hit ──────────────────────► đọc file ──► base64
                              │
                              └─ cache miss ──► single-flight lock
                                                └─ semaphore (tối đa N đồng thời)
                                                   └─ edge-tts qua WSS (retry tối đa 2 lần)
                                                      └─ ghi .tmp ──► os.replace ──► base64
```

`edge-tts` chạy **hoàn toàn ở phía server** — nó là thư viện Python mở kết nối WebSocket tới endpoint
Azure Speech mà tính năng Read Aloud của Edge dùng. Không cần cài Edge, Chromium hay headless browser
nào trong container.

### 5.1 Cấu trúc thư mục

```
langnghe/
├── docker-compose.yml
├── Dockerfile
├── .dockerignore
├── .gitignore
├── .env.example
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py          # khởi tạo FastAPI, mount static, khai báo route
│   ├── config.py        # đọc cấu hình từ biến môi trường
│   ├── text.py          # chuẩn hoá văn bản (hàm thuần, không side effect)
│   ├── tts.py           # interface synthesize() + hiện thực bằng edge-tts
│   ├── cache.py         # cache trên đĩa: key, ghi nguyên tử, dọn dẹp
│   └── limits.py        # rate limit theo IP + semaphore đồng thời
├── static/
│   ├── index.html
│   ├── about.html
│   ├── app.js
│   ├── style.css
│   └── img/{play,pause,end,check,remove}.png
├── mp3/
│   └── .gitkeep         # thư mục cache, mount volume
├── tests/
│   ├── test_text.py
│   ├── test_cache.py
│   ├── test_api.py
│   └── test_tts_integration.py
└── docs/superpowers/specs/
```

Mỗi module một trách nhiệm, kiểm thử độc lập được: `text.py` là hàm thuần; `cache.py` chỉ biết tới
đĩa; `tts.py` chỉ biết tới nhà cung cấp TTS; `main.py` ghép chúng lại.

## 6. API

### `GET /`
Trả `static/index.html`.

### `GET /about` và `GET /about/`
Trả `static/about.html` (trang tĩnh ghi tên và email tác giả, giữ cho đủ so với bản cũ). Nhận cả hai
dạng vì bản Django cũ dùng `/about/` có dấu gạch chéo cuối.

### `POST /api/tts`

Request:

```json
{ "text": "...", "voice": "vi-VN-HoaiMyNeural", "rate": "+20%" }
```

- `text` — bắt buộc, chuỗi, sau khi `strip()` phải khác rỗng, tối đa `MAX_TEXT_LENGTH` ký tự.
- `voice` — tuỳ chọn, phải nằm trong danh sách cho phép (mục 9.2). Bỏ trống thì lấy `TTS_VOICE`.
- `rate` — tuỳ chọn, khớp `^[+-]\d{1,3}%$` và nằm trong khoảng `-50%`..`+100%`. Bỏ trống thì lấy `TTS_RATE`.

Response `200`:

```json
{ "text": "<văn bản đã chuẩn hoá>", "base64": "<MP3 đã mã hoá base64>", "name": "<cache key>" }
```

Đúng shape mà frontend hiện tại đang đọc, nên phần JS xử lý kết quả không phải sửa. Trường `name`
bản cũ trả `md5(text)` và **không được frontend dùng vào việc gì**; bản mới trả cache key.

Mã lỗi:

| Mã | Khi nào | Body |
|---|---|---|
| `422` | Sai schema, text rỗng, giọng hoặc tốc độ không hợp lệ | `{"detail": "..."}` |
| `413` | Text vượt `MAX_TEXT_LENGTH` | `{"detail": "..."}` |

Độ dài `text` **không** khai bằng ràng buộc `max_length` của pydantic — làm vậy sẽ ra `422` lẫn với
lỗi schema. Kiểm tra thủ công trong handler để trả đúng `413`, tách bạch "văn bản quá dài" khỏi "sai
định dạng request".
| `429` | Vượt rate limit theo IP | `{"detail": "..."}` kèm header `Retry-After` |
| `503` | edge-tts lỗi sau khi đã retry hết | `{"detail": "..."}` |

### `POST /text-to-speech`
Alias của `/api/tts`, giữ để không làm hỏng bookmark hay client cũ đang dùng đường dẫn này.

### `GET /healthz`
Trả `{"status": "ok"}`. Không gọi ra mạng ngoài — healthcheck chỉ để biết tiến trình còn sống, chứ
không được đỏ chỉ vì Microsoft đang chập chờn.

## 7. Xử lý TTS

### 7.1 Interface

`app/tts.py` phơi ra đúng một hàm:

```python
async def synthesize(text: str, voice: str, rate: str) -> bytes
```

Phần còn lại của app chỉ gọi qua hàm này. Đổi sang Piper, gTTS hay nhà cung cấp khác là thay nội dung
một file, không phải mổ lại app. **Không** xây cơ chế fallback đa nhà cung cấp lần này — chưa cần, và
nó buộc phải giữ lại `ffmpeg` cùng hai nhánh code, đi ngược mục tiêu gọn nhẹ.

### 7.2 Retry

Tối đa 2 lần thử lại khi gặp lỗi mạng hoặc lỗi giao thức, backoff 0.5s rồi 1.5s. Hết lượt thì trả
`503`. Lỗi thoáng qua là kiểu hỏng phổ biến nhất của loại endpoint này; retry có giới hạn xử lý được
phần lớn mà không có nguy cơ lặp vô hạn.

**Không** retry với lỗi do đầu vào (giọng không tồn tại, text rỗng) — thử lại cũng hỏng y như vậy.

### 7.3 Giới hạn đồng thời

`asyncio.Semaphore(TTS_MAX_CONCURRENCY)` bao quanh mọi lời gọi ra ngoài. Ngăn một lượt tải đột biến
biến thành hàng chục kết nối đồng thời tới Microsoft — chính là kiểu hành vi dẫn tới việc IP server
bị chặn.

### 7.4 Single-flight

Một `dict[str, asyncio.Future]` khoá theo cache key. Nhiều request cùng nội dung đến cùng lúc thì chỉ
một request thật sự gọi TTS, số còn lại chờ kết quả đó. Không có nó thì hai tab mở cùng nội dung sẽ
gọi mạng hai lần và ghi đè lên nhau.

### 7.5 Tốc độ đọc

Dùng tham số `rate` của edge-tts (mặc định `+20%`), thay cho cách đổi `frame_rate` của bản cũ. Cùng
tốc độ nhưng **giữ nguyên cao độ**, nghe tự nhiên hơn. Đây là thay đổi có thể nghe thấy được so với
bản cũ, và là thay đổi có chủ ý.

## 8. Chuẩn hoá văn bản

`app/text.py` giữ **nguyên xi** chuỗi xử lý của bản cũ, kể cả những chi tiết trông lạ, vì đây là thứ
quyết định app ngắt câu nghe có tự nhiên không:

```python
text = re.sub(r'\.', '. ', text)
text = re.sub(r'\.\ \ ', '. ', text)
text = re.sub(r'\.\ +\"', '. "', text)
text = re.sub(r'\ \, ', ', ', text)
audio_text = re.sub(r'\"', '', text)
rows = [r for r in re.compile(r"\.(\ )|\-").split(audio_text.strip())
        if (r is not None and r.strip() != "")]
final_text = '. '.join(rows).strip()
```

Hai điểm phải giữ đúng khi viết lại:

1. Regex tách câu **có nhóm bắt** `(\ )`, nên `re.split` chèn cả nhóm bắt vào kết quả — và trả `None`
   ở những chỗ khớp nhánh `-`. Bộ lọc bắt buộc phải xử lý `None`, bỏ đi là vỡ ngay.
2. Thứ tự bốn phép `re.sub` có ý nghĩa; phép sau dọn dẹp kết quả của phép trước.

`test_text.py` khoá hành vi này bằng golden test đối chiếu với output của bản Django.

## 9. Cache và giới hạn

### 9.1 Cache trên đĩa

- **Key:** `md5(f"{final_text}|{voice}|{rate}")`. Có `voice` và `rate` trong key vì đổi giọng hay
  đổi tốc độ thì ra file âm thanh khác.
- **Đường dẫn:** `mp3/<key>.mp3`.
- **Đọc:** file tồn tại và kích thước lớn hơn 0 thì trả luôn, không gọi ra mạng. *Đây là phần bản cũ
  thiếu — nó luôn sinh lại.*
- **Ghi nguyên tử:** ghi vào `mp3/<key>.mp3.tmp` rồi `os.replace()` sang tên chính thức. Tiến trình
  chết giữa chừng chỉ để lại file `.tmp` vô hại, không bao giờ để lại MP3 hỏng trong cache.
- **Dọn `.tmp` mồ côi** lúc khởi động.
- **Dọn cache:** kiểm tra lúc khởi động, và sau mỗi `CACHE_CHECK_EVERY` lần ghi. Nếu tổng dung lượng
  vượt `CACHE_MAX_MB` thì xoá file cũ nhất theo `mtime` cho tới khi còn 80% ngưỡng. Không có bước này
  thì cache phình vô hạn đúng như bản cũ.

### 9.2 Danh sách giọng cho phép

edge-tts hiện có hai giọng tiếng Việt:

| Mã | Mô tả |
|---|---|
| `vi-VN-HoaiMyNeural` | Nữ (mặc định) |
| `vi-VN-NamMinhNeural` | Nam |

Danh sách này là **allowlist cứng trong code**. Cho truyền chuỗi giọng tuỳ ý nghĩa là biến server
thành proxy TTS đa ngôn ngữ cho người lạ dùng chùa.

Danh sách được kiểm chứng lại lúc hiện thực bằng `edge-tts --list-voices | grep vi-VN`; nếu thực tế
khác thì sửa allowlist và mục này cho khớp.

### 9.3 Giới hạn đầu vào

`MAX_TEXT_LENGTH` mặc định 1000 ký tự. Frontend vốn đã cắt theo từng dòng nên mỗi request là một câu
hoặc một đoạn ngắn; 1000 ký tự rộng rãi cho mục đích đó mà vẫn chặn được việc dán cả quyển sách vào
một request.

### 9.4 Rate limit

Token bucket trong bộ nhớ, theo IP: `RATE_LIMIT_PER_MINUTE` request mỗi phút (mặc định 60), cho phép
dồn cụm tới 20. Vượt thì trả `429` kèm `Retry-After`.

**Chi tiết quan trọng về việc lấy IP:** `cloudflared` chạy `network_mode: host` và kết nối tới
`127.0.0.1`, nên `request.client.host` sẽ là `127.0.0.1` với **mọi** người dùng — rate limit theo giá
trị đó là vô dụng. Phải lấy IP thật từ header `CF-Connecting-IP`, và chỉ tin header đó vì port chỉ
bind vào `127.0.0.1` nên không ai ngoài Internet gọi thẳng vào được. Không có header thì lùi về
`request.client.host`.

Bộ đếm nằm trong RAM và mất khi khởi động lại — chấp nhận được. Mục tiêu là chặn lạm dụng, không phải
tính cước.

## 10. Frontend

### 10.1 Giữ nguyên

Tách `home.html` (355 dòng, style nội tuyến) thành `index.html` + `app.js` + `style.css`, thay tag
template Django bằng đường dẫn tĩnh. **Hành vi giữ nguyên 100%:**

- Hàng đợi trong `localStorage` (`__queue_texts__`, `__base64_items__`)
- Prefetch trước tối đa 3 mục
- Vòng điều phối `setInterval` 500ms
- Phím `Space` để play/pause (trừ khi con trỏ đang ở trong textarea)
- Upload nhiều file `.txt`, cắt theo dòng
- Bộ lọc `text.match(/[a-zA-Z0-9]+/)` bỏ qua dòng không có chữ hay số
- Nút Next, nút Xoá tất cả

Vòng `setInterval` chạy liên tục có nhược điểm là hao pin trên điện thoại. Viết lại theo hướng
event-driven là việc **cố ý để lại cho sau** — lần này chỉ tách file cho sạch, không sửa logic, để
nếu có lỗi phát sinh thì biết chắc nó đến từ đâu.

### 10.2 Thêm mới: chọn giọng và tốc độ

Một hàng điều khiển gọn ngay trên vùng nhập liệu:

- **Giọng:** dropdown hai lựa chọn ở mục 9.2, mặc định Nữ (HoaiMy).
- **Tốc độ:** dropdown các mức `+0%`, `+10%`, `+20%` (mặc định), `+30%`, `+50%`. Giá trị gửi lên
  **luôn có dấu** — regex kiểm tra ở mục 6 bắt buộc như vậy, gửi `0%` sẽ bị trả `422`.

Lựa chọn lưu trong `localStorage` (`__tts_voice__`, `__tts_rate__`) và gửi kèm mỗi lời gọi `/api/tts`.

**Hành vi cần nói rõ với người dùng:** đổi giọng hoặc tốc độ chỉ ảnh hưởng tới các mục **sinh mới**.
Những mục đã prefetch xong trong hàng đợi vẫn giữ giọng cũ. Muốn áp dụng ngay lập tức thì bấm Xoá tất
cả rồi nhập lại. Ghi một dòng gợi ý nhỏ ngay cạnh bộ điều khiển.

Đây là thứ bản gTTS cũ không làm được, vì gTTS không cho chọn giọng.

### 10.3 Ảnh

Chép 5 file PNG (`play`, `pause`, `end`, `check`, `remove`) từ `static/` của bản cũ sang `static/img/`.

## 11. Cấu hình

Toàn bộ qua biến môi trường, đọc trong `app/config.py`. `.env.example` được commit; `.env` thì không.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `APP_PORT` | `8010` | Port trên host mà compose map ra (chỉ dùng bởi compose) |
| `TTS_VOICE` | `vi-VN-HoaiMyNeural` | Giọng mặc định |
| `TTS_RATE` | `+20%` | Tốc độ mặc định |
| `TTS_MAX_CONCURRENCY` | `4` | Số lời gọi TTS ra ngoài đồng thời tối đa |
| `TTS_TIMEOUT_SECONDS` | `30` | Timeout cho một lời gọi TTS |
| `MAX_TEXT_LENGTH` | `1000` | Độ dài text tối đa mỗi request |
| `RATE_LIMIT_PER_MINUTE` | `60` | Số request mỗi phút cho mỗi IP |
| `CACHE_DIR` | `mp3` | Thư mục cache |
| `CACHE_MAX_MB` | `512` | Ngưỡng dọn cache |
| `CACHE_CHECK_EVERY` | `50` | Số lần ghi giữa hai lần kiểm tra dung lượng cache |
| `LOG_LEVEL` | `INFO` | Mức log |

**Không có secret nào.** Bản cũ commit `SECRET_KEY` của Django vào git; bỏ Django thì không còn gì để lộ.

## 12. Docker

### 12.1 Dockerfile

`python:3.12-slim`, một tầng. Không cần ffmpeg. Cài `requirements.txt` trước rồi mới copy code để
tận dụng cache tầng.

Hai chi tiết **bắt buộc**, sai là hỏng ngay:

- **`HEALTHCHECK` không được dùng `curl` hay `wget`** — `python:3.12-slim` không có cả hai. Dùng
  `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"`.
- **Không đặt `USER` trong Dockerfile**; uid do compose quyết định (xem 12.2).

### 12.2 docker-compose.yml

```yaml
services:
  app:
    build: .
    image: langnghe:latest
    restart: unless-stopped
    user: "1001:33"
    ports:
      - "127.0.0.1:${APP_PORT:-8010}:8000"
    volumes:
      - ./mp3:/app/mp3
    env_file: [.env]
    security_opt: ["no-new-privileges:true"]
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "3" }
```

- **`user: "1001:33"` là bắt buộc.** Trên máy này `ubuntu` là `uid=1001 gid=33(www-data)`, không phải
  `1000:1000` như mặc định thường thấy. Chạy sai uid thì container **không ghi được vào `mp3/`** và
  mọi request đều lỗi.
- **Bind vào `127.0.0.1`**, không phải `0.0.0.0`. Chỉ `cloudflared` (chạy host network) cần với tới.
  Đây cũng là điều kiện để tin được header `CF-Connecting-IP` ở mục 9.4.
- **Giới hạn log** để container chạy nhiều tháng không ăn hết đĩa.

Kích thước image ước tính khoảng **190–210MB** (`python:3.12-slim` ~130MB cộng pydantic-core và
aiohttp). Đây là ước lượng, cần đo lại bằng `docker image ls` sau khi build. So với bản cũ (Python +
Django + ffmpeg) thì nhỏ hơn nhiều lần.

## 13. Triển khai

### 13.1 Cách site đang được phục vụ

Điều tra trên máy cho thấy **nginx không phải reverse proxy của site này**. `nginx` chỉ có site
`default` và không có dòng nào nhắc tới `langnghe`. Đường đi thật là:

```
Internet → Cloudflare → container `cloudflared` (network_mode: host) → http://localhost:8000
                                                                         ↑
                                              pm2 "Web Lang Nghe" → manage.py runserver
```

Luật ingress nằm trong dashboard Cloudflare (tunnel chạy bằng token, cấu hình từ xa). Hệ quả có lợi:
**chỉ cần container mới bind đúng `127.0.0.1:8000` là chuyển đổi xong, không phải sửa gì trên
Cloudflare.**

### 13.2 Chạy song song để kiểm thử

Mặc định `APP_PORT=8010` nên bản mới chạy được cạnh bản cũ. Bản cũ vẫn phục vụ người dùng thật trong
lúc bản mới được kiểm tra tại `http://127.0.0.1:8010`.

### 13.3 Chuyển đổi

1. `docker compose up -d --build` với `APP_PORT=8010`, kiểm tra kỹ.
2. `pm2 stop "Web Lang Nghe"` (dùng `stop`, không phải `delete`, để lùi lại được nhanh).
3. Đổi `APP_PORT=8000` trong `.env`.
4. `docker compose up -d`.
5. Kiểm tra https://langnghe.hipingu.health.

### 13.4 Lùi lại

1. `docker compose down`
2. `pm2 start "Web Lang Nghe"`

Thư mục cũ `/home/ubuntu/www/langnghe.hipingu.com` **giữ nguyên không đụng tới**, gồm cả virtualenv,
`db.sqlite3` và 138MB cache MP3. Lùi lại là thao tác trong vài giây. Chỉ xoá sau khi bản mới đã chạy
ổn định một thời gian, và đó là quyết định riêng ở thời điểm đó.

### 13.5 Git

Project đích khởi tạo repo mới (`git init`), không kế thừa lịch sử từ `tu-dong-doc`. `.gitignore` bỏ
qua `mp3/*` (giữ `.gitkeep`), `.env`, `__pycache__/`, `.pytest_cache/`.

## 14. Kiểm thử

`pytest` + `pytest-asyncio` + `httpx`. **Mặc định toàn bộ test chạy được offline.**

**`test_text.py`** — golden test cho `normalize()`. Bộ ca kiểm thử lấy từ hành vi thật của bản Django:
câu có dấu chấm, có dấu ngoặc kép, có gạch nối, dấu chấm liền nhau, chuỗi rỗng, chuỗi chỉ có khoảng
trắng. Đây là lưới an toàn quan trọng nhất — chuẩn hoá sai thì app ngắt câu sai và nghe rất khó chịu.

**`test_cache.py`** — key ổn định và đổi theo `voice`/`rate`; cache hit không gọi hàm synthesize lần
hai; ghi nguyên tử (giả lập lỗi giữa chừng, khẳng định không có file `.mp3` hỏng nào nằm lại); dọn
cache xoá đúng file cũ nhất và dừng đúng ngưỡng.

**`test_api.py`** — với `synthesize` được mock: shape response đúng; text quá dài trả `413`; giọng
ngoài allowlist trả `422`; `rate` sai định dạng trả `422`; text rỗng trả `422`; vượt rate limit trả
`429`; `synthesize` ném lỗi thì trả `503` chứ không phải `500`; single-flight — hai request đồng thời
cùng nội dung chỉ gọi `synthesize` một lần; `/text-to-speech` và `/api/tts` cho kết quả như nhau.

**`test_tts_integration.py`** — đánh dấu `@pytest.mark.integration`, mặc định bị loại qua
`addopts = -m "not integration"` trong cấu hình pytest. Gọi thật ra edge-tts và khẳng định nhận về
MP3 hợp lệ, khác rỗng. Chạy tay bằng `pytest -m integration`.

Test này tồn tại vì test mock **không bao giờ** phát hiện được kiểu hỏng mà ta lo nhất: Microsoft đổi
giao thức hoặc chặn server. Nên chạy nó trước mỗi lần deploy.

## 15. Rủi ro đã biết

| Rủi ro | Ảnh hưởng | Cách xử lý |
|---|---|---|
| edge-tts dùng endpoint không chính thức, Microsoft có thể đổi hoặc chặn | App mất chức năng đọc | Interface `synthesize()` ở 7.1 cho phép đổi nhà cung cấp bằng cách sửa một file. Integration test phát hiện sớm. Nếu cần cắt hẳn phụ thuộc mạng thì chuyển sang Piper offline. |
| Server phải có internet ra ngoài | Mất mạng là mất chức năng | Đúng như bản gTTS hiện tại, không tệ hơn. Cache giúp nội dung đã đọc vẫn phát lại được. |
| Giọng đọc khác hẳn bản cũ | Người dùng quen giọng cũ thấy lạ | Có chủ ý, và là điểm mạnh: giọng neural hay hơn, tăng tốc không bị chói. Có hai giọng để chọn. |
| Rate limit trong RAM, mất khi restart | Cửa sổ lạm dụng ngắn sau mỗi lần khởi động lại | Chấp nhận được với quy mô này. Thêm Redis là thêm một thành phần có thể hỏng, không đáng. |
| Cache cũ 138MB bị bỏ | Vài lần gọi TTS đầu tiên chậm hơn | Cache cũ dù sao cũng vô dụng: giọng khác, key khác. |

## 16. Cố tình không làm

Không database, không Redis, không worker queue, không nginx trong compose, không CI, không công cụ
quản lý dependency mới, không fallback đa nhà cung cấp TTS, không tài khoản người dùng, không lưu
lịch sử phía server. Mỗi thứ trong số đó đều thêm một thành phần có thể hỏng để đổi lấy lợi ích mà
quy mô app này chưa cần tới.
