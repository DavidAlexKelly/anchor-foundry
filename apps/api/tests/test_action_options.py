"""A multiple-choice parameter's allowed values (§335; db 0086;
`action-types` p.33).

    "Adding filters to non-object reference **multiple choice** or single object
     reference parameters will determine the allowed values that are selectable
     in the parameter's dropdown." (p.33)

    "…select the property that includes all allowed values for the parameter
     dropdown. **If only one linked object is available in the resulting object
     set and the parameter is required, the parameter dropdown will
     automatically prefill with the corresponding property value.** The
     resulting multiple choice options will be derived from the set of objects
     that the user has permission to view." (p.33)

**Two claims, and the file is split along them.** Whether a document could
produce a dropdown at all is decided without a database; what the dropdown
*holds* needs real objects, because p.33's options are the distinct values one
property takes across a set and "distinct" is a question only the store can
answer honestly.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import action_options as options  # noqa: E402
from src.services import action_filters as filters  # noqa: E402
from src.services import instance_store  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

REGIONS = "11111111-1111-1111-1111-111111111111"
TEAMS = "22222222-2222-2222-2222-222222222222"

#: What each object type offers. **Deliberately disjoint**: `label` is on the
#: Regions type and not the Teams one, so a check reading the wrong type's
#: properties cannot pass by coincidence — §334's lesson, applied up front.
PROPERTIES = {REGIONS: {"code", "label"}, TEAMS: {"name", "size"}}


def a_parameter(**over) -> dict:
    return {"api_name": "region", "data_type": "string", **over}


def from_set(type_id: str = REGIONS, prop: str = "label") -> dict:
    return {"object_type_id": type_id, "property": prop}


def check(parameter: dict, *, properties=PROPERTIES):
    return options.check_options(parameter, properties=properties)


# ---- whether a document could produce a dropdown --------------------------------
def test_no_document_is_a_parameter_that_takes_what_is_typed() -> None:
    """Every parameter written before db 0086, and every one whose panel nobody
    has opened."""
    assert options.options_of(a_parameter()) is None
    assert options.options_of(a_parameter(options_from={})) is None
    assert check(a_parameter()) is None


def test_asking_a_parameter_with_no_document_reads_nothing() -> None:
    """The guard returns before the connection is touched, which is how this
    can be asked without one — and a `TypeError` would be a poor answer for a
    caller that forgot to check.

    `asyncio.run` rather than a marker: this suite has no async plugin
    configured, and a test that silently *skips* proves even less than one that
    passes for the wrong reason.
    """
    assert asyncio.run(options.options(
        None, a_parameter(), workspace_id=uuid.uuid4(),
    )) == ([], False)


def test_a_legal_document_comes_back_normalised() -> None:
    assert check(a_parameter(options_from=from_set())) == {
        "object_type_id": REGIONS, "property": "label",
    }


def test_an_unknown_option_is_refused() -> None:
    """A key nobody validated is a key `options` would read."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(options_from={**from_set(), "order_by": "code"}))
    assert "order_by" in str(caught.value)


def test_an_object_parameter_is_refused() -> None:
    """**p.33's other shape**, which §330 built. A parameter with both would be
    two answers to "what may I pick" and no way to say which won.

    Asserted on the sentence that *points at the other dropdown*, not merely on
    the word "object": `object` is not in `OPTIONABLE_TYPES` either, so the
    fallback refusal says "is a object, which cannot be offered…" and a looser
    assertion passed with this branch deleted. A sweep said so.
    """
    with pytest.raises(ValueError) as caught:
        check(a_parameter(data_type="object", options_from=from_set()))
    assert "single object reference" in str(caught.value)
    assert "cannot be offered" not in str(caught.value)


def test_a_type_that_cannot_be_offered_as_a_list_is_refused() -> None:
    """A dropdown of attachments is not a thing anybody can read."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(data_type="attachment", options_from=from_set()))
    assert "attachment" in str(caught.value)


def test_a_type_this_workspace_does_not_have_is_refused() -> None:
    with pytest.raises(ValueError) as caught:
        check(a_parameter(options_from=from_set()), properties={TEAMS: {"name"}})
    assert "does not have" in str(caught.value)


def test_no_property_named_is_refused() -> None:
    """Half a rule. `options` would group on nothing and the dropdown would be
    empty for a reason nobody chose."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(options_from={"object_type_id": REGIONS}))
    assert "which property" in str(caught.value)


def test_a_property_the_named_type_lacks_is_refused() -> None:
    """Checked against the type the *options* name, not the action's own. The
    fixture's two types share no property names, so reading the wrong one
    cannot pass by coincidence."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(options_from=from_set(REGIONS, "name")))
    assert "name" in str(caught.value)


def test_a_property_of_the_other_type_is_still_refused() -> None:
    """The mirror of the test above, so "refuses everything" cannot pass for
    "checks the right type"."""
    check(a_parameter(options_from=from_set(TEAMS, "size")))
    with pytest.raises(ValueError):
        check(a_parameter(options_from=from_set(TEAMS, "label")))


def test_the_document_is_rebuilt_rather_than_echoed() -> None:
    """A stored key nothing validated is one `options` would read."""
    got = check(a_parameter(options_from={
        "object_type_id": REGIONS, "property": "  label  ",
    }))
    assert got == {"object_type_id": REGIONS, "property": "label"}


# ---- p.33's prefill ------------------------------------------------------------
def test_one_value_on_a_required_parameter_prefills() -> None:
    """p.33: "the parameter dropdown will automatically prefill with the
    corresponding property value"."""
    assert options.prefill(["eu"], required=True) == "eu"


