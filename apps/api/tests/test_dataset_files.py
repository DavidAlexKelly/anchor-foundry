"""Files uploaded into a dataset that already exists (§746; `dataset-preview`
p.10; db 0143).

> "If the filename and schema of the new file are identical to a previous
>  upload, you can update data in the existing dataset. If the filename is
>  different from previous uploads, you can append data to an existing
>  dataset." (p.10)

The filename decides between the two, and the columns decide whether either
is allowed. Every case below checks the dataset's rows afterwards, not only
the status code: a replace that appended, or a refusal that still wrote, would
pass a test that read only the response.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import dataset_engine as engine  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN",
    "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
)

JANUARY = b"id,val\n1,10\n2,20\n"
FEBRUARY = b"id,val\n3,30\n"
JANUARY_FIXED = b"id,val\n1,11\n2,21\n4,41\n"
#: The same names with another type: `val` reads as text.
RETYPED = b"id,val\n5,high\n"
WIDER = b"id,val,note\n6,60,x\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("file-storage")))


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
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def upload(client: TestClient, fx: Fixture, rows: bytes, filename: str = "january.csv") -> dict:
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Files {uuid.uuid4().hex[:6]}"},
        files={"file": (filename, io.BytesIO(rows), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()


def add(client: TestClient, fx: Fixture, did: str, rows: bytes, filename: str, sub: str | None = None):
    return client.post(
        f"{base(fx)}/datasets/{did}/files", headers=hdr(sub or fx.editor_sub),
        files={"file": (filename, io.BytesIO(rows), "text/csv")},
    )


def rows(client: TestClient, fx: Fixture, did: str) -> list[list]:
    r = client.get(f"{base(fx)}/datasets/{did}/preview", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return sorted(r.json()["rows"])


def files(client: TestClient, fx: Fixture, did: str) -> list[tuple[str, int]]:
    r = client.get(f"{base(fx)}/datasets/{did}/files", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return [(f["filename"], f["version_number"]) for f in r.json()]


def origin_note(client: TestClient, fx: Fixture, did: str) -> str | None:
    r = client.get(f"{base(fx)}/datasets/{did}/origin", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()["note"]


def test_a_new_name_appends_to_the_dataset(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, JANUARY)
    assert files(client, fx, created["id"]) == [("january.csv", 1)]
    r = add(client, fx, created["id"], FEBRUARY, "february.csv")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["mode"], body["filename"]) == ("append", "february.csv")
    assert (body["dataset"]["row_count"], body["dataset"]["current_version"]) == (3, 2)
    assert rows(client, fx, created["id"]) == [[1, 10], [2, 20], [3, 30]]
    assert files(client, fx, created["id"]) == [("january.csv", 1), ("february.csv", 2)]
    assert origin_note(client, fx, created["id"]) == "uploaded as february.csv"


def test_the_same_name_and_columns_replace_that_file(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, JANUARY)
    assert add(client, fx, created["id"], FEBRUARY, "february.csv").status_code == 200
    r = add(client, fx, created["id"], JANUARY_FIXED, "january.csv")
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "update"
    # January's rows are the new ones, February's are untouched, and nothing
    # of the old January is left.
    assert rows(client, fx, created["id"]) == [[1, 11], [2, 21], [3, 30], [4, 41]]
    assert files(client, fx, created["id"]) == [("february.csv", 2), ("january.csv", 3)]
    assert origin_note(client, fx, created["id"]) == "uploaded as january.csv"
    # The versions already written still hold what they held.
    back = client.post(f"{base(fx)}/datasets/{created['id']}/rollback",
                       headers=hdr(fx.editor_sub), json={"version_number": 1})
    assert back.status_code == 200, back.text
    assert rows(client, fx, created["id"]) == [[1, 10], [2, 20]]


def test_the_same_name_with_other_columns_is_refused_and_writes_nothing(
    client: TestClient, fx: Fixture
) -> None:
    created = upload(client, fx, JANUARY)
    r = add(client, fx, created["id"], RETYPED, "january.csv")
    assert r.status_code == 409, r.text
    assert "january.csv is already in this dataset, whose files read as id BIGINT, val BIGINT, so this file cannot replace it" in r.text
    assert "it reads as id BIGINT, val VARCHAR" in r.text
    detail = client.get(f"{base(fx)}/datasets/{created['id']}", headers=hdr(fx.viewer_sub)).json()
    assert detail["current_version"] == 1
    assert files(client, fx, created["id"]) == [("january.csv", 1)]
    # The kept original is still the old file: a re-parse reads January.
    again = client.post(f"{base(fx)}/datasets/{created['id']}/parse/preview",
                        headers=hdr(fx.editor_sub), json={})
    assert again.status_code == 200, again.text
    assert sorted(again.json()["rows"]) == [[1, 10], [2, 20]]


def test_a_new_name_with_other_columns_is_refused(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, JANUARY)
    r = add(client, fx, created["id"], WIDER, "march.csv")
    assert r.status_code == 409, r.text
    assert "march.csv reads as id BIGINT, val BIGINT, note VARCHAR" in r.text
    assert "cannot be added" in r.text
    assert files(client, fx, created["id"]) == [("january.csv", 1)]
    assert rows(client, fx, created["id"]) == [[1, 10], [2, 20]]


def test_a_file_of_another_kind_is_refused(client: TestClient, fx: Fixture) -> None:
    """Same columns, other reader: a re-parse could read the two with no one
    set of options."""
    created = upload(client, fx, JANUARY)
    r = add(client, fx, created["id"], b'{"id": 3, "val": 30}\n', "february.jsonl")
    assert r.status_code == 409, r.text
    assert "this dataset's files are .csv files, so a .jsonl file cannot join them" in r.text
    assert files(client, fx, created["id"]) == [("january.csv", 1)]


def test_a_dataset_that_was_not_uploaded_takes_no_file(client: TestClient, fx: Fixture) -> None:
    source = upload(client, fx, JANUARY)
    model = client.post(f"{base(fx)}/models", headers=hdr(fx.editor_sub), json={
        "name": f"Copy {uuid.uuid4().hex[:6]}", "code": "SELECT * FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    assert model.status_code == 201, model.text
    run = client.post(f"{base(fx)}/models/{model.json()['id']}/run", headers=hdr(fx.editor_sub))
    assert run.status_code in (200, 201), run.text
    output = run.json()["output_dataset"]["id"]
    r = add(client, fx, output, FEBRUARY, "february.csv")
    assert r.status_code == 409, r.text
    assert "no uploaded file" in r.text
    assert files(client, fx, output) == []


def test_a_viewer_cannot_add_a_file(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, JANUARY)
    r = add(client, fx, created["id"], FEBRUARY, "february.csv", sub=fx.viewer_sub)
    assert r.status_code == 403, r.text
    assert files(client, fx, created["id"]) == [("january.csv", 1)]


def test_an_unsupported_file_is_refused_before_anything_is_read(
    client: TestClient, fx: Fixture
) -> None:
    created = upload(client, fx, JANUARY)
    r = add(client, fx, created["id"], b"hello", "notes.txt")
    assert r.status_code == 422, r.text
    assert "unsupported file type .txt" in r.text


def test_a_re_parse_reads_every_file(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, JANUARY)
    assert add(client, fx, created["id"], FEBRUARY, "february.csv").status_code == 200
    r = client.post(f"{base(fx)}/datasets/{created['id']}/parse", headers=hdr(fx.editor_sub),
                    json={"add_file_path": True})
    assert r.status_code == 200, r.text
    assert r.json()["row_count"] == 3
    names = [c["name"] for c in r.json()["table_schema"]]
    at = names.index("filename")
    preview = client.get(f"{base(fx)}/datasets/{created['id']}/preview", headers=hdr(fx.viewer_sub))
    # In the order the files joined, not by name: February is read after
    # January though it sorts before it.
    paths = [os.path.basename(str(row[at])) for row in preview.json()["rows"]]
    assert paths == ["january.csv", "january.csv", "february.csv"]
    assert origin_note(client, fx, created["id"]) == "re-parsed from january.csv, february.csv"


def test_the_upload_is_audited_with_its_mode(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, JANUARY)
    assert add(client, fx, created["id"], FEBRUARY, "february.csv").status_code == 200
    assert add(client, fx, created["id"], FEBRUARY, "february.csv").status_code == 200
    with psycopg.connect(ADMIN_DSN) as conn:
        modes = [r[0] for r in conn.execute(
            "SELECT metadata->>'mode' FROM audit_log WHERE action = 'dataset.upload_file' "
            "AND resource_id = %s ORDER BY created_at", (created["id"],)).fetchall()]
    assert modes == ["append", "update"]


def test_combining_refuses_a_file_that_reads_differently(tmp_path) -> None:
    import duckdb

    con = duckdb.connect()
    a, b = str(tmp_path / "a.parquet"), str(tmp_path / "b.parquet")
    con.execute(f"COPY (SELECT 1 AS id) TO '{a}' (FORMAT parquet)")
    con.execute(f"COPY (SELECT 'x' AS id) TO '{b}' (FORMAT parquet)")
    with pytest.raises(engine.DatasetEngineError, match="b.csv does not read with the same columns as a.csv"):
        engine.combine_parquets([("a.csv", a), ("b.csv", b)], str(tmp_path / "out.parquet"))
    schema, count = engine.combine_parquets([("a.csv", a), ("again.csv", a)], str(tmp_path / "o2.parquet"))
    assert ([(c.name, c.data_type) for c in schema], count) == ([("id", "INTEGER")], 2)
    with pytest.raises(engine.DatasetEngineError, match="no file"):
        engine.combine_parquets([], str(tmp_path / "o3.parquet"))


#: `^` is not in DuckDB's delimiter candidate set, so the default read sees
#: one column called `id^val`.
CARETS = b"id^val\n1^10\n2^20\n"


def test_a_file_added_after_a_re_parse_is_read_the_same_way(client: TestClient, fx: Fixture) -> None:
    """p.24: "These parameters are stored in the schema of a dataset." Without
    them, adding a file would read both the default way and undo the re-parse."""
    created = upload(client, fx, CARETS, filename="january.csv")
    assert created["parse_options"] is None
    fixed = client.post(f"{base(fx)}/datasets/{created['id']}/parse", headers=hdr(fx.editor_sub),
                        json={"delimiter": "^"})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["parse_options"]["delimiter"] == "^"
    r = add(client, fx, created["id"], b"id^val\n3^30\n", "february.csv")
    assert r.status_code == 200, r.text
    assert [c["name"] for c in r.json()["dataset"]["table_schema"]] == ["id", "val"]
    assert rows(client, fx, created["id"]) == [[1, 10], [2, 20], [3, 30]]
    # Compared under the stored read too: a file with other columns under it
    # is refused, though both are one column the default way.
    other = add(client, fx, created["id"], b"id^label^x\n3^a^b\n", "march.csv")
    assert other.status_code == 409, other.text


def test_a_re_parse_back_to_the_default_stores_nothing(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, CARETS)
    did = created["id"]
    assert client.post(f"{base(fx)}/datasets/{did}/parse", headers=hdr(fx.editor_sub),
                       json={"delimiter": "^"}).status_code == 200
    back = client.post(f"{base(fx)}/datasets/{did}/parse", headers=hdr(fx.editor_sub), json={})
    assert back.status_code == 200, back.text
    assert back.json()["parse_options"] is None
    r = add(client, fx, did, b"id^val\n3^30\n", "february.csv")
    assert r.status_code == 200, r.text
    assert [c["name"] for c in r.json()["dataset"]["table_schema"]] == ["id^val"]
