import { describe, expect, it } from "vitest";
import {
  declaredTypes,
  emptyNote,
  hasOffer,
  labelOf,
  offerFor,
  truncationNote,
  untypedNote,
  type ParameterChoices,
} from "./action-choices";

function offer(over: Partial<ParameterChoices> = {}): ParameterChoices {
  return {
    parameter: "team",
    object_type_id: "t-1",
    object_type_name: "Team",
    items: [
      { id: "o-1", primary_key: "alpha", label: "Alpha team" },
      { id: "o-2", primary_key: "beta", label: "Beta team" },
    ],
    truncated: false,
    ...over,
  };
}

describe("offerFor", () => {
  it("finds the offer for a parameter", () => {
    expect(offerFor("team", [offer()])?.object_type_name).toBe("Team");
  });

  it("is null for a parameter nothing was said about", () => {
    // **Not an empty list.** No offer means nobody declared what this
    // parameter holds, so the text box stands; an empty offer means the type
    // is known and has no objects, which is a thing to say out loud.
    expect(offerFor("owner", [offer()])).toBeNull();
    expect(offerFor("team", undefined)).toBeNull();
    expect(offerFor("team", [])).toBeNull();
  });

  it("tells an empty offer apart from no offer", () => {
    expect(offerFor("team", [offer({ items: [] })])).not.toBeNull();
  });
});

describe("hasOffer", () => {
  it("is how the form decides between a dropdown and a text box", () => {
    expect(hasOffer("team", [offer()])).toBe(true);
    expect(hasOffer("team", [offer({ items: [] })])).toBe(true);
    expect(hasOffer("owner", [offer()])).toBe(false);
  });
});

describe("labelOf", () => {
  it("uses the title property", () => {
    expect(labelOf({ id: "o-1", primary_key: "alpha", label: "Alpha team" }))
      .toBe("Alpha team");
  });

  it("falls back to the primary key", () => {
    // A dropdown of uuids would be the text box with extra steps.
    expect(labelOf({ id: "o-1", primary_key: "alpha", label: "" })).toBe("alpha");
    expect(labelOf({ id: "o-1", primary_key: "alpha", label: "   " })).toBe("alpha");
  });
});

describe("truncationNote", () => {
  it("says nothing when the control holds everything", () => {
    expect(truncationNote(offer())).toBeNull();
    expect(truncationNote(null)).toBeNull();
  });

  it("says how many are shown and what to do about it", () => {
    // §256's rule one control down: somebody picking from a control that
    // quietly held the first fifty of a thousand would never learn the rest
    // existed. The fix is p.36's filter, which is what this points at.
    const note = truncationNote(offer({ truncated: true }));
    expect(note).toContain("first 2");
    expect(note).toContain("Team");
    expect(note).toContain("filter");
  });
});

describe("emptyNote", () => {
  it("says nothing when there is something to choose", () => {
    expect(emptyNote(offer())).toBeNull();
  });

  it("says nothing when there is no offer at all", () => {
    // That parameter is drawing a text box; a sentence about an empty dropdown
    // would be about a control that is not on screen.
    expect(emptyNote(null)).toBeNull();
  });

  it("names the type when the dropdown would be empty", () => {
    // §214: an empty dropdown is a control that looks like it works — somebody
    // opens it, finds nothing, and cannot tell whether the list failed to load.
    expect(emptyNote(offer({ items: [] }))).toContain("Team");
  });
});

describe("declaredTypes", () => {
  it("reads the declaration, keyed by api_name", () => {
    expect(declaredTypes([
      { api_name: "team", data_type: "object", object_type_id: "t-1" },
      { api_name: "note", data_type: "string" },
    ])).toEqual({ team: "t-1" });
  });

  it("says nothing about an object parameter nobody typed", () => {
    expect(declaredTypes([
      { api_name: "team", data_type: "object", object_type_id: null },
    ])).toEqual({});
  });

  it("ignores a type on something that is not an object parameter", () => {
    // The server refuses one; this is the editor not showing a setting that
    // could not have been saved.
    expect(declaredTypes([
      { api_name: "note", data_type: "string", object_type_id: "t-1" },
    ])).toEqual({});
  });
});

describe("untypedNote", () => {
  it("says nothing about a typed parameter", () => {
    expect(untypedNote({ data_type: "object", object_type_id: "t-1" })).toBeNull();
  });

  it("says nothing about a parameter that is not an object", () => {
    expect(untypedNote({ data_type: "string" })).toBeNull();
  });

  it("says what declaring the type would buy, without calling it wrong", () => {
    // Not a refusal: every action written before §330 is in this state and
    // works exactly as it did.
    const note = untypedNote({ data_type: "object", object_type_id: null });
    expect(note).toContain("dropdown");
    expect(note).toContain("checked before the action runs");
    expect(note).not.toMatch(/error|invalid|must/i);
  });
});
