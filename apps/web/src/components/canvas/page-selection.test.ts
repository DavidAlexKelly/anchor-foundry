import { describe, expect, it } from "vitest";

import { asPageId, pageState } from "./page-selection";

/** Variable-Based Page Selection (Foundry `workshop` p.81).
 *
 * p.82's gotcha with a page id in place of a boolean: a Switch-to-Page event
 * does not write the backing variable, so a module can be told two different
 * things at once. `collapse.test.ts` is the sibling; the cases that are only
 * here are the two a boolean cannot have — a value naming a page that does not
 * exist, and the difference between a node and an author-set page ID.
 */

/** A layout of three pages, two of them with author-set IDs. `p3` has none,
 * which is p.197's "pages without a defined page ID" and is deliberately in
 * the fixture: it is reachable by an event and unreachable by the variable. */
const NODE_FOR: Record<string, string> = { overview: "p1", detail: "p2" };
const nodeForPageId = (id: string): string | null => NODE_FOR[id] ?? null;
const DEFAULT = "p1";

describe("asPageId", () => {
  it("reads a non-empty string as the page it names", () => {
    expect(asPageId("overview")).toBe("overview");
  });

  it("trims, because a page ID in the document is trimmed too", () => {
    // A value differing only by a space would miss the page it obviously
    // means, and nothing on screen would say why.
    expect(asPageId("  overview  ")).toBe("overview");
  });

  it("treats absent, empty and blank as naming nothing", () => {
    expect(asPageId(undefined)).toBe(null);
    expect(asPageId(null)).toBe(null);
    expect(asPageId("")).toBe(null);
    expect(asPageId("   ")).toBe(null);
  });

  it("does not coerce a non-string", () => {
    // **The one that needs saying.** `String(42)` is a page ID that could in
    // principle match one, and a numeric ID matching by accident is a worse
    // failure than a wrongly-typed variable being ignored.
    expect(asPageId(42)).toBe(null);
    expect(asPageId(true)).toBe(null);
    expect(asPageId(["overview"])).toBe(null);
    expect(asPageId({ id: "overview" })).toBe(null);
  });
});

describe("pageState with no backing variable", () => {
  it("opens the default page when nothing has happened", () => {
    expect(pageState(undefined, undefined, DEFAULT, nodeForPageId)).toBe("p1");
  });

  it("shows the page an event switched to", () => {
    expect(
      pageState({ nodeId: "p2", against: null }, undefined, DEFAULT, nodeForPageId),
    ).toBe("p2");
  });

  it("can switch to a page that has no author-set ID", () => {
    // An event targets a *node*, so a page nobody has named is still a page
    // you can switch to. This is the half the variable cannot reach.
    expect(
      pageState({ nodeId: "p3", against: null }, undefined, DEFAULT, nodeForPageId),
    ).toBe("p3");
  });

  it("has no page to show when the module has none", () => {
    expect(pageState(undefined, undefined, null, nodeForPageId)).toBe(null);
  });
});

describe("pageState with a backing variable", () => {
  it("shows the page the variable names", () => {
    expect(pageState(undefined, "detail", DEFAULT, nodeForPageId)).toBe("p2");
  });

  it("falls back to the default when the variable is cleared", () => {
    // Not "stay where you are" and not "show nothing": clearing the variable
    // is the absence of an instruction, and the default is what the module
    // does with no instruction.
    expect(pageState(undefined, "", DEFAULT, nodeForPageId)).toBe("p1");
    expect(pageState(undefined, null, DEFAULT, nodeForPageId)).toBe("p1");
  });

  it("falls back to the default when the variable names no page", () => {
    // p.197's rule for a URL, reused: a stale or mistyped ID opens the module
    // rather than blanking it. Blanking is the one outcome that leaves a
    // reader stuck.
    expect(pageState(undefined, "gone", DEFAULT, nodeForPageId)).toBe("p1");
  });
});

describe("pageState when an event and a variable disagree", () => {
  it("lets the event win while the variable holds still", () => {
    // p.81: the event does not write the variable, so the variable still says
    // "overview" and the reader is looking at the detail page.
    expect(
      pageState({ nodeId: "p2", against: "overview" }, "overview", DEFAULT, nodeForPageId),
    ).toBe("p2");
  });

  it("hands control back the moment the variable changes", () => {
    // The variable is now the newer instruction. Without this, `backing` stops
    // meaning anything after the first Switch to Page.
    expect(
      pageState({ nodeId: "p2", against: "overview" }, "detail", DEFAULT, nodeForPageId),
    ).toBe("p2");
    expect(
      pageState({ nodeId: "p3", against: "overview" }, "detail", DEFAULT, nodeForPageId),
    ).toBe("p2");
  });

  it("counts a change to an unknown page as a change", () => {
    // The override was made against "overview"; the variable now says
    // something else, so the variable wins — and what it says names no page,
    // so the default shows. The reader ends up somewhere, which is the point.
    expect(
      pageState({ nodeId: "p2", against: "overview" }, "typo", DEFAULT, nodeForPageId),
    ).toBe("p1");
  });

  it("counts a clear as a change", () => {
    expect(
      pageState({ nodeId: "p2", against: "overview" }, "", DEFAULT, nodeForPageId),
    ).toBe("p1");
  });

  it("counts a change back to the original value as a change", () => {
    // The subtle one. An override made against a *cleared* variable is
    // overridden again when the variable is set — even to the page the event
    // had already chosen. "The latest instruction wins" is about which of the
    // two spoke last, not about whether they agree.
    expect(
      pageState({ nodeId: "p2", against: null }, "detail", DEFAULT, nodeForPageId),
    ).toBe("p2");
    expect(
      pageState({ nodeId: "p2", against: null }, "overview", DEFAULT, nodeForPageId),
    ).toBe("p1");
  });

  it("distinguishes a module with no backing variable from one with an empty one", () => {
    // `undefined` is "no Variable-Based Page Selection"; `""` is a variable
    // that happens to be blank. The override was recorded against `null` in
    // both cases, so only the second is a change — and only the second sends
    // the reader back to the default.
    const override = { nodeId: "p2", against: null };
    expect(pageState(override, undefined, DEFAULT, nodeForPageId)).toBe("p2");
    expect(pageState(override, "", DEFAULT, nodeForPageId)).toBe("p2");
  });
});
