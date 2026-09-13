import { describe, expect, it } from "vitest";
import {
  blankOptions,
  emptyValuesNote,
  hasValues,
  optionable,
  optionsProblem,
  optionsSummary,
  valuesTruncationNote,
  type ParameterOptions,
} from "./action-options";
import { offerFor, valuesFor, type ParameterChoices } from "./action-choices";

const REGIONS = "t-regions";
const NAMES = { [REGIONS]: "Region" };

function valuesOffer(over: Partial<ParameterChoices> = {}): ParameterChoices {
  return {
    parameter: "region", kind: "values", items: [],
    values: ["EU", "UK"], truncated: false, ...over,
  };
}

function objectOffer(over: Partial<ParameterChoices> = {}): ParameterChoices {
  return {
    parameter: "team", kind: "objects", object_type_id: "t-1",
    object_type_name: "Team", items: [], truncated: false, ...over,
  };
}

const from = (over: Partial<ParameterOptions> = {}): ParameterOptions =>
  ({ object_type_id: REGIONS, property: "label", ...over });

describe("optionable", () => {
  it("is false for an object, which is p.33's other shape", () => {
    // That parameter already has a dropdown (§330). One with both would be two
    // answers to "what may I pick" and no way to say which won.
    expect(optionable("object")).toBe(false);
  });

  it("is false for a type a dropdown cannot show", () => {
    expect(optionable("json")).toBe(false);
    expect(optionable("attachment")).toBe(false);
  });

  it("is true for the ones a person can pick from", () => {
    expect(optionable("string")).toBe(true);
    expect(optionable("integer")).toBe(true);
    expect(optionable("date")).toBe(true);
  });
});

describe("the two offer shapes", () => {
  const both = [objectOffer(), valuesOffer()];

  it("keeps p.33's two shapes apart", () => {
    // **The reason `kind` exists.** Both lists arrive in one response, and a
    // values offer reaching the object lookup would render a dropdown of
    // objects that are not there.
    expect(offerFor("team", both)?.object_type_name).toBe("Team");
    expect(offerFor("region", both)).toBeNull();
    expect(valuesFor("region", both)?.values).toEqual(["EU", "UK"]);
    expect(valuesFor("team", both)).toBeNull();
  });

  it("reads an offer with no kind as an object one", () => {
    // Every payload that predates §335.
    const legacy = { ...objectOffer(), kind: undefined };
    expect(offerFor("team", [legacy as ParameterChoices])).not.toBeNull();
    expect(valuesFor("team", [legacy as ParameterChoices])).toBeNull();
  });

  it("tells a values offer apart from no offer at all", () => {
    expect(hasValues(valuesOffer())).toBe(true);
    expect(hasValues(objectOffer())).toBe(false);
    expect(hasValues(null)).toBe(false);
  });
});

describe("emptyValuesNote", () => {
  it("says nothing when there is something to choose", () => {
    expect(emptyValuesNote(valuesOffer())).toBeNull();
  });

  it("says nothing about a parameter with no derived list", () => {
    // That parameter is drawing a text box, and a sentence about an empty
    // dropdown would be about a control that is not on screen.
    expect(emptyValuesNote(null)).toBeNull();
    expect(emptyValuesNote(objectOffer())).toBeNull();
  });

  it("names why the list is empty rather than leaving a blank control", () => {
    // §214: somebody opens it, finds nothing, and cannot tell whether the list
    // failed to load. The truth here is actionable and a blank control is not.
    const note = emptyValuesNote(valuesOffer({ values: [] }));
    expect(note).toContain("property");
    expect(note).toContain("nothing to choose");
  });
});

describe("valuesTruncationNote", () => {
  it("says nothing when the control holds everything", () => {
    expect(valuesTruncationNote(valuesOffer())).toBeNull();
    expect(valuesTruncationNote(null)).toBeNull();
  });

  it("says nothing for an object offer, which has its own sentence", () => {
    // The object note names the *type* ("the first 50 Teams") and this one
    // cannot, because a values offer is about a property.
    expect(valuesTruncationNote(objectOffer({ truncated: true }))).toBeNull();
  });

  it("says how many are shown", () => {
    const note = valuesTruncationNote(valuesOffer({ truncated: true }));
    expect(note).toContain("first 2");
    expect(note).toContain("more");
  });
});

describe("blankOptions", () => {
  it("opens with nothing chosen, because p.33 has no default set", () => {
    // Unlike §333's blank walk, which starts somewhere saveable: a walk has a
    // sensible default and an object set does not, so seeding a type would put
    // one nobody chose in front of an editor.
    expect(blankOptions()).toEqual({ object_type_id: "", property: "" });
  });
});

describe("optionsSummary", () => {
  it("says what a parameter with no document does", () => {
    expect(optionsSummary(null, NAMES)).toBe("Whatever is typed in");
  });

  it("reads as p.33 does, a property of a type", () => {
    expect(optionsSummary(from(), NAMES)).toBe("The label of every Region");
  });

  it("says what is still missing when only the type is chosen", () => {
    const note = optionsSummary(from({ property: "" }), NAMES);
    expect(note).toContain("Region");
    expect(note).toContain("not yet chosen");
  });

  it("falls back when the type is one the editor has no name for", () => {
    // Names come off the links the editor already loaded, so a type no link
    // touches has none — and "The label of every undefined" is the sentence
    // that gets written when that is not handled.
    expect(optionsSummary(from(), {})).not.toContain("undefined");
  });
});

describe("optionsProblem", () => {
  it("says nothing about a parameter with no document", () => {
    expect(optionsProblem(null, "string")).toBeNull();
  });

  it("says nothing about a complete one", () => {
    expect(optionsProblem(from(), "string")).toBeNull();
  });

  it("points an object parameter at the dropdown it already has", () => {
    // The more useful sentence: the answer is not "you cannot" but "you have
    // one" (§330).
    const note = optionsProblem(from(), "object");
    expect(note).toContain("objects it may be set to");
  });

  it("names a type that cannot be a list at all", () => {
    expect(optionsProblem(from(), "attachment")).toContain("attachment");
  });

  it("asks for the type before the property", () => {
    // In that order, because choosing a property needs a type to read it from
    // — and the panel does not draw the property control until there is one.
    expect(optionsProblem(from({ object_type_id: "", property: "" }), "string"))
      .toContain("object type");
  });

  it("asks for the property once the type is chosen", () => {
    expect(optionsProblem(from({ property: "" }), "string"))
      .toContain("property");
  });
});
