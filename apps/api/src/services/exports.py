"""What an export means (decision 0014; `data-connection` p.17, p.192-206).

The pure half: given a dataset's schema, a destination's schema and a mode,
what is legal and what will happen. No database and no socket — `export_store`
holds the rows and `export_runs` makes the call, the same three-way split every
feature here uses.

**All six of p.195-196's modes.** Decision 0014 §2 built two, because the
other four are defined over transactions - "unexported *transactions* from the
current view", or a `SNAPSHOT` / `APPEND` / `UPDATE` / `DELETE` type - and
`dataset_versions` had none. Decision 0020 (db 0144) gave every version its
type, and `plan` is what the four read from it (§748).

`data-connection` pages are `p.N`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: p.193's export types, minus streaming. p.17 pairs each with the sync it
#: reverses, and there is no stream here to reverse.
KINDS = ("table", "file")

#: The two of p.195-196's six whose definitions never mention a transaction.
#:
#:   'mirror' - "truncate (drop) the target table, and then export a snapshot
#:              of the full current dataset view... the external table always
#:              mirroring the Foundry dataset" (p.195)
#:   'full'   - "Always export a snapshot of the entire view... Note: This
#:              option will almost always result in duplicates in the external
#:              table. This option can be useful when external systems consume
#:              and remove rows after each run" (p.195)
#:
#: and p.195-196's four over transactions (§748), whose sending is `plan`'s:
#:
#:   'efficient_mirror'     - "Efficiently mirror dataset to external table
#:                            (recommended)"
#:   'incremental'          - "Export incrementally"
#:   'incremental_truncate' - "Export incrementally with truncation"
#:   'append_only'          - "Export incrementally and fail if not APPEND"
MODES = ("mirror", "full", "efficient_mirror", "incremental", "incremental_truncate",
         "append_only")

#: Shown beside each in a picker. p.195's own wording, because a mode whose
#: consequence is "almost always result in duplicates" should say so where
#: somebody is choosing it rather than in a document they will not open.
MODE_LABELS: dict[str, str] = {
    "mirror": "Replace the table each run, so it always matches the dataset",
    "full": "Append the whole dataset each run, without clearing the table",
    "efficient_mirror": ("Keep the table equal to the dataset, sending only new rows "
                         "where it can (recommended)"),
    "incremental": ("Send only rows added since the last run; a rewritten dataset is "
                    "sent again in full, which duplicates"),
    "incremental_truncate": "Clear the table, then send only rows added since the last run",
    "append_only": ("Send only rows added since the last run, and fail rather than send "
                    "anything else"),
}

#: Which source types can be an export destination, by kind. p.192: "Data
#: Connection exports are not yet supported for all source types. Review the
#: individual source pages... Each source page will list either file export,
#: streaming export, table export, or legacy export task support."
#:
#: p.17 is what decides the pairing: a table export is "the opposite of table
#: batch syncs", a file export "the opposite of file batch syncs".
DESTINATIONS: dict[str, str] = {
    "postgres": "table",
    "mysql": "table",
    "s3": "file",
}

#: **A REST source is not a destination, because it already is one.** p.17
#: lists webhooks alongside the three export types as the other way data
#: leaves for an external system, and decision 0012 built that: a request
#: shape, inputs, outputs and a history. An export to a REST source would have
#: to invent a method, a path and a body — which is a webhook, described worse.
#: Said as a sentence rather than left as an absence, because "REST is missing
#: from a dropdown" reads as a gap and this is a redirection.
NOT_A_DESTINATION: dict[str, str] = {
    "rest": (
        "a REST source is written to with a webhook rather than an export - "
        "a webhook already carries the method, path and body an HTTP write "
        "needs, which an export would have to invent"
    ),
}

#: p.197: "Array, Map, and Struct types are not supported for exports. If the
#: dataset you are exporting contains a column with type Array, Map, or Struct,
#: the export will fail."
#:
#: Matched on the leading word because DuckDB spells the parameterised forms
#: out — `STRUCT(a INTEGER, b VARCHAR)`, `INTEGER[]`, `MAP(VARCHAR, INTEGER)` —
#: and a set membership test against the bare names would match none of them.
_UNEXPORTABLE = re.compile(r"^(struct|map|list|union)\b|\[\]$", re.IGNORECASE)

#: A schema/table/path a person typed. Deliberately permissive about content
#: and strict about *shape*: these are interpolated into an identifier position
#: in SQL, so what matters is that nothing here can end a quoted identifier or
#: start a statement.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

MAX_NAME = 200


class ExportError(ValueError):
    """An export that cannot be saved or cannot run, in a sentence somebody
    configuring one can act on."""


def unexportable_columns(schema: list[dict[str, Any]]) -> list[str]:
    """The columns p.197 refuses, by name.

    Returned as a list rather than raised, so the caller can name **all** of
    them at once. A dataset with four struct columns should not need four
    round trips to find that out.
    """
    return [
        str(column.get("name", ""))
        for column in schema
        if _UNEXPORTABLE.search(str(column.get("data_type") or column.get("type") or ""))
    ]


def parse(config: Any, *, source_type: str, schema: list[dict[str, Any]]) -> dict[str, Any]:
    """Refuse an export that could not do what its author meant. Returns it clean.

    `schema` is the dataset's, so p.197's column-type refusal happens when the
    export is *configured* rather than when it runs. Foundry lets that one fail
    at run time; a schema is known at configuration time and a refusal then is
    a refusal somebody can act on while they are still looking at the form.
    """
    if not isinstance(config, dict):
        raise ExportError("an export needs a name and a destination")

    if source_type in NOT_A_DESTINATION:
        raise ExportError(NOT_A_DESTINATION[source_type])
    kind = DESTINATIONS.get(source_type)
    if kind is None:
        raise ExportError(f"a {source_type} source cannot be an export destination")

    name = str(config.get("name") or "").strip()
    if not name or len(name) > MAX_NAME:
        raise ExportError(f"an export needs a name of 1 to {MAX_NAME} characters")

    refused = unexportable_columns(schema)
    if refused:
        # p.197 names the three; `list` is DuckDB's spelling of Array and is
        # included for that reason rather than as an addition.
        raise ExportError(
            "p.197: Array, Map and Struct columns cannot be exported, and this "
            f"dataset has {', '.join(sorted(refused))}"
        )

    mode = str(config.get("mode") or "").strip()
    if kind == "table":
        if mode not in MODES:
            raise ExportError(f"a table export needs a mode: {' or '.join(MODES)}")
    elif mode:
        # p.193 gives a file export one behaviour and no modes. Accepting one
        # silently would leave a stored value that nothing reads — the shape
        # §214 calls a control that cannot work.
        raise ExportError("a file export has no mode - p.193 gives it one behaviour")

    return {
        "name": name,
        "kind": kind,
        "mode": mode if kind == "table" else None,
        "destination": destination(kind, config.get("destination")),
    }


def destination(kind: str, raw: Any) -> dict[str, Any]:
    """The destination fields for this kind, validated and nothing else kept.

    p.197: "ensure that DATABASE, SCHEMA, and TABLE fields are filled out if
    required by your source. Missing any of these fields will cause the export
    to fail at runtime. Similarly, **including unnecessary fields can also
    result in failure**." So unknown keys are dropped rather than stored — a
    field nobody reads is a field somebody will believe in.
    """
    fields = raw if isinstance(raw, dict) else {}
    if kind == "table":
        table = str(fields.get("table") or "").strip()
        schema_name = str(fields.get("schema") or "").strip()
        if not table:
            raise ExportError("a table export needs the name of the table to write to")
        for label, value in (("table", table), ("schema", schema_name)):
            if value and not _IDENTIFIER.match(value):
                raise ExportError(
                    f"{value!r} is not a {label} name - letters, digits and "
                    "underscores, starting with a letter or underscore"
                )
        return {"schema": schema_name, "table": table}

    prefix = str(fields.get("prefix") or "").strip().lstrip("/")
    if not prefix:
        raise ExportError("a file export needs a path to write under")
    if ".." in prefix:
        raise ExportError("a path may not contain '..'")
    return {"prefix": prefix}


def missing_columns(
    dataset_schema: list[dict[str, Any]], destination_columns: list[str]
) -> list[str]:
    """Dataset columns the destination table does not have, **case-sensitively**.

    p.197: "The dataset you export from Foundry must have a 1:1 match with the
    external source, including exact column names (case-sensitive) and data
    types."

    **Case-sensitive on purpose, and it is the surprising half.** Postgres
    folds an unquoted identifier to lower case, so a destination column created
    as `CustomerId` is stored as `customerid` and a dataset column spelled
    `CustomerId` would not match it. Comparing case-insensitively would let
    that export be created and fail at run time — which is the behaviour p.197
    describes and this exists to avoid.

    Only one direction is checked. A destination column the dataset lacks is
    the destination's business: it may have a default, or be filled by
    something else. A dataset column the destination lacks has nowhere to go.
    """
    have = set(destination_columns)
    return [
        str(column.get("name", ""))
        for column in dataset_schema
        if str(column.get("name", "")) not in have
    ]


#: p.195-196's four modes defined over transactions (§748; decision 0020 §4).
#: Each reads the versions since the export's last one, by type.
TRANSACTIONAL = ("efficient_mirror", "incremental", "incremental_truncate", "append_only")


@dataclass(frozen=True)
class Plan:
    """What one run of a transactional mode writes (§748).

    `whole` is a version whose entire view is sent, `added` the APPEND
    versions whose added rows are, and `refusal` the sentence when the run
    must not write at all.
    """

    skip: bool = False
    truncate: bool = False
    whole: int | None = None
    added: tuple[int, ...] = ()
    refusal: str | None = None


def plan(mode: str, last_version: int | None, versions: list[dict[str, Any]]) -> Plan:
    """p.195-196's four transactional modes, given the dataset's versions as
    `{version_number, transaction_type}`.

    **The current view** is p.26's: it begins at the latest SNAPSHOT, or at
    the first version when there is none. The versions not yet exported are
    the ones after `last_version`.

    * efficient_mirror: "incrementally exporting any unexported transactions
      from the current dataset view and truncating the external table when
      there is a SNAPSHOT transaction" (p.195).
    * incremental: "Exports only unexported transactions from the current view
      without truncating the target table" (p.196).
    * incremental_truncate: "truncates (drops) the target table, then exports
      only transactions from the current view that have not previously been
      exported" (p.196).
    * append_only: "failing if there is a SNAPSHOT, UPDATE, or DELETE
      transaction (after the first run)" (p.196).

    The first three "do not support UPDATE … transactions" (p.195-196): an
    UPDATE among the versions a run would send rows of is refused, with
    mirror named. One inside a view sent whole is not, since the view is
    sent as it now is.
    """
    ordered = sorted(versions, key=lambda v: int(v["version_number"]))
    if not ordered:
        return Plan(refusal="this dataset has no versions yet, so there is nothing to export")
    newest = int(ordered[-1]["version_number"])
    if last_version is not None and last_version >= newest:
        return Plan(skip=True)
    snapshots = [int(v["version_number"]) for v in ordered if v["transaction_type"] == "SNAPSHOT"]
    start = snapshots[-1] if snapshots else int(ordered[0]["version_number"])
    unexported = [v for v in ordered if int(v["version_number"]) > (last_version or 0)]

    if mode == "append_only" and last_version is not None:
        for v in unexported:
            if v["transaction_type"] != "APPEND":
                return Plan(refusal=(
                    f"v{v['version_number']} is a {v['transaction_type']} transaction, and this "
                    "export takes only APPENDs after its first run. Nothing was exported, so "
                    "the table has no duplicates; a mirror export would send the dataset as it is"))
        return Plan(added=tuple(int(v["version_number"]) for v in unexported))

    new_view = last_version is None or last_version < start
    truncate = mode == "incremental_truncate" or (mode == "efficient_mirror" and new_view)
    if new_view:
        # Nothing of this view is in the table yet, so all of it is sent, and
        # what its versions were is already in what it is.
        return Plan(truncate=truncate, whole=newest)
    for v in unexported:
        if v["transaction_type"] == "UPDATE":
            return Plan(refusal=(
                f"v{v['version_number']} is an UPDATE transaction: it changed rows that may "
                "already be in the table, and an incremental export can only add rows. A "
                "mirror export replaces the table with the dataset as it is"))
    return Plan(truncate=truncate, added=tuple(int(v["version_number"]) for v in unexported))


def sent(sending: Plan) -> str:
    """What a transactional run sent, for its line in the history (p.206)."""
    cleared = "cleared the table, then " if sending.truncate else ""
    if sending.whole is not None:
        return f"{cleared}sent the whole view at v{sending.whole}"
    return f"{cleared}sent the rows {', '.join(f'v{v}' for v in sending.added)} added"


def should_skip(mode: str | None, last_version: int | None, current_version: int) -> bool:
    """p.192's June 2025 behaviour: nothing new to export is a success.

    True when this run would rewrite what is already there.

    **`full` never skips**, and that is not an exception to p.192 but a
    consequence of it. p.195 says the mode is for "external systems [that]
    consume and remove rows after each run", so there is always something new
    to export — the destination emptied itself. A `full` export that skipped
    would be a queue that stopped being fed, and the skip would look like a
    bug in whatever was consuming it.
    """
    if mode == "full":
        return False
    return last_version is not None and last_version >= current_version


def truncates(mode: str | None) -> bool:
    """Whether a run of this mode clears the target first (p.195) - always,
    for these two; `efficient_mirror` does only when `plan` says a new view
    began, and is not counted here.

    A function rather than `mode == "mirror"` at the call site, because it is
    the one property that decides whether the destination credentials need
    permission Foundry cannot check for (p.197, p.203) — and a rule spelled out
    at two call sites is a rule that can differ at one of them.
    """
    return mode in ("mirror", "incremental_truncate")


#: What each mode does to the table, for a one-line summary.
_VERBS = {
    "mirror": "replaces", "full": "appends to", "efficient_mirror": "mirrors into",
    "incremental": "appends new rows to", "incremental_truncate": "clears and appends new rows to",
    "append_only": "appends new rows to",
}


def summarise(export: dict[str, Any]) -> str:
    """One line for a list: what this export does, in the destination's terms."""
    place = export.get("destination") or {}
    if export.get("kind") == "file":
        return f"files to {place.get('prefix', '')}"
    table = place.get("table", "")
    where = f"{place['schema']}.{table}" if place.get("schema") else table
    verb = _VERBS.get(str(export.get("mode")), "appends to")
    return f"{verb} {where}"
