"""Running a repository's unit tests (§293; `code-repositories.md` §8).

Foundry's Unit tests chapter (p.56) is a pointer rather than a specification —
it links to per-language docs absent from `docs/pal/`. What is actually
specified is p.13 ("run all unit tests defined in the current file"), p.14 (a
Tests helper that "lets you run those tests and displays their results") and
p.19 (their output in the Checks tab). Results are therefore what this
produces, and these tests are about the ones that are easy to get subtly wrong:

- **a run with no tests is not a pass.** A suite that runs nothing and reports
  green is the exact thing this repo does not accept, and `code-repositories.md`
  §10 says so about this feature by name: *"a failing test is reported as
  failing. A test suite that cannot fail is the exact thing this repo does not
  accept."*
- **a failing test and a broken run are different problems.** The first is the
  author's answer; the second is ours, and reporting it as theirs sends the
  wrong person looking. Same distinction `transform_runner.py` keeps with
  `result.json`.
- **the transform under test is importable**, which is the whole of §292 and
  the reason this could not be built before it.
"""
from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import unit_test_report  # noqa: E402
from anchor_worker.dataset_engine import DatasetEngineError  # noqa: E402
from anchor_worker.python_sandbox import is_test_file, run_python_tests  # noqa: E402

DECLARED = """\
import anchor


@anchor.transform(output="positive_orders", inputs={"orders": "raw_orders"})
def build(orders):
    return [row for row in orders if row > 0]
"""


def test_a_test_that_imports_the_transform_under_test_passes() -> None:
    """**§292's payoff, and the reason it had to come first.** A unit test's
    first line is an import, and until `anchor` was a module on disk this file
    could not be imported at all — `@anchor.transform` raised `NameError`
    before any assertion ran."""
    report = run_python_tests({
        "src/daily.py": DECLARED,
        "tests/test_daily.py": (
            "from src.daily import build\n\n"
            "def test_drops_the_negatives():\n"
            "    assert build([-1, 2]) == [2]\n"
        ),
    })
    assert report.ok
    assert report.passed == 1
    assert report.failed == 0


def test_a_failing_test_is_reported_as_failing() -> None:
    """`code-repositories.md` §10's acceptance test for this feature, and the
    one that keeps the rest honest."""
    report = run_python_tests({
        "tests/test_thing.py": "def test_it():\n    assert 3 == 4\n",
    })
    assert not report.ok
    assert report.failed == 1
    (outcome,) = report.outcomes
    assert outcome.outcome == unit_test_report.FAILED
    assert outcome.message == "assert 3 == 4"


def test_a_repository_with_no_tests_is_not_a_pass() -> None:
    """**The one that would be easiest to get wrong**, because "nothing failed"
    and "everything passed" are the same number.

    A caller showing green here would be showing green for a repository that
    has never had a test written in it, which is worse than showing nothing:
    it answers a question nobody asked and hides the one they should.
    """
    report = run_python_tests({"src/daily.py": DECLARED})
    assert report.outcomes == []
    assert report.failed == 0
    assert not report.ok, "a run with nothing in it must not report success"


def test_the_identity_is_the_one_you_would_type_to_run_it_again() -> None:
    """Not pytest's dotted `classname`, which is a module path and cannot be
    pasted into a command — and the file and line are what let a panel open the
    failing test rather than describe it."""
    report = run_python_tests({
        "tests/test_where.py": "def test_a():\n    assert 1\n\n\ndef test_b():\n    assert 0\n",
    })
    by_id = {o.id: o for o in report.outcomes}
    assert set(by_id) == {"tests/test_where.py::test_a", "tests/test_where.py::test_b"}
    # 1-based, because every editor is and pytest's report is not. Converted at
    # the boundary so the panel does not have to know.
    assert by_id["tests/test_where.py::test_a"].line == 1
    assert by_id["tests/test_where.py::test_b"].line == 5


def test_an_error_is_not_a_failure() -> None:
    """An assertion that did not hold is the author's answer; a fixture that
    blew up is a different problem with a different first thing to look at.
    Collapsing them would put "assert 3 == 4" and "no such fixture" under one
    heading."""
    report = run_python_tests({
        "tests/test_fixture.py": (
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def broken():\n"
            "    raise RuntimeError('the fixture is wrong')\n\n"
            "def test_it(broken):\n"
            "    assert True\n"
        ),
    })
    (outcome,) = report.outcomes
    assert outcome.outcome == unit_test_report.ERROR
    assert report.failed == 1


def test_a_skip_is_counted_apart_from_both() -> None:
    report = run_python_tests({
        "tests/test_skip.py": (
            "import pytest\n\n"
            "@pytest.mark.skip(reason='not yet')\n"
            "def test_it():\n"
            "    assert 0\n"
        ),
    })
    assert report.skipped == 1
    assert report.failed == 0
    # And it still counts as something having run, so the report is not the
    # empty one above.
    assert report.ok


def test_a_syntax_error_in_the_code_under_test_is_a_collection_error() -> None:
    """Reported rather than raised: the file is the author's and so is the
    mistake. A run that refused to produce a report here would tell them the
    platform is broken."""
    report = run_python_tests({
        "src/daily.py": "def build(:\n",
        "tests/test_daily.py": "from src.daily import build\n\ndef test_it():\n    assert build\n",
    })
    assert report.failed == 1
    assert report.outcomes[0].outcome == unit_test_report.ERROR


