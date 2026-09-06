"""The notification side effect (Foundry `action-types` p.87-101; §257).

> "Notifications can be added to an action through the Add new rule dropdown
> menu. Configuring a notification requires specification of recipients and
> content." (p.89)

**This file needs no database**, and that is the shape of the feature rather
than a choice about testing: rendering a notification is substitution over
values the caller already holds, deciding who gets it is a lookup in a dict,
and every refusal is about a config somebody typed. The delivery - the insert,
and the ontology read it renders from - is in the route, and its tests are
where the transaction is.

The three rules from the source that are easy to get subtly wrong each have a
test named after the failure they prevent, not after the function they call.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import notifications  # noqa: E402

PARAMETERS = {"priority": "string", "assignee": "string", "alert": "object"}
WORKSPACE_PROPERTIES = {
    "type-1": {"case_manager": "string", "priority": "string", "opened": "date"}
}


def rule(**over) -> dict:
    return {
        "recipients": {"kind": "static", "user_ids": ["u1"]},
        "subject": "Priority changed",
        "body": "It is now {{{priority}}}.",
        **over,
    }


# ---- p.95's truncation ---------------------------------------------------------
def test_content_too_long_is_shortened_and_says_so() -> None:
    """p.95: "any content longer than the allowed maximum lengths will be
    truncated and indicated by trailing `...`".

    **Truncated rather than refused**, and the difference matters: the length
    depends on the *data*, so a template that fits for one object would fail
    the action for another - and the person who typed the template is not the
    person who would meet that failure.
    """
    out = notifications.truncate("x" * 300, notifications.MAX_SUBJECT)
    assert len(out) == notifications.MAX_SUBJECT
    assert out.endswith("...")


def test_the_ellipsis_fits_inside_the_limit_rather_than_after_it() -> None:
    """An off-by-one that only shows up on the one value long enough to reach
    it: the same maximum is a CHECK on the column (db 0066), so a truncation
    that added three characters past the limit would be a failed insert."""
    for limit in (4, 10, notifications.MAX_BODY):
        assert len(notifications.truncate("y" * (limit + 50), limit)) == limit


def test_content_that_fits_is_left_exactly_alone() -> None:
    # Presence before absence: without this, a `truncate` that always
    # abbreviated would pass every test above.
    assert notifications.truncate("short", 250) == "short"
    assert notifications.truncate("x" * 250, 250) == "x" * 250


# ---- p.92's references ---------------------------------------------------------
def test_a_parameter_is_substituted() -> None:
    assert notifications.render(
        "Now {{{priority}}}.", values={"priority": "High"}
    ) == "Now High."


def test_an_object_parameters_property_is_substituted() -> None:
    """p.101: "If your selection is an object parameter, you will be asked to
    select which property you want to reference"."""
    assert notifications.render(
        "Was {{{alert.priority}}}.",
        values={}, objects={"alert": {"priority": "Low"}},
    ) == "Was Low."


def test_the_two_user_references_are_the_ones_p101_names() -> None:
    """p.101: "you can select the `Recipient`, `Current User`, and any
    parameter options"."""
    out = notifications.render(
        "Hello {{{recipient}}}, from {{{current_user}}}.",
        values={},
        recipient={"display_name": "Ada"},
        actor={"display_name": "Grace"},
    )
    assert out == "Hello Ada, from Grace."


def test_a_user_reference_can_name_an_attribute() -> None:
    assert notifications.render(
        "{{{recipient.email}}}", values={},
        recipient={"display_name": "Ada", "email": "ada@example.com"},
    ) == "ada@example.com"


def test_an_unset_value_renders_as_a_gap_rather_than_the_template() -> None:
    """Leaving `{{{priority}}}` on screen tells the recipient about the
    template; leaving a gap tells them about the value."""
    assert notifications.render("Now {{{priority}}}.", values={}) == "Now ."


def test_a_missing_value_is_not_the_word_None() -> None:
    """A template that renders `None` into somebody's inbox is a template that
    leaked Python."""
    out = notifications.render("[{{{priority}}}]", values={"priority": None})
    assert out == "[]"


def test_a_boolean_reads_as_a_word_rather_than_as_Python() -> None:
    assert notifications.render(
        "{{{flag}}}", values={"flag": True}
    ) == "true"


