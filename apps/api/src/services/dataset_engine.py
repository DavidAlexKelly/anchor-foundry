"""Dataset compute (spec §"Models" execution: "DuckDB for small-medium
datasets ... Athena over S3/Iceberg for large datasets").

This module is the DuckDB half. Files above the interactive size cap get a
clear message pointing at export instead of a hung request - the Athena path
arrives with the production data plane. All functions are synchronous; routes
run them on a worker thread.

Query sandboxing: user SQL runs only after the dataset is materialised into
an in-memory table and `enable_external_access` is switched off, so
read_csv('/etc/passwd'), COPY TO, httpfs and every other filesystem/network
door is closed. Writes to the ephemeral in-memory database are harmless.
"""
from __future__ import annotations

import datetime as dt
import decimal
import os
import re
import tempfile
from dataclasses import dataclass, replace
from typing import Any

import duckdb

from ..lib import duck

MAX_INTERACTIVE_BYTES = 200 * 1024 * 1024  # flag: Athena beyond this in prod
MAX_RESULT_ROWS = 500
PREVIEW_ROWS = 100
QUERY_MEMORY_LIMIT = "512MB"

_READERS: dict[str, str] = {
    ".csv": "read_csv_auto({path!r})",
    ".tsv": "read_csv_auto({path!r}, delim='\\t')",
    ".parquet": "read_parquet({path!r})",
    ".json": "read_json_auto({path!r})",
    ".jsonl": "read_json_auto({path!r}, format='newline_delimited')",
}

SUPPORTED_EXTENSIONS = tuple(_READERS)


class DatasetEngineError(RuntimeError):
    """User-safe failure (bad file, bad SQL, too large)."""


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    data_type: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "data_type": self.data_type}


@dataclass(frozen=True)
class TabularResult:
    columns: list[ColumnSchema]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool


def _reader_expr(src_path: str, extension: str) -> str:
    template = _READERS.get(extension.lower())
    if template is None:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise DatasetEngineError(
            f"unsupported file type {extension!r} (supported: {supported})"
        )
    return template.format(path=src_path)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return str(value)


def json_value(value: Any) -> Any:
    """`json_safe`, into lists and structs (§735).

    A STRUCT column reads as a dict and a list column as a list, and
    `json_safe` writes either as Python's repr - `{'a': 1}` - which no struct
    or array property can read: `_coerce_struct` parses JSON, and a repr is
    not JSON. So a struct property mapped from a struct column failed every
    sync. The sync reads values with this; a preview, which shows a value
    rather than reading it, keeps `json_safe`'s text.
    """
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return json_safe(value)


#: Character sets a re-parse may be told to decode from (§362;
#: `dataset-preview` p.14's "change encoding"). A named list rather than any
#: codec Python knows, because the point of the control is to name what the
#: file *is*, and `python -c "import codecs"` offers a hundred answers nobody
#: is choosing between. These are the ones a spreadsheet export actually
#: produces.
ENCODINGS: tuple[str, ...] = ("utf-8", "utf-8-sig", "latin-1", "cp1252", "utf-16")


@dataclass(frozen=True)
class ParseOptions:
    """How to read a delimited file (§362; `dataset-preview` p.14, p.25-27).

    Foundry's `TextDataFrameReader` table (p.25-27) is the reference. What is
    here is what DuckDB can actually do, **measured rather than assumed** — on
    the version this runs (1.1.1), `encoding` is not a `read_csv` parameter at
    all and `escape` is strictly one byte. Each field below says which of
    Foundry's properties it is, and the ones with no field are listed in the
    parity row with the reason.

    Defaults are "what the upload path already does", so `ParseOptions()` is
    the file as it was first read and a form opened on it starts from what
    somebody is looking at rather than from a blank.
    """

    #: p.26 `fieldDelimiter`. None asks DuckDB to sniff it, which is what
    #: `read_csv_auto` has always done.
    delimiter: str | None = None
    #: p.26 `quoteCharacter`.
    quote: str | None = None
    # **There is no `escape` field, and that is a finding rather than an
    # omission.** It was built, and then no file could be found where passing
    # it changes DuckDB 1.1.1's answer: the sniffer already handles
    # backslash-escaped quotes (`"a\",b"` reads as `a",b` with and without
    # it), and DuckDB refuses an escape longer than one byte anyway. A control
    # whose mutant nothing can catch is a control that cannot be shown to work
    # (§213), and one that looks like it works is worse than one that is
    # absent (§214). If a file turns up that needs it, it comes back with the
    # test that proves it.
    #: Whether the first row names the columns. Implied by p.26's "types
    #: specified in the header" rather than listed.
    header: bool = True
    #: p.26 `skipLines`.
    skip_lines: int = 0
    #: p.25 `nullValues`. Empty means DuckDB's own default.
    null_values: tuple[str, ...] = ()
    #: p.26 `jaggedRowBehavior: DROP_ROW`, which is p.14's "drop jagged rows".
    #: It also covers p.27's `parseErrorBehavior`, because DuckDB's
    #: `ignore_errors` does not distinguish the two — said here rather than
    #: pretending to offer both.
    drop_bad_rows: bool = False
    #: p.14's "change encoding". Applied **before** DuckDB sees the file, since
    #: this DuckDB has no such option; see `decode_to_utf8`.
    encoding: str = "utf-8"
    #: p.14/p.27 `addFilePath`.
    add_file_path: bool = False
    #: p.14/p.27 `addImportedAt`.
    add_imported_at: bool = False
    #: p.14's "row number". Not in p.25-27's table, which is the *reader's*
    #: options; p.14 offers it beside the other two added columns.
    add_row_number: bool = False
    #: p.14's "byte offset for row" (§766): where in the uploaded file each
    #: row's record begins. Computed here rather than asked of DuckDB, which
    #: has no such column; see `record_offsets`.
    add_byte_offset: bool = False
    #: p.26 `dateFormat`: "a map that maps column names to JodaTime
    #: DateTimeFormat patterns" (§765). Pairs rather than a dict so the options
    #: stay hashable; see `date_columns`.
    date_formats: tuple[tuple[str, str], ...] = ()


#: JodaTime's pattern letters (p.26 `dateFormat`) that DuckDB's `strptime` can
#: read, and how it spells each, by how many times the letter repeats. A count
#: not listed is refused rather than guessed.
_JODA: dict[str, dict[int, str]] = {
    "y": {1: "%Y", 2: "%y", 3: "%Y", 4: "%Y"},
    "Y": {1: "%Y", 2: "%y", 3: "%Y", 4: "%Y"},
    "M": {1: "%m", 2: "%m", 3: "%b", 4: "%B"},
    "d": {1: "%d", 2: "%d"},
    "D": {1: "%j", 2: "%j", 3: "%j"},
    "E": {1: "%a", 2: "%a", 3: "%a", 4: "%A"},
    "H": {1: "%H", 2: "%H"},
    "h": {1: "%I", 2: "%I"},
    "m": {1: "%M", 2: "%M"},
    "s": {1: "%S", 2: "%S"},
    "S": {3: "%g", 6: "%f"},
    "a": {1: "%p"},
    "Z": {1: "%z", 2: "%z"},
}
#: The letters that make a value a moment rather than a day.
_JODA_TIME = frozenset("HhmsSaZ")
#: Joda reads more of these letters than the longest form as the longest form
#: (`yyyyy` is a year, `MMMMM` a month's name); the rest must be exact.
_JODA_CLAMPED = frozenset("yYMDE")


def joda_to_strptime(pattern: str) -> tuple[str, bool]:
    """A JodaTime pattern as a `strptime` format, and whether it has a time.

    > "dateFormat: Format strings for date parsing in certain columns. A map
    > that maps column names to JodaTime DateTimeFormat patterns" (p.26)

    Joda's syntax is the one p.26 names, so it is the one taken, and
    translated here: a letter repeated is one field, quoted text is literal
    (`''` is a quote), and anything else is literal. **A letter this cannot
    translate is refused by name**, never passed through: an unknown letter
    read as literal text would match nothing and drop every row, or fail on
    every row, for a reason nobody could see.
    """
    if not pattern.strip():
        raise DatasetEngineError("a date format needs a pattern, such as dd/MM/yyyy")
    out: list[str] = []
    has_time = False
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "'":
            end = pattern.find("'", i + 1)
            if end == -1:
                raise DatasetEngineError(f"{pattern!r} opens a quote it does not close")
            literal = pattern[i + 1:end] or "'"
            out.append(literal.replace("%", "%%"))
            i = end + 1
            continue
        if not char.isalpha():
            out.append("%%" if char == "%" else char)
            i += 1
            continue
        run = 1
        while i + run < len(pattern) and pattern[i + run] == char:
            run += 1
        spellings = _JODA.get(char)
        if spellings is None:
            raise DatasetEngineError(
                f"{char!r} in {pattern!r} is not a pattern letter this platform reads")
        spelled = spellings.get(min(run, max(spellings)) if char in _JODA_CLAMPED else run)
        if spelled is None:
            raise DatasetEngineError(f"{char * run!r} in {pattern!r} is not a field it can read")
        out.append(spelled)
        has_time = has_time or char in _JODA_TIME
        i += run
    return "".join(out), has_time


