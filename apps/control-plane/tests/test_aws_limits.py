"""The control plane's AWS calls wait seconds, not minutes (§977): the copy of
the API's test (§970) for the onboarding page's preflight, connect and
provision, which call AWS inside the customer's request."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("boto3")

from src import aws  # noqa: E402


def test_a_client_carries_the_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    c = aws.client("sts", region_name="eu-west-2").meta.config
    assert (c.connect_timeout, c.read_timeout, c.retries["mode"],
            c.retries["total_max_attempts"]) == (3, 5, "standard", 3)


def test_nothing_makes_an_aws_client_any_other_way() -> None:
    makers = {
        str(path.relative_to(ROOT / "src"))
        for path in (ROOT / "src").rglob("*.py")
        if re.search(r"\bboto3\.client\(", path.read_text())
    }
    assert makers == {"aws.py"}
