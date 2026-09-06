"""Interfaces in the Ontology Manager (parity `docs/parity/ontology.md` §1.2;
Foundry `object-link-types` p.4, p.53; `ontology` p.60-62).

§251 built the resource, §252 put it in ontology search and in the object type
listing's API. Neither of those could be non-empty, because nothing in the
browser could declare an interface or claim one. This is somebody doing both.

**The claim that needs a browser is p.66's mapping.** An interface's promise is
that several object types share a shape *while differing in everything else*
(p.60), and the sharpest form of that is a type whose column is called
something else entirely - p.61's Vehicle with `last_checked` rather than
`lastInspectionDate`. An API test can post that mapping; only a browser test
can show that the dialog offers the right column, refuses to save until the
required promise is answered, and then says on the type's own row what it now
claims to be.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

VEHICLES = [
    {"id": "V1", "name": "Truck", "checked_on": "2026-01-04"},
    {"id": "V2", "name": "Van", "checked_on": "2026-02-11"},
]


@pytest.fixture(scope="module")
def module(api):
    vehicles = Module(api, "Interfaces")
    vehicles.object_type(
        columns=["id", "name", "checked_on"], rows=VEHICLES, key="id", title="name",
        types={"checked_on": "date"},
    )
    return vehicles


def open_objects(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    # `exact=True` for `test_value_types.open_objects`'s reason: the project is
    # named after the section this test is looking for, so the breadcrumb's
    # heading matches by substring too.
    expect(
        page.get_by_role("heading", name="Interfaces", exact=True)
    ).to_be_visible(timeout=30000)


def declare(page, module, *, name: str, properties: list[tuple[str, str, bool]]) -> str:
    """p.60's shape, through the dialog. Returns the API name it settled on."""
    open_objects(page, module)
    page.get_by_test_id("new-interface").click()
    page.get_by_test_id("iface-name").fill(name)
    for i, (display, data_type, required) in enumerate(properties, start=1):
        page.get_by_test_id("iface-add-property").click()
        page.get_by_role("textbox", name=f"Property {i} name").fill(display)
        page.get_by_role("combobox", name=f"Property {i} type").select_option(data_type)
        if not required:
            page.get_by_role("checkbox", name=f"Property {i} required").uncheck()
    api_name = page.get_by_test_id("iface-api-name").input_value()
    page.get_by_test_id("iface-save").click()
    expect(page.get_by_test_id("iface-table")).to_contain_text(api_name, timeout=15000)
    return api_name


def test_an_interface_is_declared_and_says_nothing_implements_it_yet(page, module):
    """p.61's argument for modelling `Inspectable` is that you can then look at
    the types that share the shape. One that nothing implements has not done
    that yet, and the row says so in words rather than reporting a zero."""
    name = f"Inspectable {uuid.uuid4().hex[:4]}"
    api_name = declare(page, module, name=name, properties=[
        ("Last inspection date", "date", True),
        ("Inspection status", "string", True),
    ])
    expect(page.get_by_test_id(f"iface-props-{api_name}")).to_have_text("2")
    expect(page.get_by_test_id(f"iface-impls-{api_name}")).to_have_text("Nothing yet")


def test_the_api_name_follows_the_display_name_the_way_p60_names_one(page, module):
    """`Schedulable Resource` becomes `SchedulableResource`, not
    `schedulable_resource`. An interface is "an Ontology type" (p.4), so it is
    named like one - and this is the single place where an interface name and
    an object type name appear together, on a type's implements line."""
    open_objects(page, module)
    page.get_by_test_id("new-interface").click()
    page.get_by_test_id("iface-name").fill("Schedulable Resource")
    expect(page.get_by_test_id("iface-api-name")).to_have_value("SchedulableResource")


