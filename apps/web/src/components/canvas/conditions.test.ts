import { describe, expect, it } from "vitest";

import { conditionsOf, CONDITION_PROPS, markerFor } from "./conditions";
import { REFERENCE_PROPS } from "../../lib/workshop-module";
import type { WorkshopVariable } from "../../lib/types";

/** p.55's conditional-visibility indicators (Foundry `workshop` p.55).
 *
 * The claim worth testing hardest is the one p.55 makes about *purpose*: a
 * conditionally-visible section must be findable "even when they are currently
 * hidden in the module view". That is a claim about what the indicator is
 * driven by, and it is checkable here without a browser.
 */

const variable = (id: string, label: string): WorkshopVariable =>
  ({ id, kind: "boolean", label } as WorkshopVariable);

const DECLARED: Record<string, WorkshopVariable> = {
  v_show: variable("v_show", "Show details"),
  v_shut: variable("v_shut", "Start collapsed"),
};

describe("the catalogue", () => {
  it("only names props the document actually carries a variable in", () => {
    // **Checked against `REFERENCE_PROPS`, not against a second copy of
    // itself** (§191's rule). A condition prop that is not a reference prop
    // would be one nothing counts as a usage - so deleting the variable it
    // names would be allowed, and the marker would then point at nothing.
    for (const prop of Object.keys(CONDITION_PROPS)) {
      expect(REFERENCE_PROPS as readonly string[]).toContain(prop);
    }
  });

  it("gives every condition an icon and a verb", () => {
    for (const [prop, spec] of Object.entries(CONDITION_PROPS)) {
      expect(spec.icon, prop).toBeTruthy();
      expect(spec.verb, prop).toBeTruthy();
    }
  });

  it("gives the two conditions different icons", () => {
    // They appear side by side on one row; the same glyph twice would say a
    // section has two conditions and nothing about which.
    const icons = Object.values(CONDITION_PROPS).map((s) => s.icon);
    expect(new Set(icons).size).toBe(icons.length);
  });
});

describe("conditionsOf", () => {
  it("finds a visibility condition", () => {
    expect(conditionsOf({ visibleWhen: "v_show" }))
      .toEqual([{ prop: "visibleWhen", variable: "v_show" }]);
  });

  it("finds a collapse condition", () => {
    // p.55 names visibility; p.82's collapse backing is the same question
    // asked about a different bit of state, and an author scanning the tree
    // wants both answered.
    expect(conditionsOf({ collapsedWhen: "v_shut" }))
      .toEqual([{ prop: "collapsedWhen", variable: "v_shut" }]);
  });

  it("reports both in a fixed order", () => {
    // Fixed, not however the props happen to be spelled out: a row whose
    // icons reorder between renders is a row nobody can scan.
    const forward = conditionsOf({ visibleWhen: "v_show", collapsedWhen: "v_shut" });
    const backward = conditionsOf({ collapsedWhen: "v_shut", visibleWhen: "v_show" });
    expect(forward.map((c) => c.prop)).toEqual(["visibleWhen", "collapsedWhen"]);
    expect(backward).toEqual(forward);
  });

  it("ignores a prop set to an empty string", () => {
    // "No variable" is how the settings panel spells cleared, so an empty
    // string must not mark the row - it would mark every section an author
    // ever touched and then thought better of.
    expect(conditionsOf({ visibleWhen: "" })).toEqual([]);
    expect(conditionsOf({ visibleWhen: "   " })).toEqual([]);
  });

  it("ignores a prop that is not a string", () => {
    expect(conditionsOf({ visibleWhen: null })).toEqual([]);
    expect(conditionsOf({ visibleWhen: true })).toEqual([]);
  });

  it("ignores props that are not conditions", () => {
    // `objectSetVariable` is a reference prop too, and binding a table to a
    // set is not a condition - marking it would make the icon mean "this row
    // mentions a variable", which is most rows.
    expect(conditionsOf({ objectSetVariable: "v_set", variable: "v_x" })).toEqual([]);
  });

  it("is empty for a node with no props at all", () => {
    expect(conditionsOf(undefined)).toEqual([]);
    expect(conditionsOf({})).toEqual([]);
  });
});

describe("markerFor", () => {
  it("names the variable rather than only saying there is one", () => {
    // **p.55's "easier to identify and manage" is the requirement.**
    // "Conditionally visible" satisfies the letter and none of the purpose:
    // the label is the only part of this an author can act on.
    const marker = markerFor({ visibleWhen: "v_show" }, DECLARED);
    expect(marker?.tooltip).toBe("Visible when Show details");
    expect(marker?.icon).toBe(CONDITION_PROPS.visibleWhen.icon);
  });

  it("says both when a section carries both", () => {
    const marker = markerFor({ visibleWhen: "v_show", collapsedWhen: "v_shut" }, DECLARED);
    expect(marker?.tooltip).toBe("Visible when Show details · Collapsed when Start collapsed");
    expect(marker?.icon).toBe(
      CONDITION_PROPS.visibleWhen.icon + CONDITION_PROPS.collapsedWhen.icon,
    );
  });

  it("falls back to the id when the variable has no definition", () => {
    // Reachable from a raw-JSON edit or an older writer. "Visible when
    // undefined" would describe the tooling rather than the problem, and the
    // id is the thing somebody can search the document for.
    expect(markerFor({ visibleWhen: "v_gone" }, DECLARED)?.tooltip)
      .toBe("Visible when v_gone");
  });

  it("is null for a node with no condition", () => {
    // Null rather than an empty marker: an icon that means nothing on most
    // rows stops meaning anything on the rows it is for.
    expect(markerFor({ title: "Section" }, DECLARED)).toBeNull();
    expect(markerFor(undefined, DECLARED)).toBeNull();
  });

  it("does not depend on the variable's value", () => {
    // **The whole of p.55's second half.** The indicator exists so a section
    // can be found "even when they are currently hidden", so it is a function
    // of the *document* and never of what the variable currently resolves to.
    // `markerFor` is not even given the resolved values - this test pins that
    // signature, because the tempting future change is to pass them in and
    // grey out the marker when the condition is false, which would take the
    // indicator away exactly when it is needed.
    expect(markerFor.length).toBe(2);
    const withNoVariablesResolved = markerFor({ visibleWhen: "v_show" }, DECLARED);
    const withNoneDeclaredAtAll = markerFor({ visibleWhen: "v_show" }, {});
    expect(withNoVariablesResolved).not.toBeNull();
    expect(withNoneDeclaredAtAll).not.toBeNull();
  });
});
