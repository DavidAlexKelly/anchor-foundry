import { describe, expect, it } from "vitest";

import {
  DEFAULT_ACTIVE_COLOUR, DEFAULT_COMPLETED_COLOUR, DEFAULT_TEMPLATE, DEFAULT_TYPE,
  STEPPER_TYPES, TEMPLATES,
  activeColourOf, activeIndex, completedColourOf, isCompleted, isReachable,
  showsStepNumber, stateOf, stepsOf, templateOf, typeOf,
} from "./stepper";

/** p.312-313's Stepper. */

describe("p.312's type", () => {
  it("has the two types p.312 names and defaults to linear", () => {
    expect(Object.keys(STEPPER_TYPES).sort()).toEqual(["linear", "non_linear"]);
    expect(DEFAULT_TYPE).toBe("linear");
    expect(typeOf(undefined)).toBe("linear");
    expect(typeOf("non_linear")).toBe("non_linear");
  });

  it("falls back for a type the widget does not have", () => {
    expect(typeOf("freeform")).toBe("linear");
    expect(typeOf("constructor")).toBe("linear");
    expect(typeOf(2)).toBe("linear");
  });
});

describe("p.313's template", () => {
  it("has the two templates p.313 names and defaults to text", () => {
    expect(Object.keys(TEMPLATES).sort()).toEqual(["icons", "text"]);
    expect(DEFAULT_TEMPLATE).toBe("text");
    expect(templateOf(undefined)).toBe("text");
    expect(templateOf("icons")).toBe("icons");
  });

  it("falls back for a template the widget does not have", () => {
    expect(templateOf("images")).toBe("text");
    expect(templateOf(0)).toBe("text");
  });
});

describe("p.313's steps", () => {
  it("reads a label, a completion variable and an icon", () => {
    expect(stepsOf([{ label: " Pick ", completedVariable: "v_a", icon: " check " }]))
      .toEqual([{ label: "Pick", completedVariable: "v_a", icon: "check" }]);
  });

  it("is empty for anything that is not a list", () => {
    expect(stepsOf(undefined)).toEqual([]);
    expect(stepsOf({ label: "Pick" })).toEqual([]);
  });

  it("drops a step with no label", () => {
    // A numbered circle with nothing beside it is a step nobody can identify,
    // and the workflow it belongs to is the thing being navigated.
    expect(stepsOf([null, 7, { icon: "check" }, { label: "  " }, { label: "Pick" }]))
      .toEqual([{ label: "Pick" }]);
  });

  it("drops a blank variable and a blank icon", () => {
    expect(stepsOf([{ label: "Pick", completedVariable: "", icon: "   " }]))
      .toEqual([{ label: "Pick" }]);
  });
});

describe("what counts as completed", () => {
  it("is true and only true", () => {
    // **A variable a module has never written holds `undefined`**, and a step
    // that counted that as done would open a workflow with every stage ticked.
    expect(isCompleted(true)).toBe(true);
    expect(isCompleted(undefined)).toBe(false);
    expect(isCompleted(null)).toBe(false);
  });

  it("is not fooled by a string or a number", () => {
    // The other direction of the same mistake: `"false"` is truthy.
    expect(isCompleted("true")).toBe(false);
    expect(isCompleted("false")).toBe(false);
    expect(isCompleted(1)).toBe(false);
  });
});

describe("which step the viewer is on", () => {
  it("is the first incomplete one", () => {
    expect(activeIndex([true, false, false])).toBe(1);
    expect(activeIndex([false, false])).toBe(0);
    // Not merely "after the last completed one": a workflow completed out of
    // order still has a first gap, and that is where somebody is.
    expect(activeIndex([false, true, false])).toBe(0);
  });

  it("is nothing at all once every step is done", () => {
    // A workflow that highlighted its last step forever would look unfinished
    // to the person who had just finished it.
    expect(activeIndex([true, true])).toBeNull();
    expect(activeIndex([])).toBeNull();
  });
});

