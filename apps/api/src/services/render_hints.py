"""A property's render hints (§724; `object-link-types` p.248-252; db 0140).

    "Foundry uses render hints to communicate information about the use of
     Ontology properties to Object Storage v1 (Phonograph) and user
     applications in the platform." (p.248)

p.249-252's table, in its own order. Each is stored by its key; which ones an
application honours is that application's business, as a type class's is
(db 0133) - this module owns only the list, the default and the one rule the
table states between them.
"""
from __future__ import annotations

from typing import Any

#: p.249-252's names, in the table's order.
HINTS: dict[str, str] = {
    "disable_formatting": "Disable formatting",
    "identifier": "Identifier",
    "keywords": "Keywords",
    "long_text": "Long text",
    "low_cardinality": "Low cardinality",
    "selectable": "Selectable",
    "sortable": "Sortable",
    "searchable": "Searchable",
    "leading_wildcards": "Enable leading wildcards",
    "regex": "Enable regex queries",
}

#: On unless deselected: p.182's "you can deselect the searchable and sortable
#: render hints", and p.250's Selectable, described by what disabling it saves.
#: Also db 0140's column default, so a property that never heard of hints is
#: searched, aggregated and sorted as it always was.
DEFAULT: tuple[str, ...] = ("selectable", "sortable", "searchable")

#: p.250-251: "The Searchable render hint must also be selected along with" each
#: of these, and p.251's "Searchable must be selected in order for
#: applications to apply the Selectable, Sortable, or Low cardinality render
#: hints".
NEEDS_SEARCHABLE: tuple[str, ...] = (
    "low_cardinality", "selectable", "sortable", "leading_wildcards", "regex",
)


def parse(raw: Any, *, property_name: str) -> list[str]:
    """The hints as stored: each known one once, in the table's order.

    `None` is the default rather than none: it is what a client written before
    hints existed sends, and reading it as "none" would make that client's
    next save stop every property it touched being searched or sorted.
    """
    if raw is None:
        return list(DEFAULT)
    if not isinstance(raw, list) or not all(isinstance(h, str) for h in raw):
        raise ValueError(f"{property_name!r}'s render hints must be a list of names")
    unknown = sorted({h for h in raw if h not in HINTS})
    if unknown:
        raise ValueError(
            f"{property_name!r}: no render hint named " + ", ".join(repr(h) for h in unknown)
        )
    chosen = [h for h in HINTS if h in raw]
    if "searchable" not in chosen:
        dependent = [HINTS[h] for h in chosen if h in NEEDS_SEARCHABLE]
        if dependent:
            raise ValueError(
                f"{property_name!r}: {', '.join(dependent)} "
                f"{'needs' if len(dependent) == 1 else 'need'} Searchable "
                "as well (object-link-types p.250-251)"
            )
    return chosen
