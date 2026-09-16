"""CSV parsing options (§362; `dataset-preview` p.14, p.24-27, build-order
item 8).

> "Here, users can also apply additional parsing options to drop jagged rows,
>  change encoding, or add additional columns like file path, byte offset for
>  row, import timestamp, or row number." (p.14)

> "CSV schemas can be manipulated in the Edit Schema UI… This will help
>  visualize the options available and how they affect the output dataset."
>  (p.24)

**The file is parsed again from the bytes somebody uploaded**, which is only
possible because those bytes were never thrown away — the upload route has kept
them since the first upload and, until db 0090, nothing could find them again.

Most of what is asserted here is one shape: an option that *changes the
answer*. A parsing option tested against a file it makes no difference to is a
test that cannot fail, so each case below uses a file the default parse reads
wrongly (or refuses) and checks that the option fixes exactly that.
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
from src.services.storage import LocalStorageGateway  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN",
    "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
)

# **Every file here defeats the sniffer, and that was measured rather than
# assumed.** DuckDB's `read_csv_auto` is better than it looks: it finds `;`,
# `|` and tabs on its own, and it skips a `#`-commented preamble. A test built
# on a file it reads correctly would prove nothing about the option under test,
# so each of these was checked to be *wrong by default* first.
PLAIN = b"id,val\n1,10\n2,20\n"
#: `^` is not in the sniffer's candidate set, so this arrives as one column.
CARETS = b"id^val\n1^10\n2^20\n"
#: A row with an extra field makes the sniffer give up on the delimiter
#: altogether — one column called `id,val`, no error, three rows.
JAGGED = b"id,val\n1,10\n2,20,extra\n3,30\n"
#: A preamble the sniffer cannot tell from data, because it has two fields per
#: line like the data does. It becomes the header.
PREAMBLE = b"REPORT,2024\nSOURCE,ledger\nid,val\n1,10\n2,20\n"
#: `NA` keeps both columns as text; naming it makes them numbers.
NULLS = b"id,val\nNA,10\n2,NA\n"
#: Quoted with `|`, which the sniffer does not consider, so the commas inside
#: the quoted field split it and the whole file lands as three nameless
#: columns. A single-quoted file would prove nothing — the sniffer finds `'`.
PIPE_QUOTED = b"id,name\n1,|Smith, John|\n2,|Jones|\n"
LATIN1 = "id,name\n1,café\n2,naïve\n".encode("latin-1")


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("parse-storage")))


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


def upload(client: TestClient, fx: Fixture, rows: bytes, filename: str = "rows.csv") -> dict:
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Parse {uuid.uuid4().hex[:6]}"},
        files={"file": (filename, io.BytesIO(rows), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()


def preview(client: TestClient, fx: Fixture, did: str, **options):
    return client.post(
        f"{base(fx)}/datasets/{did}/parse/preview",
        headers=hdr(fx.editor_sub), json=options,
    )


def apply(client: TestClient, fx: Fixture, did: str, **options):
    return client.post(
        f"{base(fx)}/datasets/{did}/parse", headers=hdr(fx.editor_sub), json=options,
    )


def columns(payload: dict) -> list[str]:
    return [c["name"] for c in payload["columns"]]


# ---- the file that was kept ---------------------------------------------------

def test_the_uploaded_file_is_remembered_so_it_can_be_read_again(
    client: TestClient, fx: Fixture
) -> None:
    """db 0090's whole purpose. The bytes were always there; the name is what
    makes them reachable."""
    created = upload(client, fx, PLAIN, filename="orders-2024.csv")
    assert created["original_filename"] == "orders-2024.csv"


def test_a_dataset_that_was_never_uploaded_says_so_rather_than_failing_later(
    client: TestClient, fx: Fixture
) -> None:
    """A model output has no original file, and a key built for one would 404
    with nothing explaining why."""
    source = upload(client, fx, PLAIN)
    model = client.post(f"{base(fx)}/models", headers=hdr(fx.editor_sub), json={
        "name": f"Copy {uuid.uuid4().hex[:6]}", "code": "SELECT * FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    assert model.status_code == 201, model.text
    run = client.post(
        f"{base(fx)}/models/{model.json()['id']}/run", headers=hdr(fx.editor_sub)
    )
    assert run.status_code in (200, 201), run.text
    output = run.json()["output_dataset"]["id"]

    r = preview(client, fx, output)
    assert r.status_code == 409, r.text
    assert "no uploaded file" in r.text


def test_an_upload_from_before_the_name_was_recorded_is_refused_by_name(
    client: TestClient, fx: Fixture
) -> None:
    """db 0090 does not backfill, because a backfill would have to guess a
    filename and the failure would arrive as a missing object instead of an
    explanation. The refusal is the explanation."""
    created = upload(client, fx, PLAIN)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE datasets SET original_filename = NULL WHERE id = %s", (created["id"],)
        )
    r = preview(client, fx, created["id"])
    assert r.status_code == 409, r.text
    assert "before the original file was recorded" in r.text


# ---- options that change the answer -------------------------------------------

def test_an_unsniffable_delimiter_reads_as_one_column_until_it_is_given(
    client: TestClient, fx: Fixture
) -> None:
    """p.26's `fieldDelimiter`, on a file the sniffer genuinely cannot do.

    A semicolon file would prove nothing — `read_csv_auto` finds `;` on its
    own, which was measured before this test was written. `^` is not in its
    candidate set, so the upload lands as a single column called `id^val` and
    the option is what fixes it.
    """
    created = upload(client, fx, CARETS)
    assert [c["name"] for c in created["table_schema"]] == ["id^val"], "one column, wrongly"

    fixed = preview(client, fx, created["id"], delimiter="^")
    assert fixed.status_code == 200, fixed.text
    assert columns(fixed.json()) == ["id", "val"]


def test_a_jagged_file_needs_both_the_delimiter_and_permission_to_drop_rows(
    client: TestClient, fx: Fixture
) -> None:
    """p.14's "drop jagged rows" / p.26's `jaggedRowBehavior: DROP_ROW`.

    **The default is not an error, which is worse.** A row with an extra field
    makes the sniffer abandon the delimiter entirely, so the file uploads
    happily as one column called `id,val` — a dataset that looks fine and is
    not. Naming the delimiter then *does* error, and dropping the bad row is
    what gets the other two through; each step is asserted, because the pair is
    the whole behaviour.
    """
    created = upload(client, fx, JAGGED, filename="jagged.csv")
    assert [c["name"] for c in created["table_schema"]] == ["id,val"]

    named = preview(client, fx, created["id"], delimiter=",")
    assert named.status_code == 422, named.text

    dropped = preview(client, fx, created["id"], delimiter=",", drop_bad_rows=True)
    assert dropped.status_code == 200, dropped.text
    assert columns(dropped.json()) == ["id", "val"]
    assert dropped.json()["row_count"] == 2, "the two well-formed rows"


def test_an_unsniffable_quote_character_can_be_named(
    client: TestClient, fx: Fixture
) -> None:
    """p.26's `quoteCharacter`, on a file the sniffer cannot do.

    Single quotes would prove nothing — `read_csv_auto` finds those, which was
    measured. `|` it does not consider, so the commas inside `|Smith, John|`
    split the field and the file arrives as three nameless columns with the
    header eaten. Naming the quote character fixes all of it at once, which is
    why both the column names and a value are asserted.
    """
    created = upload(client, fx, PIPE_QUOTED)
    assert [c["name"] for c in created["table_schema"]] == ["column0", "column1", "column2"]

    fixed = preview(client, fx, created["id"], quote="|")
    assert fixed.status_code == 200, fixed.text
    assert columns(fixed.json()) == ["id", "name"]
    assert fixed.json()["rows"][0] == [1, "Smith, John"]


def test_a_preamble_is_skipped_when_asked(client: TestClient, fx: Fixture) -> None:
    """p.26's `skipLines`.

    The preamble has two fields per line like the data does, so the sniffer
    cannot tell it apart and makes a header out of it — a `#`-commented
    preamble is skipped automatically, which was measured, and would have made
    this test unfalsifiable.
    """
    created = upload(client, fx, PREAMBLE)
    assert [c["name"] for c in created["table_schema"]] == ["REPORT", "2024"]

    fixed = preview(client, fx, created["id"], skip_lines=2)
    assert fixed.status_code == 200, fixed.text
    assert columns(fixed.json()) == ["id", "val"]
    assert fixed.json()["row_count"] == 2


def test_naming_the_null_marker_changes_the_values_and_the_types(
    client: TestClient, fx: Fixture
) -> None:
    """p.25's `nullValues`. `NA` in a numeric column keeps the whole column as
    text, which is the quiet version of the failure: nothing errors, and every
    sum downstream is a string comparison."""
    created = upload(client, fx, NULLS)
    assert {c["data_type"] for c in created["table_schema"]} == {"VARCHAR"}

    fixed = preview(client, fx, created["id"], null_values=["NA"])
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["rows"] == [[None, 10], [2, None]]

    # The stored schema is where the *type* is readable. A preview reports
    # DuckDB's Python type names ("NUMBER") rather than SQL ones, which is what
    # `/preview` has always done and is not this unit's to change — so the
    # claim about types is made where types are named.
    applied = apply(client, fx, created["id"], null_values=["NA"])
    assert applied.status_code == 200, applied.text
    assert {c["data_type"] for c in applied.json()["table_schema"]} == {"BIGINT"}


def test_a_file_whose_first_row_is_data_can_say_so(
    client: TestClient, fx: Fixture
) -> None:
    """The inverse of the sniffer's guess: it reads a header where there is
    one, so the option that matters is being able to say there is not."""
    created = upload(client, fx, PLAIN)
    assert [c["name"] for c in created["table_schema"]] == ["id", "val"]

    fixed = preview(client, fx, created["id"], header=False)
    assert fixed.status_code == 200, fixed.text
    assert columns(fixed.json()) == ["column0", "column1"]
    assert fixed.json()["row_count"] == 3, "the header row is data now"


def test_a_latin1_file_cannot_be_uploaded_at_all_and_re_encoding_is_the_fix(
    client: TestClient, fx: Fixture
) -> None:
    """**p.14's "change encoding", and why it is not a nicety here.** This
    DuckDB (1.1.1) has no `encoding` reader option, and a latin-1 file does not
    parse badly — it fails outright with "Invalid unicode". So the bytes are
    decoded before DuckDB sees them, which is the only thing that makes such a
    file loadable."""
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Latin {uuid.uuid4().hex[:6]}"},
        files={"file": ("latin.csv", io.BytesIO(LATIN1), "text/csv")},
    )
    assert r.status_code == 422, r.text
    assert "csv error" in r.text.lower(), r.text


def test_re_encoding_a_file_that_was_uploaded_as_bytes(
    client: TestClient, fx: Fixture, storage: LocalStorageGateway
) -> None:
    """The same file, reachable because the upload kept it — staged directly,
    since the upload route refuses it (above) and that refusal is the point."""
    # Overwrite the kept original with the latin-1 bytes: the dataset exists,
    # and its stored copy is now the file this test is about. Uploading it
    # directly is not an option — the route refuses it, which is the finding
    # the test above records.
    created = upload(client, fx, PLAIN, filename="latin.csv")
    import asyncio

    from src.lib.db import user_connection
    from src.services import datasets as ds_service

    async def key() -> str:
        async with user_connection(uuid.UUID(str(fx.editor))) as conn:
            return await ds_service.original_upload_key(
                conn, uuid.UUID(str(fx.project)), uuid.UUID(created["id"])
            )

    storage.put(asyncio.run(key()), LATIN1)

    as_utf8 = preview(client, fx, created["id"])
    assert as_utf8.status_code == 422, "the default parse still cannot read it"

    fixed = preview(client, fx, created["id"], encoding="latin-1")
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["rows"][0][1] == "café"


def test_an_encoding_the_file_is_not_says_where_it_gave_up(
    client: TestClient, fx: Fixture, storage: LocalStorageGateway
) -> None:
    import asyncio

    from src.lib.db import user_connection
    from src.services import datasets as ds_service

    created = upload(client, fx, PLAIN, filename="utf16.csv")

    async def key() -> str:
        async with user_connection(uuid.UUID(str(fx.editor))) as conn:
            return await ds_service.original_upload_key(
                conn, uuid.UUID(str(fx.project)), uuid.UUID(created["id"])
            )

    storage.put(asyncio.run(key()), LATIN1)
    r = preview(client, fx, created["id"], encoding="utf-16")
    assert r.status_code == 422, r.text
    assert "not utf-16" in r.text


def test_an_encoding_nobody_offers_is_refused(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, PLAIN)
    r = preview(client, fx, created["id"], encoding="ebcdic")
    assert r.status_code == 422, r.text
    assert "unsupported encoding" in r.text


# ---- the columns p.14 adds ----------------------------------------------------

def test_the_added_columns_are_added(client: TestClient, fx: Fixture) -> None:
    """p.14's file path, import timestamp and row number, each asserted where
    it lands rather than only that the count went up."""
    created = upload(client, fx, PLAIN)
    r = preview(
        client, fx, created["id"],
        add_file_path=True, add_imported_at=True, add_row_number=True,
    )
    assert r.status_code == 200, r.text
    names = columns(r.json())
    assert names[:2] == ["id", "val"], "the file's own columns come first"
    assert {"filename", "imported_at", "row_number"} <= set(names)

    by_name = {name: i for i, name in enumerate(names)}
    first, second = r.json()["rows"][0], r.json()["rows"][1]
    assert first[by_name["row_number"]] == 1 and second[by_name["row_number"]] == 2
    assert str(first[by_name["filename"]]).endswith(".csv")
    assert first[by_name["imported_at"]], "an import time is recorded"


def test_each_added_column_is_off_by_default(client: TestClient, fx: Fixture) -> None:
    """Three separate switches, not one. A default parse that quietly added a
    row number would change every dataset's schema."""
    created = upload(client, fx, PLAIN)
    assert columns(preview(client, fx, created["id"]).json()) == ["id", "val"]
    only_rows = preview(client, fx, created["id"], add_row_number=True)
    assert columns(only_rows.json()) == ["id", "val", "row_number"]


