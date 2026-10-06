"""A deployed API starts on its AWS gateways or not at all (§844).

The route modules default to development gateways - connection secrets in
process memory, files on local disk - and `_wire_production_gateways` swaps
them for AWS's when `S3_DATA_BUCKET` is set. STATUS.md §17 found that swap
missing entirely once; a task that lost the variable would make the same
mistake quietly. On ECS it now refuses to start instead.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import main  # noqa: E402


def test_on_ecs_without_a_bucket_it_will_not_start(monkeypatch) -> None:
    monkeypatch.delenv("S3_DATA_BUCKET", raising=False)
    monkeypatch.setenv(main.ECS_MARKER, "http://169.254.170.2/v4/task")
    with pytest.raises(RuntimeError, match="refusing to start"):
        main.create_app()


def test_off_ecs_without_a_bucket_it_keeps_the_development_gateways(monkeypatch) -> None:
    monkeypatch.delenv("S3_DATA_BUCKET", raising=False)
    monkeypatch.delenv(main.ECS_MARKER, raising=False)
    main.create_app()


def test_the_marker_is_what_the_ecs_agent_sets() -> None:
    """Named rather than guessed: the v4 task metadata endpoint's variable,
    present in every Fargate task on platform 1.4 and later."""
    assert main.ECS_MARKER == "ECS_CONTAINER_METADATA_URI_V4"
