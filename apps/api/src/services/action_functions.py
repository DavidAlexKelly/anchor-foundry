"""An action's Function rule (§773; decision 0018 option B).

> "Function rule: Can be used to reference an Ontology edit function whose
> inputs are derived from parameters of the action. When this rule is present,
> no other rule may be configured since function code alone is capable of
> handling everything that other rules can do." (`action-types` p.22)

The rule names a function whose output is `edits` (`function_engine._edits`),
a version, whether it auto-upgrades (p.81), and where each of the function's
parameters comes from:

* `{"parameter": name}` - an action parameter (p.22: "inputs are derived from
  parameters of the action");
* `{"value": v}` - a fixed value;
* `{"subject": true}` - the object the action is run on, for an `object`
  parameter of the action's own type. p.79's tutorial creates a "Demo Ticket
  parameter of type Object reference" for this; an action here always has the
  object it was run on, so that parameter is this source.

**At submission the edits become the rules the executor already runs**
(`edit_rules`): a `modify_object` per property of the object the action is
run on, a named `modify_object` per property of any other object that
exists, and a `create_object` for a key that does not. Their values sit in the
bound namespace under `function.`, a name no parameter can have and no caller
can supply - the same reservation a writeback's outputs use (`webhook.`). So
every check, write, log entry, notification and revert downstream reads a
function's edits exactly as it reads a rule's, and none of them changed.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from . import functions as functions_service
from .function_engine import FunctionError, UserFacingError

#: Where the edits' values live in the bound namespace. A dot, so it cannot be
#: a parameter's api_name; refused by `bind_parameters` from a caller.
PREFIX = "function."

#: The rule kinds a Function rule may sit beside. p.22: "no other rule may be
#: configured" - the Ontology rules, which the function's edits replace. A
#: notification or a webhook is a side effect (p.87), not an edit.
SIDE_EFFECT_KINDS = frozenset({"notify", "webhook"})

def function_rule(rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The action's Function rule's config, or None when it has none."""
    for rule in rules:
        if str(rule.get("kind")) == "function":
            config = rule.get("config") or {}
            if isinstance(config, str):
                import json
                config = json.loads(config)
            return dict(config)
    return None


