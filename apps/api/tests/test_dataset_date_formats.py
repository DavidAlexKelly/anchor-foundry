"""p.26's `dateFormat` (§765; `dataset-preview` p.25-27).

> "dateFormat: Format strings for date parsing in certain columns. A map that
> maps column names to JodaTime DateTimeFormat patterns." (p.26)

As in `test_dataset_parsing.py`, each file here is one the default parse
reads wrongly: either as text, or - worse - as the wrong date.
"""
from __future__ import annotations

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import dataset_engine as engine  # noqa: E402
from test_api import hdr  # noqa: E402
from test_dataset_parsing import (  # noqa: E402,F401
    _fresh_identity_cache, apply, base, client, fx, preview, storage, upload,
)

#: The sniffer reads these as day/month: 3 April and 4 May.
AMBIGUOUS = b"id,when\n1,03/04/2026\n2,04/05/2026\n"
#: The sniffer leaves both as text.
WORDY = b"id,when,at\n1,3 Apr 2026,03/04/2026 14:05\n2,4 May 2026,04/05/2026 09:30\n"
#: One value that fits no pattern, and one empty.
MESSY = b"id,when\n1,03/04/2026\n2,soon\n3,\n"


# ---- the pattern --------------------------------------------------------------

@pytest.mark.parametrize("joda,spelled,has_time", [
    ("dd/MM/yyyy", "%d/%m/%Y", False),
    ("d/M/yy", "%d/%m/%y", False),
    ("yyyyy-MMM-dd", "%Y-%b-%d", False),
    ("EEEE, d MMMMM yyyy", "%A, %d %B %Y", False),
    ("EEE D", "%a %j", False),
    ("yyyy-MM-dd'T'HH:mm:ss.SSSZ", "%Y-%m-%dT%H:%M:%S.%g%z", True),
    ("h:mm a", "%I:%M %p", True),
    ("h:mm", "%I:%M", True),
    ("HH:mm dd/MM/yyyy", "%H:%M %d/%m/%Y", True),
    ("ss.SSSSSS", "%S.%f", True),
    ("yyyy'''s' MM", "%Y's %m", False),
    ("yyyy%MM", "%Y%%%m", False),
    ("'at' 'per%' yyyy", "at per%% %Y", False),
])
def test_a_joda_pattern_is_spelled_for_strptime(joda: str, spelled: str, has_time: bool) -> None:
    assert engine.joda_to_strptime(joda) == (spelled, has_time)


@pytest.mark.parametrize("joda,said", [
    ("yyyy-ww", "'w' in 'yyyy-ww' is not a pattern letter"),
    ("dd 'of MM", "opens a quote it does not close"),
    ("ddd/MM", "'ddd' in 'ddd/MM' is not a field it can read"),
    ("HH:mm:ss.SS", "'SS' in"),
    ("  ", "needs a pattern"),
])
def test_what_cannot_be_translated_is_refused_by_name(joda: str, said: str) -> None:
    with pytest.raises(engine.DatasetEngineError) as caught:
        engine.joda_to_strptime(joda)
    assert said in str(caught.value)


# ---- the parse ------------------------------------------------------------------

def test_a_pattern_decides_which_date_an_ambiguous_value_is(client, fx) -> None:
    created = upload(client, fx, AMBIGUOUS)
    as_sniffed = preview(client, fx, created["id"])
    assert as_sniffed.json()["rows"][0][1] == "2026-04-03"
    r = preview(client, fx, created["id"], date_formats={"when": "MM/dd/yyyy"})
    assert r.status_code == 200, r.text
    assert [row[1] for row in r.json()["rows"]] == ["2026-03-04", "2026-04-05"]


