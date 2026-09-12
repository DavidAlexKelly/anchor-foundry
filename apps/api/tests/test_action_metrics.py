"""Action metrics (§323; db 0079; `action-types` p.164-166).

    "Action metrics display the near real-time usage of an action type over the
     last 30 days… Success/failure metrics: Monitor the current status of your
     actions with success and failure counts… P95 duration metric: Track the
     95th percentile (P95) execution duration for each action type." (p.164)

    "You are also able to access run history, which provides a complete view of
     a given action's executions over the past seven days." (p.164)

    "Action metrics do not require action logs to be displayed. **Unlike action
     logs, action metrics track failures.**" (p.165)

**The suite is built around that last sentence**, because it is the one this
platform did not satisfy. `action_runs` has recorded failures since db 0013,
but every refusal here is raised *before* `open_run` — so the only failure the
metric could ever see was a dataset engine error, which is to say a failure
nobody submitted. An invalid parameter and a failed submission criterion, the
two things a person actually does wrong, produced a 422 and no trace.

So the tests that matter below are the ones that submit something wrong and
then look for it in the numbers. They are also the ones with a trap in them:
the refusal is *raised*, and a raise unwinds `user_connection`'s transaction —
so a record written on the request's own connection is rolled back by the very
exception it exists to describe, and every assertion about "the 422 came back"
still passes over a dead feature.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import action_metrics  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN",
    "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
)

PEOPLE = b"person_id,name,email\nm1,Ada Lovelace,ada@example.com\nm2,Grace Hopper,grace@example.com\n"


# ---- p.166's categories, decided without a database ---------------------------
def test_a_collision_is_p166_s_conflict() -> None:
    """p.166: "failed due to a conflict, such as a concurrent modification".

    A primary key collision is exactly that — an action creating a row somebody
    else's action already created — and it is the one engine failure this
    platform can name.
    """
    for said in (
        'duplicate key value violates unique constraint "x_pkey"',
        "Constraint Error: object already exists",
        "concurrent update detected",
        # **Shouted, which is how a lot of engines say it.** The marks are
        # written in lower case and the message is folded before they are
        # looked for; without a capitalised case here, a classifier that
        # dropped the fold would answer correctly on every string this suite
        # had and wrongly on half the ones a real engine sends.
        "DUPLICATE KEY value violates unique constraint",
        "Constraint Error: object ALREADY EXISTS",
    ):
        assert action_metrics.classify_engine_error(said) == "conflict", said


def test_everything_else_is_p166_s_unclassified() -> None:
    """**Guessing more finely would be worse than not guessing.**

    "Conversion Error: could not convert string" looks like an invalid
    parameter and is not: the parameter passed this platform's own type check
    on the way in, so the disagreement is between the ontology's declared type
    and the dataset's column. Calling that an invalid parameter would send
    somebody to re-read a form they filled in correctly.
    """
    for said in (
        "Conversion Error: could not convert string 'x' to INT32",
        "Binder Error: column does not exist",
        "could not write parquet file",
        "",
    ):
        assert action_metrics.classify_engine_error(said) == "unclassified", said


def test_the_categories_are_p165_s_own_and_the_function_ones_are_absent() -> None:
    """p.166 names two categories as "only possible for function-backed
    actions", and Functions are ○ here.

    A value nothing can produce is a category that sits in every list and never
    appears, which is §214's control that looks like it works. Asserted rather
    than left to the comment in db 0079, because the day Functions arrive this
    line is the one that says the tuple has to grow.
    """
    assert "function" not in action_metrics.FAILURE_CATEGORIES
    assert "user_facing_function" not in action_metrics.FAILURE_CATEGORIES
    assert action_metrics.FAILURE_CATEGORIES[-1] == "unclassified"


def labelled_categories() -> set[str]:
    """The categories the browser has words for, read out of the TypeScript.

    Crude on purpose: a real parse would need a toolchain in this suite, and
    what is being checked is that two lists in two languages say the same
    thing. If the regex stops matching, `test_every_category_has_words`'s
    vacuity guard fails rather than the comparison passing over nothing.
    """
    import re

    # Four levels: tests -> api -> apps -> the repository root.
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    src = open(
        os.path.join(root, "apps", "web", "src", "lib", "action-metrics.ts"),
        encoding="utf-8",
    ).read()
    body = src.split("FAILURE_LABELS", 1)[1].split("};", 1)[0]
    return set(re.findall(r"^\s{2}(\w+):\s*\{", body, re.MULTILINE))


def test_every_category_has_words_on_the_screen() -> None:
    """**The drift the type system cannot see** (§315's pattern).

    `FAILURE_CATEGORIES` is a Python tuple and `FAILURE_LABELS` is a TypeScript
    object, and nothing but this line connects them. A category added to db
    0079 and not to the browser draws as a bar labelled with its own column
    value — `invalid_parameter` printed at somebody, which is a screen that
    made them learn a database's vocabulary to read a chart.
    """
    labelled = labelled_categories()
    assert labelled, "the labels could not be read; this check was about to pass over nothing"
    assert labelled == set(action_metrics.FAILURE_CATEGORIES), (
        "db 0079's categories and the browser's words for them have drifted: "
        f"only in the server {set(action_metrics.FAILURE_CATEGORIES) - labelled}, "
        f"only in the browser {labelled - set(action_metrics.FAILURE_CATEGORIES)}"
    )


def test_the_two_windows_are_p164_s_two_windows() -> None:
    """p.164 gives the metrics thirty days and the run history seven, and they
    are two decisions rather than one with a fraction in it."""
    assert action_metrics.METRICS_DAYS == 30
    assert action_metrics.HISTORY_DAYS == 7


# ---- the metrics over runs that really happened -------------------------------
@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("metrics-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    """A dataset, a type mapped to it, and an action that edits it.

    **Its own action type, not one shared with another suite.** Every number
    here is a count over one action type, so a second suite applying the same
    action would move them — which is the sort of failure that only appears
    when the whole file runs together.
    """
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"MetricPeople {fx.tag}"},
        files={"file": ("people.csv", io.BytesIO(PEOPLE), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"metric_person_{fx.tag}",
              "display_name": f"Metric person {fx.tag}",
              "properties": [{"api_name": "name", "data_type": "string"},
                             {"api_name": "email", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset_id,
              "primary_key_column": "person_id",
              "column_mappings": {"name": "name", "email": "email"}},
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    assert client.post(f"{pbase(fx)}/object-type-sources/{source_id}/sync",
                       headers=hdr(fx.editor_sub)).status_code == 200

    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "api_name": "amend_contact",
              "display_name": "Amend contact",
              "editable_properties": ["name", "email"]},
    )
    assert r.status_code == 201, r.text
    return {"dataset_id": dataset_id, "type_id": type_id,
            "action_id": r.json()["id"]}


def an_instance(client: TestClient, fx: Fixture, world: dict, key: str) -> str:
    """One object by **primary key**, the one field these tests never edit."""
    r = client.get(f"{wbase(fx)}/object-types/{world['type_id']}/instances",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["primary_key"] == key)["id"]


def submit(client: TestClient, fx: Fixture, world: dict, values: dict,
           key: str = "m1", sub: str | None = None):
    return client.post(
        f"{pbase(fx)}/actions/{world['action_id']}/execute",
        headers=hdr(sub or fx.editor_sub),
        json={"instance_id": an_instance(client, fx, world, key),
              "values": values},
    )


def metrics(client: TestClient, fx: Fixture, world: dict,
            sub: str | None = None):
    return client.get(
        f"{wbase(fx)}/action-types/{world['action_id']}/metrics",
        headers=hdr(sub or fx.viewer_sub),
    )


def history(client: TestClient, fx: Fixture, world: dict):
    r = client.get(f"{wbase(fx)}/action-types/{world['action_id']}/history",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def failures_of(body: dict) -> dict[str, int]:
    return {f["category"]: f["failures"] for f in body["failures"]}


def _add_criterion(action_id: str, config: str, message: str) -> None:
    """Straight into the database, as `test_action_criteria.py` does: there is
    no criterion editor, and what matters is what the executor does with one."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO action_criteria (action_type_id, message, config) "
            "VALUES (%s, %s, %s::jsonb)",
            (action_id, message, config),
        )


