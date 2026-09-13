import { describe, expect, it } from "vitest";
import {
  blankSearchAround,
  landingNote,
  landsOn,
  landsWhereItShould,
  nextHops,
  reaches,
  sourceSummary,
  startableParameters,
  traversable,
  type LinkType,
  type SearchAround,
} from "./action-search-arounds";

const EMPLOYEE = "t-emp";
const ISSUE = "t-iss";
const REPO = "t-repo";

const raisedBy: LinkType = {
  id: "l-1", display_name: "Raised by",
  from_object_type_id: ISSUE, to_object_type_id: EMPLOYEE,
  from_property: "employee_id", to_property: "$primary_key",
};
const inRepo: LinkType = {
  id: "l-2", display_name: "In repo",
  from_object_type_id: ISSUE, to_object_type_id: REPO,
  from_property: "repo_id", to_property: "$primary_key",
};
const unjoined: LinkType = {
  id: "l-3", display_name: "Vaguely related",
  from_object_type_id: EMPLOYEE, to_object_type_id: REPO,
  from_property: "", to_property: "",
};
const LINKS = [raisedBy, inRepo, unjoined];
const NAMES = { [EMPLOYEE]: "Employee", [ISSUE]: "Github Issue", [REPO]: "Repo" };

const walk = (start: SearchAround["start"], ...hops: string[]): SearchAround =>
  ({ start, hops: hops.map((link_type_id) => ({ link_type_id })) });

const fromType = (id = EMPLOYEE): SearchAround["start"] =>
  ({ kind: "object_type", object_type_id: id });
const fromParameter = (parameter = "who", id = EMPLOYEE): SearchAround["start"] =>
  ({ kind: "parameter", object_type_id: id, parameter });

describe("reaches", () => {
  it("goes both ways, because the walk decides the direction", () => {
    // The browser's copy of `object_sets.far_end`. A document never names a
    // direction, so it can never name the wrong one — which is only true if
    // this reads the link from whichever end the walk has arrived at.
    expect(reaches(raisedBy, ISSUE)).toBe(EMPLOYEE);
    expect(reaches(raisedBy, EMPLOYEE)).toBe(ISSUE);
  });

  it("is null for a link that touches neither end", () => {
    expect(reaches(raisedBy, REPO)).toBeNull();
  });
});

describe("traversable", () => {
  it("refuses a link type with no join", () => {
    // db 0027 lets one be defined and not followed. Offering it is a hop
    // somebody picks and the server refuses with a sentence about columns.
    expect(traversable(unjoined)).toBe(false);
    expect(traversable(raisedBy)).toBe(true);
  });
});

describe("landsOn", () => {
  it("is the start when there is nothing to walk", () => {
    expect(landsOn(walk(fromType()), LINKS)).toBe(EMPLOYEE);
  });

  it("follows p.37's example to the far side", () => {
    expect(landsOn(walk(fromType(), "l-1"), LINKS)).toBe(ISSUE);
  });

  it("keeps walking, so a second hop reads from where the first arrived", () => {
    // Employee → Issue → Repo. A version that always read from the *start*
    // would answer the same for one hop and be wrong here.
    expect(landsOn(walk(fromType(), "l-1", "l-2"), LINKS)).toBe(REPO);
  });

  it("is null as soon as a hop does not join up", () => {
    // A stored document is never in this state, but one being edited is
    // constantly: changing the starting type is one click and invalidates
    // every hop below it.
    expect(landsOn(walk(fromType(REPO), "l-1"), LINKS)).toBeNull();
  });

  it("is null for a link this workspace does not have", () => {
    expect(landsOn(walk(fromType(), "l-gone"), LINKS)).toBeNull();
  });

  it("is null when there is no walk at all", () => {
    expect(landsOn(null, LINKS)).toBeNull();
  });
});

describe("nextHops", () => {
  it("offers only links that touch where the walk has reached", () => {
    const offered = nextHops(walk(fromType()), LINKS).map((l) => l.id);
    // From an Employee: "Raised by" touches it, "In repo" does not, and
    // "Vaguely related" does but cannot be followed.
    expect(offered).toEqual(["l-1"]);
  });

  it("changes as the walk moves", () => {
    expect(nextHops(walk(fromType(), "l-1"), LINKS).map((l) => l.id))
      .toEqual(["l-1", "l-2"]);
  });

  it("offers nothing once the walk is broken", () => {
    // Rather than every link in the workspace: a hop that cannot be added to
    // *this* walk is §214's control that looks like it works.
    expect(nextHops(walk(fromType(REPO), "l-1"), LINKS)).toEqual([]);
  });
});

