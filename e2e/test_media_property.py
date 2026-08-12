"""Media shown rather than offered (decision 0009 part 2; parity `ontology.md`
§4.1's "media reference → dedicated media viewer").

**There is no media reference type**, and that is the decision: Foundry's points
into a media set, and a type shaped like one with no media set behind it is a
contract nobody honours. What was missing was the *renderer* — an attachment
holding a PNG drew a download link, so the viewer row was blocked on display,
not on storage.

So the question this file asks is the one a browser is for: does the picture
actually appear, and does everything else still get a link?
"""
from __future__ import annotations

import base64
import json

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

# A 1x1 red PNG. Small enough to inline, and a real image rather than bytes
# labelled as one - the browser has to decode it for `naturalWidth` to be
# non-zero, which is what the assertion below actually checks.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


@pytest.fixture(scope="module")
def module(api):
    """One object with two attachments: an image and a PDF.

    Both in the same fixture on purpose. "The image renders" and "the PDF does
    not" are the same rule seen from two sides, and a fixture with only the
    image could not tell a working rule from one that renders everything.
    """
    mod = Module(api, "Media property")
    base = f"/workspaces/{mod.workspace_id}"
    photo = api.upload_file(
        f"{base}/attachments", PNG, filename="dot.png", content_type="image/png"
    )
    doc = api.upload_file(
        f"{base}/attachments", PDF, filename="report.pdf", content_type="application/pdf"
    )
    # The whole reference as JSON text in the dataset column, which is exactly
    # what write-back stores and what the next sync reads back
    # (`property_values._coerce_attachment` documents the round trip).
    mod.object_type(
        columns=["id", "name", "photo", "doc"],
        rows=[{
            "id": "M1",
            "name": "Has media",
            "photo": json.dumps(photo, sort_keys=True),
            "doc": json.dumps(doc, sort_keys=True),
        }],
        key="id",
        title="name",
        types={"photo": "attachment", "doc": "attachment"},
    )
    return mod


def open_the_object(page, module):
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == 1,
               what="this type's one object")
    rows.first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()


def test_an_attached_image_renders_in_the_object_view(page, module):
    """§4.1's media viewer row, in the only form this platform can honour."""
    open_the_object(page, module)
    cell = page.get_by_test_id("sov-normal").locator("[data-property='photo']")
    image = cell.locator("img")
    expect(image).to_be_visible()
    # **Decoded, not merely present.** An `<img>` with a broken src is visible
    # and has a zero natural width, so asserting the element would pass against
    # a URL that 404s - which is the failure this is most likely to have.
    eventually(lambda: image.evaluate("el => el.naturalWidth"), lambda w: w > 0,
               what="the image actually decoded by the browser")


def test_the_image_keeps_its_filename_underneath(page, module):
    """A picture with no name is not a file anybody can go and find again, so
    the caption stays - and it is still the download link it always was."""
    open_the_object(page, module)
    cell = page.get_by_test_id("sov-normal").locator("[data-property='photo']")
    expect(cell).to_contain_text("dot.png")
    expect(cell.locator("a[download='dot.png']")).to_have_count(1)


def test_a_pdf_is_still_a_download_link(page, module):
    """The other side of the same rule. Anything this build cannot show stays
    exactly what it was, rather than becoming a broken player."""
    open_the_object(page, module)
    cell = page.get_by_test_id("sov-normal").locator("[data-property='doc']")
    expect(cell).to_contain_text("report.pdf")
    expect(cell.locator("img")).to_have_count(0)
    expect(cell.locator("[data-media-kind]")).to_have_count(0)


def test_the_media_kind_is_on_the_element(page, module):
    """The renderer's decision, readable from the DOM - so a future viewer
    (a lightbox, a gallery) has something to hang off without re-deriving
    which kind this is."""
    open_the_object(page, module)
    cell = page.get_by_test_id("sov-normal").locator("[data-property='photo']")
    expect(cell.locator("[data-media-kind='image']")).to_have_count(1)
