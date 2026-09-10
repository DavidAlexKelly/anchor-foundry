"""Repository routes (ROADMAP.md phase 2, section 2).

The first writer `code_repos` has ever had. The table has been in the schema
since migration 0003 and empty in every deployment, because decision 0001
declined to build a git server and left it with nothing to do; decision 0003
gives it a data model, and this gives it a door.

Role floors match every other project-scoped resource: read = viewer, write =
editor. Committing is a write to the repository, not to what it produces -
publishing a transform from a commit is a separate act, at its own endpoint
(item 2.5), and a commit changes nothing about what runs until somebody
performs it. A project that requires code review refuses to publish at all,
with a sentence saying why: reviewing a publish needs proposals that understand
commits, and they do not.

Creating a repository registers it in the resource registry automatically
(db 0032's trigger), so a new repository appears in the project browser and
resolves at `/r/{id}` without this module knowing either exists.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..lib.errors import ConflictError, NotFoundError
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import audit
from ..services import code as code_service
from ..services import code_checks as check_service
from ..services import code_tags as tag_service
from ..services import code_test_runs as test_run_service
from ..services import dataset_engine as engine
from ..services import datasets as ds_service
from ..services import repositories as repo_service
from ..services import transform_declarations as declarations
from ..services import transform_problems as problem_service
from ..services import transform_publish as publish_service
from ..services.dataset_engine import DatasetEngineError

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/repositories",
    tags=["repositories"],
)


def _dataset_storage():
    """The one gateway `main.py` configured, not a second one pointed
    somewhere else - same reason `models.py` reaches for it this way."""
    from . import datasets as dataset_routes

    return dataset_routes._storage


class RepositoryOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    slug: str
    description: str
    default_branch: str
    resource_id: UUID
    created_at: datetime
    updated_at: datetime


class RepositoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    default_branch: str = Field(default="main", min_length=1, max_length=100)


class BranchOut(BaseModel):
    id: UUID
    name: str
    head_commit_id: UUID | None


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # Where to start it. A branch off nothing is legitimate - an empty
    # repository has no commit to point at.
    from_commit_id: UUID | None = None
    from_branch: str | None = None


class CommitOut(BaseModel):
    id: UUID
    parent_id: UUID | None
    message: str
    created_by: UUID | None
    created_at: datetime


class CommitIn(BaseModel):
    branch: str = Field(min_length=1, max_length=100)
    # The complete tree, not a patch (decision 0003). A caller sending a patch
    # would have to be trusted to have read the parent correctly.
    files: dict[str, str]
    message: str = Field(default="", max_length=4000)


class TreeOut(BaseModel):
    commit_id: UUID | None
    files: dict[str, str]


class DiffOut(BaseModel):
    added: list[str]
    deleted: list[str]
    modified: list[str]


class FileHistoryOut(BaseModel):
    """A commit that changed one file (§287)."""
    id: UUID
    parent_id: UUID | None
    message: str
    created_by: UUID | None
    created_at: datetime
    #: The file's content address at this commit, or null where it was deleted.
    sha: str | None
    #: added / modified / deleted, about this file at this commit.
    state: str


class CompareOut(BaseModel):
    base: str
    base_commit_id: UUID | None
    head: str
    head_commit_id: UUID | None
    # One of repo_service.MERGE_STATES. A string rather than an enum here
    # because the service owns the vocabulary and duplicating it as a second
    # enum is a second place for it to drift.
    state: str
    ahead_by: int
    behind_by: int
    commits: list[CommitOut]
    files: DiffOut


class MergeOut(CompareOut):
    # False for a merge that had nothing to do, which is not a failure.
    merged: bool


class MergeIn(BaseModel):
    # `head` merges into `base`; `base` is the branch that moves. Named the way
    # the comparison reads rather than "source"/"target", because the screen
    # asks "what would merging this into that do".
    base: str = Field(min_length=1, max_length=100)
    head: str = Field(min_length=1, max_length=100)


class PublishStepOut(BaseModel):
    path: str
    output: str
    language: str
    model_id: UUID | None
    model_name: str
    # True when the source is byte-identical to what is already live, so
    # publishing writes nothing for this file.
    unchanged: bool
    renames: bool
    inputs: list[dict[str, Any]]
    # created / updated / unchanged. Absent from a plan, which has not done
    # anything yet.
    action: str | None = None
    version_number: int | None = None


class OrphanOut(BaseModel):
    """A model this repository published from a file the commit no longer has.
    Reported, never deleted: a transform that has run holds a dataset other
    things read."""
    id: UUID
    name: str
    source_path: str


class PublishPlanOut(BaseModel):
    commit_id: UUID
    steps: list[PublishStepOut]
    orphaned: list[OrphanOut]


class PublishIn(BaseModel):
    branch: str | None = None
    commit_id: UUID | None = None


class PreviewIn(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    # The editor's buffer, not the commit. Previewing only what is committed
    # would make this ceremonial - the question a person asks is "does what I
    # just typed work", and they ask it before they are willing to commit.
    content: str | None = None
    branch: str | None = None
    commit_id: UUID | None = None


class PreviewedInputOut(BaseModel):
    alias: str
    dataset: str
    dataset_id: UUID
    rows_available: int
    rows_used: int
    sampled: bool


class PreviewOut(BaseModel):
    output: str
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    # Rows produced *from the sample*. `sampled` says whether that is the same
    # thing as the answer.
    row_count: int
    truncated: bool
    sampled: bool
    inputs: list[PreviewedInputOut]
    # Against the dataset this transform already writes, when it exists.
    schema_changes: dict[str, Any] | None = None
    writes_to_existing_dataset: bool = False


@router.get("", response_model=list[RepositoryOut])
async def list_repositories(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[RepositoryOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await repo_service.list_repositories(conn, access.project_id)
    return [RepositoryOut(**r) for r in rows]


@router.post("", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
async def create_repository(
    body: RepositoryCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> RepositoryOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await repo_service.create_repository(
            conn,
            project_id=access.project_id,
            name=body.name,
            description=body.description,
            default_branch=body.default_branch,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="repository.create",
            resource_type="code_repo",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return RepositoryOut(**row)


@router.get("/{repo_id}", response_model=RepositoryOut)
async def get_repository(
    repo_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> RepositoryOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
    return RepositoryOut(**row)


# ---- branches ----------------------------------------------------------------
@router.get("/{repo_id}/branches", response_model=list[BranchOut])
async def list_branches(
    repo_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[BranchOut]:
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        rows = await repo_service.list_branches(conn, repo_id)
    return [BranchOut(**{k: r[k] for k in ("id", "name", "head_commit_id")}) for r in rows]


@router.post("/{repo_id}/branches", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
async def create_branch(
    repo_id: UUID,
    body: BranchCreate,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> BranchOut:
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        start = body.from_commit_id
        if start is None and body.from_branch:
            start = await repo_service.resolve_ref(
                conn, repo_id=repo_id, branch=body.from_branch, commit_id=None
            )
        row = await repo_service.create_branch(
            conn,
            repo_id=repo_id,
            name=body.name,
            from_commit=start,
            created_by=access.auth.user_id,
        )
    return BranchOut(**row)


@router.delete("/{repo_id}/branches/{name}", status_code=status.HTTP_204_NO_CONTENT,
               response_model=None)
async def delete_branch(
    repo_id: UUID,
    name: str,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    """Deletes the pointer. The commits stay - they are still referenced by
    anything published from them (decision 0003)."""
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        await repo_service.delete_branch(conn, repo_id=repo_id, name=name)


@router.get("/{repo_id}/compare", response_model=CompareOut)
async def compare_branches(
    repo_id: UUID,
    base: str = Query(..., min_length=1, max_length=100),
    head: str = Query(..., min_length=1, max_length=100),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> CompareOut:
    """What merging `head` into `base` would do. Viewer, because it does none
    of it - this is the screen a reviewer reads before anybody merges."""
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        try:
            result = await repo_service.compare_branches(
                conn, repo_id=repo_id, base=base, head=head
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
    return CompareOut(**result)


@router.post("/{repo_id}/merge", response_model=MergeOut)
async def merge_branch(
    repo_id: UUID,
    body: MergeIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> MergeOut:
    """Fast-forward `base` onto `head`, or refuse with what diverged.

    200 rather than 201: nothing is created. A fast-forward moves a pointer to
    commits that already existed, and a merge with nothing to do returns the
    same shape with `merged: false`.
    """
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        try:
            result = await repo_service.merge_branch(
                conn, repo_id=repo_id, base=body.base, head=body.head
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        if result["merged"]:
            await audit.record(
                conn,
                organisation_id=access.auth.organisation_id,
                user_id=access.auth.user_id,
                action="repository.merge",
                resource_type="code_repo",
                resource_id=repo_id,
                workspace_id=access.workspace_id,
                project_id=access.project_id,
                metadata={
                    "base": body.base,
                    "head": body.head,
                    "to_commit": str(result["head_commit_id"]),
                    "commits": result["ahead_by"],
                },
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
    return MergeOut(**result)


# ---- content -----------------------------------------------------------------
@router.get("/{repo_id}/tree", response_model=TreeOut)
async def read_tree(
    repo_id: UUID,
    branch: str | None = Query(default=None),
    commit_id: UUID | None = Query(default=None),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> TreeOut:
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        ref = await repo_service.resolve_ref(
            conn,
            repo_id=repo_id,
            branch=branch or repo["default_branch"],
            commit_id=commit_id,
            # Only when falling back to the default: a repository nobody has
            # committed to has no branch row, and an editor cannot open a
            # repository it is told does not exist.
            allow_missing_branch=branch is None,
        )
        # A branch with no commits is a real state, not an error: a repository
        # that has just been created renders as empty rather than as missing.
        files = (
            {}
            if ref is None
            else await repo_service.read_tree(
                conn, workspace_id=access.workspace_id, commit_id=ref
            )
        )
    return TreeOut(commit_id=ref, files=files)


# ---- checks on a branch (§285; code-repositories.md §5, p.19) -----------------
class BranchCheckOut(BaseModel):
    """One check result, carrying the proposal it belongs to.

    A check without the change it is about is a verdict on nothing, so the
    proposal travels with it - the Checks tab is a list of *what ran*, and what
    ran is always "these checks, on this proposal, over this commit".
    """
    id: UUID
    name: str
    # pass / warn / fail / error. `error` is not a pass: it means nobody has
    # been told anything about the code.
    status: str
    summary: str
    model_id: UUID | None = None
    source_path: str | None = None
    ran_at: datetime
    ran_by_email: str | None = None
    # **There is no `stale` here, and that is deliberate** (§213, §285).
    #
    # `ProposalDetail` carries one, and it earns it: a typed-changes proposal's
    # files can be edited, so a result can end up describing code nobody will
    # apply. A commit-backed proposal's cannot - the commit is immutable, which
    # is the property db 0039 chose it for - so `files_updated_at` never moves
    # and the flag is `false` for every row this endpoint can return. A field
    # that is always false is a field that lies about being a question.
    #
    # It was written and removed on finding the one path that could have moved
    # it: `PATCH /proposals/{id}` with `changes` accepted them on a
    # commit-backed proposal, wrote rows nothing reads, and invalidated every
    # approval on the way. That is now refused (`update_proposal`), which is a
    # fix worth having on its own and is also what makes this line unnecessary.
    proposal_id: UUID
    proposal_summary: str
    proposal_state: str
    source_commit_id: UUID


class BranchChecksOut(BaseModel):
    branch: str
    #: Null when nothing has ever been committed to the branch.
    head_commit_id: UUID | None = None
    checks: list[BranchCheckOut]


@router.get("/{repo_id}/checks", response_model=BranchChecksOut)
async def branch_checks(
    repo_id: UUID,
    branch: str | None = Query(default=None),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> BranchChecksOut:
    """p.19: "view a summary of running and completed checks on each branch".

    **Ours attach to a proposal rather than to a commit**, which is a real
    divergence and one the tab states rather than papers over: the schema check
    asks what the code would do to the project's datasets, and a commit nobody
    has proposed has not said which change it means to make. So this is the
    checks of the proposals made over commits on this branch - and since §284 a
    sandbox is where work happens and a proposal is how it lands, that is every
    commit on its way to mattering.
    """
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        name = branch or repo["default_branch"]
        head = await repo_service.branch_head(conn, repo_id=repo_id, name=name)
        if head is None:
            raise NotFoundError(f"branch {name!r} does not exist")
        commit_id = head["head_commit_id"]
        # The whole history, not just the head: a proposal is made over the
        # commit that existed when somebody opened it, and the branch has
        # usually moved on since. Showing only the head's checks would empty
        # the tab the moment anybody committed again.
        commits = (
            [] if commit_id is None
            else [UUID(str(c)) for c in await repo_service.ancestors(conn, UUID(str(commit_id)))]
        )
        rows = await check_service.for_branch(
            conn, project_id=access.project_id, repo_id=repo_id, commit_ids=commits
        )
    return BranchChecksOut(
        branch=name,
        head_commit_id=UUID(str(commit_id)) if commit_id else None,
        checks=[BranchCheckOut(**r) for r in rows],
    )


# ---- problems (§286; code-repositories.md §2.4, p.14) -------------------------
class ProblemOut(BaseModel):
    path: str
    #: 1-based, or 0 when the reader could not say where. Not 1: "the first
    #: line" and "somewhere in this file" are different answers, and a panel
    #: that sent somebody to line 1 for the second would be lying quietly.
    line: int
    #: error / warning. An error will refuse a publish; a warning will not.
    severity: str
    message: str
    #: Which reader said so - declaration / sql / input.
    source: str


class ProblemsIn(BaseModel):
    branch: str | None = None
    #: Uncommitted edits laid over the committed tree, path -> content, with
    #: `null` for a file the author has deleted. **The delta travels, not the
    #: tree**: the server already has the commit, and sending five hundred
    #: files to ask about the three that changed would make the panel too
    #: expensive to open often enough to be useful.
    overrides: dict[str, str | None] = Field(default_factory=dict)


class ProblemsOut(BaseModel):
    problems: list[ProblemOut]


@router.post("/{repo_id}/problems", response_model=ProblemsOut)
async def find_problems(
    repo_id: UUID,
    body: ProblemsIn,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ProblemsOut:
    """p.14's Problems helper: what is wrong with this working set.

    **Viewer, unlike Preview.** A preview *executes* the caller's SQL against
    the project's data, which is why it takes the editor floor; this parses and
    reads names, touching nothing. Somebody who may read the code may be told
    what is wrong with it.
    """
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        ref = await repo_service.resolve_ref(
            conn,
            repo_id=repo_id,
            branch=body.branch or repo["default_branch"],
            commit_id=None,
            allow_missing_branch=True,
        )
        committed = (
            {} if ref is None
            else await repo_service.read_tree(
                conn, workspace_id=access.workspace_id, commit_id=ref
            )
        )
        working = dict(committed)
        for path, content in body.overrides.items():
            if content is None:
                working.pop(path, None)
            else:
                working[repo_service.normalise_path(path)] = content
        found = await problem_service.find(
            conn, project_id=access.project_id, files=working
        )
    return ProblemsOut(problems=[ProblemOut(**p) for p in found])


class TestRunIn(BaseModel):
    branch: str | None = None
    #: The same delta the Problems panel sends (§286): uncommitted edits laid
    #: over the committed tree, `null` for a file the author has deleted. The
    #: server already has the commit, and shipping five hundred files to test
    #: the three that changed would make the button too expensive to press.
    overrides: dict[str, str | None] = Field(default_factory=dict)


class TestOutcomeOut(BaseModel):
    #: `tests/test_daily.py::test_drops_zero_totals` - what you would type to
    #: run it again.
    id: str
    outcome: str
    duration_ms: int
    file: str | None = None
    line: int | None = None
    message: str | None = None
    detail: str | None = None


class TestRunOut(BaseModel):
    id: UUID
    repo_id: UUID
    branch: str
    #: queued | running | succeeded | failed | errored. **`failed` and
    #: `errored` are different answers** (db 0071): the first is about the
    #: author's tests, the second about the run not happening.
    status: str
    outcomes: list[TestOutcomeOut] | None = None
    error: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _run_out(row: dict[str, Any]) -> TestRunOut:
    raw = row.get("outcomes")
    return TestRunOut(
        **{k: v for k, v in row.items() if k != "outcomes"},
        outcomes=None if raw is None else [TestOutcomeOut(**o) for o in raw],
    )


@router.post("/{repo_id}/tests", response_model=TestRunOut,
             status_code=status.HTTP_202_ACCEPTED)
async def run_tests(
    repo_id: UUID,
    body: TestRunIn,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> TestRunOut:
    """p.13's "run all unit tests", p.14's Tests helper: queue a run over this
    working set.

    **202, not 200**, because nothing has run yet. Decision 0004 confines
    customer Python to a process holding no platform credentials, so this
    writes a job and the worker executes it - the same answer the Python
    preview refusal gives one route above.

    **Editor, unlike Problems.** A test is code the caller supplied and it
    *executes*, which is the line `preview_transform` draws: the floor matches
    who may write the file, not who may read it.
    """
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        branch = body.branch or str(repo["default_branch"])
        ref = await repo_service.resolve_ref(
            conn, repo_id=repo_id, branch=branch, commit_id=None,
            allow_missing_branch=True,
        )
        committed = (
            {} if ref is None
            else await repo_service.read_tree(
                conn, workspace_id=access.workspace_id, commit_id=ref
            )
        )
        working = dict(committed)
        for path, content in body.overrides.items():
            if content is None:
                working.pop(path, None)
            else:
                working[repo_service.normalise_path(path)] = content
        row = await test_run_service.request(
            conn, repo_id=repo_id, branch=branch, files=working,
            requested_by=access.auth.user_id,
        )
    return _run_out(row)


class ReferenceIn(BaseModel):
    """The file as it stands, and the dataset to add to it."""

    path: str
    content: str
    alias: str
    dataset: str


class ReferenceOut(BaseModel):
    content: str


@router.post("/{repo_id}/reference", response_model=ReferenceOut)
async def insert_reference(
    repo_id: UUID,
    body: ReferenceIn,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ReferenceOut:
    """The Explorer's Insert (§304): this file, with one more input declared.

    **A round trip for a pure function, deliberately.** The declaration syntax
    has exactly one writer - `transform_declarations.render`, which lives
    beside the reader for §272's reason - and a copy of it in the browser,
    where the button is, would be a second writer that disagrees the first time
    the format changes. The file goes there and comes back.

    Nothing is stored. The content is the caller's own working set, which the
    editor holds unsaved; writing it here would be committing on their behalf.
    Editor rather than viewer for §214's reason: a viewer cannot save what this
    hands back, and a control offered to somebody who would be refused is worse
    than one that is absent. `repo_id` is in the path and checked, because the
    project is what the role is about.
    """
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
    try:
        content = declarations.with_input(
            body.path, body.content, alias=body.alias, dataset=body.dataset
        )
    except declarations.DeclarationError as exc:
        # 422 for the reason the preview route gives one route over: the file
        # is the request body and it is the thing that is wrong. The message is
        # already phrased for whoever wrote it.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ReferenceOut(content=content)


@router.get("/{repo_id}/tests/{run_id}", response_model=TestRunOut)
async def read_test_run(
    repo_id: UUID,
    run_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> TestRunOut:
    """What happened to a run. Viewer: asking for tests to run executes code,
    reading what they said does not."""
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        row = await test_run_service.get(conn, repo_id=repo_id, run_id=run_id)
    return _run_out(row)


@router.get("/{repo_id}/tests", response_model=list[TestRunOut])
async def list_test_runs(
    repo_id: UUID,
    branch: str | None = Query(default=None),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[TestRunOut]:
    """Recent runs, newest first - what the panel opens on."""
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        rows = await test_run_service.latest(conn, repo_id=repo_id, branch=branch)
    return [_run_out(r) for r in rows]


class BranchSummaryOut(BaseModel):
    id: UUID
    name: str
    head_commit_id: UUID | None = None
    #: passed | failed | none. **`none` is not `passed`** - "nothing failed" and
    #: "everything passed" are the same number, and a green tick over a branch
    #: nothing has run against is the lie §295 refuses about a test suite.
    checks: str
    #: The open proposal over this branch's *head commit*, if there is one.
    #: p.16 puts a "Propose changes" button where there is not - the browser
    #: draws that from the absence rather than from a second field.
    proposal_id: UUID | None = None
    proposal_state: str | None = None
    proposal_summary: str | None = None


@router.get("/{repo_id}/branch-summary", response_model=list[BranchSummaryOut])
async def branch_summary(
    repo_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[BranchSummaryOut]:
    """p.16's Checks and Pull request columns, in one request.

    A repository with twenty branches would otherwise open the tab with twenty
    round trips, which is how a column becomes something people wait for rather
    than glance at.
    """
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        rows = await repo_service.branch_summary(conn, repo_id=repo_id)
    return [BranchSummaryOut(**r) for r in rows]


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    #: p.17: "from the current version of a branch, or from any arbitrary
    #: commit". Both, and never both at once - `resolve_ref` is what settles
    #: that, and it already refuses the ambiguity for every other route here.
    branch: str | None = None
    commit_id: UUID | None = None
    message: str | None = Field(default=None, max_length=1000)


class TagOut(BaseModel):
    id: UUID
    repo_id: UUID
    name: str
    commit_id: UUID
    message: str | None = None
    created_at: datetime
    created_by: UUID | None = None
    created_by_email: str | None = None
    #: The commit's own message, so a tags list says what was cut and not only
    #: when. A list of version numbers and dates makes you open each one.
    commit_message: str | None = None


@router.get("/{repo_id}/tags", response_model=list[TagOut])
async def list_tags(
    repo_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[TagOut]:
    """p.17's tags section of the Branches tab."""
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        rows = await tag_service.listing(conn, repo_id=repo_id)
    return [TagOut(**r) for r in rows]


