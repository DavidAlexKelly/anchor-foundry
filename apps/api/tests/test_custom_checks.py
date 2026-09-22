"""A repository's own checks (§433; `code-repositories` p.98).

    "Custom checks can be created as Gradle tasks. These tasks should be added
     to the appropriate inner `build.gradle` files, within the language
     subfolders… In order for tasks to get executed during CI checks, there
     must be a CI task that depends on your custom task." (p.98)

Gradle is the mechanism and only the capability transfers: a repository can
define a check of its own that runs with the platform's and appears in the
Checks tab. The rules are declarative, because a Gradle task is arbitrary code
and decision 0004 already refuses to run a customer's code in the API.

The rules themselves are pure and tested here directly. The half that needs a
database is the one that matters most: that a declared check reaches
`code_proposal_checks`, that a failing one *blocks*, and that a rule nobody can
read is reported rather than skipped.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import custom_checks  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


# ---- the rules ---------------------------------------------------------------
def rule(**over) -> dict:
    """A well-formed rule with one operator.

    **`forbid` is dropped when the caller names `require`**, because a rule
    that names both is refused — which is the point of one of the tests below
    and would otherwise be the silent result of every other one.
    """
    base = {"name": "a-rule", "files": "*.sql", "forbid": "x"}
    if "require" in over:
        base.pop("forbid")
    return {**base, **over}


def only(settings: dict) -> custom_checks.Rule:
    rules, refused = custom_checks.parse(settings)
    assert not refused, [r.reason for r in refused]
    assert len(rules) == 1
    return rules[0]


def test_a_settings_file_with_no_checks_declares_none() -> None:
    assert custom_checks.parse({}) == ([], [])
    assert custom_checks.parse({"checks": []}) == ([], [])
    # Not a list is not a refusal: `read_settings` already tolerates a file
    # that will not parse, and a `checks` key of the wrong shape is the same
    # kind of nothing.
    assert custom_checks.parse({"checks": "no"}) == ([], [])


def test_a_rule_names_its_files_and_its_pattern() -> None:
    made = only({"checks": [rule(files="*.py", forbid="import os")]})
    assert made.files == "*.py"
    assert made.pattern.pattern == "import os"
    assert made.forbid is True
    assert made.check_name == "repo:a-rule"


def test_a_rule_with_no_files_pattern_looks_at_everything() -> None:
    # Omitted rather than empty: a rule about the whole repository is a
    # reasonable thing to write, and making it say `"*"` is ceremony.
    assert only({"checks": [{"name": "r", "forbid": "x"}]}).files == "*"


def test_a_checks_name_is_prefixed_so_it_cannot_overwrite_a_platform_check() -> None:
    """`code_proposal_checks` is keyed on `(proposal, model, path, name)`, so a
    repository declaring `schema_compatible` would not error — it would
    silently replace the platform's answer with its own."""
    made = only({"checks": [rule(name="schema_compatible")]})
    assert made.check_name == "repo:schema_compatible"
    assert made.check_name != "schema_compatible"


def test_a_rule_that_names_both_or_neither_operator_is_refused() -> None:
    _, refused = custom_checks.parse({"checks": [
        {"name": "both", "forbid": "a", "require": "b"},
        {"name": "neither", "files": "*.sql"},
    ]})
    assert [r.check_name for r in refused] == ["repo:both", "repo:neither"]
    assert "both" in refused[0].reason
    assert "neither" in refused[1].reason


def test_a_pattern_that_is_not_a_regex_is_refused_by_name() -> None:
    rules, refused = custom_checks.parse({"checks": [rule(forbid="(unclosed")]})
    assert rules == []
    assert len(refused) == 1
    assert refused[0].check_name == "repo:a-rule"
    assert "regular expression" in refused[0].reason


def test_a_very_long_pattern_is_refused() -> None:
    """A regex is code, and one assembled to be pathological is the ordinary
    way a validator becomes a denial of service — the same guard §299 put on
    the tag-name convention, for the same reason."""
    rules, refused = custom_checks.parse({"checks": [rule(forbid="a" * 500)]})
    assert rules == []
    assert "longer than" in refused[0].reason


def test_an_empty_pattern_is_refused() -> None:
    # `re.compile("")` matches everything, so a `require: ""` would pass
    # always and a `forbid: ""` would fail every file - both of which look
    # like a working check.
    rules, refused = custom_checks.parse({"checks": [rule(forbid="")]})
    assert rules == []
    assert "empty" in refused[0].reason


