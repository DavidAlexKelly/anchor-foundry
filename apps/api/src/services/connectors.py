"""Connector registry (spec §"Connections" supported source types).

Every source type implements one interface and the registry maps
``connection.source_type`` to an implementation. Nothing above this module
knows which driver is in play:

    validate_config(config)   -> the cleaned, non-secret config to store
    test(config, secret)      -> None; raises ConnectorOperationError
    discover(config, secret)  -> [TableInfo]
    preview(...)              -> a Preview: a capped sample of one table
    snapshot(...)             -> an Extract: a file on disk, byte-capped
    max_cursor_value(...)     -> the source's current high-water mark

The last two are the roadmap's ``snapshot()``/``incremental(cursor)`` as a
single method rather than two: an incremental pull is the same extract with a
``WHERE cursor > :last`` predicate, and every relational source implements it
that way. Splitting them would duplicate the byte-cap and error-translation
loop in each connector for no behavioural difference; ``cursor_column`` being
``None`` (a full snapshot) is the only fork, and it is one line of SQL.

``snapshot`` returns an ``Extract`` (path + extension) rather than always
writing CSV, because not every source *has* a row-by-row wire format worth
inventing one for. A database has to serialise its rows to something, and CSV
is the honest choice there; an object-storage source is already sitting on a
Parquet or JSON file that ``dataset_engine`` can read directly, and pushing it
through CSV on the way would discard the types Parquet is carrying for no
reason. Callers hand the returned extension straight to
``ingest_to_parquet``, which has always taken one.

Callers own *policy* (how many bytes an interactive sync may pull, which
dataset the rows land in), connectors own *mechanism* (the driver call and
its error translation) - hence ``max_bytes`` being a parameter rather than a
constant here.

The registry holds only connectors that genuinely work in this build.
Additional source types from the spec's list (Snowflake, S3, Salesforce, …)
are additive registry entries with their own drivers; they are deliberately
not listed until implemented, so the UI can never offer a connector that
fails.

Driver calls are synchronous; routes run them in a worker thread. The worker
carries its own trimmed copy of the snapshot/cursor half of this interface
(``anchor_worker.connectors``) for the same reason it copies
``dataset_engine``/``storage``: api and worker are independently deployable
images with no shared Python package in this build. The two must be kept in
step - a source type that syncs interactively but not on a schedule is a
silent, per-connector failure.
"""
from __future__ import annotations

import csv
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from . import egress


class ConnectorConfigError(ValueError):
    """Config failed the connector's schema. Message is user-safe."""


class ConnectorOperationError(RuntimeError):
    """Test/discover/extract failed against the source. Message is user-safe
    (no credentials, no stack traces)."""


class SourceReadError(ConnectorOperationError):
    """The named table could not be read: it does not exist, the connection's
    user cannot see it, or it exceeds the caller's byte cap. A subclass of
    ConnectorOperationError so every existing `except ConnectorOperationError`
    still catches it - the distinction is for callers that want to tell "the
    source is unreachable" apart from "the source is fine, this table isn't"."""


# Identifier guard applied before any name reaches SQL. Driver-side identifier
# quoting (psycopg's sql.Identifier, backticks for MySQL) is what actually makes
# the query safe; this check runs first so a malformed name fails with a clear
# message instead of a driver syntax error.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")


def check_identifier(name: str) -> str:
    if not _IDENT_RE.match(name or ""):
        raise SourceReadError(f"invalid identifier {name!r}")
    return name


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool


@dataclass(frozen=True)
class TableInfo:
    schema: str
    name: str
    kind: str  # "table" | "view" | "file" | "endpoint"
    columns: list[ColumnInfo] = field(default_factory=list)


@dataclass(frozen=True)
class Extract:
    """What a snapshot produced: a file on disk plus the extension
    dataset_engine should read it as.

    `empty` means "the source had nothing past the cursor" - the ordinary
    steady state of a scheduled incremental sync between source writes. It is
    an explicit flag rather than something callers infer from a row count
    because a source can legitimately produce *no file at all* in that case
    (an object-storage connector with no new objects has nothing to write),
    and because inferring it costs a pointless ingest of a header-only CSV -
    the exact path that produced the all-VARCHAR type-inference bug this
    codebase already had to fix once.
    """

    path: str
    extension: str
    empty: bool = False


# ---- source preview (decision 0015; `data-connection` p.142-143) -------------
#
# Not to be confused with `dataset_engine.PREVIEW_ROWS`, which samples a dataset
# this platform already holds. These bound a read of a system we do not own,
# whose result travels in a JSON response rather than into a file - so the
# limits are tighter and they exist for a different reason (decision 0015 §4).

#: p.143's "sample of the selected table". Enough rows to see shape and to
#: notice a column that is entirely null, which is the failure p.18 says people
#: actually open this screen to find.
PREVIEW_ROWS = 50

#: A single text column can hold megabytes, and fifty of them would be a denial
#: of service the platform performs on itself.
PREVIEW_CELL = 500


@dataclass(frozen=True)
class Preview:
    """A sample of what a sync would read, from a source, before it reads it.

    **Everything is a string, and `None` is not.** The connectors already
    stringify for CSV and a preview that tried to preserve types would be a
    second type system that could disagree with `dataset_engine`'s - the screen
    would show a number the sync would later store as text. But a null stays
    null rather than becoming `""`, because "this column is empty" and "this
    column is missing" are the two answers somebody is reading a preview to
    tell apart (decision 0015 §4).

    `more` is exact rather than inferred: every connector asks for one row past
    the cap, so "there are more" is something the source said and not something
    a full sample was taken to mean.
    """

    columns: list[str]
    rows: list[list[str | None]]
    more: bool = False
    #: How many cells were shortened to `PREVIEW_CELL`. Decision 0015 §4 keeps
    #: this because the shortening itself is the one place a preview is
    #: allowed to be inexact - a real value that is exactly the cap long and
    #: ends in an ellipsis cannot be told from a truncated one, so the count
    #: is what lets a screen say that shortening happened at all.
    truncated_cells: int = 0


def build_preview(columns: Iterable[str], rows: Iterable[Sequence[Any]]) -> Preview:
    """Apply decision 0015 §4's caps, once, for every connector.

    One place rather than four, because four copies of "take fifty and shorten
    the long ones" are four chances to disagree about what fifty means - and
    because a cap each connector implemented for itself is a cap no single
    test could kill.
    """
    kept: list[list[str | None]] = []
    shortened = 0
    more = False
    for row in rows:
        if len(kept) >= PREVIEW_ROWS:
            more = True
            break
        cells: list[str | None] = []
        for value in row:
            if value is None:
                cells.append(None)
                continue
            text = value if isinstance(value, str) else str(dataset_engine_safe(value))
            if len(text) > PREVIEW_CELL:
                text = text[:PREVIEW_CELL] + "…"
                shortened += 1
            cells.append(text)
        kept.append(cells)
    return Preview(columns=list(columns), rows=kept, more=more, truncated_cells=shortened)


def dataset_engine_safe(value: Any) -> Any:
    """`json_safe`, reached lazily.

    A date must reach the screen as the ISO string the sync would write, and
    bytes must not reach it at all - both of which `dataset_engine.json_safe`
    already decides. Importing it at call time keeps `connectors` free of a
    module-level dependency on duckdb, which is the arrangement every other
    crossing in this file uses.
    """
    from . import dataset_engine as _engine

    return _engine.json_safe(value)


class SourceConnector(Protocol):
    """What a source type must implement to be registered.

    Implementations are stateless and safe to share across requests; all
    per-call state arrives as arguments.
    """

    type_name: str
    display_name: str
    config_model: type[BaseModel]
    secret_fields: tuple[str, ...]

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Re-derive the stored config shape, dropping anything a client
        smuggled in. Raises ConnectorConfigError."""

    def test(self, config: dict[str, Any], secret: dict[str, str]) -> None:
        """Reach the source and prove the credentials work."""

    def discover(self, config: dict[str, Any], secret: dict[str, str]) -> list[TableInfo]:
        """Every table/view the connection's user can see, with columns."""

    def preview(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
    ) -> Preview:
        """A capped sample of one table, read the way a sync would read it
        (decision 0015; p.142-143).

        **Never a query.** The arguments are a schema and a table and nothing
        else, and they are checked as identifiers - the moment a caller could
        shape the read, "an editor may see fifty rows" would become "an editor
        may run statements as the connection's user", which is a much larger
        grant than the sync this preview is standing in for.

        The sample is unordered and so is not the *first* rows: p.161 calls the
        equivalent choice on the file side "a non-deterministic subset", and an
        ORDER BY would need a key the source may not have and would turn the
        cheapest check in the platform into a full sort. Raises SourceReadError
        when the table is absent or the credential cannot read it - which is
        p.18's most common use of this screen rather than a failure of it."""

    def snapshot(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        dest_dir: str,
        max_bytes: int,
        cursor_column: str | None = None,
        cursor_value: str | None = None,
    ) -> Extract:
        """Extract the table into a file inside dest_dir (which the caller
        owns and cleans up). With cursor_column/cursor_value set, only what is
        strictly past the cursor - the incremental pull. Raises SourceReadError
        past max_bytes."""

    def max_cursor_value(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        cursor_column: str,
    ) -> str | None:
        """The highest cursor value currently in the source - becomes the
        connection's new sync_last_cursor_value once the sync succeeds.
        None when the table is empty."""


