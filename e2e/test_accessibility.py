"""The platform's pages, checked by axe-core (§1008).

What a screen reader or a keyboard needs from a page is mostly not visible to
a test that clicks and reads text: a colour a little too pale for its
background, a column header with nothing in it, a heading a level too deep, a
page with no `main` for "skip to content" to go to. Each of those was on the
pages below until §1008, and nothing here would have noticed.

axe-core is the rules engine browsers' own audits use. It runs in the page,
against the page as drawn - the theme, the fonts, a header shown only when the
signed-in user may edit - with WCAG 2.1 A and AA and axe's best practices.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE

ROOT = Path(__file__).resolve().parents[1]
# npm hoists a workspace's dev dependency to the root; apps/web's own
# node_modules is where it lands when it is installed on its own.
AXE = next(
    (p for p in (ROOT / "node_modules/axe-core/axe.min.js",
                 ROOT / "apps/web/node_modules/axe-core/axe.min.js") if p.exists()),
    None,
)

TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]


def violations(page) -> list[str]:
    if AXE is None:
        pytest.fail("axe-core is not installed: `npm ci` at the repository root")
    page.add_script_tag(path=str(AXE))
    found = page.evaluate(
        """tags => axe.run(document, {runOnly: {type: "tag", values: tags}})
             .then(r => r.violations.map(v => ({id: v.id, nodes: v.nodes.map(n => n.target.join(" "))})))""",
        TAGS,
    )
    return [f"{v['id']}: {', '.join(v['nodes'][:5])}" for v in found]


@pytest.fixture(scope="module")
def place(api) -> dict:
    """A project with a dataset, an object type and a module in it, so the
    tables have rows and their Actions columns are drawn."""
    mod = Module(api, "Accessible")
    name = f"accessible_{uuid.uuid4().hex[:6]}"
    api.upload_csv(f"{mod.base}/datasets/upload", name=name, csv=b"id,region\n1,north\n2,south\n")
    mod.object_type(columns=["id", "region"], rows=[{"id": "1", "region": "north"}], key="id")
    resources = api.call("GET", f"{mod.base}/resources")["resources"]
    dataset = next(r for r in resources if r["name"] == name)
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown",
                   "props": {"source": "text", "text": "# Hello", "textVariable": "",
                             "monospace": False, "scrolling": False, "wordWrap": True,
                             "breaks": True, "alignment": "left"}},
        }),
        "variables": {},
    })
    return {"mod": mod, "dataset": dataset["id"], "name": name}


# Every page a signed-in editor reaches from the platform's navigation.
PAGES = [
    "/home", "/org", "/org/audit",
    "/{ws}", "/{ws}/explore", "/{ws}/apps", "/{ws}/tags", "/{ws}/cleanup", "/{ws}/advanced",
    "/{ws}/{pj}", "/{ws}/{pj}/datasets", "/{ws}/{pj}/objects", "/{ws}/{pj}/objects/{type}",
    "/{ws}/{pj}/pipeline", "/{ws}/{pj}/code", "/{ws}/{pj}/connections", "/{ws}/{pj}/models",
    "/{ws}/{pj}/canvas", "/{ws}/{pj}/series-analyses",
    "/{dataset}", "/{module}",
    "/no-page-is-here",
]


@pytest.mark.parametrize("path", PAGES)
def test_a_platform_page(page, place, path) -> None:
    mod = place["mod"]
    page.goto(WEB_BASE + path.format(
        ws=mod.workspace_slug, pj=mod.project_slug, type=mod.object_type_id,
        dataset=f"r/{place['dataset']}", module=mod.url.lstrip("/")))
    # Every one of them has a heading to say what it is - one of the rules.
    # Waiting for the network as well as for it, so a table that arrives
    # after the heading is drawn before the page is read.
    expect(page.locator("h1").first).to_be_visible(timeout=30000)
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Loading…")).to_have_count(0, timeout=30000)
    assert violations(page) == []


def test_the_rows_whose_headers_were_empty_are_drawn(page, place) -> None:
    """What the datasets page is checked with: a column of buttons, and the
    header above it that §1008 gave words to. Without the rows the check
    above would pass on a page that had no such header to get wrong."""
    mod = place["mod"]
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/datasets")
    expect(page.get_by_role("cell", name=place["name"]).first).to_be_visible(timeout=30000)
    expect(page.get_by_role("columnheader", name="Actions").first).to_be_attached()


def test_an_application_is_the_page_s_main(page, place) -> None:
    page.goto(f"{WEB_BASE}{place['mod'].url}")
    expect(page.get_by_role("heading", name="Hello")).to_be_visible(timeout=30000)
    expect(page.get_by_role("main")).to_have_count(1)


def test_the_check_finds_what_it_is_for(page) -> None:
    """Without this, an axe that loaded and checked nothing would pass every
    page above. A page of its own rather than one of the platform's with the
    faults added to it: added before the page hydrates, React redraws over
    them and the check finds nothing for a reason that is not axe's."""
    page.set_content("""<!doctype html><html lang="en"><head><title>t</title></head><body><main>
      <h1>Faults</h1>
      <table><thead><tr><th>Name</th><th aria-label="Actions"></th></tr></thead>
        <tbody><tr><td>x</td><td><button>Go</button></td></tr></tbody></table>
      <span style="color:#8a6d3b;background:#f3ede1;font-size:11.5px">admin</span>
    </main></body></html>""")
    found = {v.split(":")[0] for v in violations(page)}
    assert {"empty-table-header", "color-contrast"} <= found, found