def test_several_values_do_not_prefill() -> None:
    """There is a decision to make, and making it for somebody is not p.33's
    sentence."""
    assert options.prefill(["eu", "uk"], required=True) is None


def test_no_values_do_not_prefill() -> None:
    assert options.prefill([], required=True) is None


def test_an_optional_parameter_does_not_prefill() -> None:
    """p.33's own qualifier, and worth keeping: an optional parameter left
    blank means something, and filling it in would be choosing for somebody."""
    assert options.prefill(["eu"], required=False) is None


# ---- §214's half ---------------------------------------------------------------
def test_a_value_that_was_offered_is_accepted() -> None:
    options.check_option_values(a_parameter(), "eu", allowed=["eu", "uk"])


def test_a_value_that_was_not_offered_is_refused() -> None:
    """p.33 does not say this and it belongs anyway: a dropdown narrowed to
    three regions beside a check that accepts any string is §214's control that
    looks like it works, and the check runs whether or not anybody drew a
    form."""
    with pytest.raises(ValueError) as caught:
        options.check_option_values(a_parameter(), "za", allowed=["eu", "uk"])
    assert "za" in str(caught.value)
    assert "region" in str(caught.value)


def test_an_unfilled_parameter_is_not_refused() -> None:
    """An empty box is `required`'s business, and refusing it here would make
    every optional multiple-choice parameter impossible to leave blank."""
    for empty in (None, ""):
        options.check_option_values(a_parameter(), empty, allowed=["eu"])


# ---- through the API, with objects behind the values ----------------------------
@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def a_type(client: TestClient, fx: Fixture, tag: str, rows: list[tuple[str, str]],
           columns=("code", "label")):
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"op_{tag}", "display_name": f"Options {tag}",
              "properties": [{"api_name": c, "data_type": "string"}
                             for c in columns]},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    header = ",".join(columns)
    csv = f"{header}\n" + "".join(",".join(map(str, row)) + "\n" for row in rows)
    dataset = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Options {tag}"},
        files={"file": ("f.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    source = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": columns[0],
              "column_mappings": {c: c for c in columns[1:]}},
    )
    assert source.status_code == 201, source.text
    synced = client.post(
        f"{pbase(fx)}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub),
    )
    assert synced.status_code == 200, synced.text
    return type_id


@pytest.fixture(scope="module")
def setup(client: TestClient, fx: Fixture):
    """Offices whose `label` repeats, so "distinct" is a claim with something
    to prove: four objects, three labels."""
    tag = uuid.uuid4().hex[:8]
    # **`US` three times**, so the store's frequency order (US, EU, UK) and the
    # alphabetical one (EU, UK, US) differ. A fixture where they agreed could
    # not tell which the control used, and a sweep walked through it.
    #
    # `tier` is a third *populated* property, for §336's filters to cut on. The
    # first version filtered on `code` — the primary key column, declared as a
    # property and written by nothing — so every filtered list came back empty
    # and the tests failed for a reason that had nothing to do with filtering.
    region_type = a_type(
        client, fx, f"reg{tag}",
        [("o1", "US", "gold"), ("o2", "US", "gold"), ("o3", "US", "silver"),
         ("o4", "EU", "gold"), ("o5", "UK", "silver")],
        columns=("code", "label", "tier"),
    )
    ticket_type = a_type(client, fx, f"tkt{tag}", [("t1", "x")])
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket_type, "api_name": f"opt_{tag}",
              "display_name": "Assign", "editable_properties": ["label"]},
    )
    assert action.status_code == 201, action.text
    tickets = client.get(f"{wbase(fx)}/object-types/{ticket_type}/instances",
                         headers=hdr(fx.editor_sub)).json()["items"]
    return {"action": action.json()["id"], "region_type": region_type,
            "ticket": tickets[0]["id"]}


def define(client, fx, setup, options_from, *, required=False, sub=None,
           data_type="string"):
    return client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(sub or fx.editor_sub),
        json={"parameters": [
                  {"api_name": "region", "display_name": "Region",
                   "data_type": data_type, "required": required,
                   "options_from": options_from},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "label", "parameter": "region"}}],
              "criteria": []},
    )


def offered(client, fx, setup, values=None, sub=None):
    r = client.post(
        f"{wbase(fx)}/action-types/{setup['action']}/parameter-choices",
        headers=hdr(sub or fx.viewer_sub), json={"values": values or {}},
    )
    assert r.status_code == 200, r.text
    return {c["parameter"]: c for c in r.json()}


