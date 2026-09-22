"""Renaming a dataset, and what it costs (§435; `dataset-preview` p.2).

    "The header also allows some file related operations such as sharing,
     moving, renaming, and more." (p.2)

**Renaming here is not a cosmetic change.** A transform declares what it reads
and writes by *name*, and `transform_publish.plan` resolves those names against
`datasets.name` — so a rename edits, at a distance, every file that mentions
the old one. These tests are about the two things that follow from that: a name
addresses exactly one dataset, and a rename says what it will break before it
happens.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import dataset_references as references  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

CSV = b"id,total\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("rename")))


@pytest.fixture(scope="module")
def client(storage: LocalStorageGateway) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(storage)
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def repos(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/repositories"


def upload(client: TestClient, fx: Fixture, name: str) -> dict:
    r = client.post(
        f"{base(fx)}/upload", headers=hdr(fx.editor_sub),
        data={"name": name},
        files={"file": ("orders.csv", io.BytesIO(CSV), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()


def rename(client: TestClient, fx: Fixture, did: str, name: str):
    return client.patch(f"{base(fx)}/{did}", headers=hdr(fx.editor_sub),
                        json={"name": name})


def make_repo(client: TestClient, fx: Fixture) -> dict:
    r = client.post(repos(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Transforms {uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()


def commit(client: TestClient, fx: Fixture, repo_id: str, files: dict) -> dict:
    r = client.post(f"{repos(fx)}/{repo_id}/commits", headers=hdr(fx.editor_sub),
                    json={"branch": "main", "files": files, "message": "a change"})
    assert r.status_code == 201, r.text
    return r.json()


def referenced(client: TestClient, fx: Fixture, did: str) -> dict:
    r = client.get(f"{base(fx)}/{did}/references", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


# ---- a name addresses one dataset -------------------------------------------
def test_a_dataset_can_be_renamed(client: TestClient, fx: Fixture) -> None:
    """**The unit's own feature, and it had no control in the product.** The
    endpoint has taken a name since the dataset routes were written; nothing in
    `apps/web` ever sent one (§278's shape, on a different setting)."""
    made = upload(client, fx, f"orders_{uuid.uuid4().hex[:8]}")
    fresh = f"daily_orders_{uuid.uuid4().hex[:8]}"
    r = rename(client, fx, made["id"], fresh)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == fresh


def test_the_slug_does_not_move_with_the_name(client: TestClient, fx: Fixture) -> None:
    """**A link survives a rename**, which is the point of having two names at
    all — p.2 lists "name" and "display name" as different things. A slug that
    followed the name would turn every saved URL into a 404 the first time
    somebody fixed a typo."""
    made = upload(client, fx, f"orders_{uuid.uuid4().hex[:8]}")
    slug = made["slug"]
    renamed = rename(client, fx, made["id"], f"renamed_{uuid.uuid4().hex[:8]}")
    assert renamed.json()["slug"] == slug


def test_two_datasets_in_a_project_cannot_share_a_name(
    client: TestClient, fx: Fixture
) -> None:
    """**The rule the platform assumed and never wrote down** (db 0099).

    A transform declares what it reads by name, and `plan` resolves it through
    a dictionary keyed on `datasets.name` — so two rows with one name make it
    keep whichever the query returned last, and every transform declaring that
    name reads a table nobody chose. Unreachable until renaming existed,
    because a slug is derived from a name and the slug has always been unique.
    """
    # **A name whose slug differs from it.** A lower-case name and its slug are
    # the same string, so a test asserting "the refusal names the slug" passes
    # on a message that only names the *name* — which is the same conflation
    # §434 found in its completion fixtures.
    first = upload(client, fx, f"Alpha_{uuid.uuid4().hex[:8]}")
    second = upload(client, fx, f"beta_{uuid.uuid4().hex[:8]}")
    assert first["slug"] != first["name"]

    refused = rename(client, fx, second["id"], first["name"])
    assert refused.status_code == 409, refused.text
    # And it says *which* dataset has the name, which a constraint cannot.
    assert first["slug"] in refused.text
    # The refusal left the second one alone rather than half-renaming it.
    still = client.get(f"{base(fx)}/{second['id']}", headers=hdr(fx.viewer_sub))
    assert still.json()["name"] == second["name"]


def test_renaming_a_dataset_to_its_own_name_is_not_a_conflict(
    client: TestClient, fx: Fixture
) -> None:
    """Saving a form without changing the name is the ordinary case, and a
    uniqueness check that counted the row itself would refuse it."""
    made = upload(client, fx, f"same_{uuid.uuid4().hex[:8]}")
    assert rename(client, fx, made["id"], made["name"]).status_code == 200


def test_a_rename_needs_an_editor(client: TestClient, fx: Fixture) -> None:
    made = upload(client, fx, f"gated_{uuid.uuid4().hex[:8]}")
    refused = client.patch(f"{base(fx)}/{made['id']}", headers=hdr(fx.viewer_sub),
                           json={"name": "nope"})
    assert refused.status_code == 403, refused.text


# ---- what names it ----------------------------------------------------------
def test_a_dataset_nothing_names_has_no_warning(client: TestClient, fx: Fixture) -> None:
    made = upload(client, fx, f"lonely_{uuid.uuid4().hex[:8]}")
    found = referenced(client, fx, made["id"])
    assert found == {"reads": [], "writes": [], "warning": None}


def test_a_file_that_reads_it_is_reported_with_its_alias(
    client: TestClient, fx: Fixture
) -> None:
    source = upload(client, fx, f"src_{uuid.uuid4().hex[:8]}")
    repo = make_repo(client, fx)
    out = f"daily_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source['name']}\nSELECT id FROM raw\n",
    })

    found = referenced(client, fx, source["id"])
    assert [r["path"] for r in found["reads"]] == ["src/t.sql"]
    assert found["reads"][0]["aliases"] == ["raw"]
    assert found["reads"][0]["repository"] == repo["name"]
    assert found["writes"] == []
    assert "would be refused at the next publish" in found["warning"]


