#!/usr/bin/env bash
# Build the web app as it ships and serve that build (§1001).
#
#   scripts/serve-built-web.sh [port]       # default 3200
#
# The browser suite runs against `next dev`, and a production build is not the
# same program: it has the Content-Security-Policy without dev's `eval` (§993),
# no hot reload, no Strict Mode double render, and timings `next dev` hides.
# §1000 was a routed module whose Preview lost its routing in a build and kept
# it under `next dev`, for as long as the suite had only run there.
#
# The build is copied out of `apps/web/.next` before it is served, so a dev
# server writing there afterwards (`scripts/dev-up.sh`) cannot change what this
# one serves. It proxies `/api` to API_ORIGIN (default http://localhost:8300),
# read at build time, as `next.config.mjs` says. Point the suite at it with
# ANCHOR_WEB_BASE=http://127.0.0.1:<port> ANCHOR_WEB_BUILD=production.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-3200}"
OUT="${ANCHOR_WEB_BUILD_DIR:-/tmp/anchor-web-build}"

( cd "$ROOT/apps/web" && npm run build --silent )
rm -rf "$OUT"
cp -r "$ROOT/apps/web/.next/standalone" "$OUT"
cp -r "$ROOT/apps/web/.next/static" "$OUT/apps/web/.next/static"
cp -r "$ROOT/apps/web/public" "$OUT/apps/web/public"

# Its own session, and none of this shell's descriptors: a CI step or a
# pipeline waits for every process holding its output, and would wait on the
# server for as long as it ran.
cd "$OUT/apps/web"
PORT="$PORT" HOSTNAME=127.0.0.1 setsid nohup node server.js \
  > "$OUT/server.log" 2>&1 < /dev/null &
cd "$ROOT"
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null "http://127.0.0.1:$PORT/login"; then
    echo "built web: http://127.0.0.1:$PORT (log: $OUT/server.log)"
    exit 0
  fi
  sleep 1
done
echo "the built web app did not answer on $PORT; its log:" >&2
tail -n 40 "$OUT/server.log" >&2
exit 1
