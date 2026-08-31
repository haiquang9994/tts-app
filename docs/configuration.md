# Cấu hình

Toàn bộ qua biến môi trường, đọc trong `app/config.py` thành một `Settings` bất biến.
`.env.example` được commit; `.env` thì không.

`GEMINI_API_KEY` **là secret thật** và là secret duy nhất của project. Nó không bao giờ được ghi
ra log, không nằm trong thông báo lỗi (URL gọi Gemini có chứa key, nên phần thân lỗi HTTP bị bỏ
đi có chủ đích), và không xuất hiện trong `/api/status` — khoá bởi
`test_status_never_leaks_the_api_key`.

Key phải là **API key** lấy từ [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
bắt đầu bằng `AIza`. Token dạng `AQ.…` là credential tạm thời, hết hạn sau vài giờ và để lại lỗi
`401` khó đoán.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `APP_PORT` | `8010` | Cổng trên host mà compose map ra (chỉ compose dùng) |
| `TTS_RATE` | `+20%` | Tốc độ đọc của gTTS, **phải có dấu** (`+0%` chứ không phải `0%`) |
| `TTS_FALLBACK_VOICE` | `vi-VN-HoaiMyNeural` | Giọng edge-tts khi gTTS hỏng. Giọng nam là `vi-VN-NamMinhNeural` |
| `TTS_MAX_CONCURRENCY` | `4` | Số lời gọi TTS ra ngoài đồng thời tối đa |
| `TTS_TIMEOUT_SECONDS` | `30` | Timeout cho một lời gọi TTS |
| `MAX_TEXT_LENGTH` | `1000` | Giới hạn ký tự mỗi request |
| `RATE_LIMIT_PER_MINUTE` | `60` | Hạn mức mỗi IP |
| `MAX_TRANSLATE_LENGTH` | `10000` | Giới hạn ký tự mỗi lần dịch |
| `GEMINI_API_KEY` | rỗng | Bắt buộc để dịch. Để trống thì `/api/translate` trả `503` |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Model dịch |
| `GEMINI_MAX_PER_DAY` | `50` | Trần **chi phí** mỗi ngày; đặt `0` để tắt Gemini mà không xoá key |
| `GEMINI_TIMEOUT_SECONDS` | `60` | Timeout một lời gọi Gemini |
| `CACHE_DIR` | `mp3` | Thư mục cache |
| `CACHE_MAX_MB` | `512` | Vượt ngưỡng thì xoá dần file cũ nhất |
| `CACHE_CHECK_EVERY` | `50` | Số lần ghi giữa hai lần kiểm tra dung lượng cache |
| `LOG_LEVEL` | `INFO` | Mức log |
| `GTTS_MAX_PER_MINUTE` | `20` | Ngân sách gọi gTTS mỗi phút, hết thì dùng edge-tts |
| `GTTS_FAILURE_THRESHOLD` | `3` | Số lần hỏng liên tiếp trước khi mở cầu dao |
| `GTTS_COOLDOWN_SECONDS` | `300` | Khoảng nghỉ khi cầu dao mở |
| `GTTS_MAX_COOLDOWN_SECONDS` | `3600` | Trần của khoảng nghỉ sau khi nhân đôi nhiều lần |

Giá trị không phải số bị bỏ qua và lấy mặc định, thay vì làm app chết lúc khởi động.
`TTS_FALLBACK_VOICE` ngoài danh sách giọng cho phép cũng lùi về mặc định.

Biên độ dồn cụm của rate limit (`BURST` trong `app/limits.py`, giá trị 20) là hằng số trong code
chứ không đọc từ biến môi trường. Đáng nhớ khi thử nghiệm: đặt `RATE_LIMIT_PER_MINUTE=1` vẫn cho
20 request đầu lọt qua.

Cả tài liệu đi trong một lời gọi Gemini, mất khoảng 2 giây. Bản dịch được cache trên đĩa theo cả
tài liệu, dùng chung thư mục và chung ngân sách `CACHE_MAX_MB` với audio — dán lại tài liệu cũ
không tốn tiền và **không ăn vào `GEMINI_MAX_PER_DAY`**.
