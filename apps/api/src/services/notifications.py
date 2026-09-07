"""The notification side effect (Foundry `action-types` p.87-101).

> "Notifications allow you to flexibly configure how a user should be notified
> when an action is applied." (p.87)

> "Notifications can be added to an action through the Add new rule dropdown
> menu. Configuring a notification requires specification of **recipients** and
> **content**." (p.89)

**A rule, not a resource.** p.89 puts it in the same *Add new rule* menu as the
five that already exist, so `notify` is a sixth `action_rule_kind` (db 0066)
rather than a table hanging off the action type. The two halves it needs are
the two p.89 names, and each is its own refusal below.

Everything here is a function over data, and that is the whole point: rendering
a notification is string substitution over values the caller already has, and a
wrong answer is a line rather than a fixture. What is *not* here is delivery -
the insert, and the reading of the ontology it renders from, are in the route
that runs the action, because that is where the transaction is.

Three rules from the source that are easy to get subtly wrong
------------------------------------------------------------
*The content is rendered against the world **before** the action's edits.*
p.92: "Any Ontology data used for generating notification content will reflect
the state of the Ontology before edits of the current Action are applied." So
`render` is given the *old* property values, and the caller is what has to
honour that - stated here because a caller passing the post-edit dict would
produce something that looks completely right.

*Content is truncated, not refused.* p.95: "these maximum content lengths are
validated and truncated when notifications are rendered … any content longer
than the allowed maximum lengths will be truncated and indicated by trailing
`...`". A refusal would be the wrong answer: the length depends on the *data*,
so a template that is fine for one object would fail the action for another,
and the person who typed the template is not the person who would meet it.

*A recipient is a user id, and nothing else.* p.100: "the recipient must always
be a Foundry user ID. If this property contains something else such as string
email addresses, no notifications will be sent." p.96: "Sending directly to
email addresses is not supported." So a value that is not a user id is dropped
rather than guessed at.

What is deliberately absent
---------------------------
**`From a function` recipients and content** (p.90, p.92). This platform has no
Functions; §1.3 marks them ○. A dropdown entry whose only outcome is a save
that fails is worse than an absent one (§214), and the row says so.

**Email delivery, and with it p.92's Advanced Email Configuration and p.95's
redaction.** There is no mail gateway here. p.91 makes in-platform delivery the
other half of the same feature - "they may still view their notifications when
logged into Foundry by going to Notifications" - so what is built is that half,
whole, rather than both halves partly.
"""
from __future__ import annotations

import re  # for the `re.Match` annotation in `render`; the pattern lives in `templates`
from typing import Any

from . import templates

#: p.94: "There is a maximum of 500 recipients for a single Action notification
#: when the content is configured directly in the configuration dialog using
#: the Template option." The 50-recipient limit on the same page is the
#: *function* content path, which does not exist here.
MAX_RECIPIENTS = 500

#: p.95: "The maximum subject length is 250 characters. The maximum body length
#: is 1,000 characters."
MAX_SUBJECT = 250
MAX_BODY = 1000

#: How a recipient list is specified. p.90's four, less the one that needs
#: Functions.
#:
#: * `static` - "a set of users or groups who will always be notified";
#: * `parameter` - "a parameter to the action that is a Foundry user or group
#:   ID";
#: * `object_property` - "an object parameter … one of the properties of that
#:   object contains a Foundry user or group ID", which is the tutorial's own
#:   case (p.100) and the one that makes a notification follow the data.
RECIPIENT_KINDS = ("static", "parameter", "object_property")

#: p.96's two ways of handling a recipient who cannot see the data being
#: rendered. **`all` is the default, and it is the strict one**: "If any
#: recipients do not have the required access, an error will be shown … no data
#: will be edited and no notifications will be sent."
PERMISSION_MODES = ("all", "any")

#: p.92: "Triple handlebars may be used to reference parameters and user
#: attributes in the Subject, Body, and Link."
#:
#: Triple rather than double, and it is worth saying why the count matters: the
#: two-brace convention escapes its substitution in every templating language
#: that has both, and three does not. Copying the syntax without the semantics
#: would produce a template that looked like every other one and quietly
#: HTML-escaped a person's name.
#:
#: **Moved to `services/templates` in §259**, which is when webhooks gained
#: templates of their own and a second `re.compile` of this expression would
#: have become §191's mirror: two copies free to be identically wrong, with a
#: drift guard comparing them only to each other. The name stays here because
#: it is what this module's own code and its tests call it.
_REFERENCE = templates.REFERENCE

#: The two references that are not parameters. p.101: "you can select the
#: `Recipient`, `Current User`, and any parameter options from the dropdown
#: list in order to generate the correct reference to those user attributes."
USER_REFERENCES = ("recipient", "current_user")


