import { describe, expect, it } from "vitest";

import {
  DEFAULT_SECONDS, MIN_SECONDS, OFF, applyNow, changed, intervalMs, registrable,
  running, settingsOf, stamp, watchedTypes,
} from "./auto-refresh";

/** p.576-580's auto-refresh. */

const ON = {
  enabled: true, seconds: 30, disable_in_edit: true, variables: ["v_sites"],
};

describe("reading a stored setting", () => {
  it("is off for anything unusable", () => {
    // §212, and the safe direction is not a matter of taste here: the thing
    // being dropped polls a server on a timer, so a malformed setting must
    // render without polling rather than poll on a schedule nobody chose.
    for (const raw of [null, undefined, [], "on", 7, true]) {
      expect(settingsOf(raw)).toEqual(OFF);
    }
  });

  it("is off unless enabled is exactly true", () => {
    expect(settingsOf({ enabled: "yes", variables: ["v"] }).enabled).toBe(false);
    expect(settingsOf({ variables: ["v"] }).enabled).toBe(false);
    expect(settingsOf(ON).enabled).toBe(true);
  });

  it("holds p.577's floor under the interval", () => {
    // "The current minimum, or most frequent, refresh rate is 10 seconds."
    expect(settingsOf({ ...ON, seconds: 1 }).seconds).toBe(MIN_SECONDS);
    expect(settingsOf({ ...ON, seconds: -5 }).seconds).toBe(MIN_SECONDS);
    expect(settingsOf({ ...ON, seconds: "30" }).seconds).toBe(DEFAULT_SECONDS);
    expect(settingsOf({ ...ON, seconds: 30 }).seconds).toBe(30);
    expect(settingsOf({ ...ON, seconds: 30.9 }).seconds).toBe(30);
    // And again at the point of use, so a document that reached the widget by
    // some other path cannot poll faster than Foundry's own number.
    expect(intervalMs({ ...OFF, seconds: 1 })).toBe(MIN_SECONDS * 1000);
    expect(intervalMs({ ...OFF, seconds: 45 })).toBe(45_000);
  });

  it("treats an absent edit-mode setting as disabled in edit mode", () => {
    // p.578 offers it as a thing a builder switches *off*, so a document that
    // predates the setting should not start refreshing somebody's canvas
    // while they are building on it.
    expect(settingsOf({ ...ON, disable_in_edit: undefined }).disable_in_edit).toBe(true);
    expect(settingsOf({ ...ON, disable_in_edit: false }).disable_in_edit).toBe(false);
  });

  it("keeps only the registrations that are variable ids", () => {
    expect(settingsOf({ ...ON, variables: ["a", "", 3, null, "b"] }).variables)
      .toEqual(["a", "b"]);
    expect(settingsOf({ ...ON, variables: "a" }).variables).toEqual([]);
  });
});

describe("whether the module is polling", () => {
  it("needs the switch, a registration, and the right mode", () => {
    expect(running(settingsOf(ON), "run")).toBe(true);
    expect(running(settingsOf({ ...ON, enabled: false }), "run")).toBe(false);
    // **A registration, not just the switch.** p.576's feature is "register
    // object sets… to be watched"; with none registered there is nothing to
    // ask about, and polling would be a request per interval for no answer.
    expect(running(settingsOf({ ...ON, variables: [] }), "run")).toBe(false);
  });

  it("honours p.578's disable in edit mode, in both directions", () => {
    expect(running(settingsOf(ON), "edit")).toBe(false);
    // "Auto-refresh will remain configured and active in view mode with this
    // setting enabled" — so the same module still runs when viewed.
    expect(running(settingsOf(ON), "run")).toBe(true);
    // And switching it off means it runs in the builder too.
    expect(running(settingsOf({ ...ON, disable_in_edit: false }), "edit")).toBe(true);
  });
});

