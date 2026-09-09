"""Python model transform execution - the worker slice the spec's "isolated
worker runtime" note anticipated (SQL transforms run inline in the API,
sandboxed via DuckDB's `enable_external_access` switch; Python needs a real
process boundary DuckDB can't give it, which is why the API rejects
language='python' at run time and leaves the run 'queued' for this module).

Honesty about what this actually is, flagged clearly: this is process-level
isolation - a fresh OS process, capped CPU/memory, a wall-clock timeout, and
a stripped environment - not a hard multi-tenant security boundary. It does
not stop the transform from opening a network socket or reading files
outside its working directory; that needs a real sandbox (gVisor, a
Firecracker microVM, a network-denied container) applied at the worker's
deployment layer, which is a production hardening step out of scope for
this build. Treat this the same way the rest of this platform treats size
caps: a conservative day-one boundary, not the final word.

Contract with user code: **two shapes, and the file says which** (§272).

*The declared transform* — what `docs/decisions/0004-running-customer-code.md`
shows, what `transform_declarations.py` parses, and the shape a file published
from a repository is written in:

    @transform(output="daily_orders", inputs={"orders": "raw_orders"})
    def build(orders):
        return orders

*The script* — every model authored directly in the Models editor since before
repositories existed: each input arrives as a plain module-level name and the
script assigns its result to `output`.

**These had never met, and the first one could not run.** Decision 0004
documents the decorator; this file documented the script; each was right about
itself. A repository-authored Python transform died on `NameError: name
'transform' is not defined` before reaching any of the sandbox's actual
limits - and if `transform` had been defined as a no-op, the function's return
value still went nowhere, because nothing called it. Neither half was wrong;
they were two contracts for one thing, written eleven units apart, and no test
used a `.py` file on the publish path or a decorator in this one.

The script shape stays because every existing model is written in it, and a
run is stamped to the exact code that produced it (0001) - a contract change
that broke old definitions would rewrite history rather than extend it.
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

# **The decorator, defined so the declared shape can run at all.** It records
# the function and returns it unchanged: importing this file must not be how
# the declaration is read - that is `transform_declarations.py`'s job and
# decision 0004's whole point - so nothing here parses or validates. It exists
# because a file that says `@transform(...)` has to find a `transform`.
#
# `anchor.transform` as well as bare `transform`, because the reader accepts
# both spellings (`_decorator_name`), and a spelling that parses as a
# declaration and then dies on NameError is the same defect in its second form.
_declared = []


def transform(**_kwargs):
    def _register(_fn):
        _declared.append((_fn, _kwargs))
        return _fn
    return _register


class _Anchor:
    transform = staticmethod(transform)


_namespace["transform"] = transform
_namespace["anchor"] = _Anchor()

with open({code_path!r}) as _f:
    _user_code = _f.read()

try:
    exec(compile(_user_code, "<model>", "exec"), _namespace)
except Exception as exc:
    print(f"MODEL_ERROR: {{type(exc).__name__}}: {{exc}}", file=sys.stderr)
    sys.exit(1)

# **A module-level `output` wins.** Not a precedence puzzle: a file with both
# is a script that also happens to declare, and the script's assignment is the
# thing that ran last. Checking it first also means the old shape reaches its
# result without the decorator machinery being involved at all.
_output = _namespace.get("output")
if _output is None and len(_declared) > 1:
    # The publisher refuses this too (§272), so reaching it means the file
    # changed between publish and run. Refusing rather than picking the first
    # keeps "what was declared" and "what ran" the same sentence.
    print(
        "MODEL_ERROR: this file declares more than one transform, so which one "
        "produces the output is ambiguous",
        file=sys.stderr,
    )
    sys.exit(1)
if _output is None and _declared:
    _fn, _kwargs = _declared[0]
    _aliases = dict(_kwargs.get("inputs") or {{}})
    # **By keyword, never by position.** `@transform` itself refuses positional
    # arguments so that the file says which name means what rather than relying
    # on order; passing the inputs positionally here would put that back in
    # through the other door, and a transform whose parameters were in a
    # different order would silently read the wrong dataset.
    _missing = [_a for _a in _aliases if _a not in _namespace]
    if _missing:
        print(
            "MODEL_ERROR: this transform declares inputs that were not provided: "
            + ", ".join(sorted(_missing)),
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        _output = _fn(**{{_a: _namespace[_a] for _a in _aliases}})
    except TypeError as exc:
        # The common mistake, and a raw TypeError names the function rather
        # than the mismatch: a parameter list that does not match the declared
        # aliases.
        print(
            f"MODEL_ERROR: {{_fn.__name__}} does not take the inputs it declares "
            f"({{', '.join(sorted(_aliases)) or 'none'}}): {{exc}}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(f"MODEL_ERROR: {{type(exc).__name__}}: {{exc}}", file=sys.stderr)
        sys.exit(1)
    if _output is None:
        print(
            f"MODEL_ERROR: {{_fn.__name__}} returned nothing - a declared "
            "transform returns the table it produces",
            file=sys.stderr,
        )
        sys.exit(1)

if _output is None:
    print(
        "MODEL_ERROR: this file neither set a variable named `output` nor "
        "declared a transform with @transform",
        file=sys.stderr,
    )
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
            f"the transform produced {row_count:,} rows - above this build's "
            f"{MAX_OUTPUT_ROWS:,} row limit"
        )
    schema = [ColumnSchema(name=c["name"], data_type=c["data_type"]) for c in payload["schema"]]
    return schema, row_count
