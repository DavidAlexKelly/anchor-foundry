"""Every field a response model returns is declared in the shared TypeScript type.

**Written because the absence of this check cost a year of a broken screen.**
`ModelOut` has declared `source_repo_id` since §94, with a comment saying in so
many words *"the UI needs to know before it offers an editor"*. The shared
`Model` interface never gained it. So the Models page could not read the field,
went on offering an edit the server refuses, and **nothing could complain**:
`tsc` sees a type that is internally consistent, the API sees a field it
correctly returns, and the two are never compared.

That is §191's mirrored-copies problem in its worst-to-notice form. There the
two copies agreed and were identically wrong; here they do not disagree at all
— one is simply *shorter*, and a missing row looks like nothing.

**One direction only, deliberately.** This asserts that the browser's type
declares everything the server sends. The other direction — a type carrying a
field no response model has — is a different bug with a different cause (a
field removed from the API, or a type written ahead of one), and folding both
into one assertion would produce a failure message that does not say which
happened. Worth adding when there is a case to look at.

No database: this reads two files.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.routes.datasets import DatasetOut  # noqa: E402
from src.routes.models import ModelOut  # noqa: E402
from src.routes.repositories import RepositoryOut  # noqa: E402

# Four levels: tests -> api -> apps -> the repository root. §270 got this one
# short and landed on `apps/`, which is a path that exists, so the failure was
# a missing file rather than a wrong directory.
ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
TYPES = os.path.join(ROOT, "packages", "types", "src", "index.ts")

#: (response model, the interface a browser reads it as). The table *is* the
#: check — a pair nobody adds is a pair nobody verifies — so a new response
#: model that a screen consumes belongs here on the day it is written.
PAIRS = [
    (ModelOut, "Model"),
    (DatasetOut, "Dataset"),
    (RepositoryOut, "Repository"),
]


def declared_fields(interface: str) -> set[str]:
    """The top-level field names of one `export interface`.

    Braces are counted rather than matched with a regex, because a nested
    object literal in a field's type would otherwise end the interface early
    and the test would pass by seeing fewer fields than exist — a check that
    fails open is the thing this file exists to avoid.
    """
    with open(TYPES) as f:
        source = f.read()
    start = source.index(f"export interface {interface} {{")
    body_start = source.index("{", start) + 1
    depth, i = 1, body_start
    while depth and i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
        i += 1
    body = source[body_start:i - 1]

    # Strip comments before reading names, so `/** source_path: ... */` in a
    # doc comment cannot be mistaken for a declaration.
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    # Only at depth 0 of the body: a field whose type is an inline object has
    # names of its own, and those are not this interface's fields.
    names, depth = set(), 0
    for line in body.splitlines():
        stripped = line.strip()
        if depth == 0:
            found = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\??\s*:", stripped)
            if found:
                names.add(found.group(1))
        depth += stripped.count("{") - stripped.count("}")
    return names


@pytest.mark.parametrize("model,interface", PAIRS, ids=[p[1] for p in PAIRS])
def test_the_browser_type_declares_every_field_the_api_returns(model, interface) -> None:
    sent = set(model.model_fields)
    declared = declared_fields(interface)
    missing = sorted(sent - declared)
    assert not missing, (
        f"{model.__name__} returns {missing}, which `{interface}` in "
        f"packages/types does not declare. A field the browser's type does not "
        f"know about is invisible to every screen, however correctly the API "
        f"sends it - which is how the Models page went on offering an edit the "
        f"server refuses (§275)."
    )


def test_the_reader_finds_the_fields_it_is_supposed_to_find() -> None:
    """**The check on the check.**

    `declared_fields` returning an empty set would make every assertion above
    pass vacuously, and a brace-counting reader has several ways to return
    early. So this asserts it finds specific known fields, including one
    declared *after* a doc comment and one after a field whose type spans
    braces — the two cases that would truncate it.
    """
    fields = declared_fields("Model")
    assert {"id", "name", "language", "source_repo_id", "source_path",
            "inputs", "updated_at"} <= fields
    # And not something from a doc comment or a neighbouring interface.
    assert "commit_id" not in fields, fields
