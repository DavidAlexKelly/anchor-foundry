"""p.14's "byte offset for row" (§766; `dataset-preview` p.14).

> "users can also apply additional parsing options to drop jagged rows, change
> encoding, or add additional columns like file path, byte offset for row,
> import timestamp, or row number." (p.14)

DuckDB has no such column, so the offsets are found in the uploaded bytes
(`record_offsets`) and paired with the rows by position. Each file below is
one where a naive count of newlines would give the wrong answer.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import dataset_engine as engine  # noqa: E402
from test_dataset_parsing import (  # noqa: E402,F401
    _fresh_identity_cache, apply, client, columns, fx, preview, storage, upload,
)

PLAIN = b"id,val\n1,10\n2,20\n"
#: A quoted field holding a newline, a doubled quote, a blank line and CRLFs.
AWKWARD = b'id,note\r\n1,"two\r\nlines"\r\n\r\n2,"say ""hi"""\r\n3,plain\r\n'
PREAMBLE = b"REPORT,2024\nSOURCE,ledger\nid,val\n1,10\n2,20\n"


# ---- finding the records --------------------------------------------------------

def test_a_record_begins_after_each_newline_outside_quotes() -> None:
    assert engine.record_offsets(PLAIN, b'"') == [0, 7, 12]
    # The quoted line break and the doubled quotes stay inside their records;
    # the blank line is not one.
    assert engine.record_offsets(AWKWARD, b'"') == [0, 9, 27, 43]


def test_the_quote_is_the_one_named() -> None:
    raw = b"id,note\n1,|a\nb|\n2,|c|\n"
    assert engine.record_offsets(raw, b"|") == [0, 8, 16]
    assert engine.record_offsets(raw, b'"') == [0, 8, 13, 16]


def test_an_escaped_quote_does_not_end_the_quotes() -> None:
    """DuckDB's sniffer finds a backslash escape, and reads `"a\\"` + newline +
    `b"` as one field; so does this, given the escape."""
    raw = b'id,note\n1,"a\\"\nb"\n2,"c\\\\"\n3,d\n'
    assert engine.record_offsets(raw, b'"', b"\\") == [0, 8, 18, 26]
    assert engine.record_offsets(raw, b'"') != [0, 8, 18, 26]
    # An escape outside quotes is an ordinary byte.
    assert engine.record_offsets(b'id\nC:\\\n2\n', b'"', b"\\") == [0, 3, 7]
    # The quote as its own escape is the doubled quote, already handled.
    assert engine.record_offsets(AWKWARD, b'"', b'"') == [0, 9, 27, 43]


def test_a_last_record_with_no_newline_is_still_a_record() -> None:
    assert engine.record_offsets(b"id\n1\n2", b'"') == [0, 3, 5]
    assert engine.record_offsets(b"", b'"') == []
    # A stray carriage return after the last newline is not a record either.
    assert engine.record_offsets(b"id\n1\n\r", b'"') == [0, 3]


# ---- the column -----------------------------------------------------------------

def offsets_of(payload: dict) -> list[int]:
    index = columns(payload).index("byte_offset")
    return [row[index] for row in payload["rows"]]


def test_each_row_says_where_its_record_began(client, fx) -> None:
    created = upload(client, fx, AWKWARD)
    r = preview(client, fx, created["id"], add_byte_offset=True)
    assert r.status_code == 200, r.text
    assert columns(r.json()) == ["id", "note", "byte_offset"]
    assert offsets_of(r.json()) == [9, 27, 43]
    for row, start in zip(r.json()["rows"], offsets_of(r.json())):
        assert AWKWARD[start:].startswith(f"{row[0]},".encode())


def test_the_quote_character_named_is_the_one_records_are_read_with(client, fx) -> None:
    """A file quoted with `|`, which the sniffer does not consider: with the
    quote named, the line break inside the quotes stays inside its record."""
    created = upload(client, fx, b"id,note\n1,|a\nb|\n2,c\n")
    r = preview(client, fx, created["id"], add_byte_offset=True, quote="|", delimiter=",")
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [[1, "a\nb", 8], [2, "c", 16]]


def test_skipped_lines_and_the_header_come_before_the_rows(client, fx) -> None:
    created = upload(client, fx, PREAMBLE)
    r = preview(client, fx, created["id"], add_byte_offset=True, skip_lines=2,
                add_row_number=True)
    assert r.status_code == 200, r.text
    assert columns(r.json()) == ["id", "val", "byte_offset", "row_number"]
    assert r.json()["rows"] == [[1, 10, 33, 1], [2, 20, 38, 2]]


