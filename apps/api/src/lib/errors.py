"""API error types. One deliberate convention from spec §9: a resource the
user cannot access "does not exist for this user (404, not 403)" — access
denial is expressed as NotFound to avoid leaking resource existence."""
from __future__ import annotations

from fastapi import HTTPException, status


class NotFoundError(HTTPException):
    def __init__(self, resource: str = "resource") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} not found")


class ForbiddenError(HTTPException):
    """Used only when the resource is legitimately visible but the action is
    not permitted (e.g. a viewer attempting a write on a workspace they can
    see). Invisible resources always raise NotFoundError instead."""

    def __init__(self, detail: str = "insufficient permissions") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class UnauthorizedError(HTTPException):
    def __init__(self, detail: str = "authentication required") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)
