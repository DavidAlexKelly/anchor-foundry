"""Request bodies are bounded before anything reads them (§832).

Nothing capped a request body. A JSON body is read whole into memory before a
route sees it, and a multipart one is spooled whole before `UploadFile.read`
can check its size - the attachment route then read the entire file again, and
only refused it past 25 MB afterwards. So any signed-in client could send a
body as large as it liked and the API task would hold it. The load balancer in
front sets no limit either.

Two limits, by what the body is:

* **A file upload** (`multipart/form-data`) gets the largest file any route
  accepts - a dataset's 50 MB (`datasets.MAX_UPLOAD_BYTES`) - and room for the
  form around it. Each route still applies its own, smaller, cap.
* **Anything else** gets 16 MB. The largest bodies the API takes are an
  ontology import (an export of the development workspace's 815 object types
  is 1.4 MB) and a test run's working set (4 MB, `code_test_runs`); a module
  definition on the development database is under 4 KB.

A declared `Content-Length` over the limit is refused before a byte is read.
A body that declares none (chunked) is counted as it arrives and refused the
moment it passes the limit, by a 413 raised from inside the read: FastAPI
re-raises a Starlette `HTTPException` from body parsing rather than calling it
a parse error, and the exception handlers answer it like any other.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from starlette.exceptions import HTTPException

MIB = 1024 * 1024
#: Anything that is not a file upload.
BODY_MAX_BYTES = 16 * MIB
#: A file upload: the dataset cap (50 MB) and a margin for the form.
UPLOAD_MAX_BYTES = 51 * MIB


class BodyTooLarge(HTTPException):
    def __init__(self, limit: int) -> None:
        super().__init__(status_code=413, detail=_sentence(limit))


def _sentence(limit: int) -> str:
    size = f"{limit // MIB} MB" if limit >= MIB else f"{limit} bytes"
    return f"a request body here is at most {size}"


def limit_for(headers: dict[bytes, bytes]) -> int:
    kind = headers.get(b"content-type", b"").split(b";")[0].strip().lower()
    return UPLOAD_MAX_BYTES if kind == b"multipart/form-data" else BODY_MAX_BYTES


Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class BodyLimit:
    """ASGI middleware applying `limit_for` to every HTTP request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        limit = limit_for(headers)
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _refuse(send, limit)
            return

        seen = 0
        started = False

        async def counted() -> dict[str, Any]:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise BodyTooLarge(limit)
            return message

        async def watched(message: dict[str, Any]) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, watched)
        except BodyTooLarge:
            # Raised somewhere no exception handler stood between it and here
            # - a read outside a route. Answered the same way, if it still can be.
            if started:
                raise
            await _refuse(send, limit)


async def _refuse(send: Send, limit: int) -> None:
    import json

    body = json.dumps({"detail": _sentence(limit)}).encode()
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})
