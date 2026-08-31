# API

| Endpoint | Mô tả |
|---|---|
| `GET /` | Giao diện |
| `GET /about`, `/about/` | Trang giới thiệu |
| `POST /api/tts` | `{"text": "..."}` → `{"text", "base64", "name"}` |
| `POST /api/translate` | `{"text": "..."}` → `{"text"}`, dịch Anh → Việt |
| `POST /text-to-speech` | Bí danh của `/api/tts` |
| `GET /api/status` | Trạng thái cầu dao gTTS và dung lượng cache |
| `GET /healthz` | Healthcheck cho Docker, luôn 200 khi tiến trình còn sống |

## `POST /api/tts`

Request chỉ nhận một trường `text`. Không có `voice` hay `rate` — giọng và tốc độ do server quyết
định, giao diện không cho chọn. Gửi kèm hai trường đó cũng không sao, chúng bị bỏ qua.

Phản hồi:

| Trường | Ý nghĩa |
|---|---|
| `text` | Văn bản sau khi chuẩn hoá (dùng để chẩn đoán, giao diện không hiển thị) |
| `base64` | MP3 đã mã hoá base64 |
| `name` | Khoá cache |

Mã lỗi:

| Mã | Khi nào |
|---|---|
| `413` | Văn bản vượt `MAX_TEXT_LENGTH` |
| `422` | Thiếu trường `text`, văn bản rỗng, hoặc không còn chữ/số nào sau khi lọc |
| `429` | Vượt rate limit theo IP, kèm header `Retry-After` |
| `503` | Mọi nhà cung cấp TTS đều hỏng |

Độ dài `text` **không** khai bằng ràng buộc `max_length` của pydantic — làm vậy sẽ ra `422` lẫn
với lỗi schema. Kiểm tra thủ công trong handler để trả đúng `413`.

## `POST /api/translate`

Dịch tiếng Anh sang tiếng Việt để người dùng xem lại **trước khi** thêm vào hàng đợi. Hoàn toàn
tách khỏi luồng TTS: giao diện thay nội dung ô nhập bằng bản dịch, còn phần đọc phía sau không
biết gì về việc đã dịch. Hỏng ở đây không ảnh hưởng gì tới giọng đọc.

Các token trông như code được giữ nguyên tiếng Anh — chi tiết trong
[translation.md](translation.md).

Mã lỗi:

| Mã | Khi nào |
|---|---|
| `413` | Văn bản vượt `MAX_TRANSLATE_LENGTH` |
| `422` | Thiếu trường `text` hoặc văn bản rỗng |
| `429` | Vượt rate limit theo IP, kèm header `Retry-After` |
| `503` | Gemini hỏng, chưa cấu hình key, hoặc hết `GEMINI_MAX_PER_DAY` |

Gặp `503` thì giao diện **giữ nguyên văn bản gốc** và chỉ hiện thông báo — người dùng vẫn nghe
được bản tiếng Anh như trước.

## `GET /api/status`

```json
{
  "gtts": {
    "state": "closed",
    "consecutive_failures": 0,
    "seconds_until_retry": 0.0,
    "next_cooldown_seconds": 300,
    "budget_remaining": 18,
    "budget_per_minute": 20,
    "last_error": null
  },
  "cache": { "files": 12, "bytes": 148000 }
}
```

`state` là một trong `closed`, `open`, `half_open`.
