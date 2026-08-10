import { describe, expect, it } from "vitest";
import {
  KIND_LABELS,
  isKind,
  kindLabel,
  selectedKinds,
  toggleKind,
} from "./resource-filter";

describe("isKind", () => {
  it("accepts every kind the browser offers a chip for", () => {
    // Written against KIND_LABELS rather than a hand-copied list: a second
    // list is a second thing to forget to update, and the failure mode is a
    // kind that has a chip but cannot be put in a URL.
    for (const { kind } of KIND_LABELS) expect(isKind(kind)).toBe(true);
  });

  it("rejects a hand-typed value that is not a kind", () => {
    expect(isKind("nonsense")).toBe(false);
    expect(isKind("")).toBe(false);
  });

  it("rejects inherited Object properties, which are not kinds", () => {
    // `value in LABEL` walks the prototype chain, so a bare `in` check would
    // call these kinds and forward them to the API. Object.fromEntries gives a
    // normal object, not a null-prototype one, so this is reachable.
    expect(isKind("toString")).toBe(false);
    expect(isKind("constructor")).toBe(false);
  });
});

describe("selectedKinds", () => {
  it("keeps the known kinds and drops the rest", () => {
    expect(selectedKinds(["dataset", "nonsense", "model"])).toEqual(["dataset", "model"]);
  });

  it("collapses a repeated kind to one filter", () => {
    expect(selectedKinds(["dataset", "dataset"])).toEqual(["dataset"]);
  });

  it("preserves the order given in the URL", () => {
    expect(selectedKinds(["model", "dataset"])).toEqual(["model", "dataset"]);
  });

  it("is empty for no parameters, which means no filter rather than no kinds", () => {
    expect(selectedKinds([])).toEqual([]);
  });
});

describe("toggleKind", () => {
  it("adds a kind that is not selected", () => {
    expect(toggleKind(["dataset"], "model")).toEqual(["dataset", "model"]);
  });

  it("removes a kind that is selected", () => {
    expect(toggleKind(["dataset", "model"], "dataset")).toEqual(["model"]);
  });

  it("turning the last chip off leaves no filter, not an empty result", () => {
    expect(toggleKind(["dataset"], "dataset")).toEqual([]);
  });

  it("drops an unknown kind that was already in the URL", () => {
    // The toggle is the only writer, so a junk parameter that survived it
    // would persist through every subsequent click.
    expect(toggleKind(["nonsense", "dataset"], "model")).toEqual(["dataset", "model"]);
  });

  it("builds on the parameters given, not on a stale copy", () => {
    // The two-clicks-faster-than-the-router case, written as the sequence it
    // actually is: the second toggle sees the first one's output.
    const first = toggleKind([], "dataset");
    const second = toggleKind(first, "model");
    expect(second).toEqual(["dataset", "model"]);
  });
});

describe("kindLabel", () => {
  it("names every kind that has a chip", () => {
    for (const { kind, label } of KIND_LABELS) expect(kindLabel(kind)).toBe(label);
  });

  it("falls back to the raw value rather than rendering nothing", () => {
    // A kind added to the API before it is added here should read as its own
    // name in the table, not as a blank cell.
    expect(kindLabel("future_kind" as never)).toBe("future_kind");
  });
});
