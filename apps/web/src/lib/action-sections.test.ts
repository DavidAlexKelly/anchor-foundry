import { describe, expect, it } from "vitest";
import {
  availableParameters,
  blankSection,
  collapsedInitially,
  columnsLabel,
  columnsOf,
  conditionDraft,
  conditionValue,
  forgetParameters,
  renameParameter,
  conditionKey,
  conditionParameters,
  drawnSections,
  formLayout,
  moveSection,
  placeParameter,
  removeParameter,
  requiredElsewhere,
  sectionSummary,
  unreachableNote,
  type FormParameter,
  type FormSection,
} from "./action-sections";

function section(over: Partial<FormSection> = {}): FormSection {
  return {
    id: over.id ?? "s1",
    title: "Details",
    description: "",
    columns: 1,
    collapsible: false,
    collapsed: false,
    hidden: false,
    visible_when: null,
    parameters: [],
    ...over,
  };
}

const when = (parameter: string, value: unknown) => ({
  left: { kind: "parameter", parameter },
  operator: "is",
  right: { kind: "value", value },
});

const PARAMETERS: FormParameter[] = [
  { api_name: "status", display_name: "Status", required: true },
  { api_name: "reason", display_name: "Reason" },
  { api_name: "owner", display_name: "Owner" },
  { api_name: "trace", display_name: "Trace", hidden: true },
];

describe("conditionParameters", () => {
  it("is empty for a form nothing is conditional on", () => {
    expect(conditionParameters([section(), section({ id: "s2" })])).toEqual([]);
  });

  it("names the parameters a condition reads, on either side", () => {
    expect(conditionParameters([
      section({ visible_when: when("status", "closed") }),
      section({
        id: "s2",
        visible_when: {
          left: { kind: "parameter", parameter: "owner" },
          operator: "is",
          right: { kind: "parameter", parameter: "assignee" },
        },
      }),
    ])).toEqual(["assignee", "owner", "status"]);
  });

  it("says nothing about a condition that reads the current user", () => {
    // Who is asking does not change while a form is open, so there is nothing
    // here to watch — the server answered that question once.
    expect(conditionParameters([section({
      visible_when: {
        left: { kind: "current_user", attribute: "id" },
        operator: "is",
        right: { kind: "value", value: "u1" },
      },
    })])).toEqual([]);
  });

  it("ignores a hidden section's condition", () => {
    // "Hidden entirely" wins, so the condition cannot change anything and a
    // form of hidden sections still makes no round trip.
    expect(conditionParameters([
      section({ hidden: true, visible_when: when("status", "closed") }),
    ])).toEqual([]);
  });

  it("still names the parameters of a condition it cannot read", () => {
    // The point of this function is that it reads the document's *shape*. An
    // operator this build has never heard of is the server's problem, and the
    // form must still ask about it rather than decide the section is static.
    expect(conditionParameters([section({
      visible_when: {
        left: { kind: "parameter", parameter: "status" },
        operator: "is_a_haiku",
        right: { kind: "value", value: 1 },
      },
    })])).toEqual(["status"]);
  });
});

describe("conditionKey", () => {
  it("is empty when nothing is conditional, which is how the form knows not to ask", () => {
    expect(conditionKey([section()], { status: "open" })).toBe("");
  });

  it("changes when a named value changes", () => {
    const s = [section({ visible_when: when("status", "closed") })];
    expect(conditionKey(s, { status: "open" }))
      .not.toBe(conditionKey(s, { status: "closed" }));
  });

  it("does not change when an unnamed value changes", () => {
    // The reason typing in a plain field is not a round trip.
    const s = [section({ visible_when: when("status", "closed") })];
    expect(conditionKey(s, { status: "open", reason: "a" }))
      .toBe(conditionKey(s, { status: "open", reason: "b" }));
  });

  it("tells a missing value apart from nothing in particular", () => {
    const s = [section({ visible_when: when("status", "closed") })];
    expect(conditionKey(s, {})).toBe(conditionKey(s, { status: null }));
    expect(conditionKey(s, {})).not.toBe(conditionKey(s, { status: "" }));
  });
});

