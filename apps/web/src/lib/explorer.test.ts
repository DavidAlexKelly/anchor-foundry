import { describe, expect, it } from "vitest";

import {
  EXPLORER_KINDS,
  canInsert,
  emptyReason,
  insertLabel,
  suggestedAlias,
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

describe("offering Insert", () => {
  it("offers it for the two languages that declare", () => {
    expect(canInsert("src/daily.sql")).toBe(true);
    expect(canInsert("src/daily.py")).toBe(true);
  });

  it("does not offer it where the server would only refuse", () => {
    // §214: a control that looks like it works is worse than one that is
    // absent.
    expect(canInsert("README.md")).toBe(false);
    expect(canInsert("repoSettings.json")).toBe(false);
  });

  it("does not offer it when no file is open", () => {
    expect(canInsert(undefined)).toBe(false);
  });

  it("is not fooled by the suffix appearing inside the name", () => {
    expect(canInsert("src/py.notes")).toBe(false);
    expect(canInsert("src/sql.txt")).toBe(false);
  });
});

describe("the alias suggested for a dataset", () => {
  it("passes a name that is already a usable variable through", () => {
    expect(suggestedAlias("orders")).toBe("orders");
    expect(suggestedAlias("raw_orders_2024")).toBe("raw_orders_2024");
  });

  it("replaces what an alias may not hold, because the server refuses it", () => {
    // `_WRITABLE_ALIAS` is letters, digits and underscore; a dataset name may
    // also hold dots and dashes. Suggesting one that will be refused would
    // make the common case an error message.
    expect(suggestedAlias("raw-orders")).toBe("raw_orders");
    expect(suggestedAlias("sales.daily")).toBe("sales_daily");
  });

  it("prefixes a leading digit rather than dropping it", () => {
    // `024_totals` is a different thing that looks like a typo.
    expect(suggestedAlias("2024_totals")).toBe("d_2024_totals");
  });

  it("trims the separators off the ends", () => {
    expect(suggestedAlias("-orders-")).toBe("orders");
  });

  it("always suggests something usable", () => {
    // A name made entirely of characters an alias may not hold would leave
    // nothing, and an empty alias is refused by the server.
    expect(suggestedAlias("---")).toBe("input");
    expect(suggestedAlias("")).toBe("input");
  });
});

describe("what the Insert button says", () => {
  it("names the line it will write, in the file's own comment prefix", () => {
    expect(insertLabel("orders", "src/daily.sql")).toBe("Insert -- input: orders");
    expect(insertLabel("orders", "src/daily.py")).toBe("Insert # input: orders");
  });

  it("names the alias, which is the half being chosen", () => {
    // The dataset was chosen by clicking the row; the alias is the name the
    // query will use, and a button saying only "Insert" would be asking
    // somebody to accept a variable name they never saw.
    expect(insertLabel("o", "src/daily.sql")).toContain("o");
  });
});
