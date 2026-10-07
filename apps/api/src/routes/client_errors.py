"""A page that failed in someone's browser, told to the platform's operators
(§926).

§908 made a page that throws say so to the person in front of it. Nobody else
heard: the API's alarms (§815) read the API's own lines, and an exception in a
page never reaches the API, so a release that broke a screen for everyone was
known only to whoever wrote in about it. The error page now sends what it
showed here, and it becomes one line on `anchor.client_error`, which a metric
filter counts and an alarm watches.

Signed in only, so the line names who saw it and nobody outside can fill the
log. Every field is bounded, the path is taken without its query string (a
link can carry a token), and a process takes at most `REPORTS_PER_MINUTE`, so
a page failing in a loop on every open tab is a handful of lines, not a flood.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from ..middleware.auth import AuthContext, get_current_user

router = APIRouter(tags=["client-errors"])

client_error_log = logging.getLogger("anchor.client_error")

#: Reports one API process logs a minute; past it they are dropped, quietly.
REPORTS_PER_MINUTE = 60
_recent: deque[float] = deque()


class ClientErrorIn(BaseModel):
    #: "fault": the page threw. "stale": the page's code is from before a
    #: deploy (§908), which a reload fixes - logged, but not counted.
    kind: Literal["fault", "stale"]
    message: str = Field(max_length=500)
    path: str = Field(max_length=300)
    digest: str | None = Field(default=None, max_length=100)
    stack: str | None = Field(default=None, max_length=4000)


def _admit(now: float) -> bool:
    while _recent and now - _recent[0] >= 60:
        _recent.popleft()
    if len(_recent) >= REPORTS_PER_MINUTE:
        return False
    _recent.append(now)
    return True


@router.post("/client-errors", status_code=204)
async def report_client_error(
    body: ClientErrorIn, auth: AuthContext = Depends(get_current_user)
) -> Response:
    if _admit(time.monotonic()):
        client_error_log.warning("page error", extra={"fields": {
            "kind": body.kind,
            "message": body.message,
            "path": body.path.split("?", 1)[0].split("#", 1)[0],
            "digest": body.digest,
            "stack": body.stack,
            "user_id": str(auth.user_id),
        }})
    return Response(status_code=204)
