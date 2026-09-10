"""Moving a directly-authored transform into a repository (B.1; §274).

`transform_publish.py` is the direction that already existed: a file becomes a
model. This is the one that did not, and B.1 is blocked on it — **delete
`code/page.tsx` and every model that has never been in a repository loses its
only editor.** In a project that requires review it loses every editor, because
a direct edit is refused by the gate and there is no commit to publish
(`docs/parity/README.md` records this as the blocker that reorders stage 1).

**What adoption is not.** It does not change what a transform computes. The
code is copied through byte for byte, and the declaration is written from what
the model *already* says its output and inputs are. So it is not subject to the
review gate, which exists for changes to what runs — it is a change to where
the definition is edited from.

**What it is:** a file, a commit, and `models.source_repo_id` — in one
transaction, because a model pointing at a path no commit contains is a model
with no editor at all, which is precisely the state this unit exists to remove.

**One way.** Nothing here hands a model back to direct editing, and that is the
intended end state rather than a gap: B.1 removes direct editing. The obvious
"release" would hand a model back to a surface that is being deleted. Related
and worth knowing: `transform_publish.orphaned()` reports models whose file a
later commit dropped, and deliberately does not delete them — such a model is
stranded until the file comes back, since `models.update` still refuses a
direct edit. That is pre-existing and its remedy is to restore the file.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.errors import ConflictError
from . import models as model_service
from . import repositories as repo_service
from . import transform_declarations as declarations

#: Where an adopted transform goes when the caller does not say. `src/` because
#: that is what every fixture and every example in this repository uses, so a
#: repository somebody adopts into looks like one somebody wrote.
DEFAULT_DIR = "src"

_EXTENSION = {"sql": ".sql", "python": ".py"}


def default_path(name: str, language: str) -> str:
    """A path for this model, from the name it already has.

    Through `datasets.slugify` rather than a second scheme: it yields
    `[a-z0-9_-]`, which is a subset of what a declaration can write, so a name
    that slugifies at all produces a path that is also a writable output name.
    A model whose name cannot slugify is refused by the caller with a better
    message than this function could give.
    """
    from . import datasets as ds_service

    return f"{DEFAULT_DIR}/{ds_service.slugify(name)}{_EXTENSION.get(language, '.sql')}"


def compose(model: dict[str, Any], inputs: dict[str, str], path: str) -> str:
    """The file this model becomes: its declaration, then its code unchanged.

    **And then read back, which is the load-bearing part.** The reader takes
    the leading comment block *only up to the first non-comment line*, so a
    model whose own code begins with comments produces a longer block than the
    header alone — and measured against the real reader, a `-- input: x = y`
    sitting in those comments does not fail, it is *absorbed*: the parse
    succeeds and the transform silently gains an input the model never had.

    So the check is that reading the composed file gives back exactly what the
    model said. Exactly, not "the header is in there": containment passes the
    absorbed-input case, which is the one that matters.
    """
    prefix = declarations.COMMENT_PREFIX[".py" if path.endswith(".py") else ".sql"]
    # Raises UnwritableDeclaration, naming every name that does not fit.
    header = declarations.render(model["name"], inputs, prefix=prefix)
    source = header + "\n" + str(model["code"] or "")

    read_back = declarations.read(path, source)
    if read_back is None or (read_back.output, read_back.inputs) != (model["name"], inputs):
        # Reached when the model's own code carries something the reader takes
        # as part of the declaration. Says what the file would mean rather than
        # only that it is wrong, because the fix is in the code and the author
        # has to find the line.
        got = "nothing" if read_back is None else (
            f"output {read_back.output!r} reading {read_back.inputs or 'nothing'}"
        )
        raise ConflictError(
            f"{model['name']!r} cannot be moved as it stands: with a declaration "
            f"above it, this file would declare {got} rather than output "
            f"{model['name']!r} reading {inputs or 'nothing'}. Its first lines are "
            "comments the declaration reader takes as part of the declaration - "
            "move them below the first statement."
        )
    return source


async def _prepare(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    model_id: UUID,
    path: str | None,
) -> tuple[dict[str, Any], str, str]:
    """One model, checked and composed: the model row, its path, its file.

    Everything here refuses rather than repairs, and every refusal names the
    model - in a batch the whole point of the message is which of the six it
    is about.
    """
    model = await model_service.get(conn, project_id, model_id)
    if model.get("source_repo_id"):
        raise ConflictError(
            f"{model['name']!r} is already authored in a repository, at "
            f"{model['source_path']}"
        )

    language = str(model["language"])
    target = path or default_path(str(model["name"]), language)
    target = repo_service.normalise_path(target)
    # **The extension is not decoration.** `transform_publish` reads a file's
    # language off its path, so a Python model written to a `.sql` file would
    # publish back as SQL and be handed to DuckDB. Refused rather than
    # corrected, because a caller that asked for the wrong one is confused
    # about something and a silent rename hides it.
    wanted = _EXTENSION.get(language, ".sql")
    if not target.endswith(wanted):
        raise ConflictError(
            f"{model['name']!r} is a {language} transform, so its file has to end "
            f"in {wanted} - publishing reads the language from the path"
        )

    rows = await model_service.list_inputs(conn, model_id)
    inputs = {str(r["input_alias"]): str(r["dataset_name"]) for r in rows}
    return model, target, compose(model, inputs, target)


async def adopt_many(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    workspace_id: UUID,
    models: list[tuple[UUID, str | None]],
    repo_id: UUID,
    branch: str,
    actor_id: UUID,
    message: str | None = None,
) -> list[dict[str, Any]]:
    """Move several transforms into a repository as **one commit** (§289).

    **This is what the change set becomes.** Decision 0001 called the change
    set "the one genuinely new concept" - *"these three transforms changed
    together, for one reason"* - and B.1 deletes the only screen that can make
    one. A commit says the same thing about a repository's files, so the
    successor to a change set over directly-authored transforms is: adopt them
    together, then commit together. That only works if adopting *is* together;
    six adoptions are six commits and six unrelated moves in the history.

    **All of them or none.** A batch that adopted four and refused two would
    leave the project in a state nobody asked for, and the person then has to
    work out which four - so every model is checked before any file is
    written, and the refusal names the model it is about.
    """
    # Raises NotFoundError through RLS if it is not this project's, which is
    # the answer db 0006 gives everywhere: a repository in another project does
    # not exist rather than being forbidden.
    await repo_service.get_repository(conn, project_id=project_id, repo_id=repo_id)
    if not models:
        # `ValueError`, so this answers 422 like `_write_files`' "a proposal
        # needs at least one file" - a request naming nothing is malformed
        # rather than in conflict with anything. **The route does not repeat
        # it**: a `min_length=1` on the field would be a second rule with a
        # second message, and whichever fired first would be the one nobody
        # could find in the code (§213).
        raise ValueError("no transforms to move")

    prepared: list[tuple[UUID, dict[str, Any], str, str]] = []
    for model_id, path in models:
        model, target, source = await _prepare(
            conn, project_id=project_id, model_id=model_id, path=path
        )
        prepared.append((model_id, model, target, source))

    # **The whole tree, because `commit` takes a snapshot rather than a patch**
    # (decision 0003). A branch that does not exist yet is not an error: the
    # first adoption into an empty repository is the commit that creates it.
    head = await repo_service.branch_head(conn, repo_id=repo_id, name=branch)
    files: dict[str, str] = {}
    if head is not None and head.get("head_commit_id"):
        files = await repo_service.read_tree(
            conn, workspace_id=workspace_id,
            commit_id=UUID(str(head["head_commit_id"])),
        )

    # **Two models can want the same path, and only a batch can find out.**
    # `default_path` slugifies the name, so "Daily orders" and "Daily Orders!"
    # both become `src/daily_orders.sql`. Adopted one at a time the second one
    # collides with the *tree* and is refused; adopted together there is no
    # tree between them, and without this the second would silently overwrite
    # the first - one file, two models pointing at it, and a publish that
    # renames one of them.
    claimed: dict[str, str] = {}
    for _, model, target, _source in prepared:
        if target in files:
            raise ConflictError(
                f"{target} already exists on {branch} - choose another path for "
                f"{model['name']!r}, or publish the file that is already there"
            )
        if target in claimed:
            raise ConflictError(
                f"{model['name']!r} and {claimed[target]!r} would both be written to "
                f"{target} - give one of them a path of its own"
            )
        claimed[target] = str(model["name"])

    names = [str(model["name"]) for _, model, _t, _s in prepared]
    made = await repo_service.commit(
        conn,
        repo_id=repo_id,
        workspace_id=workspace_id,
        branch=branch,
        files={**files, **{t: s for _id, _m, t, s in prepared}},
        message=message or default_message(names),
        created_by=actor_id,
    )

    # **All of them, or none.** A model pointing at a path no commit contains
    # has no editor at all, and a file nothing points at is published as a
    # *new* model on the next publish - two different broken states, one
    # transaction.
    out: list[dict[str, Any]] = []
    for model_id, _model, target, _source in prepared:
        await conn.exec_driver_sql(
            "UPDATE models SET source_repo_id = %s, source_path = %s WHERE id = %s",
            (str(repo_id), target, str(model_id)),
        )
        out.append({
            "model_id": str(model_id),
            "repository_id": str(repo_id),
            "branch": branch,
            "path": target,
            "commit_id": str(made["id"]),
        })
    return out


def default_message(names: list[str]) -> str:
    """What the commit says when the caller does not.

    Names them up to a point and then counts, because a commit message listing
    forty transforms is a commit message nobody reads - and the first few are
    what makes it recognisable in a log.
    """
    if len(names) == 1:
        return f"Move {names[0]} into this repository"
    if len(names) <= 3:
        return f"Move {', '.join(names)} into this repository"
    return (
        f"Move {', '.join(names[:3])} and {len(names) - 3} more "
        "into this repository"
    )


async def adopt(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    workspace_id: UUID,
    model_id: UUID,
    repo_id: UUID,
    branch: str,
    path: str | None,
    actor_id: UUID,
) -> dict[str, Any]:
    """One model, through the same code as many (§289).

    Kept as its own function because the single case has its own route and its
    own screen, but it is `adopt_many` with a list of one - a second
    implementation would be a second set of refusals, and the two would drift
    the first time either was improved.
    """
    done = await adopt_many(
        conn,
        project_id=project_id,
        workspace_id=workspace_id,
        models=[(model_id, path)],
        repo_id=repo_id,
        branch=branch,
        actor_id=actor_id,
    )
    return done[0]
