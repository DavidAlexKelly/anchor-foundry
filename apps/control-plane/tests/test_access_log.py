"""§922: an onboarding token is not written to the control plane's logs.

The customer's link carries the token as `?token=`, and uvicorn's access line
printed each path with its query string. Checked on a record shaped as
uvicorn's own (`protocols/http/h11_impl.py`), through the filter `create_app`
installs.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.api.app import AccessLineWithoutQuery, create_app  # noqa: E402

FORMAT = '%s - "%s %s HTTP/%s" %d'


def _line(path: str) -> str:
    create_app(admin_token="t")
    access = logging.getLogger("uvicorn.access")
    record = access.makeRecord("uvicorn.access", logging.INFO, __file__, 1, FORMAT,
                               ("10.0.0.1:5000", "GET", path, "1.1", 200), None)
    assert all(f.filter(record) for f in access.filters)
    return record.getMessage()


def test_the_token_in_a_link_is_not_logged() -> None:
    line = _line("/onboarding?token=SECRET-ONBOARDING-TOKEN")
    assert "SECRET-ONBOARDING-TOKEN" not in line
    assert line == '10.0.0.1:5000 - "GET /onboarding HTTP/1.1" 200'


def test_a_path_without_a_query_is_logged_as_it_was() -> None:
    assert _line("/api/onboarding/preflight") == '10.0.0.1:5000 - "GET /api/onboarding/preflight HTTP/1.1" 200'


def test_installing_twice_adds_one_filter() -> None:
    create_app(admin_token="t")
    create_app(admin_token="t")
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(f, AccessLineWithoutQuery) for f in filters) == 1
