FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# sox để tăng tốc đọc cho gTTS (gTTS không có tham số tốc độ).
# Dùng sox chứ không dùng ffmpeg: cùng thuật toán WSOLA giữ nguyên cao độ,
# nhưng sox chỉ thêm ~12MB vào image còn ffmpeg thêm tới ~450MB.
RUN apt-get update \
 && apt-get install -y --no-install-recommends sox libsox-fmt-mp3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# COPY giữ nguyên mode của file nguồn. Ảnh chép từ project cũ có mode 640 nên
# container chạy non-root không đọc được -> StaticFiles gửi 200 + Content-Length
# rồi đóng kết nối không có thân phản hồi, và Cloudflare trả 520.
# Ép quyền đọc cho mọi user để lỗi đó không bao giờ tái diễn.
RUN chmod -R a+rX /app/app /app/static

EXPOSE 8000

# python:3.12-slim KHÔNG có curl lẫn wget, nên healthcheck phải viết bằng Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
