"""An action's rules, written by name rather than by id (§343;
`ontology-manager` p.65-67; `action-types` p.75, p.89-96, p.105-107).

    "…copy the working state of one Ontology to another." (p.65)

    "An exported Ontology working state with conditional formatting rules
     configured on its properties cannot be imported to an Ontology other than
     the one it was exported from." (p.67)

**§342 translated what a parameter points at; this is what a rule points at.**
The export wrote every rule's `config` verbatim, and six of them carry a uuid:

    p.75    create_object   `object_type`             the type it creates
    p.75    modify_object   `object_type`             the type it changes
    p.75    delete_object   `object_type`             the type it removes
    p.75    create_link     `link_type`               the link it writes
    p.75    delete_link     `link_type`               the link it clears
    p.96    notify          `recipients.object_type`  whose property holds the id

A probe is how that was established rather than a reading: an action with a
`create_link` rule exports its link type's uuid today, and the file's own
"nothing in the ontology is identified by id" assertion passed only because no
fixture had ever built a rule that carried one. `object_type` is optional on the
three object rules — absent means this action's own subject, which needs no name
at all — so the keys are rewritten where they appear and left alone where they
do not.

**An id this ontology cannot name is dropped, never written as an id**, which is
§342's rule one table over and for the same reason. It is reachable here in a
way it was not there: `delete_link_type` refuses a link an action *parameter*
walks (§339) and nothing refuses one an action *rule* names, so a rule holding a
dangling link id is a state this platform can be in today. A file carrying that
id would look portable and mean nothing anywhere; a file with the key missing
says nothing it cannot say, which is all it means **today** — nothing applies
action types yet. The day something does, `_validate_definition` refuses it by
name, "a link rule names a link type this workspace does not have", which is the
truth about the rule as it already stands.

**And two references leave the ontology, which is p.67's refusal arriving after
all.** §326 recorded that p.67's `UnreferencedRuleSets` had no cause here,
because this platform's conditional formatting is inline and names sibling
properties. That reading was right about formatting and wrong about the class:
a webhook rule names a webhook, and a static notify rule names people, and
neither is in the ontology any more than Foundry's rule sets are. They are not
translated — there is nothing in the file to translate them against — so they
travel as ids and `ontology_import` refuses the file for a workspace other than
the one it came from, which is the sentence p.67 writes and the remedy p.67
gives ("delete the … rules from the Ontology working state before importing").
"""
from __future__ import annotations

from typing import Any

#: Rule kinds that name an object type, and the config key holding it (p.75).
TYPE_KEYS = {
    "create_object": "object_type",
    "modify_object": "object_type",
    "delete_object": "object_type",
}

#: Rule kinds that name a link type. p.75's one sentence covers both tables:
#: "simple rules which allow you to create, modify, and delete objects, or
#: create and delete links between objects".
LINK_KEYS = {
    "create_link": "link_type",
    "delete_link": "link_type",
}


def to_names(
    rule: dict[str, Any],
    *,
    type_names: dict[str, str],
    link_names: dict[str, str],
) -> dict[str, Any]:
    """One rule's config, with its ontology references as api_names.

    **The keys keep their names.** A rule's `object_type` already reads as a
    name-shaped key and happens to hold an id; the rest of the document's
    convention is that `object_type` *is* an api_name, so the translation makes
    the rule agree with the file around it rather than inventing a second
    spelling. Nothing else in the config is touched — a rule's properties,
    parameters and templates name things by name already.
    """
    config = dict(rule.get("config") or {})
    kind = str(rule.get("kind", ""))
    if kind in TYPE_KEYS:
        _named(config, TYPE_KEYS[kind], type_names)
    if kind in LINK_KEYS:
        _named(config, LINK_KEYS[kind], link_names)
    if kind == "notify":
        recipients = config.get("recipients")
        if isinstance(recipients, dict) and "object_type" in recipients:
            # Copied before it is changed: `config` is a shallow copy, so
            # renaming in place here would edit the row this export is reading.
            recipients = dict(recipients)
            _named(recipients, "object_type", type_names)
            config["recipients"] = recipients
    return config


def _named(config: dict[str, Any], key: str, names: dict[str, str]) -> None:
    """Replace one id with its api_name, or take the key out.

    Absent stays absent, because an omitted `object_type` is p.75's "this
    action's own subject" and not a hole.
    """
    if key not in config:
        return
    found = names.get(str(config[key])) if config[key] else None
    if found is None:
        del config[key]
    else:
        config[key] = found


def references(rule: dict[str, Any]):
    """Every object type and link type one rule's config names, as
    `(api_name, kind)`.

    For `ontology_import.check_references`, which asks the same question of a
    parameter's dropdown: a name the file uses must be a name the file defines.
    A generator over this module's own tables rather than three loops at the
    call site — the shape of a rule's config belongs here, and the day a
    seventh field arrives it is added in one place.
    """
    kind = str(rule.get("kind", ""))
    config = rule.get("config") or {}
    if not isinstance(config, dict):
        return
    key = TYPE_KEYS.get(kind)
    if key and config.get(key):
        yield str(config[key]), "object type"
    key = LINK_KEYS.get(kind)
    if key and config.get(key):
        yield str(config[key]), "link type"
    if kind == "notify":
        recipients = config.get("recipients")
        if isinstance(recipients, dict) and recipients.get("object_type"):
            yield str(recipients["object_type"]), "object type"


def outside_ontology(rule: dict[str, Any]) -> list[str]:
    """What this rule reaches beyond the ontology, as the refusal's own phrase.

    p.67's two sentences are about exactly this class of thing — "rules that are
    not defined in that Ontology and cannot be transferred over" — and these are
    this platform's members of it.

    A **webhook** is `workspace_id` and `project_id` scoped (db 0067), so its id
    means nothing anywhere else. A **user** is organisation-scoped, so a static
    recipient list survives a copy within one organisation and not between two —
    and an export cannot know which it is about to be imported into, so it is
    named here as well rather than left to work sometimes.

    A list rather than a bool, because the phrase is what the refusal says and a
    caller assembling its own wording would be a second description of this
    table.
    """
    kind = str(rule.get("kind", ""))
    config = rule.get("config") or {}
    if not isinstance(config, dict):
        return []
    if kind == "webhook" and config.get("webhook"):
        return ["a webhook"]
    if kind == "notify":
        recipients = config.get("recipients")
        if isinstance(recipients, dict) and str(
            recipients.get("kind", "")
        ) == "static" and recipients.get("user_ids"):
            return ["a list of named recipients"]
    return []