class NotificationError(ValueError):
    """A notification rule that cannot be saved, or content that cannot be
    rendered, in a sentence somebody configuring an action can act on."""


def truncate(text: str, limit: int) -> str:
    """p.95's rule: too long is shortened and *says so*, never refused.

    The ellipsis is inside the limit rather than added to it - a truncation
    that pushed the value one character past the maximum would fail the CHECK
    the same maximum puts on the column (db 0066), which is the sort of
    off-by-one that only shows up on the one row long enough to reach it.
    """
    if len(text) <= limit:
        return text
    if limit <= 3:
        return "." * limit
    return text[: limit - 3] + "..."


def references(template: str) -> list[str]:
    """Every `{{{name}}}` in a template, in the order they appear.

    Duplicates kept: a template naming one parameter twice is two references,
    and a caller counting them is counting occurrences.
    """
    return _REFERENCE.findall(template or "")


def parse(
    config: Any,
    *,
    parameters: dict[str, str],
    workspace_properties: "dict[str, dict[str, str]] | None" = None,
    object_parameter_types: "dict[str, str] | None" = None,
) -> dict[str, Any]:
    """Validate one `notify` rule's config, or refuse in a sentence.

    `parameters` is `{api_name: data_type}` for this action;
    `workspace_properties` is `{object type id: {api_name: data_type}}`, which
    is what `actions.properties_by_type` already returns.

    **The rule names the object type, not the parameter.** A parameter of type
    `object` carries no object type of its own (db 0044) - every rule that
    consumes one says which type it means, and a notify rule reading a property
    off one is no different. Doing it any other way here would be a second
    convention for the same fact.

    `workspace_properties` is needed only by the `object_property` recipient
    kind, and its **absence is a refusal rather than a permission**: a caller
    that has not resolved the ontology has checked no property, which is §221's
    rule one service over.

    `object_parameter_types` is `{parameter: object type id}`, which
    `actions.object_parameter_types` reads off the action's own rules. It is
    what makes `{{{alert.priority}}}` checkable: without it a dotted reference
    could only be checked as far as its head, and "alert has no priority" would
    be discovered by a recipient reading a gap where a value should be.
    """
    if not isinstance(config, dict):
        raise NotificationError("a notify rule needs a configuration object")

    recipients = config.get("recipients")
    if not isinstance(recipients, dict):
        raise NotificationError(
            "a notify rule needs `recipients` (p.89: recipients and content)"
        )
    kind = str(recipients.get("kind", ""))
    if kind not in RECIPIENT_KINDS:
        raise NotificationError(
            f"unknown recipient kind {kind!r} "
            f"(supported: {', '.join(RECIPIENT_KINDS)}). p.90's `From a "
            "function` needs Functions, which this platform does not have"
        )

    out_recipients: dict[str, Any] = {"kind": kind}
    if kind == "static":
        users = recipients.get("user_ids")
        if not isinstance(users, list) or not users:
            raise NotificationError(
                "a static recipient list needs at least one `user_ids` entry"
            )
        if len(users) > MAX_RECIPIENTS:
            raise NotificationError(
                f"a notification may name at most {MAX_RECIPIENTS} recipients "
                f"(given {len(users)}) - p.94"
            )
        out_recipients["user_ids"] = [str(u) for u in users]
    elif kind == "parameter":
        name = str(recipients.get("parameter", ""))
        if name not in parameters:
            raise NotificationError(
                f"a notify rule reads {name!r} as its recipient, which is not "
                "a parameter of this action"
            )
        out_recipients["parameter"] = name
    else:  # object_property
        name = str(recipients.get("parameter", ""))
        prop = str(recipients.get("property", ""))
        type_id = str(recipients.get("object_type", ""))
        if workspace_properties is None:
            raise NotificationError(
                "an object-property recipient is checked against the object "
                "type's declared properties, which this caller did not resolve"
            )
        if parameters.get(name) != "object":
            raise NotificationError(
                f"a notify rule reads a property of {name!r}, which is not an "
                "object parameter of this action"
            )
        declared = workspace_properties.get(type_id)
        if declared is None:
            raise NotificationError(
                "a notify rule names an object type this workspace does not have"
            )
        if prop not in declared:
            raise NotificationError(
                f"a notify rule reads {prop!r} from {name!r}, which is not a "
                "property of that object type"
            )
        # p.96: "make sure the property stores the Foundry user or group ID as
        # a string". Refused here rather than silently sending nothing at run
        # time, because the person who typed the rule is the one who can fix it
        # and the person who runs the action is not.
        if declared[prop] != "string":
            raise NotificationError(
                f"{prop!r} is a {declared[prop]} and a recipient is a user id, "
                "which is stored as a string (p.96)"
            )
        out_recipients["parameter"] = name
        out_recipients["object_type"] = type_id
        out_recipients["property"] = prop

    subject = str(config.get("subject") or "").strip()
    if not subject:
        raise NotificationError("a notify rule needs a subject")
    body = str(config.get("body") or "")

    def check(field: str, template: str) -> None:
        for ref in references(template):
            # **A name that is in `parameters` whole is a name**, whatever it
            # contains. §260 puts a writeback webhook's outputs into the same
            # namespace under `webhook.<output>` (p.110: "use in a subsequent
            # notification"), and splitting *that* at the dot asks whether the
            # action has a parameter called `webhook`, which is a question
            # about the wrong thing. Checked before the split rather than
            # after, because after it the head is already the wrong string.
            if ref in parameters:
                continue
            # A dotted reference is an object parameter's property -
            # `{{{alert.priority}}}` - which p.101 generates when "your
            # selection is an object parameter".
            head, _, tail = ref.partition(".")
            if head in USER_REFERENCES:
                continue
            if head not in parameters:
                raise NotificationError(
                    f"the {field} references {ref!r}, which is neither a "
                    f"parameter of this action nor one of "
                    f"{', '.join(USER_REFERENCES)}"
                )
            if not tail:
                continue
            # **Checked all the way down when it can be.** A head that names an
            # object parameter and a tail that names nothing on it renders as a
            # gap, and a gap is what a recipient sees rather than what an
            # author does.
            type_id = (object_parameter_types or {}).get(head)
            declared = (workspace_properties or {}).get(str(type_id))
            if declared is None:
                continue
            if tail not in declared:
                raise NotificationError(
                    f"the {field} references {ref!r}, and {head!r} has no "
                    f"{tail!r} property"
                )

    check("subject", subject)
    check("body", body)

    mode = str(config.get("permissions") or "all")
    if mode not in PERMISSION_MODES:
        raise NotificationError(
            f"unknown permission mode {mode!r} "
            f"(supported: {', '.join(PERMISSION_MODES)}) - p.96"
        )

    out: dict[str, Any] = {
        "recipients": out_recipients,
        "subject": subject,
        "body": body,
        "permissions": mode,
    }

    link = config.get("link")
    if link is not None:
        if not isinstance(link, dict):
            raise NotificationError("a notify rule's `link` must be an object")
        url = str(link.get("url") or "").strip()
        text = str(link.get("text") or "").strip()
        # **Both or neither**, which db 0066 also enforces: a button with no
        # destination and a destination with no button are each half a control.
        if not url or not text:
            raise NotificationError(
                "a link needs both a `url` and the `text` for its button (p.91)"
            )
        check("link", url)
        check("link", text)
        out["link"] = {"url": url, "text": text}
    return out