def test_an_escaped_quote_in_a_file_keeps_its_rows_lined_up(client, fx) -> None:
    raw = b'id,note\n1,"a\\"\nb"\n2,c\n'
    created = upload(client, fx, raw)
    r = preview(client, fx, created["id"], add_byte_offset=True)
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [[1, 'a"\nb', 8], [2, "c", 18]]


def test_the_offset_is_into_the_file_as_uploaded(client, fx, storage) -> None:
    """A re-encoded file is read as UTF-8, where é is two bytes; the offset
    is into the latin-1 bytes somebody uploaded, where it is one. Staged as
    `test_re_encoding_a_file_that_was_uploaded_as_bytes` stages it, since the
    upload route refuses latin-1."""
    import asyncio
    import uuid

    from src.lib.db import user_connection
    from src.services import datasets as ds_service

    raw = "id,name\n1,café\n2,b\n".encode("latin-1")
    created = upload(client, fx, PLAIN)

    async def key() -> str:
        async with user_connection(uuid.UUID(str(fx.editor))) as conn:
            [(_name, kept)] = await ds_service.upload_files(
                conn, uuid.UUID(str(fx.project)), uuid.UUID(created["id"]))
            return kept

    storage.put(asyncio.run(key()), raw)
    r = preview(client, fx, created["id"], encoding="latin-1", add_byte_offset=True)
    assert r.status_code == 200, r.text
    assert offsets_of(r.json()) == [8, 15]


def test_it_is_applied_and_kept(client, fx) -> None:
    created = upload(client, fx, PLAIN)
    r = apply(client, fx, created["id"], add_byte_offset=True)
    assert r.status_code == 200, r.text
    schema = {c["name"]: c["data_type"] for c in r.json()["table_schema"]}
    assert schema["byte_offset"] == "BIGINT"
    assert r.json()["parse_options"]["add_byte_offset"] is True


@pytest.mark.parametrize("options,said", [
    ({"drop_bad_rows": True}, "cannot be given when rows that do not fit are dropped"),
    ({"encoding": "utf-16"}, "cannot be found in a UTF-16 file"),
])
def test_what_would_misplace_the_offsets_is_refused(client, fx, options, said) -> None:
    # Said before any re-encoding runs: PLAIN is not UTF-16, and the refusal
    # is the combination's, not the decoder's.
    created = upload(client, fx, PLAIN)
    r = preview(client, fx, created["id"], add_byte_offset=True, **options)
    assert r.status_code == 422, r.text
    assert said in r.text


@pytest.mark.parametrize("found", [[0, 8, 12, 16, 20, 24], []])
def test_records_that_do_not_line_up_are_refused_rather_than_misnumbered(
    tmp_path, monkeypatch, found
) -> None:
    """Records this cannot pair with the rows - more than a skipped line and
    a header ahead of them, or fewer than the rows - are refused rather than
    given offsets that point at other rows. Forced, since a file DuckDB and
    `record_offsets` disagree about is the case nobody has found yet."""
    src = tmp_path / "a.csv"
    src.write_bytes(b"id,v\n1,a\n2,b\n")
    monkeypatch.setattr(engine, "record_offsets", lambda *args: found)
    with pytest.raises(engine.DatasetEngineError) as caught:
        engine.parse_to_parquet(str(src), str(tmp_path / "out" / "d.parquet"),
                                engine.ParseOptions(add_byte_offset=True), ".csv")
    assert "could not be lined up with its 2 rows" in str(caught.value)


def test_a_skipped_line_and_a_header_are_all_that_may_come_first(tmp_path, monkeypatch) -> None:
    src = tmp_path / "a.csv"
    src.write_bytes(b"id,v\n1,a\n2,b\n")
    monkeypatch.setattr(engine, "record_offsets", lambda *args: [0, 1, 5, 9])
    engine.parse_to_parquet(str(src), str(tmp_path / "out" / "d.parquet"),
                            engine.ParseOptions(add_byte_offset=True, skip_lines=1), ".csv")


def test_a_json_file_refuses_it(client, fx) -> None:
    created = upload(client, fx, b'[{"id": 1}]', filename="d.json")
    r = preview(client, fx, created["id"], add_byte_offset=True)
    assert r.status_code == 422, r.text
    assert "a byte offset column: only a delimited file has these" in r.text
