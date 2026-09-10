"""p.14's Tests helper, in the repository application (§295).

    "When your repository contains unit tests, the Tests Helper lets you run
     those tests and displays their results." (p.14)

That sentence is the whole specification: `code-repositories.md` §8 records
that Foundry's Unit tests chapter (p.56) is a pointer to per-language docs that
are not in `docs/pal/`. The wording rules are in
`apps/web/src/lib/test-runs.test.ts` and what the runner produces is in
`apps/worker/tests/test_code_tests.py`. What needs a browser is the **seam**:
press the button, and the answer comes back.

**This suite drives the worker itself, and that is worth stating.** The dev
stack starts Postgres, the API and Next, and no Dagster daemon - so a queued
run would sit in the table for ever and the panel would poll for ever. The op
these tests call is the same one the deployed worker's schedule calls, on the
same row, so what is skipped is the *cron*, not the work. A test that faked the
result instead would prove the panel can render a fixture.
"""
from __future__ import annotations

import os
import sys
import uuid

from playwright.sync_api import expect

from api import Module
from conftest import ADMIN_DSN, WEB_BASE, eventually

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "apps", "worker", "src",
    ),
)

PASSING_TEST = "def test_it_holds():\n    assert 1 + 1 == 2\n"
FAILING_TEST = "def test_it_does_not_hold():\n    assert 3 == 4\n"


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def commit(mod: Module, repo: dict, files: dict[str, str]) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": "tests"},
    )


def work_the_queue() -> int:
    """One turn of the worker's poll, against the dev database.

    Imported here rather than at module scope so a machine without the worker's
    dependencies fails on the test that needs them, naming the import, instead
    of failing to collect this file at all.
    """
    from dagster import build_op_context

    from anchor_worker.jobs.code_test_runs import run_queued_test_runs
    from anchor_worker.resources import PlatformDatabase

    # The app role, not the admin one: `rls_worker_for_workspace` (db 0006)
    # grants the worker's cross-workspace view to `platform_app` and this is the
    # connection the deployed worker opens.
    dsn = ADMIN_DSN.replace("platform:devpass", "platform_app:devpass")
    context = build_op_context(resources={"platform_db": PlatformDatabase(dsn=dsn)})
    return run_queued_test_runs(context)


def open_tests(page, repo: dict, path: str) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    page.get_by_test_id("tests-toggle").click()


def test_a_passing_suite_is_run_and_reported(page, api) -> None:
    """**The seam, end to end.** The button queues a job (db 0071), the worker
    runs it, and the panel - which polls, because a job's answer arrives in a
    table and there is nothing to push to it - shows what happened."""
    mod = project(api, "Tests pass")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"tests/test_ok.py": PASSING_TEST})

    open_tests(page, repo, "tests/test_ok.py")
    # Before anything is asked for, the panel says so rather than showing a
    # green tick over a run that never happened.
    expect(page.get_by_test_id("tests-verdict")).to_contain_text("No tests have been run")

    page.get_by_test_id("tests-run").click()
    # Queued, and saying so: nothing has run yet, which is the whole reason
    # this is a job rather than a request.
    expect(page.get_by_test_id("tests-verdict")).to_contain_text("run", timeout=30000)

    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the run up")
    expect(page.get_by_test_id("tests-verdict")).to_contain_text("1 passed", timeout=30000)
    expect(page.get_by_test_id("tests-list")).to_contain_text("tests/test_ok.py::test_it_holds")


def test_a_failing_test_is_reported_as_failing_and_opens_where_it_is(page, api) -> None:
    """`code-repositories.md` §10's acceptance test for this feature, on the
    screen: *"a failing test is reported as failing."*

    And clicking it opens the file, because a panel that names a failure you
    then have to go and find by hand is a panel that costs more than it saves -
    the same thing §286 built into Problems.
    """
    mod = project(api, "Tests fail")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {
        "tests/test_bad.py": FAILING_TEST,
        "src/other.py": "# not a test\n",
    })

    open_tests(page, repo, "src/other.py")
    page.get_by_test_id("tests-run").click()
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the run up")

    expect(page.get_by_test_id("tests-verdict")).to_contain_text("1 failed", timeout=30000)
    row = page.get_by_test_id("test-failed")
    expect(row).to_contain_text("tests/test_bad.py::test_it_does_not_hold")
    # The assertion itself, on the row - "assert 3 == 4" is the half worth
    # showing, and the whole traceback would not fit.
    expect(row).to_contain_text("assert 3 == 4")

    row.click()
    # It opened the test rather than staying on the file that was selected.
    expect(page.locator(".repo-file-head code")).to_have_text("tests/test_bad.py")


def test_a_repository_with_no_tests_is_not_reported_as_passing(page, api) -> None:
    """**The one that would be easiest to get wrong**, because "nothing failed"
    and "everything passed" are the same number. A green tick over a repository
    that has never had a test written in it is the suite-that-cannot-fail this
    repo does not accept, wearing the wrong colour."""
    mod = project(api, "Tests none")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/daily.py": "# no tests anywhere\n"})

    open_tests(page, repo, "src/daily.py")
    page.get_by_test_id("tests-run").click()
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the run up")

    verdict = page.get_by_test_id("tests-verdict")
    expect(verdict).to_contain_text("No unit tests found", timeout=30000)
    # And it says what the rule is, because somebody who has never written one
    # cannot be expected to know it.
    expect(verdict).to_contain_text("test_*.py")


