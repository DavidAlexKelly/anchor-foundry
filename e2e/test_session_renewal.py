"""An expired access token is renewed where the person is, not by sign-in (§859).

A deployed session's access token lasts fifteen minutes. Every request after
that was a 401, and every 401 sent the page through sign-in, taking whatever
was open with it. The client now asks `POST /api/auth/refresh` first, once for
all the requests waiting, and asks again with the new session.

The development stack has no hosted UI to renew from, so both answers are
given here: the API's refusals of an expired token, and the renewal's.
"""
from __future__ import annotations

from conftest import WEB_BASE

EXPIRED = {"status": 401, "json": {"detail": "token expired"}}


def _expected_refusals(page) -> None:
    """The 401s routed here are the point of the test; the console reports
    each as a failed resource, which the fixture would otherwise fail on."""
    page.console_errors[:] = [e for e in page.console_errors if "401" not in e]


def test_a_refused_request_is_renewed_and_asked_again(page) -> None:
    renewals: list[str] = []
    refused: list[str] = []

    def workspaces(route) -> None:
        # Refused once, as an expired session would be, then answered.
        if not refused:
            refused.append(route.request.url)
            route.fulfill(**EXPIRED)
        else:
            route.continue_()

    page.route("**/api/workspaces", workspaces)
    page.route("**/api/auth/refresh", lambda route: (
        renewals.append(route.request.headers.get("x-anchor-session", "")),
        route.fulfill(json={})))
    page.goto(f"{WEB_BASE}/home")
    page.get_by_role("heading", name="Choose a workspace").wait_for()
    assert "/login" not in page.url
    assert len(refused) == 1
    assert renewals == ["1"], "renewed once, with the CSRF header"
    _expected_refusals(page)


def test_a_session_that_cannot_be_renewed_goes_to_sign_in(page) -> None:
    page.route("**/api/workspaces", lambda route: route.fulfill(**EXPIRED))
    page.route("**/api/auth/refresh", lambda route: route.fulfill(
        status=401, json={"detail": "the session could not be renewed"}))
    # Only to the commit: the redirect to sign-in aborts the load being waited on.
    page.goto(f"{WEB_BASE}/home", wait_until="commit")
    page.wait_for_url("**/login**")
    _expected_refusals(page)