def test_struct_is_not_offered_as_an_interface_property_type(page, module):
    """`check_implementation` compares base types, and a struct's promise is
    its *fields* - so an interface declaring one would be satisfied by any
    struct at all. The type is absent from the dropdown rather than accepted
    and unenforced (§214).

    Presence before absence: the assertion that `date` is on the list is what
    stops this passing against an empty dropdown."""
    open_objects(page, module)
    page.get_by_test_id("new-interface").click()
    page.get_by_test_id("iface-add-property").click()
    options = page.get_by_role("combobox", name="Property 1 type").locator("option")
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert "date" in labels, labels
    assert "struct" not in labels, labels


def test_a_type_implements_a_shape_through_a_column_of_another_name(page, module):
    """**p.66's mapping, which is the whole reason an interface is not a name
    match.** The seeded type's date column is `checked_on`; the interface asks
    for `last_inspection_date`. p.60's argument is that types satisfy one
    interface while differing in everything else, and what they call things is
    part of everything else.

    The dialog opens with nothing mapped - the names do not agree, and a
    suggestion built on a coincidence would be worse than none - so it also
    shows what a required promise looks like before it is answered."""
    name = f"Inspectable {uuid.uuid4().hex[:4]}"
    api_name = declare(page, module, name=name, properties=[
        ("Last inspection date", "date", True),
        ("Inspection status", "string", True),
    ])

    page.get_by_role("button", name=f"Implement {api_name}").click()
    page.get_by_test_id("impl-type").select_option(label=f"Seed {module.tag}")

    rows = page.get_by_test_id("impl-rows")
    expect(rows).to_be_visible(timeout=15000)
    # Nothing suggested, because nothing agreed by name.
    expect(page.get_by_test_id("impl-missing")).to_contain_text("last_inspection_date")
    expect(page.get_by_test_id("impl-save")).to_be_disabled()

    # Only the date column is offered for the date property. Presence and
    # absence together, so an empty select cannot pass this.
    date_options = page.get_by_role(
        "combobox", name="Answered by for last_inspection_date"
    ).locator("option")
    labels = [date_options.nth(i).inner_text() for i in range(date_options.count())]
    assert "checked_on" in labels, labels
    assert "name" not in labels, labels

    page.get_by_role(
        "combobox", name="Answered by for last_inspection_date"
    ).select_option("checked_on")
    page.get_by_role(
        "combobox", name="Answered by for inspection_status"
    ).select_option("name")
    expect(page.get_by_test_id("impl-save")).to_be_enabled()
    page.get_by_test_id("impl-save").click()

    expect(page.get_by_test_id(f"iface-impls-{api_name}")).to_have_text(
        "1 object type", timeout=15000
    )
    # §252's column, on the row it describes.
    expect(page.get_by_test_id(f"type-interfaces-seed_{module.tag}")).to_contain_text(
        name
    )


def test_an_implemented_interface_cannot_be_deleted_out_from_under_the_type(
    page, module
):
    """Deliberately unlike p.185's shared property, which reverts its users to
    ordinary properties. An interface is a claim other resources are written
    against, so the refusal names the type rather than performing the change."""
    name = f"Inspectable {uuid.uuid4().hex[:4]}"
    api_name = declare(page, module, name=name, properties=[
        ("Last inspection date", "date", True),
    ])
    page.get_by_role("button", name=f"Implement {api_name}").click()
    page.get_by_test_id("impl-type").select_option(label=f"Seed {module.tag}")
    page.get_by_role(
        "combobox", name="Answered by for last_inspection_date"
    ).select_option("checked_on")
    page.get_by_test_id("impl-save").click()
    expect(page.get_by_test_id(f"iface-impls-{api_name}")).to_have_text(
        "1 object type", timeout=15000
    )

    page.get_by_role("button", name=f"Delete {api_name}").click()
    expect(page.get_by_test_id("iface-delete-error")).to_contain_text(
        f"Seed {module.tag}", timeout=15000
    )
    expect(page.get_by_test_id("iface-table")).to_contain_text(api_name)