def test_a_rule_that_is_not_an_object_is_refused_where_it_is() -> None:
    """Named by position, because a rule with no name still has to be
    findable: "check 2" is a place in the file."""
    _, refused = custom_checks.parse({"checks": [rule(), "nonsense"]})
    assert [r.check_name for r in refused] == ["repo:check 2"]


def test_two_rules_with_one_name_are_refused_rather_than_merged() -> None:
    """One row in `code_proposal_checks`, so the second would silently replace
    the first and a reviewer would be told about half of what was asked for."""
    rules, refused = custom_checks.parse({"checks": [
        rule(name="same", forbid="a"), rule(name="same", forbid="b"),
    ]})
    assert [r.name for r in rules] == ["same"]
    assert rules[0].pattern.pattern == "a"
    assert "same name" in refused[0].reason


def test_more_rules_than_are_run_says_so() -> None:
    """Silence would be the worst outcome: the eleventh rule looks like it
    passed.

    **Thirteen written out, ten expected.** Counting from `MAX_RULES` makes a
    test that passes at any cap, including no cap at all — a sweep raising it
    to a hundred changed nothing (§432 found the same shape in a default
    compared to itself).
    """
    rules, refused = custom_checks.parse({"checks": [
        rule(name=f"r{i}") for i in range(13)
    ]})
    assert [r.name for r in rules] == [f"r{i}" for i in range(10)]
    assert refused[-1].check_name == "repo:too-many-checks"
    assert "13" in refused[-1].reason and "10" in refused[-1].reason


def test_one_bad_rule_does_not_stop_the_others() -> None:
    rules, refused = custom_checks.parse({"checks": [
        rule(name="good", forbid="a"),
        rule(name="bad", forbid="(unclosed"),
        rule(name="also-good", require="b"),
    ]})
    assert [r.name for r in rules] == ["good", "also-good"]
    assert [r.name for r in refused] == ["bad"]


# ---- what a rule looks at ----------------------------------------------------
FILES = {
    "src/a.sql": "SELECT * FROM t\n",
    "src/b.sql": "-- owner: ada\nSELECT id FROM t\n",
    "notes.md": "SELECT * FROM t\n",
    "repoSettings.json": '{"checks":[{"forbid":"SELECT *"}]}',
}


def test_a_files_pattern_crosses_directories() -> None:
    """`*.sql` matching `src/a.sql` is what somebody writing a settings file
    means. A shell's rule — where `*` stops at a separator — would make the
    obvious pattern match nothing at the one moment it has to be obvious."""
    assert custom_checks.scanned(FILES, "*.sql") == ["src/a.sql", "src/b.sql"]


def test_the_settings_file_is_never_scanned() -> None:
    """A rule forbidding `SELECT *` would otherwise find the words in the rule
    that forbids them, and report the repository's own conventions file as its
    first violation."""
    assert "repoSettings.json" not in custom_checks.scanned(FILES, "*")


def test_forbid_and_require_are_opposites_over_the_same_files() -> None:
    forbid = only({"checks": [rule(files="*.sql", forbid="-- owner:")]})
    require = only({"checks": [rule(files="*.sql", require="-- owner:")]})
    assert custom_checks.violations(forbid, FILES) == ["src/b.sql"]
    assert custom_checks.violations(require, FILES) == ["src/a.sql"]


def test_a_pattern_matches_anywhere_in_a_file() -> None:
    """`search`, not `fullmatch`: a rule is about something appearing
    somewhere, which is the only thing a pattern over a whole source file can
    usefully mean."""
    made = only({"checks": [rule(files="*.sql", forbid="FROM t")]})
    assert custom_checks.violations(made, FILES) == ["src/a.sql", "src/b.sql"]


# ---- what it says ------------------------------------------------------------
def test_a_rule_that_looked_at_nothing_warns_rather_than_passes() -> None:
    """"Nothing broke this rule" and "this rule looked at nothing" are the same
    green tick otherwise, and the second is usually a `files` pattern with a
    typo in it — which is exactly the check somebody thinks is protecting
    them (§226)."""
    made = only({"checks": [rule(files="*.java")]})
    status, summary = custom_checks.summarise(made, [], 0)
    assert status == "warn"
    assert "*.java" in summary


