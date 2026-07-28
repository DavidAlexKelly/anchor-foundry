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
import os
import re
from dataclasses import dataclass


class ConnectorError(RuntimeError):
    """User-safe extract failure: source unreachable, table missing/unreadable,
    or past the byte cap. Recorded as the sync run's error; jobs must include
    this in their per-candidate except tuple."""


@dataclass(frozen=True)
class Extract:
    """What a snapshot produced: a file plus the extension dataset_engine
    should read it as, and whether the source had nothing new past the cursor.
    Mirrors the API-side Extract; see its docstring for why `empty` is an
    explicit flag rather than an inferred row count."""

    path: str
    extension: str
    empty: bool = False


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

    def snapshot(
        self,
        config: dict,
        secret: dict,
        *,
        source_schema: str,
        source_table: str,
        dest_dir: str,
        max_bytes: int,
        cursor_column=None,
        cursor_value=None,
    ) -> "Extract":
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
        return Extract(path=dest_csv, extension=".csv")

    def max_cursor_value(
        self, config: dict, secret: dict, *, source_schema: str, source_table: str, cursor_column: str
    ):
        import psycopg
        from psycopg import sql

        # None rather than an error when no cursor column is configured - see
        # the API-side connector for why callers rely on that.
        if not cursor_column:
            return None

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

    def snapshot(
        self,
        config: dict,
        secret: dict,
        *,
        source_schema: str,
        source_table: str,
        dest_dir: str,
        max_bytes: int,
        cursor_column=None,
        cursor_value=None,
    ) -> "Extract":
        import pymysql
        import pymysql.cursors

        dest_csv = os.path.join(dest_dir, "snapshot.csv")
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
        return Extract(path=dest_csv, extension=".csv")

    def max_cursor_value(
        self, config: dict, secret: dict, *, source_schema: str, source_table: str, cursor_column: str
    ):
        import pymysql

        if not cursor_column:
            return None

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


# ---- S3 / object storage -----------------------------------------------------
# source_schema is the "folder" under the connection's configured prefix,
# source_table the object's file name; the cursor is the object's LastModified
# rather than a column, since the unit of change is the object. See the
# API-side connector for the full reasoning.
_S3_KEY_MAX = 1024


class S3Connector:
    type_name = "s3"

    def _client(self, config: dict, secret: dict):
        import boto3
        from botocore.config import Config as BotoConfig

        kwargs = {
            "region_name": config.get("region") or "eu-north-1",
            "config": BotoConfig(
                connect_timeout=8, read_timeout=60, retries={"max_attempts": 3}
            ),
        }
        if config.get("endpoint_url"):
            kwargs["endpoint_url"] = config["endpoint_url"]
        if secret.get("access_key_id") and secret.get("secret_access_key"):
            kwargs["aws_access_key_id"] = secret["access_key_id"]
            kwargs["aws_secret_access_key"] = secret["secret_access_key"]
        return boto3.client("s3", **kwargs)

    @staticmethod
    def _translate(exc, what: str = "") -> ConnectorError:
        from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

        if isinstance(exc, NoCredentialsError):
            return ConnectorError("no AWS credentials available for the object storage source")
        if isinstance(exc, EndpointConnectionError):
            return ConnectorError("could not reach the object storage endpoint")
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchBucket", "404", "NoSuchKey"):
                return ConnectorError(f"{what or 'the object'} does not exist")
            if code in ("AccessDenied", "403", "AllAccessDisabled"):
                return ConnectorError(f"access denied reading {what or 'the bucket'}")
            if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch"):
                return ConnectorError("the credentials were rejected by the endpoint")
            return ConnectorError(f"object storage error: {code or 'unknown'}")
        return ConnectorError(str(exc).strip().splitlines()[0] or "connection failed")

    def _resolve_key(self, prefix: str, source_schema: str, source_table: str) -> str:
        folder = (source_schema or "").strip("/")
        name = (source_table or "").strip("/")
        if not name:
            raise ConnectorError("no object name given")
        if ".." in folder or ".." in name or "/" in name:
            raise ConnectorError(f"invalid object name {source_table!r}")
        key = f"{prefix}{folder + '/' if folder else ''}{name}"
        if len(key) > _S3_KEY_MAX or not key.startswith(prefix):
            raise ConnectorError(f"invalid object name {source_table!r}")
        return key

    def snapshot(
        self,
        config: dict,
        secret: dict,
        *,
        source_schema: str,
        source_table: str,
        dest_dir: str,
        max_bytes: int,
        cursor_column=None,
        cursor_value=None,
    ) -> "Extract":
        bucket = config["bucket"]
        prefix = config.get("prefix") or ""
        client = self._client(config, secret)
        key = self._resolve_key(prefix, source_schema, source_table)
        extension = os.path.splitext(source_table)[1].lower()

        try:
            head = client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:
            raise self._translate(exc, f"{bucket}/{key}") from exc

        if int(head.get("ContentLength", 0)) > max_bytes:
            raise size_cap_error(max_bytes)

        last_modified = _s3_timestamp(head.get("LastModified"))
        if cursor_value is not None and last_modified is not None and last_modified <= cursor_value:
            return Extract(path="", extension=extension, empty=True)

        local = os.path.join(dest_dir, f"snapshot{extension}")
        try:
            client.download_file(bucket, key, local)
        except Exception as exc:
            raise self._translate(exc, f"{bucket}/{key}") from exc
        return Extract(path=local, extension=extension)

    def max_cursor_value(
        self, config: dict, secret: dict, *, source_schema: str, source_table: str, cursor_column: str
    ):
        bucket = config["bucket"]
        prefix = config.get("prefix") or ""
        client = self._client(config, secret)
        key = self._resolve_key(prefix, source_schema, source_table)
        try:
            head = client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:
            raise self._translate(exc, f"{bucket}/{key}") from exc
        return _s3_timestamp(head.get("LastModified"))


