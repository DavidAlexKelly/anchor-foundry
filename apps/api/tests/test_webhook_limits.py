"""A webhook's concurrency and rate limits (§522; db 0111; `data-connection`
p.240).

    "For each Webhook, you can set three types of limits that constrain how
     the Webhook can be executed: time limits, concurrency limits, and rate
     limits." (p.240)

Against `webhook_fixture_server.py`, through `test_webhook_rules.py`'s
fixtures: a limit only means something when calls actually go out, and its
`/slow` path is what lets two executions overlap.
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402

from test_api import ADMIN_DSN, hdr  # noqa: E402
from test_webhook_rules import (  # noqa: E402,F401
    client, connection, define, fx, hook_rule, make_action, make_webhook, modify_rule, pbase,
    priority_of, run, runs_for, target, ticket_type, tickets, _fresh_identity_cache,
)
from src.services import webhooks as webhooks_service  # noqa: E402


def test_call(client, fx, hook: dict) -> dict:
    r = client.post(f"{pbase(fx)}/webhooks/{hook['id']}/test", headers=hdr(fx.editor_sub),
                    json={"values": {"priority": "p"}})
    assert r.status_code == 200, r.text
    return r.json()


test_call.__test__ = False  # a helper, not a test


def edit(client, fx, hook: dict, **over):
    body = {k: hook[k] for k in ("connection_id", "display_name", "description", "method", "path",
                                 "query", "headers", "body", "inputs", "outputs", "store_responses",
                                 "retry_statuses", "timeout_seconds", "max_concurrent",
                                 "rate_limit", "rate_window")}
    body.update(over)
    return client.put(f"{pbase(fx)}/webhooks/{hook['id']}", headers=hdr(fx.editor_sub), json=body)


# ---- what a definition may say ---------------------------------------------------
def test_limits_are_off_unless_set_and_round_trip(client, fx, connection) -> None:
    hook = make_webhook(client, fx, connection)
    assert (hook["max_concurrent"], hook["rate_limit"], hook["rate_window"]) == (None, None, None)
    r = edit(client, fx, hook, max_concurrent=2, rate_limit=10, rate_window="minute")
    assert r.status_code == 200, r.text
    got = client.get(f"{pbase(fx)}/webhooks/{hook['id']}", headers=hdr(fx.viewer_sub)).json()
    assert (got["max_concurrent"], got["rate_limit"], got["rate_window"]) == (2, 10, "minute")
    made = make_webhook(client, fx, connection, max_concurrent=1, rate_limit=5, rate_window="day")
    assert (made["max_concurrent"], made["rate_limit"], made["rate_window"]) == (1, 5, "day")
    # Clearing them is no limit again.
    r = edit(client, fx, hook, max_concurrent=None, rate_limit=None, rate_window=None)
    assert (r.json()["max_concurrent"], r.json()["rate_limit"], r.json()["rate_window"]) == (
        None, None, None)


@pytest.mark.parametrize("over, said", [
    ({"max_concurrent": 0}, "the concurrency limit must be between 1 and 100"),
    ({"max_concurrent": 101}, "the concurrency limit must be between 1 and 100"),
    ({"max_concurrent": "2"}, "the concurrency limit must be a whole number"),
    ({"max_concurrent": True}, "the concurrency limit must be a whole number"),
    ({"max_concurrent": 1.5}, "the concurrency limit must be a whole number"),
    ({"rate_limit": 0, "rate_window": "second"}, "the rate limit must be between 1 and 1000000"),
    ({"rate_limit": 1_000_001, "rate_window": "second"}, "the rate limit must be between 1 and 1000000"),
    ({"rate_limit": 5}, "the rate window must be one of second, minute, hour, day"),
    ({"rate_limit": 5, "rate_window": "week"}, "the rate window must be one of second, minute, hour, day"),
    ({"rate_window": "day"}, "a rate window needs a rate limit"),
])
def test_a_limit_that_is_not_one_is_refused(over, said) -> None:
    with pytest.raises(webhooks_service.WebhookError) as caught:
        webhooks_service.parse({"method": "POST", **over})
    assert str(caught.value) == said


def test_the_largest_limits_are_allowed() -> None:
    parsed = webhooks_service.parse({"method": "POST", "max_concurrent": 100,
                                     "rate_limit": 1_000_000, "rate_window": "second"})
    assert (parsed["max_concurrent"], parsed["rate_limit"], parsed["rate_window"]) == (
        100, 1_000_000, "second")
    for window in ("second", "minute", "hour", "day"):
        assert webhooks_service.parse({"method": "POST", "rate_limit": 1,
                                       "rate_window": window})["rate_window"] == window


# ---- what they do ----------------------------------------------------------------
def test_a_rate_limit_refuses_what_is_over_it_and_says_so(client, fx, connection) -> None:
    hook = make_webhook(client, fx, connection, rate_limit=2, rate_window="day")
    assert [test_call(client, fx, hook)["ok"] for _ in range(2)] == [True, True]
    refused = test_call(client, fx, hook)
    assert (refused["ok"], refused["status_code"], refused["system_changed"], refused["error"]) == (
        False, None, False, "this webhook runs at most 2 times per day")
    # A refusal did not run, so it does not use up the window: raising the
    # limit by one lets exactly one more through.
    test_call(client, fx, hook)
    assert edit(client, fx, hook, rate_limit=3).status_code == 200
    hook = client.get(f"{pbase(fx)}/webhooks/{hook['id']}", headers=hdr(fx.viewer_sub)).json()
    assert [test_call(client, fx, hook)["ok"] for _ in range(2)] == [True, False]
    one = make_webhook(client, fx, connection, rate_limit=1, rate_window="hour")
    test_call(client, fx, one)
    assert test_call(client, fx, one)["error"] == "this webhook runs at most 1 time per hour"


def test_a_concurrency_limit_refuses_what_would_overlap(client, fx, connection) -> None:
    hook = make_webhook(client, fx, connection, path="slow", max_concurrent=2)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _n: test_call(client, fx, hook), range(3)))
    assert sorted(r["ok"] for r in results) == [False, True, True]
    [refused] = [r for r in results if not r["ok"]]
    assert refused["error"] == (
        "this webhook runs at most 2 executions at a time, and that many are running")
    # Finished executions give their places back.
    assert test_call(client, fx, hook)["ok"] is True
    single = make_webhook(client, fx, connection, path="slow", max_concurrent=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _n: test_call(client, fx, single), range(2)))
    assert sorted(r["error"] or "" for r in results) == [
        "", "this webhook runs at most 1 execution at a time, and that many are running"]


def test_a_refusal_for_concurrency_does_not_use_up_the_rate(client, fx, connection) -> None:
    hook = make_webhook(client, fx, connection, path="slow", max_concurrent=1,
                        rate_limit=2, rate_window="day")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _n: test_call(client, fx, hook), range(2)))
    assert sorted(r["ok"] for r in results) == [False, True]
    assert test_call(client, fx, hook)["ok"] is True
    assert test_call(client, fx, hook)["error"] == "this webhook runs at most 2 times per day"


def test_a_writeback_over_its_limit_refuses_the_action(
    client, fx, connection, ticket_type, tickets
) -> None:
    """p.106's writeback: a refused execution is a failed one, so the action
    changes nothing and says why."""
    hook = make_webhook(client, fx, connection, rate_limit=1, rate_window="day")
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [hook_rule(hook, "writeback"), modify_rule()]
                  ).status_code == 200
    assert run(client, fx, action, tickets[0], "first").status_code == 200
    r = run(client, fx, action, tickets[0], "second")
    assert r.status_code == 422, r.text
    assert "this webhook runs at most 1 time per day" in r.json()["detail"]
    assert priority_of(client, fx, ticket_type, tickets[0]) == "first"
    latest = runs_for(client, fx, hook)[0]
    assert (latest["ok"], latest["error"]) == (False, "this webhook runs at most 1 time per day")


def test_a_side_effect_over_its_limit_leaves_the_action_done(
    client, fx, connection, ticket_type, tickets
) -> None:
    hook = make_webhook(client, fx, connection, rate_limit=1, rate_window="day")
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [modify_rule(), hook_rule(hook, "side_effect")]
                  ).status_code == 200
    assert run(client, fx, action, tickets[1], "one").status_code == 200
    r = run(client, fx, action, tickets[1], "two")
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert priority_of(client, fx, ticket_type, tickets[1]) == "two"
    assert runs_for(client, fx, hook)[0]["error"] == "this webhook runs at most 1 time per day"


def test_the_browser_offers_what_the_server_takes() -> None:
    source = open(os.path.join(os.path.dirname(__file__), "..", "..", "web", "src", "lib",
                               "webhook-form.ts")).read()
    windows = ", ".join(f'"{w}"' for w in webhooks_service.RATE_WINDOWS)
    assert f"export const RATE_WINDOWS = [{windows}] as const;" in source
    assert f"export const MAX_CONCURRENT = {webhooks_service.MAX_CONCURRENT};" in source
    assert f"export const MAX_RATE = {webhooks_service.MAX_RATE:_};" in source


# ---- db 0111's bookkeeping, where no request can reach -----------------------------
def test_a_slot_past_its_expiry_is_given_back(client, fx, connection) -> None:
    """An API task that died mid-call cannot hold a slot for ever."""
    hook = make_webhook(client, fx, connection, max_concurrent=1)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        db.execute("INSERT INTO webhook_slots (webhook_id, expires_at) VALUES (%s, now() + interval '1 hour')",
                   (hook["id"],))
        assert test_call(client, fx, hook)["error"] == (
            "this webhook runs at most 1 execution at a time, and that many are running")
        db.execute("UPDATE webhook_slots SET expires_at = now() - interval '1 second' WHERE webhook_id = %s",
                   (hook["id"],))
        assert test_call(client, fx, hook)["ok"] is True
        # A slot is taken for the call's timeout and thirty seconds more.
        [left] = db.execute(
            "SELECT count(*) FROM webhook_slots WHERE webhook_id = %s", (hook["id"],)).fetchone()
        assert left == 0


def test_a_new_window_starts_a_new_count(client, fx, connection) -> None:
    hook = make_webhook(client, fx, connection, rate_limit=1, rate_window="minute")
    assert test_call(client, fx, hook)["ok"] is True
    assert test_call(client, fx, hook)["ok"] is False
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        db.execute("UPDATE webhook_rates SET window_start = window_start - interval '1 minute' "
                   "WHERE webhook_id = %s", (hook["id"],))
        assert test_call(client, fx, hook)["ok"] is True
        [taken] = db.execute("SELECT taken FROM webhook_rates WHERE webhook_id = %s",
                             (hook["id"],)).fetchone()
        assert taken == 1
    assert test_call(client, fx, hook)["ok"] is False


def test_the_slot_lasts_the_timeout_and_thirty_seconds(client, fx, connection) -> None:
    hook = make_webhook(client, fx, connection, max_concurrent=1, timeout_seconds=7)
    with psycopg.connect(ADMIN_DSN) as db:
        [[slot, _]] = db.execute("SELECT * FROM admit_webhook_call(%s)", (hook["id"],)).fetchall()
        [[seconds]] = db.execute(
            "SELECT extract(epoch FROM expires_at - now()) FROM webhook_slots WHERE id = %s",
            (slot,)).fetchall()
        assert seconds == 37
        db.rollback()


def test_two_admissions_for_one_webhook_are_answered_one_after_the_other(
    client, fx, connection
) -> None:
    """The row lock is what makes "count, then take" safe: without it, two
    executions asking at once would both count the same slots and both run."""
    hook = make_webhook(client, fx, connection, max_concurrent=5)
    with psycopg.connect(ADMIN_DSN) as first, psycopg.connect(ADMIN_DSN) as second:
        first.execute("SELECT * FROM admit_webhook_call(%s)", (hook["id"],))
        second.execute("SET lock_timeout = '300ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            second.execute("SELECT * FROM admit_webhook_call(%s)", (hook["id"],))
        second.rollback()
        first.commit()
        [[slot, refused]] = second.execute("SELECT * FROM admit_webhook_call(%s)",
                                           (hook["id"],)).fetchall()
        assert slot is not None and refused is None
        second.rollback()
