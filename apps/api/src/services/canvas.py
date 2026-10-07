"""Canvas apps - the low-code app builder (spec §11 "Canvas": widgets bound
to objects - tables, charts, forms with write-back; spec §5 "Publishing":
private / workspace / specific groups).

An app's ``definition`` is an opaque JSON blob to this layer - a Craft.js
node tree (per db 0003's comment) the frontend builder produces and
interprets; this service only stores, versions, and gates visibility on it,
the same "backend doesn't understand widget semantics" split routes/actions.py
already takes with ``submitted_values``. Rendering (tables, object instances,
write-back forms) reuses the datasets/objects/actions endpoints already
built - no new data-access surface is needed for a widget to read or write
through; Canvas only needs to remember which widgets exist and how they're
arranged.

Publishing to the workspace or to specific groups requires the workspace
admin role (enforced at the route layer, mirroring routes/connections.py's
workspace-scoped connections) - both expose project data beyond the
project's own membership, so both get the same conservative bar. A plain
project editor can always keep an app private and edit it freely.

Schema (migration 0003, already applied - this session only starts using
it): canvas_apps, canvas_app_versions (one row per save), canvas_app_shares
(group targets when publish_scope='groups'). RLS (0006, recursion-fixed in
0009) additionally allows a workspace member to see a published app without
project membership; ``get_published``/``list_published`` below are the
counterpart read paths for that case, filtering to publish_scope <> 'private'
explicitly rather than trusting RLS alone (RLS also lets the app's own
project members through the same query).
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, ForbiddenError, NotFoundError

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
MAX_DEFINITION_BYTES = 2 * 1024 * 1024  # flag: conservative day-one cap on a saved layout

_COLUMN_NAMES = (
    "id", "project_id", "name", "slug", "description", "current_version",
    "publish_scope", "published_at", "published_version", "created_at", "updated_at",
    "auto_publish_on_save", "prompt_for_description",
    # p.187's Usage Metrics Tracking (§397, db 0093). Beside the other two
    # module settings rather than fetched on its own: a read that wanted it
    # would otherwise be a second query for a boolean the row already had.
    "track_usage",
    # Where this app opens as an application (`/r/{id}`). The column has been
    # here since the registry landed; not returning it meant every caller that
    # wanted to link to a module had to build a slug path instead, which is the
    # kind of link that breaks on a rename - the exact thing resource ids exist
    # to prevent. Object types surface theirs the same way.
    "resource_id",
    # p.617's protection (§700, db 0137): main is changed only by merging a
    # branch whose proposal was approved.
    "protected",
)


def _columns(alias: str = "") -> str:
    """The row shape every read returns, optionally qualified.

    A list rather than a `SELECT *`: the definition is fetched only where it is
    wanted (it is up to 2 MB), and a join needs the same columns qualified,
    which a hand-edited second copy of the list would eventually get wrong.
    """
    prefix = f"{alias}." if alias else ""
    return ", ".join(prefix + name for name in _COLUMN_NAMES)


_COLUMNS = _columns()


def slugify(name: str) -> str:
    """canvas_apps.slug allows only [a-z0-9-] - no underscore, unlike
    datasets' slug - so this can't reuse services/datasets.py's slugify."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:63].strip("-")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"cannot derive a valid slug from {name!r}")
    return slug


# ---- project-scoped CRUD -----------------------------------------------------
async def list_for_project(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        f"SELECT {_COLUMNS} FROM canvas_apps WHERE project_id = :pid ORDER BY name",
        {"pid": str(project_id)},
    )
    return [dict(r) for r in rows]


