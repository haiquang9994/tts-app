# Dịch sang tiếng Việt

Nút **"Dịch"** biến đổi ô nhập tại chỗ, giống nút "Xuống dòng": dán đoạn tiếng Anh, bấm Dịch, ô
nhập thành tiếng Việt, mọi thứ phía sau chạy y như cũ.

Cách gắn này là có chủ đích. Dịch **không** nằm trong luồng TTS, nên `text.py`, cache audio và
hàng đợi không hề thay đổi, và một sự cố ở phía dịch không thể chạm tới giọng đọc chính.

Nhà cung cấp duy nhất là **Gemini**. Không có lớp dự phòng: hỏng thì trả `503` và giao diện giữ
nguyên văn bản gốc. Đó là lựa chọn có chủ đích — báo lỗi rõ ràng còn hơn lặng lẽ trả về bản dịch
kém hẳn mà người dùng tưởng là bản tốt.

## Vì sao phải là mô hình hiểu chỉ dẫn

Project từng dùng MyMemory (máy dịch thống kê miễn phí) và đã gỡ bỏ. Số đo giải thích vì sao —
cùng một đoạn trong `CLAUDE.md`:

| Gốc | Máy dịch thống kê | Gemini |
|---|---|---|
| `single-flight` | "một chuyến bay" | `single-flight` |
| `POST /api/tts` | "BÀI /api/tts" | `POST /api/tts` |
| `Docker COPY` | "BẢN SAO Docker" | `Docker COPY` |
| `world-readable` | "đọc được trên toàn thế giới" | quyền đọc cho mọi người (world-readable) |
| `on purpose` | "về mục đích" | một cách có chủ đích |

Gốc rễ: **máy dịch thống kê không có khái niệm "token này là code"**. Và một danh sách từ khoá
không chữa được, vì `POST`, `COPY`, `static` là từ tiếng Anh bình thường — chỉ ngữ cảnh mới biến
chúng thành thuật ngữ, nên danh sách phải vô hạn.

Chống đỡ chuyện đó từng cần cả một bộ máy: nhận diện token theo hình dạng rồi thay bằng giữ chỗ,
cắt đoạn ≤470 ký tự, tách dấu Markdown đầu đoạn, chạy song song, thử lại từng đoạn. Khoảng 300
dòng. Với một mô hình hiểu chỉ dẫn thì **toàn bộ chỗ đó thành một câu trong prompt**, và code
ngắn đi chứ không dài ra.

Các phương án khác đều đã đo và loại:

| Phương án | Kết quả |
|---|---|
| Google `translate_a/single` không chính thức | chặn IP máy chủ sau ~20 lời gọi, 20 phút sau vẫn chặn |
| Bing `ttranslatev3` | lấy được token nhưng POST trả 401 |
| Lingva (3 instance công khai) | cả ba trả 500 |
| Argos tự host (`en→vi`, 68MB) | nhanh 0,1s nhưng phá định danh: `MAX_WORDS_PER_LINE` → `MAX_WORDS_IE` |
| NLLB-200 tự host (2,3GB) | khá hơn Argos nhưng vẫn sai thuật ngữ, và chậm 3,4s/đoạn |
| MyMemory | chạy được, chất lượng ngang Google Dịch cũ — vẫn hỏng ~5% câu |

Tự host giải quyết trọn vẹn mọi vấn đề *vận hành* (không hạn mức, không chặn IP, dữ liệu không ra
ngoài) nhưng làm chất lượng **tệ đi**, vì mô hình chạy nổi trên CPU nhỏ hơn hẳn.

## Prompt là nơi chứa yêu cầu

Cả tài liệu đi trong **một** lời gọi. Không cắt nhỏ, vì hai lý do đo được:

* Cắt nhỏ làm system prompt (174 token) **lặp lại mỗi lời gọi**. Một tài liệu 40 dòng đọc hết thì
  đắt hơn **36%**.
* Số request tăng gấp 40, mà hạn mức Gemini tính theo **request mỗi ngày** — dịch từng dòng thì
  một tài liệu duy nhất cũng không xong nổi trong ngày ở gói free.

Nếu bỏ dở giữa chừng thì dịch từng dòng rẻ hơn, nhưng chênh lệch tuyệt đối chỉ khoảng
$0,0007/tài liệu. Không đáng đánh đổi lấy chất lượng và trần request.

Yêu cầu **chú giải song ngữ** — *"giới hạn tốc độ (rate limit)"* — là thứ kéo chất lượng lên
ngang bản dịch thủ công. Nó là PHONG CÁCH chứ không phải năng lực model, nên viết được thành chỉ
dẫn thay vì phải đổi model.

Đo được: 1,9 giây và ~$0,002 cho một lần dán 10.000 ký tự.

## Hai lớp phòng thủ độc lập

Key trả phí nằm ở server, nên phải có hai lớp khác nhau về bản chất:

* **Cloudflare Access** quyết định **ai vào được**. Xem [operations.md](operations.md).
* **`GEMINI_MAX_PER_DAY`** quyết định **tiêu được bao nhiêu**. Nó vẫn có tác dụng khi Access bị
  cấu hình sai, hoặc khi chính ta để một vòng lặp chạy hỏng.

Trần 50 lần/ngày ≈ $0,10/ngày là mức trần tuyệt đối. Đặt `0` là tắt hẳn Gemini mà không phải xoá
key.

Cố ý **không** dùng `ProviderGuard` của `tts.py`: cầu dao đó sinh ra để tránh bị Google chặn, còn
ở đây ta là khách trả tiền. Ngữ nghĩa "50 lần mỗi ngày" cũng rõ hơn hẳn một token bucket nhỏ giọt
theo giờ.

## Cache

Cache đĩa theo **cả tài liệu**, khoá gồm `GEMINI_VARIANT` và tên model — dán lại tài liệu cũ
không tốn xu nào, và **không ăn vào trần ngày**, vì ngân sách chỉ bị tiêu khi thật sự gọi ra
ngoài.

Bản dịch dùng chung thư mục và chung ngân sách `CACHE_MAX_MB` với audio, phân biệt bằng đuôi
`.txt` so với `.mp3`.

Bản hỏng **không** được cache — cache lại thì lần sau vẫn hỏng mà không còn cơ hội gọi lại.

Sửa prompt theo cách làm kết quả khác đi thì phải bump `GEMINI_VARIANT`. Đổi model thì không cần:
tên model đã nằm trong khoá.

## API key

`GEMINI_API_KEY` là secret **duy nhất** của project. URL gọi Gemini nhúng key ngay trong query
string, nên phần thân lỗi HTTP bị bỏ đi có chủ đích — nếu không, một lỗi 4xx sẽ ném key vào log.
Key cũng không bao giờ xuất hiện trong `/api/status`, khoá bởi `test_status_never_leaks_the_api_key`.

Key phải là **API key** lấy từ [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
bắt đầu bằng `AIza`. Token dạng `AQ.…` là credential tạm thời và sẽ hết hạn sau vài giờ, để lại
lỗi `401` khó đoán.
