#!/usr/bin/env bash
# Rehearse a restore of the platform database, and check what came back
# (roadmap phase 3, E.7; §803).
#
# "An untested backup is a hope." This dumps the database, restores the dump
# into a new database beside it, and runs the restore check against the
# restored copy with the live storage and index settings - which is the
# question a real restore has to answer: does what came back agree with the
# files and the index it will be served with?
#
# In a deployed stack the restore is RDS's point-in-time restore rather than a
# dump; `docs/deploying.md` ("Backup and restore") has those steps, and the
# check at the end is the same one.
#
#   ADMIN_DSN=postgresql://platform:...@host:5432/platform \
#   STORAGE_ROOT=/tmp/anchor-storage  scripts/rehearse-restore.sh [--workspace <uuid>]
#
# The rehearsal database is dropped afterwards unless KEEP=1.
set -euo pipefail

ADMIN_DSN=${ADMIN_DSN:-postgresql://platform:devpass@localhost:5432/platform?sslmode=disable}
here=$(cd "$(dirname "$0")/.." && pwd)
python="$here/.venv-api/bin/python"
target="platform_rehearsal_$(date +%s)"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# The same server and credentials, another database name.
base=${ADMIN_DSN%%\?*}
query=""; [[ "$ADMIN_DSN" == *\?* ]] && query="?${ADMIN_DSN#*\?}"
server=${base%/*}
target_dsn="$server/$target$query"

started=$(date +%s)
echo "dumping ${base##*/}..." >&2
pg_dump --format=custom --file="$work/platform.dump" "$ADMIN_DSN"
echo "restoring into $target..." >&2
psql --quiet --no-psqlrc "$ADMIN_DSN" -c "CREATE DATABASE \"$target\""
cleanup() {
  if [[ "${KEEP:-0}" != "1" ]]; then
    psql --quiet --no-psqlrc "$ADMIN_DSN" -c "DROP DATABASE IF EXISTS \"$target\"" >/dev/null
  else
    echo "kept $target" >&2
  fi
  rm -rf "$work"
}
trap cleanup EXIT
pg_restore --exit-on-error --dbname="$target_dsn" "$work/platform.dump"
echo "restored in $(( $(date +%s) - started ))s; checking..." >&2

status=0
( cd "$here/apps/api" && \
  DATABASE_URL="${target_dsn/postgresql:\/\//postgresql+psycopg://}" \
  "$python" -m src.services.restore_check "$@" ) || status=$?
echo "rehearsal finished in $(( $(date +%s) - started ))s, check exit $status" >&2
exit $status
