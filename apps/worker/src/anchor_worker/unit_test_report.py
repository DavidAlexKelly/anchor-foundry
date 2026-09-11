"""What a unit test run produced, read out of pytest's own report (§293).

**JUnit XML, not a plugin.** pytest writes it with `--junitxml` and nothing has
to be installed alongside customer code to get it — which matters, because the
directory customer tests run in holds their files and `anchor.py` and nothing
else. A reporting plugin would be a second thing to stage and a second thing
that could be missing.

**Parsed by the caller, never inside the sandbox.** The process that runs the
tests is the one running customer code; the process that reads the report is
ours. Keeping the parse on this side means a test that writes rubbish over
`report.xml` produces "the run wrote no readable report", not a parser running
on a string somebody chose.

`code-repositories.md` §8 records that Foundry's Unit tests chapter (p.56) is a
pointer rather than a specification. What is actually specified is p.14's Tests
helper — it "lets you run those tests and displays their results" — so results
are what this produces: an identity, an outcome, how long it took, and the
message when there is one.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

#: Every outcome a test can have. `error` is distinct from `failed` on purpose:
#: an assertion that did not hold is the author's answer, and a fixture that
#: blew up is a different problem with a different first thing to look at.
PASSED = "passed"
FAILED = "failed"
ERROR = "error"
SKIPPED = "skipped"


@dataclass(frozen=True)
class TestOutcome:
    """One test, named the way the author would name it."""

    #: `tests/test_daily.py::test_drops_zero_totals` - the id they would type to
    #: run it again, rather than pytest's dotted classname.
    id: str
    outcome: str
    duration_ms: int
    #: The file it is in and the line it starts on, so a panel can open it.
    #: Both come from pytest's `xunit1` report family; its default family
    #: writes a dotted `classname` and nothing else.
    file: str | None = None
    line: int | None = None
    #: The failure's first line, or None. The whole traceback is `detail`.
    message: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class TestReport:
    outcomes: list[TestOutcome]
    duration_ms: int

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.outcome == PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.outcome in (FAILED, ERROR))

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.outcome == SKIPPED)

    @property
    def ok(self) -> bool:
        """**Not the same as "nothing failed".**

        A repository with no tests has nothing failing in it, and reporting
        that as a pass is how a suite that runs nothing looks green - the exact
        thing this repo does not accept. A caller that wants to know whether
        anything ran asks `len(outcomes)`.
        """
        return bool(self.outcomes) and self.failed == 0


class ReportUnreadable(Exception):
    """pytest wrote no report, or wrote one this cannot read.

    Infrastructure, not a test failure - the same distinction
    `transform_runner.py` keeps with `result.json`. A caller must not report it
    as "your tests failed", because nobody's test did.
    """


def parse_junit(xml_text: str) -> TestReport:
    """Read pytest's `--junitxml` output into outcomes.

    One `<testcase>` per test. Its child element, if any, says what happened:
    `<failure>` an assertion, `<error>` a fixture or collection problem,
    `<skipped>` a skip. No child means it passed - pytest writes nothing for a
    passing test, so **absence is the pass**, which is worth saying out loud
    because it is the one branch here with no evidence of its own.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ReportUnreadable(f"the test run wrote no readable report: {exc}") from exc

    # pytest 7+ wraps the suite in <testsuites>; older versions emit
    # <testsuite> directly. Accept both rather than pinning the shape of
    # somebody else's output format.
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    outcomes: list[TestOutcome] = []
    total_s = 0.0
    for suite in suites:
        total_s += float(suite.get("time") or 0.0)
        for case in suite.findall("testcase"):
            outcomes.append(_case(case))
    return TestReport(outcomes=outcomes, duration_ms=int(total_s * 1000))


def _case(case: ET.Element) -> TestOutcome:
    file_name = case.get("file") or None
    name = case.get("name") or "?"
    # **The id the author would type to run it again**, which is the path and
    # the name - not pytest's dotted `classname`, which is a module path and
    # cannot be pasted into a command.
    identity = f"{file_name}::{name}" if file_name else name
    raw_line = case.get("line")
    # pytest counts from 0 here and every editor counts from 1. Converted at
    # the boundary rather than by whoever renders it, so there is one place
    # this is known and the panel is not the second.
    line = int(raw_line) + 1 if raw_line is not None and raw_line.isdigit() else None
    duration_ms = int(float(case.get("time") or 0.0) * 1000)

    for tag, outcome in (("failure", FAILED), ("error", ERROR), ("skipped", SKIPPED)):
        found = case.find(tag)
        if found is not None:
            message = found.get("message") or None
            return TestOutcome(
                id=identity,
                outcome=outcome,
                duration_ms=duration_ms,
                file=file_name,
                line=line,
                # The first line, because a panel shows one line per test and
                # "assert 3 == 4" is the half worth showing.
                message=(message.splitlines()[0] if message else None),
                detail=(found.text or None),
            )
    return TestOutcome(
        id=identity, outcome=PASSED, duration_ms=duration_ms, file=file_name, line=line,
    )