describe("landsWhereItShould", () => {
  it("is true when there is no walk, which is p.36's default", () => {
    expect(landsWhereItShould(null, LINKS, ISSUE)).toBe(true);
  });

  it("is true when the walk ends where the parameter holds", () => {
    expect(landsWhereItShould(walk(fromType(), "l-1"), LINKS, ISSUE)).toBe(true);
  });

  it("is false when it ends anywhere else", () => {
    expect(landsWhereItShould(walk(fromType(), "l-1"), LINKS, REPO)).toBe(false);
  });

  it("is false when the parameter says nothing about its type", () => {
    // A walk with nowhere to land cannot be checked, and the server refuses
    // this pair outright.
    expect(landsWhereItShould(walk(fromType(), "l-1"), LINKS, null)).toBe(false);
  });
});

describe("blankSearchAround", () => {
  it("opens in a state the server will save", () => {
    // p.36's default written out. Starting somebody at a type the walk cannot
    // land on would be a panel that opens refusing to save (§214).
    const blank = blankSearchAround(ISSUE);
    expect(blank).toEqual({
      start: { kind: "object_type", object_type_id: ISSUE }, hops: [],
    });
    expect(landsWhereItShould(blank, LINKS, ISSUE)).toBe(true);
  });
});

describe("sourceSummary", () => {
  it("says what the default is, without a document", () => {
    expect(sourceSummary(null, LINKS, NAMES, {})).toBe("Every object of this type");
  });

  it("names the starting type", () => {
    expect(sourceSummary(walk(fromType()), LINKS, NAMES, {}))
      .toBe("Start from every Employee");
  });

  it("reads as p.37 does, near thing then link", () => {
    expect(sourceSummary(walk(fromType(), "l-1"), LINKS, NAMES, {}))
      .toBe("Start from every Employee, then follow Raised by");
  });

  it("names every hop, not only the first", () => {
    expect(sourceSummary(walk(fromType(), "l-1", "l-2"), LINKS, NAMES, {}))
      .toContain("follow Raised by, then In repo");
  });

  it("shows a parameter start by its label", () => {
    // The person reading this is looking at a form, and the form says "Who",
    // not "who".
    expect(sourceSummary(walk(fromParameter()), LINKS, NAMES, { who: "Who" }))
      .toBe("Start from the Who chosen above");
  });

  it("falls back to the api name when there is no label", () => {
    expect(sourceSummary(walk(fromParameter()), LINKS, NAMES, {}))
      .toContain("who");
  });
});

describe("landingNote", () => {
  it("says nothing when the walk is right", () => {
    expect(landingNote(walk(fromType(), "l-1"), LINKS, ISSUE, NAMES)).toBeNull();
    expect(landingNote(null, LINKS, ISSUE, NAMES)).toBeNull();
  });

  it("names both ends when it lands elsewhere", () => {
    // "This is wrong" without them leaves somebody comparing two dropdowns of
    // type names by eye.
    const note = landingNote(walk(fromType(), "l-1"), LINKS, REPO, NAMES);
    expect(note).toContain("Github Issue");
    expect(note).toContain("Repo");
  });

  it("says something different when the walk does not join up", () => {
    // A broken walk has no landing type to name, and "reaches undefined" is
    // the sentence that gets written when that is not said separately.
    const note = landingNote(walk(fromType(REPO), "l-1"), LINKS, ISSUE, NAMES);
    expect(note).toContain("does not join up");
    expect(note).not.toContain("undefined");
  });
});

describe("startableParameters", () => {
  const all = [
    { api_name: "issue", data_type: "object", object_type_id: ISSUE },
    { api_name: "who", data_type: "object", object_type_id: EMPLOYEE },
    // **A string that still carries a type**, which is the only input that
    // tells "is it an object parameter" apart from "does it have a type" — the
    // server refuses this pair, but the dialog is in it the moment somebody
    // changes a parameter from object to string. A sweep found the two
    // conditions indistinguishable without it.
    { api_name: "note", data_type: "string", object_type_id: EMPLOYEE },
    { api_name: "untyped", data_type: "object", object_type_id: null },
  ];

  it("offers the other object parameters, with their types", () => {
    expect(startableParameters(all, "issue"))
      .toEqual([{ api_name: "who", object_type_id: EMPLOYEE }]);
  });

  it("never offers the parameter itself", () => {
    // The dropdown would walk from the value it is offering.
    expect(startableParameters(all, "who").map((p) => p.api_name))
      .not.toContain("who");
  });

  it("does not offer a string parameter", () => {
    // p.36 says an ObjectReference. Starting from a string would treat
    // whatever somebody typed as an object's key.
    expect(startableParameters(all, "issue").map((p) => p.api_name))
      .not.toContain("note");
  });

  it("does not offer an object parameter nobody typed", () => {
    // There is no type to walk from, so the server would refuse it.
    expect(startableParameters(all, "issue").map((p) => p.api_name))
      .not.toContain("untyped");
  });
});
