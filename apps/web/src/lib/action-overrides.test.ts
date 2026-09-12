import { describe, expect, it } from "vitest";
import {
  CURRENT_USER,
  blankBlock,
  conditionDraft,
  conditionParameters,
  conditionValue,
  formOrder,
  hasOverrides,
  ifSummary,
  moveBlock,
  orderNote,
  overrideKey,
  readableBefore,
  sameAsParameter,
  thenSummary,
  type OverrideBlock,
} from "./action-overrides";
import type { ActionParameter } from "./types";

const when = (parameter: string, value: unknown) => ({
  left: { kind: "parameter", parameter },
  operator: "is",
  right: { kind: "value", value },
});

function block(over: Partial<OverrideBlock> = {}): OverrideBlock {
  return {
    id: "b1",
    sort_order: 0,
    conditions: [when("status", "closed")],
    set_hidden: null,
    set_required: null,
    set_default: null,
    ...over,
  };
}

function parameter(over: Partial<ActionParameter> = {}): ActionParameter {
  return {
    id: "p1",
    api_name: "justification",
    display_name: "Justification",
    data_type: "string",
    required: false,
    default_value: null,
    hidden: false,
    sort_order: 0,
    overrides: [],
    ...over,
  };
}

describe("conditionParameters", () => {
  it("is empty for parameters with no blocks", () => {
    expect(conditionParameters([parameter(), parameter({ id: "p2" })])).toEqual([]);
  });

  it("names what the conditions read, across blocks and parameters", () => {
    expect(conditionParameters([
      parameter({ overrides: [block(), block({ conditions: [when("owner", "me")] })] }),
      parameter({ id: "p2", overrides: [block({ conditions: [when("area", "eu")] })] }),
    ])).toEqual(["area", "owner", "status"]);
  });

  it("says nothing about a condition that reads the current user", () => {
    // Who is asking does not change while a form is open.
    expect(conditionParameters([parameter({
      overrides: [block({ conditions: [conditionValue({
        parameter: CURRENT_USER, operator: "is", value: "u1",
      })] })],
    })])).toEqual([]);
  });

  it("does not watch a side whose kind is not a parameter", () => {
    // The same check §328 had to come back for. Every side kind decision 0007
    // actually has either carries a `parameter` key or carries nothing, so
    // dropping the guard and relying on the key alone behaves identically —
    // until a hand-edited document (p.65's premise) or one from a build with a
    // kind this one lacks arrives. `_side` refuses an unknown kind, so the
    // server leaves the parameter alone whatever the value is; watching it
    // would re-ask on every keystroke of something that cannot change the
    // answer.
    expect(conditionParameters([parameter({
      overrides: [block({ conditions: [{
        left: { kind: "property", parameter: "status" },
        operator: "is",
        right: { kind: "value", value: 1 },
      }] })],
    })])).toEqual([]);
  });

  it("reads both sides of a condition", () => {
    expect(conditionParameters([parameter({
      overrides: [block({ conditions: [{
        left: { kind: "parameter", parameter: "a" },
        operator: "is",
        right: { kind: "parameter", parameter: "b" },
      }] })],
    })])).toEqual(["a", "b"]);
  });
});

describe("hasOverrides", () => {
  it("is false for a form nothing overrides, which never asks the server", () => {
    expect(hasOverrides([parameter(), parameter({ id: "p2" })])).toBe(false);
    expect(hasOverrides([])).toBe(false);
  });

  it("is true for a block that names no parameter at all", () => {
    // **The defect §328 paid to learn**, refused in advance here: p.50's other
    // template asks about the current user and reads nothing out of the form,
    // so deciding whether to ask from `conditionParameters` would never ask —
    // and p.43's justification would be required for nobody.
    expect(hasOverrides([parameter({
      overrides: [block({ conditions: [conditionValue({
        parameter: CURRENT_USER, operator: "is", value: "u1",
      })] })],
    })])).toBe(true);
  });
});

