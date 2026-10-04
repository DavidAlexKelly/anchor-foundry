"""The migration Lambda's package migrates an empty database (§848).

Every deploy runs `packages/db`'s migrations from a Lambda whose package is
built from `packages/db` alone. Migration 0034 imports the Workshop converter
from `apps/api`, and that was never in the package: every fresh stack's
migration stopped at 0034 with `No module named 'src'`, and its creation rolled
back. Nothing here had run migrations from the package - local runs, CI and the
fresh-database tests all run `migrate.py` from the checkout, where the import
finds the API by walking up the tree.

So this builds the package with the script the bundling container runs
(`packages/db/bundle.sh`), puts it somewhere no checkout is above it, as
`/var/task` is in Lambda, and migrates a fresh database from it with nothing
else on the path.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, for_database  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PACKAGE = REPO_ROOT / "packages" / "db"
CONVERTER = REPO_ROOT / "apps" / "api" / "src" / "services" / "workshop_format.py"
MIGRATION_TS = REPO_ROOT / "infra" / "cdk" / "src" / "constructs" / "migration.ts"


def bundle(into: Path) -> Path:
    task = into / "var" / "task"
    task.mkdir(parents=True)
    subprocess.run(["bash", str(DB_PACKAGE / "bundle.sh"), str(task)], check=True)
    return task


@pytest.fixture
def empty_database():
    name = f"lambda_bundle_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name} OWNER platform")
    try:
        yield for_database(ADMIN_DSN, name)
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE {name} WITH (FORCE)")


def test_the_package_migrates_an_empty_database(tmp_path: Path, empty_database: str) -> None:
    task = bundle(tmp_path)
    # What lambda_handler.handler does once it has the secrets, from inside the
    # package: `migrate` and anything a migration imports must come from it.
    ran = subprocess.run(
        [sys.executable, "-c",
         "import sys, migrate\n"
         "assert migrate.__file__.startswith(sys.argv[2]), migrate.__file__\n"
         "sys.exit(migrate.run(sys.argv[1]))",
         empty_database, str(task)],
        cwd=task, capture_output=True, text=True,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(task),
             "PLATFORM_APP_PASSWORD": os.environ.get("PLATFORM_APP_PASSWORD", "devpass")},
    )
    assert ran.returncode == 0, (ran.stdout + ran.stderr)[-2000:]
    files = sorted(p.name for p in (DB_PACKAGE / "migrations").iterdir()
                   if re.match(r"^\d{4}_.*\.(sql|py)$", p.name))
    with psycopg.connect(empty_database) as conn:
        applied = sorted(r[0] for r in conn.execute("SELECT filename FROM schema_migrations"))
    assert applied == files


def test_the_packaged_converter_is_the_apis(tmp_path: Path) -> None:
    """The package carries a copy, since the bundling container sees only
    `packages/db`. A change to the API's converter has to be copied too."""
    packaged = bundle(tmp_path) / "src" / "services" / "workshop_format.py"
    assert packaged.read_bytes() == CONVERTER.read_bytes(), (
        "copy apps/api/src/services/workshop_format.py to "
        "packages/db/lambda_vendor/src/services/")


def test_the_lambda_is_bundled_by_that_script() -> None:
    source = MIGRATION_TS.read_text()
    assert "bash bundle.sh /asset-output" in source
    assert "cp migrate.py" not in source
