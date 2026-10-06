"""The sign-in page learns where to send a person from the API (§851).

One web image serves every customer's stack, so the hosted UI's address and
the app client were never in a deployed build: `NEXT_PUBLIC_COGNITO_*` are
written in when it is built, and the documented builds pass neither. The page
asks `GET /api/auth/config` instead. Driven without a session, as a person
arriving to sign in would be.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from playwright.sync_api import expect

from conftest import API_BASE, WEB_BASE

HOSTED_UI = "https://platform-check.auth.eu-west-2.amazoncognito.invalid"


def test_the_api_answers_someone_not_signed_in(stack) -> None:
    with urlopen(f"{API_BASE}/auth/config", timeout=10) as r:
        assert r.status == 200
        assert set(json.load(r)) == {"domain", "client_id"}


def test_sign_in_goes_where_the_api_says(stack, browser) -> None:
    context = browser.new_context()
    page = context.new_page()
    went: list[str] = []
    try:
        # What a stack's API answers. The hosted UI itself is not reached: the
        # request for it is recorded and answered here.
        page.route("**/api/auth/config", lambda route: route.fulfill(
            json={"domain": HOSTED_UI, "client_id": "client-from-the-stack"}))
        page.route(f"{HOSTED_UI}/**", lambda route: (
            went.append(route.request.url), route.fulfill(body="hosted ui")))
        page.goto(f"{WEB_BASE}/login")
        button = page.get_by_role("button", name="Continue to sign in")
        expect(button).to_be_enabled()
        button.click()
        page.wait_for_url(f"{HOSTED_UI}/**")
        [url] = went
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        assert parsed.path == "/oauth2/authorize"
        assert query["client_id"] == ["client-from-the-stack"]
        # Back to the page's own origin, which is the address the stack lets
        # the hosted UI return to (§849).
        assert query["redirect_uri"] == [f"{WEB_BASE}/callback"]
        assert query["code_challenge_method"] == ["S256"]
    finally:
        context.close()
