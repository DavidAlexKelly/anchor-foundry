#!/usr/bin/env bash
# What the migration Lambda's package holds besides its pip dependencies
# (§848). infra/cdk/src/constructs/migration.ts runs this inside the bundling
# container, and apps/api/tests/test_migration_bundle.py runs it on the host
# and migrates a fresh database from what it produced - so the test checks the
# Lambda's actual contents, not a description of them.
#
#   bash bundle.sh OUT
#
# `lambda_vendor/` is what a `.py` migration imports from outside this
# directory. Only `packages/db` is mounted in the bundling container, so the
# Lambda never had `apps/api`, and migration 0034's converter import failed
# there on every fresh stack. The copy is held byte-identical to the API's by
# the same test.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="${1:?usage: bundle.sh OUT}"
cp "$here/migrate.py" "$here/lambda_handler.py" "$out/"
cp -r "$here/migrations" "$out/"
cp -r "$here/lambda_vendor/." "$out/"
