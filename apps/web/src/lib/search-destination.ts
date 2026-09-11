/**
 * Where a search hit goes (§316; `ontology-manager` p.28, p.261; `object-link-types` p.178, p.4).
 *
 * The search returns seven kinds of thing, and they do not all live in the
 * same place. Four belong to an object type and open it. Three do not belong
 * to one *by definition* — a shared property (`object-link-types` p.178), an
 * object type group (p.261), and an interface, which is implemented *by* types
 * rather than owned by one (p.4), which is the whole point of it.
 *
 * **This exists because the third of those three had no destination for
 * sixty-four units and nothing could say so.** §173 gave groups one and wrote
 * down why the two ownerless kinds could not share a handler: "a group id
 * opened as a shared property finds nothing and does nothing at all". §252
 * then made interfaces searchable and did not add a third branch — so an
 * interface hit fell through the `kind === "group"` check into the shared
 * property handler, and clicking it opened an editor for an id that is not a
 * shared property. Silently: no error, no empty state, a dialog that simply
 * never resolves.
 *
 * Neither layer could complain. The server's response model types `kind` as
 * `str`, the browser's `OntologySearchHit` declared six of the seven, and a
 * `Record<Kind, string>` over a union missing a member is a complete record —
 * so `tsc` was satisfied by a map with a hole in it, exactly the way
 * `test_response_type_drift` describes one type being *shorter* than the other
 * rather than disagreeing with it.
 *
 * So the decision is a function with a case per kind and no fall-through: a
 * kind this does not know about is a compile error, and an eighth kind added
 * to the union cannot reach a screen by accident.
 */
import type { OntologySearchHit } from "./types";

/**
 * The parts of a row that decide where it goes.
 *
 * Narrower than `OntologySearchHit` on purpose: p.30's recently-edited quick
 * links (§317) carry the same `kind`/`id`/owner and nothing about matching,
 * and they have to reach the same screens. Two lists of links to the same
 * things, differing only in how they were found, would be two places for a
 * destination to go wrong — which is what this file exists because of.
 */
export type Locatable = Pick<OntologySearchHit, "kind" | "id"> & {
  object_type_id: string | null;
};

/** Which screen opens, and the id to open it with. */
export type Destination =
  | { open: "object_type"; id: string }
  | { open: "shared_property"; id: string }
  | { open: "group"; id: string }
  | { open: "interface"; id: string };

/**
 * The screen this hit opens.
 *
 * **Owner first, kind second.** The four owned kinds — a type, a property, a
 * link type, an action type — all open the object type they live on, because
 * that is the one screen all four can be looked at from. The other three are
 * decided by their own kind, and `null` is returned rather than a guess when a
 * hit claims an owner it does not have: sending somebody to a type that has
 * nothing to do with what they searched for is worse than a hit that does not
 * move, because it looks like it worked.
 */
export function destinationFor(hit: Locatable): Destination | null {
  switch (hit.kind) {
    case "object_type":
    case "property":
    case "link_type":
    case "action_type":
      return hit.object_type_id
        ? { open: "object_type", id: hit.object_type_id }
        : null;
    case "shared_property":
      return { open: "shared_property", id: hit.id };
    case "group":
      return { open: "group", id: hit.id };
    case "interface":
      return { open: "interface", id: hit.id };
  }
}

/**
 * What the row says this thing is.
 *
 * Beside `destinationFor` rather than in the component, so the two lists that
 * have to cover the same seven kinds are in one file. A label missing from a
 * map renders as an empty chip — which is how the interface bug looked on
 * screen, and a blank where a word should be is not something anybody reports.
 */
export const KIND_LABELS: Record<OntologySearchHit["kind"], string> = {
  object_type: "Object type",
  property: "Property",
  link_type: "Link type",
  action_type: "Action",
  shared_property: "Shared property",
  group: "Group",
  interface: "Interface",
};

/**
 * How an interface's reach reads on its own row.
 *
 * The count is the number of object types implementing it (§252) — the number
 * that decides whether changing this shape is cheap or expensive, which is
 * what somebody looking at an interface is deciding. **Zero is said out loud**,
 * for the reason `memberSummary` gives about an empty group: an interface
 * nothing implements yet is a real and common state, and a row that fell
 * silent for it would read as a broken row rather than an empty one.
 */
export function implementationSummary(count: number): string {
  return `implemented by ${count} object type${count === 1 ? "" : "s"}`;
}
