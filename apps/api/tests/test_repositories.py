"""Repository storage (roadmap phase 2, item 2.1).

The proofs decision 0003 promises, against real Postgres. What is under test is
not "does a commit round-trip" but the properties the decision rests on:
content is stored once, history is immutable, a branch only moves forward, and
deleting a pointer never deletes what it pointed at.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture  # noqa: E402
from src.lib.errors import ConflictError  # noqa: E402
from src.services import repositories as repos  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["DATABASE_URL"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def repo(fx: Fixture) -> dict[str, str]:
    """A repository row to hang objects off. Created directly: `code_repos`
    has no writer yet (decision 0001 left it with none, and 2.x is what gives
    it one), so there is no endpoint to go through."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        tag = uuid.uuid4().hex[:8]
        repo_id = conn.execute(
            """INSERT INTO code_repos (project_id, name, slug, s3_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (fx.project, f"Transforms {tag}", f"transforms-{tag}", f"repos/{tag}/", fx.owner),
        ).fetchone()[0]
    return {"id": str(repo_id), "workspace_id": str(fx.workspace), "owner": str(fx.owner)}


@pytest.fixture()
async def conn():
    """A superuser connection: these tests exercise the storage layer directly,
    below the RLS-scoped request path, so there is no `app.user_id` to set."""
    engine = create_async_engine(APP_DSN.replace("platform_app", "platform"))
    async with engine.begin() as connection:
        yield connection
    await engine.dispose()


async def commit_files(conn, repo, files, *, branch="main", message="") -> dict:
    return await repos.commit(
        conn,
        repo_id=uuid.UUID(repo["id"]),
        workspace_id=uuid.UUID(repo["workspace_id"]),
        branch=branch,
        files=files,
        message=message,
        created_by=uuid.UUID(repo["owner"]),
    )


# ---- paths -------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad", ["", "   ", "../secrets.sql", "a/../../b.sql", "/", "."]
)
def test_a_path_that_escapes_the_repository_is_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        repos.normalise_path(bad)


def test_paths_are_normalised_the_same_way_storage_keys_are() -> None:
    assert repos.normalise_path("/src/model.sql") == "src/model.sql"
    assert repos.normalise_path("src\\model.sql") == "src/model.sql"
    assert repos.normalise_path("./src//model.sql") == "src/model.sql"


# ---- blobs -------------------------------------------------------------------
@pytest.mark.anyio
async def test_the_same_content_is_stored_once(conn, repo) -> None:
    """The reason blobs are content-addressed: a file unchanged across a
    hundred commits is one row."""
    content = f"SELECT 1 -- {uuid.uuid4()}"
    sha = await repos.write_blob(conn, workspace_id=uuid.UUID(repo["workspace_id"]), content=content)
    again = await repos.write_blob(conn, workspace_id=uuid.UUID(repo["workspace_id"]), content=content)
    assert sha == again

    count = await conn.exec_driver_sql(
        "SELECT count(*) FROM code_blobs WHERE workspace_id = %s AND sha256 = %s",
        (repo["workspace_id"], sha),
    )
    assert count.scalar() == 1


@pytest.mark.anyio
async def test_two_workspaces_do_not_share_a_blob(conn, repo, fx) -> None:
    """Deduplication is per workspace on purpose: a shared table would make
    "does this hash exist?" a cross-tenant question, and existence is
    information."""
    content = f"SELECT 2 -- {uuid.uuid4()}"
    other_workspace = uuid.uuid4()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as raw:
        raw.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix,
                                       pg_schema, search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (other_workspace, fx.org, f"Other {other_workspace.hex[:6]}",
             f"other-{other_workspace.hex[:6]}", f"workspaces/o-{other_workspace.hex[:6]}/",
             f"ws_{other_workspace.hex[:6]}", f"o-{other_workspace.hex[:6]}", fx.owner),
        )

    await repos.write_blob(conn, workspace_id=uuid.UUID(repo["workspace_id"]), content=content)
    await repos.write_blob(conn, workspace_id=other_workspace, content=content)
    rows = await conn.exec_driver_sql(
        "SELECT count(*) FROM code_blobs WHERE sha256 = %s", (repos.blob_sha(content),)
    )
    assert rows.scalar() == 2


@pytest.mark.anyio
async def test_a_file_over_the_limit_is_refused_at_the_door(conn, repo) -> None:
    with pytest.raises(ValueError, match="larger than"):
        await repos.write_blob(
            conn,
            workspace_id=uuid.UUID(repo["workspace_id"]),
            content="x" * (repos.MAX_FILE_BYTES + 1),
        )


# ---- commits -----------------------------------------------------------------
@pytest.mark.anyio
async def test_a_commit_is_the_whole_snapshot(conn, repo) -> None:
    """`files` is the complete tree, not a patch - so the commit *is* the
    answer to "what did the repository look like"."""
    tag = uuid.uuid4().hex[:6]
    first = await commit_files(
        conn, repo,
        {"src/a.sql": "SELECT 1", "README.md": f"hello {tag}"},
        branch=f"b-{tag}", message="first",
    )
    tree = await repos.read_tree(
        conn, workspace_id=uuid.UUID(repo["workspace_id"]), commit_id=first["id"]
    )
    assert tree == {"README.md": f"hello {tag}", "src/a.sql": "SELECT 1"}


@pytest.mark.anyio
async def test_a_commit_records_its_parent_and_moves_the_branch(conn, repo) -> None:
    tag = uuid.uuid4().hex[:6]
    branch = f"b-{tag}"
    first = await commit_files(conn, repo, {"a.sql": "SELECT 1"}, branch=branch)
    second = await commit_files(conn, repo, {"a.sql": "SELECT 2"}, branch=branch)

    assert second["parent_id"] == first["id"]
    head = await repos.branch_head(conn, repo_id=uuid.UUID(repo["id"]), name=branch)
    assert head["head_commit_id"] == second["id"]

    # …and the first commit still reads as it did. History is immutable.
    old = await repos.read_tree(
        conn, workspace_id=uuid.UUID(repo["workspace_id"]), commit_id=first["id"]
    )
    assert old == {"a.sql": "SELECT 1"}


@pytest.mark.anyio
async def test_a_duplicate_path_in_one_commit_is_refused(conn, repo) -> None:
    with pytest.raises(ValueError, match="twice"):
        await commit_files(
            conn, repo, {"a.sql": "SELECT 1", "/a.sql": "SELECT 2"},
            branch=f"b-{uuid.uuid4().hex[:6]}",
        )


# ---- diffs -------------------------------------------------------------------
def test_a_diff_is_three_sets() -> None:
    before = {"keep.sql": "aaa", "change.sql": "bbb", "gone.sql": "ccc"}
    after = {"keep.sql": "aaa", "change.sql": "zzz", "new.sql": "ddd"}
    assert repos.diff(before, after) == {
        "added": ["new.sql"],
        "deleted": ["gone.sql"],
        "modified": ["change.sql"],
    }


def test_a_file_with_identical_content_is_unchanged() -> None:
    """Addresses are compared, not contents - which is the answer a reviewer
    wants and the one a line-by-line comparison would spend real time on."""
    same = repos.blob_sha("SELECT 1")
    assert repos.diff({"a.sql": same}, {"a.sql": same})["modified"] == []


# ---- branches ----------------------------------------------------------------
@pytest.mark.anyio
async def test_a_branch_moves_forward(conn, repo) -> None:
    tag = uuid.uuid4().hex[:6]
    main = f"b-{tag}"
    first = await commit_files(conn, repo, {"a.sql": "1"}, branch=main)
    second = await commit_files(conn, repo, {"a.sql": "2"}, branch=main)

    side = await repos.create_branch(
        conn, repo_id=uuid.UUID(repo["id"]), name=f"side-{tag}",
        from_commit=first["id"], created_by=uuid.UUID(repo["owner"]),
    )
    assert side["head_commit_id"] == first["id"]

    await repos.move_branch(
        conn, repo_id=uuid.UUID(repo["id"]), name=f"side-{tag}", to_commit=second["id"]
    )
    head = await repos.branch_head(conn, repo_id=uuid.UUID(repo["id"]), name=f"side-{tag}")
    assert head["head_commit_id"] == second["id"]


@pytest.mark.anyio
async def test_a_non_fast_forward_move_is_refused_and_says_what_it_would_lose(
    conn, repo
) -> None:
    """Accepting it would discard commits - silently, and permanently for
    anything not published. This is the rule fast-forward-only exists for."""
    tag = uuid.uuid4().hex[:6]
    main = f"b-{tag}"
    first = await commit_files(conn, repo, {"a.sql": "1"}, branch=main)
    await commit_files(conn, repo, {"a.sql": "2"}, branch=main)

    with pytest.raises(ConflictError) as caught:
        await repos.move_branch(
            conn, repo_id=uuid.UUID(repo["id"]), name=main, to_commit=first["id"]
        )
    assert "discard commits" in str(caught.value.detail)
    assert main in str(caught.value.detail)


@pytest.mark.anyio
async def test_deleting_a_branch_leaves_its_commits_readable(conn, repo) -> None:
    """They are still referenced by anything published from them, and a
    version whose commit vanished would be a record that changed after the
    fact."""
    tag = uuid.uuid4().hex[:6]
    branch = f"b-{tag}"
    made = await commit_files(conn, repo, {"a.sql": "SELECT 9"}, branch=branch)

    await repos.delete_branch(conn, repo_id=uuid.UUID(repo["id"]), name=branch)
    assert await repos.branch_head(conn, repo_id=uuid.UUID(repo["id"]), name=branch) is None

    tree = await repos.read_tree(
        conn, workspace_id=uuid.UUID(repo["workspace_id"]), commit_id=made["id"]
    )
    assert tree == {"a.sql": "SELECT 9"}


@pytest.mark.anyio
async def test_a_published_version_pins_its_commit(conn, repo, fx) -> None:
    """The constraint the whole decision is shaped around: a run's stamped
    version resolves to exactly one piece of code, forever. The commit cannot
    be deleted out from under it, and the version keeps its own copy of the
    source regardless.

    All on one connection: the commit lives in this test's open transaction, so
    a second connection could not see it to reference it.
    """
    tag = uuid.uuid4().hex[:6]
    made = await commit_files(conn, repo, {"m.sql": "SELECT 42"}, branch=f"b-{tag}")

    model = await conn.exec_driver_sql(
        "INSERT INTO models (project_id, name, language, code) "
        "VALUES (%s,%s,'sql','SELECT 42') RETURNING id",
        (str(fx.project), f"Published {tag}"),
    )
    model_id = model.scalar()
    await conn.exec_driver_sql(
        "INSERT INTO model_versions (model_id, version_number, code, "
        "source_commit_id, source_path) VALUES (%s, 1, 'SELECT 42', %s, 'm.sql')",
        (str(model_id), str(made["id"])),
    )

    # A savepoint, so the refused delete does not poison the surrounding
    # transaction and take the rest of the assertions with it.
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.exec_driver_sql(
                "DELETE FROM code_commits WHERE id = %s", (str(made["id"]),)
            )

    # The version still reads, and still carries its own copy of the source.
    version = await conn.exec_driver_sql(
        "SELECT code, source_path FROM model_versions WHERE model_id = %s",
        (str(model_id),),
    )
    assert version.fetchone() == ("SELECT 42", "m.sql")


# ---- comparing and merging (roadmap 2.4) -------------------------------------
async def _branch_at(conn, repo, name, commit_id):
    return await repos.create_branch(
        conn, repo_id=uuid.UUID(repo["id"]), name=name,
        from_commit=commit_id, created_by=uuid.UUID(repo["owner"]),
    )


@pytest.mark.anyio
async def test_a_branch_that_is_ahead_can_fast_forward(conn, repo) -> None:
    tag = uuid.uuid4().hex[:6]
    trunk, side = f"t-{tag}", f"s-{tag}"
    first = await commit_files(conn, repo, {"a.sql": "1"}, branch=trunk)
    await _branch_at(conn, repo, side, first["id"])
    second = await commit_files(conn, repo, {"a.sql": "2"}, branch=side)
    third = await commit_files(conn, repo, {"a.sql": "2", "b.sql": "9"}, branch=side)

    seen = await repos.compare_branches(
        conn, repo_id=uuid.UUID(repo["id"]), base=trunk, head=side
    )
    assert seen["state"] == "fast_forward"
    assert seen["ahead_by"] == 2 and seen["behind_by"] == 0
    # Newest first, and in the order of the history rather than of the clock:
    # two commits made in the same second have an order in one and not in the
    # other.
    assert [c["id"] for c in seen["commits"]] == [third["id"], second["id"]]
    # The files, against the *base*, not against the previous commit: what
    # merging would change, which is the question the screen is asking.
    assert seen["files"] == {"added": ["b.sql"], "deleted": [], "modified": ["a.sql"]}

    done = await repos.merge_branch(
        conn, repo_id=uuid.UUID(repo["id"]), base=trunk, head=side
    )
    assert done["merged"] is True
    head = await repos.branch_head(conn, repo_id=uuid.UUID(repo["id"]), name=trunk)
    assert head["head_commit_id"] == third["id"]


@pytest.mark.anyio
async def test_comparing_does_not_merge(conn, repo) -> None:
    """The whole point of a comparison is that it is safe to look at."""
    tag = uuid.uuid4().hex[:6]
    trunk, side = f"t-{tag}", f"s-{tag}"
    first = await commit_files(conn, repo, {"a.sql": "1"}, branch=trunk)
    await _branch_at(conn, repo, side, first["id"])
    await commit_files(conn, repo, {"a.sql": "2"}, branch=side)

    await repos.compare_branches(conn, repo_id=uuid.UUID(repo["id"]), base=trunk, head=side)
    head = await repos.branch_head(conn, repo_id=uuid.UUID(repo["id"]), name=trunk)
    assert head["head_commit_id"] == first["id"]


@pytest.mark.anyio
async def test_merging_something_already_landed_changes_nothing_and_is_not_an_error(
    conn, repo
) -> None:
    """A no-op called a failure sends people looking for a problem that is not
    there - and the second click of a double-click is exactly this case."""
    tag = uuid.uuid4().hex[:6]
    trunk, side = f"t-{tag}", f"s-{tag}"
    first = await commit_files(conn, repo, {"a.sql": "1"}, branch=trunk)
    await _branch_at(conn, repo, side, first["id"])
    second = await commit_files(conn, repo, {"a.sql": "2"}, branch=trunk)

    seen = await repos.merge_branch(
        conn, repo_id=uuid.UUID(repo["id"]), base=trunk, head=side
    )
    assert seen["state"] == "contained"
    assert seen["merged"] is False
    assert seen["ahead_by"] == 0 and seen["behind_by"] == 1
    head = await repos.branch_head(conn, repo_id=uuid.UUID(repo["id"]), name=trunk)
    assert head["head_commit_id"] == second["id"]


@pytest.mark.anyio
async def test_identical_branches_have_nothing_to_merge(conn, repo) -> None:
    tag = uuid.uuid4().hex[:6]
    trunk, side = f"t-{tag}", f"s-{tag}"
    made = await commit_files(conn, repo, {"a.sql": "1"}, branch=trunk)
    await _branch_at(conn, repo, side, made["id"])

    seen = await repos.merge_branch(
        conn, repo_id=uuid.UUID(repo["id"]), base=trunk, head=side
    )
    assert seen["state"] == "identical"
    assert seen["merged"] is False
    assert seen["ahead_by"] == 0 and seen["behind_by"] == 0
    assert seen["files"] == {"added": [], "deleted": [], "modified": []}


@pytest.mark.anyio
async def test_diverged_branches_are_refused_with_both_sides_and_the_files(
    conn, repo
) -> None:
    """Fast-forward only (decision 0003). The refusal has to carry enough to
    act on: what is on each side, and which files would have to move."""
    tag = uuid.uuid4().hex[:6]
    trunk, side = f"t-{tag}", f"s-{tag}"
    first = await commit_files(conn, repo, {"a.sql": "1"}, branch=trunk)
    await _branch_at(conn, repo, side, first["id"])
    on_trunk = await commit_files(conn, repo, {"a.sql": "1", "trunk.sql": "t"}, branch=trunk)
    await commit_files(conn, repo, {"a.sql": "1", "side.sql": "s"}, branch=side)

    seen = await repos.compare_branches(
        conn, repo_id=uuid.UUID(repo["id"]), base=trunk, head=side
    )
    assert seen["state"] == "diverged"
    assert seen["ahead_by"] == 1 and seen["behind_by"] == 1

    with pytest.raises(ConflictError) as caught:
        await repos.merge_branch(
            conn, repo_id=uuid.UUID(repo["id"]), base=trunk, head=side
        )
    detail = str(caught.value.detail)
    assert trunk in detail and side in detail
    assert "side.sql" in detail and "trunk.sql" in detail

    # And nothing moved.
    head = await repos.branch_head(conn, repo_id=uuid.UUID(repo["id"]), name=trunk)
    assert head["head_commit_id"] == on_trunk["id"]


@pytest.mark.anyio
async def test_a_branch_cannot_be_merged_into_itself(conn, repo) -> None:
    tag = uuid.uuid4().hex[:6]
    trunk = f"t-{tag}"
    await commit_files(conn, repo, {"a.sql": "1"}, branch=trunk)
    with pytest.raises(ValueError):
        await repos.compare_branches(
            conn, repo_id=uuid.UUID(repo["id"]), base=trunk, head=trunk
        )


@pytest.mark.anyio
async def test_an_empty_branch_fast_forwards_rather_than_diverging(conn, repo) -> None:
    """A branch created before its first commit has no head, and every commit
    descends from nothing. Calling that a divergence would strand a repository
    at its own first merge."""
    tag = uuid.uuid4().hex[:6]
    trunk, side = f"t-{tag}", f"s-{tag}"
    await _branch_at(conn, repo, trunk, None)
    made = await commit_files(conn, repo, {"a.sql": "1"}, branch=side)

    done = await repos.merge_branch(
        conn, repo_id=uuid.UUID(repo["id"]), base=trunk, head=side
    )
    assert done["state"] == "fast_forward" and done["merged"] is True
    head = await repos.branch_head(conn, repo_id=uuid.UUID(repo["id"]), name=trunk)
    assert head["head_commit_id"] == made["id"]


@pytest.mark.anyio
async def test_the_default_branch_cannot_be_deleted(conn, repo) -> None:
    """Deleting it does not fail - it makes the repository read as empty,
    which is indistinguishable from having lost everything."""
    default = (await conn.exec_driver_sql(
        "SELECT default_branch FROM code_repos WHERE id = %s", (repo["id"],)
    )).fetchone()[0]
    await commit_files(conn, repo, {"a.sql": "1"}, branch=default)

    with pytest.raises(ConflictError) as caught:
        await repos.delete_branch(conn, repo_id=uuid.UUID(repo["id"]), name=default)
    assert "default branch" in str(caught.value.detail)
    head = await repos.branch_head(conn, repo_id=uuid.UUID(repo["id"]), name=default)
    assert head is not None
