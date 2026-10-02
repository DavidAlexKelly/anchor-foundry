"""Tabs on a configured full Object View (§695; `object-views` p.34-35).

> "Each tab corresponds to a single workshop module. If only one tab is
> configured, the tab title will be hidden … Selecting the gear icon opens a
> dialog that allows you to add, reorder, rename, and delete Object View
> tabs." (p.35)

The dialog saves the whole list. The first tab is the view's own module, so a
view saved before tabs existed is a view of one tab.
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_api import hdr  # noqa: E402
from test_object_views import (  # noqa: E402,F401
    _fresh_identity_cache, client, fx, make_module, module_id, pbase, wbase,
)


def a_type(client, fx) -> str:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"tabbed_{uuid.uuid4().hex[:8]}", "display_name": f"Tabbed {uuid.uuid4().hex[:4]}",
        "properties": [{"api_name": "status", "data_type": "string"}],
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def other_module(client, fx) -> str:
    return make_module(client, fx, variables={
        "v_it": {"id": "v_it", "kind": "single_object", "label": "It"}})


def put_tabs(client, fx, type_id: str, tabs: list[dict], sub=None):
    return client.put(f"{wbase(fx)}/object-types/{type_id}/view/tabs",
                      headers=hdr(sub or fx.editor_sub), json={"tabs": tabs})


def view(client, fx, type_id: str) -> dict:
    return client.get(f"{wbase(fx)}/object-types/{type_id}/view",
                      headers=hdr(fx.viewer_sub)).json()


def test_a_view_saved_without_tabs_is_one_tab_under_its_module_name(
    client, fx, module_id
) -> None:
    type_id = a_type(client, fx)
    r = client.put(f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.editor_sub),
                   json={"canvas_app_id": module_id, "subject_variable": "v_obj"})
    assert r.status_code == 200, r.text
    (only,) = r.json()["tabs"]
    assert only["id"] == r.json()["id"]
    assert only["title"] == r.json()["canvas_app_name"]
    assert only["canvas_app_id"] == module_id and only["subject_variable"] == "v_obj"


def test_tabs_are_added_renamed_reordered_and_deleted_as_one_list(
    client, fx, module_id
) -> None:
    type_id = a_type(client, fx)
    other = other_module(client, fx)
    r = put_tabs(client, fx, type_id, [
        {"title": "Overview", "canvas_app_id": module_id, "subject_variable": "v_obj"},
        {"title": "Details", "canvas_app_id": other, "subject_variable": "v_it"},
        {"title": "Again", "canvas_app_id": module_id, "subject_variable": "v_obj"},
    ])
    assert r.status_code == 200, r.text
    got = view(client, fx, type_id)
    assert [t["title"] for t in got["tabs"]] == ["Overview", "Details", "Again"]
    assert got["canvas_app_id"] == module_id and got["title"] == "Overview"
    assert got["tabs"][0]["id"] == got["id"]
    assert got["tabs"][1]["canvas_app_id"] == other
    first_view_id = got["id"]

    # Reordered and renamed, one deleted: the module of the first becomes the view's.
    r = put_tabs(client, fx, type_id, [
        {"title": "Specifics", "canvas_app_id": other, "subject_variable": "v_it"},
        {"title": "Summary", "canvas_app_id": module_id, "subject_variable": "v_obj"},
    ])
    assert r.status_code == 200, r.text
    got = view(client, fx, type_id)
    assert [t["title"] for t in got["tabs"]] == ["Specifics", "Summary"]
    assert got["canvas_app_id"] == other and got["subject_variable"] == "v_it"
    assert got["id"] == first_view_id

    # Down to one tab; a blank first title is the module's name.
    r = put_tabs(client, fx, type_id, [
        {"title": "", "canvas_app_id": module_id, "subject_variable": "v_obj"}])
    assert r.status_code == 200, r.text
    (only,) = view(client, fx, type_id)["tabs"]
    assert only["title"] == only["canvas_app_name"]
    assert r.json()["title"] == ""


def test_a_tab_after_the_first_needs_a_title(client, fx, module_id) -> None:
    type_id = a_type(client, fx)
    r = put_tabs(client, fx, type_id, [
        {"title": "", "canvas_app_id": module_id, "subject_variable": "v_obj"},
        {"title": "  ", "canvas_app_id": module_id, "subject_variable": "v_obj"},
    ])
    assert r.status_code == 422, r.text
    assert "needs a title" in r.json()["detail"]
    assert view(client, fx, type_id) is None


def test_every_tab_is_checked_as_a_view_is(client, fx, module_id) -> None:
    type_id = a_type(client, fx)
    r = put_tabs(client, fx, type_id, [
        {"title": "A", "canvas_app_id": module_id, "subject_variable": "v_obj"},
        {"title": "B", "canvas_app_id": module_id, "subject_variable": "v_nope"},
    ])
    assert r.status_code == 422, r.text
    assert "'v_nope' is not a single-object variable" in r.json()["detail"]
    r = put_tabs(client, fx, type_id, [
        {"title": "A", "canvas_app_id": module_id, "subject_variable": "v_obj"},
        {"title": "B", "canvas_app_id": str(uuid.uuid4()), "subject_variable": "v_obj"},
    ])
    assert r.status_code == 404, r.text
    assert view(client, fx, type_id) is None


def test_the_number_of_tabs_is_bounded(client, fx, module_id) -> None:
    type_id = a_type(client, fx)
    tab = {"title": "T", "canvas_app_id": module_id, "subject_variable": "v_obj"}
    assert put_tabs(client, fx, type_id, []).status_code == 422
    assert put_tabs(client, fx, type_id, [tab] * 21).status_code == 422
    assert put_tabs(client, fx, type_id, [tab] * 20).status_code == 200
    assert len(view(client, fx, type_id)["tabs"]) == 20


def test_a_viewer_cannot_set_tabs(client, fx, module_id) -> None:
    type_id = a_type(client, fx)
    r = put_tabs(client, fx, type_id, [
        {"title": "A", "canvas_app_id": module_id, "subject_variable": "v_obj"}],
        sub=fx.viewer_sub)
    assert r.status_code == 403, r.text


def test_deleting_a_tabs_module_takes_only_that_tab(client, fx, module_id) -> None:
    type_id = a_type(client, fx)
    other = other_module(client, fx)
    assert put_tabs(client, fx, type_id, [
        {"title": "Main", "canvas_app_id": module_id, "subject_variable": "v_obj"},
        {"title": "Side", "canvas_app_id": other, "subject_variable": "v_it"},
    ]).status_code == 200
    assert client.delete(f"{pbase(fx)}/canvas-apps/{other}",
                         headers=hdr(fx.editor_sub)).status_code == 204
    assert [t["title"] for t in view(client, fx, type_id)["tabs"]] == ["Main"]


def test_setting_the_view_keeps_its_other_tabs(client, fx, module_id) -> None:
    """The old single-module PUT changes the first tab only."""
    type_id = a_type(client, fx)
    other = other_module(client, fx)
    assert put_tabs(client, fx, type_id, [
        {"title": "Main", "canvas_app_id": module_id, "subject_variable": "v_obj"},
        {"title": "Side", "canvas_app_id": other, "subject_variable": "v_it"},
    ]).status_code == 200
    r = client.put(f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.editor_sub),
                   json={"canvas_app_id": other, "subject_variable": "v_it"})
    assert r.status_code == 200, r.text
    assert [t["canvas_app_id"] for t in r.json()["tabs"]] == [other, other]