def test_a_rule_nothing_broke_passes_and_says_how_much_it_read() -> None:
    made = only({"checks": [rule(files="*.sql")]})
    status, summary = custom_checks.summarise(made, [], 2)
    assert status == "pass"
    assert "2 files checked" in summary


def test_a_failure_uses_the_repositorys_own_sentence() -> None:
    """The same argument p.17's `errorMessage` makes for tag names (§299):
    somebody wrote that sentence for their colleagues."""
    made = only({"checks": [rule(message="Name the columns you need.")]})
    status, summary = custom_checks.summarise(made, ["src/a.sql"], 2)
    assert status == "fail"
    assert summary.startswith("Name the columns you need.")
    assert "src/a.sql" in summary


def test_a_failure_without_a_message_describes_the_rule() -> None:
    made = only({"checks": [rule(files="*.sql", forbid="SELECT")]})
    _, summary = custom_checks.summarise(made, ["src/a.sql"], 2)
    assert "1 file matches" in summary
    made = only({"checks": [rule(files="*.sql", require="SELECT")]})
    _, summary = custom_checks.summarise(made, ["src/a.sql"], 2)
    assert "1 file does not match" in summary


def test_a_long_list_of_offenders_is_counted_rather_than_listed() -> None:
    """The point of the summary is to be read; the whole list is in `detail`."""
    made = only({"checks": [rule()]})
    paths = [f"src/{i}.sql" for i in range(12)]
    _, summary = custom_checks.summarise(made, paths, 12)
    assert "and 7 more" in summary
    assert summary.count("src/") == custom_checks.NAMED_PATHS


# ---- through the API ---------------------------------------------------------
def rbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/repositories"


def cbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/code"


