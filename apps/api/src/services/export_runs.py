"""Running an export (decision 0014; `data-connection` p.192-206).

The third of the three: `exports.py` is what a configuration means,
`export_store.py` is what is in the database, and this is the part that needs
something on the other end of a socket.

**Returns a result object rather than raising**, for `webhook_calls.perform`'s
reason one feature over: every caller has to record the outcome either way, and
a function that raised for a failure would make the caller's happy path and its
recording path two different shapes.

**Blocking work inside `anyio.to_thread.run_sync`.** Reading a parquet through
DuckDB and streaming it into a far-away database is slow by construction, and
doing it on the event loop would stop every other request the process is
serving. Decision 0012 §3a records this for webhooks; an export is the same
hazard with a bigger payload.
"""
from __future__ import annotations

import os
import tempfile
import time
from typing import Any

import anyio

from . import dataset_engine, egress, exports as exports_service
from .connectors import SourceReadError, get_connector


def result(
    *, ok: bool, skipped: bool = False, dataset_version: int | None = None,
    rows_written: int = 0, error: str | None = None, duration_ms: int = 0,
    detail: str | None = None,
) -> dict[str, Any]:
    """One run's outcome, in the shape `export_store.record` stores."""
    return {
        "ok": ok,
        "skipped": skipped,
        "dataset_version": dataset_version,
        "rows_written": rows_written,
        "error": error,
        "duration_ms": duration_ms,
        "detail": detail,
    }


async def perform(
    export: dict[str, Any],
    connection: dict[str, Any],
    secret: dict[str, str],
    *,
    parquet_path: str | None,
    dataset_version: int,
    dataset_schema: list[dict[str, Any]],
    policies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write the dataset's current version to the destination, or say why not.

    `parquet_path` is None when the version has no stored file — a real state
    (`routes/datasets.py` has the same branch) and a failure rather than a
    crash, because the metadata is true and the bytes are not addressable.
    """
    started = time.monotonic()

    if exports_service.should_skip(export.get("mode"), export.get("last_version"), dataset_version):
        # p.192's June 2025 behaviour, and the reason it is a *success*: a
        # scheduled export finding nothing new has done its job.
        return result(
            ok=True, skipped=True, dataset_version=dataset_version,
            duration_ms=int((time.monotonic() - started) * 1000),
            detail=f"version {dataset_version} has already been exported",
        )

    if parquet_path is None:
        return result(
            ok=False, dataset_version=dataset_version,
            error="this dataset version has no stored file, so its rows cannot be exported",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    connector = get_connector(str(connection["source_type"]))
    config = connection["config"]
    try:
        # §263: the source's own allowlist, in scope for the call. An explicit
        # argument rather than an ambient scope for `webhook_calls.perform`'s
        # reason — this caller already holds the connection row, and an
        # argument that cannot be forgotten beats a context that can.
        with egress.restricted_to(policies):
            if export["kind"] == "file":
                written = await anyio.to_thread.run_sync(
                    lambda: _put_file(
                        connector, config, secret, export, parquet_path, dataset_version
                    )
                )
                return result(
                    ok=True, dataset_version=dataset_version, rows_written=0,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    detail=f"wrote {written}",
                )
            rows = await anyio.to_thread.run_sync(
                lambda: _put_rows(
                    connector, config, secret, export, parquet_path, dataset_schema
                )
            )
            return result(
                ok=True, dataset_version=dataset_version, rows_written=rows,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
    except egress.EgressRefused as exc:
        # Nothing was attempted, so this is a configuration answer rather than
        # a failure to reach one — decision 0013 §4's distinction, and the
        # fifth call site to make it.
        return result(
            ok=False, dataset_version=dataset_version, error=str(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except (SourceReadError, dataset_engine.DatasetEngineError) as exc:
        return result(
            ok=False, dataset_version=dataset_version, error=str(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # pragma: no cover - driver surprises
        return result(
            ok=False, dataset_version=dataset_version,
            error=f"the export failed: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def _put_file(
    connector, config, secret, export, parquet_path: str, dataset_version: int
) -> str:
    """p.193's file export: the dataset's file, as it is, to the destination.

    **The name carries the version.** p.193 says an existing file is
    overwritten by default, which is right for a mirror and wrong for a
    history — and a dataset version is immutable here, so naming the file
    after it gives the destination a series rather than one file that changes
    under whoever is reading it. p.193's own advice about landing exports in a
    dedicated sub-folder is the same instinct.
    """
    filename = f"{export['name']}-v{dataset_version}.parquet"
    return connector.export_file(
        config, secret,
        prefix=export["destination"]["prefix"], filename=filename,
        local_path=parquet_path,
    )


def _put_rows(
    connector, config, secret, export, parquet_path: str,
    dataset_schema: list[dict[str, Any]],
) -> int:
    """p.195's table export: the current view's rows, into an existing table.

    **The 1:1 column check happens here, before anything is written** (p.197).
    Foundry lets a mismatch fail at run time; failing at row 40,000 of a table
    export names a driver error rather than a column.

    **The column list comes from the CSV's own header, not from the dataset
    row.** Postgres' `COPY t (a, b, c) FROM STDIN ... HEADER true` *skips* the
    header line and maps values by the position of that column list — so a
    column list built from one source and a file written from another would,
    if they ever disagreed on order, write every value into the wrong column
    and report success. They are derived from the same parquet today and there
    is no reason for them to diverge, which is exactly the kind of reasoning
    that stops being true later. Reading the header makes them the same list by
    construction rather than by agreement.
    """
    place = export["destination"]
    schema_name, table = place.get("schema", ""), place["table"]
    available = connector.destination_columns(
        config, secret, schema=schema_name, table=table
    )
    missing = exports_service.missing_columns(dataset_schema, available)
    if missing:
        where = f"{schema_name}.{table}" if schema_name else table
        raise SourceReadError(
            f"{where} has no column named {', '.join(missing)} - p.197 needs a 1:1 "
            "match on names, and the comparison is case-sensitive"
        )

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "export.csv")
        dataset_engine.export_csv(parquet_path, csv_path)
        columns = _header(csv_path)
        if not columns:
            # An empty file is not an error: a dataset can legitimately have no
            # rows, and `mirror` on an empty dataset means "empty the table",
            # which the truncate below still does.
            return connector.export_rows(
                config, secret, schema=schema_name, table=table,
                columns=[str(c["name"]) for c in dataset_schema], csv_path=csv_path,
                truncate=exports_service.truncates(export.get("mode")),
            )
        return connector.export_rows(
            config, secret,
            schema=schema_name, table=table, columns=columns, csv_path=csv_path,
            truncate=exports_service.truncates(export.get("mode")),
        )


def _header(csv_path: str) -> list[str]:
    """The CSV's column names, in file order. Empty when the file has none."""
    import csv as csv_module

    with open(csv_path, newline="", encoding="utf-8") as handle:
        row = next(csv_module.reader(handle), None)
    return [name.strip() for name in row] if row else []
