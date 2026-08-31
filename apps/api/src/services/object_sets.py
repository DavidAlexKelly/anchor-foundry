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
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:  # this module imports nothing at runtime, on purpose
    from collections.abc import Mapping

# The operators a filter may use. Deliberately short: every one of these has
# the same meaning in both stores. An operator that behaved differently on
# Postgres and OpenSearch would make an app's results depend on which store the
# deployment happens to run, which is the worst kind of difference - invisible
# until somebody compares two environments.
OPERATORS = ("eq", "neq", "in", "starts_with")

# A filter may address the instance's **primary key** as well as a property,
# under this name. It is `ontology.PRIMARY_KEY_REF`, restated here so this
# module keeps importing nothing - the two are asserted equal by a test.
#
# It exists because half of every link lands on one: migration 0027's join is
# "the *from* side holds the foreign key", so traversing towards the *to* side
# matches against that side's key rather than against a property. Without this
# a traversal would work in one direction and be refused in the other, which is
# not a feature - it is half of one.
PRIMARY_KEY_FILTER = "$primary_key"

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
# indefensible to anyone filtering a number.
#
# **Allowed now, for the types whose order both stores agree on** (§221). The
# answer was always "honour the *declared* property type", and §220 built what
# that needs: one index per object type, mapped from the ontology, so a
# `capacity` declared `integer` is a `long` in OpenSearch and a cast in
# Postgres rather than two readings of the same text. An ordered comparison on
# a property that is **not** declared orderable is still refused, in the same
# sentence as before - and a caller that does not supply the declared types at
# all gets the old refusal for everything, because a filter validated without
# them is one nothing has checked the types of.
ORDERED_OPERATORS = ("gt", "gte", "lt", "lte")

# Which declared types an ordered comparison may be asked of.
#
# **Restated rather than imported**, the same way `PRIMARY_KEY_FILTER` is: this
# module keeps importing nothing, and a test asserts the two copies agree. The
# original is `instance_mapping.ORDERABLE_TYPES`, where it is true *because* of
# the mapping - a `date` field is orderable because it is mapped `date`.
#
# `string` is absent permanently, not pending (decision 0006 §2): lexicographic
# order is the database collation on Postgres and byte order on OpenSearch, so
# `'Z' < 'a'` differs between them. Allowing `gt` on a string would reintroduce
# the exact class of bug this comment block exists to describe, one layer down
# and much harder to see.
ORDERABLE_TYPES = ("integer", "float", "date", "timestamp")

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
#
# Says which types it *would* cover, because decision 0006 settled that and the
# earlier wording implied every property would be sortable one day. A `string`
# property will not be: lexicographic order is the database collation on
# Postgres and byte order on OpenSearch, so 'Z' < 'a' differs between them -
# which is the same disagreement this refusal exists to prevent, one layer down.
PROPERTY_SORT_HINT = (
    "sorting by a property needs the declared property type behind it - instance "
    "properties are stored untyped, so the two stores would order 250 and 40 "
    "differently (docs/decisions/0006-typed-instance-properties.md). It will cover "
    "integer, float, date and timestamp properties; text will stay unsortable, "
    "because the two stores disagree about how text orders. Sort by key or by when "
    "a row last changed."
)


