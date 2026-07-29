"""A small real HTTP API for the REST connector tests.

Runs as its own process (`python rest_fixture_server.py <port>`) so the
connector talks to a genuine socket with genuine status codes, headers and
pagination - the same standard the other connectors are held to (a real
Postgres, a real MariaDB, a real moto S3). A mocked urlopen would test the
mock's shape, not the connector's.

Endpoints:
  /records            plain array body
  /wrapped            records nested under {"data": {"items": [...]}}
  /paged?page=N       page-number pagination, 2 records per page, empty at 3
  /cursored?cursor=X  cursor pagination via {"meta": {"next": ...}}
  /empty              a legitimately empty collection
  /notalist           a JSON object where a list is expected
  /notjson            not JSON at all
  /secured            requires X-API-Key: s3cret
  /bearer             requires Authorization: Bearer t0ken
  /oauth-token        POST client_credentials -> {"access_token": "minted"}
  /oauth-data         requires Authorization: Bearer minted
  /boom               always 500
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

API_KEY = "s3cret"
BEARER = "t0ken"
MINTED = "minted"

RECORDS = [
    {"id": 1, "name": "ada", "score": 9.5, "active": True, "tags": ["x", "y"]},
    {"id": 2, "name": "grace", "score": 8.25, "active": False, "tags": []},
    {"id": 3, "name": "alan", "score": 7.0, "active": True, "tags": ["z"]},
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass

    def _send(self, code: int, payload, raw: bytes | None = None) -> None:
        body = raw if raw is not None else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/oauth-token":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode())
        if (
            form.get("grant_type") == ["client_credentials"]
            and form.get("client_id") == ["the-client"]
            and form.get("client_secret") == ["the-secret"]
        ):
            self._send(200, {"access_token": MINTED, "token_type": "Bearer"})
        else:
            self._send(401, {"error": "invalid_client"})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)

        if path == "/records":
            self._send(200, RECORDS)
        elif path == "/wrapped":
            self._send(200, {"data": {"items": RECORDS}, "meta": {"total": len(RECORDS)}})
        elif path == "/paged":
            page = int((query.get("page") or ["1"])[0])
            chunk = RECORDS[(page - 1) * 2 : page * 2]
            self._send(200, {"results": chunk})
        elif path == "/cursored":
            cursor = (query.get("cursor") or [None])[0]
            if cursor is None:
                self._send(200, {"results": RECORDS[:2], "meta": {"next": "c2"}})
            elif cursor == "c2":
                self._send(200, {"results": RECORDS[2:], "meta": {"next": None}})
            else:
                self._send(200, {"results": [], "meta": {"next": None}})
        elif path == "/empty":
            self._send(200, [])
        elif path == "/notalist":
            self._send(200, {"records": {"id": 1}})
        elif path == "/notjson":
            self._send(200, None, raw=b"<html>nope</html>")
        elif path == "/secured":
            if self.headers.get("X-API-Key") == API_KEY:
                self._send(200, RECORDS)
            else:
                self._send(401, {"error": "unauthorized"})
        elif path == "/bearer":
            if self.headers.get("Authorization") == f"Bearer {BEARER}":
                self._send(200, RECORDS)
            else:
                self._send(403, {"error": "forbidden"})
        elif path == "/oauth-data":
            if self.headers.get("Authorization") == f"Bearer {MINTED}":
                self._send(200, RECORDS)
            else:
                self._send(401, {"error": "unauthorized"})
        elif path == "/boom":
            self._send(500, {"error": "kaboom"})
        else:
            self._send(404, {"error": "not found"})


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
