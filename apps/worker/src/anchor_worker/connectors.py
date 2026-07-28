"""Source connectors - the worker's copy of the extract half of apps/api's
services/connectors.py, trimmed to what scheduled syncs need: pull rows to
CSV (optionally cursor-filtered) and read a source's current high-water mark.

Duplicated for the same reason as storage.py/dataset_engine.py - api and
worker are independently deployable images with no shared Python package in
this build. Config validation, `test`, and `discover` are deliberately absent:
those are interactive operations the API owns, and a scheduled sync only ever
runs against a config the API already validated at save time.

Keep in step with the API's registry. A source type present there but missing
here syncs interactively and then silently fails on its schedule, per
connection - exactly the class of gap this module exists to make impossible
to introduce by copy-paste.
"""

import csv
import re


class ConnectorError(RuntimeError):
    """User-safe extract failure: source unreachable, table missing/unreadable,
    or past the byte cap. Recorded as the sync run's error; jobs must include
    this in their per-candidate except tuple."""


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")


def check_identifier(name: str) -> str:
    if not _IDENT_RE.match(name or ""):
        raise ConnectorError(f"invalid identifier {name!r}")
    return name


def size_cap_error(max_bytes: int) -> ConnectorError:
    return ConnectorError(f"table exceeds the {max_bytes // (1024 * 1024)} MB scheduled-sync limit")


class _CappedCsvWriter:
    """Streams rows to CSV, aborting past a byte cap - for drivers with no
    server-side COPY-to-CSV. Mirrors the API-side writer of the same name."""

    def __init__(self, dest_csv: str, max_bytes: int) -> None:
        self._dest = dest_csv
        self._max_bytes = max_bytes

    def __enter__(self):
        self._handle = open(self._dest, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._handle)
        return self

    def __exit__(self, *exc) -> None:
        self._handle.close()

    def writerow(self, row) -> None:
        self._writer.writerow(row)
        if self._handle.tell() > self._max_bytes:
            raise size_cap_error(self._max_bytes)


