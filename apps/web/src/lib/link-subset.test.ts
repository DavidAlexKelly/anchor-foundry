/**
 * Opening a link's far side in the Explorer (Foundry `object-views` p.11).
 *
 * The rule is a URL, and a URL is exactly the kind of thing a browser test
 * confirms *navigated somewhere* while a unit test says where.
 */
import { describe, expect, it } from "vitest";

import { decodeSet, encodeSet, linkSubsetHref } from "./link-subset";

const GROUP: Parameters<typeof linkSubsetHref>[1] = {
  link_type_id: "L1",
  side_name: "Aircraft",
  far_type_id: "11111111-1111-1111-1111-111111111111",
  far_property: "customer_id",
  matched_value: "C1",
};

describe("linkSubsetHref", () => {
  it("filters the far type by the join, in the Explorer's own vocabulary", () => {
    expect(linkSubsetHref("acme", GROUP)).toBe(
      "/acme/explore?type=11111111-1111-1111-1111-111111111111" +
        "&property=customer_id&value=C1",
    );
  });

  it("passes the primary-key reference through untouched", () => {
    // The explore route maps the sentinel to "the instance's key, not one of
    // its properties". Rewriting it here would be a second spelling of a
    // reserved name, free to disagree with the one that already exists.
    expect(linkSubsetHref("acme", { ...GROUP, far_property: "$primary_key" }))
      .toContain("property=%24primary_key");
  });

  it("escapes a value that would otherwise break the query string", () => {
    expect(linkSubsetHref("acme", { ...GROUP, matched_value: "a&b c" }))
      .toContain("value=a%26b+c");
  });

  it("compares as text, because the join does", () => {
    // `instance_store.join_key` promises text-to-text. A number encoded any
    // other way here would disagree with the comparison it feeds.
    expect(linkSubsetHref("acme", { ...GROUP, matched_value: 42 })).toContain("value=42");
  });

  it("has nowhere to send anyone when the object has no value to join on", () => {
    // The group already says so on screen ("No customer_id on this object, so
    // this link points at nothing"). A URL here would filter on `undefined`
    // and return an empty page — a link that looks like it worked.
    expect(linkSubsetHref("acme", { ...GROUP, matched_value: null })).toBeNull();
    expect(linkSubsetHref("acme", { ...GROUP, matched_value: undefined })).toBeNull();
  });

  it("opens a link through a join table as the set a traversal reaches (§793)", () => {
    // `matched_value` is this object's own key, which the far objects do not
    // hold: a match on it would open the wrong objects, or none.
    expect(linkSubsetHref("acme", { ...GROUP, join_table: true })).toBeNull();
    const href = linkSubsetHref("acme", { ...GROUP, join_table: true },
                                { typeId: "T0", key: "F1" })!;
    const url = new URL(href, "http://x");
    expect(url.pathname).toBe("/acme/explore");
    expect(url.searchParams.get("type")).toBe(GROUP.far_type_id);
    expect(url.searchParams.get("set_label")).toBe("Aircraft of F1");
    expect(url.searchParams.get("property")).toBeNull();
    expect(decodeSet(url.searchParams.get("set"))).toEqual({
      object_type_id: GROUP.far_type_id,
      via: { link_type_id: "L1", base: { object_type_id: "T0",
        filters: [{ property: "$primary_key", op: "eq", value: "F1" }] } },
    });
    // Through backing objects too (§666).
    expect(linkSubsetHref("acme", { ...GROUP, backed: true }, { typeId: "T0", key: "F1" }))
      .toContain("set=");
    expect(linkSubsetHref("acme", { ...GROUP, join_table: false })).not.toBeNull();
  });

  it("carries a set through a URL and back, whatever its characters", () => {
    // "ÿÿÿ" is chosen because its base64 holds a "/", which the URL-safe
    // alphabet spells "_" and has to be read back.
    const definition = { object_type_id: "T", note: "é ünïcode ?&=/+ ÿÿÿ" };
    const encoded = encodeSet(definition);
    expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(encoded).toContain("_");
    expect(decodeSet(encoded)).toEqual(definition);
    expect(decodeSet(null)).toBeNull();
    expect(decodeSet("not base64 at all!")).toBeNull();
    expect(decodeSet(encodeSet({ no: "type" }))).toBeNull();
    expect(decodeSet(encodeSet(null))).toBeNull();
  });

  // There is deliberately no case for "the link type has no join": the
  // instance-links endpoint returns only traversable links, so `far_property`
  // is a plain string and a guard for it would be a branch no test could
  // reach.
});
