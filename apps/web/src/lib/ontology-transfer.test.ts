/**
 * Reading an ontology file's plan (§327; `ontology-manager` p.65-67).
 *
 * The plan itself is computed and tested in
 * `apps/api/tests/test_ontology_import.py`. What is here is the half a database
 * cannot check: whether the screen above an Apply button says enough for
 * somebody to press it knowingly.
 */
import { describe, expect, it } from "vitest";
import {
  exportFilename,
  leftAloneWarning,
  originNote,
  planHeadline,
  refusalText,
  sectionSummary,
} from "./ontology-transfer";
import type { OntologyPlan, OntologyPlanSection } from "./types";

function section(over: Partial<OntologyPlanSection> = {}): OntologyPlanSection {
  return { added: [], changed: [], unchanged: [], absent_from_file: [], ...over };
}

function plan(over: Partial<OntologyPlan> = {}): OntologyPlan {
  return {
    workspace: { id: "w1", slug: "acme", name: "Acme" },
    from_workspace: { id: "w1", slug: "acme", name: "Acme" },
    is_round_trip: true,
    sections: {
      object_types: section(),
      link_types: section(),
      action_types: section(),
    },
    changes: 0,
    ...over,
  };
}

describe("what an exported file is called", () => {
  it("names the workspace and the day", () => {
    // p.65's second workflow is copying one ontology into another, so a
    // downloads folder ends up with several — `ontology.json` for every export
    // would make the reader open them to tell them apart.
    expect(exportFilename("acme", new Date("2026-09-12T10:00:00Z")))
      .toBe("acme-ontology-2026-09-12.json");
  });
});

describe("p.66's count", () => {
  it("says how many changes are waiting", () => {
    expect(planHeadline(plan({ changes: 4 }))).toBe("4 changes to apply.");
  });

  it("does not pluralise one", () => {
    expect(planHeadline(plan({ changes: 1 }))).toBe("1 change to apply.");
  });

  it("gives zero its own sentence rather than printing a nought", () => {
    // **"0 changes" beside a button invites somebody to press it and wonder
    // what happened.** A file that would change nothing is the expected answer
    // for p.65's edit-and-put-back workflow before you have edited anything.
    const said = planHeadline(plan({ changes: 0 }));
    expect(said).not.toContain("0");
    expect(said).toContain("Nothing to apply");
  });
});

describe("a section's line", () => {
  it("counts what is new and what differs", () => {
    expect(sectionSummary("Object types", {
      added: ["a", "b"], changed: ["c"],
    })).toBe("Object types: 2 new, 1 changed");
  });

  it("leaves out the half that is empty", () => {
    expect(sectionSummary("Link types", { added: ["a"], changed: [] }))
      .toBe("Link types: 1 new");
    expect(sectionSummary("Link types", { added: [], changed: ["a"] }))
      .toBe("Link types: 1 changed");
  });

  it("says nothing at all for a section with nothing in it", () => {
    // An empty section drawn as "Action types: " is a line the reader has to
    // parse to learn it says nothing.
    expect(sectionSummary("Action types", { added: [], changed: [] })).toBe("");
  });
});

describe("what the import will not do", () => {
  it("warns about types the file leaves out", () => {
    // **The one thing p.66's reader must not believe.** The page says import
    // "will recreate the entire working state", so somebody arriving from it
    // expects a replacement — and §326 declines to delete, because an object
    // type's removal takes its objects with it, immediately and with no review.
    const said = leftAloneWarning(plan({
      sections: {
        object_types: section({ absent_from_file: ["vessel", "berth"] }),
        link_types: section(),
        action_types: section(),
      },
    }));
    expect(said).toContain("2 object types");
    expect(said).toContain("left alone");
    // And it points at the tool that does remove them (§325).
    expect(said).toContain("Ontology cleanup");
  });

  it("does not pluralise one", () => {
    expect(leftAloneWarning(plan({
      sections: {
        object_types: section({ absent_from_file: ["vessel"] }),
        link_types: section(),
        action_types: section(),
      },
    }))).toContain("1 object type");
  });

  it("says nothing when the file leaves nothing out", () => {
    // Absent rather than reassuring somebody about a risk they do not have.
    expect(leftAloneWarning(plan())).toBe("");
  });
});

describe("where the file came from", () => {
  it("says so when it is this workspace's own export", () => {
    // p.65's two workflows read the same plan differently: "nothing changed"
    // is reassuring for an edit-and-put-back and suspicious for a copy.
    expect(originNote(plan())).toContain("from this workspace");
  });

  it("names the other workspace when it is a copy", () => {
    const said = originNote(plan({
      is_round_trip: false,
      from_workspace: { id: "w2", slug: "other", name: "Other Co" },
    }));
    expect(said).toContain("Other Co");
    expect(said).toContain("not from this workspace");
  });

  it("does not pretend to know when the file does not say", () => {
    const said = originNote(plan({ is_round_trip: false, from_workspace: null }));
    expect(said).toContain("does not say");
  });

  it("gives a different answer for each of the three", () => {
    // The assertion that makes the three above mean something: one sentence
    // for every origin would satisfy each of them on its own.
    const said = new Set([
      originNote(plan()),
      originNote(plan({ is_round_trip: false,
        from_workspace: { id: "w2", slug: "other", name: "Other Co" } })),
      originNote(plan({ is_round_trip: false, from_workspace: null })),
    ]);
    expect(said.size).toBe(3);
  });
});

describe("a refused file", () => {
  it("keeps the server's own sentence", () => {
    // §326's refusals name the property, link or action that is wrong, and
    // that is the only part somebody editing JSON can act on.
    expect(refusalText("'vessel' names 'nope' as its title property"))
      .toContain("nope");
  });

  it("has something to say when there is no message", () => {
    for (const nothing of [null, undefined, "", "  "]) {
      expect(refusalText(nothing)).toBe("This file could not be read as an ontology.");
    }
  });
});