def make_repo(client: TestClient, fx: Fixture) -> dict:
    r = client.post(rbase(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Transforms {uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()


def commit(client: TestClient, fx: Fixture, repo_id: str, files: dict) -> dict:
    r = client.post(f"{rbase(fx)}/{repo_id}/commits", headers=hdr(fx.editor_sub),
                    json={"branch": "main", "files": files, "message": "a change"})
    assert r.status_code == 201, r.text
    return r.json()


def declaring(name: str) -> str:
    return f"-- output: {name}\nSELECT 1 AS id\n"


def propose(client: TestClient, fx: Fixture, repo: dict, made: dict) -> dict:
    r = client.post(f"{cbase(fx)}/proposals", headers=hdr(fx.editor_sub),
                    json={"summary": "Publish it", "description": "",
                          "source_repo_id": repo["id"], "source_commit_id": made["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def run(client: TestClient, fx: Fixture, proposal_id: str) -> dict:
    r = client.post(f"{cbase(fx)}/proposals/{proposal_id}/checks", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


def named(detail: dict, name: str) -> dict | None:
    return next((c for c in detail["checks"] if c["name"] == name), None)


def test_a_declared_check_runs_with_the_platforms(client: TestClient, fx: Fixture) -> None:
    """**The unit, end to end.** p.98's custom check, in the Checks tab beside
    the ones this platform runs itself."""
    repo = make_repo(client, fx)
    made = commit(client, fx, repo["id"], {
        "src/a.sql": declaring(f"daily_{uuid.uuid4().hex[:8]}"),
        "repoSettings.json": json.dumps({"checks": [
            {"name": "has-output", "files": "*.sql", "require": "-- output:"},
        ]}),
    })
    detail = run(client, fx, propose(client, fx, repo, made)["id"])

    mine = named(detail, "repo:has-output")
    assert mine is not None, [c["name"] for c in detail["checks"]]
    assert mine["status"] == "pass"
    # And the platform's own checks are still there beside it.
    assert named(detail, "transform_runs") is not None


def test_a_failing_declared_check_blocks_applying(client: TestClient, fx: Fixture) -> None:
    """p.98's check runs in CI, and a CI check that fails stops the merge.
    Nothing special is needed for that here: `fail` is already the only
    blocking status, so a repository's own rule gates exactly as the
    platform's does."""
    repo = make_repo(client, fx)
    name = f"daily_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {
        "src/a.sql": f"-- output: {name}\nSELECT * FROM (SELECT 1 AS id)\n",
        "repoSettings.json": json.dumps({"checks": [
            {"name": "no-select-star", "files": "*.sql", "forbid": r"SELECT\s+\*",
             "message": "Name the columns you need."},
        ]}),
    })
    proposal = propose(client, fx, repo, made)
    detail = run(client, fx, proposal["id"])

    mine = named(detail, "repo:no-select-star")
    assert mine is not None and mine["status"] == "fail", mine
    assert mine["summary"].startswith("Name the columns you need.")
    assert any("Name the columns you need." in b for b in detail["blockers"]), detail["blockers"]

    # And it really refuses, rather than only saying it would.
    client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                headers=hdr(fx.owner_sub), json={"verdict": "approve"})
    refused = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/apply",
                          headers=hdr(fx.editor_sub))
    assert refused.status_code == 422, refused.text
    assert "Name the columns you need." in refused.text


def test_a_rule_nobody_can_read_is_reported_rather_than_skipped(
    client: TestClient, fx: Fixture
) -> None:
    """**The one place this disagrees with `read_settings`.**

    A malformed tag-name convention is skipped, because a convention that
    fails closed blocks work while the person who can fix it is elsewhere. A
    check is the opposite: its whole job is to tell a reviewer something, and
    one that quietly did not run leaves the Checks tab looking like there was
    nothing to check. `error` says so and does not gate.
    """
    repo = make_repo(client, fx)
    made = commit(client, fx, repo["id"], {
        "src/a.sql": declaring(f"daily_{uuid.uuid4().hex[:8]}"),
        "repoSettings.json": json.dumps({"checks": [
            {"name": "broken", "files": "*.sql", "forbid": "(unclosed"},
        ]}),
    })
    proposal = propose(client, fx, repo, made)
    detail = run(client, fx, proposal["id"])

    mine = named(detail, "repo:broken")
    assert mine is not None and mine["status"] == "error", mine
    assert "repoSettings.json" in mine["summary"]
    # Nobody is blocked by a typo in a settings file.
    assert detail["blockers"] == [] or all(
        "broken" not in b for b in detail["blockers"]
    ), detail["blockers"]


def test_a_repository_that_declares_nothing_gets_no_extra_checks(
    client: TestClient, fx: Fixture
) -> None:
    """The feature is absent until somebody asks for it, which is what makes
    `repoSettings.json` the right home: no rows, no settings table, nothing to
    migrate."""
    repo = make_repo(client, fx)
    made = commit(client, fx, repo["id"],
                  {"src/a.sql": declaring(f"daily_{uuid.uuid4().hex[:8]}")})
    detail = run(client, fx, propose(client, fx, repo, made)["id"])
    assert [c for c in detail["checks"] if c["name"].startswith("repo:")] == []


def test_a_proposal_that_names_no_repository_asks_for_no_settings(
    client: TestClient, fx: Fixture
) -> None:
    """**A typed-changes proposal has no repository, so it has no settings.**

    Silence rather than a refusal: there is no repository that could have
    declared a check. Worth a test in this file rather than relying on the
    review suite's, because the early return is this file's code — and a
    version without it does not quietly do nothing, it asks the database for a
    repository whose id is the string "None".
    """
    model = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/models",
        headers=hdr(fx.editor_sub),
        json={"name": f"Typed {uuid.uuid4().hex[:6]}", "code": "SELECT 1 AS id",
              "inputs": []},
    )
    assert model.status_code == 201, model.text
    proposal = client.post(
        f"{cbase(fx)}/proposals", headers=hdr(fx.editor_sub),
        json={"summary": "A typed change", "description": "",
              "changes": [{"model_id": model.json()["id"], "code": "SELECT 2 AS id"}]},
    )
    assert proposal.status_code == 201, proposal.text

    detail = run(client, fx, proposal.json()["id"])
    assert [c for c in detail["checks"] if c["name"].startswith("repo:")] == []


def test_a_rule_that_matched_no_files_warns_on_the_screen(
    client: TestClient, fx: Fixture
) -> None:
    repo = make_repo(client, fx)
    made = commit(client, fx, repo["id"], {
        "src/a.sql": declaring(f"daily_{uuid.uuid4().hex[:8]}"),
        "repoSettings.json": json.dumps({"checks": [
            {"name": "java-only", "files": "*.java", "forbid": "System.out"},
        ]}),
    })
    detail = run(client, fx, propose(client, fx, repo, made)["id"])
    mine = named(detail, "repo:java-only")
    assert mine is not None and mine["status"] == "warn", mine
    assert "looked at nothing" in mine["summary"]
