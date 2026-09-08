"""What an export means (decision 0014; §265).

No database and no socket: `services/exports` is the half where a wrong answer
is a line. The rows and the real writes are `test_export_runs.py`.

**The two modes and the four that are absent.** p.195-196 lists six table export
modes; four of them are defined over transaction types `dataset_versions` does
not have, and `test_the_absent_modes_are_absent_on_purpose` is what stops that
becoming a silent omission somebody re-adds by accident.

`data-connection` pages are `p.N`.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import exports  # noqa: E402


def schema(*columns: tuple[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "data_type": data_type} for name, data_type in columns]


ORDERS = schema(("id", "BIGINT"), ("email", "VARCHAR"), ("total", "DOUBLE"))


def config(**over):
    out = {"name": "Nightly orders", "mode": "mirror",
           "destination": {"schema": "public", "table": "orders"}}
    out.update(over)
    return out


# ---- which sources can be a destination ------------------------------------------
def test_a_database_source_takes_a_table_export() -> None:
    """p.17: "Table exports are the opposite of table batch syncs.\""""
    for source in ("postgres", "mysql"):
        assert exports.parse(config(), source_type=source, schema=ORDERS)["kind"] == "table"


def test_an_object_store_takes_a_file_export() -> None:
    """p.17: "File exports are the opposite of file batch syncs." And p.193:
    "An example of a system supporting file exports is S3.\""""
    parsed = exports.parse(
        config(mode=None, destination={"prefix": "exports/orders"}),
        source_type="s3", schema=ORDERS,
    )
    assert parsed["kind"] == "file"
    assert parsed["mode"] is None


def test_a_rest_source_is_refused_by_being_pointed_at_webhooks() -> None:
    """**Not an absence, a redirection.** p.17 lists webhooks beside the three
    export types as the other way data leaves for an external system, and
    §259-§262 built exactly that. An export to a REST source would have to
    invent a method, a path and a body - which is a webhook, described worse.

    Refused with a sentence rather than left out of a list, because "REST is
    missing from the dropdown" reads as a gap somebody should fill in.
    """
    with pytest.raises(exports.ExportError) as caught:
        exports.parse(config(), source_type="rest", schema=ORDERS)
    assert "webhook" in str(caught.value)


def test_an_unknown_source_type_is_refused_too() -> None:
    # The absence half of the two above: without it, both pass against an
    # implementation that accepts anything not named `rest`.
    with pytest.raises(exports.ExportError):
        exports.parse(config(), source_type="kafka", schema=ORDERS)


def test_the_destination_map_matches_what_the_connectors_implement() -> None:
    """**Compared against the connectors, not against a second list** (§191).

    `DESTINATIONS` says which source types can be an export destination and the
    connectors are what actually can. Two lists that agreed with each other
    would be free to be identically wrong; this compares the map to the methods
    that do the work, so adding `export_rows` without coming here - or naming a
    type here that cannot write - is what goes red.
    """
    from src.services import connectors

    for source_type, kind in exports.DESTINATIONS.items():
        connector = connectors.get_connector(source_type)
        needed = "export_rows" if kind == "table" else "export_file"
        assert hasattr(connector, needed), f"{source_type} has no {needed}"

    for source_type in connectors.list_source_types():
        name = source_type["type"]
        writes = hasattr(connectors.get_connector(name), "export_rows") or hasattr(
            connectors.get_connector(name), "export_file"
        )
        assert writes == (name in exports.DESTINATIONS), (
            f"{name} can write but is not in DESTINATIONS, or the reverse"
        )


# ---- the modes -------------------------------------------------------------------
def test_a_table_export_needs_a_mode() -> None:
    with pytest.raises(exports.ExportError) as caught:
        exports.parse(config(mode=None), source_type="postgres", schema=ORDERS)
    assert "mode" in str(caught.value)


def test_a_file_export_may_not_carry_one() -> None:
    """p.193 gives a file export one behaviour and no modes. A stored value
    nothing reads is §214's control that cannot work."""
    with pytest.raises(exports.ExportError):
        exports.parse(
            config(mode="mirror", destination={"prefix": "exports/"}),
            source_type="s3", schema=ORDERS,
        )


def test_the_absent_modes_are_absent_on_purpose() -> None:
    """**The four of p.195-196's six that this platform cannot mean.**

    Each of them is defined over a transaction log `dataset_versions` does not
    keep - "unexported *transactions* from the current view", or a `SNAPSHOT` /
    `APPEND` / `UPDATE` / `DELETE` transaction type. Decision 0014 §2 carries
    the table.

    This asserts the *absence*, which is the only way it stays a decision. A
    dropdown that grew "export incrementally" would offer a setting that could
    not do what its name says, and nothing else in the build would notice.
    """
    assert set(exports.MODES) == {"mirror", "full"}
    for absent in ("incremental", "incremental_truncate", "incremental_append_only"):
        assert absent not in exports.MODES
    # And every mode offered has a label, so a picker cannot show a bare enum.
    assert set(exports.MODE_LABELS) == set(exports.MODES)


