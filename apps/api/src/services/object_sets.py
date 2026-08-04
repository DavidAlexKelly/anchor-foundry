"""Object sets: the variable kind Workshop is actually built on.

Roadmap phase 2, item 1.2, and the part of it the roadmap calls the thing that
"decides whether Workshop parity is real". Everything a Workshop app does with
the ontology is a set: a Filter List narrows one, an Object Table pages
through one, a chart groups one, a Metric Card aggregates one - and all of them
read the *same* set, which is why it has to be one evaluated thing rather than
each widget filtering its own copy.

**Why this is server-side.** Canvas filters a page of at most 200 rows in the
browser (`filter-sql.ts`, STATUS.md §36). That is fine for narrowing what is
already on screen and wrong for everything else: "how many are there" and
"show me the next page of the filtered set" cannot be answered from a page.
A set is a query, and a query belongs where the data is.

**A definition, not a result.** What a variable holds is the *description* of a
set - a type plus filters - which is small, serialisable, and stable across
viewers. The rows come from evaluating it. Storing rows in a variable would
make a saved app a saved session, which decision 0002 rules out for exactly
this reason.

Aggregations arrived with roadmap 1.5 (`AGGREGATIONS`, `MAX_GROUPS`), and are
deliberately only the two that mean the same thing in both stores over untyped
properties. The rest are refused with a sentence rather than picked - see
`NUMERIC_AGGREGATIONS`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

# The operators a filter may use. Deliberately short: every one of these has
# the same meaning in both stores. An operator that behaved differently on
# Postgres and OpenSearch would make an app's results depend on which store the
# deployment happens to run, which is the worst kind of difference - invisible
# until somebody compares two environments.
OPERATORS = ("eq", "neq", "in", "starts_with")

# Ordered comparison is **not** in that list, and the reason is worth keeping.
# Instance properties are stored untyped - a jsonb blob in Postgres, a
# dynamically-mapped text field in OpenSearch - so `capacity > 40` has two
# defensible readings: numeric (250 > 40) and lexicographic ("250" < "40").
# Postgres can cast; OpenSearch compares the indexed text. The first
# implementation shipped both and the cross-store test caught them disagreeing
# on the first run.
#
# Refused rather than picked, because either choice is wrong somewhere: a
# numeric-only reading breaks dates and codes, and a lexicographic one is
# indefensible to anyone filtering a number. Doing it properly means honouring
# the *declared* property type (object_type_properties.data_type, db 0026) and
# indexing accordingly - a mapping change with a backfill behind it, which is
# its own item rather than a footnote in this one.
ORDERED_OPERATORS = ("gt", "gte", "lt", "lte")

# `starts_with` rather than `contains`, and for a related reason. A substring
# match is `ILIKE '%x%'` on Postgres and a wildcard query on OpenSearch, which
# cannot use the index - fine on a hundred rows and pathological on a million,
# which is the exact cost server-side evaluation exists to avoid. A prefix is
# indexable on both. The cross-store test caught this too: the first
# implementation paired Postgres substring with OpenSearch `phrase_prefix`, so
# "los" matched "closed" on one store and not the other.

# Operators whose value is a list rather than a scalar.
LIST_OPERATORS = ("in",)

# How a page of a set may be ordered (roadmap 1.5, the Object Table upgrade).
#
# Four, and **none of them sorts by a property**, which is the same refusal
# `ORDERED_OPERATORS` makes and for exactly the same reason: properties are
# stored untyped, so ordering by one means choosing between "250 comes after
# 40" and "250 comes before 40" on the caller's behalf, and the two stores
# would choose differently. A table sorted one way on Postgres and another on
# OpenSearch is the invisible kind of wrong.
#
# What is here is what both stores can order identically without knowing any
# property's type: the primary key, which is text on both, and `updated_at`,
# which is a real timestamp column on one and an indexed date on the other.
SORTS = ("key", "-key", "recent", "oldest")
DEFAULT_SORT = "recent"

# Named so the refusal can say what it would take, rather than only "no".
PROPERTY_SORT_HINT = (
    "sorting by a property needs the declared property type behind it - instance "
    "properties are stored untyped, so the two stores would order 250 and 40 "
    "differently. Sort by key or by when a row last changed."
)


def parse_sort(sort: Any) -> str:
    """Validate a sort, refusing in a sentence somebody can act on."""
    if sort is None or sort == "":
        return DEFAULT_SORT
    if not isinstance(sort, str):
        raise ValueError("sort must be a string")
    if sort in SORTS:
        return sort
    raise ValueError(f"unknown sort {sort!r} (supported: {', '.join(SORTS)}). {PROPERTY_SORT_HINT}")

# What a Metric Card can ask of a set (roadmap 1.5).
#
# Both of these are *text-identity* operations - how many documents, and how
# many distinct values of one property - so Postgres and OpenSearch agree
# without either of them knowing what the property's type is. Postgres counts
# distinct `jsonb_extract_path_text`; OpenSearch runs a cardinality aggregation
# on the `.keyword` subfield the index mapping declares explicitly. Same
# question, same answer.
AGGREGATIONS = ("count", "count_distinct")

# `sum`, `avg`, `min` and `max` are **not** here, and it is the same reason
# ordered operators are not: instance properties are stored untyped, so
# summing one means deciding what "3" and "10" are without being told. Postgres
# would cast; OpenSearch cannot aggregate numerically over a text-mapped field
# at all. Shipping it would mean a Metric Card whose number is right on one
# deployment and absent on another - which is worse than a card that says the
# platform cannot answer yet.
#
# The fix is the same one too, and doing it once unlocks both: honour the
# *declared* property type (object_type_properties.data_type, db 0026) in the
# index mapping, with a backfill behind it.
NUMERIC_AGGREGATIONS = ("sum", "avg", "min", "max")


# The most buckets a grouped count will return. A chart with three hundred
# bars is not a chart, and an unbounded group-by over a large set is a real
# cost on both stores. The caller is told when it truncated - a chart showing
# the top 20 of 300 without saying so is the same trap as a sampled preview
# that does not say it sampled.
MAX_GROUPS = 20

MAX_FILTERS = 20


def parse_aggregation(name: str, property_name: str | None) -> tuple[str, str | None]:
    """Validate an aggregation, refusing in a sentence."""
    if name in NUMERIC_AGGREGATIONS:
        raise ValueError(
            f"{name} is not supported yet: instance properties are stored untyped, so "
            f"a {name} would mean one thing on Postgres and nothing at all on "
            "OpenSearch. count and count_distinct answer the same question about how "
            "many, and agree on both."
        )
    if name not in AGGREGATIONS:
        raise ValueError(
            f"unknown aggregation {name!r}; expected one of {', '.join(AGGREGATIONS)}"
        )
    if name == "count_distinct" and not property_name:
        raise ValueError("count_distinct needs a property to count distinct values of")
    return name, property_name if name == "count_distinct" else None


@dataclass(frozen=True)
class Filter:
    property: str
    op: str
    value: Any


@dataclass(frozen=True)
class ObjectSet:
    """A set of instances of one object type, narrowed by filters.

    One type, not several. A set spanning types has no coherent property
    vocabulary to filter on, and every Workshop widget that consumes a set
    (table columns, chart axes, card properties) is configured against one
    type's properties.
    """

    object_type_id: UUID
    filters: tuple[Filter, ...] = ()


def parse(definition: dict[str, Any]) -> ObjectSet:
    """Validate a set definition, refusing in a sentence.

    Refusals are read by somebody building an app, not by a client library, so
    they name the offending value and the alternatives (STATUS.md §52).
    """
    if not isinstance(definition, dict):
        raise ValueError("an object set definition must be an object")
    raw_type = definition.get("object_type_id")
    if not raw_type:
        raise ValueError("an object set needs an object_type_id")
    try:
        object_type_id = UUID(str(raw_type))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{raw_type!r} is not a valid object type id") from exc

    raw_filters = definition.get("filters") or []
    if not isinstance(raw_filters, list):
        raise ValueError("filters must be a list")
    if len(raw_filters) > MAX_FILTERS:
        raise ValueError(f"an object set may carry at most {MAX_FILTERS} filters")

    filters: list[Filter] = []
    for entry in raw_filters:
        if not isinstance(entry, dict):
            raise ValueError("each filter must be an object")
        prop = entry.get("property")
        if not prop or not isinstance(prop, str):
            raise ValueError("each filter needs a property name")
        op = entry.get("op", "eq")
        if op in ORDERED_OPERATORS:
            raise ValueError(
                f"the {op!r} operator is not supported yet: instance properties are stored "
                "untyped, so an ordered comparison would mean 250 > 40 on one store and "
                '"250" < "40" on the other. It needs the declared property type behind it.'
            )
        if op not in OPERATORS:
            raise ValueError(
                f"unknown filter operator {op!r} (supported: {', '.join(OPERATORS)})"
            )
        value = entry.get("value")
        if op in LIST_OPERATORS:
            if not isinstance(value, list) or not value:
                raise ValueError(f"the {op!r} operator needs a non-empty list of values")
        elif isinstance(value, (list, dict)):
            raise ValueError(f"the {op!r} operator takes a single value, not a list")
        elif value is None:
            # Refused rather than treated as "no filter". A filter bound to a
            # variable nobody has set yet must not silently widen the set -
            # that is precisely the failure decision 0002 documented, where a
            # missing parameter made a map show *more* rows than it should.
            # The caller drops the filter; it does not send an empty one.
            raise ValueError(
                f"filter on {prop!r} has no value - omit the filter rather than "
                "sending an empty one, so an unset variable cannot silently widen the set"
            )
        filters.append(Filter(property=prop, op=op, value=value))

    return ObjectSet(object_type_id=object_type_id, filters=tuple(filters))


def matches(properties: dict[str, Any], filters: tuple[Filter, ...]) -> bool:
    """Whether one instance satisfies every filter.

    Shared by both stores so "does this row match" has exactly one definition.
    The Postgres store evaluates in SQL and OpenSearch in its query DSL, but
    both are checked against this in tests - a set that means two things is
    worse than a set that is slow.
    """
    for f in filters:
        actual = properties.get(f.property)
        if not _matches_one(actual, f):
            return False
    return True


def _matches_one(actual: Any, f: Filter) -> bool:
    if f.op == "eq":
        return _text(actual) == _text(f.value)
    if f.op == "neq":
        return _text(actual) != _text(f.value)
    if f.op == "in":
        return _text(actual) in {_text(v) for v in f.value}
    if f.op == "starts_with":
        return actual is not None and _text(actual).lower().startswith(_text(f.value).lower())
    # Unreachable while `parse` is the only way to build a Filter, which it is.
    raise ValueError(f"no reference semantics for operator {f.op!r}")


def _text(value: Any) -> str:
    """Comparison is on the text of a value, the same rule links already use
    (`instance_store.join_key`). Two independently-mapped sources can perfectly
    well disagree about whether a code is a string or a number, and a
    type-strict comparison would find nothing in exactly the case a filter
    exists for."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
