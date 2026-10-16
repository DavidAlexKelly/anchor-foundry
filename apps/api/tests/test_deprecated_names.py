"""Names a pinned library has said it will remove (§945).

Starlette 1.x renamed four status constants after RFC 9110 and keeps the old
names only behind a `StarletteDeprecationWarning`. The API used one of them,
`HTTP_422_UNPROCESSABLE_ENTITY`, thirty-nine times, so the upgrade that drops
the old names would have been an `AttributeError` at import. That warning
was one line among a test run's 1,600, which is how a deprecation reaches the
release that removes it. The list comes from Starlette itself, so a name it
deprecates later is caught too.
"""
from __future__ import annotations

import os
import re

import starlette.status

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
SOURCES = ("apps/api/src", "apps/control-plane/src", "apps/worker/src")


def test_no_source_uses_a_deprecated_starlette_status() -> None:
    deprecated = set(getattr(starlette.status, "__deprecated__", {}))
    assert "HTTP_422_UNPROCESSABLE_ENTITY" in deprecated, (
        "Starlette no longer lists its deprecated names where this test looks")
    pattern = re.compile(r"\b(" + "|".join(sorted(deprecated)) + r")\b")
    found = []
    for source in SOURCES:
        for folder, _dirs, files in os.walk(os.path.join(ROOT, source)):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as fh:
                    for number, line in enumerate(fh, 1):
                        if pattern.search(line):
                            found.append(f"{os.path.relpath(path, ROOT)}:{number}")
    assert not found, "deprecated Starlette status names:\n  " + "\n  ".join(found)
