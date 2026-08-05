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

MAX_VARIABLES = 200
MAX_CONCAT_PARTS = 20

# Props whose value is a variable id. The vocabulary grows widget by widget in
# item 1.5; what matters here is that it is a *list*, so usage scanning has one
# definition rather than each caller guessing.
REFERENCE_PROPS = (
    "filterParameter",
    "searchParameter",
    "variable",
    "objectSetVariable",
    "enabledVariable",
    "visibleWhen",
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
        variables[vid] = Variable(
            id=vid,
            kind=str(kind),
            label=label,
            default=value.get("default"),
            derivation=derivation,
            object_set=_parse_object_set(vid, kind, label, value.get("object_set"), derivation),
        )

    _refuse_unknown_inputs(variables)
    _refuse_cycles(variables)
    return variables


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
def evaluate(variables: dict[str, Variable], values: dict[str, Any]) -> dict[str, Any]:
    """Resolve every variable, computing derived ones from their inputs.

    `values` is what the viewer has set - a filter selection, a row click.
    A value supplied for a *derived* variable is ignored rather than honoured:
    a derived variable is a function of its inputs, and letting a caller
    override it would make the same document show two different things
    depending on which of the two the reader believed.
    """
    resolved: dict[str, Any] = {}
    for vid in evaluation_order(variables):
        variable = variables[vid]
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
    broken = dangling_references(document.get("layout"), variables)
    if broken:
        names = ", ".join(sorted({b["variable"] for b in broken}))
        raise VariableError(
            f"this layout binds to {names}, which the module does not declare - "
            "a binding to a variable that does not exist reads as no filter at all, "
            "so the widget would quietly show everything"
        )
    return variables
