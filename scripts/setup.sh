#!/usr/bin/env bash
# From a fresh checkout to a running stack you can sign into, in one command.
#
#   scripts/setup.sh              # asks before anything that costs time
#   scripts/setup.sh --defaults   # takes every default, asks nothing
#
# Every step is idempotent and checks before it acts, so this is also the
# right thing to run when you are not sure what state a machine is in - it
# reports what is already done rather than redoing it.
#
# What it does not do: install Postgres, Node or Python. Those are the machine's
# business and the ways to install them differ per machine; this script tells
# you what is missing and stops. Everything downstream of them it will do.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --defaults, or a pipe rather than a terminal. A prompt written to a
# non-terminal is a hang with no output, which is the worst way to fail; taking
# the defaults is at least a thing that finishes and says what it did.
INTERACTIVE=1
case "${1:-}" in
  "") ;;
  --defaults) INTERACTIVE=0 ;;
  *) sed -n '2,13p' "${BASH_SOURCE[0]}" | cut -c3-; exit 2 ;;
esac
[ -t 0 ] || INTERACTIVE=0

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; OFF=$'\033[0m'
[ -t 1 ] || { BOLD=""; DIM=""; RED=""; GREEN=""; OFF=""; }

step()  { echo; echo "${BOLD}==> $*${OFF}"; }
ok()    { echo "    ${GREEN}ok${OFF}  $*"; }
note()  { echo "    ${DIM}$*${OFF}"; }
die()   { echo; echo "${RED}!! $*${OFF}" >&2; exit 1; }

ask() {  # prompt, default -> echoes the answer
  local prompt="$1" default="$2" reply
  if [ "$INTERACTIVE" = 0 ]; then echo "$default"; return; fi
  read -r -p "    $prompt [$default]: " reply < /dev/tty
  echo "${reply:-$default}"
}

confirm() {  # prompt, default y|n -> returns 0 for yes
  local reply
  reply=$(ask "$1 (y/n)" "$2")
  [[ "$reply" =~ ^[Yy] ]]
}

