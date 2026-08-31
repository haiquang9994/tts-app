FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# sox de tang toc doc cho gTTS (gTTS khong co tham so toc do).
# Dung sox chu khong dung ffmpeg: cung thuat toan WSOLA giu nguyen cao do,
# nhung sox chi them ~12MB vao image con ffmpeg them toi ~450MB.
RUN apt-get update \
 && apt-get install -y --no-install-recommends sox libsox-fmt-mp3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# COPY giu nguyen mode cua file nguon. Anh chep tu project cu co mode 640 nen
# container chay non-root khong doc duoc -> StaticFiles gui 200 + Content-Length
# roi dong ket noi khong co than phan hoi, va Cloudflare tra 520.
# Ep quyen doc cho moi user de loi do khong bao gio tai dien.
RUN chmod -R a+rX /app/app /app/static

EXPOSE 8000

# python:3.12-slim KHÔNG có curl lẫn wget, nên healthcheck phải viết bằng Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