def parse_sort(
    sort: Any, *, property_types: "Mapping[str, str] | None" = None
) -> "Sort":
    """Validate a sort, refusing in a sentence somebody can act on.

    Beyond the four fixed sorts, a **property sort** is `name` or `-name` for a
    property whose declared type has an order both stores agree on (§221). The
    leading `-` is descending, matching `-key`, which is the shape every caller
    in this codebase already writes.

    `property_types` is optional for the same reason it is on `parse`: a caller
    that has not resolved the ontology has checked no type, so it gets the four
    fixed sorts and the refusal that names what a property sort would need.
    """
    if sort is None or sort == "":
        return Sort()
    if not isinstance(sort, str):
        raise ValueError("sort must be a string")
    if sort in SORTS:
        return Sort(key=sort)
    if property_types is not None:
        descending = sort.startswith("-")
        name = sort[1:] if descending else sort
        declared = property_types.get(name)
        if declared in ORDERABLE_TYPES:
            return Sort(key=sort, property=name, descending=descending, data_type=declared)
        if declared is not None:
            raise ValueError(
                f"{name!r} is a {declared} property, and a sort needs one of "
                f"{', '.join(ORDERABLE_TYPES)}. " + (
                    "Text has no order the two stores agree on - Postgres orders by "
                    "the database collation and OpenSearch by byte order."
                    if declared == "string"
                    else f"A {declared} has no order anybody would agree on."
                )
            )
    raise ValueError(
        f"unknown sort {sort!r} (supported: {', '.join(SORTS)}). {PROPERTY_SORT_HINT}"
    )


@dataclass(frozen=True)
class Sort:
    """A validated page ordering, with the declared type it orders by.

    **A value object rather than a string, for the reason `Filter.data_type`
    is a field**: the decision that this ordering is legal was made once, in
    `parse_sort`, against the ontology the caller resolved. A store that looked
    the property's type up again could reach a different answer than the
    validation did.

    `property` is `None` for the four fixed sorts, which need no type: the
    primary key is text on both stores and `updated_at` is a real timestamp on
    one and an indexed date on the other.
    """

    key: str = DEFAULT_SORT
    property: str | None = None
    descending: bool = False
    data_type: str | None = None

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
# *declared* property type (object_type_properties.data_type, db 0003) in the
# index mapping, with a backfill behind it.
NUMERIC_AGGREGATIONS = ("sum", "avg", "min", "max")


# The most buckets a grouped count will return. A chart with three hundred
# bars is not a chart, and an unbounded group-by over a large set is a real
# cost on both stores. The caller is told when it truncated - a chart showing
# the top 20 of 300 without saying so is the same trap as a sampled preview
# that does not say it sampled.
MAX_GROUPS = 20

# A cross-tab's column axis is bounded harder than its row axis, and for a
# different reason. Rows scroll; columns do not. Twenty columns of numbers is
# not a grid anybody reads, and it is the axis a viewer cannot get to the end
# of - so the top 12 with the truncation said out loud beats 20 that run off
# the side. The cost is bounded either way: the cell query is at most
# MAX_GROUPS x MAX_PIVOT_COLUMNS buckets.
MAX_PIVOT_COLUMNS = 12

MAX_FILTERS = 20

# How many hops a set definition may traverse (parity `ontology.md` §3; needed
# by `workshop.md` §3.1's "Object set definition - object types, filters, link
# traversals").
#
# Each hop is a **full evaluation of the set below it**: to know which orders
# belong to these customers, the customers have to be found first. So depth is
# not free the way a filter is, and a definition ten hops deep would be ten
# queries a viewer never asked for and cannot see. Three is enough for
# "customers → orders → items", which is the shape anybody actually draws.
MAX_TRAVERSALS = 3

# How many distinct join values one hop may carry.
#
# **A traversal resolves to an `in` filter** over the values the near side
# holds (see `join_filter`), which is why this bound exists and why it is not
# the same as a row limit: a base set of a hundred thousand objects becomes a
# hundred thousand `in` terms, on either store, and that is a query nobody
# wants to have generated by accident. Refused with a sentence naming the
# number rather than silently truncated - a set quietly missing its tail is
# the failure that looks like working software.
MAX_JOIN_VALUES = 1000

# ---- a set over time (roadmap 1.5, what a Time Series plots) -----------------
#
# **Over `updated_at`, and only over `updated_at`.** That is the same short list
# `SORTS` is drawn from and for the same reason: it is a real `timestamptz` on
# Postgres and a mapped `date` on OpenSearch, so both stores bucket it
# identically without being told what any property's type is. A *date property*
# is stored untyped like every other, so bucketing one means guessing whether
# "03/04" is March or April - see `DATE_PROPERTY_HINT`.
TIME_INTERVALS = ("day", "week", "month")
DEFAULT_TIME_INTERVAL = "day"