def _sql_string(value: str) -> str:
    """A single-quoted SQL literal. Doubling is SQL's own escape, and these
    values are one or two characters typed into a form."""
    return "'" + value.replace("'", "''") + "'"


def csv_reader_expr(src_path: str, options: ParseOptions) -> str:
    """`read_csv(...)` with the options that are not defaults.

    **Only what was chosen is passed**, so a file with nothing set is read by
    exactly the call `read_csv_auto` makes — a re-parse that changes nothing
    has to produce what is already there, or the button is a trap.
    """
    args = [repr(src_path)]
    if options.delimiter is not None:
        args.append(f"delim={_sql_string(options.delimiter)}")
    if options.quote is not None:
        args.append(f"quote={_sql_string(options.quote)}")
    if not options.header:
        args.append("header=false")
    if options.skip_lines:
        args.append(f"skip={int(options.skip_lines)}")
    if options.null_values:
        joined = ", ".join(_sql_string(v) for v in options.null_values)
        args.append(f"nullstr=[{joined}]")
    if options.drop_bad_rows:
        args.append("ignore_errors=true")
    if options.add_file_path:
        args.append("filename=true")
    if options.date_formats:
        # Read as text, so `strptime` is what decides what the value is:
        # DuckDB's sniffer reads 03/04/2026 as a date its own way, or not at
        # all, and p.26's pattern is the answer to which.
        typed = ", ".join(f"{_sql_string(column)}: 'VARCHAR'"
                          for column, _pattern in options.date_formats)
        args.append(f"types={{{typed}}}")
    return f"read_csv({', '.join(args)})"


#: The kept files a re-parse reads with `read_json` (§510). p.3's Edit schema
#: "will infer a schema for CSV and JSON files", and `read_csv` on a JSON file
#: does not fail: it returns **no rows**, so a re-parse through it would
#: quietly write an empty version.
JSON_EXTENSIONS = (".json", ".jsonl")


def json_reader_expr(src_path: str, extension: str, options: ParseOptions) -> str:
    """`read_json(...)`, read the way the upload read it (`_READERS`), plus the
    one reader option that means something for JSON: the file path."""
    args = [repr(src_path)]
    if extension == ".jsonl":
        args.append("format='newline_delimited'")
    if options.add_file_path:
        args.append("filename=true")
    return f"read_json({', '.join(args)})"


def refuse_for_file(extension: str, options: ParseOptions) -> None:
    """The options this kind of file has nothing to apply them to (§510).

    **Refused by name rather than ignored**, because an ignored option is a
    control that looks like it works (§214). A Parquet file has no parse at
    all. A JSON file has no delimiter, quote, header, preamble or null marker,
    and DuckDB's `ignore_errors` on JSON keeps a malformed record as a row of
    NULLs rather than dropping it, so "drop rows that do not fit" would not
    mean what it says. Encoding and the added columns apply to both.
    """
    if extension == ".parquet":
        raise DatasetEngineError(
            "a Parquet file carries its own schema, so there is nothing to parse again")
    # §766's two combinations that would misplace the offsets (`_with_offsets`).
    # Here so that they are said before a re-encoding runs, not after it fails.
    if options.add_byte_offset and options.drop_bad_rows:
        raise DatasetEngineError(
            "a byte offset cannot be given when rows that do not fit are dropped: "
            "the offsets would no longer line up with the rows")
    if options.add_byte_offset and options.encoding == "utf-16":
        raise DatasetEngineError(
            "a byte offset cannot be found in a UTF-16 file, whose newlines are two bytes")
    if extension not in JSON_EXTENSIONS:
        return
    chosen = [label for label, on in (
        ("a delimiter", options.delimiter is not None),
        ("a quote character", options.quote is not None),
        ("no header row", not options.header),
        ("skipped lines", options.skip_lines > 0),
        ("null markers", bool(options.null_values)),
        ("dropping rows that do not fit", options.drop_bad_rows),
        ("date formats", bool(options.date_formats)),
        ("a byte offset column", options.add_byte_offset),
    ) if on]
    if chosen:
        raise DatasetEngineError(
            f"{', '.join(chosen)}: only a delimited file has these, and this one is JSON")