describe("drawnSections", () => {
  const plain = section({ id: "plain" });
  const conditional = section({ id: "cond", visible_when: when("status", "closed") });
  const gone = section({ id: "gone", hidden: true });

  it("draws a plain section whether or not an answer has arrived", () => {
    expect(drawnSections([plain], undefined).map((s) => s.id)).toEqual(["plain"]);
    expect(drawnSections([plain], []).map((s) => s.id)).toEqual(["plain"]);
  });

  it("never draws a hidden section, even one the server named", () => {
    expect(drawnSections([gone], ["gone"])).toEqual([]);
  });

  it("draws a conditional section only when the answer names it", () => {
    expect(drawnSections([conditional], ["cond"]).map((s) => s.id)).toEqual(["cond"]);
    expect(drawnSections([conditional], [])).toEqual([]);
  });

  it("holds a conditional section back until an answer arrives", () => {
    // p.123's own wording: "hidden at first and only shown based on a prior
    // parameter". Drawing it while the question is in flight would put the
    // boxes on screen and take them away a moment later.
    expect(drawnSections([conditional], undefined)).toEqual([]);
  });
});

describe("formLayout", () => {
  it("leaves an unsectioned parameter in the body", () => {
    const layout = formLayout(PARAMETERS, [], undefined);
    expect(layout.loose.map((p) => p.api_name)).toEqual(["status", "reason", "owner"]);
    expect(layout.sections).toEqual([]);
  });

  it("never draws p.25's hidden parameter, in a section or out of one", () => {
    const layout = formLayout(
      PARAMETERS, [section({ parameters: ["trace", "owner"] })], undefined,
    );
    expect(layout.loose.map((p) => p.api_name)).not.toContain("trace");
    expect(layout.sections[0]!.parameters.map((p) => p.api_name)).toEqual(["owner"]);
  });

  it("takes a sectioned parameter out of the body", () => {
    const layout = formLayout(
      PARAMETERS, [section({ parameters: ["reason"] })], undefined,
    );
    expect(layout.loose.map((p) => p.api_name)).toEqual(["status", "owner"]);
    expect(layout.sections[0]!.parameters.map((p) => p.api_name)).toEqual(["reason"]);
  });

  it("does not return a hidden section's parameter to the body", () => {
    // **The one way p.123's hiding could be undone by accident.** A parameter
    // that fell back to the form body when its section was hidden would be
    // drawn exactly where the section was meant to keep it from.
    const layout = formLayout(
      PARAMETERS,
      [section({ hidden: true, parameters: ["reason"] })],
      undefined,
    );
    expect(layout.loose.map((p) => p.api_name)).toEqual(["status", "owner"]);
    expect(layout.sections).toEqual([]);
  });

  it("keeps the order the section names its parameters in", () => {
    const layout = formLayout(
      PARAMETERS, [section({ parameters: ["owner", "status"] })], undefined,
    );
    expect(layout.sections[0]!.parameters.map((p) => p.api_name))
      .toEqual(["owner", "status"]);
  });

  it("drops a name no parameter answers to", () => {
    // A section written before a parameter was renamed. The server carries the
    // rename through; a form that threw here would take the action down for a
    // stale row in a cosmetic table.
    const layout = formLayout(
      PARAMETERS, [section({ parameters: ["gone", "owner"] })], undefined,
    );
    expect(layout.sections[0]!.parameters.map((p) => p.api_name)).toEqual(["owner"]);
  });
});

describe("requiredElsewhere", () => {
  it("is empty when every required parameter is on screen", () => {
    expect(requiredElsewhere(PARAMETERS, [], undefined)).toEqual([]);
    expect(requiredElsewhere(
      PARAMETERS, [section({ parameters: ["status"] })], undefined,
    )).toEqual([]);
  });

  it("names a required parameter hidden inside a section", () => {
    expect(requiredElsewhere(
      PARAMETERS, [section({ hidden: true, parameters: ["status"] })], undefined,
    ).map((p) => p.api_name)).toEqual(["status"]);
  });

  it("names one whose section's condition is not met", () => {
    expect(requiredElsewhere(
      PARAMETERS,
      [section({ visible_when: when("owner", "me"), parameters: ["status"] })],
      [],
    ).map((p) => p.api_name)).toEqual(["status"]);
  });

  it("says nothing about a parameter that is not required", () => {
    expect(requiredElsewhere(
      PARAMETERS, [section({ hidden: true, parameters: ["reason"] })], undefined,
    )).toEqual([]);
  });

  it("says nothing about p.25's hidden parameter", () => {
    // Supplied by whatever runs the action. It was never going to be on
    // screen, and nobody has to fix the form for it.
    expect(requiredElsewhere(
      [{ api_name: "trace", required: true, hidden: true }],
      [section({ hidden: true, parameters: ["trace"] })],
      undefined,
    )).toEqual([]);
  });
});

