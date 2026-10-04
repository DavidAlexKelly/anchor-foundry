"""The worker stores data where the API reads it (§844).

`gateway_from_env` read `DATA_BUCKET`; the stack sets `S3_DATA_BUCKET`, so
every deployed worker fell back to local storage inside its own container and
wrote syncs, model outputs and exports where nothing else could read them.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import storage  # noqa: E402

SERVICES_TS = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                           "infra", "cdk", "src", "constructs", "services.ts")


def test_the_bucket_variable_is_one_the_stack_sets() -> None:
    """Read from the construct, not remembered: a rename on either side
    fails here rather than on a customer's stack."""
    text = open(SERVICES_TS, encoding="utf-8").read()
    common = text[text.index("const commonEnv = {"):]
    common = common[:common.index("};")]
    assert re.search(rf"^\s*{storage.BUCKET_ENV}:", common, re.M), (
        f"{storage.BUCKET_ENV} is not in services.ts's commonEnv")
    # And every service makeService builds, the worker included, gets it.
    assert "environment: { ...commonEnv," in text
    assert 'this.workerService = makeService("worker"' in text


def test_a_bucket_gives_s3(monkeypatch) -> None:
    monkeypatch.setenv(storage.BUCKET_ENV, "the-bucket")
    gateway = storage.gateway_from_env()
    assert isinstance(gateway, storage.S3StorageGateway)


def test_without_one_off_ecs_it_is_local(monkeypatch) -> None:
    monkeypatch.delenv(storage.BUCKET_ENV, raising=False)
    monkeypatch.delenv(storage.ECS_MARKER, raising=False)
    assert isinstance(storage.gateway_from_env(), storage.LocalStorageGateway)


def test_without_one_on_ecs_it_refuses(monkeypatch) -> None:
    monkeypatch.delenv(storage.BUCKET_ENV, raising=False)
    monkeypatch.setenv(storage.ECS_MARKER, "http://169.254.170.2/v4/task")
    with pytest.raises(RuntimeError, match="refusing to store data"):
        storage.gateway_from_env()


def test_the_old_name_is_not_read(monkeypatch) -> None:
    """`DATA_BUCKET` set and nothing else: still local, because nothing in a
    deployment sets that name and honouring it would only hide the next
    mismatch."""
    monkeypatch.delenv(storage.BUCKET_ENV, raising=False)
    monkeypatch.delenv(storage.ECS_MARKER, raising=False)
    monkeypatch.setenv("DATA_BUCKET", "old")
    assert isinstance(storage.gateway_from_env(), storage.LocalStorageGateway)