# The most points a series will return. A chart with a thousand points is a
# smear, and an unbounded date histogram over a long-lived set is a real cost
# on both stores. Exceeding it **refuses and names a coarser interval** rather
# than truncating: a truncated time series is not a smaller answer, it is a
# different period, and nothing on screen would say which one.
MAX_TIME_BUCKETS = 200

DATE_PROPERTY_HINT = (
    "a time series over a date *property* needs the declared property type behind it - "
    "instance properties are stored untyped, so the two stores would bucket the same "
    "value differently (docs/decisions/0006-typed-instance-properties.md). This plots "
    "when each object last changed, which both stores agree about."
)


def parse_interval(interval: Any) -> str:
    """Validate a bucket size, refusing in a sentence."""
    if interval is None or interval == "":
        return DEFAULT_TIME_INTERVAL
    if not isinstance(interval, str):
        raise ValueError("interval must be a string")
    if interval not in TIME_INTERVALS:
        raise ValueError(
            f"unknown interval {interval!r} (supported: {', '.join(TIME_INTERVALS)})"
        )
    return interval


def next_bucket(start: datetime, interval: str) -> datetime:
    """The start of the bucket after this one.

    Calendar arithmetic, not a fixed number of seconds: a month is 28-31 days
    and this has to land on the same instants `date_trunc` and
    `calendar_interval` produce, or the filled gaps would sit between the real
    buckets rather than among them.
    """
    if interval == "day":
        return start + timedelta(days=1)
    if interval == "week":
        return start + timedelta(days=7)
    if interval == "month":
        return start.replace(year=start.year + start.month // 12,
                             month=start.month % 12 + 1, day=1)
    raise ValueError(f"unknown interval {interval!r}")  # pragma: no cover


def fill_time_buckets(
    buckets: list[tuple[datetime, int]], interval: str
) -> list[tuple[datetime, int]]:
    """Every bucket from the first to the last, empty ones included.

    **Both stores return only the buckets that have rows**, and a line drawn
    through the gaps would slope smoothly across a week when nothing happened -
    which is not a smaller claim than the truth, it is a different one. Filled
    here rather than in either store so the two cannot fill differently, and
    rather than in the browser so a chart and a CSV of the same series agree.

    The range is the data's own first and last bucket. Not "the last 30 days":
    that would make the same saved app draw a different picture tomorrow with
    no change to anything it points at.
    """
    if not buckets:
        return []
    ordered = sorted(buckets)
    counts = dict(ordered)
    out: list[tuple[datetime, int]] = []
    cursor, last = ordered[0][0], ordered[-1][0]
    while cursor <= last:
        out.append((cursor, counts.get(cursor, 0)))
        cursor = next_bucket(cursor, interval)
        if len(out) > MAX_TIME_BUCKETS:
            raise ValueError(
                f"that range is more than {MAX_TIME_BUCKETS} {interval} buckets. Use a "
                "coarser interval - a truncated time series is a different period, not "
                "a shorter one."
            )
    return out


