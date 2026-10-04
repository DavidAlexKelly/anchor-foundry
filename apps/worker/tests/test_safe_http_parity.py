"""The worker sends a source's requests by the API's rules (§880).

A scheduled sync calls the same REST source and token endpoint the API's
"run now" does, and is held to the same refusals: no metadata address, by
any name or redirect, and no credential carried to another host. The two
apps share no Python (see `test_storage_key_parity.py`), so `safe_http.py`
is written twice, and the files may differ only in the sentence naming each
other. The API's `tests/test_safe_http.py` is where it is exercised.
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = os.path.join(ROOT, "api", "src", "lib", "safe_http.py")
WORKER = os.path.join(ROOT, "worker", "src", "anchor_worker", "safe_http.py")
CONNECTORS = os.path.join(ROOT, "worker", "src", "anchor_worker", "connectors.py")


def _without_the_pointer(path: str) -> list[str]:
    return [line for line in open(path).read().splitlines() if "is the same file for the" not in line]


def test_the_api_and_the_worker_send_requests_the_same_way() -> None:
    assert _without_the_pointer(API) == _without_the_pointer(WORKER)


def test_the_worker_sends_nothing_around_it() -> None:
    source = open(CONNECTORS).read()
    assert "urlopen(" not in source
    assert source.count("safe_http.open_url(") == 2