# ---- p.197's refusals -------------------------------------------------------------
def test_a_struct_column_is_refused_when_the_export_is_configured() -> None:
    """p.197: "Array, Map, and Struct types are not supported for exports."

    At configuration time rather than run time, which is where Foundry puts it
    - a dataset's schema is known when somebody is filling in the form, and a
    refusal then is one they can act on without a failed run in between.
    """
    with pytest.raises(exports.ExportError) as caught:
        exports.parse(
            config(),
            source_type="postgres",
            schema=schema(("id", "BIGINT"), ("tags", "VARCHAR[]")),
        )
    assert "p.197" in str(caught.value)
    assert "tags" in str(caught.value)


def test_every_shape_duckdb_spells_a_nested_type_is_caught() -> None:
    """The parameterised forms, because those are the ones that actually occur.

    A membership test against the bare words `ARRAY`, `MAP`, `STRUCT` would
    match none of `STRUCT(a INTEGER)`, `INTEGER[]` or `MAP(VARCHAR, INTEGER)` -
    which is every real column of those types.
    """
    for data_type in ("STRUCT(a INTEGER, b VARCHAR)", "INTEGER[]",
                      "MAP(VARCHAR, INTEGER)", "VARCHAR[]", "UNION(a INTEGER)"):
        assert exports.unexportable_columns(schema(("c", data_type))) == ["c"]


def test_an_ordinary_column_is_not_refused() -> None:
    # The presence half. Without it every check above passes against an
    # implementation that refuses every column there is.
    assert exports.unexportable_columns(ORDERS) == []
    for data_type in ("VARCHAR", "BIGINT", "DOUBLE", "TIMESTAMP", "BOOLEAN", "DATE"):
        assert exports.unexportable_columns(schema(("c", data_type))) == []


def test_all_the_refused_columns_are_named_at_once() -> None:
    """A dataset with four struct columns should not need four round trips to
    find that out."""
    refused = exports.unexportable_columns(
        schema(("a", "STRUCT(x INTEGER)"), ("b", "VARCHAR"), ("c", "INTEGER[]"))
    )
    assert refused == ["a", "c"]


# ---- the 1:1 column check (p.197) --------------------------------------------------
def test_a_column_the_destination_lacks_is_reported() -> None:
    assert exports.missing_columns(ORDERS, ["id", "email"]) == ["total"]


def test_a_destination_column_the_dataset_lacks_is_not_a_problem() -> None:
    """Only one direction. A column the destination has and the dataset does
    not may have a default, or be filled by something else; a dataset column
    the destination lacks has nowhere to go."""
    assert exports.missing_columns(ORDERS, ["id", "email", "total", "created_at"]) == []


def test_the_comparison_is_case_sensitive_because_p197_says_so() -> None:
    """p.197: "including exact column names (case-sensitive)".

    **The surprising half, and the reason it is worth a test.** Postgres folds
    an unquoted identifier to lower case, so a destination column created as
    `CustomerId` is stored as `customerid`. Comparing case-insensitively here
    would let that export be created and fail at run time - which is the
    behaviour p.197 describes and this exists to avoid.
    """
    assert exports.missing_columns(schema(("Email", "VARCHAR")), ["email"]) == ["Email"]
    assert exports.missing_columns(schema(("email", "VARCHAR")), ["email"]) == []


# ---- p.192's nothing-to-export ------------------------------------------------------
def test_mirror_skips_a_version_it_has_already_written() -> None:
    """p.192: "exports with no new files or rows to be exported will be marked
    as success"."""
    assert exports.should_skip("mirror", last_version=7, current_version=7) is True


def test_mirror_does_not_skip_a_new_version() -> None:
    # The presence half, and the one that matters: without it the check above
    # passes against an export that never writes anything at all.
    assert exports.should_skip("mirror", last_version=6, current_version=7) is False


def test_an_export_that_has_never_run_does_not_skip() -> None:
    assert exports.should_skip("mirror", last_version=None, current_version=1) is False


def test_full_never_skips_and_that_is_p195_not_an_oversight() -> None:
    """p.195 says the mode is for "external systems [that] consume and remove
    rows after each run", so there is always something new to export - the
    destination emptied itself. A `full` export that skipped would be a queue
    that stopped being fed, and the skip would look like a bug in whatever was
    consuming it."""
    assert exports.should_skip("full", last_version=7, current_version=7) is False
    assert exports.should_skip("full", last_version=99, current_version=1) is False


def test_a_file_export_skips_an_unchanged_version() -> None:
    """p.193: "only files that were modified since the last successfully
    exported transaction on the upstream dataset will be written." One file per
    version here, so "modified" means "the version changed"."""
    assert exports.should_skip(None, last_version=3, current_version=3) is True
    assert exports.should_skip(None, last_version=3, current_version=4) is False


def test_only_mirror_truncates() -> None:
    assert exports.truncates("mirror") is True
    assert exports.truncates("full") is False
    assert exports.truncates(None) is False


