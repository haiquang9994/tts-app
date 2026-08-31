# Frontend

`static/app.js` — JS thuần, không build step, không `node_modules`. Toàn bộ trạng thái nằm ở
`localStorage`, server không biết gì về hàng đợi.

## Hàng đợi

`RunAudio` chạy một vòng `setInterval` 500ms làm hai việc mỗi nhịp:

- **`prefetch`** — lấy dòng đầu hàng đợi, gọi `/api/tts`, đẩy kết quả vào `base64_items`. Giữ sẵn
  tối đa 3 mục để phát liên tục không bị khựng.
- **`play_next`** — nếu chưa có audio nào đang phát thì lấy mục đầu ra phát.

Hai khoá `localStorage`: `__queue_texts__` (dòng chờ xử lý) và `__base64_items__` (audio đã sẵn
sàng). Câu đang xử lý được lưu kèm hàng đợi, nên đóng tab giữa chừng không mất nội dung.

Vòng lặp 500ms có nhược điểm là hao pin trên điện thoại. Viết lại theo hướng event-driven là việc
cố ý để lại cho sau.

## Ràng buộc phải giữ

**Hiển thị text gốc, không phải bản đã chuẩn hoá.** `base64_items` lưu `text` là chuỗi người dùng
nhập, không phải `res.text` từ server. Chuẩn hoá chỉ phục vụ việc đọc.

**Không dùng lookbehind trong regex.** Safari dưới 16.4 không hỗ trợ `(?<=...)` và sẽ ném
`SyntaxError` lúc phân tích file, làm chết toàn bộ script. Dùng `match()` với biểu thức bắt cả dấu
câu thay cho `split()` có lookbehind.

**Đặt lại `loading` ở CẢ nhánh lỗi** (đang làm trong `.finally`). Bỏ sót nhánh đó thì một lần hỏng
là hàng đợi kẹt cứng vĩnh viễn.

**Phân biệt lỗi thử lại được với lỗi không.** `isRetryable`: `429`, `5xx` và lỗi mạng thì trả câu
về đầu hàng đợi rồi backoff — mất mạng không được phép nuốt mất nội dung người dùng đã nhập. Còn
`4xx` khác (`413`, `422`) thì bỏ câu đó đi, vì thử lại bao nhiêu lần cũng hỏng y như vậy và sẽ lặp
vô hạn.

**Bọc mọi lần đọc ghi `localStorage` trong `try/catch`.** Chế độ riêng tư hoặc trình duyệt chặn
lưu trữ sẽ làm nó ném lỗi.

**Escape HTML khi render.** Hàng đợi và danh sách đã sẵn sàng được ghi bằng `innerHTML`.

## Nút "Xuống dòng"

`autoWrap` gộp các câu liền nhau thành từng dòng, chỉ ngắt khi dòng vượt `MAX_WORDS_PER_LINE`
(50 từ) — không phải mỗi câu một dòng. Câu tự nó đã quá dài thì cắt tiếp ở dấu phẩy, cuối cùng mới
cắt cứng theo số từ. Xuống dòng có sẵn của người dùng được giữ nguyên.

Nút sửa thẳng nội dung trong ô nhập để người dùng xem lại và chỉnh trước khi thêm vào hàng đợi.

`autoWrap` được phơi ra `window.autoWrap` để kiểm thử tự động.

## Bộ lọc dòng

Trước khi gửi lên server, `prefetch` bỏ qua:

- Dòng không có chữ hay số nào (`/[a-zA-Z0-9]+/`)
- Dòng mở/đóng khối code (`isCodeFence`) — ` ```python ` *có* chữ nên lọt bộ lọc trên, lên tới
  server thì bị lọc sạch và trả `422`, làm nháy thông báo lỗi vô ích

## Kiểm thử

Không có test runner cho JS. Hai cách đang dùng:

```bash
node --check static/app.js     # kiểm tra cú pháp
```

Với `autoWrap`, trích phần thuật toán ra file tạm rồi chạy bằng node với bộ ca cụ thể — kiểm cả
"không dòng nào vượt giới hạn" lẫn "không mất chữ nào". Với luồng đầy đủ, lái Playwright vào
trang thật và kiểm tra `runAudio.queue_texts`, `runAudio.base64_items`, `runAudio.loading`.