class _CappedCsvWriter:
    """Streams rows to CSV, aborting past a byte cap.

    For drivers without a server-side COPY-to-CSV (MySQL and every future
    row-iterating driver); the Postgres connector streams COPY output
    straight through and counts bytes itself.
    """

    def __init__(self, dest_csv: str, max_bytes: int) -> None:
        self._dest = dest_csv
        self._max_bytes = max_bytes
        self._written = 0

    def __enter__(self) -> _CappedCsvWriter:
        self._handle = open(self._dest, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._handle)
        return self

    def __exit__(self, *exc: Any) -> None:
        self._handle.close()

    def writerow(self, row: list[Any]) -> None:
        self._writer.writerow(row)
        # tell() rather than summing len(): the csv module's own quoting and
        # line terminators are part of what counts against the cap.
        self._written = self._handle.tell()
        if self._written > self._max_bytes:
            raise size_cap_error(self._max_bytes)


def size_cap_error(max_bytes: int) -> SourceReadError:
    cap_mb = max_bytes // (1024 * 1024)
    return SourceReadError(
        f"table exceeds the {cap_mb} MB interactive sync limit - "
        "scheduled worker syncs handle larger tables"
    )


# ---- PostgreSQL --------------------------------------------------------------
class PostgresConfig(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    user: str = Field(min_length=1, max_length=128)
    # Literal rather than a regex so the generated JSON schema carries `enum`:
    # the create wizard renders a picker from it instead of a free-text box.
    sslmode: Literal["disable", "prefer", "require", "verify-ca", "verify-full"] = "prefer"


class PostgresConnector:
    type_name = "postgres"
    display_name = "PostgreSQL"
    config_model: type[BaseModel] = PostgresConfig
    secret_fields = ("password",)

    _CONNECT_TIMEOUT_S = 8

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        try:
            return PostgresConfig(**config).model_dump()
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"])
            raise ConnectorConfigError(f"{loc}: {first['msg']}") from exc

    def _conninfo(self, config: dict[str, Any], secret: dict[str, str]) -> dict[str, Any]:
        cfg = PostgresConfig(**config)
        # **The one chokepoint for this connector** (§263). Every `test`,
        # `discover` and `snapshot` builds its connection here, so the guard is
        # made once rather than three times — and a fourth operation added
        # later gets it without anybody remembering to.
        #
        # A host and a port, not a URL, which is the shape decision 0013 §3 says
        # the check has to take: this path never had a URL and `_check_url` was
        # never on it.
        egress.check_current(cfg.host, cfg.port)
        return {
            "host": cfg.host,
            "port": cfg.port,
            "dbname": cfg.database,
            "user": cfg.user,
            "password": secret.get("password", ""),
            "sslmode": cfg.sslmode,
            "connect_timeout": self._CONNECT_TIMEOUT_S,
        }

    @staticmethod
    def _operational(exc: Exception) -> ConnectorOperationError:
        # First line of the driver message is user-safe (auth failed, host
        # unreachable, unknown database); never includes the password.
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
        return ConnectorOperationError(reason)

    def test(self, config: dict[str, Any], secret: dict[str, str]) -> None:
        import psycopg

        try:
            with psycopg.connect(**self._conninfo(config, secret)) as conn:
                conn.execute("SELECT 1")
        except psycopg.OperationalError as exc:
            raise self._operational(exc) from exc

    def discover(self, config: dict[str, Any], secret: dict[str, str]) -> list[TableInfo]:
        import psycopg

        sql = """
            SELECT c.table_schema, c.table_name, t.table_type,
                   c.column_name, c.data_type, c.is_nullable = 'YES' AS nullable,
                   EXISTS (
                       SELECT 1
                         FROM information_schema.table_constraints tc
                         JOIN information_schema.key_column_usage kcu
                           ON kcu.constraint_name = tc.constraint_name
                          AND kcu.table_schema = tc.table_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_schema = c.table_schema
                          AND tc.table_name = c.table_name
                          AND kcu.column_name = c.column_name
                   ) AS is_pk
              FROM information_schema.columns c
              JOIN information_schema.tables t
                ON t.table_schema = c.table_schema AND t.table_name = c.table_name
             WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
             ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """
        try:
            with psycopg.connect(**self._conninfo(config, secret)) as conn:
                rows = conn.execute(sql).fetchall()
        except psycopg.OperationalError as exc:
            raise self._operational(exc) from exc

        tables: dict[tuple[str, str], TableInfo] = {}
        for schema, name, table_type, col, dtype, nullable, is_pk in rows:
            key = (schema, name)
            if key not in tables:
                tables[key] = TableInfo(
                    schema=schema,
                    name=name,
                    kind="view" if table_type == "VIEW" else "table",
                )
            tables[key].columns.append(
                ColumnInfo(name=col, data_type=dtype, nullable=bool(nullable), is_primary_key=bool(is_pk))
            )
        return list(tables.values())

    def preview(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
    ) -> Preview:
        import psycopg
        from psycopg import sql

        # PREVIEW_ROWS + 1: `Preview.more` is then something the source said
        # rather than something a full page was taken to imply.
        query = sql.SQL("SELECT * FROM {}.{} LIMIT {}").format(
            sql.Identifier(check_identifier(source_schema)),
            sql.Identifier(check_identifier(source_table)),
            sql.Literal(PREVIEW_ROWS + 1),
        )
        try:
            with psycopg.connect(**self._conninfo(config, secret)) as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    columns = [d.name for d in cur.description or []]
                    rows = cur.fetchall()
        except psycopg.errors.UndefinedTable as exc:
            raise SourceReadError(
                f"table {source_schema}.{source_table} does not exist"
            ) from exc
        except psycopg.errors.InsufficientPrivilege as exc:
            # p.18 says checking "the correct permissions and credentials are
            # being used" is the most common reason to open this screen, so
            # this sentence is the feature rather than an error path.
            raise SourceReadError(
                f"the connection's user cannot read {source_schema}.{source_table}"
            ) from exc
        except psycopg.OperationalError as exc:
            raise self._operational(exc) from exc
        return build_preview(columns, rows)

    def snapshot(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        dest_dir: str,
        max_bytes: int,
        cursor_column: str | None = None,
        cursor_value: str | None = None,
    ) -> Extract:
        import psycopg
        from psycopg import sql

        dest_csv = os.path.join(dest_dir, "snapshot.csv")

        qualified = sql.SQL("{}.{}").format(
            sql.Identifier(check_identifier(source_schema)),
            sql.Identifier(check_identifier(source_table)),
        )
        if cursor_column and cursor_value is not None:
            query = sql.SQL(
                "COPY (SELECT * FROM {} WHERE {} > {}) TO STDOUT (FORMAT csv, HEADER true)"
            ).format(
                qualified,
                sql.Identifier(check_identifier(cursor_column)),
                sql.Literal(cursor_value),
            )
        else:
            query = sql.SQL("COPY (SELECT * FROM {}) TO STDOUT (FORMAT csv, HEADER true)").format(
                qualified
            )

        written = 0
        try:
            with psycopg.connect(**self._conninfo(config, secret)) as conn:
                with conn.cursor() as cur, open(dest_csv, "wb") as out:
                    with cur.copy(query) as copy:
                        for chunk in copy:
                            written += len(chunk)
                            if written > max_bytes:
                                raise size_cap_error(max_bytes)
                            out.write(bytes(chunk))
        except psycopg.errors.UndefinedTable as exc:
            raise SourceReadError(
                f"table {source_schema}.{source_table} does not exist"
            ) from exc
        except psycopg.errors.InsufficientPrivilege as exc:
            raise SourceReadError(
                f"the connection's user cannot read {source_schema}.{source_table}"
            ) from exc
        except psycopg.OperationalError as exc:
            raise self._operational(exc) from exc
        return Extract(path=dest_csv, extension=".csv")

    def max_cursor_value(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        cursor_column: str,
    ) -> str | None:
        import psycopg
        from psycopg import sql

        # A relational source has no high-water mark without a column to take
        # it from. Returning None (rather than raising) lets callers ask every
        # incremental sync for a cursor without first knowing whether this
        # particular connector needs a column - object storage, whose cursor is
        # the object's own LastModified, ignores the argument entirely.
        if not cursor_column:
            return None

        query = sql.SQL("SELECT max({}) FROM {}.{}").format(
            sql.Identifier(check_identifier(cursor_column)),
            sql.Identifier(check_identifier(source_schema)),
            sql.Identifier(check_identifier(source_table)),
        )
        try:
            with psycopg.connect(**self._conninfo(config, secret)) as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    row = cur.fetchone()
        except psycopg.errors.UndefinedTable as exc:
            raise SourceReadError(
                f"table {source_schema}.{source_table} does not exist"
            ) from exc
        except psycopg.OperationalError as exc:
            raise self._operational(exc) from exc
        return None if row is None or row[0] is None else str(row[0])

    # ---- export (decision 0014; `data-connection` p.195-197) -----------------
    def destination_columns(
        self, config: dict[str, Any], secret: dict[str, str],
        *, schema: str, table: str,
    ) -> list[str]:
        """The target table's column names, in the destination's own spelling.

        For p.197's 1:1 check, which this platform makes *before* writing.
        Foundry lets a mismatch "fail at runtime", and failing at row 40,000 of
        a table export tells nobody which column was wrong.

        A focused query rather than `discover`, which enumerates every table in
        the database to answer a question about one.
        """
        import psycopg
        from psycopg import sql

        try:
            with psycopg.connect(**self._conninfo(config, secret)) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema = %s AND table_name = %s"
                        " ORDER BY ordinal_position",
                        (schema or "public", table),
                    )
                    names = [str(row[0]) for row in cur.fetchall()]
        except psycopg.OperationalError as exc:
            raise self._operational(exc) from exc
        if not names:
            # p.197: "The destination table must already exist in the source
            # system; it will not be automatically created by Foundry." An
            # empty column list and a missing table are the same answer here,
            # and the message says the actionable one.
            raise SourceReadError(
                f"table {schema or 'public'}.{table} does not exist in the "
                "destination - an export does not create it (p.197)"
            )
        return names

    def export_rows(
        self, config: dict[str, Any], secret: dict[str, str],
        *, schema: str, table: str, columns: list[str], csv_path: str,
        truncate: bool,
    ) -> int:
        """Write a CSV's rows into the target table. Returns rows written.

        `COPY ... FROM STDIN` rather than p.198-200's `INSERT` statements. That
        page is about what Foundry emits *for a custom JDBC source whose
        dialect it cannot assume*; this connector knows it is talking to
        Postgres, and `COPY` is the same operation stated in the dialect the
        far end actually speaks. Decision 0014 says parity is with the model,
        not the wire format.

        **The truncate and the insert are one transaction.** p.195's mirror
        mode promises the external table "always matches what you see in the
        Foundry dataset", and a truncate committed before a failed insert would
        leave it matching nothing — which is worse than either end state and is
        the moment somebody's dashboard goes blank.
        """
        import psycopg
        from psycopg import sql

        target = sql.SQL("{}.{}").format(
            sql.Identifier(check_identifier(schema or "public")),
            sql.Identifier(check_identifier(table)),
        )
        column_list = sql.SQL(", ").join(
            sql.Identifier(check_identifier(name)) for name in columns
        )
        written = 0
        try:
            with psycopg.connect(**self._conninfo(config, secret)) as conn:
                with conn.cursor() as cur:
                    if truncate:
                        cur.execute(sql.SQL("TRUNCATE TABLE {}").format(target))
                    copy_sql = sql.SQL(
                        "COPY {} ({}) FROM STDIN (FORMAT csv, HEADER true)"
                    ).format(target, column_list)
                    with open(csv_path, "rb") as handle, cur.copy(copy_sql) as copy:
                        while chunk := handle.read(1 << 20):
                            copy.write(chunk)
                    written = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                conn.commit()
        except psycopg.errors.InsufficientPrivilege as exc:
            # p.197 and p.203 both warn about this and it is worth its own
            # sentence: truncation needs a permission a plain writer does not
            # have, so "permission denied" here has two quite different causes.
            what = "truncate and write" if truncate else "write to"
            raise SourceReadError(
                f"the connection's user cannot {what} {schema or 'public'}.{table}"
            ) from exc
        except psycopg.errors.UndefinedTable as exc:
            raise SourceReadError(
                f"table {schema or 'public'}.{table} does not exist in the destination"
            ) from exc
        except psycopg.OperationalError as exc:
            raise self._operational(exc) from exc
        except psycopg.Error as exc:
            raise SourceReadError(self._operational(exc).args[0]) from exc
        return written


