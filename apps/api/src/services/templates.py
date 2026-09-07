"""The platform's one reference syntax (`action-types` p.92, p.94).

> "Click on a parameter to generate the `{{{}}}` syntax to reference that
> parameter." (p.94)

**Three braces, exactly.** Two braces escape their substitution in every
templating language that has both, and somebody typing by hand gets two — which
is why p.94 has a *button* rather than a hint, and why the count is a
correctness question rather than a formatting one. A template with two braces
renders literally and nothing on screen says so.

**Why this is a file rather than a constant in one service.** §257 put the
pattern in `services/notifications.py`, which was right while notifications
were the only thing that had templates. §259's webhooks have them too — a path,
query params, headers and a JSON body, all referencing the same kind of
declared input — and a second `re.compile` of the same expression is the shape
§191 calls a mirror: two copies that can be identically wrong and a drift guard
that would not notice, because it compares them to each other.

What is *not* here is substitution. Each caller resolves a name differently —
a notification looks up p.101's `Recipient` and `Current User` and an object
parameter's property, a webhook looks up a declared input and keeps its type —
and folding those into one function would produce a resolver with a mode
argument, which is two functions wearing a hat.
"""
from __future__ import annotations

import re

#: One `{{{name}}}`, with the dotted form `{{{object.property}}}` matched whole
#: so a caller can split the head off and decide what it means. Whitespace
#: inside the braces is tolerated because a generated reference and a typed one
#: should mean the same thing; the *brace count* is not tolerant, for the
#: reason in this module's docstring.
REFERENCE = re.compile(r"\{\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}\}")


def references(template: str | None) -> list[str]:
    """Every name a template refers to, in the order they appear.

    Duplicates are kept: a caller checking that every reference resolves wants
    each occurrence, and a caller counting them wants the count. Removing them
    here would make the second impossible and the first no easier.
    """
    return REFERENCE.findall(template or "")


def is_whole_reference(text: str) -> bool:
    """Whether this string is one reference and nothing else.

    The distinction a JSON body needs and a subject line does not. `"{{{n}}}"`
    alone can be replaced by the input's *value* — an integer stays an integer,
    a list stays a list — while `"id-{{{n}}}"` has to become a string, because
    there is nothing else a number concatenated to text could be. Getting this
    wrong sends `{"count": "3"}` where an API asked for `{"count": 3}`, which
    most servers reject and some silently accept as a different thing.
    """
    match = REFERENCE.fullmatch(text or "")
    return match is not None