def test_the_time_limit_is_the_platforms_problem_not_the_authors(monkeypatch) -> None:
    """**The distinction this whole module keeps.** A test that hangs is still
    the author's code, but the *run* is what failed, and it comes back as a
    raise rather than as a report — a caller must not paint it as "your tests
    failed", because no test of theirs reported anything.
    """
    with pytest.raises(DatasetEngineError, match="time limit"):
        run_python_tests(
            {"tests/test_slow.py": "import time\n\ndef test_it():\n    time.sleep(30)\n"},
            timeout_s=2,
        )


def test_our_own_suite_is_not_collected_into_a_customers(monkeypatch) -> None:
    """**`--rootdir`, and why it is not decoration.**

    Without it pytest walks upwards from the working directory looking for a
    config file, and if it finds one it takes that directory as the rootdir and
    reads its settings. `TMPDIR` is the user's to set, so the scratch directory
    can perfectly well live inside a checkout of this repository - at which
    point pytest finds *our* `pytest.ini` and applies it to a customer's run.

    **Two survivors are why this test looks like this**, and the second one
    found the guard was the wrong guard. It first ran in the default temp
    location - `/tmp`, under no repository at all - so nothing was above it to
    inherit and the check could not fire. Given a config file above it, the
    original `--rootdir` still failed: pytest settles its *rootdir* and its
    *inifile* separately and `--rootdir` moves only the first, so it walked up
    and applied the config anyway. `-c` is what pins it.
    """
    import tempfile as tempfile_module

    nested = os.path.join(REPO_ROOT, ".tmp-config-check")
    os.makedirs(nested, exist_ok=True)
    # A configuration above the run that would change what it does. `addopts`
    # rather than something exotic, because it is the setting most likely to be
    # in a real repository's ini and the easiest to see the effect of.
    with open(os.path.join(nested, "pytest.ini"), "w") as handle:
        handle.write("[pytest]\naddopts = -k __never_matches__\n")
    monkeypatch.setattr(tempfile_module, "tempdir", nested)
    try:
        report = run_python_tests({"tests/test_one.py": "def test_it():\n    assert 1\n"})
    finally:
        monkeypatch.undo()
    assert [o.id for o in report.outcomes] == ["tests/test_one.py::test_it"], (
        "a configuration above the run reached a customer's tests"
    )


def test_a_repository_that_brings_its_own_config_keeps_it() -> None:
    """The other half, and the reason the pinning is not just "ignore all
    configuration": a repository with a `pytest.ini` means it, and a checkout
    would honour it. Overwriting theirs would be this platform quietly
    disagreeing with a file they wrote."""
    report = run_python_tests({
        "pytest.ini": "[pytest]\naddopts = -k keep_me\n",
        "tests/test_two.py": (
            "def test_keep_me():\n    assert 1\n\n\n"
            "def test_other():\n    assert 1\n"
        ),
    })
    assert [o.id for o in report.outcomes] == ["tests/test_two.py::test_keep_me"]


def test_a_run_that_wrote_no_report_is_not_an_empty_pass() -> None:
    """**pytest can fail before it has anything to report.**

    A `conftest.py` that will not import is the ordinary way: pytest exits with
    a usage error and writes no XML at all. Reading that as "no tests, nothing
    failed" would show a green panel for a repository whose tests cannot even
    be collected - the same lie as an empty run reported as a pass, arriving by
    a different door.
    """
    with pytest.raises(DatasetEngineError, match="no report"):
        run_python_tests({
            "conftest.py": "import a_module_that_is_not_installed_anywhere\n",
            "tests/test_one.py": "def test_it():\n    assert 1\n",
        })


def test_a_multi_line_failure_is_one_line_in_the_summary_and_whole_in_the_detail() -> None:
    """A panel shows one line per test, and pytest's message for a comparison
    is a diff several lines long. Both halves are wanted: the line that fits on
    the row, and the whole thing for whoever opens it."""
    report = run_python_tests({
        "tests/test_diff.py": (
            "def test_it():\n"
            "    assert {'a': 1, 'b': 2} == {'a': 1, 'b': 3}\n"
        ),
    })
    (outcome,) = report.outcomes
    assert outcome.message is not None
    assert "\n" not in outcome.message, "a summary line has to fit on a row"
    assert outcome.detail is not None and len(outcome.detail.splitlines()) > 1


def test_a_report_that_will_not_parse_is_not_an_empty_run() -> None:
    """Infrastructure, not a test failure. Returning an empty report here would
    turn a broken run into "this repository has no tests", which reads as a
    fact about their code and is a fact about ours."""
    with pytest.raises(unit_test_report.ReportUnreadable):
        unit_test_report.parse_junit("<testsuites><oops")


# ---- which files are tests ---------------------------------------------------
def test_discovery_follows_pytests_rule_and_not_a_second_one() -> None:
    """A repository's authors already know pytest's rule, `--junitxml` reports
    against it, and a rule of our own would mean a file this platform called a
    test and pytest did not — or the reverse, which is worse, because it runs.
    """
    assert is_test_file("tests/test_daily.py")
    assert is_test_file("daily_test.py")
    assert not is_test_file("src/daily.py")
    assert not is_test_file("tests/test_daily.sql"), "SQL has no runner here"
    assert not is_test_file("src/testing.py"), "`test_` is a prefix, not a substring"
