#!/usr/bin/env bash
# The browser suite against a database that was created a minute ago.
#
#   scripts/fresh-e2e.sh                    # the whole suite
#   scripts/fresh-e2e.sh test_timeline.py   # arguments go straight to pytest
#   ANCHOR_KEEP_DB=1 scripts/fresh-e2e.sh   # leave the database behind to poke at
#
# **Why this exists, and it is not a convenience.** §271 found the browser job
# red on `main` at ten consecutive merges with an identical 28-failure set,
# none of which reproduced locally. The difference was not the code and not the
# machine: this repo's dev Postgres has been accumulating since §248 and its
# ontology queries are warm, while CI creates its database at the top of every
# run. Every one of the 28 was a *one-shot read of a collection that starts
# empty* - `all_text_contents`, `evaluate_all`, `get_attribute`, `.all()`, none
# of which retry - and against warm data the collection was always already
# there. `scripts/check.sh e2e` runs against whatever the stack is up on, which
# is the accumulated database, which is why the local gate stayed green through
# all ten.
#
# So the state of the database is part of this suite's test environment, and
# this script is the only way to run it in the environment CI actually has.
# Run it before merging anything the browser suite covers.
#
# It is deliberately *not* what `check.sh e2e` does. That target drives a stack
# somebody else started and must not take it away from them; this one owns the
# whole thing, start to finish, and puts it back.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ANCHOR_PYTHON:-$ROOT/.venv-api/bin/python}"

# The prefix is load-bearing: the teardown refuses to drop a name that does not
# start with it, so a mistyped or inherited value cannot take the dev database
# with it. The pid keeps two concurrent runs apart.
PREFIX="anchor_freshe2e"
DB="${PREFIX}_$$"
ADMIN_BASE="${TEST_ADMIN_DSN:-postgresql://platform:devpass@localhost:5432/platform?sslmode=disable}"
APP_BASE="${DATABASE_URL:-postgresql+psycopg://platform_app:devpass@localhost:5432/platform?sslmode=disable}"

# Derived through `packages/db/dsn.py` rather than by string surgery, for the
# reason that module exists: `.replace("/platform?", ...)` returns its input
# when it does not match, and a DSN that silently did not change points every
# statement at the shared database. §263 hit that twice.
#
# The scheme is put back rather than assumed, because the two callers want
# different ones and both are right: `migrate.py` and psycopg take
# `postgresql://` and reject SQLAlchemy's driver suffix outright, while the API
# is handed `postgresql+psycopg://`. `for_database` parses libpq's form, so the
# suffix comes off on the way in and back on on the way out - in one place,
# rather than at each call site with a `sed`.
dsn_for() {  # a role-carrying dsn -> the same one, pointed at $DB
  PYTHONPATH="$ROOT/packages/db" "$PYTHON" -c '
import sys
from dsn import for_database
raw, name = sys.argv[1], sys.argv[2]
scheme, _, rest = raw.partition("://")
out = for_database(f"postgresql://{rest}", name)
print(out if scheme == "postgresql"
      else out.replace("postgresql://", f"{scheme}://", 1))
' "$1" "$DB"
}

ADMIN="$(dsn_for "$ADMIN_BASE")" || exit 1
APP="$(dsn_for "$APP_BASE")" || exit 1
# A dataset written by one run must not be visible to the next, or the storage
# layer becomes the warm thing the database no longer is.
STORE="${ANCHOR_LOG_DIR:-/tmp/anchor-dev}/fresh-storage-$$"

sql() {  # a statement against the `postgres` database, outside a transaction
  PYTHONPATH="$ROOT/packages/db" "$PYTHON" -c '
import sys, psycopg
from dsn import for_database
with psycopg.connect(for_database(sys.argv[1], "postgres"), autocommit=True) as conn:
    conn.execute(sys.argv[2])
' "$ADMIN" "$1"
}

TORN=""
teardown() {
  local code=$?
  # **On Ctrl-C both traps fire**: INT runs this, which exits, which fires EXIT,
  # which runs it again - a second dev-down/dev-up pair over a stack that is
  # already back, and a second DROP against a database that is already gone.
  # Harmless today and exactly the kind of thing that stops being harmless.
  [ -n "$TORN" ] && exit "$code"
  TORN=1
  echo
  echo "=== putting the stack back ==="
  "$ROOT/scripts/dev-down.sh" >/dev/null 2>&1
  rm -rf "$STORE"
  if [ "${ANCHOR_KEEP_DB:-}" = "1" ]; then
    echo "kept: $DB (ANCHOR_KEEP_DB=1)"
  else
    # The guard is the point. A `DROP DATABASE` in a teardown is one bad
    # variable away from taking the dev sandbox, and "$DB was empty anyway" is
    # not a thing this script can know.
    case "$DB" in
      "$PREFIX"_*) sql "DROP DATABASE IF EXISTS $DB WITH (FORCE)" >/dev/null 2>&1 || true ;;
      *) echo "refusing to drop '$DB': not one of ours" >&2 ;;
    esac
  fi
  # Back on the database the developer was using, because leaving somebody's
  # stack down is a worse outcome than any result this script can report.
  "$ROOT/scripts/dev-up.sh" >/dev/null 2>&1 \
    && echo "stack: back up on the default database" \
    || echo "!! the stack did not come back up; run scripts/dev-up.sh" >&2
  exit "$code"
}

echo "=== a database that did not exist a moment ago ==="
echo "db:       $DB"
sql "CREATE DATABASE $DB" || { echo "could not create $DB" >&2; exit 1; }
trap teardown EXIT INT TERM

DATABASE_URL="$ADMIN" PLATFORM_APP_PASSWORD="${PLATFORM_APP_PASSWORD:-devpass}" \
  "$PYTHON" "$ROOT/packages/db/migrate.py" >/dev/null \
  || { echo "migrations failed against $DB" >&2; exit 1; }

echo
echo "=== the stack, on it ==="
# Down first: `dev-up.sh` is idempotent by *not* restarting what is already
# answering, so a running API would keep the database it was started with and
# the whole run would silently be the thing this script exists to avoid.
"$ROOT/scripts/dev-down.sh" >/dev/null 2>&1
mkdir -p "$STORE"
DATABASE_URL="$APP" TEST_ADMIN_DSN="$ADMIN" STORAGE_ROOT="$STORE" \
  "$ROOT/scripts/dev-up.sh" || exit 1

echo
echo "=== the browser suite ==="
# `-ra` for the same reason `check.sh e2e` passes it: the teardown below prints
# after this, so the failing test names have to be the last thing pytest says
# or they scroll past whoever is reading.
( cd "$ROOT/e2e" && DATABASE_URL="$APP" TEST_ADMIN_DSN="$ADMIN" STORAGE_ROOT="$STORE" \
    ANCHOR_E2E_REQUIRED=1 "$PYTHON" -m pytest -q -ra "$@" )
