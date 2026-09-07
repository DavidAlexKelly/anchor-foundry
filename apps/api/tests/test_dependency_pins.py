"""The repo's Python pins, and the suites nothing was running (§263).

**Why this file exists.** `apps/worker` has 78 tests and, until §263, no
documented command could run any of them: `scripts/setup.sh` built one
virtualenv from `apps/api/requirements-dev.txt` and never installed the
worker's, and `scripts/check.sh` — whose own docstring says "every check this
repo has, in one command" — had no worker step. The tests were not failing.
They were not running, which is worse: a red suite is visible and an absent one
is not, and §263 added a worker test before noticing it could not be run.

**The same defect, already found once.** `apps/api/requirements-dev.txt` has a
comment about playwright: "It was missing entirely until the CI workflow was
read against the repo: the suite ran locally because a venv had it installed by
hand, and a fresh checkout could not have run it at all." That is this bug, in
the file next door, fixed for one suite and left standing for another.

**The fix rests on one assumption**, and this is it: `apps/api` and
`apps/worker` can share a virtualenv, because `check.sh` runs both through
`$ANCHOR_PYTHON`. That holds today — every package they share is pinned to the
same version — and nothing would announce it stopping.
"""
from __future__ import annotations

import os
import re

#: The repo root: this file is `<root>/apps/api/tests/`, so four levels up.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

#: The files `scripts/setup.sh` installs into the one virtualenv. Adding a file
#: here without adding it there is the failure this whole module is about, so
#: `test_setup_installs_what_this_file_compares` holds the two together.
SHARED = (
    "apps/api/requirements.txt",
    "apps/api/requirements-dev.txt",
    "apps/worker/requirements.txt",
    "apps/worker/requirements-dev.txt",
)

#: A suite with tests that `check.sh` does not run, and the reason — written
#: down rather than left as an absence, because an absence is what took this
#: long to notice. Wiring one up means deleting its entry here.
NOT_RUN = {
    "control-plane": (
        "needs a second database (CONTROL_PLANE_DATABASE_URL) that neither "
        "setup.sh nor dev-up.sh provisions, and pins httpx==0.27.0 against "
        "apps/api's 0.27.2, so it cannot share the one virtualenv either"
    ),
}

#: `name[extra]==version`, with comments and whitespace already stripped. The
#: extras are dropped for comparison: `moto[server]==5.0.13` and
#: `moto==5.0.13` pin the same package to the same version, and treating them
#: as different would fail this file on a difference that does not exist.
PIN = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==([^\s;]+)")


def pins(path: str) -> dict[str, str]:
    found: dict[str, str] = {}
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        for line in handle:
            match = PIN.match(line.split("#")[0].strip())
            if match:
                found[match.group(1).lower().replace("_", "-")] = match.group(3)
    return found


def test_every_requirements_file_pins_something() -> None:
    """The presence half, and not a formality.

    Every assertion below compares parsed files, and a comparison between two
    empty dicts passes. A regex gone stale — a reformatted file, a switch to
    `>=` — would make this module vacuous while it reported green, which is
    §198's shape exactly.
    """
    for path in SHARED:
        assert len(pins(path)) >= 2, f"{path} parsed to no pins - the regex has gone stale"


def test_the_shared_venv_is_possible() -> None:
    """**What `scripts/check.sh` running two suites through one interpreter
    depends on.**

    The overlap is real — `psycopg`, `PyMySQL`, `duckdb`, `pytz`, `pytest`,
    `moto` — and pip installs a second pin over the first without failing,
    leaving one suite testing against a version nobody chose for it. Silent in
    both directions: the install succeeds, and the tests then pass or fail for
    reasons unrelated to the change that caused it. `apps/api`'s own comment
    records that this once cost a whole session's results.

    If the two apps ever genuinely need different versions of something, the
    answer is a second virtualenv in `setup.sh` and `check.sh` — as
    `control-plane` already needs — not a wider assertion here.
    """
    seen: dict[str, tuple[str, str]] = {}
    clashes: list[str] = []
    for path in SHARED:
        for name, version in pins(path).items():
            if name in seen and seen[name][0] != version:
                clashes.append(
                    f"{name}: {seen[name][0]} in {seen[name][1]}, {version} in {path}"
                )
            seen.setdefault(name, (version, path))
    assert not clashes, (
        "these packages are pinned to different versions in different apps, so "
        "one virtualenv cannot satisfy both and scripts/check.sh would run a "
        "suite against a version nobody pinned for it:\n  " + "\n  ".join(clashes)
    )


def test_the_shared_venv_is_only_claimed_where_it_holds() -> None:
    """The absence half of the test above, and the one that keeps it honest.

    `NOT_RUN` says `control-plane` cannot share the virtualenv, and a reason
    nobody re-checks is a reason that quietly stops being true. If its pins
    ever come into line, this goes red and somebody gets to delete an
    exclusion — which is the direction this repo wants the list moving.
    """
    shared = {name: v for path in SHARED for name, v in pins(path).items()}
    theirs = pins("apps/control-plane/requirements-dev.txt")
    theirs.update(pins("apps/control-plane/requirements.txt"))
    clashes = {n: (shared[n], v) for n, v in theirs.items() if n in shared and shared[n] != v}
    assert clashes, (
        "control-plane no longer clashes with the shared pins, so half of "
        f"NOT_RUN['control-plane'] is out of date: {NOT_RUN['control-plane']}"
    )


def test_the_check_script_runs_every_suite_or_says_why_not() -> None:
    """A directory of tests that no command runs is what §263 found, and a
    count is the only thing that stops it recurring.

    Asserted against the **directories on disk** rather than against a second
    list, because a list compared to a list is §191's mirror: both copies are
    free to be missing the same suite. A new `apps/<name>/tests` has to be
    named in `check.sh` or written into `NOT_RUN` with a reason.
    """
    apps = os.path.join(ROOT, "apps")
    with_tests = sorted(
        name for name in os.listdir(apps)
        if os.path.isdir(os.path.join(apps, name, "tests"))
    )
    script = open(os.path.join(ROOT, "scripts", "check.sh"), encoding="utf-8").read()
    unaccounted = [
        name for name in with_tests
        if f"apps/{name}" not in script and name not in NOT_RUN
    ]
    assert not unaccounted, (
        f"{unaccounted} have test directories that scripts/check.sh never runs "
        "and NOT_RUN does not explain - a suite nobody runs is not checking "
        "anything"
    )
    # And the other direction: an entry that outlived its suite is a reason
    # nobody can act on, and it would hide the next real gap behind a stale one.
    stale = [name for name in NOT_RUN if name not in with_tests]
    assert not stale, f"NOT_RUN names {stale}, which have no tests directory"


def test_setup_installs_what_this_file_compares() -> None:
    """`SHARED` is this module's model of the virtualenv, and `setup.sh` is what
    actually builds it. A model that has drifted from the thing it models makes
    every assertion above true about a virtualenv nobody has.

    This is the check `requirements-dev.txt`'s playwright comment describes
    wanting: the reason that bug survived was that nothing compared the install
    against the suites it was supposed to serve.
    """
    setup = open(os.path.join(ROOT, "scripts", "setup.sh"), encoding="utf-8").read()
    dev_files = [path for path in SHARED if path.endswith("requirements-dev.txt")]
    missing = [path for path in dev_files if path not in setup]
    assert not missing, (
        f"scripts/setup.sh does not install {missing}, so a fresh checkout "
        "cannot run the suite it belongs to"
    )
