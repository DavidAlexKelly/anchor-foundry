"""An action's rules, written by name (§343; `ontology-manager` p.65-67;
`action-types` p.75, p.89-96, p.105-107).

    "…copy the working state of one Ontology to another." (p.65)

**Pure, so it is tested here rather than through an export**, for the reason
`test_action_parameter_transfer.py` gives one module over: the interesting cases
are the ones a real workspace makes hard to build. An export only ever holds ids
it can resolve — except for the one this platform genuinely can reach, a rule
naming a link type somebody deleted, which nothing refuses today.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import action_rule_transfer as transfer  # noqa: E402

TICKET = "11111111-1111-1111-1111-111111111111"
ISSUE = "22222222-2222-2222-2222-222222222222"
RAISED = "aaaaaaaa-0000-0000-0000-000000000001"
GONE = "99999999-9999-9999-9999-999999999999"

TYPES = {TICKET: "ticket", ISSUE: "issue"}
LINKS = {RAISED: "raised_by"}


def named(rule: dict, *, types=None, links=None) -> dict:
    return transfer.to_names(
        rule,
        type_names=TYPES if types is None else types,
        link_names=LINKS if links is None else links,
    )


# ---- the six fields that held a uuid -------------------------------------------
def test_the_type_an_object_rule_names_becomes_a_name() -> None:
    """p.75's create, modify and delete, which all spell it the same way. Each
    is asserted rather than one standing for three: they are three entries in a
    table, and a table with one row tested is a table."""
    for kind in ("create_object", "modify_object", "delete_object"):
        written = named({"kind": kind,
                         "config": {"object_type": ISSUE, "object": "who"}})
        assert written == {"object_type": "issue", "object": "who"}, kind


def test_the_link_a_link_rule_names_becomes_a_name() -> None:
    for kind in ("create_link", "delete_link"):
        written = named({"kind": kind,
                         "config": {"link_type": RAISED, "object": "who"}})
        assert written == {"link_type": "raised_by", "object": "who"}, kind


def test_a_notify_rules_recipient_type_becomes_a_name() -> None:
    """p.96's object-property recipient: "make sure the property stores the
    Foundry user or group ID as a string". The type it reads that property off
    is a uuid, nested one level deeper than the five above."""
    written = named({"kind": "notify", "config": {
        "recipients": {"kind": "object_property", "parameter": "who",
                       "object_type": ISSUE, "property": "owner_id"},
        "subject": "Hello"}})
    assert written["recipients"] == {
        "kind": "object_property", "parameter": "who",
        "object_type": "issue", "property": "owner_id"}
    assert written["subject"] == "Hello"


def test_the_row_being_exported_is_not_edited() -> None:
    """**The nested rewrite is the one that could reach back.** `config` is
    copied before it is changed and so is `recipients`; without the second copy
    this would rename the dictionary the caller still holds, which for an export
    is the row it read from the database."""
    recipients = {"kind": "object_property", "object_type": ISSUE}
    rule = {"kind": "notify", "config": {"recipients": recipients}}
    named(rule)
    assert recipients["object_type"] == ISSUE
    assert rule["config"]["recipients"] is recipients


# ---- what is left alone --------------------------------------------------------
def test_a_rule_with_no_object_type_gains_none() -> None:
    """p.75's rules take `object_type` optionally, and absent means this
    action's own subject. Inventing a key here would turn "the object I am
    applied to" into a claim about a named type."""
    written = named({"kind": "modify_object",
                     "config": {"property": "state", "parameter": "state"}})
    assert written == {"property": "state", "parameter": "state"}


def test_a_rule_of_another_kind_is_untouched() -> None:
    """A webhook rule's `webhook` is an id and stays one — it is not in the
    ontology, so there is nothing in the file to name it against. p.67's
    refusal is what covers it, and it is asserted below."""
    config = {"webhook": GONE, "mode": "writeback", "inputs": {}}
    assert named({"kind": "webhook", "config": config}) == config


def test_the_rest_of_a_config_travels_verbatim() -> None:
    """Everything a rule says other than these six fields already names things
    by name — properties, parameters, templates — so a translator that touched
    anything else would be changing what the rule does."""
    written = named({"kind": "create_object", "config": {
        "object_type": ISSUE, "primary_key": "key",
        "properties": {"title": "name", "state": "state"}}})
    assert written["properties"] == {"title": "name", "state": "state"}
    assert written["primary_key"] == "key"


# ---- a reference this ontology cannot name -------------------------------------
def test_a_link_this_ontology_does_not_have_is_dropped_not_written() -> None:
    """**Never as an id** (§342's rule, one table over), and this one is
    reachable rather than defensive: `delete_link_type` refuses a link an action
    *parameter* walks and nothing refuses one an action *rule* names, so a rule
    holding a dangling link id is a state this platform can be in today.

    A file carrying that id would look portable and mean nothing anywhere. A
    file with the key missing says nothing it cannot say — and the day action
    types are applied, `_validate_definition` refuses it by name with "a link
    rule names a link type this workspace does not have", which is the truth
    about the rule as it already stands.
    """
    written = named({"kind": "create_link",
                     "config": {"link_type": GONE, "object": "who"}})
    assert written == {"object": "who"}


def test_a_type_this_ontology_does_not_have_is_dropped_not_written() -> None:
    written = named({"kind": "delete_object",
                     "config": {"object_type": GONE, "object": "who"}})
    assert written == {"object": "who"}


def test_dropping_one_field_does_not_take_the_rest_of_the_rule() -> None:
    """**The negative control.** A version that gave up on the whole config
    would pass both tests above, and would silently turn a broken rule into an
    empty one."""
    written = named({"kind": "create_link", "config": {
        "link_type": GONE, "object": "who", "target": "other"}})
    assert written == {"object": "who", "target": "other"}


# ---- and back again (§344) -----------------------------------------------------
def to_ids(rule: dict, *, types=None, links=None, where="r") -> dict:
    return transfer.to_ids(
        rule,
        type_ids={v: k for k, v in (TYPES if types is None else types).items()},
        link_ids={v: k for k, v in (LINKS if links is None else links).items()},
        where=where,
    )


def test_a_rules_references_survive_the_round_trip() -> None:
    """Asserted as one equality over each kind, so a translator that carried the
    reference and lost the rest of the config would fail here rather than pass a
    list of fields somebody remembered."""
    for rule in (
        {"kind": "create_object",
         "config": {"object_type": ISSUE, "primary_key": "key",
                    "properties": {"title": "name"}}},
        {"kind": "create_link",
         "config": {"link_type": RAISED, "object": "who", "target": "other"}},
        {"kind": "notify", "config": {
            "recipients": {"kind": "object_property", "parameter": "who",
                           "object_type": ISSUE, "property": "owner_id"},
            "subject": "Hello"}},
    ):
        assert to_ids({"kind": rule["kind"], "config": named(rule)}) \
            == rule["config"], rule["kind"]


def test_a_rule_naming_nothing_gains_nothing() -> None:
    """p.75's `object_type` is optional and absent means this action's own
    subject, so a round trip that invented the key would turn "the object I am
    applied to" into a claim about a named type."""
    config = {"property": "state", "parameter": "state"}
    assert to_ids({"kind": "modify_object", "config": config}) == config


def test_a_key_the_file_dropped_stays_absent() -> None:
    """§343 drops a reference this ontology could not name rather than writing
    an id. Refusing *here* would have to invent the field that is missing;
    `_validate_definition` names it a moment later — "a link rule names a link
    type this workspace does not have" — which is the truth about the rule."""
    assert to_ids({"kind": "create_link", "config": {"object": "who"}}) \
        == {"object": "who"}


def test_a_name_this_workspace_lacks_is_refused() -> None:
    """The mirror of §343's outward rule: dropping it on the way in would write
    a rule that does nothing and report the file as applied."""
    for rule in (
        {"kind": "create_link", "config": {"link_type": "gone"}},
        {"kind": "delete_object", "config": {"object_type": "gone"}},
        {"kind": "notify", "config": {
            "recipients": {"kind": "object_property", "object_type": "gone"}}},
    ):
        try:
            to_ids(rule, where="ticket.rename rule 2")
        except ValueError as refusal:
            assert "ticket.rename rule 2" in str(refusal), rule
        else:
            raise AssertionError(f"not refused: {rule}")


