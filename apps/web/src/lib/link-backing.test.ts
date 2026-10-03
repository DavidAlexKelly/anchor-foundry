import { describe, expect, it } from "vitest";

import type { LinkType, ObjectInstance } from "@platform/types";
import {
  NO_BACKING, backingDescription, backingDraftOf, backingFor, backingLinksFor, backingPayload, backingProblem,
} from "./link-backing";
import { linkSubsetHref } from "./link-subset";
import { sortedLinkQuery } from "../components/canvas/links-widget";

/** p.197's backing object type in the link dialogs and the Links panel (§667). */

const link = (id: string, from: string, to: string, pair = true) =>
  ({ id, from_object_type_id: from, to_object_type_id: to, from_property: pair ? "a" : null,
    to_property: pair ? "b" : null, display_name: id }) as unknown as LinkType;

const obj = (key: string, properties: Record<string, unknown>) =>
  ({ id: `i-${key}`, primary_key: key, properties }) as unknown as ObjectInstance;

describe("p.199's prerequisite links", () => {
  it("offers the links joining an end and the backing type on a pair, either way round", () => {
    const links = [link("m_air", "manifest", "aircraft"), link("air_m", "aircraft", "manifest"),
      link("m_flight", "manifest", "flight"), link("loose", "manifest", "aircraft", false),
      link("other", "aircraft", "flight")];
    expect(backingLinksFor(links, "aircraft", "manifest").map((l) => l.id)).toEqual(["m_air", "air_m"]);
    expect(backingLinksFor(links, "flight", "manifest").map((l) => l.id)).toEqual(["m_flight"]);
    expect(backingLinksFor(links, "", "manifest")).toEqual([]);
    expect(backingLinksFor(links, "aircraft", "")).toEqual([]);
  });
});

describe("the backing a dialog holds", () => {
  const draft = { type: "manifest", fromLink: "m_air", toLink: "m_flight" };

  it("says what is missing or wrong, in order", () => {
    expect(backingProblem(NO_BACKING, "aircraft", "flight")).toBe("Choose the backing object type.");
    expect(backingProblem({ ...draft, type: "aircraft" }, "aircraft", "flight"))
      .toBe("The backing object type is a third type, between the link's two ends.");
    expect(backingProblem({ ...draft, type: "flight" }, "aircraft", "flight"))
      .toBe("The backing object type is a third type, between the link's two ends.");
    expect(backingProblem({ ...draft, toLink: "" }, "aircraft", "flight"))
      .toBe("Choose the link from the backing type to each end.");
    expect(backingProblem({ ...draft, fromLink: "" }, "aircraft", "flight"))
      .toBe("Choose the link from the backing type to each end.");
    expect(backingProblem({ ...draft, toLink: "m_air" }, "aircraft", "flight"))
      .toBe("Each end needs its own link to the backing type.");
    expect(backingProblem(draft, "aircraft", "flight")).toBeNull();
  });

  it("sends all three or none, and reads back what a link has", () => {
    expect(backingPayload(draft)).toEqual({ backing_type_id: "manifest", backing_from_link_id: "m_air",
      backing_to_link_id: "m_flight" });
    expect(backingPayload({ ...draft, toLink: "" })).toEqual({ backing_type_id: null, backing_from_link_id: null,
      backing_to_link_id: null });
    expect(backingPayload(null).backing_type_id).toBeNull();
    expect(backingDraftOf({ backing_type_id: "manifest", backing_from_link_id: "m_air", backing_to_link_id: null }))
      .toEqual({ type: "manifest", fromLink: "m_air", toLink: "" });
    expect(backingDraftOf({})).toEqual(NO_BACKING);
  });

  it("describes a backed link, and one that lost a backing link", () => {
    expect(backingDescription({ backing_type_id: "m", backing_display_name: "Flight Manifest",
      backing_from_link_id: "a", backing_to_link_id: "b" })).toBe("backed by Flight Manifest");
    expect(backingDescription({ backing_type_id: "m", backing_display_name: "Flight Manifest",
      backing_from_link_id: null, backing_to_link_id: "b" })).toBe("not traversable - a backing link was deleted");
    expect(backingDescription({ backing_type_id: "m", backing_display_name: "Flight Manifest",
      backing_from_link_id: "a", backing_to_link_id: null })).toBe("not traversable - a backing link was deleted");
    expect(backingDescription({ backing_type_id: "m", backing_from_link_id: "a", backing_to_link_id: "b" }))
      .toBe("backed by an object type");
    expect(backingDescription({ backing_type_id: null })).toBeNull();
  });
});

describe("the Links panel's backing objects (p.199)", () => {
  const manifests = [obj("M1", { flight: "F1", pilot: "Ada" }), obj("M2", { flight: "F2", pilot: "Grace" }),
    obj("M3", { flight: null, pilot: "Alan" })];
  const group = { far_property: "$primary_key", backing_far_property: "flight", backing_items: manifests };

  it("gives each linked object the backing objects naming it", () => {
    expect(backingFor(group, obj("F2", {})).map((m) => m.primary_key)).toEqual(["M2"]);
    expect(backingFor(group, obj("F9", {}))).toEqual([]);
    // The far object's own value of the far property, where that is not its key.
    const byCode = { ...group, far_property: "code", backing_far_property: "flight" };
    expect(backingFor(byCode, obj("x", { code: "F1" })).map((m) => m.primary_key)).toEqual(["M1"]);
    expect(backingFor(byCode, obj("y", { code: null }))).toEqual([]);
    expect(backingFor({ far_property: "$primary_key" }, obj("F1", {}))).toEqual([]);
    const keyed = { ...group, backing_far_property: "$primary_key" };
    expect(backingFor(keyed, obj("M3", {})).map((m) => m.primary_key)).toEqual(["M3"]);
  });

  it("opens a subset through backing objects only as a set, and sorts them by a hop from the near property", () => {
    const backed = { far_type_id: "flight", far_property: "$primary_key", matched_value: "1",
                     backed: true, link_type_id: "flew", side_name: "Flights" };
    // No property match can say these objects; §793's set from the object can.
    expect(linkSubsetHref("ws", backed)).toBeNull();
    const query = sortedLinkQuery({ ...backed, link_type_id: "flew", near_property: "tail" }, "name_asc", "aircraft");
    expect(query).toEqual({ sort: "name_asc", definition: { object_type_id: "flight", via: { link_type_id: "flew",
      base: { object_type_id: "aircraft", filters: [{ property: "tail", op: "eq", value: "1" }] } } } });
  });
});
