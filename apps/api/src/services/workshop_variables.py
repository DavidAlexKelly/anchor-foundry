"""The typed variable graph (roadmap phase 2, item 1.2; decision 0002).

Decision 0002 replaced Canvas's implicit, string-keyed parameter namespace with
*declared* variables. This is what makes that declaration mean something: it
validates the graph, computes derived values in dependency order, and answers
"what would break if I deleted this" by reading the document.

Three properties, and every one of them exists because its absence is what
Canvas does today (decision 0002, "what exists today, precisely"):

**A reference resolves or the save is refused.** Today a widget bound to a
parameter nothing declares reads as "no filter" - so the widget shows *more*
rows than it should, silently and forever. A dangling reference is not a state
this format has; it is a save that does not happen.

**A variable a widget uses cannot be deleted.** `usages()` reads the layout,
so "used by 2 widgets" is answerable, and the refusal names them.

**Derivations may not form a cycle.** Refused at save, the same way Models
item 7 refuses a transform DAG cycle (`STATUS.md` §30), and for a sharper
reason: there is no run loop to notice, so a cycle here is either an infinite
recompute in the browser or a value that depends on its own previous value -
which would make what an app shows depend on the order its variables happened
to be evaluated in.

**Values are never persisted** (decision 0002 §3). This module computes them
from inputs, per viewing. Nothing here writes.

Note on where this is called from: `services/canvas.py` still stores an opaque
blob and does not interpret it, which decision 0002 records as a property worth
keeping. Validation therefore lives in the *route*, before the blob is stored -
the API refuses the document, the storage layer stays uninterested in what is
inside it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

KINDS = (
    "string",
    "number",
    "boolean",
    "date",
    "timestamp",
    "array",
    "single_object",
    "object_set",
    # > "Time series set: Stores a time series property of a single object,
    # > optionally allowing the application of time series transforms to it."
    # > (`foundry_workshop` p.76; the feature page is p.582)
    #
    # **Of a single object** - not of a set. That is the spec's own wording and
    # it is what makes this cheap here: the object is already in hand as a
    # `single_object` value, so a series variable is a *reference* built from
    # it rather than a fan-out over rows.
    "time_series_set",
)

# Foundry's transformation vocabulary, less the ones that need a widget or a
# store behind them. Each is a pure function of already-resolved inputs, which
# is what lets the whole graph be computed in one pass in dependency order.
TRANSFORMS = (
    "concat",       # string concatenation over parts
    "if_else",      # condition, then, else
    "cast",         # between primitives, refusing what it cannot convert
    "is_empty",
    "is_not_empty",
    "filter_set",   # narrow an object set by a value another variable holds
    "narrow_set",   # narrow an object set by a list of clauses a widget writes
    "object_property",  # one property of the object a viewer picked
    "filter_value",  # one property's chosen value, out of a filter's clauses
    "object_series",  # the time series a property holds, on the object picked
)

# Still declared and deliberately not evaluated here: an aggregate over a set
# needs the instance store, so it is a server round trip rather than a pure
# function, and pretending otherwise would mean this module quietly returning
# None for it and every caller having to know which of its results are real.
# `/object-sets/aggregate` is what answers it, and the Metric Card is what asks
# (§74) - which is the correction recorded against roadmap 1.2.
#
# **`object_property` moved out of this list** (§84), because its premise
# changed. It was here on the assumption that a `single_object` variable holds
# a *key* and reading a property means fetching the object. It holds the object
# the viewer picked - key, type and properties - so reading one is a lookup in
# a value this module already has, and the round trip it was waiting for does
# not exist.
STORE_TRANSFORMS = ("object_set_aggregation",)

CAST_TARGETS = ("string", "number", "boolean")

# How deep one module may be embedded inside another (roadmap 1.5, priority 4).
#
# A limit rather than "as deep as it goes", and small on purpose. Every level
# is another definition to fetch, another variable graph to resolve and another
# set of widgets to draw, all before the outermost module has anything on
# screen - so the cost of depth is paid by a *viewer* who cannot see why the
# page is slow. Three is enough for a module composed of parts composed of
# parts, and past that the honest advice is to link to the module rather than
# inline it.
MAX_EMBED_DEPTH = 3

MAX_VARIABLES = 200
MAX_CONCAT_PARTS = 20

# An external ID is a *stable* name for a variable, and the one mechanism behind
# three features Foundry describes separately: embedding, URL initialisation and
# state saving (`docs/pal/foundry_workshop.pdf` p.163, p.165, p.202).
#
# > "The module interface is the set of variables that are able to be mapped to
# > variables from a parent module when embedded, and initialized from the URL.
# > You can think of the module interface as the API for a Workshop module."
# > (p.163)
#
# Which is why it is not the variable id. `v_7f3a...` is generated by the
# builder and means nothing to a person writing a URL by hand, and a saved state
# that pointed at one would break the first time an app was rebuilt. The
# external ID is chosen by whoever builds the module and is theirs to keep.
#
# The character class is the URL's, not ours: an external ID appears as a query
# parameter name (p.165, "?interfaceVariable=123"), so anything needing
# percent-encoding would make the documented copy-paste recipe wrong. Leading
# digit excluded so it can also be a key in generated code without quoting.
EXTERNAL_ID_RE = r"[A-Za-z][A-Za-z0-9_]{0,63}"
MAX_INTERFACE_TEXT = 200

# Props whose value is a variable id. The vocabulary grows widget by widget in
# item 1.5; what matters here is that it is a *list*, so usage scanning has one
# definition rather than each caller guessing.
# Every node prop that names a variable. A binding missing from this list is a
# binding nothing checks: deleting the variable is allowed, and the widget then
# reads as "no filter" and quietly shows everything - the failure decision 0002
# exists to remove.
#
# `subjectVariable` was missing until item 1.5, which is a real gap and not a
# new one: an inline action form (§87) bound to a deleted variable was neither
# refused nor reported. Adding it can make an already-saved app fail to open,
# and that is the intended answer - such an app is already a form pointed at
# nothing, and saying so beats a form that edits whatever it finds.
REFERENCE_PROPS = (
    "filterParameter",
    "searchParameter",
    "variable",
    "objectSetVariable",
    "enabledVariable",
    "visibleWhen",
    "subjectVariable",
    "drilldownVariable",
    "seriesVariable",
)


class VariableError(ValueError):
    """Refusal, phrased for whoever is building the app."""


@dataclass(frozen=True)
class Derivation:
    transform: str
    # Variable ids this derivation reads. Kept separate from `config` so the
    # dependency graph does not depend on knowing each transform's shape - a
    # new transform cannot accidentally become invisible to cycle detection.
    inputs: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Interface:
    """A variable's membership of the module interface (p.163).

    Foundry gates this on an external ID - "add an external ID, and make sure
    the toggle for module interface is enabled" - and so do we, in `parse`. The
    two are not independent settings: the interface *is* addressed by external
    ID, so an interface variable without one would be a published API with no
    name to call it by.

    `display_name` and `description` are optional and exist for one audience:
    whoever is embedding this module, or writing a URL against it, in a panel
    that lists the interface (p.163, "shown when the module is embedded or used
    in an Open Workshop module event"). They are documentation, not identity -
    renaming one breaks nothing.

    `required` has no Foundry counterpart we could find and is ours. It exists
    because the alternative to refusing an unmapped variable is an embedded
    module that renders against a default nobody chose, which is the silent
    failure decision 0002 was written to remove. Defaults to false, so it is
    opt-in and an existing module cannot become unsaveable by upgrade.
    """

    display_name: str | None = None
    description: str | None = None
    required: bool = False


@dataclass(frozen=True)
class Variable:
    id: str
    kind: str
    label: str
    default: Any = None
    derivation: Derivation | None = None
    # kind == "object_set" only: the set this variable starts from, as a
    # *definition* (type plus filters) rather than rows. Storing rows would
    # make a saved app a saved session, which decision 0002 rules out.
    object_set: dict[str, Any] | None = None
    # The stable, author-chosen name. Optional: most variables are internal and
    # naming every one of them would be a tax on building anything.
    external_id: str | None = None
    interface: Interface | None = None

    @property
    def derived(self) -> bool:
        return self.derivation is not None


def parse(raw: Any) -> dict[str, Variable]:
    """Validate the `variables` map of a module document."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise VariableError("`variables` must be an object of id -> variable")
    if len(raw) > MAX_VARIABLES:
        raise VariableError(f"a module may declare at most {MAX_VARIABLES} variables")

    variables: dict[str, Variable] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise VariableError(f"variable {key!r} must be an object")
        vid = str(value.get("id") or key)
        if vid != key:
            # The map key and the id are two statements of the same fact, and a
            # document where they disagree has no correct reading: references
            # use the id, the builder indexes by the key.
            raise VariableError(
                f"variable {key!r} declares id {vid!r} - the key and the id must match"
            )
        kind = value.get("kind")
        if kind not in KINDS:
            raise VariableError(
                f"variable {key!r} has kind {kind!r}; expected one of {', '.join(KINDS)}"
            )
        label = str(value.get("label") or "").strip()
        if not label:
            raise VariableError(f"variable {key!r} needs a label")
        derivation = _parse_derivation(vid, value.get("derivation"))
        if kind == "time_series_set" and derivation is None:
            # There is no static form of a time series set. A series is read
            # *through* an object (p.76: "a time series property of a single
            # object"), so one that named no object would be a variable with
            # nowhere to read from - and it would resolve to whatever
            # `default` held, which for this kind is always a typo.
            raise VariableError(
                f"variable {label!r} is a time series set but is not derived from an "
                "object - a series is a property of an object, so it needs an "
                "object_series derivation naming which object and which property"
            )
        external_id, interface = _parse_interface(
            label, value.get("external_id"), value.get("interface")
        )
        variables[vid] = Variable(
            id=vid,
            kind=str(kind),
            label=label,
            default=value.get("default"),
            derivation=derivation,
            object_set=_parse_object_set(vid, kind, label, value.get("object_set"), derivation),
            external_id=external_id,
            interface=interface,
        )

    _refuse_duplicate_external_ids(variables)
    _refuse_unknown_inputs(variables)
    _refuse_cycles(variables)
    return variables


def _parse_interface(
    label: str, raw_external: Any, raw_interface: Any
) -> tuple[str | None, Interface | None]:
    """A variable's external ID and its interface membership (p.163)."""
    import re

    external_id: str | None = None
    if raw_external is not None:
        if not isinstance(raw_external, str):
            raise VariableError(f"variable {label!r}: external_id must be a string")
        external_id = raw_external.strip()
        if not external_id:
            # Distinguished from absent on purpose: an empty string is almost
            # always a form field somebody cleared, and silently treating it as
            # "no external ID" would mean the interface toggle beside it stopped
            # working with nothing said.
            raise VariableError(
                f"variable {label!r} has an empty external ID - remove it, or give it a name"
            )
        if not re.fullmatch(EXTERNAL_ID_RE, external_id):
            raise VariableError(
                f"variable {label!r}: external ID {external_id!r} must start with a letter "
                "and contain only letters, digits and underscores. It is used as a URL "
                "query parameter, so anything needing encoding would break the link"
            )

    if raw_interface is None:
        return external_id, None
    if raw_interface is False:
        return external_id, None
    # `true` is the toggle in its simplest form; an object carries the optional
    # display name and description alongside it. Both shapes are accepted
    # because the builder writes the second and a hand-written document is far
    # more likely to write the first.
    if raw_interface is True:
        block: dict[str, Any] = {}
    elif isinstance(raw_interface, dict):
        block = raw_interface
    else:
        raise VariableError(
            f"variable {label!r}: interface must be true, false, or an object"
        )

    if external_id is None:
        raise VariableError(
            f"variable {label!r} is on the module interface but has no external ID. "
            "The interface is addressed by external ID - by an embedding module, and "
            "by a URL - so one without a name cannot be reached"
        )

    def text(field: str) -> str | None:
        value = block.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            raise VariableError(f"variable {label!r}: interface {field} must be a string")
        value = value.strip()
        if len(value) > MAX_INTERFACE_TEXT:
            raise VariableError(
                f"variable {label!r}: interface {field} is longer than "
                f"{MAX_INTERFACE_TEXT} characters"
            )
        return value or None

    required = block.get("required", False)
    if not isinstance(required, bool):
        raise VariableError(f"variable {label!r}: interface required must be true or false")
    return external_id, Interface(
        display_name=text("display_name"),
        description=text("description"),
        required=required,
    )


def _refuse_duplicate_external_ids(variables: dict[str, Variable]) -> None:
    """Two variables cannot share an external ID.

    It is the key a URL query parameter and a saved state address, so a
    duplicate has no correct reading: `?status=open` would name two variables
    and seed whichever the iteration order reached last.
    """
    seen: dict[str, str] = {}
    for vid in sorted(variables):
        external_id = variables[vid].external_id
        if external_id is None:
            continue
        if external_id in seen:
            raise VariableError(
                f"external ID {external_id!r} is used by both {seen[external_id]!r} and "
                f"{variables[vid].label!r}. It is what a URL and an embedding module name, "
                "so it has to point at one variable"
            )
        seen[external_id] = variables[vid].label


def interface_variables(variables: dict[str, Variable]) -> dict[str, Variable]:
    """The module's interface, keyed by external ID - its public API (p.163)."""
    return {
        v.external_id: v
        for v in variables.values()
        if v.interface is not None and v.external_id is not None
    }


def _parse_object_set(
    vid: str, kind: Any, label: str, raw: Any, derivation: Derivation | None
) -> dict[str, Any] | None:
    """The set an `object_set` variable starts from.

    An object-set variable is either a **base** set - a type, optionally with
    fixed filters - or a **derived** one narrowed from another set. Exactly one
    of the two, because a variable that declared both would have two answers to
    "where do these rows come from" and no rule for which wins.
    """
    from . import object_sets  # local: only object-set variables need it

    if kind != "object_set":
        if raw is not None:
            raise VariableError(
                f"variable {label!r} is a {kind} but carries an object set - only "
                "object_set variables may"
            )
        return None
    if derivation is not None:
        if raw is not None:
            raise VariableError(
                f"variable {label!r} is both derived and given a set of its own; it can "
                "start from a type or be narrowed from another set, not both"
            )
        return None
    if raw is None:
        raise VariableError(
            f"variable {label!r} is an object set but names no object type to draw from"
        )
    try:
        # Parsed rather than trusted: the same validation `/object-sets/evaluate`
        # applies, so a definition that would be refused at read time is refused
        # at save time instead - which is where somebody can still fix it.
        object_sets.parse(raw)
    except ValueError as exc:
        raise VariableError(f"variable {label!r}: {exc}") from exc
    return dict(raw)


def _parse_derivation(vid: str, raw: Any) -> Derivation | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise VariableError(f"variable {vid!r} has a derivation that is not an object")
    transform = raw.get("transform")
    if transform in STORE_TRANSFORMS:
        raise VariableError(
            f"{transform} is not built yet - it reads the ontology, so it needs a "
            "server round trip rather than a local computation"
        )
    if transform not in TRANSFORMS:
        raise VariableError(
            f"variable {vid!r} uses transform {transform!r}; expected one of "
            f"{', '.join(TRANSFORMS)}"
        )
    inputs = raw.get("inputs") or []
    if not isinstance(inputs, list) or any(not isinstance(i, str) for i in inputs):
        raise VariableError(f"variable {vid!r}: derivation inputs must be a list of ids")
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        raise VariableError(f"variable {vid!r}: derivation config must be an object")

    derivation = Derivation(transform=str(transform), inputs=tuple(inputs), config=config)
    _check_arity(vid, derivation)
    return derivation


def _check_arity(vid: str, d: Derivation) -> None:
    """Refuse a derivation that cannot produce a value, at save rather than at
    view: an app that renders a blank card because a transform was configured
    with one input instead of three is a bug nobody can see the cause of."""
    if d.transform == "concat":
        if not d.inputs:
            raise VariableError(f"variable {vid!r}: concat needs at least one input")
        if len(d.inputs) > MAX_CONCAT_PARTS:
            raise VariableError(
                f"variable {vid!r}: concat takes at most {MAX_CONCAT_PARTS} parts"
            )
    elif d.transform == "if_else":
        if len(d.inputs) != 3:
            raise VariableError(
                f"variable {vid!r}: if_else needs exactly three inputs "
                "(condition, then, else)"
            )
    elif d.transform == "cast":
        if len(d.inputs) != 1:
            raise VariableError(f"variable {vid!r}: cast needs exactly one input")
        target = d.config.get("to")
        if target not in CAST_TARGETS:
            raise VariableError(
                f"variable {vid!r}: cast target {target!r}; expected one of "
                f"{', '.join(CAST_TARGETS)}"
            )
    elif d.transform in ("is_empty", "is_not_empty"):
        if len(d.inputs) != 1:
            raise VariableError(f"variable {vid!r}: {d.transform} needs exactly one input")
    elif d.transform == "filter_set":
        from . import object_sets

        if len(d.inputs) != 2:
            raise VariableError(
                f"variable {vid!r}: filter_set needs exactly two inputs "
                "(the set to narrow, and the variable holding the value)"
            )
        prop = d.config.get("property")
        if not prop or not isinstance(prop, str):
            raise VariableError(f"variable {vid!r}: filter_set needs a property to filter on")
        op = d.config.get("op", "eq")
        if op not in object_sets.OPERATORS:
            # The same short operator list, and the same reason: an operator
            # that meant different things on Postgres and OpenSearch would make
            # an app's results depend on which store the deployment runs.
            raise VariableError(
                f"variable {vid!r}: filter_set operator {op!r}; expected one of "
                f"{', '.join(object_sets.OPERATORS)}"
            )
    elif d.transform == "object_property":
        if len(d.inputs) != 1:
            raise VariableError(
                f"variable {vid!r}: object_property needs exactly one input "
                "(the variable holding the object)"
            )
        prop = d.config.get("property")
        if not prop or not isinstance(prop, str):
            raise VariableError(f"variable {vid!r}: object_property needs a property to read")
    elif d.transform == "filter_value":
        if len(d.inputs) != 1:
            raise VariableError(
                f"variable {vid!r}: filter_value needs exactly one input "
                "(the variable holding the filter clauses)"
            )
        prop = d.config.get("property")
        if not prop or not isinstance(prop, str):
            raise VariableError(
                f"variable {vid!r}: filter_value needs a property to read"
            )
    elif d.transform == "object_series":
        from . import time_series

        if len(d.inputs) != 1:
            raise VariableError(
                f"variable {vid!r}: object_series needs exactly one input "
                "(the variable holding the object)"
            )
        prop = d.config.get("property")
        if not prop or not isinstance(prop, str):
            raise VariableError(
                f"variable {vid!r}: object_series needs a time series property to read"
            )
        # The bucket and the summariser are checked here rather than at read
        # time, because the read is a `points_sql` build: an unknown aggregate
        # would surface as a DuckDB parse error in front of a viewer, naming a
        # function nobody typed.
        interval = d.config.get("interval", "day")
        if interval not in time_series.INTERVALS:
            raise VariableError(
                f"variable {vid!r}: interval {interval!r}; expected one of "
                f"{', '.join(time_series.INTERVALS)}"
            )
        aggregate = d.config.get("aggregate", "avg")
        if aggregate not in time_series.AGGREGATES:
            raise VariableError(
                f"variable {vid!r}: aggregate {aggregate!r}; expected one of "
                f"{', '.join(time_series.AGGREGATES)}"
            )
    elif d.transform == "narrow_set":
        # No property or operator here on purpose: which properties a Filter
        # List narrows on is what the *viewer* chooses, so it is part of the
        # value rather than of the declaration. The clauses are validated when
        # they arrive, by the same parse every object set gets.
        if len(d.inputs) != 2:
            raise VariableError(
                f"variable {vid!r}: narrow_set needs exactly two inputs "
                "(the set to narrow, and the variable holding the filter clauses)"
            )


def _refuse_unknown_inputs(variables: dict[str, Variable]) -> None:
    for variable in variables.values():
        if variable.derivation is None:
            continue
        for ref in variable.derivation.inputs:
            if ref not in variables:
                raise VariableError(
                    f"variable {variable.label!r} reads {ref!r}, which this module "
                    "does not declare"
                )
            if ref == variable.id:
                raise VariableError(
                    f"variable {variable.label!r} reads itself"
                )


def _refuse_cycles(variables: dict[str, Variable]) -> None:
    """Kahn's algorithm; whatever is left over is in a cycle.

    Reported by label rather than id, sorted, because the person reading this
    named the variables and has never seen `v_7f3a1c`.
    """
    remaining = {
        vid: set(v.derivation.inputs) if v.derivation else set()
        for vid, v in variables.items()
    }
    settled: set[str] = set()
    while True:
        ready = [vid for vid, deps in remaining.items() if not (deps - settled)]
        if not ready:
            break
        for vid in ready:
            settled.add(vid)
            del remaining[vid]
    if remaining:
        names = sorted(variables[vid].label for vid in remaining)
        raise VariableError(
            "these variables depend on each other in a loop: " + ", ".join(names)
        )


def evaluation_order(variables: dict[str, Variable]) -> list[str]:
    """Ids in an order where every variable's inputs come first.

    Sorted within each layer so the order is the same on every call - a
    recomputation order that varied run to run would make a bug in a transform
    reproduce only sometimes.
    """
    remaining = {
        vid: set(v.derivation.inputs) if v.derivation else set()
        for vid, v in variables.items()
    }
    order: list[str] = []
    settled: set[str] = set()
    while remaining:
        ready = sorted(vid for vid, deps in remaining.items() if not (deps - settled))
        if not ready:  # pragma: no cover - parse() refuses cycles first
            raise VariableError("these variables depend on each other in a loop")
        for vid in ready:
            order.append(vid)
            settled.add(vid)
            del remaining[vid]
    return order


# ---- values ------------------------------------------------------------------
def evaluate(
    variables: dict[str, Variable],
    values: dict[str, Any],
    *,
    bound: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Resolve every variable, computing derived ones from their inputs.

    `values` is what the viewer has set - a filter selection, a row click.
    A value supplied for a *derived* variable is ignored rather than honoured:
    a derived variable is a function of its inputs, and letting a caller
    override it would make the same document show two different things
    depending on which of the two the reader believed.

    `bound` is the one exception, and it is not a caller's preference - it is
    Foundry's precedence rule for an embedded module (p.122, p.127):

    > "Workshop always uses the parent module's variable definition and ignores
    > the embedded module's interface variable definition."

    So an interface variable the host has mapped takes the host's value and its
    *own* definition is skipped, derivation and all. p.127 spells out the two
    consequences and both follow from this line: the child's default is not used,
    and the child's recompute behaviour is not used. Downstream variables in the
    child still recompute normally - they read the bound value as their input,
    which is the entire point of passing one in.
    """
    resolved: dict[str, Any] = {}
    for vid in evaluation_order(variables):
        variable = variables[vid]
        if vid in bound:
            # No fallback to `variable.default`, deliberately. p.127: "default
            # variable values of mapped variables defined in the child module
            # will not be used." The host resolves its own variable first and
            # sends the result, so an absent value here means the host's value
            # is genuinely unset - and answering that with the child's default
            # would be the child's definition winning after all.
            resolved[vid] = values.get(vid)
            continue
        if variable.derivation is None:
            # An object-set variable resolves to its *definition*, not to rows.
            # Turning that into instances is `/object-sets/evaluate`'s job, and
            # keeping the two apart is what lets one set feed a table, a chart
            # and a count without three different notions of what the set is.
            resolved[vid] = (
                dict(variable.object_set)
                if variable.object_set is not None
                else values.get(vid, variable.default)
            )
            continue
        resolved[vid] = _apply(variable, [resolved[i] for i in variable.derivation.inputs])
    return resolved


def _apply(variable: Variable, inputs: list[Any]) -> Any:
    d = variable.derivation
    assert d is not None
    if d.transform == "concat":
        separator = str(d.config.get("separator") or "")
        # Nothing is not the string "None". A null part contributes an empty
        # string, so a half-filled concat reads as a partial label rather than
        # as debris.
        return separator.join("" if v is None else _text(v) for v in inputs)
    if d.transform == "if_else":
        condition, then, otherwise = inputs
        return then if _truthy(condition) else otherwise
    if d.transform == "cast":
        return _cast(inputs[0], str(d.config["to"]), variable.label)
    if d.transform == "is_empty":
        return _empty(inputs[0])
    if d.transform == "is_not_empty":
        return not _empty(inputs[0])
    if d.transform == "filter_set":
        return _filter_set(variable, inputs[0], inputs[1], d.config)
    if d.transform == "narrow_set":
        return _narrow_set(variable, inputs[0], inputs[1])
    if d.transform == "object_property":
        return _object_property(variable, inputs[0], str(d.config["property"]))
    if d.transform == "filter_value":
        return _filter_value(variable, inputs[0], str(d.config["property"]))
    if d.transform == "object_series":
        return _object_series(variable, inputs[0], d.config)
    raise VariableError(f"unknown transform {d.transform!r}")  # pragma: no cover


def _filter_set(
    variable: Variable, base: Any, value: Any, config: dict[str, Any]
) -> dict[str, Any]:
    """Narrow an object set by a value another variable holds - Foundry's
    Filter List driving an Object Table, expressed as a derivation.

    **An unset value drops the filter rather than filtering for nothing.** A
    viewer who has not touched the filter yet should see the whole set, not an
    empty table; filtering for `region = null` would make every app open empty
    and look broken.

    This is *not* the failure decision 0002 removed. That one was a binding to
    a variable nothing declared, which the save path now refuses outright. This
    is a declared variable that simply has no value yet, which is an ordinary
    state with an obvious meaning.
    """
    if not isinstance(base, dict) or "object_type_id" not in base:
        raise VariableError(
            f"{variable.label!r} filters something that is not an object set"
        )
    if value is None or value == "" or (isinstance(value, (list, tuple)) and not value):
        return dict(base)
    filters = list(base.get("filters") or [])
    filters.append(
        {"property": config["property"], "op": config.get("op", "eq"), "value": value}
    )
    return {**base, "filters": filters}


def _object_property(variable: Variable, obj: Any, property_name: str) -> Any:
    """One property of the object a viewer picked (roadmap 1.2, built in §84).

    **What a `single_object` variable holds, decided here**: the object the
    trigger was about - `object_type_id`, `primary_key` and `properties` - not
    a key to fetch later. Three consequences, and the middle one is the cost:

    *Reading a property is a lookup, not a round trip.* That is why this
    transform left `STORE_TRANSFORMS`: the fetch it was waiting for does not
    need to happen.

    *The value is a snapshot of the click.* If the object changes afterwards,
    a widget reading it keeps showing what was clicked until something clicks
    again. That is the honest reading of "the row you picked", and it is why
    the reference travels with it - a widget that needs live values has the
    type and the key to re-read, and an object *set* re-evaluates on every
    resolve anyway.

    *Nothing here is persisted*, so this does not make a saved app a saved
    session (decision 0002 §3) - the objection that keeps object-set variables
    holding a definition rather than rows does not apply to a value that only
    ever exists for one viewing.

    **A missing object is `None`, a wrong-shaped one is refused.** Nothing
    picked yet is an ordinary state - a detail panel before the first click -
    and reads as empty. A value that is not an object at all is a document
    wired wrongly, and saying so beats rendering blank.
    """
    if obj is None or obj == "":
        return None
    if not isinstance(obj, dict) or "properties" not in obj:
        raise VariableError(
            f"{variable.label!r} reads a property of something that is not an object - "
            "point it at a variable a row selection writes"
        )
    properties = obj.get("properties")
    if not isinstance(properties, dict):
        raise VariableError(f"{variable.label!r}: the object's properties are not an object")
    if property_name == "primary_key":
        # The key is not in `properties` on every path (a row's key is its own
        # field), so it is readable by name rather than being the one property
        # an app cannot show.
        return obj.get("primary_key")
    return properties.get(property_name)


def _filter_value(variable: Variable, clauses: Any, property_name: str) -> Any:
    """What the viewer chose for one property, out of a filter's clauses.

    p.444's other half. `narrow_set` *applies* the filter state to a set; this
    reads a value back out of it, which is what "reused in widget
    configurations" means - a heading that says "Showing: north", a chart title
    that names the region, an action whose default comes from the filter.

    **A property nobody filtered on is `None`, not an error.** A filter that
    has not been touched is the ordinary state of an app somebody just opened,
    and a derivation that raised would make the first render the broken one.
    That is `filter_set`'s rule about unset values, one layer up.

    **The clause's value is returned as it is, list and all.** An `in` clause
    holds several values because the viewer picked several, and collapsing that
    to the first would silently answer a different question - `is_empty` and
    `concat` both already handle a list, so a caller has what it needs.

    Only the *first* matching clause is read. Two clauses on one property is a
    Filter List expressing a range or a several-of, which is one filter with
    two halves rather than two answers - and picking a half here would be this
    function inventing which half matters.
    """
    if clauses is None or clauses == "" or clauses == []:
        return None
    if not isinstance(clauses, list):
        raise VariableError(
            f"{variable.label!r} expects a list of filter clauses, "
            f"not {type(clauses).__name__}"
        )
    for clause in clauses:
        if isinstance(clause, dict) and clause.get("property") == property_name:
            return clause.get("value")
    return None


def _object_series(
    variable: Variable, obj: Any, config: dict[str, Any]
) -> dict[str, Any] | None:
    """A time series set: one object's `time_series` property, as a reference.

    > "Time series set: Stores a time series property of a single object."
    > (`foundry_workshop` p.76)

    **It resolves to a reference, not to points**, and that is the same rule
    object-set variables follow: `object_set` holds a definition rather than
    rows, so one set can feed a table, a chart and a count without three
    notions of what the set is. A series is the sharper case - decision 0009
    keeps points in the dataset they arrived in, so a variable holding points
    would be the copy that decision exists to refuse, made per viewing and per
    widget.

    What comes out is the whole question a reader can ask: which object, which
    property, which bucket, which summariser. `objApi.seriesPoints` takes
    exactly that, so a widget consuming this variable adds no interpretation.

    **The bucket and the summariser live on the variable, not on the widget**
    (p.76's "optionally allowing the application of time series transforms to
    it"). Two charts reading one series variable then agree about what a point
    means, which is the difference between a variable and a shortcut for
    typing the same configuration twice.

    **Nothing picked yet is `None`**, the same as `object_property`: a detail
    panel before the first click is an ordinary state, not a fault.

    **An object with no id or no type is refused.** Unlike a missing property
    value, this is not a state a viewer can be in - every path that writes a
    `single_object` writes both (`canvas/object-set.ts`, and the Object View's
    seed) - so it means the value came from somewhere that is not an object
    selection. Returning `None` would render as "no readings yet", which is a
    sentence about the data when the truth is about the wiring.
    """
    if obj is None or obj == "":
        return None
    if not isinstance(obj, dict):
        raise VariableError(
            f"{variable.label!r} reads a time series from something that is not an "
            "object - point it at a variable a row selection writes"
        )
    type_id = obj.get("object_type_id")
    instance_id = obj.get("id")
    if not type_id or not instance_id:
        raise VariableError(
            f"{variable.label!r} reads a time series from an object with no "
            "type or no id - a series is read through the object it belongs to, "
            "so both are needed to ask for one"
        )
    return {
        "object_type_id": str(type_id),
        "instance_id": str(instance_id),
        "property": str(config["property"]),
        "interval": str(config.get("interval", "day")),
        "aggregate": str(config.get("aggregate", "avg")),
    }


def _narrow_set(variable: Variable, base: Any, clauses: Any) -> dict[str, Any]:
    """Narrow an object set by a *list* of clauses a widget wrote.

    `filter_set` is one property and one operator, both fixed when the app was
    built, driven by whatever value a variable holds. A Filter List is the
    other shape: the viewer decides *which* properties to filter and on how
    many values at once, so what varies is the list itself.

    **The clauses are runtime data and are validated like any other input.**
    They arrive from a browser, so they get the same parse every object set
    gets — unknown operators, ordered comparisons and missing values are
    refused with the sentence `object_sets.parse` already writes, rather than
    quietly dropped. A dropped clause is a set that is wider than the viewer
    asked for, which is the failure decision 0002 exists to remove.

    **An empty list is no filter, not an empty set** — the same rule
    `filter_set` follows, for the same reason: a viewer who has touched
    nothing yet should see everything.
    """
    from . import object_sets

    if not isinstance(base, dict) or "object_type_id" not in base:
        raise VariableError(f"{variable.label!r} filters something that is not an object set")
    if clauses is None or clauses == "" or clauses == []:
        return dict(base)
    if not isinstance(clauses, list):
        raise VariableError(
            f"{variable.label!r} expects a list of filter clauses, not {type(clauses).__name__}"
        )
    combined = {**base, "filters": [*(base.get("filters") or []), *clauses]}
    try:
        object_sets.parse(combined)
    except ValueError as exc:
        raise VariableError(f"{variable.label!r}: {exc}") from exc
    return combined


def _text(value: Any) -> str:
    if isinstance(value, bool):
        # Python's str(True) is "True"; every other layer here speaks JSON.
        return "true" if value else "false"
    return str(value)


def _truthy(value: Any) -> bool:
    """What `if_else` treats as true.

    Deliberately not Python's truthiness: `0` and `""` are values a viewer
    typed, and treating them as "no" would make a numeric filter of zero behave
    as though nothing was entered. Only a genuinely absent value is false, plus
    `false` itself.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return True


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, list, dict, tuple)):
        return len(value) == 0
    return False


def _cast(value: Any, target: str, label: str) -> Any:
    """Convert, or refuse in a sentence naming the value.

    Refusing rather than returning None: a cast that silently produced nothing
    would show as an empty card, and the reader would look at the widget rather
    than at the variable feeding it.
    """
    if value is None:
        return None
    try:
        if target == "string":
            return _text(value)
        if target == "number":
            if isinstance(value, bool):
                raise ValueError("a boolean is not a number")
            number = float(value)
            return int(number) if number.is_integer() else number
        if target == "boolean":
            if isinstance(value, bool):
                return value
            text = _text(value).strip().lower()
            if text in ("true", "1", "yes"):
                return True
            if text in ("false", "0", "no", ""):
                return False
            raise ValueError("not a boolean")
    except (TypeError, ValueError) as exc:
        raise VariableError(
            f"{label!r} cannot convert {value!r} to {target}: {exc}"
        ) from exc
    raise VariableError(f"unknown cast target {target!r}")  # pragma: no cover


# ---- what uses what ----------------------------------------------------------
def embedded_modules(document: Any) -> set[str]:
    """The module ids a document embeds, from its layout.

    Pure, and separate from the cycle check that consumes it, because the two
    have different needs: this one is a parse, and deciding whether an embed is
    *legal* means reading other modules out of the database. Keeping the parse
    here means the route does not have to know the document's shape.
    """
    layout = document.get("layout") if isinstance(document, dict) else None
    found: set[str] = set()
    for node in (layout or {}).values():
        if not isinstance(node, dict):
            continue
        # A node's `type` is `{"resolvedName": ...}` from the builder and a bare
        # string in hand-written and converted documents. Both are in the
        # stored corpus, and assuming the first form raised `AttributeError` on
        # the second - a save path that crashed rather than refusing.
        if _embedding_node(node) is None:
            continue
        module_id = (node.get("props") or {}).get("moduleId")
        if isinstance(module_id, str) and module_id:
            found.add(module_id)
    return found


# Both node types embed a module, and both must be seen by every rule that
# cares - the cycle walk, the depth limit, the interface check. A Loop layout
# that was invisible here could close a cycle the server refuses everywhere
# else, and the loop would be found by a viewer's browser rather than by its
# author (`docs/pal/foundry_workshop.pdf` p.129).
EMBEDDING_NODES = ("CanvasEmbeddedModule", "CanvasLoopSection")


def _embedding_node(node: Any) -> str | None:
    node_type = node.get("type")
    resolved = node_type.get("resolvedName") if isinstance(node_type, dict) else node_type
    name = str(resolved or "")
    return name if name in EMBEDDING_NODES else None


@dataclass(frozen=True)
class Embed:
    """One `CanvasEmbeddedModule` node: which module, and what is passed in."""

    node: str
    module_id: str
    # child external ID -> host variable id. Keyed by external ID because that
    # is what the child publishes (p.163); keyed by *variable id* on the host
    # side because that is what the host's own document uses everywhere else.
    # The asymmetry is deliberate and it is the boundary: an external ID is a
    # public name, a variable id is a private one, and a mapping is exactly the
    # place where one is translated into the other.
    mapping: dict[str, str] = field(default_factory=dict)
    # Loop layouts only: the child interface variable that receives each object
    # (p.135). Not part of `mapping` because it is not mapped to a host
    # variable - the loop supplies one object per copy, so its source is the set
    # being looped rather than anything the host declares.
    item_external_id: str | None = None


def embeds(document: Any) -> list[Embed]:
    """Every embedded-module node in a document, with its interface mapping.

    Separate from `embedded_modules` above, which answers "which modules does
    this reach" for the cycle walk and wants a set. This one answers "what did
    the builder configure", and the difference matters: two nodes may embed the
    same module with different mappings, and a set would lose one of them.
    """
    layout = document.get("layout") if isinstance(document, dict) else None
    out: list[Embed] = []
    for node_id, node in (layout or {}).items():
        if not isinstance(node, dict):
            continue
        kind = _embedding_node(node)
        if kind is None:
            continue
        props = node.get("props") or {}
        module_id = props.get("moduleId")
        if not isinstance(module_id, str) or not module_id:
            continue
        raw = props.get("interface") or {}
        if not isinstance(raw, dict):
            raise VariableError(
                "an embedded module's interface mapping must be an object of "
                "external id -> variable id"
            )
        mapping: dict[str, str] = {}
        for external_id, host_vid in raw.items():
            if host_vid is None or host_vid == "":
                # An unmapped row in the builder's panel. Dropped rather than
                # refused: leaving a variable unmapped is a legitimate state
                # (the child falls back to its own definition), and only
                # `required` makes it an error - checked against the child.
                continue
            if not isinstance(host_vid, str):
                raise VariableError(
                    f"the mapping for {external_id!r} must name a variable of this module"
                )
            mapping[str(external_id)] = host_vid
        item = props.get("itemVariable") if kind == "CanvasLoopSection" else None
        out.append(
            Embed(
                node=str(node_id),
                module_id=module_id,
                mapping=mapping,
                item_external_id=item if isinstance(item, str) and item else None,
            )
        )
    return out


def usages(layout: Any, variables: dict[str, Variable]) -> dict[str, list[dict[str, str]]]:
    """Where each variable is referenced, by node and prop.

    Reads the layout rather than trusting a stored index: an index is a second
    copy of a fact, and the two would disagree the first time a widget was
    deleted by anything that did not know to update it.
    """
    found: dict[str, list[dict[str, str]]] = {vid: [] for vid in variables}
    if not isinstance(layout, dict):
        return found
    for node_id, node in layout.items():
        if not isinstance(node, dict):
            continue
        props = node.get("props")
        if not isinstance(props, dict):
            continue
        for prop in REFERENCE_PROPS:
            ref = props.get(prop)
            if isinstance(ref, str) and ref in found:
                found[ref].append({"node": str(node_id), "prop": prop})
    # A derived variable is a usage too. Deleting an input out from under a
    # derivation is the same mistake as deleting one out from under a widget,
    # and only naming the widget case would make the refusal look arbitrary.
    for variable in variables.values():
        if variable.derivation is None:
            continue
        for ref in variable.derivation.inputs:
            if ref in found:
                found[ref].append({"node": variable.id, "prop": "derivation"})
    return found


def dangling_references(layout: Any, variables: dict[str, Variable]) -> list[dict[str, str]]:
    """References to variables the module does not declare.

    The failure decision 0002 exists to remove: today a widget bound to a
    parameter nothing declares silently reads as "no filter", so it shows more
    rows than it should. Returned rather than raised, because the converter
    records pre-existing ones on purpose (`broken_bindings`) and the *save*
    path is where a new one is refused.
    """
    broken: list[dict[str, str]] = []
    if not isinstance(layout, dict):
        return broken
    for node_id, node in layout.items():
        if not isinstance(node, dict):
            continue
        props = node.get("props")
        if not isinstance(props, dict):
            continue
        for prop in REFERENCE_PROPS:
            ref = props.get(prop)
            if isinstance(ref, str) and ref.startswith("v_") and ref not in variables:
                broken.append({"node": str(node_id), "prop": prop, "variable": ref})
    return broken


def validate_module(
    document: Any, *, actions: dict[str, list[str]] | None = None
) -> dict[str, Variable]:
    """Everything the save path checks, in one call.

    Only applies to `format: 2` documents. A v1 definition is a bare Craft.js
    map with no variables to validate, and refusing to save one would break
    every app that has not been converted yet.

    `actions` (id -> editable properties) is the workspace's action types, and
    is passed only when a document is being *written*. Reading one does not
    re-check it against live state: an action deleted after an app was saved
    would otherwise stop the app opening at all, and a record of what somebody
    built must not become invalid because something else moved.
    """
    if not isinstance(document, dict) or document.get("format") != 2:
        return {}
    variables = parse(document.get("variables"))
    # Events are validated against the layout and the variables, because every
    # refusal there is about a reference resolving.
    from . import workshop_events

    # A module has at most one header: it is *the* module-wide toolbar, and two
    # nodes both claiming to be that is a document no renderer can settle. Said
    # here rather than in the builder because a document can arrive by any
    # route, and a refusal only the builder makes is not a rule.
    found = workshop_events.headers(document.get("layout"))
    if len(found) > 1:
        raise VariableError(
            f"a module may have one header and this one has {len(found)} - "
            "the header is the toolbar above every page, so a second one has "
            "nowhere to be"
        )
    try:
        workshop_events.parse(
            document.get("events"),
            layout=document.get("layout"),
            variables=variables,
            actions=actions,
        )
    except workshop_events.EventError as exc:
        raise VariableError(str(exc)) from exc
    # The host half of an interface mapping: every value in it must name a
    # variable *this* module declares. The child half - does that external ID
    # exist, do the kinds agree, is a required one missing - needs the child's
    # document and so lives in the route, beside the embed walk that is already
    # reading other modules out of the database.
    for embed in embeds(document):
        for external_id, host_vid in sorted(embed.mapping.items()):
            if host_vid not in variables:
                raise VariableError(
                    f"the embedded module's {external_id!r} is mapped to {host_vid!r}, "
                    "which this module does not declare - so nothing would be passed in "
                    "and the embedded module would quietly fall back to its own default"
                )

    broken = dangling_references(document.get("layout"), variables)
    if broken:
        names = ", ".join(sorted({b["variable"] for b in broken}))
        raise VariableError(
            f"this layout binds to {names}, which the module does not declare - "
            "a binding to a variable that does not exist reads as no filter at all, "
            "so the widget would quietly show everything"
        )
    return variables