def test_claiming_a_second_shape_does_not_withdraw_the_first(page, module):
    """**The endpoint replaces the whole list**, so a dialog that sent only the
    claim it was editing would silently un-implement everything else the type
    said about itself — and nothing would say so, because the type would simply
    stop appearing under the other interface.

    Found by a mutant: removing the line that sends the other claims back
    survived a suite where no type had ever claimed two shapes.
    """
    first_name = f"Inspectable {uuid.uuid4().hex[:4]}"
    first = declare(page, module, name=first_name,
                    properties=[("Last inspection date", "date", True)])
    second = declare(page, module, name=f"Trackable {uuid.uuid4().hex[:4]}",
                     properties=[("Tracking tag", "string", True)])

    page.get_by_role("button", name=f"Implement {first}").click()
    page.get_by_test_id("impl-type").select_option(label=f"Seed {module.tag}")
    page.get_by_role(
        "combobox", name="Answered by for last_inspection_date"
    ).select_option("checked_on")
    page.get_by_test_id("impl-save").click()
    expect(page.get_by_test_id(f"iface-impls-{first}")).to_have_text(
        "1 object type", timeout=15000
    )

    page.get_by_role("button", name=f"Implement {second}").click()
    page.get_by_test_id("impl-type").select_option(label=f"Seed {module.tag}")
    page.get_by_role(
        "combobox", name="Answered by for tracking_tag"
    ).select_option("name")
    page.get_by_test_id("impl-save").click()

    expect(page.get_by_test_id(f"iface-impls-{second}")).to_have_text(
        "1 object type", timeout=15000
    )
    # The claim that would have gone silently.
    expect(page.get_by_test_id(f"iface-impls-{first}")).to_have_text("1 object type")
    expect(
        page.get_by_test_id(f"type-interfaces-seed_{module.tag}")
    ).to_contain_text(first_name)


def test_an_active_interface_offers_no_delete_button(page, module):
    """p.256's status gate, on the control rather than in the response.

    An interface has a status like every other ontology resource, and until
    §253 nothing consulted it — the gate is in `delete_interface` now, and this
    is the half a person meets first. The whole rule is one value on the row,
    so the button is disabled rather than left to fail."""
    name = f"Inspectable {uuid.uuid4().hex[:4]}"
    api_name = declare(page, module, name=name,
                       properties=[("Last inspection date", "date", True)])
    # Presence before absence: it is deletable at the default status.
    expect(page.get_by_role("button", name=f"Delete {api_name}")).to_be_enabled()

    page.get_by_role("button", name=f"Edit {api_name}").click()
    page.get_by_test_id("status-select").select_option("active")
    page.get_by_test_id("iface-save").click()

    expect(page.get_by_test_id("iface-table")).to_contain_text("active", timeout=15000)
    expect(page.get_by_role("button", name=f"Delete {api_name}")).to_be_disabled()

    # Back to experimental, so the run's sweep can take it: a cleanup that
    # cannot remove what a test deliberately made undeletable leaves one more
    # of these in the workspace on every run, which is §209's problem again.
    page.get_by_role("button", name=f"Edit {api_name}").click()
    page.get_by_test_id("status-select").select_option("experimental")
    page.get_by_test_id("iface-save").click()
    expect(page.get_by_role("button", name=f"Delete {api_name}")).to_be_enabled(
        timeout=15000
    )