describe("p.312's in-order rule", () => {
  it("lets a non-linear stepper go anywhere", () => {
    expect(isReachable({ index: 2, completed: [false, false, false], type: "non_linear" }))
      .toBe(true);
  });

  it("refuses a linear step whose predecessors are not done", () => {
    expect(isReachable({ index: 2, completed: [true, false, false], type: "linear" }))
      .toBe(false);
  });

  it("allows the next step once the ones before it are done", () => {
    expect(isReachable({ index: 2, completed: [true, true, false], type: "linear" }))
      .toBe(true);
  });

  it("always allows the first step", () => {
    // Nothing precedes it, so "in order" has nothing to say — and a workflow
    // whose first step could not be started would be unusable.
    expect(isReachable({ index: 0, completed: [false, false], type: "linear" })).toBe(true);
  });

  it("lets somebody go back to a step they finished", () => {
    // **"In order" constrains how far forward you may go, not whether you may
    // return** — and a completed step is exactly the one worth re-reading.
    expect(isReachable({ index: 0, completed: [true, true, false], type: "linear" }))
      .toBe(true);
  });

  it("reads the type rather than trusting the document", () => {
    expect(isReachable({ index: 2, completed: [true, false, false], type: "anything" }))
      .toBe(false);
  });
});

describe("what a step is", () => {
  it("is completed, active, or still to come", () => {
    const completed = [true, false, false];
    const active = activeIndex(completed);
    expect(stateOf(0, completed, active)).toBe("completed");
    expect(stateOf(1, completed, active)).toBe("active");
    expect(stateOf(2, completed, active)).toBe("upcoming");
  });

  it("prefers completed over active", () => {
    // The pair cannot both be true while `activeIndex` returns the first
    // *incomplete* step; stating the order is what keeps a later change to
    // one of them from silently changing the other.
    expect(stateOf(0, [true], 0)).toBe("completed");
  });

  it("has no active step when there is none", () => {
    expect(stateOf(1, [true, true], null)).toBe("completed");
    expect(stateOf(1, [false, false], null)).toBe("upcoming");
  });
});

describe("p.313's colours", () => {
  it("uses the configured colour", () => {
    expect(completedColourOf("#ff0000")).toBe("#ff0000");
    expect(activeColourOf(" #00ff00 ")).toBe("#00ff00");
  });

  it("falls back when a document says nothing", () => {
    expect(completedColourOf(undefined)).toBe(DEFAULT_COMPLETED_COLOUR);
    expect(completedColourOf("   ")).toBe(DEFAULT_COMPLETED_COLOUR);
    expect(activeColourOf(7)).toBe(DEFAULT_ACTIVE_COLOUR);
    // Asserted as literals too: `toBe(DEFAULT_…)` alone derives the
    // expectation from its own subject (§201).
    expect(DEFAULT_COMPLETED_COLOUR).toBe("#14646e");
    expect(DEFAULT_ACTIVE_COLOUR).toBe("#8a6d3b");
  });

  it("keeps the two apart", () => {
    // A stepper whose completed and active steps looked identical would show
    // no progress at all, which is the widget's entire job.
    expect(DEFAULT_COMPLETED_COLOUR).not.toBe(DEFAULT_ACTIVE_COLOUR);
  });
});

describe("p.313's show step number", () => {
  it("needs the icon template and the linear type and the toggle", () => {
    // p.313: "when set to linear stepper type **and** set to use icons".
    expect(showsStepNumber({ template: "icons", type: "linear", show: true })).toBe(true);
  });

  it("has nothing to add to the text template", () => {
    // That template already *is* the numbers, so "also display" is a no-op.
    expect(showsStepNumber({ template: "text", type: "linear", show: true })).toBe(false);
  });

  it("means nothing in a workflow with no order", () => {
    expect(showsStepNumber({ template: "icons", type: "non_linear", show: true })).toBe(false);
  });

  it("is off unless the toggle is actually on", () => {
    expect(showsStepNumber({ template: "icons", type: "linear", show: undefined })).toBe(false);
    expect(showsStepNumber({ template: "icons", type: "linear", show: "yes" })).toBe(false);
  });
});