def resolve_version(fn: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    """The version an action runs (p.80-82): the one it names, or with
    `auto_upgrade` the newest release of the same major at or above it.

    p.81: "a version range dependency that comprises all backward compatible
    versions, such as minor or patch upgrades, of the selected minimum
    version"; p.82: "Auto upgrades are disabled for function versions of the
    form 0.y.z". A prerelease is not in the range: it is not a release."""
    pinned = next((v for v in fn["versions"] if v["version"] == config.get("version")), None)
    if pinned is None or not config.get("auto_upgrade"):
        return pinned
    floor = functions_service.version_key(str(pinned["version"]))
    if floor[0] == 0:
        return pinned
    candidates = [
        v for v in fn["versions"]
        if (key := functions_service.version_key(str(v["version"])))[0] == floor[0]
        and key[3] == 1 and key >= floor
    ]
    return max(candidates, key=lambda v: functions_service.version_key(str(v["version"])),
               default=pinned)


def check_rules(rules: list[dict[str, Any]]) -> None:
    """p.22's "no other rule may be configured", and one function."""
    kinds = [str(r.get("kind", "")) for r in rules]
    if "function" not in kinds:
        return
    if kinds.count("function") > 1:
        raise ValueError("an action calls one function; this one has two Function rules")
    others = sorted({k for k in kinds if k != "function" and k not in SIDE_EFFECT_KINDS})
    if others:
        raise ValueError(
            f"a Function rule cannot be combined with other rules ({', '.join(others)}): "
            "the function makes every edit the action does (action-types p.22)")


def check_rule(
    config: dict[str, Any],
    *,
    functions: dict[str, dict[str, Any]],
    parameters: set[str],
    object_type_id: UUID | None,
) -> None:
    """A Function rule that could not run, refused at save (p.78-82)."""
    if object_type_id is None:
        raise ValueError("a Function rule is not built for an action on an interface")
    fn = functions.get(str(config.get("function_id") or ""))
    if fn is None:
        raise ValueError("a Function rule names a function this workspace does not have")
    version = str(config.get("version") or "")
    pinned = next((v for v in fn["versions"] if v["version"] == version), None)
    if pinned is None:
        raise ValueError(f"{fn['api_name']} has no version {version or '(none named)'}")
    if config.get("auto_upgrade") not in (None, True, False):
        raise ValueError("a Function rule's auto_upgrade is true or false")
    if config.get("auto_upgrade") and functions_service.version_key(version)[0] == 0:
        raise ValueError(
            f"{fn['api_name']} {version} cannot auto-upgrade: versions of the form 0.y.z "
            "are for initial development (action-types p.82)")
    if pinned["output"]["kind"] != "edits":
        raise ValueError(
            f"{fn['api_name']} is not an edit function: it returns "
            f"{pinned['output']['kind'].replace('_', ' ')}, and an action's function "
            "returns edits (action-types p.77)")
    inputs = config.get("inputs", {})
    if not isinstance(inputs, dict):
        raise ValueError("a Function rule's inputs are an object")
    declared = {str(p["api_name"]): p for p in pinned["parameters"]}
    for name, source in inputs.items():
        p = declared.get(str(name))
        if p is None:
            raise ValueError(f"{fn['api_name']} {version} takes no parameter {name}")
        if not isinstance(source, dict) or len(source) != 1 \
                or next(iter(source)) not in ("parameter", "value", "subject"):
            raise ValueError(f"{name} comes from a parameter, a value or this object")
        if "parameter" in source and str(source["parameter"]) not in parameters:
            raise ValueError(f"{name} reads {source['parameter']}, which is not a parameter "
                             "of this action")
        if "subject" in source and (
            source["subject"] is not True or p["data_type"] != "object"
            or str(p.get("object_type_id")) != str(object_type_id)
        ):
            raise ValueError(f"{name} is not an object of this action's type, so it cannot "
                             "be the object the action is run on")
    for name, p in declared.items():
        if p.get("required", True) and name not in inputs:
            raise ValueError(f"{fn['api_name']} needs {name}, which the rule does not supply")


def edit_rules(
    edits: list[dict[str, Any]],
    *,
    object_type_id: str,
    subject_type_id: str,
    subject_key: str,
    existing: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The function's edits as the rules and bound values the executor runs
    (module note). `existing` is `{primary key: instance id}` for the keys
    that name objects already there."""
    rules: list[dict[str, Any]] = []
    bound: dict[str, Any] = {}
    for i, edit in enumerate(edits):
        key = str(edit["primary_key"])
        values = {f"{PREFIX}{i}.{prop}": (prop, value)
                  for prop, value in edit["properties"].items()}
        bound.update({name: value for name, (_prop, value) in values.items()})
        if object_type_id == subject_type_id and key == subject_key:
            rules.extend({"kind": "modify_object",
                          "config": {"property": prop, "parameter": name}}
                         for name, (prop, _v) in values.items())
        elif key in existing:
            bound[f"{PREFIX}{i}"] = existing[key]
            rules.extend({"kind": "modify_object", "config": {
                "object": f"{PREFIX}{i}", "object_type": object_type_id,
                "property": prop, "parameter": name}}
                for name, (prop, _v) in values.items())
        else:
            bound[f"{PREFIX}{i}"] = key
            rules.append({"kind": "create_object", "config": {
                "object_type": object_type_id, "primary_key": f"{PREFIX}{i}",
                "properties": {prop: name for name, (prop, _v) in values.items()}}})
    return rules, bound


async def call(
    conn: Any,
    *,
    workspace_id: UUID,
    config: dict[str, Any],
    bound: dict[str, Any],
    subject_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call the rule's function as the submitter. Returns the function's
    output (`object_type_id` of what it edits) and its result. Every refusal
    is a `FunctionError`; p.166's user-facing one is a `UserFacingError`."""
    try:
        fn = await functions_service.get_function(
            conn, workspace_id, UUID(str(config.get("function_id"))))
    except Exception:  # NotFoundError, a malformed id
        raise FunctionError("the function this action calls is not here") from None
    chosen = resolve_version(fn, config)
    if chosen is None:
        raise FunctionError(f"{fn['api_name']} has no version {config.get('version')}")
    pinned = next(v for v in fn["versions"] if v["version"] == config.get("version"))
    if chosen["output"] != pinned["output"]:
        # p.83: "If a newer release of the function returns edits outside of
        # this provenance (for example, an additional object type), action
        # execution will fail."
        raise FunctionError(
            f"{fn['api_name']} {chosen['version']} edits another object type than "
            f"{pinned['version']}, which this action was set up against (action-types p.83)")
    values: dict[str, Any] = {}
    for name, source in (config.get("inputs") or {}).items():
        if "subject" in source:
            values[name] = subject_id
        elif "parameter" in source:
            values[name] = bound.get(str(source["parameter"]))
        else:
            values[name] = source.get("value")
    result = await functions_service.execute(
        conn, workspace_id=workspace_id, function_id=UUID(str(fn["id"])),
        version=chosen["version"], values=values)
    if not result["edits"]:
        raise FunctionError(f"{fn['api_name']} made no edits, so the action has nothing "
                            "to apply")
    return chosen["output"], result
