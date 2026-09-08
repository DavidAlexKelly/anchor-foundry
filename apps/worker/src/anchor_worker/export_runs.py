"""Running an export from the worker (decision 0016; `data-connection` p.205).

The API's `services/export_runs.py` is the original; this is the copy, for the
reason `connectors.py`'s docstring gives — api and worker are independently
deployable images with no shared Python package in this build.

**The two must not diverge, and one part of that is not left to intention.**
`anchor_worker/exports.py` is the *same file* as the API's rule module rather
than a second implementation of it, and a test holds it byte-for-byte. That is
where the skip rule lives, and the skip rule is the one place a divergence
would be invisible: p.192 makes "nothing new" a **success**, so a copy that
computed it differently would report green either way. Everything below is
orchestration around that one shared answer.

**Synchronous, unlike the API's.** The API runs this in `anyio.to_thread` so a
long export does not block the event loop; a Dagster op is already its own
process and has nothing to yield to.
"""

import csv as csv_module
import os
import tempfile
import time

from . import dataset_engine
from . import egress
from . import exports as exports_service
from .connectors import ConnectorError, get_connector


def result(
    *, ok: bool, skipped: bool = False, dataset_version=None,
    rows_written: int = 0, error=None, duration_ms: int = 0, detail=None,
) -> dict:
    """One run's outcome, in the shape the `export_runs` insert stores.

    Deliberately the same keys as the API's `export_runs.result`: the two write
    to the same table, and a history where the scheduled rows had a different
    shape from the manual ones would be a history nobody could read as one
    list.
    """
    return {
        "ok": ok,
        "skipped": skipped,
        "dataset_version": dataset_version,
        "rows_written": rows_written,
        "error": error,
        "duration_ms": duration_ms,
        "detail": detail,
    }


def perform(
    export: dict,
    connection: dict,
    secret: dict,
    *,
    parquet_path,
    dataset_version: int,
    dataset_schema: list,
    policies=None,
) -> dict:
    """Write the dataset's current version to the destination, or say why not.

    Returns a result rather than raising, for the API copy's reason: every
    caller has to record the outcome either way, and a function that raised on
    failure would make the caller's happy path and its recording path two
    different shapes. Here it matters more — the op runs several exports and
    one failing must not end the others (§263 found exactly that bug in the
    sync op, where `EgressRefused` was not a `ConnectorError` and so escaped an
    enumerated `except`).
    """
    started = time.monotonic()

    if exports_service.should_skip(
        export.get("mode"), export.get("last_version"), dataset_version
    ):
        # p.192's June 2025 behaviour, and the reason a scheduled export is
        # where it matters most: a cron that fires hourly against a dataset
        # that changes daily is twenty-three of these and one real export.
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
        # argument rather than an ambient scope, so a caller cannot forget it.
        with egress.restricted_to(policies):
            if export["kind"] == "file":
                written = _put_file(
                    connector, config, secret, export, parquet_path, dataset_version
                )
                return result(
                    ok=True, dataset_version=dataset_version, rows_written=0,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    detail=f"wrote {written}",
                )
            rows = _put_rows(connector, config, secret, export, parquet_path, dataset_schema)
            return result(
                ok=True, dataset_version=dataset_version, rows_written=rows,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
    except egress.EgressRefused as exc:
        # Listed before `ConnectorError` and separately from it, because it is
        # deliberately not one - the mistake §263 found in `sync_configs`.
        return result(
            ok=False, dataset_version=dataset_version, error=str(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except (ConnectorError, dataset_engine.DatasetEngineError) as exc:
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


def _put_file(connector, config, secret, export, parquet_path: str, dataset_version: int) -> str:
    """p.193's file export. The name carries the version, so the destination
    gets a series rather than one file that changes under whoever is reading
    it — see the API copy for the full reasoning."""
    filename = f"{export['name']}-v{dataset_version}.parquet"
    return connector.export_file(
        config, secret,
        prefix=export["destination"]["prefix"], filename=filename,
        local_path=parquet_path,
    )


def _put_rows(connector, config, secret, export, parquet_path: str, dataset_schema: list) -> int:
    """p.195's table export, with p.197's 1:1 check before anything is written.

    **The column list comes from the CSV's own header**, because Postgres'
    `COPY t (a, b) FROM STDIN … HEADER true` skips the header and maps by
    position — so a list built from one source and a file written from another
    would, if they ever disagreed on order, write every value into the wrong
    column and report success.
    """
    place = export["destination"]
    schema_name, table = place.get("schema", ""), place["table"]
    available = connector.destination_columns(config, secret, schema=schema_name, table=table)
    missing = exports_service.missing_columns(dataset_schema, available)
    if missing:
        where = f"{schema_name}.{table}" if schema_name else table
        raise ConnectorError(
            f"{where} has no column named {', '.join(missing)} - p.197 needs a 1:1 "
            "match on names, and the comparison is case-sensitive"
        )

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "export.csv")
        dataset_engine.export_csv(parquet_path, csv_path)
        columns = _header(csv_path)
        if not columns:
            # An empty file is not an error: `mirror` on an empty dataset means
            # "empty the table", which the truncate still does.
            return connector.export_rows(
                config, secret, schema=schema_name, table=table,
                columns=[str(c["name"]) for c in dataset_schema], csv_path=csv_path,
                truncate=exports_service.truncates(export.get("mode")),
            )
        return connector.export_rows(
            config, secret, schema=schema_name, table=table,
            columns=columns, csv_path=csv_path,
            truncate=exports_service.truncates(export.get("mode")),
        )


def _header(csv_path: str) -> list:
    """The CSV's column names, in file order. Empty when the file has none."""
    with open(csv_path, newline="", encoding="utf-8") as handle:
        row = next(csv_module.reader(handle), None)
    return [name.strip() for name in row] if row else []
