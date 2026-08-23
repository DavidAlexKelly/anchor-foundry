import { describe, expect, it } from "vitest";

import { activeTab, asTabName, tabLabels } from "./tab-selection";

/** Tabs sections and Variable-Based Tab Selection (Foundry `workshop` p.54,
 * p.84).
 *
 * p.84's rule is p.81's with the negation removed — a Switch-to-tab event
 * *does* write its variable — and the interesting claim of this module is that
 * the resolution arithmetic is unchanged by that. The write-back does not
 * remove the disagreement, it just ends it: for the debounce plus round trip
 * it takes the variable to come back, the event and the variable say different
 * things, exactly as they do one row up.
 */

const TABS = ["Overview", "Details", "History"];

describe("tabLabels", () => {
  it("uses the author's names, trimmed", () => {
    expect(tabLabels("Overview, Details ,History", 3)).toEqual(TABS);
  });

  it("numbers the ones the author has not named yet", () => {
    // Not the child widget's name: a tab bar reading "Section" over a section
    // tells a reader nothing, and a numbered placeholder is visibly one.
    expect(tabLabels("Overview", 3)).toEqual(["Overview", "Tab 2", "Tab 3"]);
    expect(tabLabels("", 2)).toEqual(["Tab 1", "Tab 2"]);
    expect(tabLabels(null, 1)).toEqual(["Tab 1"]);
  });

  it("gives one label per child, however long the list is", () => {
    // Too many names is as likely as too few - a child was deleted - and the
    // extras are simply not tabs.
    expect(tabLabels("A,B,C,D", 2)).toEqual(["A", "B"]);
    expect(tabLabels("A,B", 0)).toEqual([]);
  });

  it("makes duplicates unique, because a tab name is an address", () => {
    // **The one that needs saying.** p.84's event and the backing variable
    // both name a tab by its label, so two tabs called "Details" leave both
    // with no answer.
    expect(tabLabels("Details,Details,Details", 3)).toEqual([
      "Details", "Details 2", "Details 3",
    ]);
    // And a placeholder can collide with a real name too.
    expect(tabLabels("Tab 2,", 2)).toEqual(["Tab 2", "Tab 2 2"]);
  });

  it("does not refuse a half-typed configuration", () => {
    // A section is drawn while it is being configured. An author mid-keystroke
    // should see a tab bar, not an error.
    expect(tabLabels(",,", 3)).toEqual(["Tab 1", "Tab 2", "Tab 3"]);
  });
});

describe("asTabName", () => {
  it("reads a value that names one of this section's tabs", () => {
    expect(asTabName("Details", TABS)).toBe("Details");
    expect(asTabName("  Details  ", TABS)).toBe("Details");
  });

  it("reads a value naming no tab as naming nothing", () => {
    expect(asTabName("Detials", TABS)).toBe(null);
    expect(asTabName("", TABS)).toBe(null);
    expect(asTabName("Details", [])).toBe(null);
  });

  it("does not coerce a non-string", () => {
    // A tab called "2" is a name somebody could type, so coercing the number 2
    // would land an ill-typed variable on a real tab by accident.
    expect(asTabName(2, ["1", "2"])).toBe(null);
    expect(asTabName(null, TABS)).toBe(null);
    expect(asTabName(true, TABS)).toBe(null);
  });
});

describe("activeTab with no backing variable", () => {
  it("shows the first tab until something says otherwise", () => {
    expect(activeTab(undefined, undefined, TABS)).toBe("Overview");
  });

  it("shows the tab an event switched to", () => {
    expect(activeTab({ name: "History", against: null }, undefined, TABS)).toBe("History");
  });

  it("has nothing to show when the section has no tabs", () => {
    expect(activeTab(undefined, undefined, [])).toBe(null);
  });

  it("ignores an override naming a tab that is gone", () => {
    // Renaming a tab out from under a click must not blank the section. The
    // override is stale, so the section falls back the way it started.
    expect(activeTab({ name: "Archive", against: null }, undefined, TABS)).toBe("Overview");
  });
});

describe("activeTab with a backing variable", () => {
  it("shows the tab the variable names, before anything is clicked", () => {
    expect(activeTab(undefined, "Details", TABS)).toBe("Details");
  });

  it("falls back to the first tab when the variable names no tab", () => {
    expect(activeTab(undefined, "Detials", TABS)).toBe("Overview");
    expect(activeTab(undefined, "", TABS)).toBe("Overview");
  });
});

describe("activeTab while a write-back is in flight", () => {
  it("shows the clicked tab before the variable has caught up", () => {
    // **This is the case p.84 might mislead you out of testing.** The event
    // writes the variable, so it is tempting to let the variable be the only
    // state - but the write needs a debounce and a round trip, and until it
    // lands the variable still says the old tab. Without the override the
    // section would snap back to Overview on every click and settle a moment
    // later, which reads as a broken tab bar.
    expect(
      activeTab({ name: "History", against: "Overview" }, "Overview", TABS),
    ).toBe("History");
  });

  it("stays put once the write lands and the two agree", () => {
    // The variable is now a *change*, so it wins - and it happens to want the
    // same tab, which is the whole of what p.84's write-back buys. The
    // override retires and nothing moves on screen.
    expect(
      activeTab({ name: "History", against: "Overview" }, "History", TABS),
    ).toBe("History");
  });

  it("follows the variable when it changes to something else entirely", () => {
    // A second writer - another event, a filter, a URL - is the newer
    // instruction, exactly as one row up.
    expect(
      activeTab({ name: "History", against: "Overview" }, "Details", TABS),
    ).toBe("Details");
  });

  it("counts a change to an unknown value as a change", () => {
    // The variable spoke last and named nothing this section has, so the
    // section goes to its first tab rather than staying on the override. The
    // reader ends up somewhere, which is the point.
    expect(
      activeTab({ name: "History", against: "Overview" }, "Detials", TABS),
    ).toBe("Overview");
  });

  it("treats a section with no variable differently from one with a blank", () => {
    // `undefined` is "no Variable-Based Tab Selection"; a value naming no tab
    // resolves to `null`, which is what an override made against no variable
    // recorded - so that override still stands.
    const override = { name: "History", against: null };
    expect(activeTab(override, undefined, TABS)).toBe("History");
    expect(activeTab(override, "", TABS)).toBe("History");
    expect(activeTab(override, "Details", TABS)).toBe("Details");
  });
});
