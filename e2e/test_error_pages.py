"""The platform's own pages for an address that is no page and for a page
that failed (§908).

Without them, a production build shows the framework's bare 404 for the
first and a blank "Application error" screen for the second. The error
boundary's wording is `apps/web/src/lib/page-error.test.ts`'s. What needs a
browser is that the not-found page is the one actually served.
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import WEB_BASE


def test_an_address_that_is_no_page_says_so(page) -> None:
    page.goto(f"{WEB_BASE}/no/such/page/at/this/address/at/all")
    notice = page.get_by_test_id("not-found")
    expect(notice).to_be_visible(timeout=30000)
    expect(notice).to_contain_text("There is no page at this address.")
    notice.get_by_role("link", name="Go home").click()
    expect(page).to_have_url(f"{WEB_BASE}/home", timeout=30000)


def test_a_signed_in_page_can_tell_the_operators(page) -> None:
    """§926: what the error boundary sends goes through the web origin, on the
    browser's own session, and is taken. The boundary's call and its payload
    are `apps/web/src/lib/report-page-error.test.ts`'s; the API's line and its
    alarm, `apps/api/tests/test_client_errors.py`'s."""
    page.goto(f"{WEB_BASE}/home")
    page.get_by_role("heading", name="Choose a workspace").wait_for()
    status = page.evaluate("""async () => (await fetch("/api/client-errors", {
        method: "POST", credentials: "same-origin",
        headers: {"X-Anchor-Session": "1", "Content-Type": "application/json"},
        body: JSON.stringify({kind: "fault", message: "from the browser suite", path: "/home",
                              digest: null, stack: null}),
    })).status""")
    assert status == 204


def test_a_page_that_fails_tells_the_operators_itself(page) -> None:
    """§926, end to end: a page that throws while rendering reaches the error
    page, and the error page sends the report on its own. The failure is made
    the way a broken release makes one - an answer the page does not expect:
    the workspace list's request answers an object, which has a length and no
    `map`."""
    page.route("**/api/workspaces", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"length": 1}'))
    with page.expect_request(
        lambda r: r.url.endswith("/api/client-errors") and r.method == "POST", timeout=30000
    ) as sent:
        page.goto(f"{WEB_BASE}/home")
    expect(page.get_by_test_id("page-error")).to_be_visible(timeout=30000)
    report = sent.value.post_data_json
    assert report["kind"] == "fault" and report["path"] == "/home", report
    assert "map" in report["message"], report
    response = sent.value.response()
    assert response is not None and response.status == 204
