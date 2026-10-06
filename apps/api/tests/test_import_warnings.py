"""The API starts without warnings (§834).

Twenty response and request models name fields `model_id`, `model_name` and
the like - this platform's models, not pydantic's - and pydantic warned about
each on every start, a block of noise at the head of every task's log that
made a real startup warning easy to miss. Each now says the namespace is not
pydantic's, and this keeps a new one from warning again.
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_importing_the_app_warns_about_nothing() -> None:
    result = subprocess.run(
        [sys.executable, "-W", "error::UserWarning", "-c",
         "import sys; sys.path.insert(0, '.'); import src.main"],
        cwd=HERE, capture_output=True, text=True,
        env={**os.environ, "PYTHONWARNINGS": ""},
    )
    assert result.returncode == 0, result.stderr[-2000:]
