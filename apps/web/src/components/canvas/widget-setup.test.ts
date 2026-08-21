/**
 * The Widget setup tab's shape (Foundry `workshop` p.65-67).
 *
 * **The rule under test is p.66's progressive disclosure**, and it is the one
 * part of "variables-first" that is behaviour rather than layout:
 *
 * > "This configuration option is revealed in more detail once the Object Set
 * > is populated; it will then show the property types seen within the initial
 * > object set." (p.66)
 *
 * Wrong in either direction is a bad form and neither reports itself.
 * Revealed too early is a panel of empty dropdowns asking questions nothing
 * can answer; revealed too late is a widget that looks unfinishable. So the
 * rule is a pure function with its own tests rather than an `&&` inside each
 * of eighteen settings panels.
 */
import { describe, expect, it } from "vitest";

import {
  SECTION_LABELS, SETUP_SECTIONS, configReady, configWaitingFor,
} from "./widget-setup";

describe("configReady", () => {
  it("waits for the input the configuration depends on", () => {
    // p.66's own example: the filter options cannot be listed before
    // something says which object set the properties belong to.
    expect(configReady({ objectSetVariable: null }, ["objectSetVariable"])).toBe(false);
    expect(configReady({ objectSetVariable: "v1" }, ["objectSetVariable"])).toBe(true);
  });

  it("treats a blank string as unbound", () => {
    // An unset `<select>` submits "", not null - so a check that only looked
    // for null would reveal the configuration the moment the widget rendered.
    expect(configReady({ objectSetVariable: "" }, ["objectSetVariable"])).toBe(false);
    expect(configReady({ objectSetVariable: "   " }, ["objectSetVariable"])).toBe(false);
  });

  it("treats a missing key as unbound", () => {
    expect(configReady({}, ["objectSetVariable"])).toBe(false);
  });

  it("needs every named input, not just one", () => {
    expect(configReady({ a: "x", b: null }, ["a", "b"])).toBe(false);
    expect(configReady({ a: "x", b: "y" }, ["a", "b"])).toBe(true);
  });

  it("is permissive when nothing is required", () => {
    // **The half that keeps this from being a wall.** A widget with no inputs
    // whose configuration never appeared would be a widget nobody can set up,
    // and most widgets are that widget.
    expect(configReady({}, [])).toBe(true);
  });
});

describe("configWaitingFor", () => {
  it("names the input that is holding the rest back", () => {
    // p.66's example has one input; a widget with three would otherwise leave
    // somebody guessing which one the form is waiting on.
    expect(
      configWaitingFor({ objectSetVariable: null }, ["objectSetVariable"], {
        objectSetVariable: "an object set",
      }),
    ).toMatch(/Pick an object set first/);
  });

  it("names all of them when several are missing", () => {
    const message = configWaitingFor({}, ["a", "b"], { a: "a set", b: "a date" });
    expect(message).toContain("a set");
    expect(message).toContain("a date");
  });

  it("joins several missing inputs with 'and', not 'or'", () => {
    // **The distinction the containment test above cannot see**, and the Loop
    // (§181) is the first widget where getting it wrong is a real bug: it
    // needs a set to loop through *and* a module to repeat, and "a set or a
    // module" would tell somebody they were finished when they were half
    // finished. Both spellings contain both names.
    expect(configWaitingFor({}, ["a", "b"], { a: "a set", b: "a module" })).toBe(
      "Pick a set and a module first — the rest depends on it.",
    );
    // ...while a *choice* still reads as a choice (§179).
    expect(configWaitingFor({}, [["a", "b"]], { a: "a set", b: "a type" })).toBe(
      "Pick a set or a type first — the rest depends on it.",
    );
  });

  it("says nothing once they are bound", () => {
    expect(configWaitingFor({ a: "x" }, ["a"])).toBeNull();
    expect(configWaitingFor({}, [])).toBeNull();
  });

  it("falls back to the binding name when there is no label", () => {
    // Better a machine name than a sentence with a gap in it.
    expect(configWaitingFor({}, ["objectSetVariable"])).toContain("objectSetVariable");
  });
});

describe("the order p.65 gives", () => {
  it("is inputs, then configuration, then outputs", () => {
    // Not decoration: p.65 describes the tab as the input variables, the
    // output variables, "as well as any additional configuration", and its
    // worked example puts the object set before the filter options before the
    // filter output.
    expect([...SETUP_SECTIONS]).toEqual(["inputs", "configuration", "outputs"]);
  });

  it("labels every section it names", () => {
    for (const section of SETUP_SECTIONS) {
      expect(SECTION_LABELS[section]).toBeTruthy();
    }
  });
});

describe("a configuration that waits on a choice (§179)", () => {
  // Every object-set widget takes *either* a bound object set variable *or*
  // an object type picked directly. Treating those as two requirements would
  // mean the configuration never appears, because binding either one leaves
  // the other empty by design.
  const choice = [["objectSetVariable", "objectTypeId"]] as const;

  it("is ready when either one is bound", () => {
    expect(configReady({ objectSetVariable: "sales" }, choice)).toBe(true);
    expect(configReady({ objectTypeId: "type-1" }, choice)).toBe(true);
  });

  it("is not ready when neither is", () => {
    expect(configReady({}, choice)).toBe(false);
    expect(
      configReady({ objectSetVariable: null, objectTypeId: "" }, choice),
    ).toBe(false);
  });

  it("is still ready when both are", () => {
    // Not an error state - the panels that offer both say which one wins, and
    // a rule that refused here would hide the configuration from somebody who
    // had over-answered rather than under-answered.
    expect(
      configReady({ objectSetVariable: "sales", objectTypeId: "type-1" }, choice),
    ).toBe(true);
  });

  it("treats an empty alternative as unsatisfied", () => {
    // "any of nothing" read as ready would reveal a configuration whose
    // inputs somebody forgot to name - a silent hole rather than a bug.
    expect(configReady({ objectSetVariable: "sales" }, [[]] as const)).toBe(false);
  });

  it("still requires a plain string requirement", () => {
    // The choice form must not weaken the ordinary one, which is what most
    // widgets use.
    expect(configReady({ objectTypeId: "t" }, ["objectSetVariable"])).toBe(false);
  });

  it("combines a choice with a plain requirement", () => {
    expect(
      configReady({ objectTypeId: "t" }, [choice[0], "columns"]),
    ).toBe(false);
    expect(
      configReady({ objectTypeId: "t", columns: "a" }, [choice[0], "columns"]),
    ).toBe(true);
  });

  it("says the choice as a choice", () => {
    // Naming only the first would send somebody to fill in a field they do
    // not need and leave the one they do.
    expect(
      configWaitingFor({}, choice, {
        objectSetVariable: "an object set",
        objectTypeId: "an object type",
      }),
    ).toMatch(/an object set or an object type/);
  });

  it("says nothing once the choice is answered", () => {
    expect(configWaitingFor({ objectTypeId: "t" }, choice)).toBeNull();
  });
});
