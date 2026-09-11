import { describe, expect, it } from "vitest";

import {
  ISSUE_FILTER_OPTIONS,
  issue,
  issueDetail,
  issueIsAnError,
  issueLabel,
} from "./object-type-issues";
import type { ObjectTypeSummary } from "./types";

function type(over: Partial<ObjectTypeSummary> = {}): ObjectTypeSummary {
  return {
    id: "t-1",
    api_name: "site",
    display_name: "Site",
    description: "",
    icon: "",
    colour: "",
    title_property_id: null,
    source_count: 1,
    failing_source_count: 0,
    source_error: null,
    hidden_properties: [],
    resource_id: "r-1",
    status: "experimental",
    deprecation: null,
    groups: [],
    interfaces: [],
    visibility: "normal",
    ...over,
  } as ObjectTypeSummary;
}

describe("what is wrong with a type", () => {
  it("says nothing about a type with a working source", () => {
    expect(issue(type())).toBe("none");
    expect(issueLabel(type())).toBeNull();
    expect(issueDetail(type())).toBeNull();
  });

  it("tells a type nobody has sourced from one that broke", () => {
    // p.29 names both conditions, and they are different problems with
    // different remedies.
    expect(issue(type({ source_count: 0 }))).toBe("unsourced");
    expect(issue(type({ failing_source_count: 1 }))).toBe("failing");
  });

  it("lets a failure outrank an unsourced type", () => {
    expect(issue(type({ source_count: 0, failing_source_count: 1 }))).toBe("failing");
  });
});

describe("what the column says", () => {
  it("counts the failing sources, one in the singular", () => {
    expect(issueLabel(type({ failing_source_count: 1 }))).toBe("1 source failing");
    expect(issueLabel(type({ source_count: 3, failing_source_count: 2 })))
      .toBe("2 sources failing");
  });

  it("names an unsourced type without calling it a failure", () => {
    expect(issueLabel(type({ source_count: 0 }))).toBe("No source");
  });

  it("is red only for a real failure", () => {
    // A type nobody has pointed at data yet is the ordinary state of one
    // somebody is still building. Red on every new type is a column people
    // learn to ignore, which is worse than not having it.
    expect(issueIsAnError(type({ failing_source_count: 1 }))).toBe(true);
    expect(issueIsAnError(type({ source_count: 0 }))).toBe(false);
    expect(issueIsAnError(type())).toBe(false);
  });
});

describe("the hover", () => {
  it("carries the failure's own words", () => {
    // "This type has an issue" is a fact nobody can act on.
    expect(issueDetail(type({ failing_source_count: 1, source_error: "column gone" })))
      .toBe("column gone");
  });

  it("says something useful when the sync gave no reason", () => {
    const said = issueDetail(type({ failing_source_count: 1, source_error: null }));
    expect(said).toContain("could not be loaded");
    expect(said).not.toBe("");
  });

  it("tells an unsourced type what to do about it", () => {
    expect(issueDetail(type({ source_count: 0 }))).toContain("Add a source");
  });
});

describe("the filter beside the column", () => {
  it("offers the server's whole vocabulary and nothing else", () => {
    // `TYPE_ISSUES` in `ontology.py` refuses anything outside these three, so
    // an option this list gained and the server did not is a control that
    // returns a 422 — and one the server gained and this did not is a filter
    // nobody can reach.
    expect(ISSUE_FILTER_OPTIONS.map((o) => o.value)).toEqual([
      "",
      "any",
      "failing",
      "unsourced",
    ]);
  });

  it("starts unfiltered", () => {
    // The first option is what the page opens on, and a filter that starts
    // narrowed hides rows from somebody who never chose to hide them.
    expect(ISSUE_FILTER_OPTIONS[0]!.value).toBe("");
  });

  it("does not name the unfiltered option with the word `any` uses", () => {
    // **The bug this list exists to prevent.** Beside "Any status" and "Any
    // visibility", the natural fourth is "Any issue" — which reads both as
    // *do not filter* and as *has any issue*, and the second of those is what
    // the option below it does. The reader who picks the wrong one gets a
    // plausible list and no sign of the mistake.
    const unfiltered = ISSUE_FILTER_OPTIONS[0]!.label;
    const any = ISSUE_FILTER_OPTIONS.find((o) => o.value === "any")!.label;
    expect(unfiltered).not.toBe("Any issue");
    expect(any.toLowerCase()).not.toContain("any");
  });

  it("gives every option its own label", () => {
    // Two options a chooser draws identically are one option and a bug.
    const labels = ISSUE_FILTER_OPTIONS.map((o) => o.label);
    expect(new Set(labels).size).toBe(labels.length);
    for (const label of labels) expect(label.trim()).not.toBe("");
  });

  it("calls the unsourced state what the column calls it", () => {
    // Somebody filters by what they read in the cell. A filter whose wording
    // drifts from the column's is one people have to learn twice.
    const unsourced = ISSUE_FILTER_OPTIONS.find((o) => o.value === "unsourced")!;
    expect(unsourced.label).toBe(issueLabel(type({ source_count: 0 })));
  });
});
