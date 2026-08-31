# Dịch sang tiếng Việt

Nút **"Dịch"** biến đổi ô nhập tại chỗ, giống nút "Xuống dòng": dán đoạn tiếng Anh, bấm Dịch, ô
nhập thành tiếng Việt, mọi thứ phía sau chạy y như cũ.

Cách gắn này là có chủ đích. Dịch **không** nằm trong luồng TTS, nên `text.py`, cache audio và
hàng đợi không hề thay đổi, và một sự cố ở phía dịch không thể chạm tới giọng đọc chính.

## Vì sao là MyMemory

Đo tháng 8/2026, từ chính máy chủ này:

| Nhà cung cấp | Kết quả |
|---|---|
| Google `translate_a/single`, `client=gtx` | 429 ngay lời gọi đầu tiên |
| Google `translate_a/single`, `client=at` | chạy được ~20 lời gọi rồi 429, sau 20 phút vẫn chặn |
| Bing `ttranslatev3` | lấy được token nhưng POST trả 401 — cơ chế chống lạm dụng đã đổi |
| Lingva (3 instance công khai) | cả ba trả 500 |
| Argos tự host, mô hình `en→vi` | chạy được, nhưng phá định danh (xem dưới) |
| **MyMemory** | **chạy được, không cần key** |

Endpoint dịch miễn phí chặt hơn endpoint TTS rất nhiều. Quan trọng hơn: dịch qua Google nghĩa là
chung IP với gTTS, nên một lần bị chặn sẽ mất **cả bản dịch lẫn giọng đọc chính**. MyMemory tách
được rủi ro đó.

Argos tự host miễn phí vĩnh viễn và rất nhanh (0,1 giây), nhưng phá đúng thứ cần giữ —
`MAX_WORDS_PER_LINE` thành `MAX_WORDS_IE`, `gTTS` thành "hệ thống DTTS", `Cloudflare` thành "Bộ
nhớ tạm đám mây" — và cộng thêm ~310MB vào image. Bị loại vì lý do chất lượng, không phải dung
lượng.

## Bọc token trông như code

Mọi máy dịch thống kê đều thiếu khái niệm "token này là code". Các lỗi đo được:

```
single-flight   ->  "một chuyến bay"
POST /api/tts   ->  "BÀI /api/tts"
Docker COPY     ->  "BẢN SAO Docker"
world-readable  ->  "đọc được trên toàn thế giới"
markdown        ->  "điểm đánh dấu"
"requests"      ->  "yêu cầu"
```

**Danh sách từ khoá không chữa được chuyện này.** `POST`, `COPY`, `static` là từ tiếng Anh bình
thường; chỉ ngữ cảnh mới biến chúng thành thuật ngữ. Muốn phủ hết thì danh sách phải vô hạn.

Nên `app/translate.py` nhận diện theo **hình dạng token**: cái gì trông như code thì thay bằng
giữ chỗ, dịch xong trả lại. Cách này bắt được cả định danh chưa từng gặp.

| Mẫu | Ví dụ bắt được |
|---|---|
| đoạn trong backtick | `` `npm install` `` |
| có dấu gạch chéo | `static/`, `/api/tts` |
| cờ dòng lệnh | `--no-cache` |
| có dấu chấm | `tts.py`, `aiohttp.ClientError` |
| snake_case | `strip_markdown`, `MAX_WORDS_PER_LINE` |
| camelCase | `updateButtons` |
| PascalCase nội hoa | `StaticFiles` |
| tên header | `Content-Length` |
| ALL CAPS | `POST`, `COPY`, `HTTP` |

Còn lại một danh sách nhỏ trong `TERMS` cho thứ **không** nhận ra được bằng hình dạng: từ viết
thường hoặc chỉ hoa chữ đầu như `world-readable`, `single-flight`, `container`, `Cloudflare`,
`sox`. Mỗi mục ở đó là một lỗi đã đo được, không phải phòng xa.

`cache` cố ý **không** nằm trong `TERMS`: máy dịch trả "bộ nhớ cache" vốn đã đúng, bọc thêm chỉ
tăng nguy cơ giữ nguyên tiếng Anh ở chỗ đáng ra nên dịch. Đây là ranh giới chung của cả project —
chỉ can thiệp vào thứ đo được là hỏng.

## Hai cái bẫy đã sập

**Giữ chỗ bọc chồng lên chính nó.** Ban đầu các mẫu được áp lần lượt bằng nhiều lời gọi `re.sub`.
Giữ chỗ dạng `XQ0QX` khớp luôn mẫu ALL-CAPS, nên lượt sau bọc lại giữ chỗ của lượt trước và khôi
phục dở dang — văn bản trả về còn sót `XQ0QX`. Sửa bằng cách gộp thành **một** biểu thức, quét
**một** lượt, và đặt giữ chỗ ở dạng chữ thường `zq0qz` để không khớp mẫu nào.
Khoá bởi `test_placeholder_is_not_protected_again`.

**Giới hạn 500 ký tự.** MyMemory trả `403 QUERY LENGTH LIMIT EXCEEDED` cho truy vấn dài hơn 500
ký tự. `split_chunks` cắt theo ranh giới câu ở ngưỡng 470, chỉ cắt cứng khi bản thân một câu đã
dài hơn thế — cắt cứng giữa câu làm máy dịch mất ngữ cảnh và ghép lại nghe rất gượng.

## Khi bản dịch hỏng

Nếu một giữ chỗ biến mất khỏi kết quả, đoạn đó bị coi là hỏng và **giữ nguyên tiếng Anh**, vì câu
thiếu định danh còn tệ hơn câu chưa dịch. Nếu MyMemory hỏng hẳn hoặc hết hạn mức, endpoint trả
`503` và giao diện giữ nguyên văn bản gốc — người dùng vẫn nghe được bản tiếng Anh.

## Dữ liệu gửi ra ngoài

MyMemory là dịch vụ **đặt trên internet**, không tự host: mỗi lần bấm "Dịch", container gọi
HTTPS ra `api.mymemory.translated.net`. Không cần mở thêm gì ở hạ tầng — container vốn đã gọi ra
ngoài cho gTTS và edge-tts.

Đây là một **bộ nhớ dịch dùng chung, công khai** theo đúng thiết kế: phản hồi trả về cả các đoạn
do người dùng khác đóng góp, kèm id thật. Chưa kiểm chứng được là truy vấn qua API có bị thêm vào
bộ nhớ chung hay không, nhưng với tài liệu nội bộ thì nên coi như **nội dung rời khỏi máy chủ và
không lấy lại được**.

Giảm nhẹ đáng kể: `protect()` chạy **trước** khi gọi mạng, nên thứ thực sự gửi đi là bản đã che.
Tên hàm, đường dẫn, tên file và định danh nội bộ — phần nhận dạng được hệ thống — không bao giờ
rời khỏi máy chủ; chỉ phần văn xuôi đi ra.

```
gửi đi:      Request flow for zq0qz: rate limit by zq1qz, then length check...
không gửi:   POST /api/tts, strip_markdown, Synthesizer.get_audio, static/
```

## Chất lượng thực tế

Đo trên chính `CLAUDE.md` của project. Có lớp bọc thì **toàn bộ định danh được giữ**, và chuỗi
lập luận — câu điều kiện, quan hệ nhân quả, mệnh đề đối lập — qua đúng. Cái còn kém một bản dịch
bằng LLM là **hành văn**: "on purpose" ra "về mục đích" thay vì "một cách có chủ đích".

Đủ để đọc một tài liệu thiết kế và đánh giá thiết kế đó có ổn không. Không đủ để làm bản dịch
chính thức.
