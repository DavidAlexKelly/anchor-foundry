"""p.363-364's Media Preview (parity `workshop.md` §7 / the media group).

> "The Media Preview widget can be used to display image, audio, video, and
> document media, given a supported media source. Currently supported media
> sources include media URLs, attachment properties, and media reference
> properties." (p.363)

> "**Attachment property**: Define an object set with a single object and select
> the attachment typed property to render a preview of the media for that
> object." (p.363-364)

The rules are `apps/web/src/components/canvas/media.test.ts`, mutation-tested
without a browser: what a media string may be, what kind a content type draws
as, and what to say when there is nothing to show.

**What needs a browser is that the bytes arrive.** An attachment is fetched with
a CSRF header and shown through an object URL, because an `<img src>` cannot set
headers and would be a 401 — which is a fact about this platform's auth that no
unit test can reach. So the assertions here are `naturalWidth` on a decoded
image and a request that was actually authorised.
"""
from __future__ import annotations

import base64
import json

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled

# A 1x1 red PNG, the same one `test_media_property.py` uses and for the same
# reason: the browser has to *decode* it for `naturalWidth` to be non-zero, so
# the assertion is that an image rendered rather than that an element exists.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
DATA_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


@pytest.fixture(scope="module")
def media(api):
    """One object carrying an image attachment and a PDF one.

    Both, for `test_media_property.py`'s reason: "the image renders" and "the
    document gets a link" are one rule seen from two sides, and a fixture with
    only the image cannot tell a working rule from one that renders everything.
    """
    mod = Module(api, "Media preview")
    base = f"/workspaces/{mod.workspace_id}"
    photo = api.upload_file(
        f"{base}/attachments", PNG, filename="dot.png", content_type="image/png"
    )
    doc = api.upload_file(
        f"{base}/attachments", PDF, filename="report.pdf", content_type="application/pdf"
    )
    mod.object_type(
        columns=["id", "name", "photo", "doc"],
        rows=[{"id": "M1", "name": "Has media",
               "photo": json.dumps(photo, sort_keys=True),
               "doc": json.dumps(doc, sort_keys=True)}],
        key="id", title="name",
        types={"photo": "attachment", "doc": "attachment"},
    )
    # The coerced values, which is what a resolved single-object variable holds
    # - the sync turns the JSON *text* in the column into the attachment object
    # (`property_values._coerce_attachment`), so this is the shape the widget
    # actually reads rather than the shape the dataset stores.
    mod.photo, mod.doc = photo, doc
    return mod


def build(api, media, name: str, props: dict | None = None, *, subject: bool = False):
    """One media preview, optionally over an object a variable holds."""
    variables: dict = {}
    props = props or {}
    if subject:
        # p.363's "object set with a single object" - this platform's
        # single-object variable, seeded with the one object the fixture has.
        variables["v_object"] = {
            "id": "v_object", "kind": "single_object", "label": "The object",
            "object_type_id": media.object_type_id,
            "default": {
                "primary_key": "M1",
                "object_type_id": media.object_type_id,
                "properties": {"id": "M1", "name": "Has media",
                               "photo": media.photo, "doc": media.doc},
            },
        }
    mod = Module(api, name, beside=media)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMediaPreview",
                   "props": {"source": "string", "url": "", "textVariable": None,
                             "subjectVariable": "v_object" if subject else None,
                             "property": "", "label": "", "maxHeight": 320,
                             **props}},
        }),
        "variables": variables,
        "events": {},
    })
    return mod


def decoded(page, testid: str = "media-image") -> int:
    """The rendered width of an image the browser actually decoded."""
    return page.get_by_test_id(testid).evaluate("el => el.naturalWidth")


# ---- p.363's media string ----------------------------------------------------
def test_a_data_url_renders_as_an_image(page, api, media) -> None:
    """p.363's third media-string format: "Data URL with a Base64-encoded
    media". Asserted through `naturalWidth`, so this is the browser having
    decoded the bytes rather than an `<img>` existing."""
    mod = build(api, media, "Media data url", {"url": DATA_URL})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-image")).to_be_visible()
    assert decoded(page) == 1


def test_a_javascript_url_is_refused_and_says_so(page, api, media) -> None:
    """**The refusal that matters most.** An app author sets the media string
    and every viewer's browser follows it, so a `javascript:` URL is an author
    running code in every session. Refused with a sentence rather than silently
    dropped, because an author who typed one needs to know why nothing appeared.
    """
    mod = build(api, media, "Media js url", {"url": "javascript:alert(1)"})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-image")).to_have_count(0)
    expect(page.get_by_test_id("media-problem")).to_contain_text("not one this platform will follow")


def test_an_html_data_url_is_refused(page, api, media) -> None:
    """The same rule by a longer route: a `data:text/html` is a document served
    with the app's own origin behind it."""
    mod = build(api, media, "Media html data url",
                {"url": "data:text/html,<script>alert(1)</script>"})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-problem")).to_contain_text("not one this platform will follow")


