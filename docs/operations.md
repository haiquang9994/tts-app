# Vận hành

## Triển khai

```bash
./deploy.sh              # build lại và triển khai
./deploy.sh --no-cache   # build lại từ đầu
```

Script làm theo thứ tự, và thứ tự này là có chủ đích:

1. Ghi nhớ ID image hiện tại
2. `docker compose build` rồi `up -d`
3. Chờ container `healthy` (tối đa 120s)
4. Gọi thử `/healthz` qua đúng cổng đọc từ `.env`
5. **Chỉ khi cả hai bước trên xanh** mới xoá image cũ

Container không lên được thì script in log, **giữ nguyên image cũ** để lùi về, và thoát khác 0.

Máy chủ này chạy nhiều project khác nhau, nên script chỉ xoá đúng một ID — image cũ của project
này — và chỉ khi không container nào còn dùng. **Không bao giờ dùng `docker image prune`.**

## Đường đi của request

Domain đi qua Cloudflare Tunnel (container `cloudflared` chạy `network_mode: host`) trỏ thẳng vào
`http://localhost:8000`. Nginx **không** tham gia, nên đổi `APP_PORT` là đủ, không cần sửa gì trên
dashboard Cloudflare.

## Bốn cạm bẫy đã từng làm hỏng production

Mỗi cái đều đã có test hoặc cấu hình chặn tái diễn. Đừng gỡ chúng ra.

### 1. Tài nguyên tĩnh phải được gắn phiên bản

Cloudflare cache tài nguyên tĩnh 4 tiếng **và ghi đè header `Cache-Control` của origin** — đặt
`no-cache` cũng bị đổi thành `max-age=14400`, nên không thể dựa vào header để buộc làm mới.

Mọi đường dẫn tĩnh trong HTML được gắn `?v=<băm nội dung>` lúc khởi động (`_add_asset_versions`
trong `app/main.py`). Bỏ bước này thì sau mỗi lần deploy người dùng nhận HTML mới nhưng JS/CSS cũ,
hai bản lệch nhau và trang lỗi.

Băm theo nội dung nên URL chỉ đổi khi file thật sự đổi. Test: `tests/test_cache_busting.py`.

### 2. File tĩnh phải cho mọi user đọc được

Container chạy `user: "1001:33"`, còn `COPY` của Docker giữ nguyên mode file nguồn. Một file lỡ
mang mode 640 sẽ khiến StaticFiles gửi `200` kèm `Content-Length` rồi đóng kết nối **không có thân
phản hồi** — Cloudflare quy ra lỗi **520**.

Kiểu hỏng này rất dễ lọt: server dev chạy bằng chính user sở hữu file nên không tái hiện được, và
nó chỉ lộ ra khi fetch đúng file đó *từ trong container*. Dockerfile có `chmod -R a+rX`;
`tests/test_static_assets.py` kiểm bit quyền ngay từ working tree.

### 3. Không thêm `no-new-privileges` vào compose

Host bật AppArmor. `no_new_privs` chặn việc chuyển profile AppArmor lúc `exec`, làm **mọi** binary
trong container lỗi `operation not permitted`, kể cả `python` — container restart vô hạn.

Container vẫn được bảo vệ bằng profile AppArmor mặc định của Docker, chạy non-root, và chỉ bind
vào loopback.

### 4. `user: "1001:33"` phải khớp chủ sở hữu `cache/`

Trên máy này `ubuntu` là `uid=1001 gid=33(www-data)`, **không phải** `1000:1000` như mặc định
thường thấy. Sai uid thì container không ghi được cache.

## Chẩn đoán

```bash
curl -s localhost:8000/api/status | python3 -m json.tool   # cầu dao gTTS, cache
docker compose logs --tail 50
docker compose ps
```

`state` là `open` nghĩa là gTTS đang bị chặn hoặc hỏng liên tiếp, lưu lượng đang chạy qua
edge-tts. `budget_remaining` bằng 0 nghĩa là hết ngân sách chủ động — cũng dùng edge-tts, nhưng
cầu dao vẫn đóng và không phải sự cố.

Rate limit chỉ chặn được lạm dụng nếu `CF-Connecting-IP` tới nơi. Nếu ngờ nó không tới, hậu quả là
mọi người dùng chung một hạn mức thay vì mỗi người một hạn mức.

## Cloudflare Access

Tên miền công khai nằm sau **Cloudflare Access** với policy một người dùng. Gọi `curl` vào
`https://langnghe.hipingu.health` sẽ trả về trang đăng nhập của Cloudflare chứ không phải app —
**đó là đúng, không phải sự cố**.

Healthcheck của Docker và smoke test trong `deploy.sh` đều gọi `localhost:8000`, không đi qua
Cloudflare, nên Access không ảnh hưởng tới deploy.

Access chính là thứ khiến việc giữ một API key trả phí ở phía server trở nên an toàn. Trước khi
có nó, trang public đồng nghĩa với việc bất kỳ ai cũng tiêu được tiền của chủ sở hữu.

Đây là lớp chặn **truy cập**. Lớp chặn **chi phí** là `GEMINI_MAX_PER_DAY`, độc lập hoàn toàn —
xem [translation.md](translation.md).
