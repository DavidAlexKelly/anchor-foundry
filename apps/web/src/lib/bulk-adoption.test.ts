import { describe, expect, it } from "vitest";

import {
  canMove,
  chosen,
  defaultMessage,
  emptyReason,
  movable,
  moveLabel,
} from "./bulk-adoption";
import type { Model } from "./types";

function model(over: Partial<Model>): Model {
  return {
    id: "m-1",
    name: "daily_orders",
    source_repo_id: null,
    source_path: null,
    ...over,
  } as Model;
}

describe("which transforms are offered", () => {
  it("**leaves out the ones already in a repository**", () => {
    // Offered-and-refused is worse than not offered: it teaches people the
    // control is unreliable rather than that the transform has moved already.
    const rows = [
      model({ id: "a" }),
      model({ id: "b", source_repo_id: "r-1", source_path: "src/b.sql" }),
    ];
    expect(movable(rows).map((m) => m.id)).toEqual(["a"]);
  });

  it("uses the same predicate as the per-row button", () => {
    // A checkbox appearing where the button did not would be a difference
    // nobody could explain.
    const already = model({ source_repo_id: "r-1", source_path: "src/x.sql" });
    expect(movable([already])).toEqual([]);
  });
});

describe("the chosen set", () => {
  it("**is in list order, not ticking order**", () => {
    // Ticking order is invisible on screen, so a confirmation that listed them
    // that way would name the same set differently every time.
    const rows = [model({ id: "a" }), model({ id: "b" }), model({ id: "c" })];
    const picked = new Set(["c", "a"]);
    expect(chosen(rows, picked).map((m) => m.id)).toEqual(["a", "c"]);
  });

  it("cannot choose one that is not offered", () => {
    const rows = [model({ id: "a", source_repo_id: "r-1", source_path: "x.sql" })];
    expect(chosen(rows, new Set(["a"]))).toEqual([]);
  });
});

describe("whether the move can be asked for", () => {
  it("**needs a repository named**", () => {
    // There is no sensible default when a project has several, and picking the
    // first would put files somewhere nobody chose.
    expect(canMove(2, "r-1")).toBe(true);
    expect(canMove(2, "")).toBe(false);
    expect(canMove(0, "r-1")).toBe(false);
  });
});

describe("the button", () => {
  it("**puts the count on the control**", () => {
    // "Move" and "Move 12 transforms" are different promises, and the second
    // is the one a person checks before pressing.
    expect(moveLabel(12)).toBe("Move 12 transforms into a repository");
    expect(moveLabel(1)).toBe("Move 1 transform into a repository");
  });

  it("says something sensible with nothing chosen", () => {
    expect(moveLabel(0)).toBe("Move into a repository");
  });
});

describe("the default commit message", () => {
  it("names up to three and then counts", () => {
    // A commit message listing forty transforms is one nobody reads, and the
    // first few are what makes it recognisable in a log.
    expect(defaultMessage(["a"])).toBe("Move a into this repository");
    expect(defaultMessage(["a", "b", "c"])).toBe("Move a, b, c into this repository");
    expect(defaultMessage(["a", "b", "c", "d", "e"])).toBe(
      "Move a, b, c and 2 more into this repository",
    );
  });

  it("**matches what the server derives**, which is the point of it", () => {
    // The field is prefilled so somebody can see what will be recorded, and
    // leaving it untouched sends nothing - the server writes this sentence.
    // Their agreement is a test rather than a mechanism, so here it is.
    // (`transform_adoption.default_message` is the other side.)
    expect(defaultMessage(["one", "two", "three", "four"])).toBe(
      "Move one, two, three and 1 more into this repository",
    );
  });

  it("is empty when nothing is chosen, rather than a sentence about nothing", () => {
    expect(defaultMessage([])).toBe("");
  });
});

describe("when nothing can be moved", () => {
  it("**tells the three reasons apart**", () => {
    // Only one of them is a reason to go and do something else.
    expect(emptyReason(0, 0)).toContain("No transforms in this project");
    expect(emptyReason(4, 0)).toContain("already authored in a repository");
    expect(emptyReason(4, 4)).toContain("Choose the transforms");
  });
});
