#!/usr/bin/env bash
# Every check this repo has, in one command.
#
# Written as a script rather than as CI steps so that what runs locally and
# what runs in CI cannot drift: a workflow that inlines its own commands is a
# second copy of this file that nobody runs until it fails.
#
#   scripts/check.sh              # everything, e2e skipped if the stack is down
#   scripts/check.sh api          # just the API suite
#   scripts/check.sh worker       # just the worker suite
#   scripts/check.sh types        # just tsc
#   scripts/check.sh unit         # just the TypeScript unit tests
#   scripts/check.sh e2e          # just the browser suite
#
# `apps/control-plane/tests` is deliberately not here: it needs a second
# database nothing in this repo provisions, and pins httpx against apps/api's.
# `apps/api/tests/test_dependency_pins.py` holds that reason and goes red if a
# new suite is added without one - because until §263 the worker's 78 tests
# were absent from this file with no reason at all, and an absence explains
# nothing to the next person reading it.
#
# Exits non-zero on the first failure. Set ANCHOR_E2E_REQUIRED=1 to make a
# missing dev stack a failure rather than a skip - which is what CI wants,
# since there a missing stack is the bug.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${ANCHOR_PYTHON:-$ROOT/.venv-api/bin/python}"
WHICH="${1:-all}"
failed=()

export STORAGE_ROOT="${STORAGE_ROOT:-/tmp/anchor-storage}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://platform_app:devpass@localhost:5432/platform?sslmode=disable}"
export TEST_ADMIN_DSN="${TEST_ADMIN_DSN:-postgresql://platform:devpass@localhost:5432/platform?sslmode=disable}"
mkdir -p "$STORAGE_ROOT"

step() {  # name, then the command
  local name="$1"; shift
  echo
  echo "=== $name ==="
  if "$@"; then
    echo "--- $name: ok"
  else
    echo "--- $name: FAILED"
    failed+=("$name")
  fi
}

run_api()   { ( cd "$ROOT/apps/api" && "$PYTHON" -m pytest -q ); }

# **The worker suite gets its own database, and that is not a nicety** (§263).
# Its discovery functions are RLS-blind by design - `list_due_scheduled_syncs`
# sees every workspace, because a scoped connection could not find work in
# workspaces it does not know about - so a run against the shared dev database
# picks up and acts on whatever real source happens to be due. STATUS.md
# records that going wrong, with a sync failing on a storage path from a
# different run.
#
# Derived from `$TEST_ADMIN_DSN` through `packages/db/dsn.py` rather than
# assembled here, because that is the module whose whole point is that a DSN is
# parsed and not pattern-matched - and a second, shell-flavoured copy of the
# rule would be the mirror it exists to remove.
WORKER_DB="${ANCHOR_WORKER_DB:-platform_worker_test}"
# `+psycopg` is stripped on the way through: `$DATABASE_URL` is SQLAlchemy's
# form and the worker hands its DSN straight to psycopg, which cannot parse it.
worker_dsn() {  # role-carrying dsn -> the same, pointed at $WORKER_DB
  PYTHONPATH="$ROOT/packages/db" "$PYTHON" -c \
    'import sys; from dsn import for_database; print(for_database(sys.argv[1].replace("+psycopg", ""), sys.argv[2]))' \
    "$1" "$WORKER_DB"
}
run_worker() { (
  set -e
  admin="$(worker_dsn "$TEST_ADMIN_DSN")"
  app="$(worker_dsn "$DATABASE_URL")"
  # Created and migrated on demand: a suite that needs a schema and cannot make
  # one is a suite the next person will skip. `CREATE DATABASE` cannot run
  # inside a transaction, so it goes through psql-free psycopg in autocommit.
  PYTHONPATH="$ROOT/packages/db" "$PYTHON" -c '
import sys, psycopg
from dsn import for_database
admin, name = sys.argv[1], sys.argv[2]
with psycopg.connect(for_database(admin, "postgres"), autocommit=True) as conn:
    if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
        conn.execute(f"CREATE DATABASE {name}")
' "$admin" "$WORKER_DB"
  DATABASE_URL="$admin" PLATFORM_APP_PASSWORD="${PLATFORM_APP_PASSWORD:-devpass}" \
    "$PYTHON" "$ROOT/packages/db/migrate.py" >/dev/null
  cd "$ROOT/apps/worker"
  WORKER_DATABASE_URL="$app" TEST_ADMIN_DSN="$admin" \
    LOCAL_STORAGE_ROOT="${LOCAL_STORAGE_ROOT:-$STORAGE_ROOT/worker}" \
    "$PYTHON" -m pytest -q
); }
run_types() { ( cd "$ROOT/apps/web" && npx tsc --noEmit -p tsconfig.json ); }
# Pure functions only, and fast enough to be run on every save - see
# `apps/web/src/components/canvas/pure.ts` for why the boundary is drawn there.
run_unit()  { ( cd "$ROOT/apps/web" && npx vitest run ); }
# `-p no:randomly`-free and deliberately serial: these drive one dev stack, and
# two of them at once would each be seeding into the other's workspace.
run_e2e()   { ( cd "$ROOT/e2e" && "$PYTHON" -m pytest -q ); }

case "$WHICH" in
  api)    step "API tests" run_api ;;
  worker) step "Worker tests" run_worker ;;
  types)  step "TypeScript" run_types ;;
  unit)   step "TypeScript unit tests" run_unit ;;
  e2e)    step "Browser suite" run_e2e ;;
  all)
    # Cheapest first: a type error or a broken pure function should not cost
    # twelve minutes of browser time to find out about. The worker suite is
    # half a minute and sits above the API's seven, for the same reason.
    step "TypeScript" run_types
    step "TypeScript unit tests" run_unit
    step "Worker tests" run_worker
    step "API tests" run_api
    step "Browser suite" run_e2e
    ;;
  *) echo "unknown target '$WHICH' (api, worker, types, unit, e2e, all)" >&2; exit 2 ;;
esac

echo
if [ ${#failed[@]} -eq 0 ]; then
  echo "all checks passed"
else
  echo "FAILED: ${failed[*]}"
  exit 1
fi