# ---- MySQL / MariaDB ---------------------------------------------------------
# MySQL has no schema-within-database concept: what Postgres calls a schema is
# what MySQL calls a database. `source_schema` therefore carries the database
# name for this connector, and `discover` reports each database as a schema -
# so the layers above (sync targets, the discovery UI, object-type sources)
# keep one vocabulary across source types rather than special-casing MySQL.
#
# Identifier rules genuinely differ from Postgres and this is where that has to
# be honoured: MySQL allows a leading digit (`2024_orders` is a legal table
# name) and 64 characters rather than 63.
_MYSQL_IDENT_RE = re.compile(r"^[A-Za-z0-9_$]{1,64}$")


def _check_mysql_identifier(name: str) -> str:
    if not _MYSQL_IDENT_RE.match(name or ""):
        raise SourceReadError(f"invalid identifier {name!r}")
    return name


def _quote_mysql(name: str) -> str:
    # Validated above; backticks doubled per MySQL's own escaping rule so the
    # quoting is safe on its own terms, not only because of the check.
    return "`" + _check_mysql_identifier(name).replace("`", "``") + "`"


class MySQLConfig(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=64)
    user: str = Field(min_length=1, max_length=32)
    # Deliberately not mirroring PostgresConfig's `prefer` default: PyMySQL has
    # no negotiate-then-downgrade mode, so "prefer" could only be implemented as
    # try-TLS-then-silently-retry-in-plaintext. An explicit choice beats a
    # silent downgrade; `required` is the safe default and a plaintext source
    # has to opt in. `required` means encrypt-without-verifying-the-certificate,
    # the same guarantee Postgres' own `sslmode=require` gives; verify-ca/
    # verify-full would need a customer-supplied CA this config doesn't carry.
    ssl_mode: Literal["disabled", "required"] = "required"


