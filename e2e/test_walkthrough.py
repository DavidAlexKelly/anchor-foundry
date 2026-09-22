"""p.11's in-app walkthrough (§431; `code-repositories` p.11).

    "In the Code tab, you can click the [?] button to start a step-by-step
     walkthrough that guides you through the core functionalities available in
     your Code Repository. The in-app help is currently only available in the
     Code view."

The rules are in `apps/web/src/lib/walkthrough.test.ts`. What needs a browser
is the half no pure function can hold:

  * that the highlighted element is the one the step names — a tour whose
    outline lands on the wrong control is worse than no tour;
  * that a step on another tab takes you there *before* it describes it;
  * that a step about something this project does not have is dropped, and
    that the counter counts what is left rather than the list as written;
  * and that the page underneath stays usable, because a walkthrough that
    covers the controls it is describing is a contradiction.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def declaring(name: str) -> str:
    return f"-- output: {name}\nSELECT 1 AS id\n"


def commit(mod: Module, repo: dict, files: dict[str, str]) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": "a change"},
    )


def a_repository(api, name: str) -> dict:
    mod = project(api, name)
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": declaring(f"d_{uuid.uuid4().hex[:6]}")})
    return repo


def open_repo(page, repo: dict, *, tab: str = "files") -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab={tab}")
    expect(page.get_by_test_id("open-walkthrough")).to_be_visible(timeout=30000)


def start(page) -> None:
    page.get_by_test_id("open-walkthrough").click()
    expect(page.get_by_test_id("walkthrough-card")).to_be_visible(timeout=10000)


def step_id(page) -> str | None:
    return page.get_by_test_id("walkthrough-card").get_attribute("data-step")


def highlighted(page) -> list[str]:
    return page.locator("[data-tour-on]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-tour'))"
    )


def test_the_button_starts_a_walk(page, api) -> None:
    """**The unit, in one click.** p.11's button, and the first card."""
    repo = a_repository(api, "Walk start")
    open_repo(page, repo)

    expect(page.get_by_test_id("walkthrough-card")).to_have_count(0)
    start(page)
    expect(page.get_by_test_id("walkthrough-count")).to_contain_text("Step 1 of")
    assert step_id(page) == "ref"


def test_the_outline_is_on_the_control_the_step_names(page, api) -> None:
    """A tour whose highlight lands on the wrong thing is worse than none:
    it is confidently wrong about the one screen somebody asked for help on."""
    repo = a_repository(api, "Walk outline")
    open_repo(page, repo)

    start(page)
    assert highlighted(page) == ["ref"]
    page.get_by_test_id("walkthrough-next").click()
    eventually(lambda: highlighted(page), lambda h: h == ["commands"],
               what="the outline to move to the next step's control")
    # Exactly one at a time - two outlines is the tour pointing twice.
    assert len(highlighted(page)) == 1


def test_a_step_on_another_tab_takes_you_there(page, api) -> None:
    """The walk is over the whole application, so it moves between tabs — and
    it has to arrive *before* it describes what is there, or the card would be
    a sentence about a control nobody can see."""
    repo = a_repository(api, "Walk tabs")
    open_repo(page, repo)

    start(page)
    for _ in range(5):
        page.get_by_test_id("walkthrough-next").click()
    eventually(lambda: step_id(page), lambda s: s == "publish",
               what="the walk to reach the publish step")
    # **`wait_for_url`, not `eventually(lambda: page.url, ...)`.** `page.url`
    # is a cached property that Playwright refreshes while it is pumping its
    # own connection, so a poll loop that only sleeps between reads never sees
    # it change — it reported the old tab for the full twenty seconds while the
    # page had moved. `eventually` is right for values read through a locator;
    # a URL has its own wait.
    page.wait_for_url(lambda url: "tab=publish" in url, timeout=30000)
    # And the outline arrives with the panel, not with the tab: the Publish
    # tab renders "Reading main…" while its plan is a request away, so the
    # thing this step describes appears a moment after the tab does.
    eventually(lambda: highlighted(page), lambda h: h == ["publish"],
               what="the outline to reach the panel the step is about")


def test_back_returns_and_stops_at_the_start(page, api) -> None:
    repo = a_repository(api, "Walk back")
    open_repo(page, repo)

    start(page)
    page.get_by_test_id("walkthrough-next").click()
    eventually(lambda: step_id(page), lambda s: s == "commands",
               what="the walk to move on")
    page.get_by_test_id("walkthrough-back").click()
    eventually(lambda: step_id(page), lambda s: s == "ref",
               what="Back to return to the first step")
    # And there is nowhere further back to go, which the button says rather
    # than silently doing nothing.
    expect(page.get_by_test_id("walkthrough-back")).to_be_disabled()


def test_the_last_step_ends_the_walk(page, api) -> None:
    """**"Done" closes rather than stopping on the last card.** A tour that
    left its card up after the last step would make somebody dismiss it twice,
    and wrapping round to the start would restart what they just finished."""
    repo = a_repository(api, "Walk end")
    open_repo(page, repo)

    start(page)
    total = total_steps(page)
    for _ in range(total - 1):
        page.get_by_test_id("walkthrough-next").click()
    expect(page.get_by_test_id("walkthrough-next")).to_have_text("Done")
    page.get_by_test_id("walkthrough-next").click()
    expect(page.get_by_test_id("walkthrough-card")).to_have_count(0)
    expect(page.get_by_test_id("open-walkthrough")).to_be_visible()


