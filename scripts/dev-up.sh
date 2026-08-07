#!/usr/bin/env bash
# Bring the local stack up: Postgres, the API on 8300, Next on 3100.
#
# Idempotent - each piece is started only if it is not already answering, so
# running this twice is not a way to end up with two of anything.
#
# The API is started with --tokens-file, which is how the browser suite (e2e/)
# authenticates. Scraping the token out of the API's stdout was the previous
# arrangement and it failed the first time a log was truncated, with the suite
# reporting twelve assertion failures rather than "there is no token".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ANCHOR_PYTHON:-$ROOT/.venv-api/bin/python}"
API_PORT="${ANCHOR_API_PORT:-8300}"
WEB_PORT="${ANCHOR_WEB_PORT:-3100}"
TOKENS_FILE="${ANCHOR_TOKENS_FILE:-/tmp/anchor-dev-tokens.json}"
LOG_DIR="${ANCHOR_LOG_DIR:-/tmp/anchor-dev}"
mkdir -p "$LOG_DIR"

export STORAGE_ROOT="${STORAGE_ROOT:-/tmp/anchor-storage}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://platform_app:devpass@localhost:5432/platform?sslmode=disable}"
export TEST_ADMIN_DSN="${TEST_ADMIN_DSN:-postgresql://platform:devpass@localhost:5432/platform?sslmode=disable}"
mkdir -p "$STORAGE_ROOT"

wait_for() {  # url, seconds, what
  for _ in $(seq "$2"); do
    if curl -sf -o /dev/null "$1" || curl -s -o /dev/null -w '%{http_code}' "$1" | grep -qE '^[2-4]'; then
      return 0
    fi
    sleep 1
  done
  echo "!! $3 did not come up; see $LOG_DIR" >&2
  return 1
}

# ---- Postgres ---------------------------------------------------------------
# Only started when a local cluster exists and is down. A managed or
# containerised Postgres elsewhere is left alone - DATABASE_URL decides what is
# actually used, and this script does not get to override that.
if ! pg_isready -q 2>/dev/null && [ -d /var/lib/postgresql/16/main ]; then
  # The log file has to be writable by the postgres user or pg_ctl fails before
  # it writes anything - which, with the output discarded, looked exactly like
  # "the server started and is slow", and cost twenty minutes the first time.
  # Nothing here is silenced: a start that fails says why.
  touch "$LOG_DIR/postgres.log"
  chown postgres "$LOG_DIR/postgres.log" 2>/dev/null || chmod 666 "$LOG_DIR/postgres.log"
  su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/16/main \
    -l $LOG_DIR/postgres.log \
    -o '-c config_file=/etc/postgresql/16/main/postgresql.conf' start" || true
  for _ in $(seq 20); do pg_isready -q 2>/dev/null && break; sleep 1; done
fi
if ! pg_isready -q 2>/dev/null; then
  echo "postgres is not reachable: $(pg_isready 2>&1)" >&2
  echo "the last few lines of $LOG_DIR/postgres.log:" >&2
  tail -5 "$LOG_DIR/postgres.log" >&2 2>/dev/null || true
  exit 1
fi
echo "postgres: $(pg_isready)"

# ---- API --------------------------------------------------------------------
if ! curl -s -o /dev/null "http://localhost:$API_PORT/api/health"; then
  rm -f "$TOKENS_FILE"
  # setsid so the server survives this script's shell exiting. Launching it
  # from a plain subshell looked fine and left a dead server behind.
  ( cd "$ROOT/apps/api" && setsid nohup "$PYTHON" dev_server.py \
      --port "$API_PORT" --tokens-file "$TOKENS_FILE" \
      > "$LOG_DIR/api.log" 2>&1 & )
  wait_for "http://localhost:$API_PORT/api/health" 40 "the API"
fi
echo "api:      http://localhost:$API_PORT/api/health -> $(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$API_PORT/api/health")"
echo "tokens:   $TOKENS_FILE"

# ---- web --------------------------------------------------------------------
if ! curl -s -o /dev/null "http://localhost:$WEB_PORT/login"; then
  ( cd "$ROOT/apps/web" && setsid nohup npx next dev -p "$WEB_PORT" \
      > "$LOG_DIR/web.log" 2>&1 & )
  wait_for "http://localhost:$WEB_PORT/login" 90 "the web app"
fi
echo "web:      http://localhost:$WEB_PORT/login -> $(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$WEB_PORT/login")"
