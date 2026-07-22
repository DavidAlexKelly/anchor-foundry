"""Connector registry (spec §"Connections" supported source types).

Each connector declares its non-secret config model, its secret fields, and
implements test/discover against the live source. The registry holds only
connectors that genuinely work in this build — PostgreSQL today. Additional
source types from the spec's list (MySQL, Snowflake, S3, Salesforce, …) are
additive registry entries with their own drivers; they are deliberately not
listed until implemented, so the UI can never offer a connector that fails.

Driver calls are synchronous (psycopg); routes run them in a worker thread.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class ConnectorConfigError(ValueError):
    """Config failed the connector's schema. Message is user-safe."""


class ConnectorOperationError(RuntimeError):
    """Test/discover failed against the source. Message is user-safe (no
    credentials, no stack traces)."""


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


# ---- PostgreSQL --------------------------------------------------------------
class PostgresConfig(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    user: str = Field(min_length=1, max_length=128)
    sslmode: str = Field(default="prefer", pattern="^(disable|prefer|require|verify-ca|verify-full)$")


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

    def test(self, config: dict[str, Any], secret: dict[str, str]) -> None:
        import psycopg

        try:
            with psycopg.connect(**self._conninfo(config, secret)) as conn:
                conn.execute("SELECT 1")
        except psycopg.OperationalError as exc:
            # First line of the driver message is user-safe (auth failed,
            # host unreachable, unknown database); never includes the password.
            reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
            raise ConnectorOperationError(reason) from exc

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
            reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
            raise ConnectorOperationError(reason) from exc

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


# ---- registry ----------------------------------------------------------------
_REGISTRY: dict[str, PostgresConnector] = {
    PostgresConnector.type_name: PostgresConnector(),
}


def get_connector(source_type: str) -> PostgresConnector:
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
    for connector in _REGISTRY.values():
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
