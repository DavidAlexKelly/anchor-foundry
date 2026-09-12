/**
 * What a cleanup flag tells the reader (§325; `ontology-manager` p.68-74).
 *
 * The flags themselves are computed and tested in
 * `apps/api/tests/test_ontology_cleanup.py`. What is here is the half a
 * database cannot check: whether a row of a deletion queue says enough for
 * somebody to act on it.
 */
import { describe, expect, it } from "vitest";
import {
  FLAG_LABELS,
  NOTHING_TO_DO,
  alsoCount,
  alsoText,
  deleteWarning,
  flagHint,
  flagLabel,
  headline,
  snoozeText,
  stillInUse,
} from "./ontology-cleanup";
import type { CleanupCandidate } from "./types";

function candidate(over: Partial<CleanupCandidate> = {}): CleanupCandidate {
  return {
    id: "t1",
    api_name: "vessel",
    display_name: "Vessel",
    status: "experimental",
    description: "",
    deprecation: null,
    interactions: 0,
    flags: ["unused", "no_description"],
    priority: 1,
    snoozed_until: null,
    ...over,
  };
}

describe("what a flag is called", () => {
  it("says it in English rather than in the column's vocabulary", () => {
    expect(flagLabel("past_deprecation")).toBe("Deprecation overdue");
    expect(flagLabel("no_source")).toBe("No dataset");
  });

  it("carries the sentence that says what is actually true", () => {
    // "Not synced lately" is a label; "no mapping has synced in the last 30
    // days" is the fact somebody checks before deleting something.
    expect(flagHint("stale_source")).toContain("30 days");
    expect(flagHint("no_source")).toContain("mapped");
    for (const key of Object.keys(FLAG_LABELS)) {
      expect(flagHint(key).length, key).toBeGreaterThan(0);
    }
  });

  it("shows an unknown flag rather than dropping it", () => {
    // p.73: the list of flags "is not exhaustive". One added on the server and
    // not here would otherwise leave a row in a list of deletion candidates
    // with no visible reason for being there.
    expect(flagLabel("phonograph_deindexed")).toBe("Phonograph deindexed");
    expect(flagHint("phonograph_deindexed")).toBe("");
  });
});

describe("what a row leads with", () => {
  it("is the worst flag, which is what put the row where it is", () => {
    // p.70 sorts by the worst flag, so a headline naming a different one would
    // bury the reason the row is in the list at all.
    expect(headline(candidate({ flags: ["past_deprecation", "no_description"] })))
      .toBe("Deprecation overdue");
  });

  it("takes the server's order rather than ranking again", () => {
    // §146: a second ranking here is free to disagree with the one that
    // decided the row's position, and then the list's order and its headlines
    // would tell different stories. Given a deliberately "wrong" order, this
    // still leads with what it was handed.
    expect(headline(candidate({ flags: ["no_description", "past_deprecation"] })))
      .toBe("No description");
  });

  it("has something to say for a row with no flags", () => {
    expect(headline(candidate({ flags: [] }))).toBe("No flags");
  });
});

describe("the rest of the flags", () => {
  it("counts them rather than listing them", () => {
    // p.70's table is scanned: the worst flag is the headline and "and 3 more"
    // is enough to know whether opening the row is worth it.
    expect(alsoCount(candidate({ flags: ["a", "b", "c", "d"] }))).toBe(3);
    expect(alsoText(candidate({ flags: ["a", "b", "c", "d"] }))).toBe("and 3 more");
  });

  it("reads correctly for one", () => {
    // **Not a plural branch**, and the sweep is what said so: "and ${1} more"
    // is already "and 1 more", so a conditional here could not change an
    // answer. The assertion stays because the *sentence* is the claim; the
    // branch that used to produce it was deleted (§213).
    expect(alsoText(candidate({ flags: ["a", "b"] }))).toBe("and 1 more");
  });

  it("says nothing when the headline was the whole story", () => {
    expect(alsoText(candidate({ flags: ["unused"] }))).toBe("");
    expect(alsoText(candidate({ flags: [] }))).toBe("");
  });
});

describe("whether anybody is still using it", () => {
  it("is the number that argues against deleting", () => {
    // A type with no description and no source that four hundred people read
    // is not a cleanup candidate, it is a documentation problem.
    expect(stillInUse(candidate({ interactions: 400 }))).toBe(true);
    expect(stillInUse(candidate({ interactions: 0 }))).toBe(false);
  });

  it("puts the number in the delete warning when there is one", () => {
    // p.71's delete "removes associated data from object storage" and cannot
    // be undone, so the last thing the reader sees before confirming is the
    // evidence against.
    const busy = deleteWarning(candidate({ interactions: 400 }));
    expect(busy).toContain("400");
    expect(busy).toContain("Vessel");
    expect(busy).toContain("cannot be undone");
  });

  it("does not invent a number when there is none", () => {
    const quiet = deleteWarning(candidate({ interactions: 0 }));
    expect(quiet).toContain("Vessel");
    expect(quiet).not.toContain("0 interactions");
  });

  it("says what goes with the type, not just that it goes", () => {
    // p.71: "Delete object types from the Ontology **and remove associated
    // data from object storage**." A dialog saying only "delete this object
    // type?" understates what the button does.
    expect(deleteWarning(candidate())).toContain("storage");
  });
});

describe("a snooze", () => {
  const now = new Date("2026-09-12T00:00:00Z");

  it("says when it comes back rather than that it is snoozed", () => {
    // p.71 makes it "for a configurable amount of time", so the date is the
    // whole fact — and somebody who snoozed a type twice wants to see which
    // date won.
    expect(snoozeText("2026-09-19T00:00:00Z", now)).toBe("Back in 7 days");
  });

  it("does not pluralise tomorrow", () => {
    expect(snoozeText("2026-09-13T00:00:00Z", now)).toBe("Back tomorrow");
  });

  it("says a lapsed snooze is back now rather than counting backwards", () => {
    // Negative days would render as "Back in -3 days", which reads as a bug.
    expect(snoozeText("2026-09-09T00:00:00Z", now)).toBe("Back now");
  });

  it("says nothing for a row that is not snoozed", () => {
    expect(snoozeText(null, now)).toBe("");
    expect(snoozeText("not a date", now)).toBe("");
  });
});

describe("an empty queue", () => {
  it("says there is nothing to do rather than drawing nothing", () => {
    // An empty list and a list that failed to load look identical, and this is
    // a screen somebody opens expecting to find work — silence reads as the
    // tool being broken.
    expect(NOTHING_TO_DO).toContain("Nothing here");
    expect(NOTHING_TO_DO.length).toBeGreaterThan(20);
  });
});
