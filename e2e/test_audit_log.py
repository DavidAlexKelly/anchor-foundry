"""The organisation's audit log page (§988).

What the log filters and pages is the API's tests' (`apps/api/tests/
test_audit_log_search.py`) and the wording `apps/web/src/lib/audit-log.test.ts`'.
What needs a browser is that an administrator finds it from the organisation
page and can narrow it to what they are looking for, and that anybody else is
neither offered it nor shown it.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from conftest import WEB_BASE


def test_an_administrator_finds_what_was_done_and_narrows_to_it(page, api) -> None:
    workspace = api.call("GET", "/workspaces")[0]
    tag = uuid.uuid4().hex[:6]
    api.call("POST", f"/workspaces/{workspace['id']}/projects",
             {"name": f"Audited {tag}", "slug": f"audited-{tag}"})

    page.goto(f"{WEB_BASE}/org")
    page.get_by_test_id("org-audit-link").click()
    expect(page.get_by_test_id("audit-entries")).to_be_visible(timeout=30000)

    page.get_by_test_id("audit-action").fill("project.create")
    page.get_by_test_id("audit-search").click()
    rows = page.get_by_test_id("audit-entry")
    expect(rows.first).to_contain_text("project.create", timeout=15000)
    for text in rows.all_inner_texts():
        assert "project.create" in text
    # The newest is the one just made, and opening it says which.
    rows.first.click()
    expect(page.get_by_test_id("audit-metadata").first).to_contain_text(f"audited-{tag}")
    # And closing it, from a keyboard (§1009): a row takes no focus, so the
    # action in it is the button a keyboard opens it with.
    toggle = rows.first.get_by_role("button", name="project.create")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("audit-metadata")).to_have_count(0)
    page.keyboard.press(" ")
    expect(page.get_by_test_id("audit-metadata").first).to_contain_text(f"audited-{tag}")

    # A filter that cannot be asked is said before anything is.
    page.get_by_test_id("audit-resource").fill("not-an-id")
    expect(page.get_by_test_id("audit-problem")).to_contain_text("by its id")
    expect(page.get_by_test_id("audit-search")).to_be_disabled()


def test_anybody_else_is_neither_offered_nor_shown_it(viewer_page) -> None:
    viewer_page.goto(f"{WEB_BASE}/org")
    expect(viewer_page.locator("h1")).to_be_visible(timeout=30000)
    expect(viewer_page.get_by_test_id("org-audit-link")).to_have_count(0)
    viewer_page.goto(f"{WEB_BASE}/org/audit")
    expect(viewer_page.get_by_test_id("audit-error")).to_have_text(
        "Only an organisation's administrators can read its audit log.", timeout=30000)


def test_what_was_searched_for_downloads_as_a_file(page, api) -> None:
    """§989: the export is the filters last searched for."""
    workspace = api.call("GET", "/workspaces")[0]
    tag = uuid.uuid4().hex[:6]
    api.call("POST", f"/workspaces/{workspace['id']}/projects",
             {"name": f"Exported {tag}", "slug": f"exported-{tag}"})
    page.goto(f"{WEB_BASE}/org/audit")
    page.get_by_test_id("audit-action").fill("project.create")
    page.get_by_test_id("audit-search").click()
    expect(page.get_by_test_id("audit-entry").first).to_contain_text("project.create",
                                                                     timeout=15000)
    with page.expect_download() as downloading:
        page.get_by_test_id("audit-export").click()
    download = downloading.value
    assert download.suggested_filename == "audit-log.csv"
    with open(download.path(), encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    assert lines[0].startswith("id,created_at,action,actor_email")
    assert all(",project.create," in line for line in lines[1:])
    assert any(f"exported-{tag}" in line for line in lines[1:])
