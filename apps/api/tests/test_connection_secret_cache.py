"""A connection's credentials are read from Secrets Manager at most every
thirty seconds on a task, and at once after this task changes them (§960)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import connections  # noqa: E402


class Counting:
    def __init__(self) -> None:
        self.reads = 0
        self.values = {"password": "one"}

    def get_secret(self, arn: str) -> dict[str, str]:
        self.reads += 1
        return dict(self.values)


def test_a_second_read_inside_the_ttl_is_not_asked_for(monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(connections, "monotonic", lambda: clock[0])
    gateway, row = Counting(), {"secret_arn": "arn:test:cache-1", "config": {}}
    connections.forget_secret(row["secret_arn"])

    assert connections.secret_values_for(gateway, row) == {"password": "one"}
    clock[0] += 29
    assert connections.secret_values_for(gateway, row) == {"password": "one"}
    assert gateway.reads == 1
    clock[0] += 2  # past the TTL: asked again
    gateway.values = {"password": "two"}
    assert connections.secret_values_for(gateway, row) == {"password": "two"}
    assert gateway.reads == 2


def test_forgetting_reads_it_again_and_a_caller_cannot_change_the_cache(monkeypatch) -> None:
    monkeypatch.setattr(connections, "monotonic", lambda: 5000.0)
    gateway, row = Counting(), {"secret_arn": "arn:test:cache-2", "config": {}}
    connections.forget_secret(row["secret_arn"])
    first = connections.secret_values_for(gateway, row)
    first["password"] = "mutated by a caller"
    assert connections.secret_values_for(gateway, row) == {"password": "one"}
    gateway.values = {"password": "rotated"}
    connections.forget_secret(row["secret_arn"])
    assert connections.secret_values_for(gateway, row) == {"password": "rotated"}
    assert gateway.reads == 2