describe("unreachableNote", () => {
  it("is nothing when nothing is unreachable", () => {
    expect(unreachableNote([])).toBeNull();
  });

  it("names the field and points at whoever can fix it", () => {
    const note = unreachableNote([{ api_name: "status", display_name: "Status" }]);
    expect(note).toContain("Status");
    // Addressed to the builder, because the reader of the form cannot open a
    // section somebody hid.
    expect(note).toContain("arranged the form");
    expect(note).toContain("is required");
  });

  it("reads as a plural for more than one", () => {
    const note = unreachableNote([
      { api_name: "a", display_name: "A" }, { api_name: "b", display_name: "B" },
    ]);
    expect(note).toContain("A, B");
    expect(note).toContain("are required");
  });

  it("falls back to the api name when there is no label", () => {
    expect(unreachableNote([{ api_name: "status" }])).toContain("status");
  });
});

describe("columns", () => {
  it("is p.123's one or two and nothing else", () => {
    expect(columnsOf({ columns: 2 })).toBe(2);
    expect(columnsOf({ columns: 1 })).toBe(1);
    expect(columnsOf({ columns: 3 })).toBe(1);
    expect(columnsOf({})).toBe(1);
  });

  it("is named rather than numbered on screen", () => {
    expect(columnsLabel(1)).toBe("One column");
    expect(columnsLabel(2)).toBe("Two columns");
  });
});

describe("collapsedInitially", () => {
  it("folds a collapsible section that starts folded", () => {
    expect(collapsedInitially(section({ collapsible: true, collapsed: true }))).toBe(true);
  });

  it("leaves a collapsible section open unless it says otherwise", () => {
    expect(collapsedInitially(section({ collapsible: true }))).toBe(false);
  });

  it("refuses to fold a section that cannot be unfolded", () => {
    // A section folded with no way to open it would be p.123's "hidden
    // entirely" wearing the wrong name.
    expect(collapsedInitially(section({ collapsible: false, collapsed: true }))).toBe(false);
  });
});

describe("sectionSummary", () => {
  it("counts the parameters and says how it is laid out", () => {
    expect(sectionSummary(section({ parameters: ["a", "b"], columns: 2 })))
      .toBe("2 parameters · two columns");
  });

  it("says one parameter rather than 1 parameters", () => {
    expect(sectionSummary(section({ parameters: ["a"] }))).toBe("1 parameter · one column");
  });

  it("counts an empty section", () => {
    expect(sectionSummary(section())).toBe("0 parameters · one column");
  });

  it("says which kind of hiding a section has", () => {
    expect(sectionSummary(section({ hidden: true }))).toContain("hidden");
    expect(sectionSummary(section({ visible_when: when("a", 1) })))
      .toContain("shown on a condition");
  });

  it("says nothing about a condition on a section that is hidden anyway", () => {
    // The two do not both apply, and a list saying both would invite reading
    // the condition as the one in force.
    const summary = sectionSummary(
      section({ hidden: true, visible_when: when("a", 1) }),
    );
    expect(summary).toContain("hidden");
    expect(summary).not.toContain("condition");
  });

  it("distinguishes collapsible from starting folded", () => {
    expect(sectionSummary(section({ collapsible: true }))).toContain("collapsible");
    expect(sectionSummary(section({ collapsible: true })))
      .not.toContain("starts folded");
    expect(sectionSummary(section({ collapsible: true, collapsed: true })))
      .toContain("starts folded");
  });

  it("says nothing about folding for a section that cannot fold", () => {
    expect(sectionSummary(section({ collapsed: true }))).not.toContain("collaps");
  });
});