class MySQLConnector:
    """MySQL/MariaDB. Same relational shape as Postgres - the differences that
    actually matter are the driver, the information_schema dialect, the
    identifier rules above, and the absence of a server-side COPY-to-CSV
    (rows are streamed client-side through _CappedCsvWriter instead)."""

    type_name = "mysql"
    display_name = "MySQL / MariaDB"
    config_model: type[BaseModel] = MySQLConfig
    secret_fields = ("password",)

    _CONNECT_TIMEOUT_S = 8
    _SYSTEM_SCHEMAS = ("information_schema", "performance_schema", "mysql", "sys")
    #: Rows per `INSERT` on an export (p.199's multi-row form). Large enough
    #: that the round trips stop dominating, small enough to stay well under
    #: `max_allowed_packet`'s 4 MB default at any plausible row width.
    _BATCH = 500

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        try:
            return MySQLConfig(**config).model_dump()
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"])
            raise ConnectorConfigError(f"{loc}: {first['msg']}") from exc

    def _connect_kwargs(self, config: dict[str, Any], secret: dict[str, str]) -> dict[str, Any]:
        cfg = MySQLConfig(**config)
        # The same chokepoint one connector over (§263), for the same reason.
        egress.check_current(cfg.host, cfg.port)
        kwargs: dict[str, Any] = {
            "host": cfg.host,
            "port": cfg.port,
            "database": cfg.database,
            "user": cfg.user,
            "password": secret.get("password", ""),
            "connect_timeout": self._CONNECT_TIMEOUT_S,
            "charset": "utf8mb4",
        }
        if cfg.ssl_mode == "required":
            import ssl as ssl_module

            kwargs["ssl"] = {
                "check_hostname": False,
                "verify_mode": ssl_module.CERT_NONE,
            }
        return kwargs

    def _connect(self, config: dict[str, Any], secret: dict[str, str]):
        """Connect, and when ssl_mode is `required`, prove the session actually
        got encrypted.

        This second step is not belt-and-braces, it is the enforcement: PyMySQL
        upgrades to TLS only `if self.ssl and self.server_capabilities &
        CLIENT.SSL` (read from its own source, then confirmed live against a
        server built without TLS) - so against a plaintext-only server it
        silently completes the handshake unencrypted and reports success.
        Without this check `required` would be a promise the code doesn't keep.
        Ssl_cipher is empty exactly when the session is not encrypted.
        """
        import pymysql

        conn = pymysql.connect(**self._connect_kwargs(config, secret))
        if config.get("ssl_mode", "required") != "required":
            return conn
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW STATUS LIKE 'Ssl_cipher'")
                row = cur.fetchone()
            cipher = row[1] if row and len(row) > 1 else ""
        except pymysql.MySQLError:
            conn.close()
            raise
        if not cipher:
            conn.close()
            raise ConnectorOperationError(
                "the server accepted the connection without TLS, but this "
                "connection requires it - enable TLS on the source or set "
                "ssl_mode to 'disabled' to accept a plaintext connection"
            )
        return conn

    @staticmethod
    def _translate(exc: Exception, source_schema: str = "", source_table: str = "") -> Exception:
        """MySQL reports 'missing table' and 'no privilege' as ordinary errors
        with a numeric code rather than distinct exception classes, so the code
        is what the mapping keys on."""
        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
        qualified = f"{source_schema}.{source_table}" if source_table else "the source table"
        if code == 1146:  # ER_NO_SUCH_TABLE
            return SourceReadError(f"table {qualified} does not exist")
        if code in (1142, 1143, 1044, 1045):  # table/column/db access denied
            return SourceReadError(f"the connection's user cannot read {qualified}")
        if code == 1054:  # ER_BAD_FIELD_ERROR - a cursor/pk column that isn't there
            return SourceReadError(str(exc.args[1]) if len(exc.args) > 1 else str(exc))
        # Message carries host/user/error code but never the password.
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
        return ConnectorOperationError(reason)

    def test(self, config: dict[str, Any], secret: dict[str, str]) -> None:
        import pymysql

        try:
            with self._connect(config, secret) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
        except pymysql.MySQLError as exc:
            raise self._translate(exc) from exc

    def discover(self, config: dict[str, Any], secret: dict[str, str]) -> list[TableInfo]:
        import pymysql

        placeholders = ", ".join(["%s"] * len(self._SYSTEM_SCHEMAS))
        sql = f"""
            SELECT c.TABLE_SCHEMA, c.TABLE_NAME, t.TABLE_TYPE, c.COLUMN_NAME,
                   c.DATA_TYPE, c.IS_NULLABLE = 'YES', c.COLUMN_KEY = 'PRI'
              FROM information_schema.COLUMNS c
              JOIN information_schema.TABLES t
                ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
             WHERE c.TABLE_SCHEMA NOT IN ({placeholders})
             ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
        """
        try:
            with self._connect(config, secret) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, self._SYSTEM_SCHEMAS)
                    rows = cur.fetchall()
        except pymysql.MySQLError as exc:
            raise self._translate(exc) from exc

        tables: dict[tuple[str, str], TableInfo] = {}
        for schema, name, table_type, col, dtype, nullable, is_pk in rows:
            key = (schema, name)
            if key not in tables:
                tables[key] = TableInfo(
                    schema=schema,
                    name=name,
                    kind="view" if table_type == "VIEW" else "table",
                )
            tables[key].columns.append(
                ColumnInfo(
                    name=col,
                    data_type=dtype,
                    nullable=bool(nullable),
                    is_primary_key=bool(is_pk),
                )
            )
        return list(tables.values())

    def preview(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
    ) -> Preview:
        import pymysql

        qualified = f"{_quote_mysql(source_schema)}.{_quote_mysql(source_table)}"
        try:
            with self._connect(config, secret) as conn:
                with conn.cursor() as cur:
                    # The limit is a bound parameter, not interpolated, because
                    # every other value in this file that reaches SQL is - the
                    # identifiers are quoted precisely because they cannot be.
                    cur.execute(f"SELECT * FROM {qualified} LIMIT %s", (PREVIEW_ROWS + 1,))
                    columns = [d[0] for d in cur.description or []]
                    rows = cur.fetchall()
        except pymysql.MySQLError as exc:
            raise self._translate(exc, source_schema, source_table) from exc
        return build_preview(columns, rows)

    def snapshot(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        dest_dir: str,
        max_bytes: int,
        cursor_column: str | None = None,
        cursor_value: str | None = None,
    ) -> Extract:
        import pymysql
        import pymysql.cursors

        dest_csv = os.path.join(dest_dir, "snapshot.csv")
        qualified = f"{_quote_mysql(source_schema)}.{_quote_mysql(source_table)}"
        params: tuple[Any, ...] = ()
        if cursor_column and cursor_value is not None:
            query = f"SELECT * FROM {qualified} WHERE {_quote_mysql(cursor_column)} > %s"
            params = (cursor_value,)
        else:
            query = f"SELECT * FROM {qualified}"

        try:
            with self._connect(config, secret) as conn:
                # SSCursor streams from the server rather than buffering the
                # whole result in memory first - the byte cap below is only
                # meaningful if the rows arrive incrementally.
                with conn.cursor(pymysql.cursors.SSCursor) as cur:
                    cur.execute(query, params)
                    header = [d[0] for d in cur.description or []]
                    with _CappedCsvWriter(dest_csv, max_bytes) as out:
                        out.writerow(header)
                        for row in cur:
                            out.writerow([_csv_value(v) for v in row])
        except pymysql.MySQLError as exc:
            raise self._translate(exc, source_schema, source_table) from exc
        return Extract(path=dest_csv, extension=".csv")

    def max_cursor_value(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        cursor_column: str,
    ) -> str | None:
        import pymysql

        if not cursor_column:
            return None  # see PostgresConnector.max_cursor_value

        query = (
            f"SELECT max({_quote_mysql(cursor_column)}) "
            f"FROM {_quote_mysql(source_schema)}.{_quote_mysql(source_table)}"
        )
        try:
            with self._connect(config, secret) as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    row = cur.fetchone()
        except pymysql.MySQLError as exc:
            raise self._translate(exc, source_schema, source_table) from exc
        return None if row is None or row[0] is None else str(row[0])

    # ---- export (decision 0014; `data-connection` p.195-197) -----------------
    def destination_columns(
        self, config: dict[str, Any], secret: dict[str, str],
        *, schema: str, table: str,
    ) -> list[str]:
        """The target table's columns. See `PostgresConnector.destination_columns`.

        `schema` is a MySQL *database*, per this connector's own vocabulary
        note above — and it falls back to the connection's configured database
        rather than to a constant, because MySQL has no `public`.
        """
        import pymysql

        database = schema or str(config.get("database") or "")
        if not database:
            raise SourceReadError("a MySQL export needs a database to write into")
        try:
            with self._connect(config, secret) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema = %s AND table_name = %s"
                        " ORDER BY ordinal_position",
                        (database, table),
                    )
                    names = [str(row[0]) for row in cur.fetchall()]
        except pymysql.MySQLError as exc:
            raise self._translate(exc, database, table) from exc
        if not names:
            raise SourceReadError(
                f"table {database}.{table} does not exist in the destination - "
                "an export does not create it (p.197)"
            )
        return names

    def export_rows(
        self, config: dict[str, Any], secret: dict[str, str],
        *, schema: str, table: str, columns: list[str], csv_path: str,
        truncate: bool,
    ) -> int:
        """Write a CSV's rows into the target table. Returns rows written.

        **Batched `INSERT`, which is p.198-200's shape and here it is not a
        compromise**: MySQL has no `COPY FROM STDIN`, and `LOAD DATA LOCAL
        INFILE` needs a server-side setting the connection cannot assume. So
        this is the multi-row insert p.199 shows, at `_BATCH` rows a statement.

        **The truncate and the inserts are one transaction**, for the reason
        `PostgresConnector.export_rows` gives — and it costs something here
        that it does not there: `TRUNCATE TABLE` is DDL in MySQL and commits
        implicitly, so this uses `DELETE FROM` instead. Slower on a large
        table, and the only form that can be rolled back. p.195's mirror mode
        promises the table always matches the dataset, and a table left empty
        by a half-done export matches nothing.
        """
        import csv as csv_module

        import pymysql

        database = schema or str(config.get("database") or "")
        target = f"{_quote_mysql(database)}.{_quote_mysql(table)}"
        column_list = ", ".join(_quote_mysql(name) for name in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        statement = f"INSERT INTO {target} ({column_list}) VALUES ({placeholders})"

        written = 0
        try:
            with self._connect(config, secret) as conn:
                with conn.cursor() as cur:
                    if truncate:
                        cur.execute(f"DELETE FROM {target}")
                    with open(csv_path, newline="", encoding="utf-8") as handle:
                        reader = csv_module.reader(handle)
                        header = next(reader, None)
                        if header is None:
                            conn.commit()
                            return 0
                        # The CSV is written from the dataset in its own column
                        # order; the insert names its columns in the same
                        # order, so position is meaningful. Asserted rather
                        # than assumed, because a silent mismatch here writes
                        # every value into the wrong column.
                        if [h.strip() for h in header] != list(columns):
                            raise SourceReadError(
                                "the exported file's columns do not match the "
                                "export's column list"
                            )
                        batch: list[tuple] = []
                        for row in reader:
                            batch.append(tuple(None if v == "" else v for v in row))
                            if len(batch) >= self._BATCH:
                                cur.executemany(statement, batch)
                                written += len(batch)
                                batch = []
                        if batch:
                            cur.executemany(statement, batch)
                            written += len(batch)
                conn.commit()
        except pymysql.err.OperationalError as exc:
            raise self._translate(exc, database, table) from exc
        except pymysql.MySQLError as exc:
            raise self._translate(exc, database, table) from exc
        return written


def _csv_value(value: Any) -> Any:
    """Row values on their way into the CSV DuckDB will re-infer types from.

    Only two cases need help: None must land as an unquoted empty field (what
    Postgres COPY writes for NULL, and what csv.writer already does), and bytes
    would otherwise be written as a Python repr (`b'\\x00'`). Hex is lossless
    and unambiguous - binary columns flattening to text is the same documented
    limitation CSV-as-wire-format already carries for exotic types.
    """
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


# ---- S3 / object storage -----------------------------------------------------
# The first non-relational source type, and the one that made `snapshot` return
# an Extract rather than always writing CSV: these objects are already in a
# format dataset_engine reads natively.
#
# Coordinate mapping, so the layers above keep one vocabulary (same move the
# MySQL connector makes for database-means-schema):
#   source_schema -> the "folder" the object sits in, relative to the
#                    connection's configured base prefix ("" for the root)
#   source_table  -> the object's file name within that folder
# One object is one table is one dataset, per the roadmap's "sync each as a
# dataset". Unioning every file under a prefix into a single dataset is a
# natural follow-up and deliberately not day one - it needs a rule for what
# happens when two files under the same prefix disagree on schema, which is a
# real design question rather than an extra loop.
#
# Cursor semantics differ from a relational source and this is the interesting
# part: there is no cursor *column*, because the unit of change is the object,
# not the row. The cursor is the object's LastModified, so "incremental" means
# "this file changed since we last read it" rather than "these rows are new".
# `cursor_column` is therefore accepted and ignored, documented here rather
# than silently - a caller that configures one is not wrong, it just does not
# have a column-level concept to hang it on.
_S3_KEY_MAX = 1024
_MAX_DISCOVER_OBJECTS = 500
# Schema inference downloads the object. Past this, discovery still lists the
# file (so it can be selected and synced) but reports no columns rather than
# pulling hundreds of MB to fill in a preview grid.
_MAX_INSPECT_BYTES = 32 * 1024 * 1024


class S3Config(BaseModel):
    bucket: str = Field(min_length=3, max_length=63)
    prefix: str = Field(default="", max_length=_S3_KEY_MAX)
    region: str = Field(default="eu-north-1", min_length=1, max_length=64)
    # Set for S3-compatible stores (MinIO, Ceph, R2). Empty means real AWS S3.
    endpoint_url: str = Field(default="", max_length=253)


class S3Connector:
    """S3 and S3-compatible object storage.

    Credentials are optional, unlike every other connector here: the common
    in-AWS case is a bucket the platform's own task role can already read, and
    forcing a long-lived access key into Secrets Manager to express that would
    be strictly worse security than using the role. When the secret is absent
    boto3 falls back to its normal credential chain.
    """

    type_name = "s3"
    display_name = "S3 / object storage"
    config_model: type[BaseModel] = S3Config
    secret_fields = ("access_key_id", "secret_access_key")

    _CONNECT_TIMEOUT_S = 8

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        try:
            cleaned = S3Config(**config).model_dump()
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"])
            raise ConnectorConfigError(f"{loc}: {first['msg']}") from exc
        prefix = cleaned["prefix"].lstrip("/")
        if ".." in prefix:
            raise ConnectorConfigError("prefix: must not contain '..'")
        # Normalised to a trailing slash so key joins are unambiguous later.
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        cleaned["prefix"] = prefix
        return cleaned

    def _client(self, config: dict[str, Any], secret: dict[str, str]):
        import urllib.parse

        import boto3
        from botocore.config import Config as BotoConfig

        cfg = S3Config(**config)
        kwargs: dict[str, Any] = {
            "region_name": cfg.region,
            "config": BotoConfig(
                connect_timeout=self._CONNECT_TIMEOUT_S,
                read_timeout=60,
                retries={"max_attempts": 3},
            ),
        }
        if cfg.endpoint_url:
            # **Only a custom endpoint is checkable here** (§263). AWS's own S3
            # host is derived by boto3 from the bucket and region at request
            # time and never passes through this function, and p.184's
            # troubleshooting page is a list of the destinations an S3 sync
            # reaches that nobody expected — STS among them. So an allowlist
            # cannot honestly claim to scope an AWS S3 source, and pretending
            # otherwise would be the worst kind of security control: one that
            # reads as covering something it does not.
            #
            # A custom endpoint *is* a destination somebody typed, so it is
            # checked. `data-connection.md`'s row says the rest out loud.
            parsed = urllib.parse.urlparse(cfg.endpoint_url)
            egress.check_current(
                parsed.hostname or "", egress.port_for(parsed.scheme, parsed.port)
            )
            kwargs["endpoint_url"] = cfg.endpoint_url
        if secret.get("access_key_id") and secret.get("secret_access_key"):
            kwargs["aws_access_key_id"] = secret["access_key_id"]
            kwargs["aws_secret_access_key"] = secret["secret_access_key"]
        return boto3.client("s3", **kwargs)

    @staticmethod
    def _translate(exc: Exception, what: str = "") -> Exception:
        """botocore reports everything as ClientError with a code in the
        response body, so the code is what the mapping keys on. Messages are
        user-safe: they name the bucket/key and the condition, never the
        credentials."""
        from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

        if isinstance(exc, NoCredentialsError):
            return ConnectorOperationError(
                "no AWS credentials available - add an access key to the "
                "connection, or grant the platform's role access to the bucket"
            )
        if isinstance(exc, EndpointConnectionError):
            return ConnectorOperationError("could not reach the object storage endpoint")
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchBucket", "404", "NoSuchKey"):
                return SourceReadError(f"{what or 'the object'} does not exist")
            if code in ("AccessDenied", "403", "AllAccessDisabled"):
                return SourceReadError(f"access denied reading {what or 'the bucket'}")
            if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch"):
                return ConnectorOperationError("the credentials were rejected by the endpoint")
            return ConnectorOperationError(f"object storage error: {code or 'unknown'}")
        return ConnectorOperationError(str(exc).strip().splitlines()[0] or "connection failed")

    def test(self, config: dict[str, Any], secret: dict[str, str]) -> None:
        cfg = S3Config(**config)
        client = self._client(config, secret)
        try:
            # list rather than head_bucket: listing under the prefix is the
            # permission the connector actually needs, and a role may be
            # scoped to a prefix without being allowed to see the bucket.
            client.list_objects_v2(Bucket=cfg.bucket, Prefix=cfg.prefix, MaxKeys=1)
        except Exception as exc:
            raise self._translate(exc, f"bucket {cfg.bucket}") from exc

    def _list_objects(self, config: dict[str, Any], secret: dict[str, str], limit: int):
        cfg = S3Config(**config)
        client = self._client(config, secret)
        out: list[dict[str, Any]] = []
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=cfg.bucket, Prefix=cfg.prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/"):
                        continue  # a "directory" marker, not a file
                    if os.path.splitext(key)[1].lower() not in SUPPORTED_FILE_EXTENSIONS:
                        continue
                    out.append(obj)
                    if len(out) >= limit:
                        return out
        except Exception as exc:
            raise self._translate(exc, f"bucket {cfg.bucket}") from exc
        return out

    @staticmethod
    def _split_key(prefix: str, key: str) -> tuple[str, str]:
        """(schema, table) for a key: the folder under the base prefix, and
        the file name."""
        relative = key[len(prefix):] if prefix and key.startswith(prefix) else key
        folder, _, name = relative.rpartition("/")
        return folder, name

    def _resolve_key(self, prefix: str, source_schema: str, source_table: str) -> str:
        """Rebuild the full object key from the (schema, table) coordinates,
        refusing anything that tries to climb out of the configured prefix -
        the connection's prefix is a real trust boundary, not a default."""
        folder = (source_schema or "").strip("/")
        name = (source_table or "").strip("/")
        if not name:
            raise SourceReadError("no object name given")
        if ".." in folder or ".." in name or "/" in name:
            raise SourceReadError(f"invalid object name {source_table!r}")
        key = f"{prefix}{folder + '/' if folder else ''}{name}"
        if len(key) > _S3_KEY_MAX or not key.startswith(prefix):
            raise SourceReadError(f"invalid object name {source_table!r}")
        return key

    def discover(self, config: dict[str, Any], secret: dict[str, str]) -> list[TableInfo]:
        import tempfile

        cfg = S3Config(**config)
        client = self._client(config, secret)
        tables: list[TableInfo] = []
        for obj in self._list_objects(config, secret, _MAX_DISCOVER_OBJECTS):
            key = obj["Key"]
            folder, name = self._split_key(cfg.prefix, key)
            columns: list[ColumnInfo] = []
            if int(obj.get("Size", 0)) <= _MAX_INSPECT_BYTES:
                with tempfile.TemporaryDirectory() as tmp:
                    local = os.path.join(tmp, name)
                    try:
                        client.download_file(cfg.bucket, key, local)
                        columns = _describe_file(local, os.path.splitext(name)[1].lower())
                    except Exception:
                        # One unreadable or malformed object must not sink the
                        # whole listing - it is still shown, just without a
                        # column preview.
                        columns = []
            tables.append(TableInfo(schema=folder, name=name, kind="file", columns=columns))
        return tables

    def preview(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
    ) -> Preview:
        import tempfile

        from . import dataset_engine as _engine

        cfg = S3Config(**config)
        client = self._client(config, secret)
        key = self._resolve_key(cfg.prefix, source_schema, source_table)
        extension = os.path.splitext(source_table)[1].lower()
        if extension not in SUPPORTED_FILE_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_FILE_EXTENSIONS))
            raise SourceReadError(
                f"unsupported file type {extension or source_table!r} (supported: {supported})"
            )

        try:
            head = client.head_object(Bucket=cfg.bucket, Key=key)
        except Exception as exc:
            raise self._translate(exc, f"{cfg.bucket}/{key}") from exc

        # **The object is downloaded whole, so it is refused rather than
        # sampled past the cap.** DuckDB's readers want a file, not a prefix of
        # one, and a truncated CSV would parse into rows that are not in the
        # source. `discover` makes the same call with the same constant and
        # degrades to no columns; here there is nothing to degrade to, so the
        # limit is said out loud instead.
        size = int(head.get("ContentLength", 0))
        if size > _MAX_INSPECT_BYTES:
            raise SourceReadError(
                f"{source_table} is too large to preview "
                f"({size // (1024 * 1024)}MB, limit {_MAX_INSPECT_BYTES // (1024 * 1024)}MB) - "
                "sync it and preview the dataset instead"
            )

        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, f"preview{extension}")
            try:
                client.download_file(cfg.bucket, key, local)
            except Exception as exc:
                raise self._translate(exc, f"{cfg.bucket}/{key}") from exc
            try:
                # One past the cap, so `Preview.more` is the file's answer
                # rather than an inference from a full page.
                columns, rows = _engine.sample_file(local, extension, PREVIEW_ROWS + 1)
            except _engine.DatasetEngineError as exc:
                raise SourceReadError(f"could not read {source_table}: {exc}") from exc
        return build_preview([c.name for c in columns], rows)

    def snapshot(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        dest_dir: str,
        max_bytes: int,
        cursor_column: str | None = None,
        cursor_value: str | None = None,
    ) -> Extract:
        cfg = S3Config(**config)
        client = self._client(config, secret)
        key = self._resolve_key(cfg.prefix, source_schema, source_table)
        extension = os.path.splitext(source_table)[1].lower()
        if extension not in SUPPORTED_FILE_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_FILE_EXTENSIONS))
            raise SourceReadError(
                f"unsupported file type {extension or source_table!r} (supported: {supported})"
            )

        try:
            head = client.head_object(Bucket=cfg.bucket, Key=key)
        except Exception as exc:
            raise self._translate(exc, f"{cfg.bucket}/{key}") from exc

        size = int(head.get("ContentLength", 0))
        if size > max_bytes:
            raise size_cap_error(max_bytes)

        # Incremental: the object is the unit of change, so "nothing new" means
        # the file has not been rewritten since the last successful sync.
        last_modified = _s3_timestamp(head.get("LastModified"))
        if cursor_value is not None and last_modified is not None and last_modified <= cursor_value:
            return Extract(path="", extension=extension, empty=True)

        local = os.path.join(dest_dir, f"snapshot{extension}")
        try:
            client.download_file(cfg.bucket, key, local)
        except Exception as exc:
            raise self._translate(exc, f"{cfg.bucket}/{key}") from exc
        return Extract(path=local, extension=extension)

    def max_cursor_value(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        cursor_column: str,
    ) -> str | None:
        """The object's LastModified. `cursor_column` is accepted and ignored -
        see this section's header: an object store's unit of change is the
        object, not a column within it."""
        cfg = S3Config(**config)
        client = self._client(config, secret)
        key = self._resolve_key(cfg.prefix, source_schema, source_table)
        try:
            head = client.head_object(Bucket=cfg.bucket, Key=key)
        except Exception as exc:
            raise self._translate(exc, f"{cfg.bucket}/{key}") from exc
        return _s3_timestamp(head.get("LastModified"))

    # ---- export (decision 0014; `data-connection` p.193, p.203) --------------
    def export_file(
        self, config: dict[str, Any], secret: dict[str, str],
        *, prefix: str, filename: str, local_path: str,
    ) -> str:
        """Put one file under the export's path. Returns the key written.

        p.193: "File exports write files from the selected Foundry dataset to
        the configured destination… By default, if a file already exists in the
        destination, export jobs will overwrite that file with the exported
        data."

        **Under the connection's own prefix, not instead of it.** The
        connection's prefix is a trust boundary — `_resolve_key` exists for
        that reason on the read side — and an export that could write above it
        would let somebody who may configure an export reach objects the
        connection was scoped away from. p.193's own advice points the same
        way: "we recommend creating a dedicated sub-folder in which to land
        exported data from Foundry."

        `s3:PutObject` is what this needs (p.203) and a refusal says so,
        because the alternative is a generic AccessDenied against a bucket
        somebody can read perfectly well.
        """
        cfg = S3Config(**config)
        folder = (prefix or "").strip("/")
        if ".." in folder or ".." in filename or "/" in filename:
            raise SourceReadError(f"invalid export path {prefix!r}")
        key = f"{cfg.prefix}{folder + '/' if folder else ''}{filename}"
        if len(key) > _S3_KEY_MAX or not key.startswith(cfg.prefix):
            raise SourceReadError(f"invalid export path {prefix!r}")

        client = self._client(config, secret)
        try:
            client.upload_file(local_path, cfg.bucket, key)
        except Exception as exc:
            translated = self._translate(exc, f"{cfg.bucket}/{key}")
            if "denied" in str(translated).lower():
                raise SourceReadError(
                    f"the connection's credentials cannot write {cfg.bucket}/{key} - "
                    "a file export needs s3:PutObject (p.203)"
                ) from exc
            raise translated from exc
        return key


