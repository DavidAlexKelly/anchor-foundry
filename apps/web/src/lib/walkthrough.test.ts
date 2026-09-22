/** The walkthrough's arithmetic (§431; `code-repositories` p.11). */
import { describe, expect, it } from "vitest";
import type { Step } from "./walkthrough";
import {
  CARD_GAP,
  CARD_MARGIN,
  at,
  centred,
  isLast,
  move,
  nextLabel,
  placeCard,
  progressLabel,
  stepsFor,
} from "./walkthrough";

const step = (id: string, over: Partial<Step> = {}): Step => ({
  id,
  title: id,
  body: `about ${id}`,
  anchor: id,
  ...over,
});

const three = [step("a"), step("b"), step("c")];

describe("stepsFor", () => {
  const conditional = [
    step("a"),
    step("b", { needs: "gated" }),
    step("c"),
  ];

  it("keeps a step with no condition, whatever the caller says", () => {
    expect(stepsFor(conditional, () => false).map((s) => s.id)).toEqual(["a", "c"]);
  });

  it("keeps a conditional step when its condition holds", () => {
    expect(stepsFor(conditional, (need) => need === "gated").map((s) => s.id))
      .toEqual(["a", "b", "c"]);
  });

  it("keeps the order they were written in", () => {
    // A walkthrough is a sequence, so the filter must not be a re-sort.
    expect(stepsFor(three, () => true).map((s) => s.id)).toEqual(["a", "b", "c"]);
  });

  it("asks about the condition, not the id", () => {
    const s = [step("one", { needs: "something-else" })];
    expect(stepsFor(s, (need) => need === "something-else")).toHaveLength(1);
    expect(stepsFor(s, (need) => need === "one")).toHaveLength(0);
  });

  it("never drops an unconditional walk", () => {
    expect(stepsFor(three, () => false)).toHaveLength(3);
  });
});

describe("move", () => {
  it("goes forward and back", () => {
    expect(move(three, 0, 1)).toBe(1);
    expect(move(three, 2, -1)).toBe(1);
  });

  it("stops at the end rather than wrapping", () => {
    // The opposite of the command palette's arrows, and deliberately: "Next"
    // on the last step must not restart a tour somebody has just finished.
    expect(move(three, 2, 1)).toBe(2);
  });

  it("stops at the start rather than wrapping", () => {
    expect(move(three, 0, -1)).toBe(0);
  });

  it("survives an empty walk", () => {
    expect(move([], 0, 1)).toBe(0);
  });

  it("clamps a jump past the end", () => {
    expect(move(three, 0, 99)).toBe(2);
  });
});

describe("at", () => {
  it("returns the step", () => {
    expect(at(three, 1)?.id).toBe("b");
  });

  it("is null past the end", () => {
    // The list can shrink underneath an index when the page changes, and a
    // card rendering `undefined.title` would take the page with it.
    expect(at(three, 9)).toBe(null);
    expect(at([], 0)).toBe(null);
  });
});

describe("isLast and nextLabel", () => {
  it("knows the last step", () => {
    expect(isLast(three, 2)).toBe(true);
    expect(isLast(three, 1)).toBe(false);
  });

  it("is not last when there is nothing at all", () => {
    // An empty walk must not show "Done" over no content — `at` returns null
    // there and the card says so instead.
    expect(isLast([], 0)).toBe(false);
  });

  it("says Done on the last step and Next before it", () => {
    expect(nextLabel(three, 2)).toBe("Done");
    expect(nextLabel(three, 0)).toBe("Next");
  });

  it("says Next on a one-step walk's only step", () => {
    expect(nextLabel([step("only")], 0)).toBe("Done");
  });
});

describe("progressLabel", () => {
  it("counts from one", () => {
    expect(progressLabel(three, 0)).toBe("Step 1 of 3");
  });

  it("counts the steps that survived, not the list as written", () => {
    // The bug this module exists to make impossible: two steps dropped for
    // things this project does not have, and a counter still promising five.
    const shown = stepsFor(
      [step("a"), step("b", { needs: "gated" }), step("c"),
       step("d", { needs: "pinned" }), step("e")],
      () => false,
    );
    expect(progressLabel(shown, 2)).toBe("Step 3 of 3");
  });

  it("does not count past the end", () => {
    expect(progressLabel(three, 9)).toBe("Step 3 of 3");
  });
});

describe("placeCard", () => {
  const card = { width: 300, height: 120 };
  const view = { width: 1000, height: 800 };

  it("sits below the element when there is room", () => {
    const anchor = { top: 100, left: 200, width: 150, height: 40 };
    expect(placeCard(anchor, card, view).top).toBe(100 + 40 + CARD_GAP);
  });

  it("sits above when there is not", () => {
    // A card that ran off the bottom would be a tour describing something
    // nobody can read.
    const anchor = { top: 740, left: 200, width: 150, height: 40 };
    expect(placeCard(anchor, card, view).top).toBe(740 - CARD_GAP - card.height);
  });

  it("starts where the element starts", () => {
    const anchor = { top: 100, left: 200, width: 150, height: 40 };
    expect(placeCard(anchor, card, view).left).toBe(200);
  });

  it("is pulled back inside the right edge", () => {
    const anchor = { top: 100, left: 950, width: 40, height: 40 };
    expect(placeCard(anchor, card, view).left).toBe(1000 - card.width - CARD_MARGIN);
  });

  it("keeps its margin at the left edge", () => {
    const anchor = { top: 100, left: 0, width: 40, height: 40 };
    expect(placeCard(anchor, card, view).left).toBe(CARD_MARGIN);
  });

  it("does not go off the top when nothing fits", () => {
    // A tall card and an element near the top: above is off-screen and below
    // is off-screen, and the margin is what is left.
    const anchor = { top: 10, left: 200, width: 150, height: 40 };
    const tall = { width: 300, height: 790 };
    expect(placeCard(anchor, tall, view).top).toBe(CARD_MARGIN);
  });

  it("prefers below on a window that has room for exactly one", () => {
    // The boundary: the card's bottom edge lands on the margin.
    const anchor = { top: 100, left: 10, width: 10, height: 10 };
    const snug = { width: 100, height: 800 - 100 - 10 - CARD_GAP - CARD_MARGIN };
    expect(placeCard(anchor, snug, view).top).toBe(100 + 10 + CARD_GAP);
  });
});

describe("centred", () => {
  const view = { width: 1000, height: 800 };

  it("puts a card with nothing to point at in the middle", () => {
    // An anchor can be missing for a reason nobody predicted, and a
    // walkthrough that went blank would be the help itself breaking.
    expect(centred({ width: 300, height: 120 }, view)).toEqual({
      top: (800 - 120) / 2,
      left: (1000 - 300) / 2,
    });
  });

  it("keeps its margin when the card is larger than the window", () => {
    expect(centred({ width: 1200, height: 900 }, view))
      .toEqual({ top: CARD_MARGIN, left: CARD_MARGIN });
  });
});
