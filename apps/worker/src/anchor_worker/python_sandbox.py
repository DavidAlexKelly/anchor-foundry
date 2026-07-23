"""Python model transform execution — the worker slice the spec's "isolated
worker runtime" note anticipated (SQL transforms run inline in the API,
sandboxed via DuckDB's `enable_external_access` switch; Python needs a real
process boundary DuckDB can't give it, which is why the API rejects
language='python' at run time and leaves the run 'queued' for this module).

Honesty about what this actually is, flagged clearly: this is process-level
isolation — a fresh OS process, capped CPU/memory, a wall-clock timeout, and
a stripped environment — not a hard multi-tenant security boundary. It does
not stop the transform from opening a network socket or reading files
outside its working directory; that needs a real sandbox (gVisor, a
Firecracker microVM, a network-denied container) applied at the worker's
deployment layer, which is a production hardening step out of scope for
this build. Treat this the same way the rest of this platform treats size
caps: a conservative day-one boundary, not the final word.

Contract with user code: each input dataset is loaded into a pandas
DataFrame available under its input alias as a plain module-level name; the
script must assign its result to a variable named `output` (a DataFrame) by
the time it finishes.
"""
from __future__ import annotations

import os
import resource
import subprocess
import sys
import tempfile
from typing import Any

from .dataset_engine import ColumnSchema, DatasetEngineError

DEFAULT_TIMEOUT_S = 300
MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024  # 1 GB, flag: worker-tier day-one cap
CPU_LIMIT_S = 120
MAX_OUTPUT_ROWS = 5_000_000  # matches the SQL transform's day-one cap

_RUNNER_TEMPLATE = """
import json
import sys

import duckdb

_inputs = {inputs!r}
_namespace: dict = {{}}
for _alias, _path in _inputs.items():
    _namespace[_alias] = duckdb.connect().execute(
        f"SELECT * FROM read_parquet({{_path!r}})"
    ).df()

with open({code_path!r}) as _f:
    _user_code = _f.read()

try:
    exec(compile(_user_code, "<model>", "exec"), _namespace)
except Exception as exc:
    print(f"MODEL_ERROR: {{type(exc).__name__}}: {{exc}}", file=sys.stderr)
    sys.exit(1)

_output = _namespace.get("output")
if _output is None:
    print("MODEL_ERROR: the script did not set a variable named `output`", file=sys.stderr)
    sys.exit(1)

_con = duckdb.connect()
_con.register("_output_df", _output)
try:
    _con.execute(f"COPY _output_df TO {dest_path!r} (FORMAT parquet)")
    _schema = _con.execute("DESCRIBE _output_df").fetchall()
    _row_count = _con.execute("SELECT count(*) FROM _output_df").fetchone()[0]
except duckdb.Error as exc:
    print(f"MODEL_ERROR: output is not a valid table: {{exc}}", file=sys.stderr)
    sys.exit(1)

print(json.dumps({{
    "schema": [{{"name": r[0], "data_type": r[1]}} for r in _schema],
    "row_count": int(_row_count),
}}))
"""


def _limit_resources() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_S, CPU_LIMIT_S))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))


def run_python_transform(
    inputs: dict[str, str],
    code: str,
    dest_parquet: str,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> tuple[list[ColumnSchema], int]:
    os.makedirs(os.path.dirname(dest_parquet), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        code_path = os.path.join(tmp, "model.py")
        with open(code_path, "w") as f:
            f.write(code)
        runner_path = os.path.join(tmp, "runner.py")
        with open(runner_path, "w") as f:
            f.write(_RUNNER_TEMPLATE.format(inputs=inputs, code_path=code_path, dest_path=dest_parquet))

        env = {"PATH": "/usr/bin:/bin", "HOME": tmp}
        try:
            result = subprocess.run(
                [sys.executable, runner_path],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                preexec_fn=_limit_resources if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise DatasetEngineError(f"transform exceeded the {timeout_s}s time limit") from exc

        if result.returncode != 0:
            message = next(
                (line for line in result.stderr.splitlines() if line.startswith("MODEL_ERROR:")),
                None,
            )
            if message is None:
                stderr_lines = result.stderr.strip().splitlines()
                message = stderr_lines[-1] if stderr_lines else "transform failed"
            raise DatasetEngineError(message.removeprefix("MODEL_ERROR: ")[:500])

        import json

        try:
            payload: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError) as exc:
            raise DatasetEngineError("transform produced no readable output") from exc

    row_count = int(payload["row_count"])
    if row_count > MAX_OUTPUT_ROWS:
        raise DatasetEngineError(
            f"the transform produced {row_count:,} rows — above this build's "
            f"{MAX_OUTPUT_ROWS:,} row limit"
        )
    schema = [ColumnSchema(name=c["name"], data_type=c["data_type"]) for c in payload["schema"]]
    return schema, row_count