describe("availableParameters", () => {
  const two = [
    section({ id: "s1", parameters: ["status"] }),
    section({ id: "s2", title: "More", parameters: ["reason"] }),
  ];

  it("offers what no other section holds", () => {
    expect(availableParameters(PARAMETERS, two, 0).map((p) => p.api_name))
      .toEqual(["status", "owner", "trace"]);
  });

  it("still offers what this section already holds", () => {
    // Removing it would make the control forget what it is showing.
    expect(availableParameters(PARAMETERS, two, 1).map((p) => p.api_name))
      .toContain("reason");
  });

  it("offers everything when there is nothing to collide with", () => {
    expect(availableParameters(PARAMETERS, [], 0)).toHaveLength(PARAMETERS.length);
  });
});

describe("placeParameter", () => {
  it("puts a parameter in a section", () => {
    const next = placeParameter([section()], 0, "status");
    expect(next[0]!.parameters).toEqual(["status"]);
  });

  it("takes it out of wherever it was, so no form can be in two", () => {
    // p.124 offers two ways to put a parameter in a section and neither is
    // "in both" — the move is one edit as far as the builder is concerned.
    const next = placeParameter([
      section({ id: "s1", parameters: ["status", "owner"] }),
      section({ id: "s2", title: "More" }),
    ], 1, "status");
    expect(next[0]!.parameters).toEqual(["owner"]);
    expect(next[1]!.parameters).toEqual(["status"]);
  });

  it("does not double it up when it is already there", () => {
    const next = placeParameter([section({ parameters: ["status"] })], 0, "status");
    expect(next[0]!.parameters).toEqual(["status"]);
  });
});

describe("removeParameter", () => {
  it("returns a parameter to the form body", () => {
    const next = removeParameter([section({ parameters: ["status", "owner"] })], 0, "status");
    expect(next[0]!.parameters).toEqual(["owner"]);
  });

  it("leaves other sections alone", () => {
    const next = removeParameter([
      section({ id: "s1", parameters: ["status"] }),
      section({ id: "s2", title: "More", parameters: ["owner"] }),
    ], 0, "status");
    expect(next[1]!.parameters).toEqual(["owner"]);
  });
});

describe("moveSection", () => {
  const three = [
    section({ id: "a", title: "A" }),
    section({ id: "b", title: "B" }),
    section({ id: "c", title: "C" }),
  ];

  it("moves a section up p.124's list", () => {
    expect(moveSection(three, 2, -1).map((s) => s.id)).toEqual(["a", "c", "b"]);
  });

  it("moves one down", () => {
    expect(moveSection(three, 0, 1).map((s) => s.id)).toEqual(["b", "a", "c"]);
  });

  it("does nothing at the ends rather than wrapping round", () => {
    expect(moveSection(three, 0, -1).map((s) => s.id)).toEqual(["a", "b", "c"]);
    expect(moveSection(three, 2, 1).map((s) => s.id)).toEqual(["a", "b", "c"]);
  });

  it("leaves the list it was given alone", () => {
    moveSection(three, 0, 1);
    expect(three.map((s) => s.id)).toEqual(["a", "b", "c"]);
  });
});

describe("blankSection", () => {
  it("is p.123's one-column section with nothing in it", () => {
    const made = blankSection([]);
    expect(made).toMatchObject({
      title: "Section", columns: 1, hidden: false, collapsible: false,
      visible_when: null, parameters: [],
    });
  });

  it("does not arrive with a title the form already has", () => {
    // Two sections cannot share a title, and Add section twice is the most
    // direct way to find that out from the server rather than from the page.
    expect(blankSection([section({ title: "Section" })]).title).toBe("Section 2");
    expect(blankSection([
      section({ title: "Section" }), section({ id: "s2", title: "Section 2" }),
    ]).title).toBe("Section 3");
  });
});