# ---- PostgreSQL --------------------------------------------------------------
class PostgresConnector:
    type_name = "postgres"

    def conninfo(self, config: dict, secret: dict) -> dict:
        return {
            "host": config["host"],
            "port": config["port"],
            "dbname": config["database"],
            "user": config["user"],
            "password": secret.get("password", ""),
            "sslmode": config.get("sslmode", "prefer"),
            "connect_timeout": 8,
        }

    def snapshot_to_csv(
        self,
        config: dict,
        secret: dict,
        *,
        source_schema: str,
        source_table: str,
        dest_csv: str,
        max_bytes: int,
        cursor_column=None,
        cursor_value=None,
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
            with psycopg.connect(**self.conninfo(config, secret)) as conn:
                with conn.cursor() as cur, open(dest_csv, "wb") as out:
                    with cur.copy(query) as copy:
                        for chunk in copy:
                            written += len(chunk)
                            if written > max_bytes:
                                raise size_cap_error(max_bytes)
                            out.write(bytes(chunk))
        except psycopg.errors.UndefinedTable as exc:
            raise ConnectorError(f"table {source_schema}.{source_table} does not exist") from exc
        except psycopg.errors.InsufficientPrivilege as exc:
            raise ConnectorError(
                f"the connection's user cannot read {source_schema}.{source_table}"
            ) from exc
        except psycopg.OperationalError as exc:
            reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
            raise ConnectorError(reason) from exc

    def max_cursor_value(
        self, config: dict, secret: dict, *, source_schema: str, source_table: str, cursor_column: str
    ):
        import psycopg
        from psycopg import sql

        query = sql.SQL("SELECT max({}) FROM {}.{}").format(
            sql.Identifier(check_identifier(cursor_column)),
            sql.Identifier(check_identifier(source_schema)),
            sql.Identifier(check_identifier(source_table)),
        )
        try:
            with psycopg.connect(**self.conninfo(config, secret)) as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    row = cur.fetchone()
        except psycopg.errors.UndefinedTable as exc:
            raise ConnectorError(f"table {source_schema}.{source_table} does not exist") from exc
        except psycopg.OperationalError as exc:
            reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
            raise ConnectorError(reason) from exc
        return None if row is None or row[0] is None else str(row[0])


# ---- MySQL / MariaDB ---------------------------------------------------------
# `source_schema` carries the database name - MySQL has no schema-within-
# database concept. See the API-side connector for the full reasoning.
_MYSQL_IDENT_RE = re.compile(r"^[A-Za-z0-9_$]{1,64}$")


def _quote_mysql(name: str) -> str:
    if not _MYSQL_IDENT_RE.match(name or ""):
        raise ConnectorError(f"invalid identifier {name!r}")
    return "`" + name.replace("`", "``") + "`"


def _csv_value(value):
    """bytes would otherwise reach the CSV as a Python repr; hex is lossless
    and unambiguous. Mirrors the API-side helper of the same name."""
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


class MySQLConnector:
    type_name = "mysql"

    def _connect_kwargs(self, config: dict, secret: dict) -> dict:
        kwargs = {
            "host": config["host"],
            "port": config["port"],
            "database": config["database"],
            "user": config["user"],
            "password": secret.get("password", ""),
            "connect_timeout": 8,
            "charset": "utf8mb4",
        }
        if config.get("ssl_mode", "required") == "required":
            import ssl as ssl_module

            kwargs["ssl"] = {"check_hostname": False, "verify_mode": ssl_module.CERT_NONE}
        return kwargs

    def _connect(self, config: dict, secret: dict):
        """Connect, and when ssl_mode is `required`, prove the session was
        actually encrypted - PyMySQL upgrades to TLS only if the server
        advertises it and otherwise completes the handshake in plaintext
        without complaint. Mirrors the API-side connector; see its docstring."""
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
            raise ConnectorError(
                "the server accepted the connection without TLS, but this "
                "connection requires it - enable TLS on the source or set "
                "ssl_mode to 'disabled'"
            )
        return conn

    @staticmethod
    def _translate(exc, source_schema: str = "", source_table: str = "") -> ConnectorError:
        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
        qualified = f"{source_schema}.{source_table}" if source_table else "the source table"
        if code == 1146:
            return ConnectorError(f"table {qualified} does not exist")
        if code in (1142, 1143, 1044, 1045):
            return ConnectorError(f"the connection's user cannot read {qualified}")
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
        return ConnectorError(reason)

    def snapshot_to_csv(
        self,
        config: dict,
        secret: dict,
        *,
        source_schema: str,
        source_table: str,
        dest_csv: str,
        max_bytes: int,
        cursor_column=None,
        cursor_value=None,
    ) -> None:
        import pymysql
        import pymysql.cursors

        qualified = f"{_quote_mysql(source_schema)}.{_quote_mysql(source_table)}"
        params = ()
        if cursor_column and cursor_value is not None:
            query = f"SELECT * FROM {qualified} WHERE {_quote_mysql(cursor_column)} > %s"
            params = (cursor_value,)
        else:
            query = f"SELECT * FROM {qualified}"

        try:
            with self._connect(config, secret) as conn:
                # SSCursor: stream from the server so the byte cap can stop a
                # runaway table instead of buffering it all first.
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
        self, config: dict, secret: dict, *, source_schema: str, source_table: str, cursor_column: str
    ):
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


# ---- registry ----------------------------------------------------------------
_REGISTRY = {
    PostgresConnector.type_name: PostgresConnector(),
    MySQLConnector.type_name: MySQLConnector(),
}


def get_connector(source_type: str):
    connector = _REGISTRY.get(source_type)
    if connector is None:
        supported = ", ".join(sorted(_REGISTRY))
        raise ConnectorError(
            f"source type {source_type!r} cannot be synced on a schedule "
            f"(supported: {supported})"
        )
    return connector