describe("overrideKey", () => {
  it("changes when a value a condition reads changes", () => {
    const p = [parameter({ overrides: [block()] })];
    expect(overrideKey(p, { status: "open" }))
      .not.toBe(overrideKey(p, { status: "closed" }));
  });

  it("does not change when an unread value changes", () => {
    const p = [parameter({ overrides: [block()] })];
    expect(overrideKey(p, { status: "open", note: "a" }))
      .toBe(overrideKey(p, { status: "open", note: "b" }));
  });

  it("is one key for a form with no blocks", () => {
    expect(overrideKey([parameter()], { status: "open" }))
      .toBe(overrideKey([parameter()], { status: "closed" }));
  });
});

describe("sameAsParameter", () => {
  it("says nothing about a block that changes something", () => {
    expect(sameAsParameter(
      block({ set_required: true }), parameter({ required: false }),
    )).toBeNull();
  });

  it("warns when the block requires what is already required", () => {
    // p.45: "If an override is configured to take on the same value as the
    // default already set on the parameter, a warning will be shown."
    const note = sameAsParameter(
      block({ set_required: true }), parameter({ required: true }));
    expect(note).toContain("required");
    expect(note).toContain("change nothing");
  });

  it("warns about hiding what is already hidden, in the right words", () => {
    expect(sameAsParameter(block({ set_hidden: true }), parameter({ hidden: true })))
      .toContain("hidden");
    expect(sameAsParameter(block({ set_hidden: false }), parameter({ hidden: false })))
      .toContain("shown");
  });

  it("warns about a default that is already the default", () => {
    expect(sameAsParameter(
      block({ set_default: "none" }), parameter({ default_value: "none" }),
    )).toContain("that default");
  });

  it("does not warn about a different default", () => {
    expect(sameAsParameter(
      block({ set_default: "other" }), parameter({ default_value: "none" }),
    )).toBeNull();
  });

  it("ignores what the block leaves alone", () => {
    // A block that says nothing about `required` is not "the same as the
    // default" for a parameter that happens to be optional — it is a block
    // about something else.
    expect(sameAsParameter(
      block({ set_hidden: false }), parameter({ hidden: true, required: false }),
    )).toBeNull();
  });

  it("names every field that matches, not just the first", () => {
    const note = sameAsParameter(
      block({ set_hidden: true, set_required: true }),
      parameter({ hidden: true, required: true }),
    );
    expect(note).toContain("hidden");
    expect(note).toContain("required");
  });
});

describe("thenSummary", () => {
  it("says what the block does", () => {
    expect(thenSummary(block({ set_required: true }))).toBe("require it");
    expect(thenSummary(block({ set_required: false }))).toBe("make it optional");
    expect(thenSummary(block({ set_hidden: true }))).toBe("hide it");
    expect(thenSummary(block({ set_hidden: false }))).toBe("show it");
  });

  it("says p.43's two together", () => {
    expect(thenSummary(block({ set_hidden: false, set_required: true })))
      .toBe("show it, require it");
  });

  it("shows the default it would set", () => {
    expect(thenSummary(block({ set_default: "see the ticket" })))
      .toContain("see the ticket");
  });

  it("says so when a half-written block does nothing", () => {
    expect(thenSummary(block())).toBe("change nothing yet");
  });

  it("treats a false as something rather than as nothing", () => {
    // The trap `null means leave alone` exists to avoid, on the screen this
    // time: `set_hidden: false` is p.43's "show it" and a summary that tested
    // truthiness would call it "change nothing yet".
    expect(thenSummary(block({ set_hidden: false }))).not.toContain("nothing");
  });
});

describe("ifSummary", () => {
  it("counts the conditions", () => {
    expect(ifSummary(block())).toBe("one condition holds");
    expect(ifSummary(block({ conditions: [when("a", 1), when("b", 2)] })))
      .toBe("all 2 conditions hold");
  });

  it("says a block with none will not save", () => {
    // §214: better to say the control will not do what it looks like it does
    // than to let somebody find out at the save.
    expect(ifSummary(block({ conditions: [] }))).toContain("refuses to save");
  });
});

describe("orderNote", () => {
  it("says nothing when there is only one block", () => {
    // A note that is always on screen is one nobody reads when it matters.
    expect(orderNote([block()])).toBeNull();
    expect(orderNote([])).toBeNull();
  });

  it("says p.45's first-match rule when more than one can apply", () => {
    const note = orderNote([block(), block()]);
    expect(note).toContain("only the first");
  });
});