def _s3_timestamp(value: Any) -> str | None:
    """LastModified as a sortable, storable string. sync_last_cursor_value is
    a text column and the comparison it feeds is a string comparison, so the
    format has to be fixed-width and lexicographically ordered - isoformat in
    UTC is both."""
    if value is None:
        return None
    if hasattr(value, "astimezone"):
        import datetime as _dt

        return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z")
    return str(value)


def _describe_file(path: str, extension: str) -> list[ColumnInfo]:
    """Column names/types for a downloaded object, via the same DuckDB readers
    the datasets layer uses for uploads - so a file discovered here reports the
    schema it will actually land with."""
    from . import dataset_engine as _engine

    try:
        return [
            ColumnInfo(name=c.name, data_type=c.data_type, nullable=True, is_primary_key=False)
            for c in _engine.describe_file(path, extension)
        ]
    except _engine.DatasetEngineError:
        return []


# Kept in step with dataset_engine's readers: a connector must never offer a
# file the ingest path cannot actually read.
def _supported_file_extensions() -> tuple[str, ...]:
    from . import dataset_engine as _engine

    return _engine.SUPPORTED_EXTENSIONS


SUPPORTED_FILE_EXTENSIONS: tuple[str, ...] = _supported_file_extensions()


# ---- Generic REST / HTTP JSON ------------------------------------------------
# The roadmap calls this "the highest-variance connector to build well" and says
# to scope the first cut narrowly rather than trying to cover every API's
# quirks. That is exactly what this is, and the boundaries are worth stating
# outright so nobody mistakes it for a general HTTP client:
#
#   * GET only. A sync reads; a REST connector that POSTs is a write-back
#     feature (Connections item 8), which wants its own design.
#   * The response must contain a JSON *array of objects* somewhere, located by
#     a dotted `records_path` ("" when the body is itself the array). Anything
#     else - XML, CSV-over-HTTP, an object keyed by id - is out of scope, and
#     says so rather than guessing.
#   * Two pagination styles, because they cover most of what real APIs do:
#     an incrementing page number, and an opaque cursor echoed from the
#     response. Link headers, RFC 5988, and offset/limit are not handled yet.
#   * No server-side incrementality. There is no universal "changed since" for
#     REST, so `max_cursor_value` returns None and every run fetches the whole
#     collection. In incremental mode the platform still merges by primary key,
#     which is useful (an append-only endpoint converges) but is not a
#     bandwidth saving, and is documented as such rather than implied.
#
# Records land as JSONL rather than CSV - the other half of why `snapshot`
# returns an extension. A REST payload routinely has nested objects, and
# flattening those through CSV would turn them into unparseable text.