def test_no_media_string_says_which_thing_is_missing(page, api, media) -> None:
    """Four ways this widget ends up empty and four sentences, because they are
    four different things for an author to fix."""
    mod = build(api, media, "Media empty")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-problem")).to_have_text("No media string set")


def test_a_media_string_can_come_from_a_variable(page, api, media) -> None:
    """p.363's media string need not be written by the author - a variable is
    what makes the widget follow a selection."""
    mod = Module(api, "Media from variable", beside=media)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMediaPreview",
                   "props": {"source": "string", "url": "", "textVariable": "v_src",
                             "subjectVariable": None, "property": "", "label": "",
                             "maxHeight": 320}},
        }),
        "variables": {"v_src": {"id": "v_src", "kind": "string", "label": "Source",
                                "default": DATA_URL}},
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    assert decoded(page) == 1


# ---- p.363's attachment property ---------------------------------------------
def test_an_attachment_renders_through_an_authorised_fetch(page, api, media) -> None:
    """**The assertion a browser is for.**

    An attachment is private bytes behind a CSRF header, and an `<img src>`
    cannot set headers - so the widget fetches a Blob and points the element at
    an object URL. `naturalWidth` is what proves the round trip happened: an
    unauthorised request would be a 401 and an image that never decodes.
    """
    mod = build(api, media, "Media attachment",
                {"source": "attachment", "property": "photo"}, subject=True)
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-image")).to_be_visible()
    assert decoded(page) == 1
    # An object URL, not the download route - which is what says the bytes came
    # through a request that could carry the header.
    src = page.get_by_test_id("media-image").get_attribute("src")
    assert src.startswith("blob:"), src


def test_an_attachment_the_platform_will_not_inline_gets_a_link(page, api, media) -> None:
    """p.363 says "document media", and this platform serves a PDF as a
    download: a PDF can run script, and inline from the app's own origin is the
    stored-XSS shape `download_attachment` exists to describe.

    So it is a link with the filename on it - which is an answer, where a
    broken `<img>` would not be.
    """
    mod = build(api, media, "Media pdf",
                {"source": "attachment", "property": "doc"}, subject=True)
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-image")).to_have_count(0)
    link = page.get_by_test_id("media-link")
    expect(link).to_contain_text("report.pdf")


def test_a_property_with_no_attachment_says_so(page, api, media) -> None:
    mod = build(api, media, "Media no attachment",
                {"source": "attachment", "property": "name"}, subject=True)
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-problem")).to_have_text("No attachment on this object")


def test_no_object_chosen_says_so_rather_than_drawing_nothing(page, api, media) -> None:
    """An attachment source with no object variable bound. The widget is
    unfinished, and saying which half is missing is the difference between a
    settings panel somebody can fix and a blank rectangle."""
    mod = build(api, media, "Media no object",
                {"source": "attachment", "property": "photo"})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-problem")).to_have_text("No attachment on this object")


# ---- the caption -------------------------------------------------------------
def test_the_caption_is_shown_and_names_the_image(page, api, media) -> None:
    """The caption is also the accessible name. A preview whose whole content is
    one file has nothing else to describe it, so an empty `alt` would make the
    widget invisible to a screen reader rather than unobtrusive."""
    mod = build(api, media, "Media caption", {"url": DATA_URL, "label": "Site photo"})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-caption")).to_have_text("Site photo")
    expect(page.get_by_test_id("media-image")).to_have_attribute("alt", "Site photo")


def test_without_a_caption_the_filename_is_the_accessible_name(page, api, media) -> None:
    mod = build(api, media, "Media no caption",
                {"source": "attachment", "property": "photo"}, subject=True)
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("media-image")).to_have_attribute("alt", "dot.png")
    expect(page.get_by_test_id("media-caption")).to_have_count(0)


def test_the_maximum_height_is_applied(page, api, media) -> None:
    """Measured rather than read off the attribute: a setting no rule acts on
    passes every other kind of check."""
    mod = build(api, media, "Media height", {"url": DATA_URL, "maxHeight": 120})
    open_module(page, mod)
    settled(page)

    height = page.get_by_test_id("media-image").evaluate(
        "el => getComputedStyle(el).maxHeight"
    )
    assert height == "120px", height


# ---- the builder -------------------------------------------------------------
def test_the_settings_panel_offers_the_source_it_is_set_to(page, api, media) -> None:
    """p.363's two sources want different inputs, and showing both at once would
    put two answers to "where does this media come from" on one panel."""
    mod = build(api, media, "Media settings", {"url": DATA_URL})
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Media preview").first.click()
    expect(page.get_by_test_id("media-url")).to_be_visible()
    expect(page.get_by_test_id("media-property")).to_have_count(0)

    page.get_by_test_id("media-source").select_option("attachment")
    expect(page.get_by_test_id("media-property")).to_be_visible()
    expect(page.get_by_test_id("media-url")).to_have_count(0)


def test_the_object_picker_offers_only_single_object_variables(page, api, media) -> None:
    mod = build(api, media, "Media object picker",
                {"source": "attachment", "property": "photo"}, subject=True)
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Media preview").first.click()
    options = page.get_by_test_id("media-subject").locator("option").all_text_contents()
    assert "The object" in options, options