def parse_cross_tab(row_property: str, column_property: str) -> tuple[str, str]:
    """Validate a cross-tab's two axes, refusing in a sentence.

    One property against itself is refused rather than drawn. It is not
    ill-defined - it is a diagonal, every off-diagonal cell empty - but it is a
    grouped count wearing a grid's clothes, and `/object-sets/group` already
    answers that question in a shape somebody can read.
    """
    if not row_property or not column_property:
        raise ValueError("a cross-tab needs a row property and a column property")
    if row_property == column_property:
        raise ValueError(
            f"a cross-tab of {row_property!r} against itself is its own diagonal: every "
            "cell off it is empty, and the counts on it are what grouping by that one "
            "property already gives. Pick a second property, or use a chart."
        )
    return row_property, column_property


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
    # The property's **declared** type, for an ordered comparison (§221).
    #
    # Carried on the filter rather than looked up by each store, because the
    # decision that this comparison is legal was made once, in `parse`, against
    # the ontology the caller resolved. A store that looked the type up again
    # could reach a different answer than the validation did - which is the
    # two-implementations problem this whole area exists to avoid, moved one
    # level down.
    #
    # `None` for every equality-shaped operator, which need no type: they
    # compare the *text* of a value (`_text`), the same rule links already use.
    data_type: str | None = None


@dataclass(frozen=True)
class ObjectSet:
    """A set of instances of one object type, narrowed by filters.

    One type, not several. A set spanning types has no coherent property
    vocabulary to filter on, and every Workshop widget that consumes a set
    (table columns, chart axes, card properties) is configured against one
    type's properties.

    `via` makes the set the *far side of a link* from another set - "the orders
    belonging to these customers". The type is still one type; what changes is
    where the members come from.
    """

    object_type_id: UUID
    filters: tuple[Filter, ...] = ()
    via: "Traversal | None" = None

    @property
    def depth(self) -> int:
        """How many hops below this set, for the limit and for saying so."""
        return 0 if self.via is None else 1 + self.via.base.depth


@dataclass(frozen=True)
class Traversal:
    """One hop: follow a link type from the set below to this one.

    **The link type, not a pair of properties.** A link already names both
    ends (migration 0027: "which instances of the far type have `to_property`
    equal to this instance's `from_property`"), so a definition that restated
    them would be a second copy of the join, free to disagree with the ontology
    the moment somebody edits it.

    Which *end* is near is not stored either: it follows from the type of the
    set below, and `ontology.links_for_type` already answers it per end. A
    definition that named the direction would be able to name the wrong one.
    """

    link_type_id: UUID
    base: ObjectSet


def object_type_id_of(definition: Any) -> UUID:
    """Just the object type an unvalidated definition names.

    **A pre-parse, and it exists because validation now needs the ontology.**
    An ordered comparison is checked against the declared property types
    (§221), and reading those needs to know which type's properties to read -
    which is in the definition being validated. So the id comes out first, the
    caller resolves the types, and `parse` gets both.

    Kept to *only* the id: everything else this function could check would be a
    second copy of a rule `parse` states, free to drift from it.
    """
    if not isinstance(definition, dict):
        raise ValueError("an object set definition must be an object")
    raw = definition.get("object_type_id")
    if not raw:
        raise ValueError("an object set needs an object_type_id")
    try:
        return UUID(str(raw))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{raw!r} is not a valid object type id") from exc


def _orderable_type(
    prop: str, op: str, property_types: "Mapping[str, str] | None"
) -> str:
    """The declared type an ordered comparison may use, or a refusal (§221).

    Three different refusals, because they are three different mistakes and
    only one of them is the caller's to fix by changing the filter:

    * **No declared types supplied at all.** The caller did not resolve the
      ontology, so nothing has checked this property's type — and validating an
      ordered comparison without that is the untyped comparison decision 0006
      refuses. Every pre-§221 caller lands here and keeps its old behaviour.
    * **A property the type does not declare.** Almost always a typo, and the
      old code could not tell it from a legal one.
    * **A property whose type has no agreed order** — `string` above all, which
      is refused permanently rather than pending (0006 §2).
    """
    if property_types is None:
        raise ValueError(
            f"the {op!r} operator needs the declared property types, and this caller "
            "did not supply them - an ordered comparison over untyped values means "
            '250 > 40 on one store and "250" < "40" on the other'
        )
    declared = property_types.get(prop)
    if declared is None:
        raise ValueError(
            f"the {op!r} operator names {prop!r}, which this object type does not declare"
        )
    if declared not in ORDERABLE_TYPES:
        raise ValueError(
            f"{prop!r} is a {declared} property, and {op!r} needs one of "
            f"{', '.join(ORDERABLE_TYPES)}. "
            + (
                "Text has no order the two stores agree on - Postgres orders by the "
                "database collation and OpenSearch by byte order, so 'Z' < 'a' is true "
                "in one and false in the other. Derive an orderable property instead."
                if declared == "string"
                else f"A {declared} has no order anybody would agree on."
            )
        )
    return declared


