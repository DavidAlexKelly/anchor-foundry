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
#
#   scripts/dev-up.sh
#   scripts/dev-up.sh --extra-user 'sam@client.local:Sam Client:member'
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --extra-user) EXTRA+=(--extra-user "$2"); shift 2 ;;
    --extra-user=*) EXTRA+=(--extra-user "${1#*=}"); shift ;;
    *) echo "usage: dev-up.sh [--extra-user EMAIL:NAME:ROLE]..." >&2; exit 2 ;;
  esac
done
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

# **`setsid` is Linux-only.** macOS has no such command, so a line written as
# `setsid nohup ... &` there does not start a detached server - it fails with
# "setsid: command not found", into the log file, and the only thing the user
# sees is "the API did not come up". `nohup` alone is enough on macOS: the
# server is already in a background subshell whose parent exits, and nohup
# detaches it from the terminal. Resolved once, here, rather than at each of
# the two call sites.
#
# **`--fork` is what makes it actually detach**, and its absence cost real
# time. A script has job control off, so a backgrounded command stays in the
# shell's process group and is therefore *not* a group leader - and `setsid`
# only forks when its caller is one. Without the fork it `exec`s in place, so
# the server keeps the pid of the script's own child and the script sits in
# `wait` until the server exits, which for a dev server is never.
#
# Interactively nobody notices: the shell is a tty, the prompt comes back.
# Piped, it is minutes of nothing - `dev-up.sh | tail` prints not one line
# until the pipe closes, and the pipe cannot close while a child holds it. A
# 20-hour-old `dev-up.sh` was still parked in `do_wait` when this was found.
# Anything driving the repo without a terminal - CI, an agent, a Makefile -
# hits it on every run that has to start a server.
if command -v setsid >/dev/null 2>&1; then DETACH=(setsid --fork nohup); else DETACH=(nohup); fi

wait_for() {  # url, seconds, what, logfile
  for _ in $(seq "$2"); do
    if curl -sf -o /dev/null "$1" || curl -s -o /dev/null -w '%{http_code}' "$1" | grep -qE '^[2-4]'; then
      return 0
    fi
    sleep 1
  done
  # **Print the log, do not point at it.** "did not come up; see $LOG_DIR" is a
  # sentence that makes the reader do the work, and the answer is almost always
  # in the last few lines - a missing command, a refused connection, a
  # traceback. A server that failed to start already knows why.
  echo "!! $3 did not come up. The last 20 lines of ${4:-$LOG_DIR/*.log}:" >&2
  if [ -n "${4:-}" ] && [ -s "$4" ]; then
    sed 's/^/   | /' "$4" | tail -20 >&2
  else
    echo "   | (the log is empty, which usually means the process never started)" >&2
  fi
  return 1
}

# ---- Postgres ---------------------------------------------------------------
# Only started when a local cluster exists and is down. A managed or
# containerised Postgres elsewhere is left alone - DATABASE_URL decides what is
# actually used, and this script does not get to override that.
# **Probe the DSN the app will actually use, not the default socket.** Bare
# `pg_isready` asks a local Unix socket; a Postgres in a container - which is
# how CI runs it - answers on TCP. The bare probe reported "no response" for a
# database that was up and reachable, and the script then refused to start
# anything. libpq does not know SQLAlchemy's `+psycopg`, so it comes off first.
PROBE_DSN="${DATABASE_URL/+psycopg/}"
ready() { pg_isready -q -d "$PROBE_DSN" 2>/dev/null; }

if ! ready && [ -d /var/lib/postgresql/16/main ]; then
  # The log file has to be writable by the postgres user or pg_ctl fails before
  # it writes anything - which, with the output discarded, looked exactly like
  # "the server started and is slow", and cost twenty minutes the first time.
  # Nothing here is silenced: a start that fails says why.
  touch "$LOG_DIR/postgres.log"
  chown postgres "$LOG_DIR/postgres.log" 2>/dev/null || chmod 666 "$LOG_DIR/postgres.log"
  su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/16/main \
    -l $LOG_DIR/postgres.log \
    -o '-c config_file=/etc/postgresql/16/main/postgresql.conf' start" || true
fi
# Waited for either way: a managed or containerised Postgres this script did not
# start still has to be *up* before anything else is worth trying.
for _ in $(seq 30); do ready && break; sleep 1; done
if ! ready; then
  echo "postgres is not reachable at ${PROBE_DSN%%\?*}: $(pg_isready -d "$PROBE_DSN" 2>&1)" >&2
  tail -5 "$LOG_DIR/postgres.log" >&2 2>/dev/null || true
  exit 1
fi
echo "postgres: $(pg_isready -d "$PROBE_DSN")"

# ---- API --------------------------------------------------------------------
# **Extra users force a restart**, and this is not an optimisation detail worth
# hiding. `dev_server.py` generates its signing key at startup, so only the
# running process can mint a token it will accept — seeding a user against the
# database while that process runs creates a user with no usable token, and the
# symptom is a login box that rejects a token that was just printed. Restarting
# is the only arrangement where "I asked for this user" and "I can sign in as
# them" are the same sentence.
if [ ${#EXTRA[@]} -gt 0 ] && curl -s -o /dev/null "http://localhost:$API_PORT/api/health"; then
  echo "restarting the API to seed ${#EXTRA[@]} extra user(s) and mint their tokens"
  # **Not `pkill -f`.** That pattern matches any command line containing it,
  # including the shell that typed it — a plain `pkill -f` here killed the
  # terminal that ran this script, which reads as the machine hanging up on
  # you. Own pid and parent excluded for the same reason.
  for pid in $(pgrep -f "dev_server\.py --port $API_PORT" || true); do
    if [ "$pid" != "$$" ] && [ "$pid" != "$PPID" ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for _ in $(seq 20); do
    curl -s -o /dev/null "http://localhost:$API_PORT/api/health" || break
    sleep 0.5
  done
fi

if ! curl -s -o /dev/null "http://localhost:$API_PORT/api/health"; then
  rm -f "$TOKENS_FILE"
  # Detached so the server survives this script's shell exiting. Launching it
  # from a plain subshell looked fine and left a dead server behind.
  ( cd "$ROOT/apps/api" && "${DETACH[@]}" "$PYTHON" dev_server.py \
      --port "$API_PORT" --tokens-file "$TOKENS_FILE" "${EXTRA[@]+"${EXTRA[@]}"}" \
      < /dev/null > "$LOG_DIR/api.log" 2>&1 & )
  wait_for "http://localhost:$API_PORT/api/health" 40 "the API" "$LOG_DIR/api.log"
fi
echo "api:      http://localhost:$API_PORT/api/health -> $(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$API_PORT/api/health")"
echo "tokens:   $TOKENS_FILE"
if [ -f "$TOKENS_FILE" ]; then
  echo "users:    $("$PYTHON" -c 'import json,sys; print(", ".join(sorted(json.load(open(sys.argv[1])))))' "$TOKENS_FILE")"
fi

# ---- web --------------------------------------------------------------------
if ! curl -s -o /dev/null "http://localhost:$WEB_PORT/login"; then
  ( cd "$ROOT/apps/web" && "${DETACH[@]}" npx next dev -p "$WEB_PORT" \
      < /dev/null > "$LOG_DIR/web.log" 2>&1 & )
  wait_for "http://localhost:$WEB_PORT/login" 90 "the web app" "$LOG_DIR/web.log"
fi
echo "web:      http://localhost:$WEB_PORT/login -> $(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$WEB_PORT/login")"