def run(client, fx, setup, values, sub=None):
    return client.post(
        f"{pbase(fx)}/actions/{setup['action']}/execute",
        headers=hdr(sub or fx.editor_sub),
        json={"instance_id": setup["ticket"], "values": values},
    )


def test_the_options_are_the_distinct_values_of_the_property(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**p.33's sentence with objects behind it.** Four objects, three labels —
    a version that listed one option per object would offer EU twice."""
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "label"}).raise_for_status()
    offer = offered(client, fx, setup)["region"]
    assert offer["kind"] == "values"
    assert offer["values"] == ["EU", "UK", "US"]
    # And **not** truncated, which the test below cannot say for it: without
    # this, "everything is truncated" passes every assertion in this file.
    assert offer["truncated"] is False


def test_a_values_offer_says_which_shape_it_is(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.33's two shapes come back in one response, and an object type with no
    objects and a property with no values are both empty — so the form is told
    which control to draw rather than guessing from which list is non-empty."""
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "label"}).raise_for_status()
    offer = offered(client, fx, setup)["region"]
    assert offer["kind"] == "values"
    assert offer["object_type_id"] is None
    assert offer["items"] == []


def test_one_value_and_required_prefills_through_the_api(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.33's prefill, end to end. `code` is unique per object, so grouping on
    it gives four values; `label` gives three; a type with one value is what
    this needs, so the fixture makes one."""
    tag = uuid.uuid4().hex[:8]
    only = a_type(client, fx, f"one{tag}", [("a", "SOLE"), ("b", "SOLE")])
    define(client, fx, setup, {"object_type_id": only, "property": "label"},
           required=True).raise_for_status()
    offer = offered(client, fx, setup)["region"]
    assert offer["values"] == ["SOLE"]
    # Two objects, one value — p.33 says "one linked object" and this build
    # reads it for its purpose: there is one answer, so there is nothing to
    # choose. See `action_options.prefill`.
    assert offer["prefill"] == "SOLE"


def test_several_values_do_not_prefill_through_the_api(
    client: TestClient, fx: Fixture, setup
) -> None:
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "label"},
           required=True).raise_for_status()
    assert offered(client, fx, setup)["region"]["prefill"] is None


def test_an_optional_parameter_with_one_value_does_not_prefill_through_the_api(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.33's `required` qualifier, through the door a caller uses.

    The prefill tests above all use a required parameter, so a route that
    passed `required=True` regardless behaved identically — a sweep said so.
    """
    tag = uuid.uuid4().hex[:8]
    only = a_type(client, fx, f"opt{tag}", [("a", "SOLE"), ("b", "SOLE")])
    define(client, fx, setup, {"object_type_id": only, "property": "label"},
           required=False).raise_for_status()
    offer = offered(client, fx, setup)["region"]
    assert offer["values"] == ["SOLE"]
    assert offer["prefill"] is None


def test_what_is_stored_is_the_normalised_document(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**The check's answer is what gets written**, not what arrived.

    A property with whitespace round it passes the refusals — `check_options`
    strips before comparing — and would then be grouped on verbatim, so the
    dropdown would be empty for a reason nobody could see. The route stores
    what the check returned, and a sweep that dropped the assignment left every
    other test passing.
    """
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "  label  "}).raise_for_status()
    read = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                      headers=hdr(fx.editor_sub)).json()
    region = next(p for p in read["parameters"] if p["api_name"] == "region")
    assert region["options_from"]["property"] == "label"
    assert offered(client, fx, setup)["region"]["values"] == ["EU", "UK", "US"]


def test_a_submission_outside_the_options_is_refused(
    client: TestClient, fx: Fixture, setup
) -> None:
    """§214's half. A dropdown narrowed to three regions beside a check that
    accepts any string is a control that looks like it works."""
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "label"}).raise_for_status()
    refused = run(client, fx, setup, {"region": "ZA"})
    assert refused.status_code == 422, refused.text
    assert "offers" in refused.text


def test_a_submission_inside_the_options_is_accepted(
    client: TestClient, fx: Fixture, setup
) -> None:
    """Without this the refusal above passes for a check that refuses
    everything."""
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "label"}).raise_for_status()
    ok = run(client, fx, setup, {"region": "UK"})
    assert ok.status_code == 200, ok.text


def test_a_parameter_with_no_options_still_takes_anything(
    client: TestClient, fx: Fixture, setup
) -> None:
    """Every action written before §335, and the reason the column is NULL
    rather than an empty document."""
    define(client, fx, setup, None).raise_for_status()
    assert "region" not in offered(client, fx, setup)
    assert run(client, fx, setup, {"region": "anything"}).status_code == 200


def test_an_options_document_on_an_object_parameter_is_refused_by_the_api(
    client: TestClient, fx: Fixture, setup
) -> None:
    """Through the door a caller uses, not only against the function."""
    bad = define(client, fx, setup,
                 {"object_type_id": setup["region_type"], "property": "label"},
                 data_type="object")
    assert bad.status_code == 422, bad.text


def test_the_saved_document_comes_back_and_can_be_sent_again(
    client: TestClient, fx: Fixture, setup
) -> None:
    """Read-modify-write: what the editor saved is what it can send again."""
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "label"}).raise_for_status()
    read = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                      headers=hdr(fx.editor_sub)).json()
    region = next(p for p in read["parameters"] if p["api_name"] == "region")
    assert region["options_from"] == {
        "object_type_id": setup["region_type"], "property": "label",
    }
    again = define(client, fx, setup, region["options_from"])
    assert again.status_code == 200, again.text


def test_a_viewer_gets_the_values_but_not_the_document(
    client: TestClient, fx: Fixture, setup
) -> None:
    """§333's redaction argument in a third shape: the document names an object
    type and a property, and p.40's concern is the combination. The *values*
    are the dropdown itself and RLS already decided which objects this reader
    could see them on, so they are not redacted."""
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "label"}).raise_for_status()
    read = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                      headers=hdr(fx.viewer_sub)).json()
    region = next(p for p in read["parameters"] if p["api_name"] == "region")
    assert region["options_from"] is None

    as_editor = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                           headers=hdr(fx.editor_sub)).json()
    mine = next(p for p in as_editor["parameters"] if p["api_name"] == "region")
    assert mine["options_from"] is not None

    assert offered(client, fx, setup, sub=fx.viewer_sub)["region"]["values"] == [
        "EU", "UK", "US",
    ]


def test_more_distinct_values_than_the_control_holds_are_reported(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**§256, and the one read that does not fall into it.**

    Truncation is measured against the *distinct total the store reports*, not
    against how many rows were read — collapsing a page of objects would answer
    "the distinct values of those objects", which is a different question and
    one nothing on screen could distinguish.
    """
    tag = uuid.uuid4().hex[:8]
    many = a_type(client, fx, f"many{tag}", [
        (f"k{n:03d}", f"V{n:03d}")
        for n in range(instance_store.INSTANCE_PAGE_SIZE + 5)
    ])
    define(client, fx, setup,
           {"object_type_id": many, "property": "label"}).raise_for_status()
    offer = offered(client, fx, setup)["region"]
    assert offer["truncated"] is True
    assert len(offer["values"]) == instance_store.INSTANCE_PAGE_SIZE


def test_the_options_are_sorted_for_display(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**Two orderings, and the fixture has to tell them apart.**

    The store returns the most common first, so a cap keeps the ones somebody
    is most likely to want; what survives is sorted so the control does not
    reshuffle as the data moves. `US` is the most common here and the last
    alphabetically, so `== sorted(values)` is a claim rather than a tautology —
    the first fixture had them agreeing and a sweep removed the sort with
    everything green.
    """
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "label"}).raise_for_status()
    values = offered(client, fx, setup)["region"]["values"]
    assert values == ["EU", "UK", "US"]


def test_the_watch_list_is_untouched_by_an_options_document(
    client: TestClient, fx: Fixture, setup
) -> None:
    """The set is not narrowed by anything in the form yet, so the options
    cannot change while somebody types and the form asks once. A watch list
    naming something would be a round trip per keystroke for nothing."""
    p = {"api_name": "region", "data_type": "string",
         "options_from": {"object_type_id": setup["region_type"],
                          "property": "label"}}
    assert filters.for_reader(p, may_edit=False)["dropdown_watches"] == []


# ---- p.33's filters over the options set (§336) ---------------------------------
def define_filtered(client, fx, setup, filters_doc, *, required=False, sub=None,
                    property_name="label"):
    return client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(sub or fx.editor_sub),
        json={"parameters": [
                  {"api_name": "tier", "display_name": "Tier",
                   "data_type": "string"},
                  {"api_name": "region", "display_name": "Region",
                   "data_type": "string", "required": required,
                   "options_from": {"object_type_id": setup["region_type"],
                                    "property": property_name},
                   "dropdown_filters": filters_doc},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "label", "parameter": "region"}}],
              "criteria": []},
    )


def test_a_static_filter_narrows_the_options(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.33's own first sentence: "**adding filters** to non-object reference
    multiple choice… parameters will determine the allowed values".

    The fixture's offices are US/gold, US/gold, US/silver, EU/gold, UK/silver —
    so the silver ones leave UK and US where the whole set leaves EU, UK and
    US. Both halves differ, which is what makes "narrowed" visible.
    """
    define_filtered(client, fx, setup, [
        {"property": "tier", "values": [{"kind": "value", "value": "silver"}]},
    ]).raise_for_status()
    assert offered(client, fx, setup)["region"]["values"] == ["UK", "US"]


def test_the_unfiltered_list_is_still_the_whole_set(
    client: TestClient, fx: Fixture, setup
) -> None:
    """Without this, "the filter narrows" passes for "the options are always
    one value"."""
    define_filtered(client, fx, setup, []).raise_for_status()
    assert offered(client, fx, setup)["region"]["values"] == ["EU", "UK", "US"]


def test_a_filter_reading_a_parameter_narrows_as_it_is_typed(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.36's second value kind over p.33's shape. The same compiled narrowing
    an object dropdown uses, because p.33 describes one filter vocabulary over
    two shapes and a second one here would be free to disagree."""
    define_filtered(client, fx, setup, [
        {"property": "tier", "values": [{"kind": "parameter", "parameter": "tier"}]},
    ]).raise_for_status()
    assert offered(client, fx, setup, {"tier": "silver"})["region"]["values"] == [
        "UK", "US",
    ]
    assert offered(client, fx, setup, {"tier": "gold"})["region"]["values"] == [
        "EU", "US",
    ]


def test_an_unfilled_filter_leaves_the_list_empty_and_names_the_box(
    client: TestClient, fx: Fixture, setup
) -> None:
    """The same empty-and-named answer an object dropdown gives: offering every
    value would offer exactly the ones the filter exists to exclude."""
    define_filtered(client, fx, setup, [
        {"property": "tier", "values": [{"kind": "parameter", "parameter": "tier"}]},
    ]).raise_for_status()
    offer = offered(client, fx, setup)["region"]
    assert offer["values"] == []
    assert offer["waiting_for"] == "tier"


def test_a_narrowed_list_narrows_the_check_too(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.34's rule for the other shape, read for this one: a list narrowed to
    EU and US beside a check that accepts UK as well is §214's control that
    looks like it works."""
    define_filtered(client, fx, setup, [
        {"property": "tier", "values": [{"kind": "value", "value": "gold"}]},
    ]).raise_for_status()
    assert run(client, fx, setup, {"region": "EU"}).status_code == 200
    refused = run(client, fx, setup, {"region": "UK"})
    assert refused.status_code == 422, refused.text
    assert "offers" in refused.text


def test_a_submission_that_does_not_supply_the_filters_box_is_refused(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**Fails closed**, as it does for an object dropdown: whether this value
    is in the set is a question nobody can answer without the box."""
    define_filtered(client, fx, setup, [
        {"property": "tier", "values": [{"kind": "parameter", "parameter": "tier"}]},
    ]).raise_for_status()
    refused = run(client, fx, setup, {"region": "US"})
    assert refused.status_code == 422, refused.text
    assert "tier" in refused.text


def test_a_blank_parameter_is_not_refused_for_a_filter_nothing_is_using(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**The refusal above, aimed at a value that does not exist** (§338).

    Nothing was chosen for Region, so whether Region's value is in the set is
    not a question this submission asks — and refusing on it makes an optional
    parameter's filter into a reason the whole action cannot run. The rule
    above still holds for the case it is about: a value *was* submitted and the
    set it must belong to cannot be worked out.

    `check_object_values` has always skipped an empty box before it looks at a
    rule; this is the same line for p.33's other shape, and a required
    parameter left blank is still refused by the check that is about
    requiredness.
    """
    # Its own definition rather than `define_filtered`'s, because the action
    # has to be able to write something without Region: a form whose only rule
    # reads the blank parameter is refused for having nothing to write, which
    # is a different refusal and would hide this one.
    client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [
                  {"api_name": "tier", "display_name": "Tier",
                   "data_type": "string"},
                  {"api_name": "note", "display_name": "Note",
                   "data_type": "string"},
                  {"api_name": "region", "display_name": "Region",
                   "data_type": "string",
                   "options_from": {"object_type_id": setup["region_type"],
                                    "property": "label"},
                   "dropdown_filters": [
                       {"property": "tier",
                        "values": [{"kind": "parameter", "parameter": "tier"}]}]},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "label", "parameter": "note"}}],
              "criteria": []},
    ).raise_for_status()
    got = run(client, fx, setup, {"note": "anything"})
    assert got.status_code == 200, got.text
    # **A cleared box, not an absent one**, which is what a form sends: every
    # parameter with the emptied one as `""`. The sweep found that only `None`
    # was being treated as nothing, so a submission from a real form would
    # still have been refused for a filter about the box it had just cleared.
    cleared = run(client, fx, setup, {"note": "anything", "region": ""})
    assert cleared.status_code == 200, cleared.text


@pytest.fixture(scope="module")
def crowded(client: TestClient, fx: Fixture, setup):
    """More distinct values than the control holds, so "offered" and "allowed"
    are different lists.

    One office per region and `MAX_OPTIONS + 10` of them, which makes the
    truncation *arbitrary* rather than principled: `group_object_set` orders by
    frequency, every value has a count of one, and the tie-break is alphabetical
    — so the values that fall off the end are simply the last ones by name, and
    every one of them is a value the set genuinely allows.
    """
    tag = uuid.uuid4().hex[:8]
    over = options.MAX_OPTIONS + 10
    type_id = a_type(
        client, fx, f"many{tag}",
        [(f"o{i:04d}", f"R{i:04d}") for i in range(over)],
        columns=("code", "label"),
    )
    return {"type": type_id, "over": over}


def test_a_value_past_the_controls_cap_is_still_accepted(
    client: TestClient, fx: Fixture, setup, crowded
) -> None:
    """**§256's trap, arriving through the back door** (§338).

    The check used to evaluate the set at `MAX_OPTIONS` and look for the
    submitted value in what came back, so the answer to "is this value allowed"
    depended on how many the *control* can hold — and the sentence it refused
    with, "is not one of the values it offers", was false about a value the set
    contains. §331 shipped exactly this for the object shape and §333 removed it
    by asking about the one object; this asks about the one value.
    """
    define(client, fx, setup,
           {"object_type_id": crowded["type"], "property": "label"},
           ).raise_for_status()
    offer = offered(client, fx, setup)["region"]
    assert offer["truncated"] is True
    every = {f"R{i:04d}" for i in range(crowded["over"])}
    missing = sorted(every - set(offer["values"]))
    # The fixture has to overflow or the test is about nothing.
    assert missing, offer["values"]

    accepted = run(client, fx, setup, {"region": missing[0]})
    assert accepted.status_code == 200, accepted.text
    # And still a check: a value no object has is refused, at the same cap.
    refused = run(client, fx, setup, {"region": "R9999"})
    assert refused.status_code == 422, refused.text
    assert "offers" in refused.text


def test_a_filter_is_checked_against_the_type_the_options_name(
    client: TestClient, fx: Fixture, setup
) -> None:
    """Not the action's own type, and not a guess: p.33's multiple choice has
    no `object_type_id` of its own, so the only type its filters can be written
    against is the one its options come from."""
    bad = define_filtered(client, fx, setup, [
        {"property": "no_such_property",
         "values": [{"kind": "value", "value": "x"}]},
    ])
    assert bad.status_code == 422, bad.text
    assert "no_such_property" in bad.text


def test_a_filtered_multiple_choice_parameter_is_watched(
    client: TestClient, fx: Fixture, setup
) -> None:
    """§332's rule: the filter is redacted and the box it reads is not, or a
    reader's form narrows once and then stops."""
    define_filtered(client, fx, setup, [
        {"property": "tier", "values": [{"kind": "parameter", "parameter": "tier"}]},
    ]).raise_for_status()
    read = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                      headers=hdr(fx.viewer_sub)).json()
    region = next(p for p in read["parameters"] if p["api_name"] == "region")
    assert region["dropdown_filters"] == []
    assert region["dropdown_watches"] == ["tier"]


