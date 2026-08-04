"""Code routes (ROADMAP Code item 2): a repository surface over a project's
transforms.

There is no repository resource to create, and that is the design rather than
an omission - `docs/decisions/0001-where-code-lives.md` decided the Code
pillar renders `model_versions` instead of storing code a second time, because
a run is pinned to the exact definition that produced it and a git ref cannot
promise that. So these are read paths over models, plus one write: the change
set, which saves several transforms as a single edit.

Role floors match Models exactly, deliberately: read = viewer, write =
editor. A second authoring surface that enforced a *different* floor from the
first would be a permission bug waiting for somebody to notice which door was
unlocked.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import audit
from ..services import code as code_service

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/code",
    tags=["code"],
)


class FileEntry(BaseModel):
    id: UUID
    path: str
    name: str
    language: str
    description: str
    size_bytes: int
    current_version: int | None
    updated_at: datetime


class FileDetail(FileEntry):
    code: str
    version_number: int | None
    inputs: list[dict[str, Any]] = []
    created_by_email: str | None = None
    restored_from: int | None = None
    change_set_id: UUID | None = None


class DiffOut(BaseModel):
    path: str
    model_id: UUID
    from_version: int | None
    to_version: int | None
    diff: str
    added: int
    removed: int


class HistoryEntry(BaseModel):
    kind: str
    id: UUID
    summary: str
    description: str
    created_at: datetime
    created_by_email: str | None
    model_count: int
    model_id: UUID | None = None
    version_number: int | None = None
    path: str | None = None


class ChangeSetMember(BaseModel):
    model_id: UUID
    model_name: str
    language: str
    path: str | None
    version_number: int
    previous_version: int | None


class ChangeSetOut(BaseModel):
    id: UUID
    project_id: UUID
    summary: str
    description: str
    created_at: datetime
    created_by_email: str | None = None
    models: list[ChangeSetMember]


class FileChange(BaseModel):
    model_id: UUID
    code: str | None = None
    inputs: list[dict[str, Any]] | None = None


class ChangeSetIn(BaseModel):
    summary: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    changes: list[FileChange] = Field(min_length=1)


@router.get("/tree", response_model=list[FileEntry])
async def get_tree(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[FileEntry]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await code_service.tree(conn, access.project_id)
    return [FileEntry(**r) for r in rows]


@router.get("/files/{model_id}", response_model=FileDetail)
async def get_file(
    model_id: UUID,
    version: int | None = Query(default=None, ge=1),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> FileDetail:
    """Head, or a numbered version. An old version returns the inputs it was
    saved with as well as its code: a transform that says `FROM orders` means
    nothing without knowing what `orders` was bound to at the time."""
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.file(conn, access.project_id, model_id, version)
    return FileDetail(**row)


@router.get("/files/{model_id}/diff", response_model=DiffOut)
async def get_diff(
    model_id: UUID,
    from_version: int | None = Query(default=None, ge=1),
    to_version: int | None = Query(default=None, ge=1),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> DiffOut:
    """Computed on read, stored nowhere - a saved diff is a second copy that
    can disagree with the versions it claims to describe."""
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.diff(
            conn, access.project_id, model_id, from_version, to_version
        )
    return DiffOut(**row)


@router.get("/history", response_model=list[HistoryEntry])
async def get_history(
    limit: int = Query(default=50, ge=1, le=200),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[HistoryEntry]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await code_service.history(conn, access.project_id, limit)
    return [HistoryEntry(**r) for r in rows]


@router.get("/change-sets/{change_set_id}", response_model=ChangeSetOut)
async def get_change_set(
    change_set_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ChangeSetOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.get_change_set(conn, access.project_id, change_set_id)
    return ChangeSetOut(**row)


@router.post("/change-sets", response_model=ChangeSetOut, status_code=201)
async def create_change_set(
    body: ChangeSetIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ChangeSetOut:
    """Save several transforms as one edit.

    Every file goes through the same `models.update` the inline editor calls,
    inside one transaction, so this cannot bypass a validation the other
    surface enforces (cycle refusal, input checks) and the versions it writes
    are the same rows a run resolves against.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.apply_change_set(
            conn,
            access.project_id,
            summary=body.summary,
            description=body.description,
            changes=[c.model_dump() for c in body.changes],
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="code_change_set.create",
            resource_type="code_change_set",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={
                "summary": body.summary,
                "models": [str(m["model_id"]) for m in row["models"]],
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ChangeSetOut(**row)


# ---- review-gated promotion (ROADMAP Code item 4) ---------------------------
class DiffRowOut(BaseModel):
    """One line of a side-by-side diff, carrying both sides' line numbers.

    Line numbers rather than row indices, because a comment anchors to a line
    of a file - an index into a rendering would move whenever the rendering
    changed.
    """
    kind: str
    live_line: int | None
    live_text: str | None
    proposed_line: int | None
    proposed_text: str | None


class ProposalCommentOut(BaseModel):
    id: UUID
    model_id: UUID
    side: str
    # None is a remark about the file rather than about a line.
    line: int | None
    body: str
    author_id: UUID | None
    author_email: str | None
    created_at: datetime
    # The proposal's `files_updated_at` this was said about - a version, not a
    # moment. Returned because "outdated" without saying *what it was about*
    # leaves a reader unable to tell which text the remark applies to.
    anchored_at: datetime
    # True when the proposal has been edited since: the line this points at is
    # not the line it was written about. Shown and marked, never hidden.
    outdated: bool
    resolved_at: datetime | None
    resolved_by: UUID | None


class FileMarkOut(BaseModel):
    """"I have read this file", per reviewer. Only marks made against the
    *current* files are returned - a mark from before the last edit says
    somebody read a file that no longer exists in that form."""
    model_id: UUID
    reviewer_id: UUID
    reviewer_email: str | None
    marked_at: datetime


class ProposalFileOut(BaseModel):
    model_id: UUID
    model_name: str
    language: str
    path: str | None
    code: str
    base_version: int
    current_version: int
    diff: str
    rows: list[DiffRowOut] = []
    comments: list[ProposalCommentOut] = []
    read_by: list[FileMarkOut] = []


class ReviewOut(BaseModel):
    id: UUID
    reviewer_id: UUID | None
    reviewer_email: str | None
    verdict: str
    comment: str
    created_at: datetime


class ProposalSummary(BaseModel):
    id: UUID
    project_id: UUID
    summary: str
    description: str
    state: str
    change_set_id: UUID | None
    created_by: UUID | None
    created_by_email: str | None
    created_at: datetime
    files_updated_at: datetime
    closed_by: UUID | None = None
    closed_at: datetime | None = None
    file_count: int = 0


class ProposalDetail(ProposalSummary):
    files: list[ProposalFileOut]
    reviews: list[ReviewOut]
    # The whole conversation in one list, for a caller that wants a timeline
    # rather than the per-file view above. Same rows, not a second store.
    comments: list[ProposalCommentOut] = []
    # Every reason this cannot be applied, so the UI can say which rule was
    # tripped rather than showing a disabled button with no explanation.
    blockers: list[str]


class ProposalIn(BaseModel):
    summary: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    changes: list[FileChange] = Field(min_length=1)


class ProposalPatch(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    changes: list[FileChange] | None = None


class ReviewIn(BaseModel):
    verdict: str = Field(pattern="^(approve|request_changes)$")
    comment: str = Field(default="", max_length=4000)


class ReviewPolicyIn(BaseModel):
    require_code_review: bool


class CommentIn(BaseModel):
    model_id: UUID
    side: str = Field(pattern="^(live|proposed)$")
    line: int | None = Field(default=None, ge=1)
    body: str = Field(min_length=1, max_length=4000)


class ResolveIn(BaseModel):
    resolved: bool


class FileMarkIn(BaseModel):
    model_id: UUID
    read: bool


def _detail(row: dict[str, Any]) -> ProposalDetail:
    return ProposalDetail(**{**row, "file_count": len(row.get("files", []))})


@router.get("/proposals", response_model=list[ProposalSummary])
async def list_proposals(
    state: str | None = Query(default=None, pattern="^(open|applied|withdrawn)$"),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[ProposalSummary]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await code_service.list_proposals(conn, access.project_id, state)
    return [ProposalSummary(**r) for r in rows]


@router.get("/proposals/{proposal_id}", response_model=ProposalDetail)
async def get_proposal(
    proposal_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ProposalDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.get_proposal(conn, access.project_id, proposal_id)
    return _detail(row)


@router.post("/proposals", response_model=ProposalDetail, status_code=201)
async def create_proposal(
    body: ProposalIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ProposalDetail:
    """Propose a change rather than making it. The files live on the proposal,
    not in `model_versions`, because that table is what a run resolves against
    and must never hold code nobody approved."""
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.create_proposal(
            conn, access.project_id,
            summary=body.summary, description=body.description,
            changes=[c.model_dump() for c in body.changes],
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="code_proposal.create",
            resource_type="code_proposal",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"summary": body.summary, "files": len(body.changes)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _detail(row)


@router.patch("/proposals/{proposal_id}", response_model=ProposalDetail)
async def update_proposal(
    proposal_id: UUID,
    body: ProposalPatch,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ProposalDetail:
    """Author-only, and changing the files invalidates the approvals it
    already had - otherwise approve-then-swap is a way past a reviewer."""
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.update_proposal(
            conn, access.project_id, proposal_id,
            summary=body.summary, description=body.description,
            changes=None if body.changes is None else [c.model_dump() for c in body.changes],
            actor_id=access.auth.user_id,
        )
    return _detail(row)


@router.post("/proposals/{proposal_id}/reviews", response_model=ProposalDetail, status_code=201)
async def review_proposal(
    proposal_id: UUID,
    body: ReviewIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ProposalDetail:
    """Editor-level, because approving a change is as consequential as making
    one - a viewer who could approve would be able to authorise an edit they
    are not allowed to write."""
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.review_proposal(
            conn, access.project_id, proposal_id,
            verdict=body.verdict, comment=body.comment,
            reviewer_id=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="code_proposal.review",
            resource_type="code_proposal",
            resource_id=proposal_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"verdict": body.verdict},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _detail(row)


@router.post("/proposals/{proposal_id}/apply", response_model=ProposalDetail)
async def apply_proposal(
    proposal_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ProposalDetail:
    """Turn an approved proposal into definitions, as one change set. The
    staleness check happens here rather than at review time: the gap between
    the two is exactly where a lost update lives."""
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.apply_proposal(
            conn, access.project_id, proposal_id, actor_id=access.auth.user_id
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="code_proposal.apply",
            resource_type="code_proposal",
            resource_id=proposal_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"change_set": str(row["change_set_id"])},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _detail(row)


@router.post("/proposals/{proposal_id}/withdraw", response_model=ProposalDetail)
async def withdraw_proposal(
    proposal_id: UUID,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ProposalDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.withdraw_proposal(
            conn, access.project_id, proposal_id, actor_id=access.auth.user_id
        )
    return _detail(row)


# ---- the review surface (ROADMAP.md phase 2, item 2.7) ----------------------
@router.post("/proposals/{proposal_id}/comments", response_model=ProposalDetail,
             status_code=201)
async def add_proposal_comment(
    proposal_id: UUID,
    body: CommentIn,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ProposalDetail:
    """Anchor a remark to a line, or to a file when `line` is absent.

    **Viewer**, unlike reviewing. A verdict is editor-level because approving a
    change is as consequential as making one; asking a question about line 14
    is not a verdict, and a reviewer who cannot be asked to explain their own
    code makes the conversation one-directional. The author may comment on
    their own proposal for the same reason - what they may not do is approve
    it.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.add_comment(
            conn, access.project_id, proposal_id,
            model_id=body.model_id, side=body.side, line=body.line,
            body=body.body, author_id=access.auth.user_id,
        )
    return _detail(row)


@router.patch("/proposals/{proposal_id}/comments/{comment_id}",
              response_model=ProposalDetail)
async def resolve_proposal_comment(
    proposal_id: UUID,
    comment_id: UUID,
    body: ResolveIn,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ProposalDetail:
    """Settle a thread, or reopen one. Both directions: a comment marked
    settled by mistake otherwise needs a second comment saying so."""
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.resolve_comment(
            conn, access.project_id, proposal_id, comment_id,
            resolved=body.resolved, actor_id=access.auth.user_id,
        )
    return _detail(row)


@router.put("/proposals/{proposal_id}/read", response_model=ProposalDetail)
async def mark_proposal_file_read(
    proposal_id: UUID,
    body: FileMarkIn,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ProposalDetail:
    """Per-file resolution: "I have read this one", per reviewer.

    Kept against the version that was read, so editing the proposal clears it
    without a write - the same rule that makes an approval stop counting.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.mark_file_read(
            conn, access.project_id, proposal_id,
            model_id=body.model_id, read=body.read, reviewer_id=access.auth.user_id,
        )
    return _detail(row)


@router.get("/review-policy", response_model=ReviewPolicyIn)
async def get_review_policy(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ReviewPolicyIn:
    """Readable by anyone who can read the code: whether an edit needs review
    is part of understanding what you are looking at."""
    async with user_connection(access.auth.user_id) as conn:
        required = await code_service.requires_review(conn, access.project_id)
    return ReviewPolicyIn(require_code_review=required)


@router.put("/review-policy", response_model=ReviewPolicyIn)
async def set_review_policy(
    body: ReviewPolicyIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("owner")),
) -> ReviewPolicyIn:
    """Owner-level: deciding whether changes need review is a governance
    decision about the project, not an editing action within it."""
    async with user_connection(access.auth.user_id) as conn:
        required = await code_service.set_require_review(
            conn, access.project_id, required=body.require_code_review
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="code_review_policy.update",
            resource_type="project",
            resource_id=access.project_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"require_code_review": required},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ReviewPolicyIn(require_code_review=required)
