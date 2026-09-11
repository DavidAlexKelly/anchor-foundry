import { describe, expect, it } from "vitest";

import {
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