def test_a_filter_on_a_parameter_with_no_options_is_still_refused(
    client: TestClient, fx: Fixture, setup
) -> None:
    """The gate widened to "or the type its options name", not to "anything
    goes": a string parameter with filters and no options document has nothing
    to filter, and the refusal says so."""
    bad = client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [
                  {"api_name": "region", "display_name": "Region",
                   "data_type": "string",
                   "dropdown_filters": [
                       {"property": "label",
                        "values": [{"kind": "value", "value": "EU"}]}]},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "label", "parameter": "region"}}],
              "criteria": []},
    )
    assert bad.status_code == 422, bad.text
    assert "which object type it offers" in bad.text


# ---- p.37's walk over the options set (§337) ------------------------------------
#
# **p.33's own word is "linked" and until §337 nothing could be.**
#
#     "…If only one **linked** object is available in the resulting object set
#      and the parameter is required, the parameter dropdown will automatically
#      prefill with the corresponding property value." (p.33)
#
# A multiple-choice parameter could name an object type and a property (§335)
# and narrow that type by a filter (§336), but "the resulting object set" was
# always every object of one type. p.33's sentence is about a set reached from
# somewhere — "display or prefill values based on properties of **a linked
# object**" — which is p.37's Search Around, and this is where the two meet.
@pytest.fixture(scope="module")
def linked(client: TestClient, fx: Fixture, setup):
    """p.37's example with a property read off the far end: employees, the
    issues raised by them, and the states those issues are in.

    **Three employees and deliberately uneven issues.** Ada's two issues are in
    two states, Grace's two are both open, and Hopper has none — so "the whole
    set", "narrowed to one value" and "narrowed to nothing" are three different
    answers a fixture with one employee could not tell apart.
    """
    tag = uuid.uuid4().hex[:8]
    employee = a_type(
        client, fx, f"emp{tag}",
        [("E1", "Ada"), ("E2", "Grace"), ("E3", "Hopper")],
        columns=("id", "name"),
    )
    issue = a_type(
        client, fx, f"iss{tag}",
        [("I1", "E1", "open"), ("I2", "E1", "closed"),
         ("I3", "E2", "open"), ("I4", "E2", "open")],
        columns=("id", "employee_id", "state"),
    )
    link = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"raised_by_{tag}", "display_name": "Raised by",
              "from_type_id": issue, "to_type_id": employee,
              "cardinality": "one_to_many",
              "from_property": "employee_id", "to_property": "$primary_key"},
    )
    assert link.status_code == 201, link.text
    people = {
        r["primary_key"]: r["id"]
        for r in client.get(f"{wbase(fx)}/object-types/{employee}/instances",
                            headers=hdr(fx.editor_sub)).json()["items"]
    }
    return {"employee": employee, "issue": issue, "link": link.json()["id"],
            "people": people}


