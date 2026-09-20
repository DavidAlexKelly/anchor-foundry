import { describe, expect, it } from "vitest";

import {
  type AccessResource,
  type ModuleAccess,
  byKind,
  label,
  met,
  moduleReason,
  moduleVerdict,
  shortfalls,
  summary,
} from "./check-access";

function resource(over: Partial<AccessResource> = {}): AccessResource {
  return { kind: "object_type", id: "id-1", name: "Customer", status: "visible", ...over };
}

function answer(over: Partial<ModuleAccess> = {}): ModuleAccess {
  return {
    user: { id: "u1", email: "reader@example.com", display_name: "Reader" },
    workspace_role: "viewer",
    project_role: "viewer",
    can_open: true,
    can_edit: false,
    resources: [],
    ...over,
  };
}

describe("met", () => {
  it("counts only a resource the user can actually use", () => {
    expect(met("visible")).toBe(true);
  });

  it("does not count an action they can see and cannot run", () => {
    // p.92's warning in one assertion. A widget that draws is the trap this
    // panel exists to spring early, so `unusable` reading as met would make
    // the panel agree with the broken page.
    expect(met("unusable")).toBe(false);
  });

  it("does not count a resource that is hidden or missing", () => {
    expect(met("hidden")).toBe(false);
    expect(met("unknown")).toBe(false);
  });
});

describe("shortfalls", () => {
  it("lists every requirement that is not met", () => {
    const rows = [
      resource({ id: "a", status: "visible" }),
      resource({ id: "b", status: "unusable" }),
      resource({ id: "c", status: "hidden" }),
      resource({ id: "d", status: "unknown" }),
    ];
    expect(shortfalls(rows).map((r) => r.id)).toEqual(["b", "c", "d"]);
  });

  it("keeps a dangling reference in the list", () => {
    // Not a complaint about the user - nobody meets it - but a module with a
    // widget pointing at a deleted type is not fine, and dropping the row
    // would let it report itself so.
    const rows = [resource({ id: "gone", name: null, status: "unknown" })];
    expect(shortfalls(rows)).toHaveLength(1);
  });
});

describe("label", () => {
  it("uses the name when there is one", () => {
    expect(label(resource({ name: "Orders" }))).toBe("Orders");
  });

  it("falls back to the id only when nobody could name it", () => {
    expect(label(resource({ name: null, id: "7f3a" }))).toBe("7f3a");
  });
});

describe("byKind", () => {
  it("orders the kinds the way p.92 lists them", () => {
    const rows = [
      resource({ kind: "action_type", id: "a" }),
      resource({ kind: "link_type", id: "l" }),
      resource({ kind: "object_type", id: "o" }),
    ];
    expect(byKind(rows).map((r) => r.kind)).toEqual([
      "object_type", "link_type", "action_type",
    ]);
  });

  it("orders within a kind by the name a reader sees", () => {
    const rows = [
      resource({ id: "1", name: "Zebra" }),
      resource({ id: "2", name: "Apple" }),
    ];
    expect(byKind(rows).map((r) => r.name)).toEqual(["Apple", "Zebra"]);
  });

  it("leaves the answer it was given alone", () => {
    const rows = [resource({ kind: "action_type", id: "a" }), resource({ id: "o" })];
    byKind(rows);
    expect(rows.map((r) => r.id)).toEqual(["a", "o"]);
  });
});

describe("moduleVerdict", () => {
  it("separates editing from opening", () => {
    expect(moduleVerdict(answer({ can_open: true, can_edit: true })))
      .toBe("Can open and edit this module");
    expect(moduleVerdict(answer({ can_open: true, can_edit: false })))
      .toBe("Can open this module, and not edit it");
  });

  it("says plainly when they cannot open it", () => {
    expect(moduleVerdict(answer({ can_open: false, can_edit: false })))
      .toBe("Cannot open this module");
  });
});

describe("moduleReason", () => {
  it("names the project role when they have one", () => {
    expect(moduleReason(answer({ project_role: "editor" })))
      .toBe("editor on this project");
  });

  it("says publishing is what lets them in when no role does", () => {
    // The two things a builder could change, and which one is carrying them.
    const reason = moduleReason(answer({
      project_role: null, workspace_role: "viewer", can_open: true,
    }));
    expect(reason).toContain("no role on this project");
    expect(reason).toContain("published");
  });

  it("does not credit publishing when they cannot open it", () => {
    const reason = moduleReason(answer({
      project_role: null, workspace_role: "viewer", can_open: false,
    }));
    expect(reason).not.toContain("published");
  });

  it("reports the workspace when they are not in it", () => {
    expect(moduleReason(answer({
      project_role: null, workspace_role: null, can_open: false,
    }))).toBe("no role on this workspace");
  });
});

describe("summary", () => {
  it("counts what is unmet against what is needed", () => {
    expect(summary(answer({
      resources: [
        resource({ id: "a", status: "visible" }),
        resource({ id: "b", status: "unusable" }),
        resource({ id: "c", status: "hidden" }),
      ],
    }))).toBe("2 of 3 data requirements unmet.");
  });

  it("says so when everything is met", () => {
    expect(summary(answer({ resources: [resource(), resource({ id: "b" })] })))
      .toBe("Meets all 2 data requirements.");
  });

  it("uses the singular for one requirement", () => {
    expect(summary(answer({ resources: [resource()] })))
      .toBe("Meets all 1 data requirement.");
  });

  it("does not report a module with no requirements as meeting them", () => {
    // §226: an aggregation over an empty set answers nothing, not zero. "Meets
    // all 0 requirements" reads as a pass, and a module that reads no ontology
    // was never asking for one.
    expect(summary(answer({ resources: [] })))
      .toBe("This module needs no ontology access.");
  });
});
