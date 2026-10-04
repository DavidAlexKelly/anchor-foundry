"""A refused sign-in says why, in Cognito's words (§816).

The first real deployment's owner was refused at sign-in and nobody could say
why, because the page Cognito sent the browser back to dropped the reason:
a refusal arrives at `/callback` as `?error=...&error_description=...`, and
the page answered "Missing authorization code". Driven without a signed-in
session, as a person arriving from the hosted UI would be.
"""
from __future__ import annotations

from urllib.parse import urlencode

from conftest import WEB_BASE


def test_a_refused_sign_in_shows_cognitos_reason(stack, browser) -> None:
    context = browser.new_context()
    page = context.new_page()
    try:
        query = urlencode({"error": "access_denied",
                           "error_description": "User is disabled."})
        page.goto(f"{WEB_BASE}/callback?{query}")
        message = page.get_by_test_id("sign-in-error")
        message.wait_for()
        assert "User is disabled. (access_denied)" in message.inner_text()
        assert "Missing authorization code" not in message.inner_text()
        # And the way back is offered.
        assert page.get_by_role("link", name="back to sign in").get_attribute("href") == "/login"
    finally:
        context.close()


def test_a_callback_with_neither_says_the_code_is_missing(stack, browser) -> None:
    context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(f"{WEB_BASE}/callback")
        message = page.get_by_test_id("sign-in-error")
        message.wait_for()
        assert "Missing authorization code" in message.inner_text()
    finally:
        context.close()
