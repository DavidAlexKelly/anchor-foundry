"""The Iframe widget (`workshop` p.545–547; §455).

> "The Iframe widget enables embedding of external, full-page applications
> within Workshop, providing builders with a way to add custom views to their
> modules." (p.545)

> "When embedding another Foundry application, you can hide the Foundry
> sidebar by adding the `embedded=true` URL query parameter." (p.547)

**Every frame here shows one of this platform's own pages.** That is p.547's
own case, and it is the only one a browser suite can assert on honestly: a
same-origin frame's *contents* are readable, so "the page rendered inside it"
is a claim about the page rather than about an element existing. It also keeps
the suite off the network.

The URL rules are `frame.ts`'s and are tested there; what needs a browser is
that the widget follows them — a refused URL says why instead of drawing a
frame — and that the shell honours `embedded=true`, which nothing else can see.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled


def iframe_module(api, name: str, *, props: dict, variables: dict | None = None,
                  beside=None):
    mod = Module(api, name, beside=beside)
    mod.define({
        "format": 2,
        "layout": layout({
            "frame": {"resolvedName": "CanvasIframe", "props": props},
        }),
        "variables": variables or {},
        "events": {},
    })
    return mod


@pytest.fixture(scope="module")
def home(api):
    """A module to hang the others beside, and the workspace whose pages they
    frame."""
    return Module(api, "Iframe host")


def test_a_platform_page_renders_inside_the_frame(page, api, home) -> None:
    """p.545's whole claim, asserted on the *contents*: the framed page's own
    heading is there, which an empty or blocked frame cannot fake."""
    mod = iframe_module(api, "Iframe renders", beside=home,
                        props={"url": "/home?embedded=true", "title": "Workspaces"})
    open_module(page, mod)
    settled(page)

    frame = page.frame_locator('[data-testid="iframe"]')
    expect(frame.get_by_role("heading", name="Choose a workspace")).to_be_visible(timeout=30000)


def test_embedded_true_hides_the_platforms_own_top_bar(page, api, home) -> None:
    """p.547, and the half this platform had to build: its chrome is a top bar,
    and a framed page without the parameter draws a second one inside the
    module's.

    **Both frames, asserted as a pair**: the bar present without the parameter
    and absent with it. The absence alone passes for a frame that never
    rendered (§318), and the presence is the positive it is measured against.
    """
    plain = iframe_module(api, "Iframe with chrome", beside=home,
                          props={"url": "/home", "title": "With chrome"})
    open_module(page, plain)
    settled(page)
    framed = page.frame_locator('[data-testid="iframe"]')
    expect(framed.get_by_role("heading", name="Choose a workspace")).to_be_visible(timeout=30000)
    expect(framed.locator("header.topbar")).to_have_count(1)

    bare = iframe_module(api, "Iframe without chrome", beside=home,
                         props={"url": "/home?embedded=true", "title": "Without"})
    open_module(page, bare)
    settled(page)
    framed = page.frame_locator('[data-testid="iframe"]')
    expect(framed.get_by_role("heading", name="Choose a workspace")).to_be_visible(timeout=30000)
    expect(framed.locator("header.topbar")).to_have_count(0)


def test_a_refused_url_says_why_instead_of_drawing_a_frame(page, api, home) -> None:
    """§214: a frame showing nothing looks exactly like a page that failed to
    load, and the two have different fixes. A `javascript:` URL is the case
    that matters most — an author who can set one could run code in every
    viewer's session — so there must be no iframe at all, not an empty one."""
    mod = iframe_module(api, "Iframe refused", beside=home,
                        props={"url": "javascript:alert(1)"})
    open_module(page, mod)
    settled(page)

    note = page.get_by_test_id("iframe-refused")
    expect(note).to_be_visible()
    expect(note).to_contain_text("http")
    expect(page.get_by_test_id("iframe")).to_have_count(0)


def test_the_url_can_come_from_a_string_variable(page, api, home) -> None:
    """p.546: "Input the URL for an application as a static string or a string
    variable."

    **The variable wins over a static URL that is also set**, and the static one
    here is a refused URL: if the widget read the literal, the frame would not
    exist at all, so a rendered page is proof the variable was read."""
    mod = iframe_module(
        api, "Iframe from variable", beside=home,
        props={"url": "javascript:alert(1)", "textVariable": "v_url",
               "title": "From a variable"},
        variables={"v_url": {"id": "v_url", "kind": "string", "label": "URL",
                             "default": "/home?embedded=true"}},
    )
    open_module(page, mod)
    settled(page)

    frame = page.frame_locator('[data-testid="iframe"]')
    expect(frame.get_by_role("heading", name="Choose a workspace")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("iframe-refused")).to_have_count(0)


