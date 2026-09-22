"""`repoSettings.json` — a repository's own rules, kept with its code
(§299, §433, §441; `code-repositories` p.17, p.105, p.114).

p.105 lists it among the things a repository's Settings tab configures —
"Additional repository settings (`repoSettings.json`)" — and it is the shape
this platform has reached for three times now:

  * p.17's `tagNameValidation`, which §299 built (`code_tags.py`);
  * p.106's custom checks, which §433 built (`custom_checks.py`);
  * p.114's commit message rule, which §441 built and which lives here.

**A file rather than a settings table**, and the reason has not changed since
§299 chose it: the rule is about a repository's contents and it travels with
them — a branch that adds it, a commit that relaxes it, and a history that says
who changed the convention and when. A column in `code_repos` would have none
of that.

**This module exists because the reader had two callers.** `read_settings` was
written inside `code_tags.py` for the tag convention, and p.114's rule needs
the same three lines with the same two decisions behind them — so it moved
rather than being copied (§292). A second parser is a second answer to "is this
file readable", and the two would disagree the first time either was made
stricter.
"""
from __future__ import annotations

import json
from typing import Any

#: Foundry's own settings file, at the root of the repository (p.17, p.105).
SETTINGS_FILE = "repoSettings.json"

#: How long a regex from a customer's settings file may be. **A regex is code**,
#: and one assembled to be pathological is the ordinary way a validator becomes
#: a denial of service. Length is a blunt guard and it is not the only one — see
#: `code_tags._compiled`.
MAX_REGEX_LENGTH = 200


def read_settings(files: dict[str, str]) -> dict[str, Any]:
    """`repoSettings.json` from a commit's files, or `{}`.

    **Absent and unreadable are the same answer here, deliberately.** A settings
    file with a syntax error would otherwise stop every tag and every commit in
    the repository until somebody fixed it, and the person blocked is rarely the
    person who broke it. The convention stops being enforced, which is visible
    in the next tag or commit anybody makes; the alternative fails closed on a
    rule that is a convention rather than a permission.
    """
    raw = files.get(SETTINGS_FILE)
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class CommitMessageRefused(Exception):
    """p.114's rule, refused in the repository's own words where it set some."""


#: p.114's block. **The key is ours and the behaviour is p.114's**, which is
#: worth saying plainly: Foundry's control is a checkbox in the Settings tab
#: ("By default commit messages will be auto-generated… You can encourage more
#: meaningful messages by disabling this option"), and it has no documented
#: JSON. It is spelled like `tagNameValidation` — a block with a rule and an
#: `errorMessage` — so a repository's settings file reads as one file with one
#: convention rather than as two files that happen to share a name.
COMMIT_BLOCK = "commitMessages"


def message_required(settings: dict[str, Any]) -> bool:
    """Whether this repository asks every commit to say what changed.

    **Off unless it says so.** p.114 describes turning auto-generation *off* to
    get meaningful messages; this platform never generated one, so what it can
    offer is the requirement — and a requirement that arrived by default would
    refuse the next commit in every repository that already exists, for a rule
    nobody in them had asked for.
    """
    block = settings.get(COMMIT_BLOCK)
    return isinstance(block, dict) and block.get("required") is True


def check_message(message: str, settings: dict[str, Any]) -> None:
    """Refuse an empty commit message where the repository asks for one.

    **Whitespace is empty**, because a space typed to get past a check is the
    check working exactly as badly as no check at all.

    The repository's own `errorMessage` where it set one, for `TagNameRefused`'s
    reason: a sentence somebody wrote for their colleagues says why the rule
    exists, and "a commit message is required" does not.
    """
    if not message_required(settings):
        return
    if message.strip():
        return
    block = settings.get(COMMIT_BLOCK)
    said = block.get("errorMessage") if isinstance(block, dict) else None
    raise CommitMessageRefused(
        said if isinstance(said, str) and said.strip()
        else (
            "This repository asks every commit to say what changed, which is "
            f"set in {SETTINGS_FILE}."
        )
    )