def render(
    template: str,
    *,
    values: dict[str, Any],
    objects: "dict[str, dict[str, Any]] | None" = None,
    recipient: "dict[str, Any] | None" = None,
    actor: "dict[str, Any] | None" = None,
) -> str:
    """Substitute p.92's triple handlebars.

    `values` is the action's submitted parameter values; `objects` is
    `{object parameter: its properties}` **as they were before this action's
    edits** (p.92); `recipient` and `actor` are `{display_name, email}` for
    p.101's two user references.

    **An unresolved reference renders as empty**, not as itself and not as an
    error. It cannot normally happen - `parse` refuses a name that is not a
    parameter - so the case this covers is a parameter left unset, and p.92's
    own note that content "will reflect the state of the Ontology before edits"
    is about *stale* data rather than *absent* data. Leaving `{{{priority}}}`
    on screen would tell the recipient about the template; leaving a gap tells
    them about the value.
    """
    def one(match: "re.Match[str]") -> str:
        ref = match.group(1)
        # The same rule `parse` applies, and it has to be the same or the two
        # disagree about what a name is: a reference that is a key of `values`
        # whole is that value, dots and all. §260's `webhook.<output>` is the
        # case — splitting it would look for an *object parameter* called
        # `webhook` and render the gap that means "unset".
        if ref in values:
            return _text(values[ref])
        head, _, tail = ref.partition(".")
        if head in ("recipient", "current_user"):
            who = recipient if head == "recipient" else actor
            return str((who or {}).get(tail or "display_name") or "")
        if tail:
            return _text((objects or {}).get(head, {}).get(tail))
        return _text(values.get(head))

    return _REFERENCE.sub(one, template or "")


