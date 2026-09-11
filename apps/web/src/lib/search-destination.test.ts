import { describe, expect, it } from "vitest";

import {
  KIND_LABELS,
  destinationFor,
  implementationSummary,
} from "./search-destination";
import type { OntologySearchHit } from "./types";

/** The seven kinds the server can return (`ontology_search.py`).
 *
 * Written out rather than derived from `KIND_LABELS`, deliberately: a list
 * derived from the thing under test agrees with it by construction, which is
 * how the six-of-seven map went unnoticed in the first place.
 */
const KINDS: OntologySearchHit["kind"][] = [
  "object_type",
  "property",
  "link_type",
  "action_type",
  "shared_property",
  "group",
  "interface",
];

function hit(over: Partial<OntologySearchHit> = {}): OntologySearchHit {
  return {
    kind: "object_type",
    id: "h-1",
    api_name: "site",
    display_name: "Site",
    object_type_id: "t-1",
    object_type_name: "Site",
    usage_count: null,
    matched_field: "display_name",
    matched_value: "Site",
    ...over,
  };
}

describe("where a hit goes", () => {
  it("sends the four owned kinds to their object type", () => {
    // One screen for all four, because it is the one place a property, a link
    // and an action can each be looked at.
    for (const kind of ["object_type", "property", "link_type", "action_type"] as const) {
      expect(destinationFor(hit({ kind, object_type_id: "t-9" }))).toEqual({
        open: "object_type",
        id: "t-9",
      });
    }
  });

  it("gives each ownerless kind its own screen", () => {
    // **The bug.** An interface has no object type to borrow, and the chain
    // this replaced fell through to the shared property handler for any kind
    // it did not name — so clicking an interface opened an editor for an id
    // that is not a shared property, with no error and no empty state.
    expect(destinationFor(hit({ kind: "shared_property", id: "s-1", object_type_id: null })))
      .toEqual({ open: "shared_property", id: "s-1" });
    expect(destinationFor(hit({ kind: "group", id: "g-1", object_type_id: null })))
      .toEqual({ open: "group", id: "g-1" });
    expect(destinationFor(hit({ kind: "interface", id: "i-1", object_type_id: null })))
      .toEqual({ open: "interface", id: "i-1" });
  });

  it("never sends one ownerless kind to another's screen", () => {
    // The three ids are drawn from three different tables, so opening one as
    // another finds nothing — which is the shape of failure that is hardest to
    // report, because nothing errors.
    const opened = new Set(
      (["shared_property", "group", "interface"] as const).map(
        (kind) => destinationFor(hit({ kind, object_type_id: null }))!.open,
      ),
    );
    expect(opened).toEqual(new Set(["shared_property", "group", "interface"]));
  });

  it("refuses to guess when an owned kind has no owner", () => {
    // A made-up owner would send somebody to a type that has nothing to do
    // with what they searched for — which looks like it worked.
    expect(destinationFor(hit({ kind: "property", object_type_id: null }))).toBeNull();
  });

  it("has an answer for every kind the server can return", () => {
    // The check the missing union member defeated: `tsc` is satisfied by a map
    // over a union with a hole in it, so the hole has to be found by asking.
    for (const kind of KINDS) {
      const to = destinationFor(hit({ kind, object_type_id: "t-1" }));
      expect(to, `no destination for ${kind}`).not.toBeNull();
    }
  });
});

describe("what the row calls it", () => {
  it("names every kind", () => {
    // A label missing from the map renders as an empty chip, and a blank where
    // a word should be is not something anybody reports.
    for (const kind of KINDS) {
      expect(KIND_LABELS[kind], `no label for ${kind}`).toBeTruthy();
    }
  });

  it("gives each kind its own word", () => {
    const labels = KINDS.map((k) => KIND_LABELS[k]);
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe("an interface's reach", () => {
  it("says the number rather than hinting at it", () => {
    expect(implementationSummary(3)).toBe("implemented by 3 object types");
  });

  it("says one in the singular", () => {
    expect(implementationSummary(1)).toBe("implemented by 1 object type");
  });

  it("says zero out loud", () => {
    // An interface nothing implements yet is a real and common state; a row
    // that fell silent for it would read as broken rather than empty.
    expect(implementationSummary(0)).toBe("implemented by 0 object types");
  });
});