_REST_TIMEOUT_S = 20
_REST_MAX_PAGES = 1000  # a guard against a mis-configured cursor looping forever


class RestConfig(BaseModel):
    base_url: str = Field(min_length=1, max_length=2048)
    # Split from base_url so the same connection can name the collection it
    # syncs while `source_table` stays a display coordinate like every other
    # connector's.
    resource_path: str = Field(default="", max_length=2048)
    auth_type: Literal["none", "api_key_header", "bearer", "oauth2_client_credentials"] = "none"
    auth_header_name: str = Field(default="X-API-Key", min_length=1, max_length=128)
    token_url: str = Field(default="", max_length=2048)
    oauth_scope: str = Field(default="", max_length=512)
    records_path: str = Field(default="", max_length=256)
    pagination: Literal["none", "page_number", "cursor"] = "none"
    page_param: str = Field(default="page", min_length=1, max_length=64)
    page_size_param: str = Field(default="", max_length=64)
    page_size: int = Field(default=100, ge=1, le=10000)
    # Where the next cursor lives in the response, and what to send it back as.
    cursor_path: str = Field(default="", max_length=256)
    cursor_param: str = Field(default="cursor", min_length=1, max_length=64)
    # Same shape of decision as MySQL's ssl_mode: plaintext has to be asked for.
    allow_insecure_http: bool = False