def _text(value: Any) -> str:
    """One value as it reads in a sentence.

    `None` is empty rather than "None", which is the whole of what this
    function is for: a template that renders the word `None` into somebody's
    inbox is a template that leaked Python.
    """
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def rendered(
    rule: dict[str, Any],
    *,
    values: dict[str, Any],
    objects: "dict[str, dict[str, Any]] | None" = None,
    recipient: "dict[str, Any] | None" = None,
    actor: "dict[str, Any] | None" = None,
) -> dict[str, Any]:
    """The whole notification, for one recipient, ready to store.

    Truncated to p.95's limits **after** substitution, because that is where
    the length is decided: a 200-character subject with a parameter in it can
    render to anything.
    """
    def fill(template: str, limit: int) -> str:
        return truncate(
            render(template, values=values, objects=objects,
                   recipient=recipient, actor=actor),
            limit,
        )

    out: dict[str, Any] = {
        "subject": fill(str(rule.get("subject") or ""), MAX_SUBJECT),
        "body": fill(str(rule.get("body") or ""), MAX_BODY),
    }
    link = rule.get("link")
    if isinstance(link, dict):
        # Not truncated: a URL cut short is a link to somewhere else, and a
        # button label is not the content p.95's limits are about.
        out["link_url"] = render(
            str(link.get("url") or ""), values=values, objects=objects,
            recipient=recipient, actor=actor,
        )
        out["link_text"] = render(
            str(link.get("text") or ""), values=values, objects=objects,
            recipient=recipient, actor=actor,
        )
    return out


def recipient_ids(
    rule: dict[str, Any],
    *,
    values: dict[str, Any],
    objects: "dict[str, dict[str, Any]] | None" = None,
) -> list[str]:
    """Who this firing should reach, before permissions are checked.

    Deduplicated and **order-preserving**, because a list of recipients read
    out of a property can repeat and p.90's "sent to each recipient
    individually" is one message each, not one per mention.

    Values that are not plausible user ids are dropped rather than guessed at
    (p.100: "if this property contains something else such as string email
    addresses, no notifications will be sent"). Whether an id names a real user
    is the database's question and is answered by the caller.
    """
    spec = rule.get("recipients") or {}
    kind = str(spec.get("kind", ""))
    raw: list[Any]
    if kind == "static":
        raw = list(spec.get("user_ids") or [])
    elif kind == "parameter":
        raw = _as_list(values.get(str(spec.get("parameter", ""))))
    elif kind == "object_property":
        held = (objects or {}).get(str(spec.get("parameter", "")), {})
        raw = _as_list(held.get(str(spec.get("property", ""))))
    else:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        text = _text(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out[:MAX_RECIPIENTS]


def deliverable(
    mode: str, *, requested: list[str], permitted: "set[str] | frozenset[str]"
) -> list[str]:
    """Who actually gets it, or a refusal — p.96's two failure modes.

    > "Require all users to have permissions (default): If any recipients do
    > not have the required access, an error will be shown when attempting to
    > apply the Action. If this happens, **no data will be edited and no
    > notifications will be sent**." (p.96)

    > "Require any user to have permissions: If at least one user can see the
    > object, the Action will succeed. Only users with permissions will receive
    > notifications." (p.96)

    **The `all` mode's refusal is about the whole action, not the
    notification**, which is why this is checked before anything is written
    rather than after: "no data will be edited" is not something a caller can
    honour once it has edited the data. That is the only reason this function
    exists separately from `recipient_ids` — the two would otherwise be one
    call, and joining them would put the check on the wrong side of the write.

    An empty `requested` is nobody to notify and no refusal in either mode: a
    rule whose recipient property is unset on this object has not failed a
    permission check, it has simply found no one. p.96 is about access, and
    absence is not a denial.
    """
    if not requested:
        return []
    allowed = [u for u in requested if u in permitted]
    if mode == "all" and len(allowed) != len(requested):
        missing = sorted(set(requested) - set(allowed))
        raise NotificationError(
            "this action notifies "
            + ", ".join(missing)
            + ", who cannot see the data it would send them - nothing has been "
            "changed (p.96). Set the notification to `any` to send to whoever "
            "can, or remove them from the recipients"
        )
    if not allowed:
        raise NotificationError(
            "none of this action's notification recipients can see the data it "
            "would send them, so nothing has been changed (p.96)"
        )
    return allowed


def _as_list(value: Any) -> list[Any]:
    """One value or several, as p.90's "this is also possible for lists of
    Foundry user and group IDs" requires.

    A comma-separated string is **not** split, and that is a decision rather
    than an omission: a property holding `"a,b"` is one value that happens to
    contain a comma, and guessing otherwise would make a display name with a
    comma in it into two recipients.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]
