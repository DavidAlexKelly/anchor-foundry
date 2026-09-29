import { describe as group, expect, it } from "vitest";

import type { OntologyChange } from "@/lib/types";
import { describe, details, mergedByAuthor } from "./ontology-history";

function change(over: Partial<OntologyChange> = {}): OntologyChange {
  return {
    id: 1, action: "object_type.update", resource_type: "object_type", resource_id: "t1",
    resource_name: "Flight", metadata: {}, user_id: "u1", user_name: "Ada",
    created_at: "2026-09-29T00:00:00Z", ...over,
  };
}

group("each change as a sentence (p.8)", () => {
  it("says what was done to what", () => {
    expect(describe(change())).toBe("Edited object type Flight");
    expect(describe(change({ action: "interface.create", resource_name: "Located" })))
      .toBe("Created interface Located");
    expect(describe(change({ action: "object_type.set_interfaces" })))
      .toBe("Changed the interfaces of object type Flight");
    expect(describe(change({ action: "action_type.set_sections", resource_name: "Move" })))
      .toBe("Changed the form of action type Move");
    expect(describe(change({ action: "value_type.version", resource_name: "Email" })))
      .toBe("Changed the rule of value type Email");
  });

  it("names a deleted resource by its kind", () => {
    expect(describe(change({ action: "interface.delete", resource_name: null })))
      .toBe("Deleted an interface");
    expect(describe(change({ action: "link_type.update", resource_name: null })))
      .toBe("Edited a link type since deleted");
    expect(describe(change({ action: "link_type.delete", resource_name: "flies" })))
      .toBe("Deleted link type flies");
  });

  it("says an import was into the ontology, and reads an action it has no word for", () => {
    expect(describe(change({ action: "ontology.import", resource_name: null })))
      .toBe("Imported a file into the ontology");
    expect(describe(change({ action: "object_type.set_colour_wheel" })))
      .toBe("Changed (set colour wheel) object type Flight");
    expect(describe(change({ action: "new_kind.create", resource_name: "X" })))
      .toBe("Created new kind X");
  });
});

group("the details (p.8)", () => {
  it("lists what the record holds, in order", () => {
    expect(details({ properties: 2, api_name: "flight", acknowledged_breaking: false }))
      .toEqual(["acknowledged breaking: false", "api name: flight", "properties: 2"]);
    expect(details({})).toEqual([]);
  });
});

group("merging by author (p.8)", () => {
  it("joins one author's run, keeping time order", () => {
    const runs = mergedByAuthor([
      change({ id: 5, user_id: "u1" }), change({ id: 4, user_id: "u1" }),
      change({ id: 3, user_id: "u2", user_name: "Grace" }), change({ id: 2, user_id: "u1" }),
    ]);
    expect(runs.map((r) => [r.user_name, r.changes.map((c) => c.id)])).toEqual([
      ["Ada", [5, 4]], ["Grace", [3]], ["Ada", [2]]]);
    expect(mergedByAuthor([])).toEqual([]);
  });
});