def parse(
    definition: dict[str, Any],
    *,
    property_types: "Mapping[str, str] | None" = None,
) -> ObjectSet:
    """Validate a set definition, refusing in a sentence.

    Refusals are read by somebody building an app, not by a client library, so
    they name the offending value and the alternatives (STATUS.md §52).

    `property_types` maps an api_name to its declared `data_type`, and is what
    an ordered comparison is checked against (§221). **Optional, and its
    absence is a refusal rather than a permission**: a caller that has not
    resolved the ontology has not checked any type, so it gets the pre-§221
    behaviour of refusing every ordered operator.
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
        data_type: str | None = None
        if op in ORDERED_OPERATORS:
            data_type = _orderable_type(prop, op, property_types)
        elif op not in OPERATORS:
            raise ValueError(
                f"unknown filter operator {op!r} "
                f"(supported: {', '.join((*OPERATORS, *ORDERED_OPERATORS))})"
            )
        value = entry.get("value")
        if op in LIST_OPERATORS:
            if not isinstance(value, list):
                raise ValueError(f"the {op!r} operator needs a list of values")
            # **An empty list is the empty set, and is allowed.** This refused
            # it once, alongside the `None` case below and for what looked like
            # the same reason. It is not the same reason, and the difference is
            # the direction: a missing value must not *widen* a set, because
            # that is decision 0002's failure - a map showing more rows than it
            # should because a parameter was unset. `in []` narrows, to
            # nothing, which is the safe direction and the only honest reading
            # of "is a member of no values".
            #
            # It has to be expressible, because otherwise a widget whose output
            # is a selection has no value for "nothing is selected" (p.224's
            # Selected objects). Every alternative available to such a widget -
            # omitting the filter, leaving the variable unset - hands
            # downstream widgets the *whole* set, which is exactly the failure
            # the refusal below exists to prevent. Keeping the refusal here
            # causes the bug it was written against.
            #
            # Both stores already agree: Postgres `= ANY(ARRAY[])` is false and
            # OpenSearch `terms: []` matches nothing, as does `matches`.
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
        filters.append(
            Filter(property=prop, op=op, value=value, data_type=data_type)
        )

    raw_via = definition.get("via")
    via: Traversal | None = None
    if raw_via is not None:
        if not isinstance(raw_via, dict):
            raise ValueError("`via` must be an object naming a link type and a base set")
        raw_link = raw_via.get("link_type_id")
        if not raw_link:
            raise ValueError("a traversal needs a link_type_id")
        try:
            link_type_id = UUID(str(raw_link))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError(f"{raw_link!r} is not a valid link type id") from exc
        raw_base = raw_via.get("base")
        if not isinstance(raw_base, dict):
            raise ValueError("a traversal needs a base set to traverse from")
        via = Traversal(link_type_id=link_type_id, base=parse(raw_base))

    result = ObjectSet(object_type_id=object_type_id, filters=tuple(filters), via=via)
    if result.depth > MAX_TRAVERSALS:
        raise ValueError(
            f"an object set may traverse at most {MAX_TRAVERSALS} links and this one "
            f"traverses {result.depth} - each hop evaluates the set below it, so depth "
            "costs a query a viewer never asked for"
        )
    return result


def join_filter(*, far_property: str, values: list[Any]) -> Filter | None:
    """The filter that *is* a traversal, given the near side's join values.

    **A hop compiles to an `in` filter**, which is the whole implementation
    trick and worth stating: `in` already means the same thing on Postgres and
    OpenSearch (it is in `OPERATORS` for that reason), so a traversal needs no
    new store capability and cannot introduce the cross-store disagreement the
    ordered operators were refused over.

    `None` means **the empty set**, not "no filter". A base set with no members
    links to nothing, and returning an unfiltered set there would be the
    silent-widening failure decision 0002 exists to remove - the same reason a
    filter with no value is refused above. Callers must treat `None` as "stop,
    the answer is empty" rather than as "nothing to apply".

    Values are de-duplicated and their order fixed, so the same set produces
    the same query and a cache key over it means something.
    """
    seen: list[Any] = []
    known: set[str] = set()
    for value in values:
        if value is None:
            # An object whose join property is empty is linked to nothing.
            # Including it would match far-side rows whose property is also
            # empty, which is not a link - it is two absences.
            continue
        key = _text(value)
        if key in known:
            continue
        known.add(key)
        seen.append(value)
    if not seen:
        return None
    if len(seen) > MAX_JOIN_VALUES:
        raise ValueError(
            f"this traversal starts from {len(seen)} distinct values and the limit is "
            f"{MAX_JOIN_VALUES} - narrow the set it traverses from first"
        )
    return Filter(property=far_property, op="in", value=sorted(seen, key=_text))


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
    if f.op in ORDERED_OPERATORS:
        return _compares(actual, f)
    # Unreachable while `parse` is the only way to build a Filter, which it is.
    raise ValueError(f"no reference semantics for operator {f.op!r}")


def _compares(actual: Any, f: Filter) -> bool:
    """An ordered comparison, in the declared type's own ordering (§221).

    **A value that does not fit its declared type does not match**, either way
    round. A `capacity` holding `"n/a"` is not greater than 40 and not less than
    40 - it is not on the number line at all, and the alternatives are both
    worse: sorting it to one end makes a filter silently include rows nobody
    asked for, and raising makes one bad row break a whole page.

    That is `NULL`'s behaviour in SQL and a missing field's in OpenSearch, so
    the two stores agree with this without being told to.
    """
    left = comparable(actual, f.data_type)
    right = comparable(f.value, f.data_type)
    if left is None or right is None:
        return False
    if f.op == "gt":
        return left > right
    if f.op == "gte":
        return left >= right
    if f.op == "lt":
        return left < right
    return left <= right


def comparable(value: Any, data_type: str | None) -> Any:
    """A value in the form its declared type orders by, or `None`.

    `None` means "this value has no place in that ordering" - a blank, a word
    where a number belongs, an unparseable date. Every caller treats that as
    "does not match" rather than as an error; see `_compares`.

    Exported because the OpenSearch store binds the *bound* of a range query
    through it, so the value a query carries is the one this definition
    compared. Postgres casts in SQL instead and is checked against this by the
    cross-store tests, which is the standard every operator in this file is
    held to.
    """
    if value is None or isinstance(value, bool):
        # A bool is not a number here even though Python says it is: `True > 0`
        # is not a question anybody filtering data meant to ask, and `boolean`
        # is not an orderable type (0006 §2).
        return None
    if data_type in ("integer", "float"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if data_type in ("date", "timestamp"):
        return _instant(value)
    return None


def _instant(value: Any) -> datetime | None:
    """An ISO-8601 date or timestamp as a comparable instant.

    **Naive and aware values are made comparable by assuming UTC for a naive
    one**, because Python refuses to compare the two and a source dataset
    routinely holds both - db 0029 stores "ISO-8601 text, with an offset
    preserved when the source has one", so the offset is present exactly when
    the source had one. A page that raised on the mixture would fail on real
    data for a reason no filter author could act on.

    A bare date is midnight UTC, which is what makes `date` and `timestamp` one
    ordering rather than two.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
