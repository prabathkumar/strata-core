#!/usr/bin/env bash
# Build and run the orders service as a container image, with no registry.
#
# The Dockerfile at the repo root is the real one: two stages, a Debian base,
# apt for the toolchain. It needs to pull `debian:bookworm-slim`, and this
# environment's egress policy refuses every container registry — so it is
# built by CI and not here.
#
# What this script does instead is buildable offline and proves the half that
# matters: the service, its data and the three libraries it links against are
# enough to serve. The binary is compiled on the host, the image is `FROM
# scratch`, and the container is asked for a page.
#
# It found one thing the Dockerfile could not: `docker logs` was empty. A C
# program whose stdout is a pipe gets a block buffer, so the line the service
# prints at startup never left libc. The runtime preamble line-buffers now.
#
# Usage:  deploy/build_scratch_image.sh [port]
set -euo pipefail

PORT="${1:-18080}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/apps/orders"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "[1/4] compiling the service"
mkdir -p "$APP/build"
( cd "$APP" && python3 "$ROOT/bootstrap/stage0.py" src/main.sta -o build/orders >/dev/null )

echo "[2/4] collecting what it links against"
mkdir -p "$STAGE/app" "$STAGE/lib64"
cp "$APP/build/orders" "$STAGE/app/orders"
cp -r "$APP/data" "$STAGE/app/data"
# Whatever ldd reports, rather than a list written down once and left to rot.
while read -r _ _ path _; do
    [ -f "${path:-}" ] || continue
    mkdir -p "$STAGE$(dirname "$path")"
    cp -L "$path" "$STAGE$path"
done < <(ldd "$APP/build/orders" | grep '=>')
loader="$(ldd "$APP/build/orders" | awk '/ld-linux/ {print $1}')"
[ -n "$loader" ] && { mkdir -p "$STAGE$(dirname "$loader")"; cp -L "$loader" "$STAGE$loader"; }

cat > "$STAGE/Dockerfile" <<'DOCKER'
FROM scratch
COPY lib /lib
COPY lib64 /lib64
COPY app /app
WORKDIR /app
EXPOSE 8080
CMD ["/app/orders"]
DOCKER

echo "[3/4] building the image"
docker build -q -t strata-orders:scratch "$STAGE" >/dev/null
docker images strata-orders:scratch --format '      {{.Repository}}:{{.Tag}}  {{.Size}}'

echo "[4/4] running it and asking for a page"
docker rm -f strata-orders-check >/dev/null 2>&1 || true
docker run -d --name strata-orders-check -p "$PORT:8080" strata-orders:scratch >/dev/null
trap 'docker rm -f strata-orders-check >/dev/null 2>&1 || true; rm -rf "$STAGE"' EXIT

for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/login"; then served=1; break; fi
    sleep 1
done
if [ "${served:-0}" != 1 ]; then
    echo "      the container did not serve /login"; docker logs strata-orders-check; exit 1
fi
curl -fsS "http://127.0.0.1:$PORT/login" | grep -q password \
    || { echo "      /login did not render the sign-in form"; exit 1; }
echo "      served /login"

logs="$(docker logs strata-orders-check 2>&1 | head -1)"
case "$logs" in
    *listening*) echo "      logged: $logs" ;;
    *) echo "      the service logged nothing — stdout is not line-buffered"; exit 1 ;;
esac
echo "OK — the image builds, serves and logs."
