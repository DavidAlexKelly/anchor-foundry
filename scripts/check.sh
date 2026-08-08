#!/usr/bin/env bash
# Every check this repo has, in one command.
#
# Written as a script rather than as CI steps so that what runs locally and
# what runs in CI cannot drift: a workflow that inlines its own commands is a
# second copy of this file that nobody runs until it fails.
#
#   scripts/check.sh              # everything, e2e skipped if the stack is down
#   scripts/check.sh api          # just the API suite
#   scripts/check.sh types        # just tsc
#   scripts/check.sh e2e          # just the browser suite
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
run_types() { ( cd "$ROOT/apps/web" && npx tsc --noEmit -p tsconfig.json ); }
# `-p no:randomly`-free and deliberately serial: these drive one dev stack, and
# two of them at once would each be seeding into the other's workspace.
run_e2e()   { ( cd "$ROOT/e2e" && "$PYTHON" -m pytest -q ); }

case "$WHICH" in
  api)   step "API tests" run_api ;;
  types) step "TypeScript" run_types ;;
  e2e)   step "Browser suite" run_e2e ;;
  all)
    step "API tests" run_api
    step "TypeScript" run_types
    step "Browser suite" run_e2e
    ;;
  *) echo "unknown target '$WHICH' (api, types, e2e, all)" >&2; exit 2 ;;
esac

echo
if [ ${#failed[@]} -eq 0 ]; then
  echo "all checks passed"
else
  echo "FAILED: ${failed[*]}"
  exit 1
fi