# ---- 1. the things this script will not install for you ---------------------
step "Checking prerequisites"
missing=()
for cmd in python3 node npm psql pg_isready; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
[ ${#missing[@]} -eq 0 ] || die "not on PATH: ${missing[*]}
  psql/pg_isready come from a Postgres client install; node and npm from Node 20+.
  Install them and run this again - everything after this point is automatic."

PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info[:2] >= (3, 11) else 0)')
[ "$PY_OK" = 1 ] || die "Python 3.11 or newer is required; found $(python3 -V 2>&1)"
ok "$(python3 -V 2>&1), $(node -v), psql $(psql --version | awk '{print $3}')"

# ---- 2. Postgres ------------------------------------------------------------
step "Postgres"
PGHOST_="${PGHOST:-localhost}"
PGPORT_="${PGPORT:-5432}"

if ! pg_isready -q -h "$PGHOST_" -p "$PGPORT_" 2>/dev/null; then
  if [ -d /var/lib/postgresql/16/main ]; then
    note "a local cluster exists but is not running; starting it"
    mkdir -p /tmp/anchor-dev && touch /tmp/anchor-dev/postgres.log
    chown postgres /tmp/anchor-dev/postgres.log 2>/dev/null || chmod 666 /tmp/anchor-dev/postgres.log
    su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/16/main \
      -l /tmp/anchor-dev/postgres.log \
      -o '-c config_file=/etc/postgresql/16/main/postgresql.conf' start" || true
    for _ in $(seq 30); do pg_isready -q -h "$PGHOST_" -p "$PGPORT_" && break; sleep 1; done
  fi
fi
pg_isready -q -h "$PGHOST_" -p "$PGPORT_" 2>/dev/null \
  || die "no Postgres answering at $PGHOST_:$PGPORT_.
  Start one however this machine does it (a service, a container, Postgres.app),
  then run this again. Set PGHOST/PGPORT if it listens somewhere else."
ok "answering at $PGHOST_:$PGPORT_"

# ---- 3. role and database ---------------------------------------------------
step "Database and roles"
DB_NAME=$(ask "database name" "platform")
DB_OWNER=$(ask "owner role (migrations and seeding run as this)" "platform")
DB_PASSWORD=$(ask "password for both roles" "devpass")

# Whoever can already create roles. A machine where the current user is a
# superuser and one where only `postgres` is differ only here, so it is worth
# finding out rather than assuming, and saying which was used.
#
# **`-w` on every probe, and it is not optional.** Without it `psql` prompts for
# a password when the connection wants one, and a probe whose whole purpose is
# to answer "does this work" instead sits waiting for input — on a real
# terminal that is an indefinite hang partway through setup, with a bare
# "Password for user root:" and no explanation of what asked. With `-w` the
# probe fails, and the next candidate is tried.
ADMIN_ARGS=()
if psql -w -h "$PGHOST_" -p "$PGPORT_" -d postgres -Atqc 'SELECT 1' >/dev/null 2>&1; then
  ADMIN_ARGS=(-w -h "$PGHOST_" -p "$PGPORT_" -d postgres)
elif su postgres -c "psql -w -Atqc 'SELECT 1'" >/dev/null 2>&1; then
  ADMIN_ARGS=(SU)
else
  die "cannot connect to Postgres as a superuser to create the role and database.
  Either make your own account a superuser, or create them by hand:
    CREATE ROLE $DB_OWNER LOGIN PASSWORD '$DB_PASSWORD' CREATEDB CREATEROLE;
    CREATE DATABASE $DB_NAME OWNER $DB_OWNER;
  then run this again - it will see them and move on."
fi

admin_sql() {  # runs one statement as a superuser, whichever way works here
  if [ "${ADMIN_ARGS[0]}" = "SU" ]; then
    su postgres -c "psql -w -v ON_ERROR_STOP=1 -Atqc \"$1\""
  else
    psql "${ADMIN_ARGS[@]}" -v ON_ERROR_STOP=1 -Atqc "$1"
  fi
}

if [ "$(admin_sql "SELECT 1 FROM pg_roles WHERE rolname='$DB_OWNER'")" = "1" ]; then
  # **Set the password even when the role exists.** A role left over from an
  # earlier run with a different password is indistinguishable from a correct
  # one until the API fails to connect, three steps later, with an error that
  # names neither this script nor the password.
  admin_sql "ALTER ROLE $DB_OWNER LOGIN PASSWORD '$DB_PASSWORD' CREATEDB CREATEROLE" >/dev/null
  ok "role $DB_OWNER exists; password set to the one above"
else
  admin_sql "CREATE ROLE $DB_OWNER LOGIN PASSWORD '$DB_PASSWORD' CREATEDB CREATEROLE" >/dev/null
  ok "created role $DB_OWNER"
fi

# **The privilege `migrate.py` needs at its very last step.** It finishes by
# running `ALTER ROLE platform_app PASSWORD ...`, and since Postgres 16 that
# requires CREATEROLE *and* ADMIN OPTION on the role being altered. A machine
# where `platform_app` does not exist yet is fine - migration 0006 creates it,
# so the migrating role owns it. A machine where it already exists from an
# earlier setup under a different owner is not: every migration applies, and
# then the last statement fails with "permission denied to alter role", which
# reads like the whole run failed rather than like a grant is missing.
if [ "$(admin_sql "SELECT 1 FROM pg_roles WHERE rolname='platform_app'")" = "1" ]; then
  admin_sql "GRANT platform_app TO $DB_OWNER WITH ADMIN OPTION" >/dev/null \
    && ok "$DB_OWNER may set platform_app's password" \
    || note "could not grant ADMIN on platform_app to $DB_OWNER; migrations may fail at the last step"
fi

if [ "$(admin_sql "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")" = "1" ]; then
  ok "database $DB_NAME exists"
else
  admin_sql "CREATE DATABASE $DB_NAME OWNER $DB_OWNER" >/dev/null
  ok "created database $DB_NAME"
fi

# Two DSNs, and the difference between them is not cosmetic:
#   * ADMIN_DSN is plain libpq. `migrate.py` and `dev_server.py`'s seeding hand
#     it straight to psycopg, which does not understand SQLAlchemy's `+psycopg`
#     and fails with an unhelpful "invalid connection option".
#   * APP_DSN is the SQLAlchemy form, and connects as `platform_app` - a role
#     that *is* subject to row-level security. Running the app as the owner
#     would work and would silently disable every RLS policy in the schema.
ADMIN_DSN="postgresql://$DB_OWNER:$DB_PASSWORD@$PGHOST_:$PGPORT_/$DB_NAME?sslmode=disable"
APP_DSN="postgresql+psycopg://platform_app:$DB_PASSWORD@$PGHOST_:$PGPORT_/$DB_NAME?sslmode=disable"

# ---- 4. Python dependencies -------------------------------------------------
# **Before the migrations, not after.** `migrate.py` imports psycopg, which the
# system Python does not have; running it first fails with a ModuleNotFoundError
# that says nothing about setup order. The venv is a prerequisite of the schema,
# so it is built first.
step "Python dependencies"
VENV="$ROOT/.venv-api"
if [ ! -x "$VENV/bin/python" ]; then
  note "creating $VENV"
  python3 -m venv "$VENV" || die "could not create the virtualenv"
fi
# Compared against the pins rather than merely "is something installed". A venv
# that has drifted from requirements-dev.txt is the reason a whole session's
# test results once had to be thrown away: they had run against four packages
# at versions nobody had asked for.
if "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check \
     -r apps/api/requirements-dev.txt; then
  ok "installed to the pins in apps/api/requirements-dev.txt"
else
  die "pip install failed - see the output above"
fi

# ---- 5. migrations ----------------------------------------------------------
step "Schema"
# PLATFORM_APP_PASSWORD is the whole reason this cannot be a bare `migrate.py`.
# Migration 0006 creates `platform_app` with a placeholder password, because
# migrations are checksummed and immutable so a real password cannot live in
# one. Without this variable the role keeps the placeholder, and the API's very
# first connection fails authentication - a failure that looks like a bad DSN.
if ! PLATFORM_APP_PASSWORD="$DB_PASSWORD" DATABASE_URL="$ADMIN_DSN" \
     "$VENV/bin/python" packages/db/migrate.py; then
  die "migrations failed - see the output above. Nothing after this can work."
fi
ok "schema up to date, and platform_app's password matches"

# ---- 6. Node dependencies ---------------------------------------------------
step "Node dependencies"
# `node_modules/.package-lock.json` is npm's own record of what it installed,
# written at the end of a successful install. Comparing against it - rather than
# against the directory, whose timestamp any stray write bumps - is the
# difference between "npm has installed this lockfile" and "something exists".
if [ -f node_modules/.package-lock.json ] \
   && [ ! package-lock.json -nt node_modules/.package-lock.json ]; then
  ok "node_modules already matches package-lock.json"
elif npm ci --silent; then
  ok "npm ci"
else
  die "npm ci failed - see the output above"
fi

# ---- 7. the browser, which only the e2e suite needs -------------------------
step "Playwright browser"
# **Launched exactly the way the suite launches it**, by reading `CHROMIUM`
# from the suite's own conftest rather than by writing the rule a second time.
# The first version of this check did write it a second time - a bare
# `chromium.launch()` - and reported "not installed" on a machine with a
# perfectly good browser at `/opt/pw-browsers/chromium`, then spent two minutes
# failing to download a duplicate. A check that disagrees with the thing it
# checks is worse than no check.
if "$VENV/bin/python" -c "
import sys; sys.path.insert(0, 'e2e')
from conftest import CHROMIUM
import os
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    p.chromium.launch(**({'executable_path': CHROMIUM} if os.path.exists(CHROMIUM) else {})).close()
" 2>/dev/null; then
  ok "chromium launches the way e2e/conftest.py launches it"
elif confirm "Chromium is not installed. Install it (~150MB, only the browser suite needs it)?" y; then
  "$VENV/bin/playwright" install chromium || note "install failed; scripts/check.sh e2e will not run"
else
  note "skipped - scripts/check.sh will skip the browser suite"
fi

# ---- 8. who you want to sign in as ------------------------------------------
step "Test users"
note "Four always exist: owner@ and admin@ and editor@ and viewer@acme.dev.local."
note "Add your own to try the product as somebody who is not one of those."
EXTRA=()
if [ "$INTERACTIVE" = 1 ]; then
  while true; do
    email=$(ask "extra user's email (blank to finish)" "")
    [ -z "$email" ] && break
    if [[ "$email" != *@* ]]; then note "that does not look like an email address"; continue; fi
    name=$(ask "  display name" "${email%%@*}")
    role=$(ask "  org role: owner, admin or member" "member")
    case "$role" in
      owner|admin|member) ;;
      *) note "org role must be owner, admin or member; skipping $email"; continue ;;
    esac
    if [ "$role" = "member" ]; then
      # Asked separately because it is separate. An org member with no
      # workspace role can sign in and see nothing at all, which looks like a
      # broken install rather than a permission boundary.
      ws_role=$(ask "  workspace role: admin, editor or viewer" "editor")
      case "$ws_role" in
        admin|editor|viewer) ;;
        *) note "workspace role must be admin, editor or viewer; skipping $email"; continue ;;
      esac
      EXTRA+=(--extra-user "$email:$name:$role:$ws_role")
      ok "will seed $email as org $role, workspace $ws_role"
    else
      EXTRA+=(--extra-user "$email:$name:$role")
      ok "will seed $email as org $role (admin on every workspace, by definition)"
    fi
  done