describe("which object types are watched", () => {
  const resolved = {
    v_sites: { object_type_id: "type-a", filters: [] },
    v_also_sites: { object_type_id: "type-a", filters: [{ property: "x" }] },
    v_orders: { object_type_id: "type-b", filters: [] },
    v_unresolved: undefined,
  };

  it("is the type behind each registered set", () => {
    // p.579's boundary: a registered set watches its own type and nothing it
    // links to.
    expect(watchedTypes(settingsOf({ ...ON, variables: ["v_orders"] }), resolved))
      .toEqual(["type-b"]);
  });

  it("counts two sets over one type once, in a stable order", () => {
    expect(watchedTypes(
      settingsOf({ ...ON, variables: ["v_also_sites", "v_orders", "v_sites"] }),
      resolved,
    )).toEqual(["type-a", "type-b"]);
  });

  it("ignores a registration that resolves to nothing", () => {
    // An unresolved set is not an empty one (§210), and polling for a type
    // nobody named would be watching at random.
    expect(watchedTypes(
      settingsOf({ ...ON, variables: ["v_unresolved", "v_gone"] }), resolved,
    )).toEqual([]);
  });
});

describe("the watermark", () => {
  const a = { object_type_id: "t1", updated_at: "2026-01-01T00:00:00Z", count: 2 };
  const b = { object_type_id: "t2", updated_at: null, count: 0 };

  it("does not depend on the order the server answered in", () => {
    expect(stamp([a, b])).toBe(stamp([b, a]));
  });

  it("moves when a timestamp moves", () => {
    expect(stamp([{ ...a, updated_at: "2026-02-02T00:00:00Z" }])).not.toBe(stamp([a]));
  });

  it("moves when only the count moves, which is the delete case", () => {
    // **The reason the answer is a pair.** A delete does not raise the newest
    // `updated_at`; it usually lowers it. A watcher comparing only the
    // timestamp would miss the write, or see the watermark go backwards and
    // have to guess. This is also the only place that case can be expressed:
    // this platform writes instances through Actions and sync and has no
    // route that removes a source.
    expect(stamp([{ ...a, count: 1 }])).not.toBe(stamp([a]));
  });

  it("tells an empty type from an absent answer", () => {
    expect(stamp([b])).not.toBe(stamp([]));
    expect(stamp(undefined)).toBeNull();
  });
});

describe("deciding to refresh", () => {
  it("never treats the first answer as a change", () => {
    // Nothing to compare it to, and treating it as one would refresh every
    // module once on open — the unresolved state read as the changed one
    // (§210).
    expect(changed(null, "t1::2")).toBe(false);
    expect(changed("t1::2", null)).toBe(false);
  });

  it("refreshes when the watermark moved and not when it held", () => {
    expect(changed("t1::2", "t1::3")).toBe(true);
    expect(changed("t1::2", "t1::2")).toBe(false);
  });
});

describe("a background tab", () => {
  it("holds the refresh rather than dropping it", () => {
    // p.579: "If an auto-refresh notification occurs while a variable is
    // hidden, it will be delayed until the variable becomes visible again, at
    // which point a reload will immediately be triggered… also applies if the
    // browser tab is minimized, or is not the currently active tab."
    expect(applyNow(false)).toBe(false);
    expect(applyNow(true)).toBe(true);
  });
});

describe("a reader who paused updates (p.578)", () => {
  it("holds them the same way a hidden tab does", () => {
    // "Disable auto-refresh updates: Prevents updates from auto-refresh from
    // **taking effect**" — not from happening. Same question as the tab, so
    // the same function rather than a second one.
    expect(applyNow(true, true)).toBe(false);
    expect(applyNow(true, false)).toBe(true);
  });

  it("stays held while either reason holds", () => {
    // A reader who paused, then switched tabs, then came back has resolved
    // one of the two and not the other.
    expect(applyNow(false, true)).toBe(false);
    expect(applyNow(false, false)).toBe(false);
  });

  it("defaults to not paused, so a module that never fires the event runs", () => {
    expect(applyNow(true)).toBe(true);
  });
});

describe("what can be registered", () => {
  it("is the object set variables and nothing else", () => {
    // p.576 registers *object sets*. Offering a string variable would be
    // offering a registration that resolves to no type and watches nothing.
    const declared = {
      v_sites: { id: "v_sites", kind: "object_set", label: "Sites" },
      v_name: { id: "v_name", kind: "string", label: "Name" },
      v_picked: { id: "v_picked", kind: "single_object", label: "Picked" },
    } as never;
    expect(registrable(declared).map((v) => v.id)).toEqual(["v_sites"]);
  });
});