describe("blankBlock", () => {
  it("arrives with a condition row to fill in", () => {
    // The server refuses a block with no conditions, so starting somebody in
    // a state it will not save would be §214's control that looks like it
    // works.
    expect(blankBlock().conditions).toHaveLength(1);
    expect(blankBlock().set_required).toBeNull();
  });
});

describe("conditionDraft / conditionValue", () => {
  it("round-trips a prior parameter against a value", () => {
    const draft = { parameter: "status", operator: "is", value: "closed" };
    expect(conditionDraft(conditionValue(draft))).toEqual(draft);
  });

  it("round-trips p.43's current-user condition", () => {
    const draft = { parameter: CURRENT_USER, operator: "is", value: "u1" };
    expect(conditionDraft(conditionValue(draft))).toEqual(draft);
    expect(conditionValue(draft).left).toEqual({ kind: "current_user", attribute: "id" });
  });

  it("cannot collide with a parameter somebody declared", () => {
    // An api_name is `^[a-z][a-z0-9_]{0,99}$`, so the `$` is what makes this
    // sentinel safe rather than a convention nobody checks.
    expect(CURRENT_USER).toMatch(/\$/);
    expect(CURRENT_USER).not.toMatch(/^[a-z][a-z0-9_]*$/);
  });

  it("reads an empty condition as an empty draft", () => {
    expect(conditionDraft(undefined))
      .toEqual({ parameter: "", operator: "is", value: "" });
  });

  it("keeps an operator this panel has no entry for", () => {
    expect(conditionDraft({
      left: { kind: "parameter", parameter: "n" },
      operator: "is_less_than",
      right: { kind: "value", value: 5 },
    }).operator).toBe("is_less_than");
  });
});

describe("formOrder", () => {
  const declared = [
    { api_name: "status" }, { api_name: "reason" }, { api_name: "owner" },
  ];

  it("is the body then the sections", () => {
    expect(formOrder(declared, [{ id: "s1", parameters: ["status"] }]))
      .toEqual(["reason", "owner", "status"]);
  });

  it("is the declaration order when nothing is sectioned", () => {
    expect(formOrder(declared, [])).toEqual(["status", "reason", "owner"]);
  });

  it("ignores a name no parameter answers to", () => {
    expect(formOrder(declared, [{ id: "s1", parameters: ["gone", "owner"] }]))
      .toEqual(["status", "reason", "owner"]);
  });

  it("keeps the sections in their own order", () => {
    expect(formOrder(declared, [
      { id: "s1", parameters: ["owner"] },
      { id: "s2", parameters: ["status"] },
    ])).toEqual(["reason", "owner", "status"]);
  });
});

describe("readableBefore", () => {
  it("is strictly above", () => {
    expect(readableBefore(["a", "b", "c"], "a")).toEqual([]);
    expect(readableBefore(["a", "b", "c"], "b")).toEqual(["a"]);
    expect(readableBefore(["a", "b", "c"], "c")).toEqual(["a", "b"]);
  });

  it("offers nothing for a parameter the form does not mention", () => {
    expect(readableBefore(["a", "b"], "gone")).toEqual([]);
  });
});

describe("moveBlock", () => {
  const three = [block({ id: "a" }), block({ id: "b" }), block({ id: "c" })];

  it("reorders, which is the rule rather than a presentation detail", () => {
    expect(moveBlock(three, 2, -1).map((b) => b.id)).toEqual(["a", "c", "b"]);
    expect(moveBlock(three, 0, 1).map((b) => b.id)).toEqual(["b", "a", "c"]);
  });

  it("does nothing at the ends rather than wrapping", () => {
    expect(moveBlock(three, 0, -1).map((b) => b.id)).toEqual(["a", "b", "c"]);
    expect(moveBlock(three, 2, 1).map((b) => b.id)).toEqual(["a", "b", "c"]);
  });

  it("leaves the list it was given alone", () => {
    moveBlock(three, 0, 1);
    expect(three.map((b) => b.id)).toEqual(["a", "b", "c"]);
  });
});