def test_a_file_that_writes_it_is_reported_as_the_worse_case(
    client: TestClient, fx: Fixture
) -> None:
    """**The failure that does not announce itself.** A reader stops publishing
    and says so; a writer goes on publishing and starts filling a *different*
    table, leaving the renamed one behind with nothing to say so."""
    source = upload(client, fx, f"in_{uuid.uuid4().hex[:8]}")
    out = upload(client, fx, f"out_{uuid.uuid4().hex[:8]}")
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {
        "src/t.sql":
            f"-- output: {out['name']}\n-- input: raw = {source['name']}\n"
            "SELECT id FROM raw\n",
    })

    found = referenced(client, fx, out["id"])
    assert [w["path"] for w in found["writes"]] == ["src/t.sql"]
    assert found["reads"] == []
    assert "create a new dataset under the old name" in found["warning"]


def test_the_warning_says_published_transforms_are_safe(
    client: TestClient, fx: Fixture
) -> None:
    """Half the value of the sentence. `model_inputs` holds a `dataset_id`, so
    a transform that has been published keeps reading the same table whatever
    it is called — and somebody who was not told that would assume the worst
    and not rename anything."""
    source = upload(client, fx, f"safe_{uuid.uuid4().hex[:8]}")
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {
        "src/t.sql":
            f"-- output: d_{uuid.uuid4().hex[:8]}\n-- input: raw = {source['name']}\n"
            "SELECT id FROM raw\n",
    })
    assert "already been published" in referenced(client, fx, source["id"])["warning"]


