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
