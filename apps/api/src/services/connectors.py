"""Connector registry (spec §"Connections" supported source types).

Every source type implements one interface and the registry maps
``connection.source_type`` to an implementation. Nothing above this module
knows which driver is in play:

    validate_config(config)   -> the cleaned, non-secret config to store
    test(config, secret)      -> None; raises ConnectorOperationError
    discover(config, secret)  -> [TableInfo]
    snapshot_to_csv(...)      -> extract rows to a CSV file, byte-capped
    max_cursor_value(...)     -> the source's current high-water mark

The last two are the roadmap's ``snapshot()``/``incremental(cursor)`` as a
single method rather than two: an incremental pull is the same extract with a
``WHERE cursor > :last`` predicate, and every relational source implements it
that way. Splitting them would duplicate the byte-cap and error-translation
loop in each connector for no behavioural difference; ``cursor_column`` being
``None`` (a full snapshot) is the only fork, and it is one line of SQL.

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
    kind: str  # "table" | "view"
    columns: list[ColumnInfo] = field(default_factory=list)


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

    def snapshot_to_csv(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        dest_csv: str,
        max_bytes: int,
        cursor_column: str | None = None,
        cursor_value: str | None = None,
    ) -> None:
        """Extract the table to a CSV file (header included). With
        cursor_column/cursor_value set, only rows strictly past the cursor -
        the incremental pull. Raises SourceReadError past max_bytes."""

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

    def snapshot_to_csv(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        dest_csv: str,
        max_bytes: int,
        cursor_column: str | None = None,
        cursor_value: str | None = None,
    ) -> None:
        import psycopg
        from psycopg import sql

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

    def snapshot_to_csv(
        self,
        config: dict[str, Any],
        secret: dict[str, str],
        *,
        source_schema: str,
        source_table: str,
        dest_csv: str,
        max_bytes: int,
        cursor_column: str | None = None,
        cursor_value: str | None = None,
    ) -> None:
        import pymysql
        import pymysql.cursors

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


# ---- registry ----------------------------------------------------------------
_REGISTRY: dict[str, SourceConnector] = {
    PostgresConnector.type_name: PostgresConnector(),
    MySQLConnector.type_name: MySQLConnector(),
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