def decode_to_utf8(src_path: str, dest_path: str, encoding: str) -> None:
    """Rewrite a file as UTF-8, because this DuckDB cannot be told otherwise.

    `read_csv` grew an `encoding` parameter in DuckDB 1.2 and this runs 1.1.1,
    where a latin-1 file does not parse badly — it **fails outright**, with
    "Invalid unicode (byte sequence mismatch)". So p.14's "change encoding" is
    not a nicety here: without it there is no way to load the file at all.

    Doing it here rather than waiting for the upgrade also keeps the control
    honest in the other direction — a option that silently did nothing on the
    version actually deployed would be §214's exact shape.
    """
    if encoding not in ENCODINGS:
        raise DatasetEngineError(
            f"unsupported encoding {encoding!r} (supported: {', '.join(ENCODINGS)})"
        )
    with open(src_path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise DatasetEngineError(
            f"this file is not {encoding} - it failed to decode at byte {exc.start}"
        ) from exc
    with open(dest_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def record_offsets(raw: bytes, quote: bytes, escape: bytes | None = None) -> list[int]:
    """Where each record of a delimited file begins, in bytes (§766).

    A record ends at a newline outside quotes, so a quoted field holding a
    line break stays one record, as DuckDB reads it. Empty lines are not
    records, since DuckDB skips them. Only the quote, escape and newline
    bytes are visited, so a large file costs one pass of a regular expression.

    Byte-level, which is why `refuse_for_file` refuses UTF-16: there a
    newline is two bytes and a quote's second byte can be anything.

    `escape` is the sniffed one (`\\` in `"a\\"b"`): inside quotes it takes
    the byte after it out of play, as DuckDB reads it. A doubled quote needs
    no escape, since it toggles twice.
    """
    starts: list[int] = []
    in_quote = False
    start = 0
    escaped = -1
    special = re.escape(quote) + rb"|\n"
    if escape and escape != quote:
        special += rb"|" + re.escape(escape)
    for found in re.finditer(special, raw):
        if found.start() == escaped:
            continue
        if found.group() == escape and found.group() != quote:
            if in_quote:
                escaped = found.end()
            continue
        if found.group() == quote:
            # A doubled quote toggles twice, which is the same as not at all.
            in_quote = not in_quote
            continue
        if not in_quote:
            if raw[start:found.start()].strip(b"\r"):
                starts.append(start)
            start = found.end()
    if raw[start:].strip(b"\r"):
        starts.append(start)
    return starts


def _with_offsets(
    con: "duckdb.DuckDBPyConnection", src_path: str, original_path: str, reader: str,
    options: ParseOptions, workdir: str,
) -> str:
    """The read with p.14's byte offset beside each row (§766).

    **The rows are the file's last records**: whatever a parse leaves out
    comes first (skipped lines, the header), and dropping rows that do not
    fit is refused with this option because it would leave holes nothing can
    line up (`refuse_for_file`). So the offsets are the last N record starts, paired with the rows
    by position. A file whose records cannot be lined up that way is refused
    rather than given offsets that point at the wrong rows.
    """
    sniffed = con.execute(f"SELECT Quote, Escape FROM sniff_csv({src_path!r})").fetchone()
    quote = options.quote or (str(sniffed[0]) if sniffed and sniffed[0] else '"')
    escape = str(sniffed[1]) if sniffed and sniffed[1] else None
    with open(original_path, "rb") as handle:
        starts = record_offsets(
            handle.read(), quote.encode(), escape.encode() if escape else None)
    rows = int(con.execute(f"SELECT count(*) FROM {reader}").fetchone()[0])
    preamble = len(starts) - rows
    if not 0 <= preamble <= options.skip_lines + 1:
        raise DatasetEngineError(
            f"the file's {len(starts)} records could not be lined up with its "
            f"{rows} rows, so no byte offsets were given")
    offsets = os.path.join(workdir, "byte_offsets.csv")
    with open(offsets, "w") as handle:
        handle.write("byte_offset\n")
        handle.writelines(f"{start}\n" for start in starts[preamble:])
    return (f"(SELECT * FROM {reader} r POSITIONAL JOIN "
            f"read_csv({offsets!r}, header=true, columns={{'byte_offset': 'BIGINT'}}) o)")


def parse_to_parquet(
    src_path: str, dest_path: str, options: ParseOptions, extension: str,
    original_path: str | None = None,
) -> tuple[list[ColumnSchema], int]:
    """Read a delimited file the way `options` says, and write the Parquet.

    The added columns (p.14) are `SELECT` expressions rather than reader
    options, because only one of the three is a reader option at all —
    `filename=true` gives the path, and the import time and the row number are
    things this platform knows and DuckDB does not.

    `original_path` is the file as uploaded, when `src_path` is a re-encoded
    copy of it: a byte offset is a position in what was uploaded.
    """
    refuse_for_file(extension, options)
    reader = (json_reader_expr(src_path, extension, options) if extension in JSON_EXTENSIONS
              else csv_reader_expr(src_path, options))
    selected = ["src.*"]
    if options.add_imported_at:
        selected.append("now() AS imported_at")
    if options.add_row_number:
        # Over the file's own order. `row_number() OVER ()` with no ORDER BY is
        # the reading order, which is the only order a row number can mean for
        # a file — anything else would number a sort somebody did not ask for.
        selected.append("row_number() OVER () AS row_number")
    con = duck.connect()
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        try:
            if options.date_formats:
                reader = _with_dates(con, src_path, reader, options)
            if options.add_byte_offset:
                reader = _with_offsets(con, src_path, original_path or src_path, reader,
                                       options, os.path.dirname(dest_path))
            con.execute(f"CREATE VIEW src AS SELECT {', '.join(selected)} FROM {reader} src")
            con.execute(f"COPY src TO '{dest_path}' (FORMAT parquet)")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        schema = [
            ColumnSchema(name=row[0], data_type=row[1])
            for row in con.execute("DESCRIBE src").fetchall()
        ]
        row_count = int(con.execute("SELECT count(*) FROM src").fetchone()[0])
        return schema, row_count
    finally:
        con.close()


def _with_dates(
    con: "duckdb.DuckDBPyConnection", src_path: str, reader: str, options: ParseOptions
) -> str:
    """The read with p.26's `dateFormat` applied: each named column parsed by
    its pattern, into a date, or a timestamp when the pattern has a time.

    A column the file does not have is refused by name, as is a value that
    does not match - unless rows that do not fit are being dropped, which is
    what `drop_bad_rows` already means for a value of the wrong type (p.26's
    `parseErrorBehavior`).
    """
    plain = csv_reader_expr(src_path, replace(options, date_formats=()))
    present = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {plain}").fetchall()]
    replaced: list[str] = []
    fits: list[str] = []
    for column, pattern in options.date_formats:
        if column not in present:
            raise DatasetEngineError(
                f"date format for {column!r}: the file has no such column "
                f"(it has {', '.join(present)})")
        spelled, has_time = joda_to_strptime(pattern)
        quoted = _quote_column(column)
        parsed = f"try_strptime({quoted}, {_sql_string(spelled)})"
        # A CASE rather than `IS NULL OR …`: DuckDB 1.1.1 plans that OR as
        # two scans, and the rows come back out of the file's order, which
        # is the order p.14's row number counts in.
        fit = f"(CASE WHEN {quoted} IS NULL THEN true ELSE {parsed} IS NOT NULL END)"
        if not options.drop_bad_rows:
            bad = con.execute(
                f"SELECT {quoted} FROM {reader} WHERE NOT {fit} LIMIT 1").fetchone()
            if bad is not None:
                raise DatasetEngineError(
                    f"{column}: {bad[0]!r} does not match {pattern!r}")
        replaced.append(f"{parsed}{'' if has_time else '::DATE'} AS {quoted}")
        fits.append(fit)
    return (f"(SELECT * REPLACE ({', '.join(replaced)}) FROM {reader} "
            f"WHERE {' AND '.join(fits)})")


def ingest_to_parquet(src_path: str, extension: str, dest_path: str) -> tuple[list[ColumnSchema], int]:
    """Convert an uploaded file to canonical Parquet; returns (schema, rows)."""
    reader = _reader_expr(src_path, extension)
    con = duck.connect()
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        try:
            con.execute(f"CREATE VIEW src AS SELECT * FROM {reader}")
            con.execute(f"COPY src TO '{dest_path}' (FORMAT parquet)")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        schema = [
            ColumnSchema(name=row[0], data_type=row[1])
            for row in con.execute("DESCRIBE src").fetchall()
        ]
        row_count = int(con.execute("SELECT count(*) FROM src").fetchone()[0])
        return schema, row_count
    finally:
        con.close()


def combine_parquets(
    parts: list[tuple[str, str]], dest_path: str
) -> tuple[list[ColumnSchema], int]:
    """One Parquet from several, in order: the files an uploaded dataset holds
    (§746; `dataset-preview` p.10), each already read on its own.

    `parts` is `(filename, parquet path)`. **The schemas must agree**, column
    for column, and a part that does not is named in the refusal rather than
    unioned in: a dataset has one schema, and widening it to take a file that
    disagrees would be decision 0002's silent widening. The upload route
    refuses such a file before it is kept; this is what still catches a
    re-parse whose options read two files differently.
    """
    if not parts:
        raise DatasetEngineError("there is no file to read")
    con = duck.connect()
    try:
        schemas = [
            (name, [(str(r[0]), str(r[1])) for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet({path!r})").fetchall()])
            for name, path in parts
        ]
        first_name, first = schemas[0]
        for name, schema in schemas[1:]:
            if schema != first:
                raise DatasetEngineError(
                    f"{name} does not read with the same columns as {first_name}, "
                    "so the two cannot be one dataset"
                )
        paths = ", ".join(repr(path) for _name, path in parts)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        try:
            con.execute(f"CREATE VIEW combined AS SELECT * FROM read_parquet([{paths}])")
            con.execute(f"COPY combined TO '{dest_path}' (FORMAT parquet)")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        row_count = int(con.execute("SELECT count(*) FROM combined").fetchone()[0])
        return [ColumnSchema(name=n, data_type=t) for n, t in first], row_count
    finally:
        con.close()


def diff_schemas(
    previous: list[dict[str, str]] | None, current: list[ColumnSchema]
) -> dict[str, Any] | None:
    """Schema drift between the previous dataset version and the one about to
    be written (roadmap Connections item 6, migration 0018).

    `previous` is a stored `table_schema` jsonb array (or None for a dataset's
    first version). Returns None when there is nothing to report - no baseline,
    or no change - so a caller can store the result directly and
    `schema_changes IS NOT NULL` means "this run drifted".

    Column order is deliberately not drift: a source reordering its SELECT
    changes nothing about what downstream consumers can read, and reporting it
    would bury the changes that do matter.
    """
    if not previous:
        return None
    before = {c["name"]: c.get("data_type", "") for c in previous if c.get("name")}
    after = {c.name: c.data_type for c in current}

    added = [
        {"name": name, "data_type": after[name]} for name in after if name not in before
    ]
    removed = [
        {"name": name, "data_type": before[name]} for name in before if name not in after
    ]
    retyped = [
        {"name": name, "from": before[name], "to": after[name]}
        for name in after
        if name in before and before[name] != after[name]
    ]

    changes: dict[str, Any] = {}
    if added:
        changes["added"] = added
    if removed:
        changes["removed"] = removed
    if retyped:
        changes["retyped"] = retyped
    return changes or None


def describe_file(src_path: str, extension: str) -> list[ColumnSchema]:
    """Column names/types of a source file without converting it.

    Same readers as ingest_to_parquet, so what a connector reports at
    discovery time is what the file will actually land with - but DESCRIBE
    only, since discovery inspects files it has no intention of ingesting."""
    reader = _reader_expr(src_path, extension)
    con = duck.connect()
    try:
        try:
            con.execute(f"CREATE VIEW src AS SELECT * FROM {reader}")
            return [
                ColumnSchema(name=row[0], data_type=row[1])
                for row in con.execute("DESCRIBE src").fetchall()
            ]
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
    finally:
        con.close()


def sample_file(
    src_path: str, extension: str, limit: int
) -> tuple[list[ColumnSchema], list[list[Any]]]:
    """The first `limit` rows of a source file, without converting it.

    `describe_file`'s argument one step further along (decision 0015): a file a
    connector is previewing is read through the same readers the ingest would
    use, so the rows on the screen are the rows that would land - a preview
    that parsed the file its own way could show a clean table for a file the
    sync would then refuse.

    Returns exactly what `LIMIT` gave and says nothing about whether there is
    more, deliberately: `TabularResult.truncated` would have to be inferred
    from a full page here, and a caller that wants the answer asks for one row
    past its own cap (which is what `connectors.build_preview` does). Counting
    the file's rows would mean reading all of it - the cost a preview exists to
    avoid.
    """
    reader = _reader_expr(src_path, extension)
    con = duck.connect()
    try:
        try:
            cursor = con.execute(f"SELECT * FROM {reader} LIMIT {max(1, int(limit))}")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        columns = [ColumnSchema(name=d[0], data_type=str(d[1])) for d in cursor.description]
        return columns, [[json_safe(v) for v in row] for row in cursor.fetchall()]
    finally:
        con.close()


def profile_columns(parquet_path: str) -> list[dict[str, Any]]:
    """Per-column statistics for a dataset version (migration 0019).

    One pass over the file computing every column's aggregates at once, rather
    than a query per column: DuckDB reads the Parquet once and the whole thing
    stays a single scan even on a wide table.

    min/max come back as text because the result has to hold whatever each
    column's type is in one JSON array, and this is display metadata - nothing
    computes against it. Types DuckDB cannot order (structs, lists, maps -
    ordinary in a JSON source) get NULL min/max rather than failing the whole
    profile; the null rate and distinct count are still meaningful for them.
    """
    con = duck.connect()
    try:
        try:
            con.execute(
                f"CREATE VIEW src AS SELECT * FROM read_parquet('{parquet_path}')"
            )
            described = con.execute("DESCRIBE src").fetchall()
            total = int(con.execute("SELECT count(*) FROM src").fetchone()[0])
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        if not described:
            return []

        selects: list[str] = []
        quoted_names: list[str] = []
        for name, data_type, *_ in described:
            quoted = '"' + str(name).replace('"', '""') + '"'
            quoted_names.append(quoted)
            selects.append(f"count({quoted})")
            if _is_orderable(str(data_type)):
                selects.append(f"CAST(min({quoted}) AS VARCHAR)")
                selects.append(f"CAST(max({quoted}) AS VARCHAR)")
            else:
                # Kept in the projection so the row stays a fixed 3-per-column
                # stride and the unpacking below doesn't need to branch.
                selects.append("NULL")
                selects.append("NULL")

        try:
            row = con.execute(f"SELECT {', '.join(selects)} FROM src").fetchone()
            # **One distinct count per query (§875).** An exact distinct count
            # holds every value of its column at once, so one aggregate over
            # all the columns held all of them: at three million rows it took
            # 1.3 GB, and under a connection's memory limit it refused to run.
            # One column at a time is the same wall-clock time - the file is
            # columnar, so each query reads only its own column - and 400 MB.
            distincts = [
                con.execute(f"SELECT count(DISTINCT {quoted}) FROM src").fetchone()[0]
                for quoted in quoted_names
            ]
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        profile: list[dict[str, Any]] = []
        for index, (name, data_type, *_) in enumerate(described):
            non_null, minimum, maximum = row[index * 3 : index * 3 + 3]
            distinct = distincts[index]
            non_null = int(non_null or 0)
            null_count = total - non_null
            profile.append(
                {
                    "name": str(name),
                    "data_type": str(data_type),
                    "null_count": null_count,
                    # Rounded rather than raw: this is rendered as a percentage
                    # and a full float would put 17 digits on screen.
                    "null_rate": round(null_count / total, 6) if total else 0.0,
                    "distinct_count": int(distinct or 0),
                    "min": None if minimum is None else str(minimum),
                    "max": None if maximum is None else str(maximum),
                }
            )
        return profile
    finally:
        con.close()


RULE_TYPES = ("not_null", "unique", "value_in_range", "regex_match", "column_exists")


#: Types a `value_in_range` comparison against a number binds against.
#:
#: **Measured, not recalled.** `CAST(NULL AS <type>) < 5` was run against every
#: type this platform can produce, and these are the ones DuckDB accepts:
#: the integer family, the float family, DECIMAL, and BOOLEAN — which coerces,
#: and is the one nobody would have guessed. VARCHAR, DATE, TIMESTAMP, TIME,
#: BLOB, UUID and INTERVAL all raise a binder error instead.
#:
#: Prefixes, because DECIMAL carries its precision ("DECIMAL(21,1)") and the
#: integer types do not.
_COMPARABLE_TO_A_NUMBER = (
    "BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT",
    "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT",
    "DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC", "BOOLEAN",
)


def compares_to_a_number(data_type: str) -> bool:
    """Whether `value_in_range` can run against a column of this type."""
    upper = (data_type or "").strip().upper()
    return upper.startswith(_COMPARABLE_TO_A_NUMBER)


def expectations_at_risk(
    rules: list[dict[str, Any]], changes: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Which of a dataset's expectations the proposed columns would stop
    (`code-repositories` p.52, p.54; §371).

    > "Build on head branch (development) to validate that the code builds
    >  properly, the outputs appear as expected, and that **all Data
    >  Expectations are met**." (p.52)

    **Predicted from the schema rather than measured by running them**, which
    is what makes it answerable at all: evaluating a rule needs the proposed
    data, and producing that needs p.52's build. The columns come from §365's
    preview, so this costs nothing beyond it.

    Deliberately narrow. Only two things here are certain from a column list,
    and both are read out of `_evaluate_one` below rather than assumed:

    * **A removed column.** `column_exists` *fails* on it — that rule's whole
      job — and every other rule *errors*, because "the column is not in this
      version" is not a statement about the data. The two are different
      outcomes and are reported as different things; collapsing them would
      tell a reviewer their data went bad when their rule stopped applying.
    * **A retype away from a numeric type**, which breaks `value_in_range` and
      nothing else. `regex_match` casts to VARCHAR before matching, so no
      retype can touch it, and `not_null`, `unique` and `column_exists` do not
      look at the type at all.

    Everything else a schema change can do is a question about *data*, which a
    column list cannot answer — so nothing is claimed about it. A panel that
    guessed here would be worse than one that stayed quiet: a reviewer told a
    rule is safe when it is not has been given a reason not to look.
    """
    if not changes:
        return []
    removed = {str(c["name"]) for c in changes.get("removed", []) if c.get("name")}
    retyped = {
        str(c["name"]): str(c.get("to") or "")
        for c in changes.get("retyped", [])
        if c.get("name")
    }

    at_risk: list[dict[str, Any]] = []
    for rule in rules:
        column = str(rule.get("column_name") or "")
        rule_type = str(rule.get("rule_type") or "")
        if column in removed:
            at_risk.append({
                "expectation_id": str(rule.get("id")),
                "rule_type": rule_type,
                "column_name": column,
                "severity": str(rule.get("severity") or "error"),
                # p.55's distinction, kept: the rule that asserts the column is
                # there has an answer when it goes, and the rest do not.
                "outcome": "fail" if rule_type == "column_exists" else "error",
                "reason": "removed",
            })
        elif rule_type == "value_in_range" and column in retyped:
            if not compares_to_a_number(retyped[column]):
                at_risk.append({
                    "expectation_id": str(rule.get("id")),
                    "rule_type": rule_type,
                    "column_name": column,
                    "severity": str(rule.get("severity") or "error"),
                    "outcome": "error",
                    "reason": "retyped",
                    "new_type": retyped[column],
                })
    return at_risk


def evaluate_expectations(
    parquet_path: str, rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Check each rule against a version's data (migration 0020).

    Returns one result per rule, in the order given, each with a status of
    `pass`, `fail`, or `error`. `error` is distinct from `fail` on purpose: a
    rule that cannot be evaluated (its column is gone, its regex is invalid)
    has not proven the data bad, and reporting that as a data failure would
    send someone looking in the wrong place.

    One rule failing never stops the others - a dataset's health is the whole
    picture, and the first broken rule is the least useful place to stop.
    """
    con = duck.connect()
    try:
        try:
            con.execute(
                f"CREATE VIEW src AS SELECT * FROM read_parquet('{parquet_path}')"
            )
            columns = {str(row[0]) for row in con.execute("DESCRIBE src").fetchall()}
            total = int(con.execute("SELECT count(*) FROM src").fetchone()[0])
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        results: list[dict[str, Any]] = []
        for rule in rules:
            results.append(_evaluate_one(con, rule, columns, total))
        return results
    finally:
        con.close()


def _evaluate_one(
    con: "duckdb.DuckDBPyConnection",
    rule: dict[str, Any],
    columns: set[str],
    total: int,
) -> dict[str, Any]:
    rule_type = str(rule.get("rule_type"))
    column = str(rule.get("column_name") or "")
    config = rule.get("config") or {}
    if isinstance(config, str):
        import json

        try:
            config = json.loads(config)
        except ValueError:
            config = {}

    base = {
        "expectation_id": str(rule.get("id")) if rule.get("id") is not None else None,
        "rule_type": rule_type,
        "column_name": column,
        "severity": str(rule.get("severity") or "error"),
        "failing_rows": 0,
        "rows_checked": total,
    }

    if rule_type == "column_exists":
        present = column in columns
        return {
            **base,
            "status": "pass" if present else "fail",
            "message": None if present else f"column '{column}' is missing",
        }

    # Every other rule needs the column to be there to mean anything. Missing
    # is an `error`, not a `fail`: add a column_exists rule to assert presence.
    if column not in columns:
        return {
            **base,
            "status": "error",
            "message": f"column '{column}' is not in this version",
        }

    quoted = '"' + column.replace('"', '""') + '"'
    try:
        if rule_type == "not_null":
            failing = _scalar(con, f"SELECT count(*) FROM src WHERE {quoted} IS NULL")
            message = f"{failing} null value(s)" if failing else None
        elif rule_type == "unique":
            # Rows beyond the first occurrence of each value - nulls excluded,
            # since SQL uniqueness does not constrain them.
            failing = _scalar(
                con,
                f"SELECT count({quoted}) - count(DISTINCT {quoted}) FROM src",
            )
            message = f"{failing} duplicate value(s)" if failing else None
        elif rule_type == "value_in_range":
            minimum, maximum = config.get("min"), config.get("max")
            if minimum is None and maximum is None:
                return {
                    **base,
                    "status": "error",
                    "message": "value_in_range needs a min, a max, or both",
                }
            clauses = []
            if minimum is not None:
                clauses.append(f"{quoted} < {_number(minimum)}")
            if maximum is not None:
                clauses.append(f"{quoted} > {_number(maximum)}")
            predicate = " OR ".join(clauses)
            failing = _scalar(
                con,
                f"SELECT count(*) FROM src WHERE {quoted} IS NOT NULL AND ({predicate})",
            )
            message = f"{failing} value(s) outside the range" if failing else None
        elif rule_type == "regex_match":
            pattern = config.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                return {**base, "status": "error", "message": "regex_match needs a pattern"}
            escaped = pattern.replace("'", "''")
            failing = _scalar(
                con,
                f"SELECT count(*) FROM src WHERE {quoted} IS NOT NULL "
                f"AND NOT regexp_matches(CAST({quoted} AS VARCHAR), '{escaped}')",
            )
            message = f"{failing} value(s) do not match" if failing else None
        else:
            return {**base, "status": "error", "message": f"unknown rule type '{rule_type}'"}
    except duckdb.Error as exc:
        # A rule that cannot run against this column's type (a range check on
        # text, a bad regex) is the rule's problem, not the data's.
        return {**base, "status": "error", "message": _clean(exc)}

    return {
        **base,
        "failing_rows": failing,
        "status": "pass" if failing == 0 else "fail",
        "message": message,
    }


def _scalar(con: "duckdb.DuckDBPyConnection", sql: str) -> int:
    row = con.execute(sql).fetchone()
    return int(row[0] or 0) if row else 0


def _number(value: Any) -> str:
    """A numeric literal for a range bound. Anything non-numeric is refused
    rather than interpolated - this is the one place rule config reaches SQL."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DatasetEngineError("range bounds must be numbers")
    return repr(float(value))


def overall_status(results: list[dict[str, Any]]) -> str:
    """A dataset's health from its rule results.

    `fail` if any error-severity rule failed, `warn` if only warn-severity
    ones did or a rule could not be evaluated, `pass` otherwise, and `none`
    when there are no rules - which is different from passing, and shows
    differently.
    """
    if not results:
        return "none"
    statuses = {(r.get("status"), r.get("severity")) for r in results}
    if any(status == "fail" and severity == "error" for status, severity in statuses):
        return "fail"
    if any(status in ("fail", "error") for status, _ in statuses):
        return "warn"
    return "pass"


def _is_orderable(data_type: str) -> bool:
    """Whether min()/max() mean anything for this DuckDB type. Nested types
    (STRUCT, LIST/[], MAP, UNION) either error or produce something useless."""
    upper = data_type.upper()
    return not (
        upper.endswith("[]")
        or upper.startswith("STRUCT")
        or upper.startswith("MAP")
        or upper.startswith("UNION")
        or upper == "JSON"
    )


def preview(parquet_path: str, limit: int = PREVIEW_ROWS) -> TabularResult:
    limit = max(1, min(limit, MAX_RESULT_ROWS))
    con = duck.connect()
    try:
        try:
            cursor = con.execute(
                f"SELECT * FROM read_parquet('{parquet_path}') LIMIT {limit}"
            )
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        columns = [ColumnSchema(name=d[0], data_type=str(d[1])) for d in cursor.description]
        rows = [[json_safe(v) for v in row] for row in cursor.fetchall()]
        total = int(
            con.execute(f"SELECT count(*) FROM read_parquet('{parquet_path}')").fetchone()[0]
        )
        return TabularResult(columns=columns, rows=rows, total_rows=total, truncated=total > len(rows))
    finally:
        con.close()


def query(
    parquet_path: str, sql: str, max_rows: int = MAX_RESULT_ROWS,
    tables: dict[str, str] | None = None,
) -> TabularResult:
    """Run user SQL with the dataset available as the table `dataset`, and each
    of `tables` - name to parquet path - as its own: a time series formula's
    other inputs (§561) live in whichever datasets their series do. The names
    are the caller's, never a user's."""
    extra = dict(tables or {})
    for path in [parquet_path, *extra.values()]:
        if os.path.getsize(path) > MAX_INTERACTIVE_BYTES:
            raise DatasetEngineError(
                "this dataset is too large for interactive queries in this build - "
                "use export, or a model transform"
            )
    max_rows = max(1, min(max_rows, MAX_RESULT_ROWS))
    con = duck.connect()
    try:
        con.execute(f"SET memory_limit='{QUERY_MEMORY_LIMIT}'")
        con.execute(f"CREATE TABLE dataset AS SELECT * FROM read_parquet('{parquet_path}')")
        for name, path in extra.items():
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{path}')")
        # Sandbox boundary: from here on, no filesystem or network access.
        duck.seal(con)
        try:
            cursor = con.execute(sql)
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        if cursor.description is None:
            raise DatasetEngineError("only queries that return rows are supported here")
        columns = [ColumnSchema(name=d[0], data_type=str(d[1])) for d in cursor.description]
        rows_raw = cursor.fetchmany(max_rows + 1)
        truncated = len(rows_raw) > max_rows
        rows = [[json_safe(v) for v in row] for row in rows_raw[:max_rows]]
        return TabularResult(columns=columns, rows=rows, total_rows=len(rows), truncated=truncated)
    finally:
        con.close()


def empty_parquet(columns: list[tuple[str, str]]) -> bytes:
    """A Parquet file with these columns - name and DuckDB type - and no rows:
    a dataset something can map, or write to, before it holds anything (the
    action log, §554; a generated join table, §562). The names are the
    caller's, never a user's: each is built from an api name, a letter then
    letters, digits and underscores, which DuckDB reads the same unquoted
    (quoting them survived the sweep as equivalent)."""
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, "data.parquet")
        con = duck.connect()
        try:
            definition = ", ".join(f"{name} {kind}" for name, kind in columns)
            con.execute(f"CREATE TABLE t ({definition})")
            con.execute(f"COPY t TO '{dest}' (FORMAT parquet)")
        finally:
            con.close()
        with open(dest, "rb") as handle:
            return handle.read()


def export_csv(parquet_path: str, dest_path: str) -> None:
    con = duck.connect()
    try:
        try:
            con.execute(
                f"COPY (SELECT * FROM read_parquet('{parquet_path}')) TO '{dest_path}' "
                "(FORMAT csv, HEADER true)"
            )
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
    finally:
        con.close()


def merge_incremental(
    existing_parquet: str | None,
    new_rows_parquet: str,
    primary_key_column: str,
    dest_parquet: str,
) -> tuple[list[ColumnSchema], int]:
    """Upsert an incremental sync's new/changed rows into the existing
    dataset by primary key, writing the merged result as a new version. No
    existing_parquet means this is the connection's first incremental run -
    the new rows are the whole dataset."""
    con = duck.connect()
    try:
        try:
            con.execute(
                f"CREATE TABLE new_rows AS SELECT * FROM read_parquet({new_rows_parquet!r})"
            )
            if existing_parquet is None:
                con.execute("CREATE TABLE merged AS SELECT * FROM new_rows")
            else:
                con.execute(
                    f"CREATE TABLE existing AS SELECT * FROM read_parquet({existing_parquet!r})"
                )
                pk = f'"{primary_key_column}"'
                con.execute(
                    f"""
                    CREATE TABLE merged AS
                    SELECT * FROM existing WHERE {pk} NOT IN (SELECT {pk} FROM new_rows)
                    UNION ALL
                    SELECT * FROM new_rows
                    """
                )
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        schema = [
            ColumnSchema(name=row[0], data_type=row[1])
            for row in con.execute("DESCRIBE merged").fetchall()
        ]
        row_count = int(con.execute("SELECT count(*) FROM merged").fetchone()[0])
        os.makedirs(os.path.dirname(dest_parquet), exist_ok=True)
        con.execute(f"COPY merged TO {dest_parquet!r} (FORMAT parquet)")
        return schema, row_count
    finally:
        con.close()


def merge_transaction(
    existing_parquet: str | None, new_rows_parquet: str, primary_key_column: str,
) -> str:
    """What `merge_incremental` does to the view, as p.22's type (§747): the
    first run is a SNAPSHOT, a run whose keys are all new only adds - an
    APPEND - and a run that replaces any existing row is an UPDATE."""
    if existing_parquet is None:
        return "SNAPSHOT"
    con = duck.connect()
    try:
        pk = f'"{primary_key_column}"'
        (replaced,) = con.execute(
            f"SELECT count(*) FROM read_parquet({new_rows_parquet!r}) "
            f"WHERE {pk} IN (SELECT {pk} FROM read_parquet({existing_parquet!r}))"
        ).fetchone()
        return "UPDATE" if replaced else "APPEND"
    finally:
        con.close()


def added_rows(pairs: list[tuple[int, str, str]], dest_path: str) -> int:
    """The rows each APPEND version added, as one Parquet (§748; decision 0020
    §4). `pairs` is `(version, its parquet, the previous version's parquet)`.

    An APPEND is the previous view plus rows (data-integration p.22), so what
    it added is `version EXCEPT ALL previous` - exact for a multiset, and it
    needs no second file per version. A pair whose columns differ is refused
    rather than compared: rows of two shapes cannot be told apart.
    """
    con = duck.connect()
    try:
        selects = []
        for version, new, previous in pairs:
            shape = [con.execute(f"DESCRIBE SELECT * FROM read_parquet({p!r})").fetchall()
                     for p in (new, previous)]
            if shape[0] != shape[1]:
                raise DatasetEngineError(
                    f"v{version} has different columns from v{version - 1}, so the rows it "
                    "added cannot be told apart from the ones before"
                )
            selects.append(
                f"(SELECT * FROM read_parquet({new!r}) "
                f"EXCEPT ALL SELECT * FROM read_parquet({previous!r}))"
            )
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        try:
            con.execute(f"CREATE VIEW added AS {' UNION ALL '.join(selects)}")
            con.execute(f"COPY added TO '{dest_path}' (FORMAT parquet)")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        return int(con.execute("SELECT count(*) FROM added").fetchone()[0])
    finally:
        con.close()


def _clean(exc: duckdb.Error) -> str:
    """First line of DuckDB's message: precise about the SQL/file problem,
    never contains paths beyond the one we passed in."""
    text = str(exc).strip()
    first = text.splitlines()[0] if text else "query failed"
    return first[:500]


def _quote_column(name: str) -> str:
    """Dataset column names come from uploaded file headers, not a fixed
    identifier grammar - quote-and-escape rather than assume unquoted-safe."""
    return '"' + name.replace('"', '""') + '"'


def join_keys(
    parquet_path: str, near_column: str, far_column: str, keys: list[str], limit: int,
) -> list[str]:
    """The far keys a join table pairs with these near keys (§552;
    `object-link-types` p.35), distinct, at most `limit`.

    Compared as text, as a primary key is everywhere else here: a join table
    whose key column the upload inferred as an integer still pairs with the
    key "7". A pair with a null on either side links nothing.
    """
    con = duck.connect()
    try:
        try:
            names = {
                str(d[0]) for d in con.execute(
                    f"SELECT * FROM read_parquet('{parquet_path}') LIMIT 0"
                ).description
            }
            for column in (near_column, far_column):
                if column not in names:
                    raise DatasetEngineError(
                        f"the join table has no column {column!r} any more, so this "
                        "link cannot be followed until it is joined on one that exists"
                    )
            rows = con.execute(
                f"SELECT DISTINCT CAST({_quote_column(far_column)} AS VARCHAR) AS k "
                f"FROM read_parquet('{parquet_path}') "
                f"WHERE CAST({_quote_column(near_column)} AS VARCHAR) IN "
                "(SELECT unnest(CAST(? AS VARCHAR[])))"
                # No ORDER BY: under the limit `join_filter` sorts the keys,
                # and at it the traversal is refused whichever came back.
                # DISTINCT is not the same kind of redundancy - a duplicate
                # pair counted against the limit would let a traversal past
                # the cap return a prefix instead of refusing.
                f" AND {_quote_column(far_column)} IS NOT NULL LIMIT ?",
                [list(keys), limit],
            ).fetchall()
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        return [str(r[0]) for r in rows]
    finally:
        con.close()


def join_pairs(
    parquet_path: str, near_column: str, far_column: str, keys: list[str], limit: int,
) -> list[tuple[str, str]]:
    """`join_keys`, keeping which near key each far key came from (§604).

    A page of derived values follows one join table for every row at once and
    then has to hand each row its own far objects back, which the flat list
    cannot say. Same comparison as `join_keys` - text on both sides, nulls
    link nothing - and the same limit, counted in pairs.
    """
    con = duck.connect()
    try:
        try:
            names = {
                str(d[0]) for d in con.execute(
                    f"SELECT * FROM read_parquet('{parquet_path}') LIMIT 0"
                ).description
            }
            for column in (near_column, far_column):
                if column not in names:
                    raise DatasetEngineError(
                        f"the join table has no column {column!r} any more, so this "
                        "link cannot be followed until it is joined on one that exists"
                    )
            near, far = _quote_column(near_column), _quote_column(far_column)
            rows = con.execute(
                f"SELECT DISTINCT CAST({near} AS VARCHAR), CAST({far} AS VARCHAR) "
                f"FROM read_parquet('{parquet_path}') "
                f"WHERE CAST({near} AS VARCHAR) IN (SELECT unnest(CAST(? AS VARCHAR[])))"
                f" AND {far} IS NOT NULL LIMIT ?",
                [list(keys), limit],
            ).fetchall()
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        return [(str(r[0]), str(r[1])) for r in rows]
    finally:
        con.close()


def write_rows(
    parquet_path: str,
    primary_key_column: str,
    updates: list[tuple[str, dict[str, Any]]],
    appends: list[dict[str, Any]],
    dest_path: str,
    deletes: list[str] | None = None,
) -> tuple[list[ColumnSchema], int]:
    """Apply a set of row updates and row appends, and write **one** file.

    Decision 0008: an action is "a single transaction" (Foundry `action-types`
    p.2), and in a Parquet-backed dataset that means one output file and one
    version however many rows an action touched. Three versions with the same
    `produced_by_id` would be a history that has to be interpreted rather than
    read, and a failure between them would leave a dataset nobody asked for.

    Every write lands in one DuckDB table before anything is copied out, so a
    failure on the third row leaves the file on disk untouched - there is no
    half-written output to clean up, because the output is written last.

    **An append whose primary key already exists is refused.** Instance identity
    is `(source_id, primary_key)`, so a duplicate key would produce two objects
    that no query could tell apart - the same failure the STATUS note about two
    sources feeding one object type describes, arrived at from the other side.
    """
    con = duck.connect()
    try:
        try:
            con.execute(f"CREATE TABLE t AS SELECT * FROM read_parquet({parquet_path!r})")
            pk_col = _quote_column(primary_key_column)

            for primary_key_value, column_updates in updates:
                (matched,) = con.execute(
                    f"SELECT count(*) FROM t WHERE CAST({pk_col} AS VARCHAR) = ?",
                    [primary_key_value],
                ).fetchone()
                if not matched:
                    raise DatasetEngineError(
                        f"no row with {primary_key_column} = {primary_key_value!r} in this dataset"
                    )
                if not column_updates:
                    continue
                set_clause = ", ".join(f"{_quote_column(c)} = ?" for c in column_updates)
                params = list(column_updates.values()) + [primary_key_value]
                con.execute(
                    f"UPDATE t SET {set_clause} WHERE CAST({pk_col} AS VARCHAR) = ?", params
                )

            for row in appends:
                key = row.get(primary_key_column)
                if key is None or str(key) == "":
                    raise DatasetEngineError(
                        f"a new row needs a value for {primary_key_column!r}"
                    )
                (clash,) = con.execute(
                    f"SELECT count(*) FROM t WHERE CAST({pk_col} AS VARCHAR) = ?", [str(key)]
                ).fetchone()
                if clash:
                    raise DatasetEngineError(
                        f"a row with {primary_key_column} = {str(key)!r} already exists"
                    )
                columns = ", ".join(_quote_column(c) for c in row)
                placeholders = ", ".join("?" for _ in row)
                # Columns the caller said nothing about are left NULL rather
                # than defaulted: a dataset column this platform knows nothing
                # about is not ours to invent a value for.
                try:
                    con.execute(
                        f"INSERT INTO t ({columns}) VALUES ({placeholders})", list(row.values())
                    )
                except duckdb.Error as exc:
                    # **DuckDB buries the reason under a sentence about
                    # internals.** A value that will not convert reports as
                    # "Attempting to execute an unsuccessful or closed pending
                    # query result", with `Conversion Error: Could not convert
                    # string 'T9' to INT32` on the *second* line - so `_clean`,
                    # which keeps the first line everywhere else, would hand the
                    # user the one sentence with nothing in it. This is the one
                    # place that reads further, because supplying a value of the
                    # wrong type for a column is a thing people will do.
                    detail = next(
                        (line.strip() for line in str(exc).splitlines()[1:] if line.strip()),
                        _clean(exc),
                    )
                    raise DatasetEngineError(f"could not add a row: {detail}") from exc

            for primary_key_value in deletes or []:
                (matched,) = con.execute(
                    f"SELECT count(*) FROM t WHERE CAST({pk_col} AS VARCHAR) = ?",
                    [primary_key_value],
                ).fetchone()
                if not matched:
                    # Refused rather than treated as already-done: an action
                    # that reports success for a row it could not find is one
                    # nobody can tell from one that deleted something.
                    raise DatasetEngineError(
                        f"no row with {primary_key_column} = {primary_key_value!r} to delete"
                    )
                con.execute(
                    f"DELETE FROM t WHERE CAST({pk_col} AS VARCHAR) = ?", [primary_key_value]
                )

            described = con.execute("DESCRIBE t").fetchall()
            schema = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
            row_count = int(con.execute("SELECT count(*) FROM t").fetchone()[0])
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            con.execute(f"COPY t TO '{dest_path}' (FORMAT parquet)")
            return schema, row_count
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
    finally:
        con.close()


def add_columns(
    parquet_path: str, columns: list[str], dest_path: str,
) -> tuple[list[ColumnSchema], int]:
    """The same rows with these text columns added, empty - what an action
    log needs when its action gains a parameter after the log was made
    (§792). A column the file already has is left as it is."""
    con = duck.connect()
    try:
        try:
            con.execute(f"CREATE TABLE t AS SELECT * FROM read_parquet({parquet_path!r})")
            have = {row[0] for row in con.execute("DESCRIBE t").fetchall()}
            for column in columns:
                if column not in have:
                    con.execute(f"ALTER TABLE t ADD COLUMN {_quote_column(column)} VARCHAR")
            described = con.execute("DESCRIBE t").fetchall()
            schema = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
            row_count = int(con.execute("SELECT count(*) FROM t").fetchone()[0])
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            con.execute(f"COPY t TO '{dest_path}' (FORMAT parquet)")
            return schema, row_count
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
    finally:
        con.close()


def has_pair(parquet_path: str, from_column: str, to_column: str, pair: tuple[str, str]) -> bool:
    """Whether a join table holds this link now (§553), compared as text as
    `join_keys` reads one - what an undo asks before it reverses a link."""
    con = duck.connect()
    try:
        try:
            a, b = _quote_column(from_column), _quote_column(to_column)
            (count,) = con.execute(
                f"SELECT count(*) FROM read_parquet({parquet_path!r}) "
                f"WHERE CAST({a} AS VARCHAR) = ? AND CAST({b} AS VARCHAR) = ?",
                list(pair),
            ).fetchone()
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        return bool(count)
    finally:
        con.close()


def write_pairs(
    parquet_path: str,
    from_column: str,
    to_column: str,
    add: list[tuple[str, str]],
    remove: list[tuple[str, str]],
    dest_path: str,
) -> tuple[list[ColumnSchema], int, list[tuple[str, str]], list[tuple[str, str]]]:
    """Write links into a join table (§553; `action-types` p.20's "Create
    link(s)" and "Delete link"), as **one** file, for decision 0008's reason.

    Returns the schema, the row count, and **the pairs that actually changed**:
    a link made that was already there, or removed that was not, changed
    nothing, and recording it as a change would give an undo something to put
    back that never happened. Removals are applied before additions, so a
    submission that removes and re-makes one link leaves it made.

    Keys compare as text, as `join_keys` reads them; a pair is written into the
    columns' own types, and a key that will not convert is refused.
    """
    con = duck.connect()
    try:
        try:
            con.execute(f"CREATE TABLE t AS SELECT * FROM read_parquet({parquet_path!r})")
            a, b = _quote_column(from_column), _quote_column(to_column)
            # A row with an empty side reads as ("None", …), a pair no key
            # made or removed here is spelled as - so it is never touched,
            # and a filter for it survived the sweep as equivalent.
            existing = {
                (str(f), str(t)) for f, t in con.execute(
                    f"SELECT CAST({a} AS VARCHAR), CAST({b} AS VARCHAR) FROM t"
                ).fetchall()
            }
            after = (existing - set(remove)) | set(add)
            removed = sorted(existing - after)
            added = sorted(after - existing)
            for f, t in removed:
                con.execute(
                    f"DELETE FROM t WHERE CAST({a} AS VARCHAR) = ? AND CAST({b} AS VARCHAR) = ?",
                    [f, t],
                )
            for f, t in added:
                try:
                    con.execute(f"INSERT INTO t ({a}, {b}) VALUES (?, ?)", [f, t])
                except duckdb.Error as exc:
                    detail = next(
                        (line.strip() for line in str(exc).splitlines()[1:] if line.strip()),
                        _clean(exc),
                    )
                    raise DatasetEngineError(f"could not add a link: {detail}") from exc
            described = con.execute("DESCRIBE t").fetchall()
            schema = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
            row_count = int(con.execute("SELECT count(*) FROM t").fetchone()[0])
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            con.execute(f"COPY t TO '{dest_path}' (FORMAT parquet)")
            return schema, row_count, added, removed
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
    finally:
        con.close()


def write_back_row(
    parquet_path: str,
    primary_key_column: str,
    primary_key_value: str,
    column_updates: dict[str, Any],
    dest_path: str,
) -> tuple[list[ColumnSchema], int]:
    """One row updated, written as a new version. The single-write shape, kept
    because most callers have exactly one and `write_rows` reads oddly with a
    one-element list at every call site."""
    return write_rows(
        parquet_path, primary_key_column, [(primary_key_value, column_updates)], [], dest_path
    )


# ---- model transforms --------------------------------------------------------
TRANSFORM_BATCH_ROWS = 50_000
MAX_TRANSFORM_OUTPUT_ROWS = 5_000_000  # flag: worker/Athena path beyond this

_IDENT_RE_ENGINE = __import__("re").compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_RESERVED_ALIASES = {"dataset", "__model_output", "src"}


def validate_alias(alias: str) -> str:
    if not _IDENT_RE_ENGINE.match(alias) or alias.lower() in _RESERVED_ALIASES:
        raise DatasetEngineError(f"invalid input alias {alias!r}")
    return alias


def run_transform(
    inputs: dict[str, str], sql: str, dest_parquet: str
) -> tuple[list[ColumnSchema], int]:
    """Execute a SQL transform over named input datasets; write the result as
    Parquet. Returns (schema, row_count).

    Sandboxing has a wrinkle here: DuckDB's enable_external_access switch is
    one-way per connection, and writing Parquet needs external access. So the
    user's SQL runs in a sandboxed connection (inputs pre-materialised, all
    filesystem/network doors closed), and the result streams out in batches
    through a second, trusted connection that only ever executes SQL this
    module composed itself.
    """
    total_bytes = 0
    for alias, path in inputs.items():
        validate_alias(alias)
        total_bytes += os.path.getsize(path)
    if total_bytes > MAX_INTERACTIVE_BYTES:
        raise DatasetEngineError(
            "combined inputs exceed the interactive transform limit in this build - "
            "scheduled worker runs handle larger models"
        )

    sandbox = duck.connect()
    writer = duck.connect()
    try:
        sandbox.execute(f"SET memory_limit='{QUERY_MEMORY_LIMIT}'")
        for alias, path in inputs.items():
            sandbox.execute(
                f'CREATE TABLE "{alias}" AS SELECT * FROM read_parquet({path!r})'
            )
        # Sandbox boundary: user SQL sees only the input tables.
        duck.seal(sandbox)
        try:
            sandbox.execute(f"CREATE TABLE __model_output AS ({sql})")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        described = sandbox.execute("DESCRIBE __model_output").fetchall()
        if not described:
            raise DatasetEngineError("the transform produced no columns")
        schema = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
        row_count = int(sandbox.execute("SELECT count(*) FROM __model_output").fetchone()[0])
        if row_count > MAX_TRANSFORM_OUTPUT_ROWS:
            raise DatasetEngineError(
                f"the transform produced {row_count:,} rows - above this build's "
                f"{MAX_TRANSFORM_OUTPUT_ROWS:,} row limit"
            )

        columns_ddl = ", ".join(f'"{c.name}" {c.data_type}' for c in schema)
        writer.execute(f"CREATE TABLE __model_output ({columns_ddl})")
        placeholders = ", ".join("?" for _ in schema)
        cursor = sandbox.execute("SELECT * FROM __model_output")
        while True:
            batch = cursor.fetchmany(TRANSFORM_BATCH_ROWS)
            if not batch:
                break
            writer.executemany(
                f"INSERT INTO __model_output VALUES ({placeholders})", batch
            )
        os.makedirs(os.path.dirname(dest_parquet), exist_ok=True)
        writer.execute(f"COPY __model_output TO '{dest_parquet}' (FORMAT parquet)")
        return schema, row_count
    finally:
        sandbox.close()
        writer.close()


# ---- preview (ROADMAP.md phase 2, item 2.6) ----------------------------------
PREVIEW_SAMPLE_ROWS = 1000


@dataclass(frozen=True)
class PreviewedInput:
    alias: str
    rows_available: int
    rows_used: int

    @property
    def sampled(self) -> bool:
        return self.rows_used < self.rows_available


def preview_transform(
    inputs: dict[str, str],
    sql: str,
    *,
    sample_rows: int = PREVIEW_SAMPLE_ROWS,
    limit: int = PREVIEW_ROWS,
    spill_to: str | None = None,
) -> tuple[TabularResult, list[PreviewedInput]]:
    """Run a transform over a *sample* of its inputs and return the rows,
    writing nothing (roadmap item 2.6).

    Lives here, beside `run_transform`, because it needs the same sandbox
    discipline and a second almost-identical one would eventually drift from
    it. It is simpler in one respect: nothing is written, so there is no
    trusted writer connection and the user's SQL never leaves the sandbox
    where `enable_external_access` is off.

    **The row count returned is the count over the sample, and the caller must
    say so.** A transform with a join or a `group by` over the first thousand
    rows of each input produces an answer that is not the answer - one where
    the join found fewer matches than it will and the groups are smaller than
    they will be. That is inherent to previewing rather than running, which is
    why `PreviewedInput.sampled` exists: it is the difference between a screen
    a person can trust and one that quietly misleads them.

    **`spill_to` is the one exception to "writing nothing", and it exists for
    one caller** (§372's chained preview; `code-repositories` p.54). Analysing
    what a change does to a *derived* dataset means running the transform below
    it over the changed output, which has to exist as a file for the next hop
    to read. It follows `run_transform`'s discipline exactly: the user's SQL
    still runs in the sandbox with external access off, and the result leaves
    through a second, trusted connection executing only SQL this module
    composed, with the column DDL rebuilt from the sandbox's own DESCRIBE. It
    is a scratch file, not a dataset version — nothing is registered, nothing
    is versioned, and the caller deletes it.

    Spilled from `__model_output` rather than from the rows this returns,
    because those are capped at `limit` and passed through `json_safe`: a next
    hop fed them would be reading a hundred stringified rows and calling it a
    preview.
    """
    sample_rows = max(1, sample_rows)
    limit = max(1, min(limit, MAX_RESULT_ROWS))

    sandbox = duck.connect()
    try:
        sandbox.execute(f"SET memory_limit='{QUERY_MEMORY_LIMIT}'")
        previewed: list[PreviewedInput] = []
        for alias, path in inputs.items():
            validate_alias(alias)
            available = int(
                sandbox.execute(
                    f"SELECT count(*) FROM read_parquet({path!r})"
                ).fetchone()[0]
            )
            sandbox.execute(
                f'CREATE TABLE "{alias}" AS '
                f"SELECT * FROM read_parquet({path!r}) LIMIT {sample_rows}"
            )
            used = int(sandbox.execute(f'SELECT count(*) FROM "{alias}"').fetchone()[0])
            previewed.append(
                PreviewedInput(alias=alias, rows_available=available, rows_used=used)
            )

        # Sandbox boundary: user SQL sees only the sampled input tables, and
        # unlike run_transform nothing after this point needs it reopened.
        duck.seal(sandbox)
        try:
            sandbox.execute(f"CREATE TABLE __model_output AS ({sql})")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        described = sandbox.execute("DESCRIBE __model_output").fetchall()
        if not described:
            raise DatasetEngineError("the transform produced no columns")
        columns = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
        produced = int(sandbox.execute("SELECT count(*) FROM __model_output").fetchone()[0])
        if spill_to is not None:
            # The writer never sees user SQL — only this DDL and these inserts,
            # which is `run_transform`'s bargain made for the same reason.
            writer = duck.connect()
            try:
                columns_ddl = ", ".join(f'"{c.name}" {c.data_type}' for c in columns)
                writer.execute(f"CREATE TABLE __spill ({columns_ddl})")
                placeholders = ", ".join("?" for _ in columns)
                cursor = sandbox.execute("SELECT * FROM __model_output")
                while True:
                    batch = cursor.fetchmany(TRANSFORM_BATCH_ROWS)
                    if not batch:
                        break
                    writer.executemany(
                        f"INSERT INTO __spill VALUES ({placeholders})", batch
                    )
                os.makedirs(os.path.dirname(spill_to), exist_ok=True)
                writer.execute(f"COPY __spill TO '{spill_to}' (FORMAT parquet)")
            finally:
                writer.close()

        rows = sandbox.execute(
            f"SELECT * FROM __model_output LIMIT {limit}"
        ).fetchall()
        return (
            TabularResult(
                columns=columns,
                rows=[[json_safe(value) for value in row] for row in rows],
                # Rows the transform produced *from the sample*, not from the
                # datasets. Named total_rows only because every other tabular
                # response is; the caller has to make the difference visible.
                total_rows=produced,
                truncated=len(rows) < produced,
            ),
            previewed,
        )
    finally:
        sandbox.close()
