"""How long the platform takes at a million rows (roadmap phase 3, E.4; §804).

`docs/roadmap-phase-3-fidelity.md` E.4: "Every test runs against tens of rows.
Not 'it will be slow' - unknown, which is worse, because it cannot be planned
around." And its acceptance line: "a named number for p95 dataset-preview
latency at a million rows. Any number."

This drives the real API in-process (TestClient, so no network) against the
development database and local storage, through the routes a person uses:

- upload a million-row file;
- the dataset preview, the profile (first, then cached) and a grouped query;
- map it to an object type and sync a million objects into the index;
- list the first page of objects, count them, and sum a property over them.

Each timed read is repeated and reported as p50/p95/max in milliseconds; the
one-off writes are reported once, in seconds. Run it on a machine you can
describe, because the numbers are about that machine:

    cd apps/api && DATABASE_URL=... TEST_ADMIN_DSN=... \\
      ../../.venv-api/bin/python bench/scale.py [--rows 1000000] [--repeat 30]

It prints one JSON object. Not part of the test suite: a benchmark that runs
on every commit is a slow test, and one nobody reads.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tests"))


def timed(fn, repeat: int) -> dict:
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return {
        "runs": repeat,
        "p50_ms": round(statistics.median(samples), 1),
        "p95_ms": round(samples[max(0, int(round(0.95 * repeat)) - 1)], 1),
        "max_ms": round(samples[-1], 1),
    }


def once(fn) -> tuple[object, float]:
    started = time.perf_counter()
    result = fn()
    return result, round(time.perf_counter() - started, 2)


def make_file(rows: int, directory: str) -> str:
    """A table shaped like an operational one: a key, a category to group by,
    a number to sum, a timestamp and some text."""
    import duckdb

    path = os.path.join(directory, "events.parquet")
    duckdb.connect().execute(f"""
        COPY (
          SELECT 'E' || lpad(CAST(i AS VARCHAR), 8, '0') AS event_id,
                 ['north', 'south', 'east', 'west', 'central'][1 + i % 5] AS region,
                 round(((i * 7919) % 100000) / 100.0, 2) AS amount,
                 TIMESTAMP '2026-01-01' + INTERVAL (i % 525600) MINUTE AS happened_at,
                 'note ' || CAST(i % 997 AS VARCHAR) AS note
            FROM range({rows}) t(i)
        ) TO '{path}' (FORMAT parquet, COMPRESSION zstd)
    """)
    return path


def main(argv: list[str]) -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--repeat", type=int, default=30)
    parser.add_argument("--skip-objects", action="store_true",
                        help="measure the dataset half only")
    args = parser.parse_args(argv)

    # One access line per request would bury the report.
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    from fastapi.testclient import TestClient

    from test_api import Fixture, LocalVerifier, hdr
    from src.main import create_app
    from src.middleware import auth as auth_mw
    from src.routes import datasets as ds_routes
    from src.services.storage import LocalStorageGateway

    out: dict = {"rows": args.rows, "repeat": args.repeat, "cpus": os.cpu_count()}
    with tempfile.TemporaryDirectory() as work:
        auth_mw.configure_verifier(LocalVerifier())
        ds_routes.configure_storage_gateway(LocalStorageGateway(os.path.join(work, "storage")))
        fx = Fixture()
        wbase = f"/api/workspaces/{fx.workspace}"
        pbase = f"{wbase}/projects/{fx.project}"
        editor = hdr(fx.editor_sub)
        path, out["make_file_s"] = once(lambda: make_file(args.rows, work))
        out["file_mb"] = round(os.path.getsize(path) / 1024 / 1024, 1)

        with TestClient(create_app(), raise_server_exceptions=True) as client:
            def upload():
                with open(path, "rb") as handle:
                    r = client.post(f"{pbase}/datasets/upload", headers=editor,
                                    data={"name": f"Scale {fx.tag}"},
                                    files={"file": ("events.parquet", handle,
                                                    "application/octet-stream")})
                assert r.status_code == 201, r.text
                return r.json()["id"]

            dataset, out["upload_s"] = once(upload)
            base = f"{pbase}/datasets/{dataset}"

            def ok(r):
                assert r.status_code == 200, r.text
                return r.json()

            preview = ok(client.get(f"{base}/preview", headers=editor))
            assert preview["total_rows"] == args.rows, preview["total_rows"]
            out["dataset_preview"] = timed(
                lambda: ok(client.get(f"{base}/preview", headers=editor)), args.repeat)
            _profile, out["dataset_profile_first_s"] = once(
                lambda: ok(client.get(f"{base}/profile", headers=editor)))
            out["dataset_profile_cached"] = timed(
                lambda: ok(client.get(f"{base}/profile", headers=editor)), args.repeat)
            grouped = ("SELECT region, count(*) AS n, sum(amount) AS total "
                       "FROM dataset GROUP BY region ORDER BY region")
            out["dataset_group_query"] = timed(
                lambda: ok(client.post(f"{base}/query", headers=editor, json={"sql": grouped})),
                args.repeat)

            if not args.skip_objects:
                made = ok_created(client.post(f"{wbase}/object-types", headers=editor, json={
                    "api_name": f"event_{fx.tag}", "display_name": f"Event {fx.tag}",
                    "properties": [
                        {"api_name": "region", "data_type": "string"},
                        {"api_name": "amount", "data_type": "float"},
                        {"api_name": "note", "data_type": "string"},
                    ]}))
                source = ok_created(client.post(f"{pbase}/object-type-sources", headers=editor, json={
                    "object_type_id": made["id"], "dataset_id": dataset,
                    "primary_key_column": "event_id",
                    "column_mappings": {"region": "region", "amount": "amount", "note": "note"}}))
                from src.services.instances import MAX_INSTANCE_SYNC_ROWS

                if args.rows <= MAX_INSTANCE_SYNC_ROWS:
                    synced, out["object_sync_s"] = once(lambda: ok(client.post(
                        f"{pbase}/object-type-sources/{source['id']}/sync", headers=editor)))
                    out["object_sync_result"] = {k: synced.get(k) for k in ("upserted", "removed")}
                    out["object_sync_by"] = "api"
                else:
                    # Past the interactive limit a table is the worker's: its
                    # scheduled sync is the only way a million rows become
                    # objects, so that is what is timed.
                    out["object_sync_s"] = worker_sync(source["id"], os.path.join(work, "storage"))
                    out["object_sync_by"] = "worker"
                definition = {"object_type_id": made["id"]}
                out["objects_first_page"] = timed(lambda: ok(client.get(
                    f"{wbase}/object-types/{made['id']}/instances?limit=50", headers=editor)),
                    args.repeat)
                count = ok(client.post(f"{wbase}/object-sets/aggregate", headers=editor,
                                       json={"definition": definition}))
                assert count["value"] == args.rows, count
                out["objects_count"] = timed(lambda: ok(client.post(
                    f"{wbase}/object-sets/aggregate", headers=editor,
                    json={"definition": definition})), args.repeat)
                out["objects_sum"] = timed(lambda: ok(client.post(
                    f"{wbase}/object-sets/aggregate", headers=editor,
                    json={"definition": definition, "aggregation": "sum",
                          "property": "amount"})), args.repeat)
    return out


def worker_sync(source_id: str, storage_root: str) -> float:
    """Make the source due and run the worker's scheduled sync job once."""
    import psycopg
    from dagster import build_op_context

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "worker", "src"))
    from anchor_worker.jobs.instance_syncs import run_due_object_source_syncs
    from anchor_worker.resources import PlatformDatabase

    admin = os.environ["TEST_ADMIN_DSN"]
    app = os.environ["DATABASE_URL"].replace("+psycopg", "")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("UPDATE object_type_sources SET sync_schedule = '0 0 1 1 *', "
                     "sync_next_run_at = now() - interval '1 minute' WHERE id = %s", (source_id,))
    os.environ["LOCAL_STORAGE_ROOT"] = storage_root
    os.environ.pop("DATA_BUCKET", None)
    started = time.perf_counter()
    run_due_object_source_syncs(build_op_context(
        resources={"platform_db": PlatformDatabase(dsn=app)}))
    elapsed = round(time.perf_counter() - started, 2)
    with psycopg.connect(admin, autocommit=True) as conn:
        status, error = conn.execute(
            "SELECT sync_status, last_error FROM object_type_sources WHERE id = %s",
            (source_id,)).fetchone()
        conn.execute("UPDATE object_type_sources SET sync_schedule = NULL, "
                     "sync_next_run_at = NULL WHERE id = %s", (source_id,))
    assert str(status) == "ok", error
    return elapsed


def ok_created(r):
    assert r.status_code == 201, r.text
    return r.json()


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:]), indent=2))
