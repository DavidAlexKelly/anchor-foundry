/** §515: p.28's arrow keys, previews and Enter in the ontology search. */
import { describe, expect, it } from "vitest";

import { nextIndex, previewRows } from "./search-keys";
import type { OntologySearchHit } from "./types";

describe("nextIndex", () => {
  it("moves down and up, stopping at the ends", () => {
    expect(nextIndex(0, 3, "ArrowDown")).toBe(1);
    expect(nextIndex(2, 3, "ArrowDown")).toBe(2);
    expect(nextIndex(2, 3, "ArrowUp")).toBe(1);
    expect(nextIndex(0, 3, "ArrowUp")).toBe(0);
  });

  it("keeps the selection inside a list that shrank, and at zero for none", () => {
    expect(nextIndex(4, 2, "Shift")).toBe(1);
    expect(nextIndex(1, 3, "Shift")).toBe(1);
    expect(nextIndex(3, 0, "ArrowDown")).toBe(0);
  });
});

describe("previewRows", () => {
  const hit = (extra: Partial<OntologySearchHit>): OntologySearchHit => ({
    kind: "property", id: "p1", api_name: "status", display_name: "Status",
    object_type_id: "t1", object_type_name: "Ticket", usage_count: null,
    matched_field: "name", matched_value: "Status", ...extra,
  });

  it("says what a hit is, why it matched and where it lives", () => {
    expect(previewRows(hit({}))).toEqual([
      ["Kind", "Property"], ["Name", "Status"], ["API name", "status"],
      ["Matched", "name: Status"], ["On", "Ticket"],
    ]);
  });

  it("gives an ownerless kind its usage instead of an owner", () => {
    const rows = previewRows(hit({
      kind: "shared_property", object_type_id: null, object_type_name: "", usage_count: 0,
      display_name: "",
    }));
    expect(rows).toContainEqual(["Used by", "0"]);
    expect(rows.map((r) => r[0])).not.toContain("On");
    // A blank display name falls back to the api_name.
    expect(rows).toContainEqual(["Name", "status"]);
  });

  it("gives a function its versions, which is what its count is (§777)", () => {
    const rows = previewRows(hit({
      kind: "function", object_type_id: null, object_type_name: "", usage_count: 2 }));
    expect(rows).toContainEqual(["Versions", "2"]);
    expect(rows.map((r) => r[0])).not.toContain("Used by");
  });
});