describe("conditionDraft", () => {
  it("is empty for a section with no condition", () => {
    expect(conditionDraft(section())).toEqual({
      parameter: "", operator: "is", value: "", expressible: true,
    });
  });

  it("reads back a prior parameter against a value", () => {
    expect(conditionDraft(section({ visible_when: when("status", "closed") })))
      .toEqual({
        parameter: "status", operator: "is", value: "closed", expressible: true,
      });
  });

  it("says a condition it cannot draw is not expressible", () => {
    // Legal, and the server evaluates it. A dropdown that silently reduced it
    // to "no condition" would delete the rule on the next save.
    expect(conditionDraft(section({
      visible_when: {
        left: { kind: "current_user", attribute: "id" },
        operator: "is",
        right: { kind: "value", value: "u1" },
      },
    })).expressible).toBe(false);
    expect(conditionDraft(section({
      visible_when: {
        left: { kind: "parameter", parameter: "a" },
        operator: "is",
        right: { kind: "parameter", parameter: "b" },
      },
    })).expressible).toBe(false);
  });

  it("keeps an operator this control has no entry for", () => {
    expect(conditionDraft(section({
      visible_when: {
        left: { kind: "parameter", parameter: "n" },
        operator: "is_less_than",
        right: { kind: "value", value: 5 },
      },
    })).operator).toBe("is_less_than");
  });
});

describe("conditionValue", () => {
  it("is nothing when no parameter is chosen", () => {
    // "Always shown" and "shown when this happens to be true" are different
    // things, and only the first survives the parameter being renamed.
    expect(conditionValue({
      parameter: "", operator: "is", value: "closed", expressible: true,
    })).toBeNull();
    expect(conditionValue({
      parameter: "   ", operator: "is", value: "", expressible: true,
    })).toBeNull();
  });

  it("stores decision 0007's shape", () => {
    expect(conditionValue({
      parameter: "status", operator: "is_not", value: "open", expressible: true,
    })).toEqual({
      left: { kind: "parameter", parameter: "status" },
      operator: "is_not",
      right: { kind: "value", value: "open" },
    });
  });

  it("survives the round trip back into a draft", () => {
    const draft = {
      parameter: "status", operator: "is", value: "closed", expressible: true,
    };
    expect(conditionDraft(section({ visible_when: conditionValue(draft) })))
      .toEqual(draft);
  });
});

describe("renameParameter", () => {
  it("carries a rename through a section's membership", () => {
    const next = renameParameter([section({ parameters: ["status", "owner"] })],
      "status", "state");
    expect(next[0]!.parameters).toEqual(["state", "owner"]);
  });

  it("carries it through a condition that names it", () => {
    const next = renameParameter(
      [section({ visible_when: when("status", "closed") })], "status", "state");
    expect(conditionDraft(next[0]!).parameter).toBe("state");
  });

  it("leaves a condition it cannot read alone", () => {
    // Rewriting a condition this control cannot express would be an edit
    // nobody asked for, on a rule nobody can see.
    const odd = {
      left: { kind: "current_user", attribute: "id" },
      operator: "is",
      right: { kind: "value", value: "status" },
    };
    expect(renameParameter([section({ visible_when: odd })], "status", "state")[0]!
      .visible_when).toEqual(odd);
  });

  it("does nothing while the name is empty mid-typing", () => {
    // An api_name is cleared on the way to the next one. Taking the parameter
    // out of its section at that moment would lose the arrangement.
    const before = [section({ parameters: ["status"] })];
    expect(renameParameter(before, "status", "")[0]!.parameters).toEqual(["status"]);
    expect(renameParameter(before, "", "state")[0]!.parameters).toEqual(["status"]);
    expect(renameParameter(before, "status", "status")[0]!.parameters).toEqual(["status"]);
  });

  it("leaves a parameter that is not the one renamed", () => {
    expect(renameParameter([section({ parameters: ["status", "owner"] })],
      "owner", "assignee")[0]!.parameters).toEqual(["status", "assignee"]);
  });
});

describe("forgetParameters", () => {
  it("drops a parameter the action no longer declares", () => {
    const next = forgetParameters(
      [section({ parameters: ["status", "gone"] })],
      [{ api_name: "status" }],
    );
    expect(next[0]!.parameters).toEqual(["status"]);
  });

  it("keeps every parameter that is still declared", () => {
    const next = forgetParameters(
      [section({ parameters: ["status", "owner"] })], PARAMETERS);
    expect(next[0]!.parameters).toEqual(["status", "owner"]);
  });

  it("keeps a hidden parameter, which is declared like any other", () => {
    expect(forgetParameters(
      [section({ parameters: ["trace"] })], PARAMETERS)[0]!.parameters)
      .toEqual(["trace"]);
  });
});
