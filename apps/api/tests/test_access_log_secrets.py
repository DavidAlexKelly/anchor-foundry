"""§922: no request's path or query string is written to the logs.

uvicorn's own access line printed both in full, so a listener's endpoint token
and an OAuth callback's code reached the stack's logs. Run as the image runs
it - the uvicorn command, in a process of its own - because what decides this
is the server's logging, not anything a TestClient goes through.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_a_token_in_the_path_or_query_is_not_logged(tmp_path) -> None:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--port", str(port)],
        cwd=API_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**os.environ, "STORAGE_ROOT": str(tmp_path)},
    )
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/listen/TOKEN-NOT-FOR-LOGS?code=CODE-NOT-FOR-LOGS",
            method="POST", data=b"{}")
        try:
            urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError:
            pass
        time.sleep(0.5)
    finally:
        proc.terminate()
        output = proc.communicate(timeout=10)[0].decode()
    assert "/api/listen/{token}" in output, f"the request was not logged at all:\n{output}"
    assert "TOKEN-NOT-FOR-LOGS" not in output and "CODE-NOT-FOR-LOGS" not in output, output
