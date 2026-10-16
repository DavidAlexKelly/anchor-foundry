"""No coroutine calls AWS through a blocking client itself (§954).

The API serves every request on one event loop per task. The secrets,
storage and Cognito gateways are boto3 underneath, which blocks: called
from a coroutine, a Secrets Manager round trip - every sync, export, file
sync, outbound call and action webhook read one - stopped every other
request on the task until it answered, and under throttling boto3's retries
make that seconds. They go through `anyio.to_thread.run_sync`, as the
storage calls already did; this reads the source and keeps it that way.

A sync function that calls them is fine: it is either itself run on a
thread, or called from one. Only a direct call in a coroutine's own body
(not a function nested in it, which is how a thread's work is written here)
is the mistake.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

#: The blocking gateways' methods (storage.S3StorageGateway,
#: secrets.Boto3SecretsGateway, orgs.Boto3CognitoGateway), and the one helper
#: every caller of a connection's secret goes through.
BLOCKING = {
    "put", "put_file", "read", "local_path", "size", "delete_prefix", "sizes_under",
    "put_secret", "get_secret", "delete_secret",
    "admin_create_user", "admin_disable_user",
    "secret_values_for",
}
#: What those are called on here; a method of the same name on anything else
#: (a dict's `get`, a DuckDB `read`) is not one of them.
RECEIVERS = ("storage", "secret", "gateway", "cognito", "conn_service")
#: Operator commands, which run alone and serve nobody else.
COMMANDS = {"restore_check.py", "instance_cutover.py"}


def _own_nodes(fn: ast.AsyncFunctionDef):
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def blocking_calls(source: str) -> list[tuple[int, str]]:
    found = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in _own_nodes(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in BLOCKING
                    and any(r in ast.unparse(node.func.value).lower() for r in RECEIVERS)):
                found.append((node.lineno, f"{fn.name}: {ast.unparse(node)[:80]}"))
    return found


def test_no_coroutine_calls_a_blocking_gateway() -> None:
    found = [f"{path.relative_to(SRC)}:{line} {what}"
             for path in sorted(SRC.rglob("*.py")) if path.name not in COMMANDS
             for line, what in blocking_calls(path.read_text(encoding="utf-8"))]
    assert not found, ("a coroutine calls a blocking gateway on the event loop; wrap it in "
                       "`await anyio.to_thread.run_sync(...)`:\n  " + "\n  ".join(found))


def test_the_check_sees_what_it_is_for() -> None:
    """Both halves of the rule, on code written to break and to keep it."""
    assert blocking_calls(
        "async def f(gw, row):\n    return conn_service.secret_values_for(gw, row)\n")
    assert not blocking_calls(
        "async def f(gw, row):\n"
        "    return await anyio.to_thread.run_sync(conn_service.secret_values_for, gw, row)\n")
    assert not blocking_calls(
        "async def f(storage):\n"
        "    def work():\n        return storage.put('k', b'')\n"
        "    return await anyio.to_thread.run_sync(work)\n")
    assert not blocking_calls("async def f(d):\n    return d.get('k')\n")
