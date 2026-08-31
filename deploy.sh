#!/usr/bin/env bash
#
# Build lại image, khởi động lại service, chờ healthy rồi dọn image cũ.
#
# Cách dùng:
#   ./deploy.sh              build bình thường
#   ./deploy.sh --no-cache   build lại từ đầu, bỏ qua cache
#
# Máy này chạy nhiều project khác nhau, nên script chỉ xoá đúng image cũ của
# project này theo ID. KHÔNG bao giờ dùng `docker image prune` ở đây.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

IMAGE="langnghe:latest"
CONTAINER="langnghe"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!!  %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31mXX  %s\033[0m\n' "$*" >&2; exit 1; }

BUILD_ARGS=()
case "${1:-}" in
  --no-cache) BUILD_ARGS+=(--no-cache) ;;
  "")         ;;
  *)          die "Tham số không hiểu: $1 (chỉ nhận --no-cache)" ;;
esac

# ---- Chuẩn bị ----

[ -f .env ] || { log ".env chưa có, tạo từ .env.example"; cp .env.example .env; }

APP_PORT="$(sed -n 's/^APP_PORT=\([0-9]\+\).*/\1/p' .env | head -1)"
APP_PORT="${APP_PORT:-8010}"

OLD_IMAGE_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || true)"
OLD_SIZE="$(docker image ls "$IMAGE" --format '{{.Size}}' 2>/dev/null | head -1)"

# ---- Build và khởi động ----

log "Build image${BUILD_ARGS[*]:+ (${BUILD_ARGS[*]})}"
docker compose build "${BUILD_ARGS[@]}"

log "Khởi động lại service"
docker compose up -d

# ---- Chờ healthy ----

log "Chờ container healthy (tối đa ${HEALTH_TIMEOUT}s)"
deadline=$(( SECONDS + HEALTH_TIMEOUT ))
while :; do
  state="$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo missing)"
  [ "$state" = healthy ] && break

  if [ "$SECONDS" -ge "$deadline" ]; then
    warn "Container không healthy sau ${HEALTH_TIMEOUT}s (trạng thái: $state)"
    docker compose logs --tail 40
    [ -n "$OLD_IMAGE_ID" ] && warn "Image cũ vẫn còn để lùi lại: ${OLD_IMAGE_ID#sha256:}"
    die "Triển khai thất bại — image cũ KHÔNG bị xoá."
  fi
  sleep 2
done

log "Kiểm tra /healthz qua cổng ${APP_PORT}"
curl -fsS --max-time 10 "http://127.0.0.1:${APP_PORT}/healthz" || {
  docker compose logs --tail 40
  die "healthz không trả về 200 — image cũ KHÔNG bị xoá."
}
echo

# ---- Dọn image cũ ----

NEW_IMAGE_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}')"

if [ -z "$OLD_IMAGE_ID" ]; then
  log "Lần build đầu tiên, không có image cũ để xoá"
elif [ "$OLD_IMAGE_ID" = "$NEW_IMAGE_ID" ]; then
  log "Image không đổi, không có gì để xoá"
elif [ -n "$(docker ps -aq --filter "ancestor=$OLD_IMAGE_ID")" ]; then
  warn "Image cũ vẫn đang được một container khác dùng, giữ lại"
else
  log "Xoá image cũ ${OLD_IMAGE_ID#sha256:}"
  docker image rm "$OLD_IMAGE_ID" >/dev/null && echo "đã xoá"
fi

# ---- Tổng kết ----

DANGLING="$(docker image ls -qf dangling=true | wc -l)"

log "Xong"
printf 'image      : %s -> %s\n' "${OLD_SIZE:-(chưa có)}" "$(docker image ls "$IMAGE" --format '{{.Size}}' | head -1)"
printf 'phục vụ tại: http://127.0.0.1:%s\n' "$APP_PORT"
docker compose ps --format 'table {{.Name}}\t{{.Status}}'

if [ "$DANGLING" -gt 0 ]; then
  printf '\n'
  warn "Còn ${DANGLING} image dangling trên máy (có thể của project khác)."
  warn "Muốn xem thì chạy: docker image ls -f dangling=true"
fi