fi

# ---- 9. up ------------------------------------------------------------------
step "Starting the stack"
export DATABASE_URL="$APP_DSN"
export TEST_ADMIN_DSN="$ADMIN_DSN"
"$ROOT/scripts/dev-up.sh" "${EXTRA[@]+"${EXTRA[@]}"}" || die "the stack did not come up"

TOKENS_FILE="${ANCHOR_TOKENS_FILE:-/tmp/anchor-dev-tokens.json}"
WEB_PORT="${ANCHOR_WEB_PORT:-3100}"

echo
echo "${BOLD}Ready.${OFF}"
echo
echo "  1. open  ${BOLD}http://localhost:$WEB_PORT/login${OFF}"
echo "  2. paste one of these tokens into the sign-in box:"
echo
"$VENV/bin/python" - "$TOKENS_FILE" <<'PY'
import json, sys
try:
    tokens = json.load(open(sys.argv[1]))
except Exception as exc:
    sys.exit(f"    could not read {sys.argv[1]}: {exc}")
for email, token in sorted(tokens.items()):
    print(f"     {email:<28} {token[:24]}...{token[-8:]}")
print(f"\n    Full tokens are in {sys.argv[1]}. To copy one:")
first = sorted(tokens)[0]
print(f"      python3 -c \"import json;print(json.load(open('{sys.argv[1]}'))['{first}'])\"")
PY
echo
echo "  Tokens last eight hours and are only valid for the API process now"
echo "  running - restarting it mints new ones. Run this script again to refresh."
echo
echo "  ${DIM}Run the tests:   scripts/check.sh${OFF}"
echo "  ${DIM}Logs:            /tmp/anchor-dev/{api,web,postgres}.log${OFF}"
echo "  ${DIM}Full guide:      docs/local-setup.md${OFF}"
