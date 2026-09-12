import { describe, expect, it } from "vitest";

import {
  APPLICATION_LABELS,
  applicationLabel,
  applicationSummary,
  emptyMessage,
  hasAudience,
  headline,
  isUnused,
} from "./usage-metrics";
import type { ObjectTypeUsage, ObjectTypeUsageByApplication } from "./types";

function usage(over: Partial<ObjectTypeUsage> = {}): ObjectTypeUsage {
  return {
    reads: 10,
    writes: 2,
    interactions: 12,
    active_users: 3,
    window_days: 30,
    ...over,
  };
}

function app(
  over: Partial<ObjectTypeUsageByApplication> = {},
): ObjectTypeUsageByApplication {
  return {
    application: "explorer",
    reads: 4,
    writes: 0,
    interactions: 4,
    active_users: 1,
    ...over,
  };
}

describe("a type nobody has used", () => {
  it("is recognised by its interactions, not by its reads", () => {
    // A type written to and never read is used. Checking `reads === 0` would
    // call it unused and invite a rename of a property something is writing.
    expect(isUnused(usage({ reads: 0, writes: 3, interactions: 3 }))).toBe(false);
    expect(isUnused(usage({ reads: 0, writes: 0, interactions: 0 }))).toBe(true);
  });

  it("says so in a sentence rather than leaving a blank", () => {
    // **p.33 attaches a warning to this exact state**, which means people see
    // it and wonder whether the screen is broken. A blank panel and a failed
    // one look identical.
    const said = emptyMessage(usage({ interactions: 0 }));
    expect(said).toContain("No usage");
    expect(said).toContain("30 days");
  });

  it("carries the window from the server rather than saying 30", () => {
    // A screen that hard-coded the sentence would go on saying it after
    // somebody changed the constant.
    expect(emptyMessage(usage({ interactions: 0, window_days: 7 }))).toContain(
      "7 days",
    );
  });

  it("gives the empty sentence as its headline too", () => {
    expect(headline(usage({ interactions: 0 }))).toBe(
      emptyMessage(usage({ interactions: 0 })),
    );
  });
});

describe("the headline", () => {
  it("leads with people, not with the count", () => {
    // **The order is the decision.** p.32 defines the four numbers in one
    // order and they are useful in another: how many people would notice
    // decides whether a rename needs a conversation.
    const said = headline(usage({ active_users: 3, interactions: 12 }));
    expect(said.indexOf("3 people")).toBeLessThan(said.indexOf("12 interactions"));
  });

  it("says one person in the singular", () => {
    // "1 people" is the kind of sentence that makes a reader distrust the rest
    // of the screen.
    expect(headline(usage({ active_users: 1, interactions: 1 }))).toContain(
      "1 person and 1 interaction ",
    );
  });

  it("names the window", () => {
    expect(headline(usage())).toContain("last 30 days");
  });
});

describe("whether a breaking change needs a plan", () => {
  it("asks how many parties, not how many requests", () => {
    // A nightly job reading a type ten thousand times is one caller to fix;
    // two people using it by hand is two conversations, and that is the harder
    // change. p.33 frames the feature as understanding "the implications of
    // making a breaking change".
    expect(hasAudience(usage({ active_users: 1, interactions: 10_000 }))).toBe(false);
    expect(hasAudience(usage({ active_users: 2, interactions: 2 }))).toBe(true);
  });

  it("is false for a type nobody uses", () => {
    expect(hasAudience(usage({ active_users: 0, interactions: 0 }))).toBe(false);
  });
});

describe("one application's row", () => {
  it("names writes separately when there are any", () => {
    // Writes are the half that makes a change dangerous: a reader breaks
    // visibly at the next deploy, a writer can be corrupting data against a
    // shape that has moved.
    expect(applicationSummary(app({ reads: 4, writes: 2 }))).toBe("4 reads, 2 writes");
  });

  it("says nothing about writes when there are none", () => {
    // A trailing ", 0 writes" on every read-only row is noise that makes the
    // rows that do write harder to spot.
    expect(applicationSummary(app({ reads: 4, writes: 0 }))).toBe("4 reads");
  });

  it("counts one in the singular on both halves", () => {
    expect(applicationSummary(app({ reads: 1, writes: 1 }))).toBe("1 read, 1 write");
  });
});

describe("what an application is called", () => {
  it("gives the ones this product has a name for", () => {
    expect(applicationLabel("explorer")).toBe("Object Explorer");
    expect(applicationLabel("workshop")).toBe("Workshop");
  });

  it("shows an unlabelled one as it was recorded", () => {
    // **Not "Unknown".** A row labelled `some_screen` is a screen somebody can
    // go and look for; a row labelled "Unknown" is one nobody can.
    expect(applicationLabel("some_screen")).toBe("some_screen");
  });

  it("has a label for every application the server records", () => {
    // The server's `APPLICATIONS` tuple, written out rather than imported —
    // there is no import across the two languages, and a list derived from the
    // map under test would agree with it by construction.
    for (const known of ["explorer", "object_view", "workshop", "action", "api"]) {
      expect(APPLICATION_LABELS[known], `no label for ${known}`).toBeTruthy();
    }
  });

  it("does not label the one the server excludes", () => {
    // p.32: "any object type or link type usage happening in Ontology Manager
    // is not included." A label for it would be a row that can never appear,
    // and the next person to read this file would go looking for the bug.
    expect(APPLICATION_LABELS.ontology_manager).toBeUndefined();
  });
});