def test_the_document_being_applied_is_not_edited() -> None:
    """The nested rewrite again, in the direction that reads from a file the
    caller still holds — and an import reads the same document twice, once to
    plan and once to apply."""
    recipients = {"kind": "object_property", "object_type": "issue"}
    rule = {"kind": "notify", "config": {"recipients": recipients}}
    to_ids(rule)
    assert recipients["object_type"] == "issue"


# ---- what `check_references` reads ---------------------------------------------
def test_the_references_a_rule_makes_are_reported_with_their_kind() -> None:
    assert list(transfer.references(
        {"kind": "create_link", "config": {"link_type": "raised_by"}}
    )) == [("raised_by", "link type")]
    assert list(transfer.references(
        {"kind": "modify_object", "config": {"object_type": "issue"}}
    )) == [("issue", "object type")]
    assert list(transfer.references({"kind": "notify", "config": {
        "recipients": {"kind": "object_property", "object_type": "issue"}}
    })) == [("issue", "object type")]


def test_a_rule_naming_nothing_reports_nothing() -> None:
    """Every rule written before §343, and most of them after — so a
    `check_references` built on this must not start refusing files that were
    fine."""
    assert list(transfer.references(
        {"kind": "modify_object", "config": {"property": "a", "parameter": "a"}}
    )) == []
    assert list(transfer.references({"kind": "webhook", "config": {
        "webhook": GONE, "mode": "writeback"}})) == []


# ---- p.67's references, the ones that leave the ontology ------------------------
def test_a_webhook_rule_reaches_outside_the_ontology() -> None:
    """db 0067 scopes a webhook to a workspace *and* a project, so its id means
    nothing anywhere else — the shape p.67's `UnreferencedRuleSets` is about,
    which §326 recorded as having no cause here."""
    assert transfer.outside_ontology(
        {"kind": "webhook", "config": {"webhook": GONE}}
    ) == ["a webhook"]


def test_a_static_recipient_list_reaches_outside_the_ontology() -> None:
    """p.94's list of user ids. A user is organisation-scoped, so this survives
    a copy inside one organisation and not between two — and an export cannot
    know which it is about to be imported into."""
    assert transfer.outside_ontology({"kind": "notify", "config": {
        "recipients": {"kind": "static", "user_ids": [GONE]}}
    }) == ["a list of named recipients"]


def test_a_notify_rule_that_reads_a_property_stays_inside() -> None:
    """**The one that distinguishes the check from "is it a notify rule".**
    p.96's object-property recipient names an object type and a property, both
    of which are in the file, so it travels — and a refusal that stopped every
    notification from being copied would be refusing the wrong document."""
    assert transfer.outside_ontology({"kind": "notify", "config": {
        "recipients": {"kind": "object_property", "parameter": "who",
                       "object_type": ISSUE, "property": "owner_id"}}}) == []


# ---- p.65's hand-edited file ---------------------------------------------------
def test_a_config_that_is_not_an_object_names_nothing() -> None:
    """**p.65's premise is somebody editing this JSON in a text editor**, so a
    `config` that is a string is a file this platform will be handed. Both
    readers are asked, because the plan calls both on every rule in the
    document and either one reaching for `.get` on a string turns a typo into a
    500 with nothing in it (§340 shipped exactly that defect for a link's
    missing `cardinality`).
    """
    broken = {"kind": "create_link", "config": "link_type: raised_by"}
    assert list(transfer.references(broken)) == []
    assert transfer.outside_ontology({"kind": "webhook", "config": "oops"}) == []


def test_a_rule_that_names_no_webhook_reaches_nothing() -> None:
    """The other half of §318's pair: `kind == "webhook"` is not the question,
    "does it name one" is."""
    assert transfer.outside_ontology({"kind": "webhook", "config": {}}) == []
    assert transfer.outside_ontology({"kind": "notify", "config": {
        "recipients": {"kind": "static", "user_ids": []}}}) == []
    assert transfer.outside_ontology(
        {"kind": "modify_object", "config": {"property": "a"}}) == []