def test_the_run_is_over_what_is_typed_rather_than_what_is_committed(page, api) -> None:
    """**The reason the working set travels** (db 0071). The question an author
    asks is "does what I just typed pass", and a runner that could only answer
    for committed code would answer a different one - convincingly, which is
    worse than not answering."""
    mod = project(api, "Tests working set")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"tests/test_edit.py": PASSING_TEST})

    open_tests(page, repo, "tests/test_edit.py")
    # Break it in the editor and do not commit.
    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type("\n\ndef test_typed_just_now():\n    assert 0\n")

    page.get_by_test_id("tests-run").click()
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the run up")

    expect(page.get_by_test_id("tests-verdict")).to_contain_text("1 failed", timeout=30000)
    expect(page.get_by_test_id("tests-list")).to_contain_text("test_typed_just_now")


# There was a test here asserting a viewer is not offered the Run button. It is
# gone because this suite signs in as one user and cannot be a viewer, so the
# assertion could only ever have been about something else - and the version
# that shipped first asserted branch protection instead, which is a different
# rule and does not hide the button at all. The real rule has three layers that
# can each be made to fail: `canEditProject` in
# `apps/web/src/lib/test-runs.test.ts`, the 403 in
# `apps/api/tests/test_repository_routes.py`, and the route's own dependency.


def test_the_button_does_not_invite_a_second_press_while_a_run_is_in_flight(
    page, api
) -> None:
    """The server refuses a fourth queued run over the same repository, and a
    button that still said "Run tests" would be walking people into that
    refusal. So it reports progress instead - and is disabled, because the
    press it would accept is one nobody wants."""
    mod = project(api, "Tests in flight")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"tests/test_ok.py": PASSING_TEST})

    open_tests(page, repo, "tests/test_ok.py")
    button = page.get_by_test_id("tests-run")
    expect(button).to_have_text("Run tests")

    button.click()
    # Queued and not yet worked: nothing has driven the poll, so this is the
    # in-flight state rather than a race against a finished run.
    expect(button).to_have_text("Running…", timeout=30000)
    expect(button).to_be_disabled()

    # And it comes back once there is an answer, rather than staying disabled
    # for the life of the page.
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the run up")
    expect(button).to_have_text("Run tests", timeout=30000)
    expect(button).to_be_enabled()


# ---- p.19: the Checks tab shows them too (§296) --------------------------------
def open_checks(page, repo: dict, branch: str = "main") -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=checks&branch={branch}")
    expect(page.get_by_test_id("checks-tab")).to_be_visible(timeout=30000)
    # **Visible, not merely present**, and a survivor is why. `to_contain_text`
    # matches an element nobody can see, so every assertion below passed with
    # the whole row hidden - a check that could not fail for the one failure
    # that matters most here, the tests not being on the tab at all.
    expect(page.get_by_test_id("checks-tests")).to_be_visible()


def test_the_checks_tab_says_what_the_unit_tests_did(page, api) -> None:
    """p.19: *"The Checks tab will also include the output of any unit tests
    that have been defined for your repo."*

    **And it names the failures rather than counting them.** "3 failed" sends
    you to the panel; `tests/test_bad.py::test_it_does_not_hold` sends you to
    the test.
    """
    mod = project(api, "Checks tests")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"tests/test_bad.py": FAILING_TEST})

    open_checks(page, repo)
    # Nothing has been asked for yet, and the row says which of the two empties
    # this is: press the button, not write a test.
    expect(page.get_by_test_id("checks-tests-summary")).to_contain_text(
        "No unit tests have been run"
    )

    open_tests(page, repo, "tests/test_bad.py")
    page.get_by_test_id("tests-run").click()
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the run up")

    open_checks(page, repo)
    expect(page.get_by_test_id("checks-tests-summary")).to_contain_text(
        "1 failed", timeout=30000
    )
    expect(page.get_by_test_id("checks-tests-failures")).to_contain_text(
        "tests/test_bad.py::test_it_does_not_hold"
    )


def test_the_checks_tab_does_not_call_an_empty_run_passed(page, api) -> None:
    """The same assertion the panel makes, on the third screen that could get
    it wrong. A green row for a repository nobody has written a test in is the
    suite-that-cannot-fail, and a Checks tab is exactly where somebody would
    trust it."""
    mod = project(api, "Checks tests empty")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/daily.py": "# no tests\n"})

    open_tests(page, repo, "src/daily.py")
    page.get_by_test_id("tests-run").click()
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the run up")

    open_checks(page, repo)
    row = page.get_by_test_id("checks-tests")
    expect(row).to_contain_text("failed", timeout=30000)
    expect(page.get_by_test_id("checks-tests-summary")).to_contain_text(
        "No unit tests in this repository"
    )


def test_the_checks_tab_asks_about_the_branch_it_is_showing(page, api) -> None:
    """**A survivor found this untested.** A tab that listed every branch's
    runs would put a sandbox's failures under `main` - and the Checks tab is
    where somebody decides whether a branch is in a state to merge, so a wrong
    answer here is a wrong answer at the worst moment."""
    mod = project(api, "Checks tests branch")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"tests/test_ok.py": PASSING_TEST})
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "sandbox", "from_branch": "main"})

    # A failing run on the sandbox only.
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/tests",
        {"branch": "sandbox", "overrides": {"tests/test_ok.py": FAILING_TEST}},
    )
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the run up")

    open_checks(page, repo, "sandbox")
    expect(page.get_by_test_id("checks-tests-summary")).to_contain_text(
        "1 failed", timeout=30000
    )

    # `main` has had no run at all, and must say so rather than borrowing the
    # sandbox's answer.
    open_checks(page, repo, "main")
    expect(page.get_by_test_id("checks-tests-summary")).to_contain_text(
        "No unit tests have been run", timeout=30000
    )
