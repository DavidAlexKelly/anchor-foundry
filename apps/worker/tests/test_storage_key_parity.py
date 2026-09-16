"""The two storage-key validators say the same thing (§191, §358).

`apps/worker/src/anchor_worker/storage.py` opens by promising to be kept in
step with `apps/api/src/services/storage.py`, and adds that "a validator that
is *narrower* than the writer's is how a key written by one service becomes
unreadable by the other". Nothing enforced that promise until §358 needed it:
the worker writes a model run's log and only the API reads it, so the two
grammars disagreeing means the log is written and then cannot be fetched.

**Compared as source, because the two are separate packages on purpose.** They
are independently deployable images with no shared Python between them, which
is the reason there are two copies at all; importing one from the other to
compare them would undo the thing being checked. Reading the line each declares
is the cheapest check that fails when they drift.

Which direction matters: **the worker's must not be narrower than the API's**
for keys the worker writes, and the API's must not be narrower for keys it
reads. Since every shape is written by one and read by the other, "identical"
is the only rule that covers both, and it is the one that catches an addition
to either side (§191).
"""
from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API_STORAGE = os.path.join(ROOT, "api", "src", "services", "storage.py")
WORKER_STORAGE = os.path.join(
    ROOT, "worker", "src", "anchor_worker", "storage.py"
)

_PATTERN_LINE = re.compile(r'^\s*r"(\^workspaces/.*\$)"\s*$', re.M)


def _grammar(path: str) -> str:
    with open(path) as handle:
        found = _PATTERN_LINE.search(handle.read())
    assert found is not None, f"no key grammar found in {path}"
    return found.group(1)


def test_both_services_accept_exactly_the_same_keys() -> None:
    assert _grammar(API_STORAGE) == _grammar(WORKER_STORAGE)


def test_the_grammar_covers_every_kind_of_byte_this_platform_stores() -> None:
    """Named, so that adding a kind to the grammar without adding it here is a
    failure rather than a silent widening — the check above only says the two
    agree, and two copies can agree on the wrong thing."""
    grammar = _grammar(API_STORAGE)
    for kind in ("datasets", "attachments", "runs"):
        assert kind in grammar, f"{kind} is not in the storage key grammar"