def test_double_handlebars_are_not_a_reference() -> None:
    """**Three braces, and the count is not decoration.** The two-brace
    convention escapes its substitution in every templating language that has
    both; copying the syntax without the semantics would produce a template
    that looked like every other one and quietly escaped a person's name."""
    assert notifications.render(
        "{{priority}}", values={"priority": "High"}
    ) == "{{priority}}"


def test_references_are_reported_in_order_and_with_repeats() -> None:
    assert notifications.references(
        "{{{a}}} then {{{b}}} then {{{a}}}"
    ) == ["a", "b", "a"]


# ---- p.89's two halves, refused ------------------------------------------------
def test_a_rule_with_no_recipients_is_refused() -> None:
    with pytest.raises(notifications.NotificationError, match="recipients"):
        notifications.parse({"subject": "x"}, parameters=PARAMETERS)


def test_a_rule_with_no_subject_is_refused() -> None:
    with pytest.raises(notifications.NotificationError, match="subject"):
        notifications.parse(
            {"recipients": {"kind": "static", "user_ids": ["u1"]}},
            parameters=PARAMETERS,
        )


def test_the_function_recipient_kind_is_refused_and_says_why() -> None:
    """p.90's fourth option needs Functions, which §1.3 marks ○. A dropdown
    entry whose only outcome is a save that fails is worse than an absent one
    (§214), and the refusal names the reason rather than the rule."""
    with pytest.raises(notifications.NotificationError) as exc:
        notifications.parse(
            rule(recipients={"kind": "function", "function": "f"}),
            parameters=PARAMETERS,
        )
    assert "Functions" in str(exc.value)


def test_a_static_list_needs_somebody_on_it() -> None:
    with pytest.raises(notifications.NotificationError):
        notifications.parse(
            rule(recipients={"kind": "static", "user_ids": []}),
            parameters=PARAMETERS,
        )


def test_a_static_list_may_not_exceed_p94s_five_hundred() -> None:
    many = [f"u{i}" for i in range(notifications.MAX_RECIPIENTS + 1)]
    with pytest.raises(notifications.NotificationError, match="500"):
        notifications.parse(
            rule(recipients={"kind": "static", "user_ids": many}),
            parameters=PARAMETERS,
        )
    # And one fewer is fine, which is what stops this passing against a parse
    # that refused every static list.
    notifications.parse(
        rule(recipients={"kind": "static", "user_ids": many[:-1]}),
        parameters=PARAMETERS,
    )


def test_a_parameter_recipient_must_be_a_parameter() -> None:
    with pytest.raises(notifications.NotificationError, match="not a parameter"):
        notifications.parse(
            rule(recipients={"kind": "parameter", "parameter": "nobody"}),
            parameters=PARAMETERS,
        )


def test_an_object_property_recipient_is_checked_against_the_ontology() -> None:
    """p.100's tutorial case: the recipient is a property of the object being
    edited."""
    parsed = notifications.parse(
        rule(recipients={
            "kind": "object_property", "parameter": "alert",
            "object_type": "type-1", "property": "case_manager",
        }),
        parameters=PARAMETERS,
        workspace_properties=WORKSPACE_PROPERTIES,
    )
    assert parsed["recipients"]["property"] == "case_manager"


def test_an_object_property_recipient_needs_a_resolved_ontology() -> None:
    """§221's rule one service over: a caller that has not resolved the
    ontology has checked no property, so its absence is a refusal rather than
    a permission."""
    with pytest.raises(notifications.NotificationError, match="did not resolve"):
        notifications.parse(
            rule(recipients={
                "kind": "object_property", "parameter": "alert",
                "object_type": "type-1", "property": "case_manager",
            }),
            parameters=PARAMETERS,
        )


def test_a_recipient_property_that_is_not_a_string_is_refused() -> None:
    """p.96: "make sure the property stores the Foundry user or group ID as a
    string".

    Refused where the rule is typed rather than silently sending nothing at run
    time, because the person who typed it is the one who can fix it.
    """
    with pytest.raises(notifications.NotificationError, match="user id"):
        notifications.parse(
            rule(recipients={
                "kind": "object_property", "parameter": "alert",
                "object_type": "type-1", "property": "opened",
            }),
            parameters=PARAMETERS,
            workspace_properties=WORKSPACE_PROPERTIES,
        )


