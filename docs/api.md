# API

| Endpoint | Mô tả |
|---|---|
| `GET /` | Giao diện |
| `GET /about`, `/about/` | Trang giới thiệu |
| `POST /api/tts` | `{"text": "..."}` → `{"text", "base64", "name"}` |
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