def _s3_timestamp(value):
    """Fixed-width, lexicographically ordered UTC isoformat - sync_last_cursor_value
    is a text column and the comparison it feeds is a string comparison.
    Mirrors the API-side helper."""
    if value is None:
        return None
    if hasattr(value, "astimezone"):
        import datetime as _dt

        return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z")
    return str(value)


# ---- Generic REST / HTTP JSON ------------------------------------------------
# GET only, JSON array of records located by a dotted records_path, two
# pagination styles, records written as JSONL. No server-side incrementality -
# max_cursor_value is always None. See the API-side connector for the full
# reasoning and the scope boundaries.
_REST_TIMEOUT_S = 20
_REST_MAX_PAGES = 1000


class RestConnector:
    type_name = "rest"

    def _auth_headers(self, config: dict, secret: dict) -> dict:
        auth = config.get("auth_type", "none")
        if auth == "none":
            return {}
        if auth == "api_key_header":
            key = secret.get("api_key")
            if not key:
                raise ConnectorError("no api_key stored for this connection")
            return {config.get("auth_header_name") or "X-API-Key": key}
        if auth == "bearer":
            token = secret.get("api_key")
            if not token:
                raise ConnectorError("no bearer token stored for this connection")
            return {"Authorization": f"Bearer {token}"}
        return {"Authorization": f"Bearer {self._oauth_token(config, secret)}"}

    def _oauth_token(self, config: dict, secret: dict) -> str:
        import json
        import urllib.error
        import urllib.parse
        import urllib.request

        client_id = secret.get("client_id")
        client_secret = secret.get("client_secret")
        if not client_id or not client_secret:
            raise ConnectorError(
                "oauth2_client_credentials needs both client_id and client_secret"
            )
        form = {"grant_type": "client_credentials", "client_id": client_id,
                "client_secret": client_secret}
        if config.get("oauth_scope"):
            form["scope"] = config["oauth_scope"]
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
            # Never echo the body - a token endpoint can quote back the secret.
            raise ConnectorError(
                f"the token endpoint rejected the credentials (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ConnectorError(f"could not get an access token: {exc}") from exc
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise ConnectorError("the token endpoint returned no access_token")
        return str(token)

    def _fetch_page(self, config: dict, secret: dict, params: dict):
        import json
        import urllib.error
        import urllib.parse
        import urllib.request

        base = config["base_url"]
        path = config.get("resource_path") or ""
        url = f"{base.rstrip('/')}/{path.lstrip('/')}" if path else base
        if params:
            separator = "&" if urllib.parse.urlparse(url).query else "?"
            url = f"{url}{separator}{urllib.parse.urlencode(params)}"

        headers = {"Accept": "application/json", **self._auth_headers(config, secret)}
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=_REST_TIMEOUT_S) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise ConnectorError(f"the API returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectorError(f"could not reach the API: {exc}") from exc
        try:
            return json.loads(body.decode("utf-8", "replace"))
        except ValueError as exc:
            raise ConnectorError("the API did not return JSON") from exc

    def _records(self, payload, config: dict) -> list:
        located = _json_path(payload, config.get("records_path") or "")
        if not isinstance(located, list):
            where = config.get("records_path") or "the response body"
            raise ConnectorError(f"expected a JSON array at {where}")
        return [row for row in located if isinstance(row, dict)]

    def _pages(self, config: dict, secret: dict):
        style = config.get("pagination", "none")
        params = {}
        if config.get("page_size_param"):
            params[config["page_size_param"]] = config.get("page_size", 100)

        page_number = 1
        cursor = None
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
                if not records:
                    return
                page_number += 1
            else:
                cursor = _json_path(payload, config.get("cursor_path") or "")
                if cursor in (None, "", []):
                    return

    def snapshot(
        self,
        config: dict,
        secret: dict,
        *,
        source_schema: str,
        source_table: str,
        dest_dir: str,
        max_bytes: int,
        cursor_column=None,
        cursor_value=None,
    ) -> "Extract":
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
            return Extract(path=dest, extension=".jsonl", empty=True)
        return Extract(path=dest, extension=".jsonl")

    def max_cursor_value(
        self, config: dict, secret: dict, *, source_schema: str, source_table: str, cursor_column: str
    ):
        """Always None - REST has no universal "changed since". See the
        API-side connector."""
        return None


def _json_path(payload, path: str):
    """Dotted lookup into a decoded JSON body; empty path means the body
    itself. Mirrors the API-side helper."""
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


# ---- registry ----------------------------------------------------------------
_REGISTRY = {
    PostgresConnector.type_name: PostgresConnector(),
    MySQLConnector.type_name: MySQLConnector(),
    S3Connector.type_name: S3Connector(),
    RestConnector.type_name: RestConnector(),
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