def test_a_reference_to_something_that_is_not_a_parameter_is_refused() -> None:
    with pytest.raises(notifications.NotificationError, match="neither a"):
        notifications.parse(
            rule(body="{{{nonsense}}}"), parameters=PARAMETERS
        )


def test_the_user_references_are_accepted_without_being_parameters() -> None:
    notifications.parse(
        rule(subject="For {{{recipient}}}", body="From {{{current_user}}}"),
        parameters=PARAMETERS,
    )


def test_a_dotted_reference_is_checked_against_the_object_type() -> None:
    """**Checked all the way down when it can be.** A head that names an object
    parameter and a tail that names nothing on it renders as a gap, and a gap
    is what a recipient sees rather than what an author does."""
    with pytest.raises(notifications.NotificationError, match="no 'nonsense'"):
        notifications.parse(
            rule(body="{{{alert.nonsense}}}"),
            parameters=PARAMETERS,
            workspace_properties=WORKSPACE_PROPERTIES,
            object_parameter_types={"alert": "type-1"},
        )


def test_a_dotted_reference_that_resolves_is_accepted() -> None:
    # Presence before absence: without this, a check that refused every dotted
    # reference would pass the test above.
    notifications.parse(
        rule(body="{{{alert.priority}}}"),
        parameters=PARAMETERS,
        workspace_properties=WORKSPACE_PROPERTIES,
        object_parameter_types={"alert": "type-1"},
    )


def test_a_dotted_reference_is_left_alone_when_the_type_is_unknown() -> None:
    """The caller that did not resolve the ontology gets the head check and no
    more. Refusing here instead would make a template unsaveable because of
    something about the *caller* rather than about the template."""
    notifications.parse(rule(body="{{{alert.anything}}}"), parameters=PARAMETERS)


def test_a_link_needs_both_halves() -> None:
    """p.91's link is a button with a destination. Either half alone is half a
    control, and db 0066's CHECK says the same thing about the stored row."""
    for link in ({"url": "/x"}, {"text": "Open"}):
        with pytest.raises(notifications.NotificationError, match="both"):
            notifications.parse(rule(link=link), parameters=PARAMETERS)


def test_a_links_references_are_checked_too() -> None:
    with pytest.raises(notifications.NotificationError, match="link references"):
        notifications.parse(
            rule(link={"url": "/o/{{{nope}}}", "text": "Open"}),
            parameters=PARAMETERS,
        )


def test_an_unknown_permission_mode_is_refused() -> None:
    with pytest.raises(notifications.NotificationError, match="permission mode"):
        notifications.parse(rule(permissions="whatever"), parameters=PARAMETERS)


def test_the_default_permission_mode_is_p96s_strict_one() -> None:
    """p.96: "Require all users to have permissions (default)". The default is
    the one that refuses the whole action, which is the direction that cannot
    quietly send somebody data they may not see."""
    assert notifications.parse(rule(), parameters=PARAMETERS)["permissions"] == "all"


# ---- who it reaches -------------------------------------------------------------
def test_a_static_list_is_its_own_answer() -> None:
    assert notifications.recipient_ids(
        rule(recipients={"kind": "static", "user_ids": ["u1", "u2"]}), values={}
    ) == ["u1", "u2"]


def test_a_parameter_recipient_reads_the_submitted_value() -> None:
    assert notifications.recipient_ids(
        rule(recipients={"kind": "parameter", "parameter": "assignee"}),
        values={"assignee": "u9"},
    ) == ["u9"]


def test_a_property_holding_several_ids_is_several_recipients() -> None:
    """p.90: "This is also possible for lists of Foundry user and group IDs"."""
    assert notifications.recipient_ids(
        rule(recipients={
            "kind": "object_property", "parameter": "alert",
            "property": "case_manager",
        }),
        values={},
        objects={"alert": {"case_manager": ["u1", "u2"]}},
    ) == ["u1", "u2"]


def test_the_same_recipient_named_twice_is_notified_once() -> None:
    """p.90's "sent to each recipient individually" is one message each, not
    one per mention."""
    assert notifications.recipient_ids(
        rule(recipients={"kind": "static", "user_ids": ["u1", "u1", "u2"]}),
        values={},
    ) == ["u1", "u2"]