def test_the_walk_does_not_point_at_something_that_has_gone(page, api) -> None:
    """**The reader can leave while the card is up, because nothing stops
    them.**

    The walk dims the page rather than covering it, so clicking a tab mid-step
    is an ordinary thing to do — and the element the current step describes
    goes with it. The card stays readable in the middle of the window with
    nothing outlined, rather than hanging beside a rectangle that is no longer
    there and sounding certain about it.
    """
    repo = a_repository(api, "Walk left behind")
    open_repo(page, repo)

    start(page)
    page.get_by_test_id("walkthrough-next").click()
    page.get_by_test_id("walkthrough-next").click()
    page.get_by_test_id("walkthrough-next").click()
    eventually(lambda: step_id(page), lambda s: s == "tree",
               what="the walk to reach the file tree")
    eventually(lambda: highlighted(page), lambda h: h == ["tree"],
               what="the tree to be outlined")

    page.get_by_role("button", name="History", exact=True).click()
    eventually(lambda: highlighted(page), lambda h: h == [],
               what="the outline to go with the panel it was on")
    expect(page.get_by_test_id("walkthrough-card")).to_be_visible()
    expect(page.get_by_test_id("walkthrough-card")).to_contain_text("Your files")

    # **And it moves to the middle**, which is the visible difference between
    # a card that knows it has nothing to point at and one that is still
    # sitting beside where the thing used to be. Asserted as geometry because
    # that is the only place the difference exists: the outline goes away on
    # its own when the element is unmounted, so a test that only checked for
    # an outline would pass against a card that never noticed.
    eventually(
        lambda: page.evaluate(
            "() => {"
            "  const c = document.querySelector('[data-testid=walkthrough-card]');"
            "  const b = c.getBoundingClientRect();"
            "  return Math.round(Math.abs((b.left + b.width / 2) - window.innerWidth / 2));"
            "}"
        ),
        lambda off: off <= 2,
        what="the card to move to the middle once it has nothing to point at",
    )


def test_escape_ends_the_walk(page, api) -> None:
    repo = a_repository(api, "Walk escape")
    open_repo(page, repo)

    start(page)
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("walkthrough-card")).to_have_count(0)
    # And nothing is left outlined behind it.
    assert highlighted(page) == []


def test_the_controls_underneath_stay_usable(page, api) -> None:
    """**Dimmed, not covered.** A walkthrough describing a control while a
    layer over it swallows the click is a contradiction somebody discovers by
    trying exactly what they were just told to do."""
    repo = a_repository(api, "Walk clickable")
    open_repo(page, repo)

    start(page)
    expect(page.get_by_test_id("walkthrough-dim")).to_be_visible()
    # The command palette is the second step's own subject, so this is the
    # control the walk is pointing at.
    page.get_by_test_id("open-command-palette").click()
    expect(page.get_by_test_id("command-palette")).to_be_visible()


def total_steps(page) -> int:
    """**`text_content`, not `inner_text`.** The counter is uppercased in CSS,
    so the rendered text reads "STEP 1 OF 7" and a split on " of " finds
    nothing — a test failing on a stylesheet rather than on the product."""
    label = page.get_by_test_id("walkthrough-count").text_content() or ""
    return int(label.split(" of ")[1])


def test_a_step_about_something_this_project_lacks_is_dropped(page, api) -> None:
    """**And the counter counts what is left.**

    The gate step describes a control that only exists in a project requiring
    review. An ungated project must not be walked past an empty rectangle and
    told what would be there — and the counter must not promise the step it
    dropped.
    """
    mod = project(api, "Walk gated")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": declaring(f"d_{uuid.uuid4().hex[:6]}")})

    open_repo(page, repo)
    start(page)
    ungated = total_steps(page)
    page.get_by_test_id("walkthrough-close").click()

    mod.api.call("PUT", f"{mod.base}/code/review-policy", {"require_code_review": True})
    page.reload()
    expect(page.get_by_test_id("open-walkthrough")).to_be_visible(timeout=30000)
    start(page)
    eventually(lambda: total_steps(page), lambda n: n == ungated + 1,
               what="the gated project to gain the step about its gate")

    mod.api.call("PUT", f"{mod.base}/code/review-policy", {"require_code_review": False})


def test_every_step_the_counter_promises_has_a_control(page, api) -> None:
    """The total is a promise the walk keeps, step by step: each one outlines
    exactly one element, and no step is visited twice."""
    repo = a_repository(api, "Walk counter")
    open_repo(page, repo)

    start(page)
    total = total_steps(page)
    seen = []
    for _ in range(total):
        eventually(lambda: highlighted(page), lambda h: len(h) == 1,
                   what="each step to have exactly one control")
        seen.append(step_id(page))
        page.get_by_test_id("walkthrough-next").click()
    assert len(seen) == total
    assert len(set(seen)) == total