def test_the_frame_is_named_for_a_screen_reader(page, api, home) -> None:
    """An `<iframe>` with no title is announced as "frame" and nothing else."""
    mod = iframe_module(api, "Iframe title", beside=home,
                        props={"url": "/home?embedded=true", "title": "Weather board"})
    open_module(page, mod)
    settled(page)
    expect(page.get_by_test_id("iframe")).to_have_attribute("title", "Weather board")


def test_the_frame_is_inert_in_the_builder(page, api, home) -> None:
    """An iframe captures every click on it, so a builder could not select the
    widget they had just dropped. In the builder the frame takes no pointer
    events; in the running module it does, which is the half that makes the
    first a choice rather than a broken frame."""
    mod = iframe_module(api, "Iframe inert", beside=home,
                        props={"url": "/home?embedded=true"})
    open_builder(page, mod)
    settled(page)
    # **Retrying assertions, not a one-shot `evaluate`** — §271's trap. The
    # first version read the computed style once, passed on a fresh database
    # and failed on the accumulated one, and a sweep then scored the mutant
    # this test exists for as a survivor against a baseline that was already
    # failing it. A style is a state the page settles into, so it is waited for.
    frame = page.get_by_test_id("iframe")
    expect(frame).to_have_css("pointer-events", "none", timeout=30000)

    open_module(page, mod)
    settled(page)
    frame = page.get_by_test_id("iframe")
    expect(frame).to_have_css("pointer-events", "auto", timeout=30000)


def test_a_youtube_link_is_offered_its_embed_form(page, api, home) -> None:
    """p.547: "When pasting a standard YouTube URL… Workshop will detect the URL
    format and offer a one-click option to convert it to the proper embedded
    format." The offer, the conversion, and the offer going away once taken —
    a button that converted a URL into itself would be a control with nothing
    to do."""
    mod = iframe_module(api, "Iframe youtube", beside=home, props={"url": ""})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Iframe").first.click()

    box = page.get_by_test_id("iframe-url")
    expect(box).to_be_visible()
    expect(page.get_by_test_id("iframe-youtube")).to_have_count(0)
    box.fill("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    page.get_by_test_id("iframe-youtube").click()
    expect(box).to_have_value("https://www.youtube.com/embed/dQw4w9WgXcQ")
    expect(page.get_by_test_id("iframe-youtube")).to_have_count(0)


def test_a_framed_page_cannot_take_over_the_module(page, api, home) -> None:
    """The two claims the widget makes about a page it does not control.

    **Sandboxed without top-level navigation**, so a framed page cannot move the
    module out from under its viewer — the `allow-top-navigation` family is the
    one permission a hostile page would want, and it is asserted *absent* rather
    than the whole attribute compared, so adding a harmless permission later is
    not a failure here. And **`no-referrer`**, because the module's URL names the
    workspace and the app.

    Read as attributes because they *are* configuration: the browser enforces
    them, and a page that tried to break out would be a test of the browser.
    """
    mod = iframe_module(api, "Iframe sandbox", beside=home,
                        props={"url": "/home?embedded=true"})
    open_module(page, mod)
    settled(page)
    frame = page.get_by_test_id("iframe")
    expect(frame).to_be_visible(timeout=30000)
    sandbox = frame.get_attribute("sandbox")
    assert sandbox is not None, "the frame is not sandboxed at all"
    assert "allow-scripts" in sandbox, sandbox
    assert "allow-top-navigation" not in sandbox, sandbox
    expect(frame).to_have_attribute("referrerpolicy", "no-referrer")


def test_a_cleared_or_tiny_height_does_not_collapse_the_frame(page, api, home) -> None:
    """Clearing the Height box stores `0` — `Number("")` — and a frame drawn at
    that height is a widget nobody can see or select again. So `0` means the
    default, and anything below a usable floor is raised to it."""
    cleared = iframe_module(api, "Iframe cleared height", beside=home,
                            props={"url": "/home?embedded=true", "height": 0})
    open_module(page, cleared)
    settled(page)
    expect(page.get_by_test_id("iframe")).to_have_css("height", "480px", timeout=30000)

    tiny = iframe_module(api, "Iframe tiny height", beside=home,
                         props={"url": "/home?embedded=true", "height": 10})
    open_module(page, tiny)
    settled(page)
    expect(page.get_by_test_id("iframe")).to_have_css("height", "120px", timeout=30000)