# ---- preview and apply are the same parse -------------------------------------

def test_a_preview_writes_nothing(client: TestClient, fx: Fixture) -> None:
    """p.24's rehearsal. A preview that versioned the dataset would make
    trying an option the same act as choosing it."""
    created = upload(client, fx, CARETS)
    assert preview(client, fx, created["id"], delimiter="^").status_code == 200
    after = client.get(
        f"{base(fx)}/datasets/{created['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert after["current_version"] == 1
    assert [c["name"] for c in after["table_schema"]] == ["id^val"], "still parsed the old way"


def test_applying_gives_exactly_what_the_preview_showed(
    client: TestClient, fx: Fixture
) -> None:
    """**The claim that makes a preview worth having.** Two code paths would
    eventually disagree and the one somebody trusted would be the preview, so
    there is one parse behind both — asserted rather than left to the reader of
    `_parse_original`.
    """
    created = upload(client, fx, CARETS)
    rehearsed = preview(client, fx, created["id"], delimiter="^", add_row_number=True)
    assert rehearsed.status_code == 200, rehearsed.text

    applied = apply(client, fx, created["id"], delimiter="^", add_row_number=True)
    assert applied.status_code == 200, applied.text
    assert applied.json()["current_version"] == 2
    assert [c["name"] for c in applied.json()["table_schema"]] == columns(rehearsed.json())
    assert applied.json()["row_count"] == rehearsed.json()["row_count"]

    rows = client.post(
        f"{base(fx)}/datasets/{created['id']}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT sum(val) AS total FROM dataset"},
    )
    assert rows.json()["rows"] == [[30]]


