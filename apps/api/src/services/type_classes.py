"""A property's type classes (§671; db 0133; `object-link-types` p.91).

    "Type classes: Apply type classes as additional metadata that can be
     interpreted by applications." (p.91)

Each is `kind:name` - p.222's `hubble:icon`, `workshop`'s
`scenarios:scenario-name` - and only that shape is checked: which ones mean
something is up to the application reading them (db 0133's reason).
"""
from __future__ import annotations

import re
from typing import Any

#: `kind:name`, each part letters, digits, `_`, `.` or `-`.
SHAPE = re.compile(r"^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$")
MAX_CLASSES = 20
MAX_LENGTH = 100


def parse(raw: Any, *, property_name: str, limit: int = MAX_CLASSES) -> list[str]:
    """The type classes as stored: trimmed, each once, in the order given.
    None is none; anything but a list of `kind:name` strings is refused, by
    the property it was on.

    `limit` is wider only where a save may carry p.188's union of a property's
    own classes and its shared property's (§723); what is stored is still held
    to `MAX_CLASSES` (`check_count`)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{property_name!r}'s type classes must be a list")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"{property_name!r}'s type classes must be text")
        name = item.strip()
        if len(name) > MAX_LENGTH or not SHAPE.match(name):
            raise ValueError(
                f"{property_name!r}'s type class {item!r} is not kind:name "
                f"(letters, digits, _ . -, at most {MAX_LENGTH} characters)"
            )
        if name not in out:
            out.append(name)
    if len(out) > limit:
        raise ValueError(f"{property_name!r} has more than {limit} type classes")
    return out


def check_count(classes: list[str], *, property_name: str) -> None:
    if len(classes) > MAX_CLASSES:
        raise ValueError(f"{property_name!r} has more than {MAX_CLASSES} type classes")
