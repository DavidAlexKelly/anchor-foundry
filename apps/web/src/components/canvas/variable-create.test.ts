import { describe, expect, it } from "vitest";

import {
  canCreateFrom, duplicate, fromCurrent, nextLabel, settingsOn, UNIQUE_SETTINGS,
} from "./variable-create";
import type { WorkshopVariable } from "../../lib/types";

/** p.73's Duplicate and New-variable-from-current. */

const v = (id: string, extra: Partial<WorkshopVariable> = {}): WorkshopVariable =>
  ({ id, kind: "string", label: id, ...extra } as WorkshopVariable);

const module_ = (...vars: WorkshopVariable[]): Record<string, WorkshopVariable> =>
  Object.fromEntries(vars.map((x) => [x.id, x]));

describe("UNIQUE_SETTINGS", () => {
  it("names the three features an external ID carries", () => {
    // §3.4's "one mechanism, three features" (p.163, p.198, p.202). A fourth
    // feature added to that mechanism without landing here is a setting a
    // duplicate would drop and never mention.
    expect(Object.keys(UNIQUE_SETTINGS).sort())
      .toEqual(["interface", "routing", "state_saving"]);
  });
});

describe("settingsOn", () => {
  it("reports nothing for a plain variable", () => {
    expect(settingsOn(v("a"))).toEqual([]);
  });

  it("reports each of the three when it is on", () => {
    const all = v("a", {
      external_id: "a",
      interface: {},
      url_behavior: "always",
      save_state: true,
    } as never);
    expect(settingsOn(all).sort()).toEqual(["interface", "routing", "state_saving"]);
  });

  it("does not call an explicit 'never' routing", () => {
    // `url_behavior: "never"` is the absence of routing written down, and the
    // server's own parse returns early on it. Reporting it as a dropped
    // setting would tell an author they lost something they never had.
    expect(settingsOn(v("a", { url_behavior: "never" } as never))).toEqual([]);
  });
});

describe("nextLabel", () => {
  it("adds the suffix when nothing is using it", () => {
    expect(nextLabel(module_(v("a", { label: "Region" })), "Region")).toBe("Region copy");
  });

  it("numbers from two, not from one", () => {
    // One copy of one thing is "Region copy". The number is what a *second*
    // copy needs, so it appears when it is needed rather than on every copy so
    // that the second one can be "Region copy 2".
    const vars = module_(v("a", { label: "Region" }), v("b", { label: "Region copy" }));
    expect(nextLabel(vars, "Region")).toBe("Region copy 2");
  });

  it("keeps counting past a gap", () => {
    const vars = module_(
      v("a", { label: "Region" }),
      v("b", { label: "Region copy" }),
      v("c", { label: "Region copy 2" }),
    );
    expect(nextLabel(vars, "Region")).toBe("Region copy 3");
  });

  it("treats labels differing only in case as taken", () => {
    // Two rows that differ only in case read as the same row in a list, which
    // is the thing this function exists to avoid.
    const vars = module_(v("a", { label: "Region" }), v("b", { label: "REGION COPY" }));
    expect(nextLabel(vars, "Region")).toBe("Region copy 2");
  });

  it("ignores surrounding whitespace on both sides of the comparison", () => {
    const vars = module_(v("a", { label: "Region" }), v("b", { label: "  Region copy  " }));
    expect(nextLabel(vars, "  Region  ")).toBe("Region copy 2");
  });

  it("takes the suffix as an argument", () => {
    // "copy" for a duplicate, "narrowed" for a set built on another - the two
    // buttons make different things and a label saying "copy" for a derived
    // set would be wrong about what it is.
    expect(nextLabel(module_(v("a", { label: "All" })), "All", "narrowed"))
      .toBe("All narrowed");
  });
});

