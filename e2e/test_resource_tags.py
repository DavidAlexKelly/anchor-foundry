"""Tags on resources (§511; db 0105; `dataset-preview` p.3, `app-building`
p.35).

    "You can create and manage tags from the Tags section of Platform
     Settings. Once they are created, they can be added … in the filesystem."
     (p.35)

The rules are `apps/api/tests/test_resource_tags.py`'s and the wording is
`apps/web/src/lib/resource-tags.test.ts`'s. What needs a browser is the round
trip across two screens, the workspace's Tags page and a dataset's Details,
and what a reader is not offered on either.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def dataset_resource(mod: Module) -> str:
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload", f"tagged_{mod.tag}", b"id\n1\n")
    resources = mod.api.call("GET", f"{mod.base}/resources")["resources"]
    return next(r for r in resources if r["name"] == made["name"] and r["kind"] == "dataset")["id"]


def tag_row(page, name: str):
    return page.get_by_test_id("tag-row").filter(has_text=name)


def test_an_admin_makes_a_tag_and_an_editor_applies_it(page, api) -> None:
    mod = Module(api, "Tags")
    rid = dataset_resource(mod)
    name = f"Gold {mod.tag}"

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/tags")
    page.get_by_test_id("tag-category").fill("Quality")
    page.get_by_test_id("tag-name").fill(name)
    page.get_by_test_id("tag-create").click()
    expect(tag_row(page, name)).to_contain_text("not used yet", timeout=30000)
    expect(page.get_by_test_id("tag-group").filter(has=tag_row(page, name))
           .locator("h2")).to_have_text("Quality")

    page.goto(f"{WEB_BASE}/r/{rid}?tab=details")
    expect(page.get_by_test_id("ds-no-tags")).to_be_visible(timeout=30000)
    page.get_by_test_id("ds-tag-add").select_option(label=f"Quality: {name}")
    expect(page.get_by_test_id("ds-tag")).to_have_text(f"Quality: {name}×")
    expect(page.get_by_test_id("ds-no-tags")).to_have_count(0)
    # A tag already on the resource is not offered again.
    expect(page.get_by_test_id("ds-tag-add").locator("option", has_text=name)).to_have_count(0)

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/tags")
    expect(tag_row(page, name)).to_contain_text("on 1 resource", timeout=30000)

    page.goto(f"{WEB_BASE}/r/{rid}?tab=details")
    page.get_by_role("button", name=f"Remove Quality: {name}").click()
    expect(page.get_by_test_id("ds-no-tags")).to_be_visible()

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/tags")
    tag_row(page, name).get_by_test_id("tag-delete").click()
    expect(tag_row(page, name)).to_have_count(0)


def test_a_reader_sees_tags_and_is_offered_nothing_to_change(page, viewer_page, api) -> None:
    mod = Module(api, "Tags reader")
    rid = dataset_resource(mod)
    name = f"Silver {mod.tag}"
    tag = mod.api.call("POST", f"/workspaces/{mod.workspace_id}/tags", {"name": name})
    mod.api.call("PUT", f"/workspaces/{mod.workspace_id}/resource-tags/{rid}/{tag['id']}")

    viewer_page.goto(f"{WEB_BASE}/{mod.workspace_slug}/tags")
    expect(tag_row(viewer_page, name)).to_contain_text("on 1 resource", timeout=30000)
    expect(viewer_page.get_by_test_id("tags-read-only")).to_be_visible()
    expect(viewer_page.get_by_test_id("tag-form")).to_have_count(0)
    expect(tag_row(viewer_page, name).get_by_test_id("tag-delete")).to_have_count(0)

    viewer_page.goto(f"{WEB_BASE}/r/{rid}?tab=details")
    expect(viewer_page.get_by_test_id("ds-tag")).to_have_text(name, timeout=30000)
    expect(viewer_page.get_by_test_id("ds-tag-remove")).to_have_count(0)
    expect(viewer_page.get_by_test_id("ds-tag-add")).to_have_count(0)