def define_walked(client, fx, setup, linked, *, hops=None, start=None,
                  required=False, filters_doc=None, walked=True):
    """The action's `state` parameter, offering the states of the issues
    reached from whoever is in the `who` box."""
    source = None
    if walked:
        source = {
            "start": start or {"kind": "parameter",
                               "object_type_id": linked["employee"],
                               "parameter": "who"},
            "hops": [{"link_type_id": linked["link"]}] if hops is None else hops,
        }
    return client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [
                  {"api_name": "who", "display_name": "Who",
                   "data_type": "object", "object_type_id": linked["employee"]},
                  {"api_name": "state", "display_name": "State",
                   "data_type": "string", "required": required,
                   "options_from": {"object_type_id": linked["issue"],
                                    "property": "state"},
                   "dropdown_filters": filters_doc or [],
                   "dropdown_search_around": source},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "label", "parameter": "state"}}],
              "criteria": []},
    )


def states(client, fx, setup, values=None):
    return offered(client, fx, setup, values)["state"]


def test_a_walk_narrows_the_values_to_what_is_linked(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """p.37's sentence with a property read off the far end: "traversing a link
    on every object in the current set".

    Ada's issues are open and closed; Grace's are both open. Two starts, two
    answers — and neither is a coincidence of the data, because the unfiltered
    set below holds both values.
    """
    define_walked(client, fx, setup, linked).raise_for_status()
    ada = {"who": linked["people"]["E1"]}
    grace = {"who": linked["people"]["E2"]}
    assert states(client, fx, setup, ada)["values"] == ["closed", "open"]
    assert states(client, fx, setup, grace)["values"] == ["open"]


def test_without_the_walk_the_start_changes_nothing(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """The negative control the test above needs. Without it, "the walk
    narrows" passes for an options list that happens to answer differently for
    two different people — so this pins the *unwalked* answer, which is every
    state in the workspace whoever is in the box.
    """
    define_walked(client, fx, setup, linked, walked=False).raise_for_status()
    grace = {"who": linked["people"]["E2"]}
    assert states(client, fx, setup, grace)["values"] == ["closed", "open"]
    assert states(client, fx, setup)["values"] == ["closed", "open"]


def test_before_the_start_is_chosen_the_list_is_empty_and_names_the_box(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """p.37's own example before the employee is chosen. The same
    empty-and-named answer an object dropdown gives — one `Unresolved`, one
    `except`, so a walk starting nowhere and a filter reading nothing cannot
    drift into being answered differently."""
    define_walked(client, fx, setup, linked).raise_for_status()
    offer = states(client, fx, setup)
    assert offer["values"] == []
    assert offer["waiting_for"] == "who"


def test_a_walk_that_reaches_nothing_offers_nothing(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """**Not the same as an empty walk.** Hopper has no issues, so the set is
    genuinely empty — and reading the type unfiltered would offer every state
    in the workspace, which is the opposite of what a walk narrowing to none
    means. Empty and *not* waiting: there is nothing to fill in."""
    define_walked(client, fx, setup, linked).raise_for_status()
    offer = states(client, fx, setup, {"who": linked["people"]["E3"]})
    assert offer["values"] == []
    assert offer["waiting_for"] is None


def test_a_start_that_names_nothing_offers_nothing(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """**The other empty, and the sweep found it.** An id naming no object the
    caller can read is not "nobody has chosen yet": the walk starts from an
    empty set, so it reaches nothing and there is nothing to offer. Falling
    through to an unfiltered read would offer every state in the workspace —
    the silent widening decision 0002 exists to remove — and it is the only
    input that reaches that branch, because an employee who merely has no
    issues still gives the walk a join value to look for.

    `start_key_of`'s own docstring draws this line and nothing was asking it to
    hold. The submission is refused either way, by `check_object_values` and in
    a sentence about the box that actually holds the bad value.
    """
    define_walked(client, fx, setup, linked).raise_for_status()
    offer = states(client, fx, setup, {"who": str(uuid.uuid4())})
    assert offer["values"] == []
    assert offer["waiting_for"] is None


def test_p33s_linked_prefill(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """**p.33's own sentence, for the first time with something linked.**

    > "If only one linked object is available in the resulting object set and
    > the parameter is required, the parameter dropdown will automatically
    > prefill with the corresponding property value." (p.33)

    Grace's issues are both open, so there is one value and nothing to decide.
    Ada's are not, so there is — and the same parameter does not prefill.
    """
    define_walked(client, fx, setup, linked, required=True).raise_for_status()
    grace = states(client, fx, setup, {"who": linked["people"]["E2"]})
    assert grace["values"] == ["open"] and grace["prefill"] == "open"
    ada = states(client, fx, setup, {"who": linked["people"]["E1"]})
    assert ada["prefill"] is None


def test_a_filter_narrows_the_far_end_rather_than_the_start(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """p.34 names "filters **and Search Arounds**" in one breath, and the order
    matters: what shows up is the far end, so that is what a filter cuts. A
    filter applied to the starting set would be filtering Employees by a
    property of an Issue.

    **Both starts are asked on purpose.** Ada has a closed issue and Grace has
    none, so the filter and the walk each have to hold for the pair to differ —
    a version asking only Ada would pass with the walk ignored entirely, which
    is how the first draft of this test read.
    """
    define_walked(
        client, fx, setup, linked,
        filters_doc=[{"property": "state",
                      "values": [{"kind": "value", "value": "closed"}]}],
    ).raise_for_status()
    assert states(client, fx, setup,
                  {"who": linked["people"]["E1"]})["values"] == ["closed"]
    assert states(client, fx, setup,
                  {"who": linked["people"]["E2"]})["values"] == []


def test_the_walk_narrows_the_check_too(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """p.34's second sentence for p.33's other shape. A list narrowed to the
    states of Grace's issues beside a check that accepts `closed` as well is
    §214's control that looks like it works — with the extra insult of having
    offered the value it then rejects."""
    define_walked(client, fx, setup, linked).raise_for_status()
    grace = linked["people"]["E2"]
    assert run(client, fx, setup,
               {"who": grace, "state": "open"}).status_code == 200
    refused = run(client, fx, setup, {"who": grace, "state": "closed"})
    assert refused.status_code == 422, refused.text
    assert "offers" in refused.text

    # **And a value that is in the walked set without being the first of it**
    # (§338, and the sweep found it). Ada's two issues are one open and one
    # closed, so both counts are one and the tie-break is alphabetical — a
    # check that read the walked set at one bucket rather than asking about
    # this value would accept `closed` and refuse `open`, which is narrower
    # than the rule and wrong in the direction nobody notices until a form
    # refuses what it just offered.
    ada = linked["people"]["E1"]
    assert run(client, fx, setup,
               {"who": ada, "state": "open"}).status_code == 200


def test_the_check_carries_the_filters_as_well_as_the_walk(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """**Both narrowings on the submit path, which the sweep found was one.**

    The filters ride on the walk's outermost set rather than beside it — the
    compiled definition carries them, and the resolver hands them back — so a
    check built from a walk with no filters on it silently accepts everything
    the walk reaches. Ada has an open issue and a closed one, and the filter
    leaves only the closed one, so `open` is exactly the value that separates
    "narrowed by both" from "narrowed by the walk alone".
    """
    define_walked(
        client, fx, setup, linked,
        filters_doc=[{"property": "state",
                      "values": [{"kind": "value", "value": "closed"}]}],
    ).raise_for_status()
    ada = linked["people"]["E1"]
    assert run(client, fx, setup,
               {"who": ada, "state": "closed"}).status_code == 200
    refused = run(client, fx, setup, {"who": ada, "state": "open"})
    assert refused.status_code == 422, refused.text
    assert "offers" in refused.text


def test_a_submission_that_does_not_supply_the_walks_start_is_refused(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """**Fails closed**, as it does for a filter and for an object dropdown:
    the walk starts from a box nothing supplied, so whether this value is in
    the set is a question nobody can answer, and accepting on an unanswered
    question is how a value the rule exists to exclude gets written."""
    define_walked(client, fx, setup, linked).raise_for_status()
    refused = run(client, fx, setup, {"state": "open"})
    assert refused.status_code == 422, refused.text
    assert "who" in refused.text


def test_a_walk_landing_somewhere_other_than_the_options_type_is_refused(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """The refusal the save-time check exists for, read against the type the
    *options* name. With no hops the walk stops on the employee, whose
    properties are not where `state` lives, so every value offered would be
    refused a moment after somebody picked it."""
    bad = define_walked(client, fx, setup, linked, hops=[])
    assert bad.status_code == 422, bad.text
    assert "different object type" in bad.text


def test_a_walk_on_a_parameter_with_nothing_to_offer_is_still_refused(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """The landing type widened to "or the type its options name", not to
    "anything goes": a plain string parameter has no set for a walk to land
    on, and the refusal says so."""
    bad = client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [
                  {"api_name": "who", "display_name": "Who",
                   "data_type": "object", "object_type_id": linked["employee"]},
                  {"api_name": "state", "display_name": "State",
                   "data_type": "string",
                   "dropdown_search_around": {
                       "start": {"kind": "parameter",
                                 "object_type_id": linked["employee"],
                                 "parameter": "who"},
                       "hops": [{"link_type_id": linked["link"]}]}},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "label", "parameter": "state"}}],
              "criteria": []},
    )
    assert bad.status_code == 422, bad.text
    assert "where it is meant to land" in bad.text


def test_a_reader_watches_the_walks_start_without_being_told_the_walk(
    client: TestClient, fx: Fixture, setup, linked
) -> None:
    """§332's rule, which this shape inherits rather than repeats: the walk is
    redacted for somebody who may not edit the action (p.40-41) and the box it
    starts from is not, or a reader's form narrows once and then stops."""
    define_walked(client, fx, setup, linked).raise_for_status()
    read = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                      headers=hdr(fx.viewer_sub)).json()
    state = next(p for p in read["parameters"] if p["api_name"] == "state")
    assert state["dropdown_search_around"] is None
    assert state["dropdown_watches"] == ["who"]