def test_the_implementing_types_answer_one_question_together(page, module):
    """**p.61's argument, on screen.** "Target the interface directly. A single
    workflow covers all implementing types."

    Two object types, two differently named date columns, one heading. The
    assertion that matters is that neither column name appears: the table is
    keyed by what the *interface* calls the property, which is what makes it
    one question rather than two.
    """
    name = f"Inspectable {uuid.uuid4().hex[:4]}"
    api_name = declare(page, module, name=name, properties=[
        ("Last inspection date", "date", True),
    ])
    page.get_by_role("button", name=f"Implement {api_name}").click()
    page.get_by_test_id("impl-type").select_option(label=f"Seed {module.tag}")
    page.get_by_role(
        "combobox", name="Answered by for last_inspection_date"
    ).select_option("checked_on")
    page.get_by_test_id("impl-save").click()
    expect(page.get_by_test_id(f"iface-impls-{api_name}")).to_contain_text(
        "1 object type", timeout=15000
    )

    page.get_by_role("button", name=f"Objects of {api_name}").click()
    rows = page.get_by_test_id("objects-rows")
    expect(rows).to_be_visible(timeout=20000)

    # The seeded type's column is `checked_on`; the heading is the interface's.
    #
    # **Lowercased before comparing**, because `.table th` is
    # `text-transform: uppercase` and `inner_text` returns what is rendered.
    # Asserting the display name verbatim compares against the stylesheet.
    headings = rows.locator("thead th")
    labels = [
        headings.nth(i).inner_text().lower() for i in range(headings.count())
    ]
    assert "last inspection date" in labels, labels
    assert "checked_on" not in labels, labels

    # Both seeded rows, with the date under the interface's column.
    expect(rows.locator("tbody tr")).to_have_count(len(VEHICLES))
    expect(rows).to_contain_text("2026-01-04")
    # And the summary names the type that answered, which is the half of
    # "2 objects" that says an interface did something.
    expect(page.get_by_test_id("objects-summary")).to_contain_text(
        f"Seed {module.tag}"
    )


def test_an_interface_nothing_implements_offers_nothing_to_open(page, module):
    """§214 on the count itself: a button that opened an empty dialog is worse
    than a label, because it looks like there is something behind it."""
    name = f"Trackable {uuid.uuid4().hex[:4]}"
    api_name = declare(page, module, name=name, properties=[("Tag", "string", True)])
    expect(page.get_by_test_id(f"iface-impls-{api_name}")).to_have_text("Nothing yet")
    expect(
        page.get_by_role("button", name=f"Objects of {api_name}")
    ).to_have_count(0)


def test_an_interface_cannot_be_offered_as_its_own_parent(page, module):
    """p.53 allows any number of parents; a circle is refused by the server,
    which names the path it followed. The one cycle a list of summaries can
    see is self-extension, and it is the one most likely to be clicked by
    accident, so it is absent from the checkboxes rather than refused."""
    name = f"Trackable {uuid.uuid4().hex[:4]}"
    api_name = declare(page, module, name=name, properties=[("Tag", "string", True)])

    page.get_by_role("button", name=f"Edit {api_name}").click()
    boxes = page.get_by_test_id("iface-extends")
    expect(boxes).to_be_visible(timeout=15000)
    # Presence before absence again: other interfaces from earlier tests in
    # this module are on the list, so an empty box cannot pass either half.
    assert boxes.locator("input[type=checkbox]").count() > 0
    expect(boxes.get_by_role("checkbox", name=f"Extend {api_name}")).to_have_count(0)


def test_an_inherited_shape_is_shown_resolved(page, module):
    """p.62's "extend interfaces for multi-level abstraction". The listing
    shows what an interface *declares*, because that is what an edit changes;
    the editor shows what it *amounts to*, because that is what an
    implementation is checked against. Both, in the two places each answers."""
    parent_name = f"Trackable {uuid.uuid4().hex[:4]}"
    parent = declare(page, module, name=parent_name, properties=[
        ("Tracking tag", "string", True),
    ])
    child_name = f"Schedulable {uuid.uuid4().hex[:4]}"
    child = declare(page, module, name=child_name, properties=[
        ("Scheduled for", "date", True),
    ])

    page.get_by_role("button", name=f"Edit {child}").click()
    page.get_by_test_id("iface-extends").get_by_role(
        "checkbox", name=f"Extend {parent}"
    ).check()
    page.get_by_test_id("iface-save").click()

    # The row still reports its own one declaration.
    expect(page.get_by_test_id(f"iface-props-{child}")).to_have_text("1", timeout=15000)

    page.get_by_role("button", name=f"Edit {child}").click()
    expect(page.get_by_test_id("iface-effective")).to_contain_text("2 properties")
    expect(page.get_by_test_id("iface-effective")).to_contain_text("tracking_tag")