class RestConnector:
    type_name = "rest"
    display_name = "REST / HTTP JSON"
    config_model: type[BaseModel] = RestConfig
    secret_fields = ("api_key", "client_id", "client_secret")

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        try:
            cleaned = RestConfig(**config).model_dump()
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"])
            raise ConnectorConfigError(f"{loc}: {first['msg']}") from exc

        _check_url(cleaned["base_url"], cleaned["allow_insecure_http"], field="base_url")
        if cleaned["auth_type"] == "oauth2_client_credentials":
            if not cleaned["token_url"]:
                raise ConnectorConfigError(
                    "token_url: required for oauth2_client_credentials"
                )
            _check_url(cleaned["token_url"], cleaned["allow_insecure_http"], field="token_url")
        if cleaned["pagination"] == "cursor" and not cleaned["cursor_path"]:
            raise ConnectorConfigError(
                "cursor_path: required when pagination is 'cursor' - without it "
                "there is no way to find the next page in the response"
            )
        return cleaned

    # -- request plumbing ------------------------------------------------------
    def _auth_headers(self, config: dict[str, Any], secret: dict[str, str]) -> dict[str, str]:
        auth = config.get("auth_type", "none")
        if auth == "none":
            return {}
        if auth == "api_key_header":
            key = secret.get("api_key")
            if not key:
                raise ConnectorOperationError("no api_key stored for this connection")
            return {config.get("auth_header_name") or "X-API-Key": key}
        if auth == "bearer":
            token = secret.get("api_key")
            if not token:
                raise ConnectorOperationError("no bearer token stored for this connection")
            return {"Authorization": f"Bearer {token}"}
        return {"Authorization": f"Bearer {self._oauth_token(config, secret)}"}

    def _oauth_token(self, config: dict[str, Any], secret: dict[str, str]) -> str:
        """client_credentials grant. Fetched per operation rather than cached:
        a sync is a handful of requests over a few seconds, and a cache would
        need invalidation, a clock, and somewhere to live - none of which earn
        their keep before someone has an API that actually rate-limits it."""
        import json
        import urllib.error
        import urllib.parse
        import urllib.request

        client_id = secret.get("client_id")
        client_secret = secret.get("client_secret")
        if not client_id or not client_secret:
            raise ConnectorOperationError(
                "oauth2_client_credentials needs both client_id and client_secret"
            )
        form = {"grant_type": "client_credentials", "client_id": client_id,
                "client_secret": client_secret}
        if config.get("oauth_scope"):
            form["scope"] = config["oauth_scope"]
        # **The token endpoint is a second destination** (§263, decision 0013's
        # enforcement table). p.12's own example is a source that needs both —
        # "retrieve credentials from an internet-hosted system, and use said
        # credentials to authenticate with an on-premise system" — so an
        # allowlist that covered only `base_url` would cover the smaller half.
        #
        # Checked here rather than only in `validate_config`, which does look at
        # `token_url` when the connection is saved. §259 recorded why that is
        # not the same thing: `_check_url` resolves the hostname *when it runs*,
        # and a name that answered publicly at configure time can answer
        # differently later. This path had no send-time check at all until now.
        _check_url(config["token_url"], config.get("allow_insecure_http", False),
                   field="token_url")
        request = urllib.request.Request(
            config["token_url"],
            data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_REST_TIMEOUT_S) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            # Deliberately not echoing the body: a token endpoint's error can
            # quote back what was sent, which is the client_secret.
            raise ConnectorOperationError(
                f"the token endpoint rejected the credentials (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectorOperationError(f"could not reach the token endpoint: {_reason(exc)}") from exc
        except ValueError as exc:
            raise ConnectorOperationError("the token endpoint did not return JSON") from exc

        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise ConnectorOperationError("the token endpoint returned no access_token")
        return str(token)

    def _fetch_page(
        self, config: dict[str, Any], secret: dict[str, str], params: dict[str, Any]
    ) -> Any:
        import json
        import urllib.error
        import urllib.parse
        import urllib.request

        url = _join_url(config["base_url"], config.get("resource_path") or "")
        _check_url(url, config.get("allow_insecure_http", False))
        if params:
            separator = "&" if urllib.parse.urlparse(url).query else "?"
            url = f"{url}{separator}{urllib.parse.urlencode(params)}"

        headers = {"Accept": "application/json", **self._auth_headers(config, secret)}
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=_REST_TIMEOUT_S) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise SourceReadError(
                    f"the API rejected the request (HTTP {exc.code}) - check the credentials"
                ) from exc
            if exc.code == 404:
                raise SourceReadError(f"the API returned 404 for {config.get('resource_path') or '/'}") from exc
            raise ConnectorOperationError(f"the API returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectorOperationError(f"could not reach the API: {_reason(exc)}") from exc

        try:
            return json.loads(body.decode("utf-8", "replace"))
        except ValueError as exc:
            raise SourceReadError("the API did not return JSON") from exc

    def _records(self, payload: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
        located = _json_path(payload, config.get("records_path") or "")
        if not isinstance(located, list):
            where = config.get("records_path") or "the response body"
            raise SourceReadError(
                f"expected a JSON array at {where}, got {type(located).__name__} - "
                "set records_path to wherever the list of records lives"
            )
        rows = [row for row in located if isinstance(row, dict)]
        if located and not rows:
            raise SourceReadError(
                "the records array does not contain objects - this connector "
                "reads a list of records, not a list of scalars"
            )
        return rows

    def _pages(self, config: dict[str, Any], secret: dict[str, str]):
        """Yields one page of records at a time, following the configured
        pagination style until it runs out or hits the page guard."""
        style = config.get("pagination", "none")
        params: dict[str, Any] = {}
        if config.get("page_size_param"):
            params[config["page_size_param"]] = config.get("page_size", 100)

        page_number = 1
        cursor: Any = None
        for _ in range(_REST_MAX_PAGES):
            page_params = dict(params)
            if style == "page_number":
                page_params[config.get("page_param") or "page"] = page_number
            elif style == "cursor" and cursor is not None:
                page_params[config.get("cursor_param") or "cursor"] = cursor

            payload = self._fetch_page(config, secret, page_params)
            records = self._records(payload, config)
            yield records

            if style == "none":
                return
            if style == "page_number":
                # An empty page is the end. Pages that keep returning data
                # forever are what _REST_MAX_PAGES is for.
                if not records:
                    return
                page_number += 1
            else:
                cursor = _json_path(payload, config["cursor_path"])
                if cursor in (None, "", []):
                    return

    # -- interface -------------------------------------------------------------
    def test(self, config: dict[str, Any], secret: dict[str, str]) -> None:
        payload = self._fetch_page(config, secret, {})
        self._records(payload, config)  # proves records_path is right too

    def discover(self, config: dict[str, Any], secret: dict[str, str]) -> list[TableInfo]:
        """A REST API has no catalog to enumerate, so discovery reports the one
        collection this connection is configured for, with columns inferred
        from the first page's records."""
        payload = self._fetch_page(config, secret, {})
        records = self._records(payload, config)
        columns: dict[str, str] = {}
        nullable: set[str] = set()
        for row in records[:200]:
            for key, value in row.items():
                inferred = _json_type(value)
                if value is None:
                    nullable.add(key)
                if key not in columns or columns[key] == "NULL":
                    columns[key] = inferred
                elif inferred != columns[key] and inferred != "NULL":
                    columns[key] = "VARCHAR"  # mixed types degrade to text
        # Any key missing from some record is effectively nullable.
        for row in records[:200]:
            for key in columns:
                if key not in row:
                    nullable.add(key)
        return [
            TableInfo(
                schema="",
                name=_resource_name(config),
                kind="endpoint",
                columns=[
                    ColumnInfo(
                        name=key,
                        data_type=data_type,
                        nullable=key in nullable,
                        is_primary_key=False,
                    )
                    for key, data_type in columns.items()
                ],
            )
        ]

    def preview(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
    ) -> Preview:
        """The first page's records, as a table.

        `source_schema` and `source_table` are ignored, because a REST source
        has exactly one collection and `discover` reports it as the only entry
        - the same reason `max_cursor_value` ignores its cursor column. They
        stay in the signature because the interface is one interface; a
        connector that quietly took different arguments would be a second one.

        **This is the row decision 0015 §6 says must be tested separately.** A
        REST preview does not reach `_client` or `_conninfo`, so the egress
        argument that covers the other three - "they share a chokepoint" - is a
        different claim here, made about `_fetch_page` and `_check_url`.
        """
        import json

        payload = self._fetch_page(config, secret, {})
        records = self._records(payload, config)[: PREVIEW_ROWS + 1]

        # A union rather than the first record's keys: a collection whose
        # second object carries a field the first one omits is exactly the
        # shape a preview is being read to notice, and a header taken from row
        # one would hide it.
        columns: list[str] = []
        for record in records:
            for key in record:
                if key not in columns:
                    columns.append(key)

        rows: list[list[Any]] = []
        for record in records:
            row: list[Any] = []
            for key in columns:
                value = record.get(key)
                # A nested object reaches the screen as the JSON a `.jsonl`
                # snapshot would write, not as Python's `{'a': 1}` repr - the
                # preview's job is to show what would land.
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, default=str)
                row.append(value)
            rows.append(row)
        return build_preview(columns, rows)

    def snapshot(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        dest_dir: str,
        max_bytes: int,
        cursor_column: str | None = None,
        cursor_value: str | None = None,
    ) -> Extract:
        import json

        dest = os.path.join(dest_dir, "snapshot.jsonl")
        written = 0
        rows = 0
        with open(dest, "w", encoding="utf-8") as handle:
            for page in self._pages(config, secret):
                for record in page:
                    line = json.dumps(record, default=str) + "\n"
                    written += len(line.encode("utf-8"))
                    if written > max_bytes:
                        raise size_cap_error(max_bytes)
                    handle.write(line)
                    rows += 1
        if rows == 0:
            # DuckDB cannot infer a schema from an empty JSONL file, and an
            # empty collection is a legitimate steady state rather than an
            # error - report it the same way an object store reports "nothing
            # new" so callers skip the write instead of failing.
            return Extract(path=dest, extension=".jsonl", empty=True)
        return Extract(path=dest, extension=".jsonl")

    def max_cursor_value(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        cursor_column: str,
    ) -> str | None:
        """Always None: see this section's header. REST has no universal
        "changed since", so there is no high-water mark to store, and every run
        fetches the whole collection."""
        return None


def _reason(exc: Exception) -> str:
    text = str(getattr(exc, "reason", exc)).strip()
    return text.splitlines()[0] if text else "connection failed"


def _resource_name(config: dict[str, Any]) -> str:
    """A display name for the one collection a REST connection reads - the last
    non-empty path segment, falling back to the host."""
    import urllib.parse

    path = (config.get("resource_path") or urllib.parse.urlparse(config["base_url"]).path or "").strip("/")
    if path:
        return path.split("/")[-1] or path
    return urllib.parse.urlparse(config["base_url"]).netloc or "records"


def _join_url(base: str, path: str) -> str:
    if not path:
        return base
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _check_url(url: str, allow_insecure_http: bool, *, field: str = "base_url") -> None:
    """Scheme and destination guard.

    A connector that fetches an operator-supplied URL runs inside the
    customer's own VPC, so an editor who cannot otherwise reach AWS could point
    it at the instance metadata service and read the task role's credentials
    out of the response. Link-local is refused for that reason. Other private
    ranges are deliberately *not* blocked - an internal API on a private
    subnet is a legitimate thing to sync, and blocking it would break the
    ordinary case to defend against nothing in particular.
    """
    import ipaddress
    import socket
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ConnectorConfigError(f"{field}: must be an http(s) URL")
    # **The source's own allowlist, before the platform's own guard** (§263).
    # Two controls, and this is the one that says whether the *destination* was
    # asked for; the link-local refusal below is the platform's, and a source's
    # policies cannot override it. Order matters only for which message a call
    # to a link-local address inside its own allowlist gets, and the specific
    # one is more use than "not allowed".
    #
    # `port_for` fills in the port a scheme implies, because
    # `https://api.example.com/x` and `https://api.example.com:443/x` are the
    # same destination and a port-scoped policy has to allow both.
    egress.check_current(
        parsed.hostname or "", egress.port_for(parsed.scheme, parsed.port)
    )
    if parsed.scheme == "http" and not allow_insecure_http:
        raise ConnectorConfigError(
            f"{field}: refusing plaintext http - use https, or set "
            "allow_insecure_http to accept an unencrypted connection"
        )
    host = parsed.hostname
    if not host:
        raise ConnectorConfigError(f"{field}: no host in URL")

    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return  # unresolvable is the request's problem to report, not config's
    for address in resolved:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_link_local:
            raise ConnectorConfigError(
                f"{field}: refusing to reach the link-local address range "
                "(this is where cloud instance metadata lives)"
            )


def _json_path(payload: Any, path: str) -> Any:
    """Dotted lookup into a decoded JSON body. Empty path means the body
    itself. Deliberately not a JSONPath implementation - a dotted key walk is
    what almost every paginated API actually needs, and a real expression
    language here would be a dependency and a support surface."""
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _json_type(value: Any) -> str:
    """DuckDB's name for what this JSON value will land as, so discovery
    reports the same vocabulary the other connectors do."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "BIGINT"
    if isinstance(value, float):
        return "DOUBLE"
    if isinstance(value, (dict, list)):
        return "JSON"
    return "VARCHAR"


# ---- registry ----------------------------------------------------------------
_REGISTRY: dict[str, SourceConnector] = {
    PostgresConnector.type_name: PostgresConnector(),
    MySQLConnector.type_name: MySQLConnector(),
    S3Connector.type_name: S3Connector(),
    RestConnector.type_name: RestConnector(),
}


def register(connector: SourceConnector) -> None:
    """Add a source type. Called at import time by this module for the
    built-ins; exposed so a test can register a fake without reaching into
    the private dict."""
    _REGISTRY[connector.type_name] = connector


def get_connector(source_type: str) -> SourceConnector:
    connector = _REGISTRY.get(source_type)
    if connector is None:
        supported = ", ".join(sorted(_REGISTRY))
        raise ConnectorConfigError(
            f"unsupported source type {source_type!r} (supported: {supported})"
        )
    return connector


def list_source_types() -> list[dict[str, Any]]:
    """For the create wizard's type picker: name, label, config field shape,
    and which fields are secrets (rendered as password inputs, sent once,
    never echoed back)."""
    out: list[dict[str, Any]] = []
    for connector in sorted(_REGISTRY.values(), key=lambda c: c.display_name):
        schema = connector.config_model.model_json_schema()
        out.append(
            {
                "type": connector.type_name,
                "display_name": connector.display_name,
                "config_schema": schema,
                "secret_fields": list(connector.secret_fields),
            }
        )
    return out