@router.post("/{repo_id}/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    repo_id: UUID,
    body: TagIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> TagOut:
    """p.17: "A tag can be created from the current version of a branch, or from
    any arbitrary commit."

    **Editor, not owner.** A tag marks a version; it changes no code and moves
    no branch, and `code_tags`' trigger means it cannot later be pointed
    somewhere else. Whoever may commit may say which commit mattered.

    The repository's own naming convention comes from `repoSettings.json` at the
    commit being tagged - see `code_tags.check_name` and p.17's
    `tagNameValidation`.
    """
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        ref = await repo_service.resolve_ref(
            conn,
            repo_id=repo_id,
            branch=body.branch or (None if body.commit_id else str(repo["default_branch"])),
            commit_id=body.commit_id,
            allow_missing_branch=body.branch is None and body.commit_id is None,
        )
        if ref is None:
            # A repository with no commits has no version to mark, and a tag
            # pointing at nothing is the state db 0072 refuses outright.
            raise ConflictError(
                "there is nothing committed on this branch yet, so there is no "
                "version to tag"
            )
        files = await repo_service.read_tree(
            conn, workspace_id=access.workspace_id, commit_id=ref
        )
        try:
            row = await tag_service.create(
                conn,
                repo_id=repo_id,
                name=body.name,
                commit_id=ref,
                settings=tag_service.read_settings(files),
                message=body.message,
                created_by=access.auth.user_id,
            )
        except tag_service.TagNameRefused as exc:
            # 422: the name is the request body and it is the thing that is
            # wrong. The message is the repository's own where it set one.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="repository.tag",
            resource_type="code_repo",
            resource_id=repo_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"tag": body.name, "commit_id": str(ref)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return TagOut(**row, created_by_email=None, commit_message=None)


@router.delete("/{repo_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_model=None)
async def delete_tag(
    repo_id: UUID,
    tag_id: UUID,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    """A mistyped name has to be removable.

    Deleting takes nothing with it - db 0072 keeps `ON DELETE RESTRICT` on the
    commit, so the code is exactly as safe afterwards. That is why p.17's
    warning about deleting *branches* ("this can result in lost work for
    others") has no counterpart here.
    """
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        await tag_service.remove(conn, repo_id=repo_id, tag_id=tag_id)


@router.post("/{repo_id}/commits", response_model=CommitOut, status_code=status.HTTP_201_CREATED)
async def create_commit(
    repo_id: UUID,
    body: CommitIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CommitOut:
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        row = await repo_service.commit(
            conn,
            repo_id=repo_id,
            workspace_id=access.workspace_id,
            branch=body.branch,
            files=body.files,
            message=body.message,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="repository.commit",
            resource_type="code_repo",
            resource_id=repo_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"commit_id": str(row["id"]), "branch": body.branch,
                      "files": len(body.files)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return CommitOut(**{k: row[k] for k in
                        ("id", "parent_id", "message", "created_by", "created_at")})


@router.get("/{repo_id}/commits", response_model=list[CommitOut])
async def list_commits(
    repo_id: UUID,
    branch: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[CommitOut]:
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        rows = await repo_service.history(conn, repo_id=repo_id, branch=branch, limit=limit)
    return [CommitOut(**r) for r in rows]


# ---- file changes (§287; code-repositories.md §2.4, p.14) --------------------
class FileChangeRowOut(BaseModel):
    """One line of a side-by-side diff, carrying both sides' line numbers.

    The same shape the review surface uses (`code.py`'s `DiffRowOut`) and the
    same builder behind it. **A second alignment would be a second answer**:
    the panel and the review would disagree about what changed the first time
    one of them was improved.
    """
    kind: str
    live_line: int | None
    live_text: str | None
    proposed_line: int | None
    proposed_text: str | None


class FileChangesIn(BaseModel):
    path: str
    branch: str | None = None
    #: What the editor holds. `null` means the file has been deleted in the
    #: working set, which is a change worth showing rather than an absence.
    content: str | None = None
    #: What to compare against. Defaults to the branch head - "what have I
    #: changed" - and takes an older commit for p.14's "comparison with
    #: previous versions".
    against_commit_id: UUID | None = None


class FileChangesOut(BaseModel):
    path: str
    #: added / deleted / modified / unchanged, about this file rather than the
    #: whole tree.
    state: str
    added: int
    removed: int
    rows: list[FileChangeRowOut]


@router.post("/{repo_id}/file-changes", response_model=FileChangesOut)
async def file_changes(
    repo_id: UUID,
    body: FileChangesIn,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> FileChangesOut:
    """p.14: "view any uncommitted changes to the current file, as well as
    compare previous versions of the file".

    **Only the working side travels.** The committed side is already here, and
    a panel that posted both would be paying twice for the half the server
    wrote - the same reasoning §286's Problems endpoint takes for its overrides.
    """
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        ref = (
            body.against_commit_id
            if body.against_commit_id is not None
            else await repo_service.resolve_ref(
                conn,
                repo_id=repo_id,
                branch=body.branch or repo["default_branch"],
                commit_id=None,
                allow_missing_branch=True,
            )
        )
        path = repo_service.normalise_path(body.path)
        committed = (
            {} if ref is None
            else await repo_service.read_tree(
                conn, workspace_id=access.workspace_id, commit_id=ref
            )
        )
    before = committed.get(path)
    after = body.content
    rows = code_service.side_by_side(before or "", after or "")
    # A file absent on both sides has no rows and nothing to say, which is not
    # the same as one whose two versions happen to match.
    if before is None and after is None:
        state = "unchanged"
    elif before is None:
        state = "added"
    elif after is None:
        state = "deleted"
    else:
        state = "unchanged" if before == after else "modified"
    return FileChangesOut(
        path=path,
        state=state,
        added=sum(1 for r in rows if r["kind"] in ("added", "changed")),
        removed=sum(1 for r in rows if r["kind"] in ("removed", "changed")),
        rows=[FileChangeRowOut(**r) for r in rows],
    )


@router.get("/{repo_id}/file-history", response_model=list[FileHistoryOut])
async def file_history(
    repo_id: UUID,
    path: str = Query(...),
    branch: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[FileHistoryOut]:
    """The commits that **changed** this file, newest first (§287).

    Not every commit on the branch: the version list p.14 means is the one
    where the file changed, and most commits said nothing about it.
    """
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        rows = await repo_service.touching(
            conn, repo_id=repo_id, branch=branch or str(repo["default_branch"]),
            path=path, limit=limit,
        )
    return [FileHistoryOut(**r) for r in rows]


@router.get("/{repo_id}/diff", response_model=DiffOut)
async def diff_commits(
    repo_id: UUID,
    from_commit_id: UUID | None = Query(default=None),
    to_commit_id: UUID = Query(...),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> DiffOut:
    """Two commits, three sets. `from` defaults to the target's parent, which
    is the diff a reviewer means by "what changed in this commit"."""
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        target = await repo_service.get_commit(conn, to_commit_id)
        base_id = from_commit_id or target["parent_id"]
        base: dict[str, Any] = (
            {} if base_id is None
            else (await repo_service.get_commit(conn, UUID(str(base_id))))["manifest"]
        )
    return DiffOut(**repo_service.diff(base, target["manifest"]))


# ---- publishing (ROADMAP.md phase 2, item 2.5) -------------------------------
async def _publish_target(conn, access, repo_id: UUID, branch, commit_id) -> tuple[dict, UUID]:
    repo = await repo_service.get_repository(
        conn, project_id=access.project_id, repo_id=repo_id
    )
    ref = await publish_service.resolve_commit(
        conn, repo_id=repo_id, branch=branch, commit_id=commit_id,
        default_branch=str(repo["default_branch"]),
    )
    return repo, ref


@router.get("/{repo_id}/publish", response_model=PublishPlanOut)
async def plan_publish(
    repo_id: UUID,
    branch: str | None = Query(default=None),
    commit_id: UUID | None = Query(default=None),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> PublishPlanOut:
    """What publishing this commit would do, without doing it.

    Viewer, because it does none of it - and separate from the POST for the
    same reason 2.4's comparison is separate from its merge: a screen that can
    only report a problem after the button has been pressed teaches people to
    press and hope.
    """
    async with user_connection(access.auth.user_id) as conn:
        _, ref = await _publish_target(conn, access, repo_id, branch, commit_id)
        try:
            steps = await publish_service.plan(
                conn, project_id=access.project_id, workspace_id=access.workspace_id,
                repo_id=repo_id, commit_id=ref,
            )
        except publish_service.PublishError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        left = await publish_service.orphaned(
            conn, project_id=access.project_id, repo_id=repo_id,
            workspace_id=access.workspace_id, commit_id=ref,
        )
    return PublishPlanOut(
        commit_id=ref,
        steps=[PublishStepOut(**s) for s in steps],
        orphaned=[OrphanOut(**{k: o[k] for k in ("id", "name", "source_path")}) for o in left],
    )


@router.post("/{repo_id}/publish", response_model=PublishPlanOut)
async def publish_transforms(
    repo_id: UUID,
    body: PublishIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> PublishPlanOut:
    """Make the declared transforms at this commit the project's definitions.

    One transaction for the whole commit: a commit is a snapshot, and half of
    one landing would leave a pipeline matching no state the repository has ever
    been in.
    """
    async with user_connection(access.auth.user_id) as conn:
        _, ref = await _publish_target(conn, access, repo_id, body.branch, body.commit_id)
        try:
            steps = await publish_service.publish(
                conn, project_id=access.project_id, workspace_id=access.workspace_id,
                repo_id=repo_id, commit_id=ref, actor_id=access.auth.user_id,
            )
        except publish_service.PublishError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        left = await publish_service.orphaned(
            conn, project_id=access.project_id, repo_id=repo_id,
            workspace_id=access.workspace_id, commit_id=ref,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="repository.publish",
            resource_type="code_repo",
            resource_id=repo_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={
                "commit_id": str(ref),
                "transforms": [
                    {"path": s["path"], "output": s["output"], "action": s["action"]}
                    for s in steps
                ],
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return PublishPlanOut(
        commit_id=ref,
        steps=[PublishStepOut(**{**s, "model_id": s["model_id"]}) for s in steps],
        orphaned=[OrphanOut(**{k: o[k] for k in ("id", "name", "source_path")}) for o in left],
    )


# ---- preview (ROADMAP.md phase 2, item 2.6) ----------------------------------
@router.post("/{repo_id}/preview", response_model=PreviewOut)
async def preview_transform(
    repo_id: UUID,
    body: PreviewIn,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> PreviewOut:
    """Run one file's transform against a sample of its declared inputs and
    return the rows, writing nothing.

    Editor rather than viewer, unlike every other read here. A preview
    executes SQL the caller supplied against datasets in the project, which is
    the same act `POST /datasets/{id}/query` performs - but this one arrives
    from an editor buffer rather than a saved model, so the floor matches who
    is allowed to write the file rather than who is allowed to read it.

    The inputs are resolved *by name*, from the declaration. A transform that
    names a dataset the project does not have is refused with the name in the
    message, which is the answer to the question the author is actually asking.
    """
    content = body.content
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        if content is None:
            ref = await repo_service.resolve_ref(
                conn,
                repo_id=repo_id,
                branch=body.branch or repo["default_branch"],
                commit_id=body.commit_id,
                allow_missing_branch=body.branch is None,
            )
            files = (
                {} if ref is None
                else await repo_service.read_tree(
                    conn, workspace_id=access.workspace_id, commit_id=ref
                )
            )
            if body.path not in files:
                raise NotFoundError(f"{body.path} at this commit")
            content = files[body.path]

        try:
            declaration = declarations.read(body.path, content)
        except declarations.DeclarationError as exc:
            # 422: the file is the request body and it is the thing that is
            # wrong. The message is already phrased for whoever wrote it.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        if declaration is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{body.path} does not declare a transform, so there is nothing to "
                    "preview - a transform declares the dataset it produces"
                ),
            )
        if not body.path.endswith(".sql"):
            # Decision 0004: customer Python runs in the runner task, never in
            # the API. Previewing it means dispatching a Fargate task and
            # waiting on it, which is a job with a status rather than an HTTP
            # response (STATUS.md §69).
            raise ConflictError(
                "previewing Python transforms is not built yet - they run in an isolated "
                "task rather than in the API, which takes long enough to need a job you "
                "can watch rather than a request that waits. SQL transforms preview now."
            )

        datasets_by_name = {
            str(row["name"]): row
            for row in await ds_service.list_for_project(conn, access.project_id)
        }
        missing = [
            name for name in declaration.inputs.values() if name not in datasets_by_name
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "this transform reads "
                    + ", ".join(sorted(set(missing)))
                    + ", which this project does not have"
                ),
            )
        input_rows = {
            alias: datasets_by_name[name] for alias, name in declaration.inputs.items()
        }
        output_row = datasets_by_name.get(declaration.output)

    storage = _dataset_storage()
    input_paths: dict[str, str] = {}
    for alias, row in input_rows.items():
        input_paths[alias] = await anyio.to_thread.run_sync(
            storage.local_path, str(row["s3_location"])
        )

    try:
        result, previewed = await anyio.to_thread.run_sync(
            engine.preview_transform, input_paths, content
        )
    except DatasetEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except FileNotFoundError as exc:
        # A dataset row with no bytes behind it. Not the author's fault, and
        # saying "your SQL is wrong" would send them to the wrong place.
        raise ConflictError(
            "one of this transform's inputs has no stored data yet, so there is nothing "
            "to preview against"
        ) from exc

    used = {p.alias: p for p in previewed}
    return PreviewOut(
        output=declaration.output,
        columns=[c.as_dict() for c in result.columns],
        rows=result.rows,
        row_count=result.total_rows,
        truncated=result.truncated,
        sampled=any(p.sampled for p in previewed),
        inputs=[
            PreviewedInputOut(
                alias=alias,
                dataset=str(row["name"]),
                dataset_id=UUID(str(row["id"])),
                rows_available=used[alias].rows_available,
                rows_used=used[alias].rows_used,
                sampled=used[alias].sampled,
            )
            for alias, row in input_rows.items()
        ],
        # The drift the roadmap asked this to catch: what this change would do
        # to the dataset the transform already writes.
        schema_changes=engine.diff_schemas(
            output_row.get("table_schema") if output_row else None, result.columns
        ),
        writes_to_existing_dataset=output_row is not None,
    )