async def get(conn: AsyncConnection, project_id: UUID, app_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"SELECT {_COLUMNS}, definition FROM canvas_apps WHERE id = :aid AND project_id = :pid",
        {"aid": str(app_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("canvas app")
    return dict(row)


async def create(
    conn: AsyncConnection, *, project_id: UUID, name: str, description: str, created_by: UUID
) -> dict[str, Any]:
    slug = slugify(name)
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM canvas_apps WHERE project_id=:pid AND slug=:slug",
        {"pid": str(project_id), "slug": slug},
    )
    if existing is not None:
        raise ConflictError(f"an app named {slug!r} already exists in this project")
    row = await fetch_one(
        conn,
        f"""
        INSERT INTO canvas_apps (project_id, name, slug, description, created_by)
        VALUES (:pid, :name, :slug, :descr, :by)
        RETURNING {_COLUMNS}, definition
        """,
        {
            "pid": str(project_id), "name": name, "slug": slug,
            "descr": description, "by": str(created_by),
        },
    )
    assert row is not None
    return dict(row)


async def update_metadata(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    *,
    name: str | None,
    description: str | None,
) -> dict[str, Any]:
    await get(conn, project_id, app_id)  # 404 if invisible
    row = await fetch_one(
        conn,
        f"""
        UPDATE canvas_apps
           SET name = COALESCE(:name, name),
               description = COALESCE(:descr, description)
         WHERE id = :aid
        RETURNING {_COLUMNS}, definition
        """,
        {"name": name, "descr": description, "aid": str(app_id)},
    )
    assert row is not None
    return dict(row)


async def delete(conn: AsyncConnection, project_id: UUID, app_id: UUID) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM canvas_apps WHERE id=:aid AND project_id=:pid RETURNING id",
        {"aid": str(app_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("canvas app")


# ---- definition versioning ----------------------------------------------------
async def save_definition(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    *,
    definition: dict[str, Any],
    created_by: UUID,
    version_description: str = "",
    through_merge: bool = False,
) -> dict[str, Any]:
    existing = await get(conn, project_id, app_id)
    # p.617: a protected module's main is changed "on a branch rather than
    # directly to main". A merge is the one way in, and it says so; a revert
    # is a save like any other and is refused with it.
    if existing.get("protected") and not through_merge:
        raise ConflictError(
            "this module is protected: save your changes to a branch and merge it "
            "through an approved proposal"
        )
    payload = json.dumps(definition)
    if len(payload) > MAX_DEFINITION_BYTES:
        raise ValueError(f"layout exceeds the {MAX_DEFINITION_BYTES // (1024 * 1024)} MB size limit")
    version = int(existing["current_version"]) + 1
    row = await fetch_one(
        conn,
        f"""
        UPDATE canvas_apps
           SET definition = CAST(:def AS jsonb),
               current_version = :version,
               -- "Automatically publish when saving" (Foundry p.192). Done in
               -- the same statement as the save, because a save that published
               -- in a second round trip could leave viewers on the previous
               -- version if the second one failed - and the failure mode of
               -- "published, but not really" is the one thing §88 exists to
               -- rule out.
               published_version = CASE
                   WHEN auto_publish_on_save THEN :version ELSE published_version
               END,
               published_at = CASE
                   WHEN auto_publish_on_save THEN now() ELSE published_at
               END
         WHERE id = :aid
        RETURNING {_COLUMNS}, definition
        """,
        {"def": payload, "version": version, "aid": str(app_id)},
    )
    assert row is not None
    await fetch_one(
        conn,
        """
        INSERT INTO canvas_app_versions
                    (canvas_app_id, version_number, definition, created_by, description)
        VALUES (:aid, :version, CAST(:def AS jsonb), :by, :descr)
        RETURNING id
        """,
        {"aid": str(app_id), "version": version, "def": payload, "by": str(created_by),
         "descr": version_description[:500]},
    )
    return dict(row)


#: A page of an app's versions. Every save writes one, so the list grows for
#: as long as the app is edited.
VERSION_PAGE = 50


async def list_versions(
    conn: AsyncConnection, project_id: UUID, app_id: UUID,
    *, limit: int = VERSION_PAGE, before: int | None = None,
) -> list[dict[str, Any]]:
    """Newest first, `limit` at a time; `before` is the oldest version number
    already shown."""
    await get(conn, project_id, app_id)
    return await fetch_all(
        conn,
        """
        -- The editor's *name*, not their id. p.191 lists "a timestamp,
        -- editor, and description"; a dialog showing a uuid where a person
        -- belongs is a dialog nobody reads twice. LEFT JOIN because
        -- `created_by` is ON DELETE SET NULL - a version outlives the account
        -- that made it, and losing the whole row with the account would be
        -- worse than losing the name.
        SELECT v.id, v.version_number, v.created_by, v.created_at, v.description,
               u.display_name AS created_by_name
          FROM canvas_app_versions v
          LEFT JOIN users u ON u.id = v.created_by
         WHERE v.canvas_app_id = :aid
           AND (CAST(:before AS integer) IS NULL OR v.version_number < :before)
         ORDER BY v.version_number DESC
         LIMIT :limit
        """,
        {"aid": str(app_id), "before": before, "limit": limit},
    )


async def get_version(
    conn: AsyncConnection, project_id: UUID, app_id: UUID, version_number: int
) -> dict[str, Any]:
    """One saved version, definition included - "View this version" (p.191)."""
    await get(conn, project_id, app_id)
    row = await fetch_one(
        conn,
        """
        SELECT v.id, v.version_number, v.created_by, v.created_at, v.description,
               v.definition, u.display_name AS created_by_name
          FROM canvas_app_versions v
          LEFT JOIN users u ON u.id = v.created_by
         WHERE v.canvas_app_id = :aid AND v.version_number = :n
        """,
        {"aid": str(app_id), "n": version_number},
    )
    if row is None:
        raise NotFoundError("canvas app version")
    return dict(row)


async def describe_version(
    conn: AsyncConnection, project_id: UUID, app_id: UUID, version_number: int, description: str
) -> dict[str, Any]:
    """p.192: descriptions "can be viewed, added, and edited"."""
    await get(conn, project_id, app_id)
    row = await fetch_one(
        conn,
        """
        UPDATE canvas_app_versions SET description = :descr
         WHERE canvas_app_id = :aid AND version_number = :n
        RETURNING id, version_number, created_by, created_at, description
        """,
        {"aid": str(app_id), "n": version_number, "descr": description[:500]},
    )
    if row is None:
        raise NotFoundError("canvas app version")
    return dict(row)


async def publish_version(
    conn: AsyncConnection, project_id: UUID, app_id: UUID, version_number: int
) -> dict[str, Any]:
    """"Publish this version" (p.191) - pin viewers to a *named* version.

    Distinct from `set_publish_scope`, which pins whatever is current. This is
    the other half of what §88 made possible: if saving does not move viewers,
    then something has to be able to move them deliberately, and to a version
    somebody chose rather than to the newest one.

    **It does not change the scope.** A private module stays private and simply
    records which version its viewers would see; publishing to an audience is a
    separate decision with a separate permission (workspace admin), and folding
    the two together would let a project editor widen an audience by choosing a
    version number.
    """
    await get(conn, project_id, app_id)
    exists = await fetch_one(
        conn,
        "SELECT 1 AS ok FROM canvas_app_versions WHERE canvas_app_id = :aid AND version_number = :n",
        {"aid": str(app_id), "n": version_number},
    )
    if exists is None:
        raise NotFoundError("canvas app version")
    row = await fetch_one(
        conn,
        f"""
        UPDATE canvas_apps
           SET published_version = :n,
               published_at = COALESCE(published_at, now())
         WHERE id = :aid
        RETURNING {_COLUMNS}, definition
        """,
        {"aid": str(app_id), "n": version_number},
    )
    assert row is not None
    return dict(row)


async def revert_to_version(
    conn: AsyncConnection, project_id: UUID, app_id: UUID, version_number: int, created_by: UUID
) -> dict[str, Any]:
    """p.192: "Save the historic version as the newest version of the module."

    A *new* version rather than a rewind, which is the important part: the
    history between then and now is still there, and reverting a revert is
    another save rather than an archaeology problem.

    "A description detailing the revert action will be automatically generated"
    - so the generated text is the description, and it names the version this
    came from, because "Reverted" on its own tells you nothing a timestamp did
    not already.
    """
    source = await get_version(conn, project_id, app_id, version_number)
    definition = source["definition"]
    if isinstance(definition, str):
        definition = json.loads(definition)
    return await save_definition(
        conn, project_id, app_id,
        definition=definition,
        created_by=created_by,
        version_description=f"Reverted to version {version_number}",
    )


async def set_version_settings(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    *,
    auto_publish_on_save: bool | None,
    prompt_for_description: bool | None,
) -> dict[str, Any]:
    """The two toggles in the Versions dialog (p.192)."""
    await get(conn, project_id, app_id)
    row = await fetch_one(
        conn,
        f"""
        UPDATE canvas_apps
           SET auto_publish_on_save = COALESCE(:auto, auto_publish_on_save),
               prompt_for_description = COALESCE(:prompt, prompt_for_description)
         WHERE id = :aid
        RETURNING {_COLUMNS}, definition
        """,
        {"aid": str(app_id), "auto": auto_publish_on_save, "prompt": prompt_for_description},
    )
    assert row is not None
    return dict(row)


async def set_usage_tracking(
    conn: AsyncConnection, project_id: UUID, app_id: UUID, *, on: bool
) -> dict[str, Any]:
    """p.187's Usage Metrics Tracking toggle (§397).

    Its own statement rather than a field on `set_version_settings`: p.187 puts
    it in the Metrics tab and p.192 puts those two in the Versions dialog, and
    a route that took all three would let a caller change what is recorded
    about a module while saying it was adjusting how versions are published.
    """
    row = await fetch_one(
        conn,
        """
        UPDATE canvas_apps SET track_usage = :on, updated_at = now()
         WHERE id = :aid AND project_id = :pid
     RETURNING """ + _COLUMNS + """, definition
        """,
        {"aid": str(app_id), "pid": str(project_id), "on": on},
    )
    if row is None:
        raise NotFoundError("this module")
    return dict(row)


# ---- branches (§698, db 0136) -----------------------------------------------------
# p.193: "When developing on a branch, you may need to rebase before merging your
# Workshop changes into main if main has changed since your last save." A branch
# is a second head of the same module; `canvas_apps.definition` stays main's.

_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")

_BRANCH_COLUMNS = (
    "b.id, b.name, b.base_version, b.save_count, b.created_by, b.created_at, "
    "b.updated_at, u.display_name AS created_by_name, "
    # p.618's proposal (§700, db 0137).
    "b.proposal_status, b.proposed_by, b.proposed_at, b.reviewed_by, b.reviewed_at, "
    "b.last_saved_by, r.display_name AS reviewed_by_name"
)
_BRANCH_FROM = (
    "canvas_app_branches b "
    "LEFT JOIN users u ON u.id = b.created_by "
    "LEFT JOIN users r ON r.id = b.reviewed_by"
)


def check_branch_name(name: str) -> str:
    """The rule 0136's CHECK enforces, said in words before the database says
    it as a constraint name."""
    if not _BRANCH_NAME_RE.match(name):
        raise ValueError(
            "a branch name is 1-63 letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    if name.lower() == "main":
        raise ValueError("'main' is the module's own head, not a branch name")
    return name


def _with_rebase(row: dict[str, Any], current_version: int) -> dict[str, Any]:
    """p.193's "if main has changed since your last save", as a field: the
    branch was taken from (or last rebased onto) a main version that main has
    saved past."""
    return {**row, "needs_rebase": int(row["base_version"]) < current_version}


async def list_branches(
    conn: AsyncConnection, project_id: UUID, app_id: UUID
) -> list[dict[str, Any]]:
    app = await get(conn, project_id, app_id)
    rows = await fetch_all(
        conn,
        f"""
        SELECT {_BRANCH_COLUMNS}
          FROM {_BRANCH_FROM}
         WHERE b.canvas_app_id = :aid
         ORDER BY b.name
        """,
        {"aid": str(app_id)},
    )
    return [_with_rebase(dict(r), int(app["current_version"])) for r in rows]


async def get_branch(
    conn: AsyncConnection, project_id: UUID, app_id: UUID, name: str
) -> dict[str, Any]:
    app = await get(conn, project_id, app_id)
    row = await fetch_one(
        conn,
        f"""
        SELECT {_BRANCH_COLUMNS}, b.definition
          FROM {_BRANCH_FROM}
         WHERE b.canvas_app_id = :aid AND b.name = :name
        """,
        {"aid": str(app_id), "name": name},
    )
    if row is None:
        raise NotFoundError("branch")
    return _with_rebase(dict(row), int(app["current_version"]))


def _payload(definition: dict[str, Any]) -> str:
    payload = json.dumps(definition)
    if len(payload) > MAX_DEFINITION_BYTES:
        raise ValueError(f"layout exceeds the {MAX_DEFINITION_BYTES // (1024 * 1024)} MB size limit")
    return payload


async def create_branch(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    *,
    name: str,
    definition: dict[str, Any],
    created_by: UUID,
) -> dict[str, Any]:
    """p.617-618's **Save to new branch**: "Name the branch", and what is saved is
    the document the builder holds - so the edits somebody made on main before
    deciding they belonged on a branch go to the branch, not nowhere.

    Based on main's current version, which is the version those edits were
    made against."""
    check_branch_name(name)
    app = await get(conn, project_id, app_id)
    payload = _payload(definition)
    taken = await fetch_one(
        conn,
        "SELECT 1 AS x FROM canvas_app_branches WHERE canvas_app_id = :aid AND name = :name",
        {"aid": str(app_id), "name": name},
    )
    if taken is not None:
        raise ConflictError(f"this module already has a branch named {name!r}")
    await fetch_one(
        conn,
        """
        INSERT INTO canvas_app_branches
                    (canvas_app_id, name, definition, base_version, save_count, created_by,
                     last_saved_by)
        VALUES (:aid, :name, CAST(:def AS jsonb), :base, 1, :by, :by)
        RETURNING id
        """,
        {"aid": str(app_id), "name": name, "def": payload,
         "base": int(app["current_version"]), "by": str(created_by)},
    )
    return await get_branch(conn, project_id, app_id, name)


async def save_branch(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    name: str,
    *,
    definition: dict[str, Any],
    saved_by: UUID,
    base_version: int | None = None,
) -> dict[str, Any]:
    """A save on a branch: its document changes and main's does not.

    `base_version` is given only by a rebase (§699), which is the one save
    that moves what the branch is based on - and it must name main's current
    version, because a rebase onto a main that has since moved again has
    merged against the wrong ancestor."""
    app = await get(conn, project_id, app_id)
    payload = _payload(definition)
    if base_version is not None and base_version != int(app["current_version"]):
        raise ConflictError(
            f"main is at version {app['current_version']}, not {base_version} - "
            "it changed during the rebase, so rebase again"
        )
    row = await fetch_one(
        conn,
        """
        UPDATE canvas_app_branches
           SET definition = CAST(:def AS jsonb),
               save_count = save_count + 1,
               base_version = COALESCE(:base, base_version),
               last_saved_by = :by,
               -- p.618's review was of the document this save replaces, so a
               -- proposal goes back to waiting for one. Kept approved, it would
               -- carry whatever was saved after onto a protected main unread.
               proposal_status = CASE WHEN proposal_status IS NULL THEN NULL
                                      ELSE 'open'::branch_proposal_status END,
               reviewed_by = NULL,
               reviewed_at = NULL
         WHERE canvas_app_id = :aid AND name = :name
        RETURNING id
        """,
        {"aid": str(app_id), "name": name, "def": payload, "base": base_version,
         "by": str(saved_by)},
    )
    if row is None:
        raise NotFoundError("branch")
    return await get_branch(conn, project_id, app_id, name)


async def delete_branch(conn: AsyncConnection, project_id: UUID, app_id: UUID, name: str) -> None:
    await get(conn, project_id, app_id)
    row = await fetch_one(
        conn,
        "DELETE FROM canvas_app_branches WHERE canvas_app_id = :aid AND name = :name RETURNING id",
        {"aid": str(app_id), "name": name},
    )
    if row is None:
        raise NotFoundError("branch")


async def merge_branch(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    name: str,
    *,
    created_by: UUID,
) -> dict[str, Any]:
    """Merge a branch into main: its document becomes main's next version.

    **Refused while main has moved past the branch's base** - p.193: "you may
    need to rebase before merging … if main has changed since your last save".
    Merging anyway would replace main with a document that never saw main's
    newer changes, and they would be gone without anybody having chosen that.

    Main's row is locked first, so a save to main between the check and the
    merge waits for the merge rather than being overwritten by it.
    """
    locked = await fetch_one(
        conn,
        "SELECT current_version FROM canvas_apps WHERE id = :aid AND project_id = :pid FOR UPDATE",
        {"aid": str(app_id), "pid": str(project_id)},
    )
    if locked is None:
        raise NotFoundError("canvas app")
    branch = await get_branch(conn, project_id, app_id, name)
    app = await get(conn, project_id, app_id)
    # p.618's merge requirement on a protected module: an approved proposal.
    # Checked before the rebase rule so the message names what is missing
    # first on a module where both are.
    if app.get("protected") and branch["proposal_status"] != "approved":
        raise ConflictError(
            "this module is protected: the branch needs an approved proposal before "
            "it merges into main"
        )
    if branch["needs_rebase"]:
        raise ConflictError(
            f"main has changed since branch {name!r} was based on version "
            f"{branch['base_version']} (main is at {locked['current_version']}) - "
            "rebase the branch before merging it"
        )
    definition = branch["definition"]
    if isinstance(definition, str):
        definition = json.loads(definition)
    row = await save_definition(
        conn, project_id, app_id,
        definition=definition,
        created_by=created_by,
        version_description=f"Merged branch {name}",
        through_merge=True,
    )
    await delete_branch(conn, project_id, app_id, name)
    return row


def may_review(branch: dict[str, Any], user_id: UUID) -> bool:
    """p.618's reviewer: not whoever proposed the change and not whoever last
    saved it - their work is what is being reviewed."""
    me = str(user_id)
    return (
        branch.get("proposal_status") == "open"
        and str(branch.get("proposed_by") or "") != me
        and str(branch.get("last_saved_by") or "") != me
    )


async def propose_branch(
    conn: AsyncConnection, project_id: UUID, app_id: UUID, name: str, *, proposed_by: UUID,
) -> dict[str, Any]:
    """p.618: "When you are ready to merge your changes to main, create a
    proposal." Proposing again restarts the review."""
    await get(conn, project_id, app_id)
    row = await fetch_one(
        conn,
        """
        UPDATE canvas_app_branches
           SET proposal_status = 'open', proposed_by = :by, proposed_at = now(),
               reviewed_by = NULL, reviewed_at = NULL
         WHERE canvas_app_id = :aid AND name = :name
        RETURNING id
        """,
        {"aid": str(app_id), "name": name, "by": str(proposed_by)},
    )
    if row is None:
        raise NotFoundError("branch")
    return await get_branch(conn, project_id, app_id, name)


async def review_branch(
    conn: AsyncConnection, project_id: UUID, app_id: UUID, name: str,
    *, reviewer: UUID, approve: bool,
) -> dict[str, Any]:
    """p.618's Approve and Reject. Only an open proposal is reviewed, and
    never by the person whose changes it carries."""
    branch = await get_branch(conn, project_id, app_id, name)
    if branch["proposal_status"] != "open":
        raise ConflictError("there is no open proposal on this branch to review")
    if not may_review(branch, reviewer):
        raise ForbiddenError(
            "a proposal is reviewed by someone other than whoever proposed or last saved it"
        )
    await fetch_one(
        conn,
        """
        UPDATE canvas_app_branches
           SET proposal_status = CAST(:status AS branch_proposal_status),
               reviewed_by = :by, reviewed_at = now()
         WHERE canvas_app_id = :aid AND name = :name
        RETURNING id
        """,
        {"aid": str(app_id), "name": name, "by": str(reviewer),
         "status": "approved" if approve else "rejected"},
    )
    return await get_branch(conn, project_id, app_id, name)


async def set_protection(
    conn: AsyncConnection, project_id: UUID, app_id: UUID, *, on: bool,
) -> dict[str, Any]:
    """p.617's protection switch. The route decides who may use it."""
    row = await fetch_one(
        conn,
        f"""
        UPDATE canvas_apps SET protected = :on
         WHERE id = :aid AND project_id = :pid
        RETURNING {_COLUMNS}, definition
        """,
        {"aid": str(app_id), "pid": str(project_id), "on": on},
    )
    if row is None:
        raise NotFoundError("canvas app")
    return dict(row)


# ---- publishing ---------------------------------------------------------------
async def set_publish_scope(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    *,
    organisation_id: UUID,
    scope: str,
    group_ids: list[UUID] | None,
) -> dict[str, Any]:
    await get(conn, project_id, app_id)  # 404 if invisible
    if scope == "groups":
        if not group_ids:
            raise ValueError("choose at least one group to publish to")
        rows = await fetch_all(
            conn,
            "SELECT id FROM groups WHERE organisation_id = :org AND id = ANY(:ids)",
            {"org": str(organisation_id), "ids": [str(g) for g in group_ids]},
        )
        found = {str(r["id"]) for r in rows}
        unknown = [str(g) for g in group_ids if str(g) not in found]
        if unknown:
            raise ValueError(f"unknown group(s): {', '.join(unknown)}")

    # Publishing pins the version viewers see (roadmap 1.7). Saving never
    # touches it, so an author can work on an app all day without anybody
    # watching a half-finished layout - which is what "publish" has to mean
    # for the word to be worth anything.
    #
    # Re-publishing an already-published app moves the pin to the current
    # version: the button says "publish", and publishing what is in front of
    # you is the only thing it could sensibly do. Going private clears it, so
    # a later re-publish pins what is current *then* rather than resurrecting
    # a version nobody has looked at since.
    row = await fetch_one(
        conn,
        f"""
        UPDATE canvas_apps
           SET publish_scope = CAST(:scope AS app_publish_scope),
               published_at = CASE WHEN :scope = 'private' THEN NULL
                                    ELSE COALESCE(published_at, now()) END,
               published_version = CASE
                   WHEN :scope = 'private' THEN NULL
                   WHEN current_version > 0 THEN current_version
                   ELSE NULL END
         WHERE id = :aid
        RETURNING {_COLUMNS}, definition
        """,
        {"scope": scope, "aid": str(app_id)},
    )
    assert row is not None
    await conn.execute(
        text("DELETE FROM canvas_app_shares WHERE canvas_app_id = :aid"), {"aid": str(app_id)}
    )
    if scope == "groups":
        assert group_ids is not None
        for group_id in group_ids:
            await conn.execute(
                text(
                    "INSERT INTO canvas_app_shares (canvas_app_id, group_id) VALUES (:aid, :gid)"
                ),
                {"aid": str(app_id), "gid": str(group_id)},
            )
    return dict(row)


async def list_shares(conn: AsyncConnection, project_id: UUID, app_id: UUID) -> list[dict[str, Any]]:
    await get(conn, project_id, app_id)
    return await fetch_all(
        conn,
        """
        SELECT s.group_id, g.name AS group_name
          FROM canvas_app_shares s JOIN groups g ON g.id = s.group_id
         WHERE s.canvas_app_id = :aid
         ORDER BY g.name
        """,
        {"aid": str(app_id)},
    )


# ---- workspace-wide read path for published apps ------------------------------
async def list_published(conn: AsyncConnection, workspace_id: UUID) -> list[dict[str, Any]]:
    """Apps visible to any workspace member regardless of project
    membership - the counterpart to list_for_project for a "gallery of apps
    shared with me" view. Scoped by the app's own `workspace_id` (db 0161)
    rather than a join to `projects`: `projects` is itself RLS-protected,
    and a permission_mode='custom' project can legitimately hide its own row
    from a user this endpoint exists to serve. The column is copied from the
    project by a trigger, and filtering on it lets the index find this
    workspace's apps before the row policy runs - the per-row
    `rls_project_workspace_id` it replaced ran the policy on every tenant's
    apps first (§826). RLS still independently enforces group-share
    membership for publish_scope='groups' rows."""
    rows = await fetch_all(
        conn,
        f"""
        SELECT {_COLUMNS} FROM canvas_apps
         WHERE publish_scope <> 'private'
           AND workspace_id = :wid
         ORDER BY name
        """,
        {"wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def get_saved(conn: AsyncConnection, workspace_id: UUID, app_id: UUID) -> dict[str, Any]:
    """The app as its *author* last saved it (§314; `workshop` p.166).

        "For testing purposes, you can change the `/latest/` to `/dev/` in the
         URL, and the link will now redirect to the last saved version of the
         Workshop application instead of the last published version."

    **The live definition, which is what `published_version` exists to hide.**
    `get_published` reads the pinned version because publishing is an act
    rather than a checkbox; this is the other half of that decision, and it is
    only useful *because* the two can differ. An app whose author has not saved
    since publishing gives the same answer either way, which is the honest
    result rather than a special case.

    **No `publish_scope` clause, deliberately.** `get_published` has one because
    a private app has no viewers; this is not for viewers. Whether the caller
    may see unpublished work is a permission question and it is answered where
    permissions are — the route — rather than by a WHERE clause that would
    make the refusal look like a missing row.
    """
    row = await fetch_one(
        conn,
        f"""
        SELECT {_columns("a")}, a.definition AS definition
          FROM canvas_apps a
         WHERE a.id = :aid
           AND a.workspace_id = :wid
        """,
        {"aid": str(app_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("canvas app")
    return dict(row)


async def get_published(conn: AsyncConnection, workspace_id: UUID, app_id: UUID) -> dict[str, Any]:
    """A published app as its viewers see it: the *published* version's
    definition, not the live one (roadmap 1.7).

    The row still carries `current_version`, so a caller can tell that the
    author has moved on - but `definition` is what was published, because that
    is the whole point of publishing being an act rather than a checkbox.

    An app whose `published_version` is NULL has been published without ever
    being saved. Its viewers get the live (empty) definition, which is the same
    thing, rather than a 404 for a version row that does not exist.
    """
    row = await fetch_one(
        conn,
        f"""
        SELECT {_columns("a")},
               COALESCE(v.definition, a.definition) AS definition
          FROM canvas_apps a
          LEFT JOIN canvas_app_versions v
                 ON v.canvas_app_id = a.id
                AND v.version_number = a.published_version
         WHERE a.id = :aid AND a.publish_scope <> 'private'
           AND a.workspace_id = :wid
        """,
        {"aid": str(app_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("canvas app")
    return dict(row)