def test_a_pattern_turns_text_into_a_date_or_a_timestamp(client, fx) -> None:
    created = upload(client, fx, WORDY)
    assert {c["name"]: c["data_type"] for c in created["table_schema"]}["when"] == "VARCHAR"
    formats = {"when": "d MMM yyyy", "at": "dd/MM/yyyy HH:mm"}
    r = preview(client, fx, created["id"], date_formats=formats)
    assert r.status_code == 200, r.text
    assert r.json()["rows"][1][1:] == ["2026-05-04", "2026-05-04T09:30:00"]
    applied = apply(client, fx, created["id"], date_formats=formats)
    assert applied.status_code == 200, applied.text
    types = {c["name"]: c["data_type"] for c in applied.json()["table_schema"]}
    assert (types["id"], types["when"], types["at"]) == ("BIGINT", "DATE", "TIMESTAMP")


def test_a_value_that_does_not_match_is_refused_unless_rows_that_do_not_fit_are_dropped(
    client, fx
) -> None:
    created = upload(client, fx, MESSY)
    r = preview(client, fx, created["id"], date_formats={"when": "dd/MM/yyyy"})
    assert r.status_code == 422, r.text
    assert "when: 'soon' does not match 'dd/MM/yyyy'" in r.text
    r = preview(client, fx, created["id"], date_formats={"when": "dd/MM/yyyy"},
                drop_bad_rows=True, add_row_number=True)
    assert r.status_code == 200, r.text
    # The empty one is kept: nothing in it fails to match.
    assert r.json()["rows"] == [[1, "2026-04-03", 1], [3, None, 2]]


def test_a_column_the_file_lacks_is_refused_by_name(client, fx) -> None:
    created = upload(client, fx, AMBIGUOUS)
    r = preview(client, fx, created["id"], date_formats={"wen": "dd/MM/yyyy"})
    assert r.status_code == 422, r.text
    assert "date format for 'wen': the file has no such column (it has id, when)" in r.text
    r = preview(client, fx, created["id"], date_formats={"when": "dd/MM/yyyy ww"})
    assert r.status_code == 422, r.text
    assert "'w' in" in r.text


def test_a_headerless_file_names_its_columns_as_it_reads_them(client, fx) -> None:
    created = upload(client, fx, b"1,03/04/2026\n2,04/05/2026\n")
    r = preview(client, fx, created["id"], header=False,
                date_formats={"column1": "MM/dd/yyyy"})
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0] == [1, "2026-03-04"]


def test_the_formats_are_kept_and_read_a_later_file_the_same_way(client, fx) -> None:
    """p.24's "stored in the schema" (§746): a file added later is read with
    the dataset's options, its date formats included."""
    created = upload(client, fx, AMBIGUOUS)
    assert apply(client, fx, created["id"],
                 date_formats={"when": "MM/dd/yyyy"}).status_code == 200
    r = preview(client, fx, created["id"], date_formats={"when": "MM/dd/yyyy"})
    assert r.json()["rows"][0][1] == "2026-03-04"
    r = client.post(f"{base(fx)}/datasets/{created['id']}/files", headers=hdr(fx.editor_sub),
                    files={"file": ("more.csv", io.BytesIO(b"id,when\n3,12/01/2026\n"),
                                    "text/csv")})
    assert r.status_code in (200, 201), r.text
    rows = client.get(f"{base(fx)}/datasets/{created['id']}/preview",
                      headers=hdr(fx.editor_sub)).json()["rows"]
    assert sorted(str(row[1]) for row in rows) == ["2026-03-04", "2026-04-05", "2026-12-01"]


def test_a_json_file_refuses_date_formats(client, fx) -> None:
    created = upload(client, fx, b'[{"id": 1, "when": "03/04/2026"}]', filename="d.json")
    r = preview(client, fx, created["id"], date_formats={"when": "dd/MM/yyyy"})
    assert r.status_code == 422, r.text
    assert "date formats: only a delimited file has these" in r.text


def test_nothing_chosen_is_the_upload(client, fx) -> None:
    """The defaults are unchanged by the new field, so a parse with nothing set
    still reproduces the upload exactly (and stores nothing)."""
    assert engine.ParseOptions().date_formats == ()
    created = upload(client, fx, AMBIGUOUS)
    r = preview(client, fx, created["id"], date_formats={})
    assert r.json()["rows"][0][1] == "2026-04-03"