def test_nothing_has_happened_and_that_is_not_a_p95_of_nought(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**`None`, not zero.** A P95 of 0 seconds says every run was instant,
    which is a different and much more flattering claim than "no run has
    finished in the window"."""
    r = metrics(client, fx, world)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["succeeded"], body["failed"], body["running"]) == (0, 0, 0)
    assert body["p95_seconds"] is None
    assert body["total"] == 0
    assert body["window_days"] == 30
    assert body["failures"] == []


def test_a_successful_apply_is_counted_and_timed(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.164's success count and P95, over a run that really wrote a dataset."""
    assert submit(client, fx, world, {"email": "ada@metrics.test"}).status_code == 200

    body = metrics(client, fx, world).json()
    assert body["succeeded"] == 1
    assert body["failed"] == 0
    assert body["total"] == 1
    # It finished, so it has a duration — and the duration is a real number of
    # seconds rather than the `None` that means "nothing has finished".
    assert body["p95_seconds"] is not None
    assert body["p95_seconds"] >= 0


def test_an_invalid_parameter_is_p165_s_first_category(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**p.165's sentence, and the trap underneath it.**

    "Unlike action logs, action metrics track failures" — so a submission
    naming a parameter this action does not have must appear in the numbers.
    Until §323 it did not: the refusal is raised before `open_run`, so there
    was no run to fail.

    And the fix has a second trap: the refusal unwinds the request's
    transaction, so a record written on the request's own connection is rolled
    back by the exception it describes. The 422 below is true either way. The
    count is what tells the two apart.
    """
    before = metrics(client, fx, world).json()["failed"]
    r = submit(client, fx, world, {"not_a_parameter": "x"})
    assert r.status_code == 422, r.text

    body = metrics(client, fx, world).json()
    assert body["failed"] == before + 1, (
        "a refused submission is a failure p.165 says the metric tracks"
    )
    assert failures_of(body).get("invalid_parameter") == 1


def test_a_failed_criterion_is_p166_s_authentication_failure(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.166: "did not pass the security submission criteria".

    Its own category, and not `invalid_parameter`: the parameter was fine and
    the person was not allowed to send it, which sends somebody to ask for
    access rather than to correct a form.
    """
    _add_criterion(
        world["action_id"],
        '{"left": {"kind": "parameter", "parameter": "name"},'
        ' "operator": "is_not", "right": {"kind": "value", "value": "Refused"}}',
        "That name is not allowed from here.",
    )
    before = failures_of(metrics(client, fx, world).json())
    r = submit(client, fx, world, {"name": "Refused"})
    assert r.status_code == 422, r.text
    # **The criterion's own message and nothing appended to it.** An
    # unevaluable criterion also refuses, and also counts as an authentication
    # failure — so "it was refused" and "the category moved" are both satisfied
    # by a criterion whose config this suite got wrong. They were: the first
    # version of this test wrote a condition side that does not exist, and
    # every assertion below passed over a criterion that could not be read.
    assert r.json()["detail"] == "That name is not allowed from here.", (
        "refused because the rule said no, not because the rule was unreadable"
    )

    now = failures_of(metrics(client, fx, world).json())
    assert now.get("authentication", 0) == before.get("authentication", 0) + 1
    # The other category did not move: a refusal counted under two headings
    # would make the chart add up to more than the failure count beside it.
    assert now.get("invalid_parameter", 0) == before.get("invalid_parameter", 0)


def test_a_refused_submission_survives_the_rollback_it_caused(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**The one assertion that is about the mechanism rather than the number.**

    Read straight out of the database with a second connection, so a row that
    existed only inside the request's doomed transaction cannot answer. This is
    the check that would have failed for the obvious implementation — the one
    that passes `conn` to `record_refusal` — and every count above would still
    have been right at the moment it was taken and wrong a millisecond later.
    """
    assert submit(client, fx, world, {"still_not_a_parameter": 1}).status_code == 422
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT status, failure_category, finished_at, error "
            "  FROM action_runs "
            " WHERE action_type_id = %s AND failure_category = 'invalid_parameter' "
            " ORDER BY started_at DESC LIMIT 1",
            (world["action_id"],),
        ).fetchall()
    assert rows, "the refusal left no row behind"
    status, category, finished_at, error = rows[0]
    assert (status, category) == ("failed", "invalid_parameter")
    # Opened and closed in the same breath: a refusal is not a run somebody is
    # waiting on, and one left `running` would sit in the third count forever.
    assert finished_at is not None
    assert "still_not_a_parameter" in (error or "")


def test_the_counts_add_up_to_the_total(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """The number somebody checks first when they think a metric is lying.

    `running` is reported as itself rather than folded into either side — a run
    that has not finished is neither a success nor a failure — so the three
    have to sum to the total or one of them is being counted twice.
    """
    body = metrics(client, fx, world).json()
    assert body["succeeded"] + body["failed"] + body["running"] == body["total"]
    assert body["failed"] == sum(failures_of(body).values()), (
        "every failure has exactly one of p.166's categories"
    )


def test_the_history_is_newest_first_and_names_who_submitted(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.164's run history: "a complete view of a given action's executions".

    Newest first, which is the opposite of §322's conversation and the same as
    every other "what happened" list here — somebody opens it to find out what
    just went wrong.
    """
    rows = history(client, fx, world)
    assert rows, "runs have happened"
    times = [r["started_at"] for r in rows]
    assert times == sorted(times, reverse=True)
    assert any(r["requested_by_name"] for r in rows), (
        "a run with no author is one nobody can ask about"
    )


def test_the_history_shows_the_refusals_as_well_as_the_applies(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """The same claim as the counts, one row at a time.

    A history that listed only the runs that opened would disagree with the
    failure count above it, which is worse than either number on its own: a
    reader who clicks the failures to see them finds nothing there.
    """
    rows = history(client, fx, world)
    refused = [r for r in rows if r["failure_category"] == "invalid_parameter"]
    assert refused, "a refused submission is an execution p.164 lists"
    assert refused[0]["status"] == "failed"
    assert refused[0]["error"]
    succeeded = [r for r in rows if r["status"] == "succeeded"]
    assert succeeded, "and so is one that worked"
    assert succeeded[0]["failure_category"] is None, (
        "a category on a run that worked is a column with a meaning for one "
        "value of another column"
    )


def test_a_viewer_may_read_the_metrics(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.164 puts metrics on the action type's own page, which a viewer can
    already open — and a success count is not more sensitive than the list of
    runs it counts."""
    assert metrics(client, fx, world, sub=fx.viewer_sub).status_code == 200
    assert history(client, fx, world)


def test_an_outsider_reads_nothing(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """How often an action fails is a fact about somebody else's workspace."""
    r = metrics(client, fx, world, sub=fx.outsider_sub)
    assert r.status_code in (403, 404), r.text
    r = client.get(f"{wbase(fx)}/action-types/{world['action_id']}/history",
                   headers=hdr(fx.outsider_sub))
    assert r.status_code in (403, 404), r.text


def test_an_engine_failure_is_classified_when_it_is_caught(
    client: TestClient, fx: Fixture, world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third source of failures, and the only one that existed before §323.

    Forced rather than provoked: a real collision needs two writers racing, and
    what is being checked is that `close_run` asks `classify_engine_error`
    rather than storing `NULL` and leaving the category to be guessed from the
    message later (db 0079).

    The break is put in `write_rows` because that is the call that runs *after*
    `open_run` — which is the whole distinction this file turns on. A failure
    reaching here has a run to fail; the two above did not, and that is why
    they had to be given one.
    """
    from src.routes import actions as action_routes
    from src.services.dataset_engine import DatasetEngineError

    def boom(*a, **k):
        raise DatasetEngineError("duplicate key value violates unique constraint")

    monkeypatch.setattr(action_routes.engine, "write_rows", boom)
    before = failures_of(metrics(client, fx, world).json())
    r = submit(client, fx, world, {"email": "clash@metrics.test"}, key="m2")
    # The run opened, so this is a 200 reporting a failure rather than a 422.
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False

    now = failures_of(metrics(client, fx, world).json())
    assert now.get("conflict", 0) == before.get("conflict", 0) + 1


# ---- the states a handful of real runs cannot produce -------------------------
#
# **Seeded straight into `action_runs`, and that is the point.** What the tests
# below check is arithmetic in one SQL statement — a window boundary, a
# percentile over a distribution, a status that is neither outcome, a page limit
# — and none of them can be reached by applying an action a few times: a real
# run always finishes, always finishes now, and always takes about the same
# fraction of a second. Twenty applications would be twenty durations clustered
# inside a tenth of a second, which is a distribution no percentile can be wrong
# about.
#
# The mutation sweep is what said so. `percentile_disc` → `percentile_cont`,
# thirty days → nine hundred, a `running` run counted as a failure, and a
# history with no `LIMIT` all survived a suite of real applications: every
# assertion in it was true, and none of them reached the branch it was about.


def seed(action_id: str, user_id, rows: list[dict]) -> None:
    """Write runs with the durations, ages and statuses a test chooses.

    Offsets in seconds rather than timestamps, so a row reads as "began forty
    days ago and took three seconds" instead of as two absolute times the
    reader has to subtract.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for row in rows:
            began = row["began_secs_ago"]
            took = row.get("took_secs")
            conn.execute(
                "INSERT INTO action_runs (action_type_id, requested_by, status, "
                "       failure_category, started_at, finished_at) "
                "VALUES (%s, %s, %s, %s, now() - make_interval(secs => %s), "
                "        CASE WHEN %s::float IS NULL THEN NULL "
                "             ELSE now() - make_interval(secs => %s) END)",
                (action_id, str(user_id), row["status"], row.get("category"),
                 began, took, began - (took or 0)),
            )


def a_spare_action(client: TestClient, fx: Fixture, world: dict) -> str:
    """Another action type on the same object type, for seeded runs.

    **Its own, every time.** Every number here is a count over one action type,
    and these rows are chosen to put a percentile in a known place — seeding
    them onto a shared action would move what the tests above assert, and
    sharing one between the tests below would make each depend on the order the
    others ran in.
    """
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": world["type_id"],
              "api_name": f"seeded_{uuid.uuid4().hex[:8]}",
              "display_name": "Seeded runs", "editable_properties": ["name"]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def metrics_of(client: TestClient, fx: Fixture, action_id: str) -> dict:
    r = client.get(f"{wbase(fx)}/action-types/{action_id}/metrics",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def history_of(client: TestClient, fx: Fixture, action_id: str) -> list[dict]:
    r = client.get(f"{wbase(fx)}/action-types/{action_id}/history",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


DAY = 24 * 60 * 60


def test_a_run_older_than_the_window_is_not_counted(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.164's window is "the last 30 days", which is a claim about what is
    **left out**.

    A suite whose runs all happened moments ago cannot tell a thirty-day window
    from a thirty-year one — every assertion is true under both. So one run is
    placed outside it and the count is asserted to have ignored it.
    """
    action = a_spare_action(client, fx, world)
    seed(action, fx.editor, [
        {"began_secs_ago": 2 * DAY, "took_secs": 1, "status": "succeeded"},
        {"began_secs_ago": 60 * DAY, "took_secs": 1, "status": "succeeded"},
    ])
    body = metrics_of(client, fx, action)
    assert body["succeeded"] == 1, "the sixty-day-old run is outside p.164's window"
    assert body["total"] == 1


def test_a_running_run_is_neither_outcome(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**The third state, which no real run in this suite stays in.**

    An action here finishes inside the request that started it, so `running` is
    a status the other tests can never observe — and a mutant folding it into
    the failures survived every one of them. Counted as itself, it also stays
    out of the P95: a run still going has no duration, and treating its elapsed
    time as one would make the percentile fall as soon as anybody looked.
    """
    action = a_spare_action(client, fx, world)
    seed(action, fx.editor, [
        {"began_secs_ago": 90, "took_secs": 5, "status": "succeeded"},
        {"began_secs_ago": 30, "took_secs": None, "status": "running"},
    ])
    body = metrics_of(client, fx, action)

    assert body["running"] == 1
    assert body["failed"] == 0, "a run still going has not failed"
    assert body["succeeded"] == 1, "nor has it succeeded"
    assert body["total"] == 2
    assert body["p95_seconds"] == 5, (
        "an unfinished run has no duration to put in the percentile — its "
        "elapsed time is not one"
    )


def test_the_p95_is_the_95th_percentile_of_durations_that_happened(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.164's P95, over a distribution wide enough to be wrong about.

    **Two claims, and each kills a different mutant.** That it is a *discrete*
    percentile — the answer is a duration some run actually took, not one
    interpolated between two that did, which is the honest reading of p.164's
    "upper range of execution times". And that it is the ninety-fifth rather
    than the fiftieth: twenty runs of one to twenty seconds have a median of
    ten and a P95 of nineteen, and a suite whose runs all take the same
    fraction of a second cannot tell those apart.
    """
    action = a_spare_action(client, fx, world)
    seed(action, fx.editor,
         [{"began_secs_ago": 3600, "took_secs": n, "status": "succeeded"}
          for n in range(1, 21)])
    body = metrics_of(client, fx, action)

    assert body["succeeded"] == 20
    p95 = body["p95_seconds"]
    # A whole number of seconds: every run took one, so an interpolating
    # percentile — 19.05 over this set — is a duration nothing took.
    assert p95 == int(p95), f"P95 {p95} falls between two runs rather than on one"
    assert 1 <= p95 <= 20
    # And it is the upper range rather than the middle of it.
    assert p95 > 10, f"P95 {p95} is a median, not a 95th percentile"


def test_a_failure_recorded_before_db_0079_is_still_counted(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**The rows that predate the column**, of which this build's development
    database holds 515.

    `failure_category` is nullable and every failure written since db 0079 has
    one, so nothing this suite does produces a `NULL` — and a query that
    dropped those rows would give a breakdown adding up to less than the
    failure count printed above it. `COALESCE` puts them in p.166's own last
    category, which is what "unclassified" is for.
    """
    action = a_spare_action(client, fx, world)
    seed(action, fx.editor, [
        {"began_secs_ago": 60, "took_secs": 1, "status": "failed", "category": None},
        {"began_secs_ago": 50, "took_secs": 1, "status": "failed",
         "category": "conflict"},
    ])
    body = metrics_of(client, fx, action)

    counted = {f["category"]: f["failures"] for f in body["failures"]}
    assert body["failed"] == 2
    # **And no success was invented.** Two failures and nothing else is the one
    # shape that tells `status = 'succeeded'` from `status IN ('succeeded',
    # 'failed')` — every test above this one asserted `succeeded` while there
    # were no failures yet, where the two spellings agree.
    assert body["succeeded"] == 0, "a failure is not a success"
    assert counted == {"unclassified": 1, "conflict": 1}
    assert sum(counted.values()) == body["failed"], (
        "a breakdown that drops rows adds up to less than the count above it"
    )


def test_the_breakdown_is_biggest_first(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """The order, which needs two categories of **different** sizes to exist.

    Every other test here reads the breakdown into a dict, which throws the
    order away — so a query sorting ascending was indistinguishable from one
    sorting descending. Somebody opening this list is looking for the biggest
    cause of failure, and finding it last is finding it after reading the rest.
    """
    action = a_spare_action(client, fx, world)
    seed(action, fx.editor,
         [{"began_secs_ago": 60, "took_secs": 1, "status": "failed",
           "category": "conflict"}]
         + [{"began_secs_ago": 50, "took_secs": 1, "status": "failed",
             "category": "invalid_parameter"} for _ in range(3)])
    body = metrics_of(client, fx, action)

    assert [f["category"] for f in body["failures"]] == [
        "invalid_parameter", "conflict",
    ]
    assert [f["failures"] for f in body["failures"]] == [3, 1]


def test_the_history_is_one_action_type_s(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**Two action types, which is the only pair that can disagree.**

    A history keyed on nothing still returns exactly the runs a test made when
    the test made all of them — the query is wrong and the answer is right.
    Two actions make the two differ: the other action's failures would appear
    under this one, and somebody diagnosing a broken action would be reading
    about a different one.
    """
    mine = a_spare_action(client, fx, world)
    theirs = a_spare_action(client, fx, world)
    seed(mine, fx.editor, [{"began_secs_ago": 60, "took_secs": 1,
                            "status": "succeeded"}])
    seed(theirs, fx.editor, [{"began_secs_ago": 60, "took_secs": 1,
                              "status": "failed", "category": "conflict"}])

    rows = history_of(client, fx, mine)
    assert [r["status"] for r in rows] == ["succeeded"]
    assert history_of(client, fx, theirs) and [
        r["status"] for r in history_of(client, fx, theirs)
    ] == ["failed"]


def test_the_history_is_a_page_rather_than_everything(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.164 says "complete", and seven days of a busy action is not a list
    anybody reads — so the window is the promise and `HISTORY_LIMIT` is the
    page (§256).

    Seeded past the limit because nothing else here comes near it: a suite that
    makes four runs cannot tell a limit of two hundred from no limit at all,
    and the mutant removing the `LIMIT` survived every test in this file.
    """
    action = a_spare_action(client, fx, world)
    over = action_metrics.HISTORY_LIMIT + 1
    seed(action, fx.editor,
         [{"began_secs_ago": 100 + n, "took_secs": 1, "status": "succeeded"}
          for n in range(over)])

    rows = history_of(client, fx, action)
    assert len(rows) == action_metrics.HISTORY_LIMIT, (
        f"seeded {over} runs and the history returned {len(rows)}"
    )
    # Newest first, so the page that is returned is the recent end of the list
    # rather than an arbitrary slice of it.
    times = [r["started_at"] for r in rows]
    assert times == sorted(times, reverse=True)


def test_a_category_this_platform_cannot_produce_is_refused(
) -> None:
    """The guard on `record_refusal`, which nothing else reaches.

    db 0079's CHECK would reject the row anyway — but it would reject it as a
    database error inside a request already unwinding from a refusal, which is
    a failure to record a failure and would surface as a 500 over a 422. The
    guard names the mistake where somebody can read it.

    Run with `asyncio.run` because the check happens **before** the connection
    is opened, which is also the claim: a bad category costs nothing.
    """
    import asyncio

    with pytest.raises(ValueError) as refused:
        asyncio.run(action_metrics.record_refusal(
            action_type_id=uuid.uuid4(), instance_id=None, dataset_id=None,
            requested_by=uuid.uuid4(), submitted_values={},
            category="function", message="a function that does not exist failed",
        ))
    # p.166's two function categories are the realistic mistake — they are on
    # the page, and absent here on purpose — so the message names what is
    # allowed rather than only what was wrong.
    assert "function" in str(refused.value)
    assert "invalid_parameter" in str(refused.value)