def test_re_parsing_keeps_the_version_that_was_parsed_wrongly(
    client: TestClient, fx: Fixture
) -> None:
    """§361's rule, which this inherits: the bad version stays readable,
    because a run stamped with it has to keep resolving to what it was."""
    created = upload(client, fx, CARETS)
    assert apply(client, fx, created["id"], delimiter="^").status_code == 200
    versions = client.get(
        f"{base(fx)}/datasets/{created['id']}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert versions[0]["produced_by_kind"] == "reparse"
    assert [c["name"] for c in versions[1]["table_schema"]] == ["id^val"], \
        "v1 still describes the wrong parse"


def test_parsing_with_nothing_chosen_reproduces_the_upload(
    client: TestClient, fx: Fixture
) -> None:
    """**A re-parse that changes nothing must change nothing.** The upload path
    calls `read_csv_auto` and this one builds a `read_csv` call; if the two
    disagreed on defaults, pressing Apply without touching a field would
    silently rewrite the dataset."""
    created = upload(client, fx, PLAIN)
    applied = apply(client, fx, created["id"])
    assert applied.status_code == 200, applied.text
    assert applied.json()["table_schema"] == created["table_schema"]
    assert applied.json()["row_count"] == created["row_count"]


# ---- access -------------------------------------------------------------------

def test_parsing_needs_more_than_reading(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, CARETS)
    for path in (f"/parse/preview", "/parse"):
        r = client.post(
            f"{base(fx)}/datasets/{created['id']}{path}",
            headers=hdr(fx.viewer_sub), json={"delimiter": "^"},
        )
        assert r.status_code == 403, (path, r.text)


def test_a_re_parse_is_audited(client: TestClient, fx: Fixture) -> None:
    created = upload(client, fx, CARETS)
    assert apply(client, fx, created["id"], delimiter="^").status_code == 200
    entries = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    assert "dataset.reparse" in {e["action"] for e in entries.json()}
