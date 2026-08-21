import { describe, expect, it } from "vitest";

import { asCollapsed, collapseState, nextCollapsed } from "./collapse";

/** Collapsible sections (Foundry `workshop` p.55, p.82).
 *
 * Three events and one gotcha, and the gotcha is the whole reason this is a
 * module rather than three lines of state: p.82 says a backing Boolean
 * variable "will not be updated as a result of one of these events", so a
 * section can be told two different things at once and something has to decide
 * which is on screen.
 */

describe("asCollapsed", () => {
  it("reads a boolean as itself", () => {
    expect(asCollapsed(true)).toBe(true);
    expect(asCollapsed(false)).toBe(false);
  });

  it("treats absent and empty as expanded", () => {
    expect(asCollapsed(null)).toBe(false);
    expect(asCollapsed("")).toBe(false);
    expect(asCollapsed(0)).toBe(false);
  });

  it('reads the *word* "false" as false', () => {
    // **The one that needs saying.** It is a non-empty string, so the obvious
    // coercion makes it true - and a section stuck collapsed because a
    // transform produced the word false is a bug with nothing to see.
    expect(asCollapsed("false")).toBe(false);
    expect(asCollapsed("False")).toBe(false);
    expect(asCollapsed(" no ")).toBe(false);
    expect(asCollapsed("0")).toBe(false);
    // ...and anything else still means collapsed.
    expect(asCollapsed("true")).toBe(true);
    expect(asCollapsed("yes")).toBe(true);
  });
});

describe("nextCollapsed", () => {
  it("expands, collapses, and toggles from where it is", () => {
    expect(nextCollapsed("expand_section", true)).toBe(false);
    expect(nextCollapsed("expand_section", false)).toBe(false);
    expect(nextCollapsed("collapse_section", false)).toBe(true);
    expect(nextCollapsed("collapse_section", true)).toBe(true);
    expect(nextCollapsed("toggle_section", false)).toBe(true);
    expect(nextCollapsed("toggle_section", true)).toBe(false);
  });
});

describe("collapseState with no backing variable", () => {
  it("starts where the section says", () => {
    expect(collapseState(undefined, undefined, true)).toBe(true);
    expect(collapseState(undefined, undefined, false)).toBe(false);
  });

  it("follows the last event once one has fired", () => {
    expect(collapseState({ collapsed: false, against: null }, undefined, true)).toBe(false);
    expect(collapseState({ collapsed: true, against: null }, undefined, false)).toBe(true);
  });
});

describe("collapseState with a backing variable", () => {
  it("follows the variable before any event", () => {
    // **`backing` has to mean something.** A section whose variable is ignored
    // until somebody clicks is a section with a decorative setting.
    expect(collapseState(undefined, true, false)).toBe(true);
    expect(collapseState(undefined, false, true)).toBe(false);
  });

  it("lets an event override it, which is p.82's gotcha in one line", () => {
    // The variable still says collapsed; the section is expanded; p.82 says
    // that is correct and the builder syncs them with a Set Variable Value
    // event if they want the two to agree.
    expect(collapseState({ collapsed: false, against: true }, true, false)).toBe(false);
  });

  it("hands control back when the variable's own value changes", () => {
    // **The half that keeps `backing` true after the first click.** The
    // override was made while the variable said collapsed; the variable now
    // says expanded, which is a newer instruction than the click.
    expect(collapseState({ collapsed: true, against: true }, false, false)).toBe(false);
    expect(collapseState({ collapsed: false, against: false }, true, false)).toBe(true);
  });

  it("compares the variable as a collapse state, not as a raw value", () => {
    // An override made against `true` is still in force when the variable
    // changes from `true` to `"yes"` - the value moved, what it *means* did
    // not, and re-asserting the variable there would undo a click for no
    // reason a reader could see.
    expect(collapseState({ collapsed: false, against: true }, "yes", false)).toBe(false);
  });

  it("does not confuse a missing variable with one holding false", () => {
    // The section has no backing variable at all, so its own default applies;
    // a section whose variable holds false is being told to expand.
    expect(collapseState(undefined, undefined, true)).toBe(true);
    expect(collapseState(undefined, false, true)).toBe(false);
  });
});
