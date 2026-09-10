import { describe, expect, it } from "vitest";

import {
  EXPLORER_KINDS,
  emptyReason,
  kindLabel,
  needsWorkspaceLevel,
  ofKind,
  openHref,
  sections,
  shouldSearch,
  subtitle,
} from "./explorer";
import type { Resource, ResourceKind } from "./types";

function resource(over: Partial<Resource> & { name: string }): Resource {
  return {
    id: "res-1",
    workspace_id: "ws-1",
    project_id: "proj-1",
    kind: "dataset",
    description: "",
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("what the Explorer offers", () => {
  it("lists datasets and object types, and not the four other kinds", () => {
    expect(EXPLORER_KINDS).toEqual(["dataset", "object_type"]);
  });

  it("reaches past the project, because object types are not in one", () => {
    // The rule this buys: `project_id` is null for an object type, so a
    // project-scoped listing would show an empty section in every project.
    expect(needsWorkspaceLevel(EXPLORER_KINDS)).toBe(true);
  });

  it("stops reaching past the project when object types are not asked for", () => {
    // Derived rather than hard-coded: narrowing the panel has to narrow the
    // request too, or the panel goes on paying for rows it does not draw.
    expect(needsWorkspaceLevel(["dataset"])).toBe(false);
  });
});

describe("opening a resource", () => {
  it("links by id", () => {
    expect(openHref(resource({ name: "orders", id: "res-9" }))).toBe("/r/res-9");
  });

  it("does not link by the name that is sitting right beside the button", () => {
    // The mistake that looks correct: a dataset's name is what a declaration
    // uses, so it is on screen and to hand.
    expect(openHref(resource({ name: "orders", id: "res-9" }))).not.toContain("orders");
  });
});

describe("what a row says", () => {
  it("shows the description when there is one", () => {
    expect(subtitle(resource({ name: "orders", description: "One row per order" })))
      .toBe("One row per order");
  });

  it("says nothing rather than repeating the heading", () => {
    expect(subtitle(resource({ name: "orders" }))).toBeNull();
    expect(subtitle(resource({ name: "orders", description: "   " }))).toBeNull();
  });

  it("names the two kinds as headings", () => {
    expect(kindLabel("dataset")).toBe("Datasets");
    expect(kindLabel("object_type")).toBe("Object types");
  });
});

describe("when to ask the server", () => {
  it("asks for everything when nothing is typed", () => {
    expect(shouldSearch("")).toBe(false);
    expect(shouldSearch("   ")).toBe(false);
  });

  it("does not treat one character as a search", () => {
    expect(shouldSearch("o")).toBe(false);
  });

  it("searches from two characters", () => {
    expect(shouldSearch("or")).toBe(true);
    expect(shouldSearch("  or  ")).toBe(true);
  });
});

describe("the empty state tells the three absences apart", () => {
  it("says nothing at all when there is something to show", () => {
    expect(emptyReason(3, "")).toBeNull();
    expect(emptyReason(3, "orders")).toBeNull();
  });

  it("blames the search when there was one", () => {
    expect(emptyReason(0, "orders")).toBe("Nothing here matches orders.");
  });

  it("names what it trimmed, so the message quotes what was typed", () => {
    expect(emptyReason(0, "  orders  ")).toBe("Nothing here matches orders.");
  });

  it("explains the project instead when nothing was searched for", () => {
    const said = emptyReason(0, "");
    expect(said).toContain("No datasets or object types yet");
    expect(said).not.toContain("matches");
  });

  it("treats a one-character query as no search, so the message matches", () => {
    // `shouldSearch` decides both what is sent and what the empty state
    // blames. If those two disagreed, a single character would produce an
    // unfiltered list under a message saying nothing matched it.
    expect(emptyReason(0, "o")).not.toContain("matches");
  });
});

describe("the rows", () => {
  const rows = [
    resource({ name: "zebra", id: "a" }),
    resource({ name: "orders", id: "b" }),
    resource({ name: "Customer", id: "c", kind: "object_type", project_id: null }),
    resource({ name: "apples", id: "d" }),
  ];

  it("keeps only the kind asked for", () => {
    expect(ofKind(rows, "object_type").map((r) => r.name)).toEqual(["Customer"]);
  });

  it("sorts by name rather than keeping the server's order", () => {
    // The listing arrives most-recently-updated first, which is right for a
    // resource browser and wrong here: this panel is read to find a name you
    // already know.
    expect(ofKind(rows, "dataset").map((r) => r.name)).toEqual([
      "apples",
      "orders",
      "zebra",
    ]);
  });

  it("sorts without regard to case, so a capital is not banished to the top", () => {
    const mixed = [resource({ name: "beta" }), resource({ name: "Alpha" })];
    expect(ofKind(mixed, "dataset").map((r) => r.name)).toEqual(["Alpha", "beta"]);
  });
});

describe("the sections", () => {
  it("draws both kinds in order, with their headings", () => {
    const drawn = sections([resource({ name: "orders" })]);
    expect(drawn.map((s) => s.kind)).toEqual(["dataset", "object_type"]);
    expect(drawn.map((s) => s.label)).toEqual(["Datasets", "Object types"]);
  });

  it("keeps a section that has nothing in it", () => {
    // "This project has no object types" and "this panel does not do object
    // types" look identical when the heading is missing, and only one of them
    // is something the reader can act on.
    const drawn = sections([resource({ name: "orders" })]);
    expect(drawn[1]!.rows).toEqual([]);
    expect(drawn).toHaveLength(2);
  });

  it("puts each resource under its own heading", () => {
    const drawn = sections([
      resource({ name: "orders" }),
      resource({ name: "Customer", kind: "object_type", project_id: null }),
    ]);
    expect(drawn[0]!.rows.map((r) => r.name)).toEqual(["orders"]);
    expect(drawn[1]!.rows.map((r) => r.name)).toEqual(["Customer"]);
  });

  it("ignores a kind the Explorer does not offer, even when the server sends one", () => {
    // The server is asked for two kinds; if it ever answered with more, the
    // panel must not quietly grow a third section.
    const drawn = sections([
      resource({ name: "orders" }),
      resource({ name: "some-app", kind: "canvas_app" as ResourceKind }),
    ]);
    expect(drawn.flatMap((s) => s.rows).map((r) => r.name)).toEqual(["orders"]);
  });
});
