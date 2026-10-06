"""Nothing slow runs on the API's event loop (§877).

The API serves every request on one event loop per task, so a synchronous
call made directly in an `async def` holds up every request on the task until
it returns. Most of the slow work already went through
`anyio.to_thread.run_sync`; §877 found the rest. A "run now" sync ingested
and merged with DuckDB and uploaded the result in line. A new dataset
version's upload, of up to 200 MB, and a dataset's deletion, which lists and
deletes its whole prefix, did the same, and an invitation called Cognito.

Checked as source, because the defect is where a call is made and not what it
returns. Each call here is one that reaches DuckDB, S3, Cognito, the network
or the clock. It must be made from a synchronous function or a lambda, which
is how this codebase hands work to a thread, and not in an `async def`
itself. The operator commands are run from a shell, with no other requests to
hold up.
"""
from __future__ import annotations

import ast
import os

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
SERVICES = os.path.join(SRC, "services")

#: Operator commands (`python -m`), which have no requests to hold up.
OPERATOR = {"instance_cutover.py", "restore_check.py"}

STORAGE_METHODS = {"put", "read", "local_path", "size", "delete_prefix"}
SLOW_METHODS = {
    "urlopen", "sleep", "check_output", "Popen",
    "get_secret_value", "put_secret_value", "create_secret",
    "admin_create_user", "admin_disable_user", "admin_enable_user", "admin_delete_user",
    "get_object", "put_object", "list_objects_v2", "delete_objects", "head_object",
}
#: The engines' cheap helpers, which read a schema or a name and not a file.
ENGINE_CHEAP = {
    "diff_schemas", "validate_alias", "InputTable", "check_sql", "json_value",
    "_clean", "_number", "expectations_at_risk", "typed_edits",
}
ENGINE_MODULES = {"engine", "dataset_engine", "_engine", "function_engine"}


def _top_level_functions(path: str) -> set[str]:
    tree = ast.parse(open(path).read())
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


ENGINE = (_top_level_functions(os.path.join(SERVICES, "dataset_engine.py"))
          | _top_level_functions(os.path.join(SERVICES, "function_engine.py"))) - ENGINE_CHEAP


def _is_storage(value: ast.expr) -> bool:
    if isinstance(value, ast.Name):
        return value.id in ("storage", "gateway")
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        return value.func.attr == "current"
    return isinstance(value, ast.Attribute) and value.attr in ("storage", "gateway")


def _slow(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute):
        if f.attr in STORAGE_METHODS and _is_storage(f.value):
            return True
        if isinstance(f.value, ast.Name) and f.value.id in ENGINE_MODULES and f.attr in ENGINE:
            return True
        if f.attr in SLOW_METHODS and not ast.unparse(f).startswith(("asyncio.", "anyio.")):
            return True
    if isinstance(f, ast.Name) and f.id in ENGINE:
        return True
    return False


def _in_async(node: ast.AST, path: str, found: list[str], inside: str | None = None) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.Lambda, ast.FunctionDef)):
            _in_async(child, path, found, None)
        elif isinstance(child, ast.AsyncFunctionDef):
            _in_async(child, path, found, child.name)
        else:
            if inside and isinstance(child, ast.Call) and _slow(child):
                found.append(f"{os.path.relpath(path, SRC)}:{child.lineno} in {inside}: "
                             f"{ast.unparse(child.func)}")
            _in_async(child, path, found, inside)


def slow_calls_on_the_loop(source: str, path: str = "<source>") -> list[str]:
    found: list[str] = []
    _in_async(ast.parse(source), path, found)
    return found


def test_no_async_function_makes_a_slow_call_itself() -> None:
    found: list[str] = []
    for folder, _, files in os.walk(SRC):
        for name in files:
            if name.endswith(".py") and name not in OPERATOR:
                path = os.path.join(folder, name)
                found += slow_calls_on_the_loop(open(path).read(), path)
    assert not found, "slow calls on the event loop:\n  " + "\n  ".join(found)


def test_the_check_tells_a_call_in_line_from_one_handed_to_a_thread() -> None:
    """The check itself, both ways: a check that found nothing anywhere would
    pass the test above as well."""
    in_line = (
        "async def f(storage, engine):\n"
        "    storage.put(k, b)\n"
        "    engine.ingest_to_parquet(a, b, c)\n"
        "    cognito.admin_create_user(e, n)\n"
    )
    assert len(slow_calls_on_the_loop(in_line)) == 3
    handed = (
        "async def f(storage, engine):\n"
        "    await to_thread.run_sync(storage.put, k, b)\n"
        "    await to_thread.run_sync(lambda: engine.ingest_to_parquet(a, b, c))\n"
        "    def work():\n"
        "        return engine.merge_incremental(a, b, c, d)\n"
        "    await to_thread.run_sync(work)\n"
        "    await asyncio.sleep(1)\n"
        "    engine.diff_schemas(a, b)\n"
    )
    assert slow_calls_on_the_loop(handed) == []