# ---- the destination fields (p.197) --------------------------------------------------
def test_a_table_export_needs_a_table() -> None:
    with pytest.raises(exports.ExportError):
        exports.parse(
            config(destination={"schema": "public"}), source_type="postgres", schema=ORDERS
        )


def test_a_schema_is_optional_because_not_every_source_needs_one() -> None:
    """p.197: "ensure that DATABASE, SCHEMA, and TABLE fields are filled out
    **if required by your source**"."""
    parsed = exports.parse(
        config(destination={"table": "orders"}), source_type="mysql", schema=ORDERS
    )
    assert parsed["destination"] == {"schema": "", "table": "orders"}


def test_unknown_destination_fields_are_dropped_rather_than_stored() -> None:
    """p.197: "**including unnecessary fields can also result in failure**".

    A field nobody reads is a field somebody will believe in.
    """
    parsed = exports.parse(
        config(destination={"table": "orders", "database": "prod", "nonsense": 1}),
        source_type="postgres", schema=ORDERS,
    )
    assert set(parsed["destination"]) == {"schema", "table"}


def test_something_that_is_not_an_identifier_is_refused() -> None:
    for table in ("orders; DROP TABLE x", "orders table", '"orders"', "1orders", ""):
        with pytest.raises(exports.ExportError):
            exports.parse(
                config(destination={"table": table}),
                source_type="postgres", schema=ORDERS,
            )


def test_a_file_export_needs_a_path_and_may_not_climb_out_of_it() -> None:
    with pytest.raises(exports.ExportError):
        exports.parse(
            config(mode=None, destination={"prefix": ""}), source_type="s3", schema=ORDERS
        )
    with pytest.raises(exports.ExportError):
        exports.parse(
            config(mode=None, destination={"prefix": "../elsewhere"}),
            source_type="s3", schema=ORDERS,
        )


def test_a_leading_slash_is_taken_off_rather_than_refused() -> None:
    """A path typed with a leading slash means the same thing, and refusing it
    would be refusing a convention rather than a mistake."""
    parsed = exports.parse(
        config(mode=None, destination={"prefix": "/exports/orders"}),
        source_type="s3", schema=ORDERS,
    )
    assert parsed["destination"]["prefix"] == "exports/orders"


# ---- names ---------------------------------------------------------------------------
def test_an_export_needs_a_name() -> None:
    for name in ("", "   ", "x" * (exports.MAX_NAME + 1)):
        with pytest.raises(exports.ExportError):
            exports.parse(config(name=name), source_type="postgres", schema=ORDERS)


def test_a_name_is_trimmed() -> None:
    parsed = exports.parse(
        config(name="  Nightly  "), source_type="postgres", schema=ORDERS
    )
    assert parsed["name"] == "Nightly"


# ---- what a list says ------------------------------------------------------------------
def test_a_summary_says_which_way_round_the_mode_is() -> None:
    """`mirror` and `full` differ in exactly one observable way and it is the
    one somebody needs from a list: whether last run's rows are still there."""
    assert exports.summarise(
        {"kind": "table", "mode": "mirror", "destination": {"schema": "public", "table": "orders"}}
    ) == "replaces public.orders"
    assert exports.summarise(
        {"kind": "table", "mode": "full", "destination": {"schema": "", "table": "orders"}}
    ) == "appends to orders"
    assert exports.summarise(
        {"kind": "file", "destination": {"prefix": "exports/orders"}}
    ) == "files to exports/orders"


def test_the_browser_offers_exactly_the_destinations_the_server_accepts() -> None:
    """**The browser's copy of `DESTINATIONS`, compared against this one.**

    `apps/web/src/lib/export-form.ts` has to know which sources can be a
    destination, because the picker is built from it — and §191's rule is that
    two copies of a list are two chances to be identically wrong. The browser's
    own test compares that map to a literal, which is a copy checked against a
    copy; this is the one that compares it to the thing it mirrors.

    Read out of the TypeScript rather than duplicated here, so the failure is
    "the two disagree" rather than "somebody forgot to update a third place".
    The same argument `test_egress.py` makes for the worker's copy, at the one
    boundary where the languages differ and a shared module is not available.
    """
    import re

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source = open(
        os.path.join(root, "web", "src", "lib", "export-form.ts"), encoding="utf-8"
    ).read()
    block = re.search(
        r'DESTINATIONS: Record<string, "table" \| "file"> = \{(.*?)\}', source, re.S
    )
    assert block, "could not find DESTINATIONS in export-form.ts - has it been renamed?"
    theirs = dict(re.findall(r'(\w+):\s*"(table|file)"', block.group(1)))
    assert theirs, "DESTINATIONS parsed to nothing - the regex has gone stale"
    assert theirs == exports.DESTINATIONS, (
        "the export form offers different destinations from the ones the server "
        f"accepts: browser={theirs}, server={exports.DESTINATIONS}"
    )