def test_a_sandbox_branch_is_not_reported(client: TestClient, fx: Fixture) -> None:
    """**The default branch only**, because that is the ref a publish is made
    against (§283) and the one every reader opens. A sandbox naming the old
    dataset is somebody's work in progress, and reporting it would be reporting
    a file whose author has not finished deciding."""
    source = upload(client, fx, f"sandboxed_{uuid.uuid4().hex[:8]}")
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {"README.md": "# nothing declared\n"})
    client.post(f"{repos(fx)}/{repo['id']}/branches", headers=hdr(fx.editor_sub),
                json={"name": "work", "from_branch": "main"})
    r = client.post(f"{repos(fx)}/{repo['id']}/commits", headers=hdr(fx.editor_sub),
                    json={"branch": "work", "message": "wip", "files": {
                        "README.md": "# nothing declared\n",
                        "src/t.sql":
                            f"-- output: d_{uuid.uuid4().hex[:8]}\n"
                            f"-- input: raw = {source['name']}\nSELECT id FROM raw\n",
                    }})
    assert r.status_code == 201, r.text

    assert referenced(client, fx, source["id"]) == {
        "reads": [], "writes": [], "warning": None,
    }


def test_an_empty_repository_is_skipped_rather_than_failing(
    client: TestClient, fx: Fixture
) -> None:
    """A repository nobody has committed to has no tree to read, and a project
    is allowed to contain one."""
    made = upload(client, fx, f"empty_{uuid.uuid4().hex[:8]}")
    make_repo(client, fx)
    assert referenced(client, fx, made["id"])["warning"] is None


def test_a_file_that_will_not_parse_does_not_break_the_answer(
    client: TestClient, fx: Fixture
) -> None:
    """A broken declaration is a problem the Problems panel already reports.
    Refusing to answer "what names this dataset" because an unrelated file is
    malformed would make this screen fail for a reason that has nothing to do
    with it."""
    source = upload(client, fx, f"parse_{uuid.uuid4().hex[:8]}")
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {
        "src/broken.sql": "-- output:\nSELECT 1\n",
        "src/t.sql":
            f"-- output: d_{uuid.uuid4().hex[:8]}\n-- input: raw = {source['name']}\n"
            "SELECT id FROM raw\n",
    })
    assert [r["path"] for r in referenced(client, fx, source["id"])["reads"]] \
        == ["src/t.sql"]


def test_references_are_readable_by_a_viewer(client: TestClient, fx: Fixture) -> None:
    """"What reads this dataset" is a question about understanding the
    pipeline, and a floor above reading would hide the warning from exactly the
    people who should see it before asking somebody else to rename something."""
    made = upload(client, fx, f"viewable_{uuid.uuid4().hex[:8]}")
    r = client.get(f"{base(fx)}/{made['id']}/references", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text


# ---- the sentence -----------------------------------------------------------
def test_the_warning_puts_the_quiet_failure_first() -> None:
    """A reader stops publishing and says so; a writer goes on publishing into
    a different table. The order is which one somebody has to read."""
    said = references.warning(
        {"reads": [{"path": "a.sql"}], "writes": [{"path": "b.sql"}]}, "orders",
    )
    assert said is not None
    assert said.index("old name") < said.index("refused")


def test_the_warning_counts_in_the_singular() -> None:
    one = references.warning({"reads": [{"path": "a.sql"}], "writes": []}, "orders")
    assert one is not None and "1 file reads it" in one
    two = references.warning(
        {"reads": [{"path": "a.sql"}, {"path": "b.sql"}], "writes": []}, "orders",
    )
    assert two is not None and "2 files read it" in two


def test_the_warning_names_the_dataset_in_the_declaration() -> None:
    """`-- output: orders` is the line somebody has to go and change, so the
    sentence writes it out rather than describing it."""
    said = references.warning({"reads": [], "writes": [{"path": "b.sql"}]}, "orders")
    assert said is not None and "`-- output: orders`" in said


def test_nothing_named_is_no_sentence() -> None:
    assert references.warning({"reads": [], "writes": []}, "orders") is None