describe("duplicate", () => {
  it("returns null for a variable that is not there", () => {
    expect(duplicate(module_(v("a")), "nope", "new")).toBeNull();
  });

  it("carries what the variable is", () => {
    const source = v("a", {
      kind: "array",
      label: "Clauses",
      element: "string",
      default: ["x"],
      recompute: "only_on_event",
    } as never);
    const out = duplicate(module_(source), "a", "new")!;
    expect(out.variable.kind).toBe("array");
    expect(out.variable.element).toBe("string");
    expect(out.variable.default).toEqual(["x"]);
    expect(out.variable.recompute).toBe("only_on_event");
  });

  it("carries a derivation, so a copy of a derived variable is derived", () => {
    // A copy of a computed thing is a computed thing. The inputs point at
    // *other* variables by id and those are untouched, so the copy reads the
    // same sources - which is what "duplicate" means.
    const source = v("b", {
      derivation: { transform: "concat", inputs: ["a"] },
    } as never);
    const out = duplicate(module_(v("a"), source), "b", "new")!;
    expect(out.variable.derivation).toEqual({ transform: "concat", inputs: ["a"] });
  });

  it("carries an object set definition", () => {
    const source = v("a", {
      kind: "object_set",
      object_set: { object_type_id: "t1", filters: [] },
    } as never);
    const out = duplicate(module_(source), "a", "new")!;
    expect(out.variable.object_set).toEqual({ object_type_id: "t1", filters: [] });
  });

  it("takes the new id it is given and a label nothing else uses", () => {
    const out = duplicate(module_(v("a", { label: "Region" })), "a", "v_new")!;
    expect(out.variable.id).toBe("v_new");
    expect(out.variable.label).toBe("Region copy");
  });

  it("drops the external ID", () => {
    // **The server refuses two variables sharing one**
    // (`_refuse_duplicate_external_ids`), so a copy that kept it would be a
    // copy the module cannot save - and the 422 would name a variable the
    // author did not edit.
    const source = v("a", { external_id: "region" } as never);
    const out = duplicate(module_(source), "a", "new")!;
    expect(out.variable.external_id).toBeUndefined();
  });

  it("drops everything the external ID carried, and says which", () => {
    // The cascade is the point. Routing without an external ID is refused
    // (p.198), interface membership without one is refused, a saved state
    // without one has no key (p.203) - so the three flags cannot survive the
    // ID's removal, and an author who is not told loses them silently.
    const source = v("a", {
      label: "Region",
      external_id: "region",
      interface: { required: false },
      url_behavior: "always",
      save_state: true,
    } as never);
    const out = duplicate(module_(source), "a", "new")!;
    expect(out.variable.interface).toBeUndefined();
    expect(out.variable.url_behavior).toBeUndefined();
    expect(out.variable.save_state).toBeUndefined();
    expect(out.dropped.sort()).toEqual(["interface", "routing", "state_saving"]);
  });

  it("reports nothing dropped when there was nothing on", () => {
    // So the panel can stay quiet. A note listing an empty set of losses is
    // noise on the common case.
    expect(duplicate(module_(v("a")), "a", "new")!.dropped).toEqual([]);
  });

  it("reports only the settings that were actually on", () => {
    const source = v("a", { external_id: "region", save_state: true } as never);
    expect(duplicate(module_(source), "a", "new")!.dropped).toEqual(["state_saving"]);
  });

  it("drops the legacy name", () => {
    // It records what this variable was called in the v1 document this app was
    // converted from. A copy made today was never that parameter, and two
    // variables claiming to be it makes the conversion record ambiguous in the
    // one direction it exists to keep clear.
    const source = v("a", { legacy_name: "region" } as never);
    expect(duplicate(module_(source), "a", "new")!.variable.legacy_name).toBeUndefined();
  });

  it("leaves the original alone", () => {
    const source = v("a", { external_id: "region", save_state: true } as never);
    const vars = module_(source);
    duplicate(vars, "a", "new");
    expect(vars.a!.external_id).toBe("region");
    expect(vars.a!.save_state).toBe(true);
  });
});

describe("canCreateFrom", () => {
  it("is object sets only, per p.73", () => {
    expect(canCreateFrom(v("a", { kind: "object_set" } as never))).toBe(true);
    expect(canCreateFrom(v("a", { kind: "string" } as never))).toBe(false);
  });

  it("refuses a time series set", () => {
    // A series is read *through* an object (p.76) and is not an object set, so
    // there is no set for a new variable to take as its input.
    expect(canCreateFrom(v("a", { kind: "time_series_set" } as never))).toBe(false);
  });

  it("refuses nothing at all", () => {
    expect(canCreateFrom(undefined)).toBe(false);
  });
});

describe("fromCurrent", () => {
  const source = v("a", {
    kind: "object_set",
    label: "All orders",
    object_set: { object_type_id: "t1", filters: [] },
  } as never);

  it("refuses anything that is not an object set", () => {
    expect(fromCurrent(module_(v("a", { kind: "string" } as never)), "a", "new")).toBeNull();
    expect(fromCurrent(module_(source), "missing", "new")).toBeNull();
  });

  it("references the source rather than copying it", () => {
    // **The difference between this button and Duplicate.** p.73: "maintaining
    // a reference to the source variable" - so the new set has no object set
    // definition of its own, and changing the source's filters moves this one
    // too.
    const out = fromCurrent(module_(source), "a", "new")!;
    expect(out.derivation?.inputs).toEqual(["a"]);
    expect(out.object_set).toBeUndefined();
  });

  it("makes an object set narrowed from the source", () => {
    const out = fromCurrent(module_(source), "a", "new")!;
    expect(out.kind).toBe("object_set");
    expect(out.derivation?.transform).toBe("filter_set");
    expect(out.derivation?.config).toEqual({ op: "eq" });
  });

  it("lands with the value slot still empty", () => {
    // Half configured on purpose: the same state the panel's own "Is another
    // set, narrowed" option produces. Guessing a property to make it savable
    // immediately would invent a filter nobody asked for.
    const out = fromCurrent(module_(source), "a", "new")!;
    expect(out.derivation?.inputs).toHaveLength(1);
  });

  it("names itself after the source without claiming to be a copy", () => {
    expect(fromCurrent(module_(source), "a", "new")!.label).toBe("All orders narrowed");
  });

  it("does not collide with a label already in the module", () => {
    const vars = module_(source, v("b", { label: "All orders narrowed" }));
    expect(fromCurrent(vars, "a", "new")!.label).toBe("All orders narrowed 2");
  });

  it("carries no external ID or settings", () => {
    // It is a new variable, not a copy - there is nothing to carry, and the
    // three settings each need an ID the author has not chosen yet.
    const out = fromCurrent(module_(source), "a", "new")!;
    expect(out.external_id).toBeUndefined();
    expect(out.interface).toBeUndefined();
    expect(out.save_state).toBeUndefined();
  });
});
