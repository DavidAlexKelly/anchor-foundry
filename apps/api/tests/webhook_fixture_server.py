"""A small real HTTP server for the webhook tests (§259).

Its own process (`python webhook_fixture_server.py <port>`) so the call goes
over a genuine socket with genuine status codes, exactly as
`rest_fixture_server.py` does for the connector — a patched `urlopen` would
test the patch's shape rather than the request.

**Most endpoints echo what they received.** That is the difference from the
connector's fixture and the reason this file exists: a connector test asks what
came *back*, and a webhook test has to ask what went *out*. A webhook that sent
`{"count": "3"}` where `{"count": 3}` was configured is wrong in a way no
assertion about the response can see.

Endpoints:
  /echo                any method; answers with the method, path, query,
                       selected headers and the decoded body
  /created             201 with {"results": {"unique_id": "X1"}}
  /empty               204 with no body at all
  /text                200 with a plain-text body
  /refuse              400 with {"detail": "no"} - p.237's "did not change"
  /boom                500 - p.237's unknown
  /slow                sleeps two seconds, then 200
  /huge                a body larger than the response cap
  /secured             requires X-API-Key: s3cret
"""
from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

API_KEY = "s3cret"

#: Which request headers the echo reports. Not all of them: `Host`,
#: `Content-Length` and `User-Agent` are set by the client library and asserting
#: on them would be asserting on urllib.
ECHOED_HEADERS = ("x-trace", "content-type", "accept", "x-api-key", "authorization")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass

    def _send(self, code: int, payload=None, raw: bytes | None = None,
              content_type: str = "application/json") -> None:
        if raw is None and payload is None:
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = raw if raw is not None else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return None
        raw = self.rfile.read(length).decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._body()

        if path == "/echo":
            self._send(200, {
                "method": method,
                "path": path,
                "query": {k: v[0] for k, v in parse_qs(parsed.query).items()},
                "headers": {
                    name: self.headers.get(name)
                    for name in ECHOED_HEADERS
                    if self.headers.get(name) is not None
                },
                "body": body,
            })
        elif path.startswith("/echo/"):
            # The path-substitution case: what arrives after `/echo/` is the
            # rendered path segment, percent-encoding and all.
            self._send(200, {"method": method, "path": path, "body": body})
        elif path == "/created":
            self._send(201, {"results": {"unique_id": "X1"}, "count": 7})
        elif path == "/empty":
            self._send(204)
        elif path == "/text":
            self._send(200, raw=b"OK", content_type="text/plain")
        elif path == "/refuse":
            self._send(400, {"detail": "no"})
        elif path == "/boom":
            self._send(500, {"detail": "boom"})
        elif path == "/slow":
            time.sleep(2)
            self._send(200, {"ok": True})
        elif path == "/huge":
            self._send(200, {"blob": "x" * (1024 * 1024 + 64)})
        elif path == "/secured":
            if self.headers.get("X-API-Key") != API_KEY:
                self._send(401, {"detail": "no key"})
            else:
                self._send(200, {"ok": True})
        else:
            self._send(404, {"detail": "not found"})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_PATCH(self) -> None:
        self._handle("PATCH")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_HEAD(self) -> None:
        # A HEAD answers with headers and no body, which is what makes it worth
        # a webhook: the status is the whole answer.
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> None:
    port = int(sys.argv[1])
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
