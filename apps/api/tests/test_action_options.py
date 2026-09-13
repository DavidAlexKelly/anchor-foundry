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
    csv = f"{header}\n" + "".join(f"{a},{b}\n" for a, b in rows)
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
    region_type = a_type(client, fx, f"reg{tag}", [
        ("o1", "EU"), ("o2", "UK"), ("o3", "US"), ("o4", "EU"),
    ])
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
    """The store returns the most common values first so a cap keeps the ones
    somebody is most likely to want; what survives is sorted so the control
    does not reshuffle when the data shifts underneath it. `EU` is the most
    common label in this fixture and it is not first by frequency alone."""
    define(client, fx, setup, {"object_type_id": setup["region_type"],
                               "property": "label"}).raise_for_status()
    values = offered(client, fx, setup)["region"]["values"]
    assert values == sorted(values)


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
