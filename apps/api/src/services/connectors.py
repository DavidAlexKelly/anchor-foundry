"""Connector registry (spec §"Connections" supported source types).

Every source type implements one interface and the registry maps
``connection.source_type`` to an implementation. Nothing above this module
knows which driver is in play:

    validate_config(config)   -> the cleaned, non-secret config to store
    test(config, secret)      -> None; raises ConnectorOperationError
    discover(config, secret)  -> [TableInfo]
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
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError


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
    kind: str  # "table" | "view" | "file"
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

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        try:
            return MySQLConfig(**config).model_dump()
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"])
            raise ConnectorConfigError(f"{loc}: {first['msg']}") from exc

    def _connect_kwargs(self, config: dict[str, Any], secret: dict[str, str]) -> dict[str, Any]:
        cfg = MySQLConfig(**config)
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


# ---- registry ----------------------------------------------------------------
_REGISTRY: dict[str, SourceConnector] = {
    PostgresConnector.type_name: PostgresConnector(),
    MySQLConnector.type_name: MySQLConnector(),
    S3Connector.type_name: S3Connector(),
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