def test_a_comma_separated_string_is_one_recipient_not_two() -> None:
    """A decision rather than an omission: a property holding `"a,b"` is one
    value that happens to contain a comma, and splitting it would make a
    display name with a comma in it into two recipients."""
    assert notifications.recipient_ids(
        rule(recipients={"kind": "parameter", "parameter": "assignee"}),
        values={"assignee": "u1,u2"},
    ) == ["u1,u2"]


def test_an_unset_recipient_parameter_reaches_nobody() -> None:
    """**Nobody, rather than everybody.** The safe direction for a missing
    value is the narrow one - decision 0002's rule about a filter, applied to
    an audience."""
    assert notifications.recipient_ids(
        rule(recipients={"kind": "parameter", "parameter": "assignee"}), values={}
    ) == []


# ---- the whole thing ------------------------------------------------------------
def test_a_rendered_notification_is_substituted_then_truncated() -> None:
    """**In that order, because that is where the length is decided.** A
    200-character subject with a parameter in it can render to anything."""
    out = notifications.rendered(
        {"subject": "Alert: {{{priority}}}", "body": "{{{note}}}"},
        values={"priority": "High", "note": "z" * 2000},
    )
    assert out["subject"] == "Alert: High"
    assert len(out["body"]) == notifications.MAX_BODY
    assert out["body"].endswith("...")


def test_a_link_is_rendered_and_not_truncated() -> None:
    """A URL cut short is a link to somewhere else, and a button label is not
    the content p.95's limits are about."""
    out = notifications.rendered(
        {"subject": "s", "body": "", "link": {
            "url": "/objects/{{{alert.id}}}", "text": "Open {{{priority}}}",
        }},
        values={"priority": "High"},
        objects={"alert": {"id": "A-1"}},
    )
    assert out["link_url"] == "/objects/A-1"
    assert out["link_text"] == "Open High"


def test_a_notification_without_a_link_has_no_link_fields() -> None:
    out = notifications.rendered({"subject": "s", "body": ""}, values={})
    assert "link_url" not in out
    assert "link_text" not in out


# ---- p.96's two failure modes ----------------------------------------------------
def test_the_strict_mode_refuses_the_whole_action() -> None:
    """p.96: "If any recipients do not have the required access, an error will
    be shown when attempting to apply the Action. If this happens, no data will
    be edited and no notifications will be sent."

    **A refusal about the action, not about the notification** — which is why
    it is checked before anything is written. "No data will be edited" is not
    something a caller can honour once it has edited the data.
    """
    with pytest.raises(notifications.NotificationError) as exc:
        notifications.deliverable(
            "all", requested=["u1", "u2"], permitted={"u1"}
        )
    assert "u2" in str(exc.value)
    assert "nothing has been changed" in str(exc.value)


def test_the_strict_mode_is_happy_when_everybody_can_see_it() -> None:
    # Presence before absence: without this, a `deliverable` that refused every
    # strict call would pass the test above.
    assert notifications.deliverable(
        "all", requested=["u1", "u2"], permitted={"u1", "u2"}
    ) == ["u1", "u2"]


def test_the_lenient_mode_sends_to_whoever_can_see_it() -> None:
    """p.96: "If at least one user can see the object, the Action will succeed.
    Only users with permissions will receive notifications"."""
    assert notifications.deliverable(
        "any", requested=["u1", "u2"], permitted={"u2"}
    ) == ["u2"]


def test_the_lenient_mode_still_fails_when_nobody_can_see_it() -> None:
    """"At least one" is a floor, not a wish: a notification nobody may read is
    an action that quietly did nothing it said it would."""
    with pytest.raises(notifications.NotificationError, match="none of"):
        notifications.deliverable("any", requested=["u1"], permitted=set())


def test_nobody_to_notify_is_not_a_permission_failure() -> None:
    """A rule whose recipient property is unset on this object has not failed a
    permission check — it has found no one. p.96 is about access, and absence
    is not a denial."""
    for mode in notifications.PERMISSION_MODES:
        assert notifications.deliverable(mode, requested=[], permitted=set()) == []


def test_the_refusal_names_who_and_what_to_do() -> None:
    """A refusal that said only "permissions" would send somebody to read the
    documentation; this one names the person and both ways out."""
    with pytest.raises(notifications.NotificationError) as exc:
        notifications.deliverable("all", requested=["ada"], permitted=set())
    message = str(exc.value)
    assert "ada" in message
    assert "`any`" in message
