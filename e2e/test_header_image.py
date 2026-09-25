"""p.47's application logo image and p.48's collapsed-state image (§472).

> "Image: Select an image from your Palantir resources or upload one from your
> computer. Customize the image height. Position the image: Choose left,
> center, or right for horizontal headers; choose top or bottom for vertical
> headers." (p.47)
>
> "Add a custom image for the collapsed state … To display a collapsed image,
> you must first set up a header image as outlined above." (p.48–49)

Which mark shows when is `header-logo.test.ts`. What needs a browser is that
an uploaded image reaches the header at all - through the authenticated fetch,
since an `<img src>` cannot carry the session header - at the height and in
the place asked for, and that collapsing swaps it.
"""
from __future__ import annotations

import struct
import zlib

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, select_node


def png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A solid PNG, so a test has a real image to upload without a fixture file."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def upload(api, mod: Module, name: str, data: bytes) -> dict:
    return api.upload_file(f"/workspaces/{mod.workspace_id}/attachments", data,
                           filename=name, content_type="image/png")


def header_module(api, name: str, props: dict, *, upload_as: list[str] = ()) -> Module:
    mod = Module(api, name)
    refs = {n: upload(api, mod, n, png(40, 20, (20, 100, 110))) for n in upload_as}
    resolved = {k: (refs[v] if isinstance(v, str) and v in refs else v) for k, v in props.items()}
    mod.define({"format": 2, "layout": layout({
        "hdr": {"resolvedName": "CanvasHeader", "props": {"title": "Fleet", **resolved}},
        "page": {"resolvedName": "CanvasPage", "props": {"title": "Overview"},
                 "isCanvas": True, "nodes": ["body"]},
        "body": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "BODY"},
                 "parent": "page"},
    }), "variables": {}, "events": {}})
    return mod


def logo(page):
    return page.get_by_test_id("header-logo-image").locator("img")


def test_an_uploaded_image_is_the_logo_at_the_height_asked(page, api) -> None:
    mod = header_module(api, "Header image", {"logoImage": "logo.png", "logoHeight": 48,
                                              "icon": "◎"}, upload_as=["logo.png"])
    open_module(page, mod)
    expect(logo(page)).to_be_visible(timeout=30000)
    expect(logo(page)).to_have_attribute("data-filename", "logo.png")
    # Fetched and shown, not a broken image: it has its natural size.
    assert logo(page).evaluate("img => img.naturalWidth") == 40
    assert abs(logo(page).bounding_box()["height"] - 48) < 1
    # The image replaces the icon rather than sitting beside it.
    expect(page.get_by_test_id("header-logo")).to_have_count(0)
    # And with no position set, it is where the icon always was: before the
    # title. A default of anything else would move every saved header's logo.
    assert logo(page).bounding_box()["x"] < page.locator(".canvas-header-title").bounding_box()["x"]


@pytest.mark.parametrize("where", ["left", "right", "center"])
def test_the_image_goes_where_it_is_put(page, api, where) -> None:
    mod = header_module(api, f"Header image {where}", {"logoImage": "logo.png",
                                                       "logoPosition": where},
                        upload_as=["logo.png"])
    open_module(page, mod)
    expect(logo(page)).to_be_visible(timeout=30000)
    image = logo(page).bounding_box()
    header = page.locator(".canvas-header").bounding_box()
    title = page.locator(".canvas-header-title").bounding_box()
    middle = image["x"] + image["width"] / 2
    if where == "left":
        assert image["x"] < title["x"], (image, title)
    elif where == "right":
        assert image["x"] > title["x"] + title["width"], (image, title)
        assert header["x"] + header["width"] - (image["x"] + image["width"]) < 24, (image, header)
    else:
        assert abs(middle - (header["x"] + header["width"] / 2)) < 2, (image, header)


def test_a_vertical_header_puts_it_at_the_bottom_when_asked(page, api) -> None:
    mod = header_module(api, "Header image bottom", {
        "orientation": "vertical", "logoImage": "logo.png", "logoPosition": "bottom"},
        upload_as=["logo.png"])
    open_module(page, mod)
    expect(logo(page)).to_be_visible(timeout=30000)
    assert logo(page).bounding_box()["y"] > page.locator(".canvas-header-title").bounding_box()["y"]


def test_collapsed_the_collapsed_image_shows_and_open_the_logo(page, api) -> None:
    mod = header_module(api, "Header collapsed image", {
        "orientation": "vertical", "collapsible": True, "collapsedByDefault": True,
        "logoImage": "logo.png", "collapsedImage": "mini.png"},
        upload_as=["logo.png", "mini.png"])
    open_module(page, mod)
    expect(logo(page)).to_have_attribute("data-filename", "mini.png", timeout=30000)
    page.get_by_role("button", name="Expand the header").click()
    expect(logo(page)).to_have_attribute("data-filename", "logo.png")


def test_the_panel_uploads_an_image_and_refuses_what_is_not_one(page, api) -> None:
    mod = header_module(api, "Header image panel", {})
    open_builder(page, mod)
    select_node(page, "Header")
    page.get_by_test_id("header-logo-upload").set_input_files(
        {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"not a picture"})
    expect(page.locator(".field-hint[role=alert]")).to_have_text("That is not an image.")
    page.get_by_test_id("header-logo-upload").set_input_files(
        {"name": "brand.png", "mimeType": "image/png", "buffer": png(8, 8, (200, 50, 50))})
    expect(page.get_by_test_id("header-logo-upload-name")).to_have_text("brand.png")
    page.get_by_test_id("header-logo-height").fill("40")
    page.get_by_test_id("header-logo-position").select_option("right")
    save(page)
    props = mod.definition()["layout"]["hdr"]["props"]
    assert props["logoImage"]["filename"] == "brand.png", props
    assert props["logoImage"]["content_type"] == "image/png", props
    assert (props["logoHeight"], props["logoPosition"]) == (40, "right"), props
    expect(logo(page)).to_be_visible()
