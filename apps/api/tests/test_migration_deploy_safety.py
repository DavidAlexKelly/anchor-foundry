"""§927: a migration does not break the version of the platform still running.

A deploy migrates first and then replaces the tasks a few at a time, with every
old task still serving until its replacement is healthy (minHealthyPercent 100,
`infra/cdk/src/constructs/services.ts`). So for a few minutes the previous
API and worker run against the new schema. A migration that drops or renames
what they read, changes a column's type under them, or makes a column they do
not write required, turns those minutes into errors for everyone - STATUS.md
named this after 0044 dropped a column and the previous API failed until it
was replaced.

So from 0169 on, such a statement needs a `-- deploy-safe:` comment just
above it saying why the previous version survives it: nothing reads it any
more, a trigger fills the column, or it is the second half of a change whose
first half shipped a release earlier (expand, then contract). The migrations
before are what they are; they are not re-read.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[3] / "packages" / "db" / "migrations"
#: The last migration written before this rule; nothing up to it is checked.
GRANDFATHERED_THROUGH = 168

UNSAFE = re.compile(
    r"\b(DROP\s+(TABLE|VIEW|FUNCTION|COLUMN)"
    r"|RENAME\s+(COLUMN\s+)?\w+\s+TO|RENAME\s+TO"
    r"|ALTER\s+COLUMN\s+\w+\s+(SET\s+DATA\s+)?TYPE"
    r"|SET\s+NOT\s+NULL)\b",
    re.IGNORECASE,
)
REASON = re.compile(r"--\s*deploy-safe:\s*\S", re.IGNORECASE)


def violations(directory: Path, after: int = GRANDFATHERED_THROUGH) -> list[str]:
    found = []
    for path in sorted(directory.iterdir()):
        number = re.match(r"(\d+)_", path.name)
        if not number or int(number.group(1)) <= after or path.suffix not in (".sql", ".py"):
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            code = line.split("--", 1)[0] if path.suffix == ".sql" else line
            if not UNSAFE.search(code):
                continue
            above = lines[max(0, index - 3):index + 1]
            if not any(REASON.search(candidate) for candidate in above):
                found.append(f"{path.name}:{index + 1}: {line.strip()}")
    return found


def test_no_migration_breaks_the_version_still_running() -> None:
    assert MIGRATIONS.is_dir(), MIGRATIONS
    found = violations(MIGRATIONS)
    assert not found, (
        "these statements would fail the API and worker still running during the "
        "deploy; split the change (add now, remove a release later) or say above "
        "the statement why it is safe with `-- deploy-safe: <reason>`:\n  " + "\n  ".join(found)
    )


def test_the_rule_reads_what_it_should(tmp_path: Path) -> None:
    def write(name: str, body: str) -> None:
        (tmp_path / name).write_text(body, encoding="utf-8")

    write("0100_old.sql", "ALTER TABLE a DROP COLUMN b;\n")
    write("0200_drop.sql", "ALTER TABLE a DROP COLUMN b;\n")
    write("0201_rename.sql", "ALTER TABLE a RENAME COLUMN b TO c;\nALTER TABLE x RENAME TO y;\n")
    write("0202_type.sql", "ALTER TABLE a ALTER COLUMN b TYPE bigint;\n")
    write("0203_required.sql", "ALTER TABLE a ALTER COLUMN b SET NOT NULL;\n")
    write("0204_reasoned.sql",
          "-- deploy-safe: nothing has read b since 0190.\nALTER TABLE a DROP COLUMN b;\n")
    write("0205_comment.sql", "-- we used to DROP TABLE here\nSELECT 1;\n")
    write("0206_additive.sql", "ALTER TABLE a ADD COLUMN c text;\nDROP INDEX IF EXISTS i;\n")
    write("0207_function.sql", "DROP FUNCTION f(uuid);\n")
    found = violations(tmp_path, after=GRANDFATHERED_THROUGH)
    assert [f.split(":")[0] for f in found] == [
        "0200_drop.sql", "0201_rename.sql", "0201_rename.sql",
        "0202_type.sql", "0203_required.sql", "0207_function.sql"], found


def test_every_grandfathered_migration_exists() -> None:
    """The line is drawn at a migration that is there, so a renumbering cannot
    move it silently."""
    assert any(name.startswith(f"{GRANDFATHERED_THROUGH:04d}_") for name in os.listdir(MIGRATIONS))
