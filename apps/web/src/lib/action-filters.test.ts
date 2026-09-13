import { describe, expect, it } from "vitest";
import {
  blankFilter,
  filterKey,
  filterParameters,
  filterSummary,
  isWaiting,
  readableParameters,
  staticValueWarning,
  waitingNote,
  type DropdownFilter,
} from "./action-filters";
import type { ParameterChoices } from "./action-choices";

const statically = (property: string, ...values: unknown[]): DropdownFilter => ({
  property,
  values: values.map((value) => ({ kind: "value", value })),
});

const fromParameter = (property: string, parameter: string): DropdownFilter => ({
  property,
  values: [{ kind: "parameter", parameter }],
});

function parameter(over: Partial<{
  api_name: string; data_type: string; dropdown_watches: string[];
}> = {}) {
  return {
    api_name: "team", data_type: "object", dropdown_watches: [], ...over,
  };
}

function offer(over: Partial<ParameterChoices> = {}): ParameterChoices {
  return {
    parameter: "team", object_type_id: "t-1", object_type_name: "Team",
    items: [], truncated: false, ...over,
  };
}

describe("filterParameters", () => {
  it("is empty when nothing reads a parameter", () => {
    // A form whose object parameters carry no filters asks exactly once, when
    // it opens.
    expect(filterParameters([parameter()])).toEqual([]);
  });

  // **Withdrawn (§332), and this is the reasoning §213 asks be left in its
  // place.** There used to be a test here that a value whose `kind` is not
  // `"parameter"` is not watched — the fourth copy of a guard §328, §329 and
  // §331 each needed. It is gone because this function no longer reads a
  // filter: the kinds are the server's business now (`referenced_parameters`,
  // and `test_referenced_parameters_ignores_a_side_whose_kind_is_not_a_parameter`
  // is that check, still failing when the guard goes). A copy here would assert
  // over an argument this module is never handed.

  it("names what the server said the dropdown reads", () => {
    // **Told, not worked out.** The filters are redacted for anyone who may not
    // edit the action (p.40-41), so a version of this that walked them returned
    // nothing for exactly the readers who fill the form in — and their dropdown
    // never re-asked. The names come down whole and this only merges them.
    expect(filterParameters([
      parameter({ dropdown_watches: ["where"] }),
      parameter({ api_name: "owner", dropdown_watches: ["level"] }),
    ])).toEqual(["level", "where"]);
  });

  it("says each name once, however many dropdowns read it", () => {
    // Two controls narrowed by the same box is one value to watch, and a key
    // that listed it twice would still be right — until it is compared with one
    // built from a document that happens to order them differently.
    expect(filterParameters([
      parameter({ dropdown_watches: ["where"] }),
      parameter({ api_name: "owner", dropdown_watches: ["where"] }),
    ])).toEqual(["where"]);
  });

  it("survives a parameter the server said nothing about", () => {
    // Every parameter written before §332 — and every non-object one, which is
    // most of a form.
    expect(filterParameters([{ api_name: "note", data_type: "string" }]))
      .toEqual([]);
  });
});

describe("filterKey", () => {
  it("changes when a value a filter reads changes", () => {
    const p = [parameter({ dropdown_watches: ["where"] })];
    expect(filterKey(p, { where: "eu" })).not.toBe(filterKey(p, { where: "uk" }));
  });

  it("does not change when an unread value changes", () => {
    // The reason typing in a plain field is not a round trip.
    const p = [parameter({ dropdown_watches: ["where"] })];
    expect(filterKey(p, { where: "eu", note: "a" }))
      .toBe(filterKey(p, { where: "eu", note: "b" }));
  });

  it("is one key for a form with no parameter-reading filters", () => {
    expect(filterKey([parameter()], { where: "eu" }))
      .toBe(filterKey([parameter()], { where: "uk" }));
  });
});

describe("waitingNote", () => {
  it("says nothing when the offer is not waiting", () => {
    expect(waitingNote(offer({ items: [] }), {})).toBeNull();
    expect(waitingNote(null, {})).toBeNull();
  });

  it("names the box to fill in first, by its label", () => {
    // The person reading this is looking at a form, and the form says
    // "Region", not "region".
    const note = waitingNote(
      offer({ waiting_for: "where" } as Partial<ParameterChoices>),
      { where: "Region" },
    );
    expect(note).toContain("Region");
    expect(note).toContain("first");
  });

  it("falls back to the api name when there is no label", () => {
    expect(waitingNote(
      offer({ waiting_for: "where" } as Partial<ParameterChoices>), {},
    )).toContain("where");
  });
});

describe("isWaiting", () => {
  it("tells an empty-because-waiting offer from an empty-because-empty one", () => {
    // The two look identical on screen and are different things to be told:
    // "there are no Teams" is false and unhelpful when the truth is "you have
    // not said which region".
    expect(isWaiting(offer({ items: [] }))).toBe(false);
    expect(isWaiting(offer({ waiting_for: "where" } as Partial<ParameterChoices>)))
      .toBe(true);
    expect(isWaiting(null)).toBe(false);
  });
});

describe("blankFilter", () => {
  it("arrives with a value row to fill in", () => {
    // The server refuses a filter with no values, so starting somebody in a
    // state it will not save would be §214's control that looks like it works.
    expect(blankFilter().values).toHaveLength(1);
    expect(blankFilter().values[0]).toEqual({ kind: "value", value: "" });
  });
});

describe("filterSummary", () => {
  it("reads as p.36 does for one value", () => {
    expect(filterSummary(statically("region", "eu"), {}))
      .toBe('region is "eu"');
  });

  it("says any of for several, which is p.36's OR", () => {
    expect(filterSummary(statically("region", "eu", "uk"), {}))
      .toContain("any of");
  });

  it("shows a parameter by its label rather than its api name", () => {
    expect(filterSummary(fromParameter("region", "where"), { where: "Region" }))
      .toBe("region is Region");
  });

  it("says so when a half-written filter has no property", () => {
    expect(filterSummary({ property: "", values: [] }, {}))
      .toContain("no property");
  });

  it("says so when it has no values", () => {
    expect(filterSummary(statically("region"), {})).toContain("nothing yet");
  });
});

describe("readableParameters", () => {
  const all = [{ api_name: "team" }, { api_name: "where" }, { api_name: "note" }];

  it("offers the other parameters", () => {
    expect(readableParameters(all, "team")).toEqual(["where", "note"]);
  });

  it("never offers the parameter itself", () => {
    // The dropdown would depend on the value it is offering. The server
    // refuses it; this is why nobody meets that refusal by the obvious route.
    expect(readableParameters(all, "where")).not.toContain("where");
  });
});

describe("staticValueWarning", () => {
  it("says nothing when every value comes from a parameter", () => {
    // p.41 is explicit that this carries no risk: "no information about the
    // underlying data is exposed to the action type viewer". A warning on
    // every filter is one nobody reads by the third.
    expect(staticValueWarning([fromParameter("region", "where")])).toBeNull();
    expect(staticValueWarning([])).toBeNull();
  });

  it("warns about a typed-in value, and says what to do instead", () => {
    // p.40's concern, and p.41's own mitigation — "relying on object
    // properties or parameters to filter the object set".
    const note = staticValueWarning([statically("region", "eu")]);
    expect(note).toContain("edit this action can read it");
    expect(note).toContain("parameter instead");
  });

  it("warns when any filter has a static value, not only the first", () => {
    expect(staticValueWarning([
      fromParameter("region", "where"), statically("tier", "a"),
    ])).not.toBeNull();
  });
});
