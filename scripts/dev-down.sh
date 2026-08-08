#!/usr/bin/env bash
# Stop what `dev-up.sh` started: the API on 8300 and Next on 3100.
#
#   scripts/dev-down.sh
#
# **Postgres is deliberately left running.** dev-up.sh only ever starts it on a
# machine where it found a local cluster stopped; everywhere else - Homebrew, a
# container, a managed instance - it belongs to the machine rather than to this
# repo, and a script that stops other people's databases because it once
# connected to one is not a script anybody should trust. Stop it the way you
# started it: `brew services stop postgresql@16`, `pg_ctl stop`, `docker stop`.
set -uo pipefail

API_PORT="${ANCHOR_API_PORT:-8300}"
WEB_PORT="${ANCHOR_WEB_PORT:-3100}"
TOKENS_FILE="${ANCHOR_TOKENS_FILE:-/tmp/anchor-dev-tokens.json}"

# **Whoever holds the port, plus whoever launched them.** Matching on the
# command line alone is not enough: `next dev -p 3100` spawns a child that
# renames itself to `next-server (v14.2.5)` and drops the port from its
# arguments entirely, so a pattern with the port in it finds the three
# launchers and misses the server actually serving. Going the other way -
# port only - leaves the npm launcher alive to be confusing later. Both, then.
listeners() {  # port
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null
  elif command -v ss >/dev/null 2>&1; then
    ss -lptnH "sport = :$1" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2
  fi
}

# Never `pkill -f`: `-f` matches any command line containing the pattern,
# including the shell that typed it. A plain `pkill -f` once killed the
# terminal running dev-up.sh, which reads as the machine hanging up on you
# rather than as a command doing its job. Own pid and parent excluded too.
stop() {  # port, launcher pattern, label
  local port="$1" pattern="$2" label="$3" pids=() pid seen=" "
  for pid in $(listeners "$port") $(pgrep -f "$pattern" 2>/dev/null || true); do
    case "$seen" in *" $pid "*) continue ;; esac
    seen="$seen$pid "
    if [ "$pid" != "$$" ] && [ "$pid" != "$PPID" ]; then pids+=("$pid"); fi
  done
  if [ ${#pids[@]} -eq 0 ]; then
    echo "$label: not running"
    return
  fi
  kill "${pids[@]}" 2>/dev/null || true
  # SIGTERM first, and a moment to take it. A dev server killed outright can
  # leave a half-written file or a lock behind, and the next `dev-up.sh` then
  # fails for a reason that has nothing to do with the next run.
  for _ in $(seq 20); do
    [ -z "$(listeners "$port")" ] && break
    sleep 0.25
  done
  if [ -n "$(listeners "$port")" ]; then
    kill -9 "${pids[@]}" 2>/dev/null || true
    echo "$label: stopped (forced)"
  else
    echo "$label: stopped"
  fi
}

stop "$API_PORT" "dev_server\.py --port $API_PORT" "api ($API_PORT)"
stop "$WEB_PORT" "next dev -p $WEB_PORT"           "web ($WEB_PORT)"

# The tokens are only valid for the process that minted them, so leaving the
# file behind is leaving something that looks usable and is not.
if [ -f "$TOKENS_FILE" ]; then
  rm -f "$TOKENS_FILE"
  echo "tokens: removed $TOKENS_FILE - they were only valid for that API process"
fi
echo "postgres: left running; it is not this repo's to stop"
