/**
 * p.30's "all resources that are related to the one you are currently
 * viewing" (§603), for an object type. `ontology-manager` pages are `p.N`.
 */
import { describe as group, expect, test } from "vitest";

import type { LinkType } from "./types";
import { relatedResources } from "./related-resources";

const TYPE = "t-order";

function link(over: Partial<LinkType>): LinkType {
  return {
    id: "l",
    api_name: "link",
    display_name: "Link",
    cardinality: "many_to_one",
    from_object_type_id: TYPE,
    from_display_name: "Order",
    to_object_type_id: "t-customer",
    to_display_name: "Customer",
    created_at: "2026-01-01T00:00:00Z",
    from_property: null,
    to_property: null,
    ...over,
  } as LinkType;
}

function prop(api_name: string, shared: string | null = null, display_name = "") {
  return {
    api_name,
    display_name,
    shared_property_id: shared,
    shared_property_api_name: shared ? `shared_${shared}` : null,
  };
}

const none = { id: TYPE, properties: [] };

group("p.30's related resources", () => {
  test("nothing related is no sections at all", () => {
    expect(relatedResources(none, [], [], [], [])).toEqual([]);
  });

  test("a link type opens the type at its other end, either way round", () => {
    const [links] = relatedResources(
      none,
      [
        link({ id: "out", display_name: "Placed by" }),
        link({
          id: "in",
          display_name: "Invoices",
          from_object_type_id: "t-invoice",
          from_display_name: "Invoice",
          to_object_type_id: TYPE,
          to_display_name: "Order",
        }),
        link({ id: "else", from_object_type_id: "t-a", to_object_type_id: "t-b" }),
      ],
      [],
      [],
      [],
    );
    expect(links).toEqual({
      title: "Link types",
      entries: [
        { key: "out", label: "Placed by", via: "to Customer", to: { open: "object_type", id: "t-customer" } },
        { key: "in", label: "Invoices", via: "from Invoice", to: { open: "object_type", id: "t-invoice" } },
      ],
    });
  });

  test("a link to itself says so and opens nothing", () => {
    const [links] = relatedResources(
      none,
      [link({ id: "self", display_name: "", api_name: "parent", to_object_type_id: TYPE })],
      [],
      [],
      [],
    );
    expect(links!.entries).toEqual([{ key: "self", label: "parent", via: "to itself", to: null }]);
  });

  test("actions on this type, not on others and not on interfaces", () => {
    const [actions] = relatedResources(
      none,
      [],
      [
        { id: "a1", api_name: "close", display_name: "Close order", object_type_id: TYPE },
        { id: "a2", api_name: "other", display_name: "", object_type_id: "t-customer" },
        { id: "a3", api_name: "iface", display_name: "", object_type_id: null },
        { id: "a4", api_name: "reopen", display_name: "", object_type_id: TYPE },
      ],
      [],
      [],
    );
    expect(actions).toEqual({
      title: "Action types",
      entries: [
        { key: "a1", label: "Close order", via: null, to: { open: "action_type", id: "a1" } },
        { key: "a4", label: "reopen", via: null, to: { open: "action_type", id: "a4" } },
      ],
    });
  });

  test("interfaces and groups open themselves", () => {
    const sections = relatedResources(
      none,
      [],
      [],
      [{ interface_id: "i1", api_name: "inspectable", display_name: "", property_mapping: {} }],
      [{ id: "g1", api_name: "sales", display_name: "Sales" }],
    );
    expect(sections).toEqual([
      {
        title: "Interfaces",
        entries: [{ key: "i1", label: "inspectable", via: null, to: { open: "interface", id: "i1" } }],
      },
      {
        title: "Groups",
        entries: [{ key: "g1", label: "Sales", via: null, to: { open: "group", id: "g1" } }],
      },
    ]);
  });

  test("a shared property is listed once however many properties use it", () => {
    const [shared] = relatedResources(
      {
        id: TYPE,
        properties: [
          prop("placed", "s1", "Placed"),
          prop("plain"),
          prop("shipped", "s1"),
          prop("region", "s2", "Region"),
        ],
      },
      [],
      [],
      [],
      [],
    );
    expect(shared).toEqual({
      title: "Shared properties",
      entries: [
        { key: "s1", label: "shared_s1", via: "as Placed, shipped", to: { open: "shared_property", id: "s1" } },
        { key: "s2", label: "shared_s2", via: "as Region", to: { open: "shared_property", id: "s2" } },
      ],
    });
  });

  test("sections keep their order", () => {
    const titles = relatedResources(
      { id: TYPE, properties: [prop("x", "s1")] },
      [link({})],
      [{ id: "a", api_name: "a", display_name: "", object_type_id: TYPE }],
      [{ interface_id: "i", api_name: "i", display_name: "", property_mapping: {} }],
      [{ id: "g", api_name: "g", display_name: "" }],
    ).map((s) => s.title);
    expect(titles).toEqual(["Link types", "Action types", "Interfaces", "Shared properties", "Groups"]);
  });
});
