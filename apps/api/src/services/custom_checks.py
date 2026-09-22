"""A repository's own checks (§433; `code-repositories` p.98).

    "Custom checks can be created as Gradle tasks. These tasks should be added
     to the appropriate inner `build.gradle` files, within the language
     subfolders… In order for tasks to get executed during CI checks, there
     must be a CI task that depends on your custom task." (p.98)

**Gradle is the mechanism, not the capability, and only the capability
transfers.** There is no Gradle here, no `build.gradle` and no language
subfolders: a repository holds SQL and Python files and publishes transforms.
What p.98 offers is that *a repository can define a check of its own that runs
with the platform's and appears in the Checks tab*, and that is worth having.

**The rules are declarative, and that is a decision rather than a shortcut.**
A Gradle task is arbitrary code, and running a customer's arbitrary code as
part of a review would mean the API executing whatever somebody put in a file —
which decision 0004 already refuses for transforms, where Python runs in an
isolated task and never in the API. A check that gated a merge would be the
worst place to make an exception. So a repository declares *patterns* and this
module runs them.

They live in `repoSettings.json`, where the repository's tag-name convention
already does (§299, p.17) — the same argument holds twice: the rule is about
the repository's contents, so it travels with them, and a branch that adds a
check, a commit that relaxes one, and a history saying who changed the
convention and when all come free.

    "checks": [
      {
        "name": "no-select-star",
        "files": "*.sql",
        "forbid": "SELECT\\\\s+\\\\*",
        "message": "Name the columns you need rather than SELECT *."
      },
      {
        "name": "has-owner",
        "files": "*.sql",
        "require": "-- owner:"
      }
    ]

---

**A rule that cannot be understood is reported, not ignored — and this is the
one place that disagrees with `code_tags.read_settings`.** There, a malformed
convention is skipped, because a convention that fails closed blocks work while
the person who can fix it is elsewhere. A *check* is the opposite: its whole job
is to tell a reviewer something, and one that quietly did not run leaves the
Checks tab looking like there was nothing to check. So a rule that will not
compile becomes a check with status `error`, which says so on the screen and —
by `code_checks.BLOCKING_STATUSES` — does not gate. Nobody is blocked by a
typo, and nobody is told a rule passed that never ran.
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any

from .code_tags import MAX_REGEX_LENGTH, SETTINGS_FILE

#: At most this many rules from one settings file. A check row per rule per
#: proposal is a row on somebody's screen, and a settings file with two hundred
#: of them is a Checks tab nobody can read - and two hundred regexes over every
#: file in the repository, which is the cheap way to make a review slow.
MAX_RULES = 10

#: How many offending paths a summary names before it counts the rest. The
#: point of the summary is to be read; "and 40 more" is more useful than forty
#: paths, and the whole list is in `detail` either way.
NAMED_PATHS = 5

#: Prefixed, so a repository cannot declare a rule called `schema_compatible`
#: and have it overwrite the platform's answer - `code_proposal_checks` is keyed
#: on `(proposal_id, model_id, source_path, name)`, so a collision would not
#: error, it would silently replace. The prefix is also what tells a reviewer
#: which checks are the repository's own.
PREFIX = "repo:"


class Rule:
    """One declared check, already validated."""

    def __init__(
        self, *, name: str, files: str, pattern: re.Pattern[str],
        forbid: bool, message: str | None,
    ) -> None:
        self.name = name
        self.files = files
        self.pattern = pattern
        self.forbid = forbid
        self.message = message

    @property
    def check_name(self) -> str:
        return f"{PREFIX}{self.name}"


class Refused:
    """A rule that could not be understood, and why.

    Carried rather than raised: one bad rule in a list of five must not stop
    the other four from running, and the reviewer needs to be told about all
    of them rather than the first.
    """

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason

    @property
    def check_name(self) -> str:
        return f"{PREFIX}{self.name}"


def parse(settings: dict[str, Any]) -> tuple[list[Rule], list[Refused]]:
    """The rules a settings file declares, and the ones it got wrong.

    Both lists, always: `read_settings` has already turned an unparseable file
    into `{}`, and from here on every refusal is a sentence somebody needs to
    read rather than a reason to stop.
    """
    block = settings.get("checks")
    if not isinstance(block, list):
        return ([], [])

    rules: list[Rule] = []
    refused: list[Refused] = []
    seen: set[str] = set()

    for index, raw in enumerate(block[:MAX_RULES]):
        name = _name_of(raw, index)
        if not isinstance(raw, dict):
            refused.append(Refused(name, "this check is not an object"))
            continue
        if name in seen:
            # **Refused rather than merged.** Two rules with one name would be
            # one row in `code_proposal_checks`, so the second would silently
            # replace the first and a reviewer would be told about half of what
            # the repository asked for.
            refused.append(Refused(name, "two checks in this file have the same name"))
            continue
        seen.add(name)

        forbid = raw.get("forbid")
        require = raw.get("require")
        if isinstance(forbid, str) == isinstance(require, str):
            refused.append(Refused(
                name,
                "a check names either 'forbid' or 'require', and this one names "
                + ("both" if isinstance(forbid, str) else "neither"),
            ))
            continue

        source = forbid if isinstance(forbid, str) else require
        assert isinstance(source, str)
        if not source or len(source) > MAX_REGEX_LENGTH:
            refused.append(Refused(
                name,
                f"the pattern is empty or longer than {MAX_REGEX_LENGTH} characters",
            ))
            continue
        try:
            pattern = re.compile(source)
        except re.error as exc:
            refused.append(Refused(name, f"the pattern is not a regular expression: {exc}"))
            continue

        files = raw.get("files")
        message = raw.get("message")
        rules.append(Rule(
            name=name,
            files=files if isinstance(files, str) and files else "*",
            pattern=pattern,
            forbid=isinstance(forbid, str),
            message=message if isinstance(message, str) and message else None,
        ))

    if len(block) > MAX_RULES:
        refused.append(Refused(
            "too-many-checks",
            f"{SETTINGS_FILE} declares {len(block)} checks and at most "
            f"{MAX_RULES} are run; the rest were not",
        ))
    return (rules, refused)


def _name_of(raw: Any, index: int) -> str:
    """A rule's name, or one that says where to look.

    A rule with no usable name still has to be reportable — "check 3" is a
    place in the file, which is what somebody fixing it needs.
    """
    if isinstance(raw, dict):
        name = raw.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()[:60]
    return f"check {index + 1}"


def scanned(files: dict[str, str], pattern: str) -> list[str]:
    """The paths a rule applies to, sorted.

    **`fnmatch`, so `*` crosses directories.** `*.sql` matching `src/a.sql` is
    what somebody writing a settings file means, and a shell's rule — where `*`
    stops at a separator and `**/*.sql` is needed — would make the obvious
    pattern match nothing at the one moment it has to be obvious.

    **`repoSettings.json` is never scanned.** A rule forbidding `SELECT *`
    would otherwise find the words in the rule that forbids them, and report
    the repository's own conventions file as its first violation.
    """
    return sorted(
        path for path in files
        if path != SETTINGS_FILE and fnmatch.fnmatchcase(path, pattern)
    )


def violations(rule: Rule, files: dict[str, str]) -> list[str]:
    """The paths this rule is unhappy about, sorted.

    A `forbid` rule is unhappy about a file that *matches*; a `require` rule
    about one that does not. `search`, not `fullmatch`: a rule is about
    something appearing somewhere in a file, which is the only thing a pattern
    over a whole source file can usefully mean.
    """
    offending = []
    for path in scanned(files, rule.files):
        found = rule.pattern.search(files[path]) is not None
        if found == rule.forbid:
            offending.append(path)
    return offending


def summarise(rule: Rule, offending: list[str], scanned_count: int) -> tuple[str, str]:
    """`(status, summary)` for one rule that ran.

    **A rule that matched no files at all is a `warn`, not a `pass`.** "Nothing
    broke this rule" and "this rule looked at nothing" are the same green tick
    otherwise, and the second is usually a `files` pattern with a typo in it —
    which is exactly the check somebody thinks is protecting them (§226).
    """
    if scanned_count == 0:
        return (
            "warn",
            f"No files matched {rule.files!r}, so this check looked at nothing.",
        )
    if not offending:
        return ("pass", f"{scanned_count} file{_s(scanned_count)} checked.")

    named = ", ".join(offending[:NAMED_PATHS])
    rest = len(offending) - NAMED_PATHS
    where = named + (f" and {rest} more" if rest > 0 else "")
    count = len(offending)
    # **The repository's own sentence when it wrote one.** The same argument
    # p.17's `errorMessage` makes for tag names (§299): "Name the columns you
    # need" is a sentence somebody wrote for their colleagues, and replacing it
    # with a regex would throw away the only part of the refusal that helps.
    said = rule.message or (
        f"{count} file{_s(count)} "
        + (_verb(count, "matches", "match") if rule.forbid
           else _verb(count, "does not match", "do not match"))
        + f" {rule.pattern.pattern!r}"
    )
    return ("fail", f"{said} ({where})")


def _s(count: int) -> str:
    return "" if count == 1 else "s"


def _verb(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural
