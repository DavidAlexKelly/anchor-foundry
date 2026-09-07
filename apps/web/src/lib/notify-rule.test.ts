import { describe, expect, it } from "vitest";
import {
  PERMISSION_MODES, RECIPIENT_KINDS, USER_REFERENCES, blankNotifyConfig,
  insertReference, problem, referenceOptions, referencesIn,
} from "./notify-rule";

const PARAMETERS = ["priority", "alert"];

function config(over: Partial<ReturnType<typeof blankNotifyConfig>> = {}) {
  return {
    ...blankNotifyConfig(),
    recipients: { kind: "static", user_ids: ["u1"] },
    subject: "Retriaged",
    ...over,
  };
}

describe("blankNotifyConfig", () => {
  it("starts on p.96's strict permission mode", () => {
    // The default cannot quietly send somebody data they may not see, so it is
    // the one that refuses the whole action.
    expect(blankNotifyConfig().permissions).toBe("all");
  });

  it("starts on the recipient kind that needs nothing else to exist", () => {
    // p.101's own advice: "initially configure the action with hardcoded
    // recipient(s) … to validate the logic".
    expect(blankNotifyConfig().recipients.kind).toBe("static");
  });
});

describe("the offered vocabularies", () => {
  it("offers p.90's three recipient kinds and not the fourth", () => {
    // `From a function` needs Functions, which this platform does not have —
    // absent rather than disabled, because its only outcome would be a save
    // that fails.
    expect(RECIPIENT_KINDS.map(([v]) => v)).toEqual([
      "static", "parameter", "object_property",
    ]);
  });

  it("offers p.96's two permission modes", () => {
    expect(PERMISSION_MODES.map(([v]) => v)).toEqual(["all", "any"]);
  });

  it("names p.101's two user references", () => {
    expect(USER_REFERENCES.map(([v]) => v)).toEqual(["recipient", "current_user"]);
  });
});

describe("problem", () => {
  it("passes a rule the server would take", () => {
    expect(problem(config(), PARAMETERS)).toBeNull();
  });

  it("wants somebody on a static list", () => {
    expect(
      problem(config({ recipients: { kind: "static", user_ids: [] } }), PARAMETERS),
    ).toContain("at least one person");
  });

  it("wants the parameter a recipient is read from", () => {
    expect(
      problem(config({ recipients: { kind: "parameter" } }), PARAMETERS),
    ).toContain("parameter that names");
  });

  it("wants the property as well, for p.100's recipient kind", () => {
    expect(
      problem(
        config({ recipients: { kind: "object_property", parameter: "alert" } }),
        PARAMETERS,
      ),
    ).toContain("property");
  });

  it("wants a subject, which is half of p.89's requirement", () => {
    expect(problem(config({ subject: "   " }), PARAMETERS)).toContain("subject");
  });

  it("catches a reference to something that is not a parameter", () => {
    // The round trip this exists to avoid: the server refuses it too, on Save,
    // about a form somebody has already left.
    expect(
      problem(config({ body: "Now {{{nonsense}}}" }), PARAMETERS),
    ).toContain("nonsense");
  });

  it("accepts the two user references without them being parameters", () => {
    expect(
      problem(
        config({ subject: "For {{{recipient}}}", body: "By {{{current_user}}}" }),
        PARAMETERS,
      ),
    ).toBeNull();
  });

  it("accepts a dotted reference on its head alone", () => {
    // Whether `alert` has a `priority` needs the ontology, which a form does
    // not have — the server answers that one, and refusing here would make a
    // template unsaveable because of something about the *caller*.
    expect(problem(config({ body: "{{{alert.priority}}}" }), PARAMETERS)).toBeNull();
  });

  it("wants both halves of a link", () => {
    expect(
      problem(config({ link: { url: "/x", text: "" } }), PARAMETERS),
    ).toContain("both");
  });

  it("checks a link's references too", () => {
    expect(
      problem(config({ link: { url: "/o/{{{nope}}}", text: "Open" } }), PARAMETERS),
    ).toContain("nope");
  });
});

describe("referencesIn", () => {
  it("finds three-brace references and not two", () => {
    // **The count is not decoration.** Two braces escape their substitution in
    // every templating language that has both; somebody typing by hand gets
    // two, which is why the syntax is generated rather than typed.
    expect(referencesIn("{{{a}}} and {{b}}")).toEqual(["a"]);
  });

  it("finds a dotted reference whole", () => {
    expect(referencesIn("{{{alert.priority}}}")).toEqual(["alert.priority"]);
  });

  it("has nothing to say about plain text", () => {
    expect(referencesIn("no references here")).toEqual([]);
  });
});

describe("insertReference", () => {
  it("generates the syntax rather than asking somebody to type it", () => {
    expect(insertReference("Now ", 4, 4, "priority")).toEqual({
      text: "Now {{{priority}}}",
      caret: "Now {{{priority}}}".length,
    });
  });

  it("leaves the caret after the reference so the sentence can continue", () => {
    const out = insertReference("A  B", 2, 2, "x");
    expect(out.text).toBe("A {{{x}}} B");
    expect(out.text.slice(out.caret)).toBe(" B");
  });

  it("replaces a selection, which is what every text field does", () => {
    expect(insertReference("Now WORD.", 4, 8, "priority").text).toBe(
      "Now {{{priority}}}.",
    );
  });

  it("survives a caret past the end of the text", () => {
    // A stale caret from a field that was cleared: the reference lands at the
    // end rather than throwing while somebody is typing.
    expect(insertReference("ab", 99, 99, "x").text).toBe("ab{{{x}}}");
  });
});

describe("referenceOptions", () => {
  it("offers the parameters first and the fixed pair last", () => {
    // A fixed pair at the end is easier to find than a fixed pair at the start
    // of a list that grows.
    expect(referenceOptions(["a", "b"]).map((o) => o.value)).toEqual([
      "a", "b", "recipient", "current_user",
    ]);
  });
});
