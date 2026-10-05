"""§824: the workspace check once per statement, in the policies 0155 missed.

0058 replaced a per-row `rls_can_access_workspace(...)` with the per-query
`rls_workspace_ids()` set across the isolation policies of its day, and 0155
made that set an InitPlan, computed once per statement. Thirteen policies
written since still call `rls_can_access_workspace(<expr>)` row by row, and
each call is a membership lookup: `object_type_usage` holds 21,372 rows on the
development database, so the ontology cleanup page - which sums it - took five
seconds, nearly all of it in that policy.

Each call becomes `(<expr>) = ANY ((SELECT rls_workspace_ids())::uuid[])`,
read from `pg_policies` rather than listed, with `<expr>` found by matching
parentheses because some are calls themselves
(`rls_project_workspace_id(project_id)`). `tests/test_rls_workspace_ids.py`
proves the two predicates equivalent per access route, and
`tests/test_rls_policies.py` now refuses a later policy written per row.

**Why not the project check too.** The same rewrite of
`rls_can_access_project` was measured on a copy of the development database
and made things slower, not faster, as 0060 did before 0061 reverted it: an
org owner's project set is every project in the organisation, ten thousand
ids built once per statement, which costs more than the per-row checks it
replaces on the small reads that dominate. The workspace set is a handful of
ids, so its cost is nothing.
"""
from __future__ import annotations

CALL = "rls_can_access_workspace("
SET = "(SELECT rls_workspace_ids())::uuid[]"


def rewrite(text: str) -> str:
    """Every `rls_can_access_workspace(<expr>)` in a deparsed policy, as a
    membership test of the statement's workspace set."""
    out: list[str] = []
    at = 0
    while True:
        start = text.find(CALL, at)
        if start < 0:
            out.append(text[at:])
            return "".join(out)
        depth, i = 1, start + len(CALL)
        while depth:
            if i >= len(text):
                raise ValueError(f"unbalanced call in policy text: {text!r}")
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        argument = text[start + len(CALL):i - 1]
        out.append(text[at:start])
        out.append(f"(({argument}) = ANY ({SET}))")
        at = i


def apply(cur) -> None:
    cur.execute(
        """
        SELECT schemaname, tablename, policyname, qual, with_check
          FROM pg_policies
         WHERE qual LIKE %s OR with_check LIKE %s
        """,
        (f"%{CALL}%", f"%{CALL}%"),
    )
    for schema, table, name, qual, check in cur.fetchall():
        if qual and CALL in qual:
            cur.execute(f'ALTER POLICY "{name}" ON "{schema}"."{table}" USING ({rewrite(qual)})')
        if check and CALL in check:
            cur.execute(f'ALTER POLICY "{name}" ON "{schema}"."{table}" WITH CHECK ({rewrite(check)})')
