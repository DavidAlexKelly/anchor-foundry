/**
 * p.29's issue column (§313; `ontology-manager` p.29).
 *
 *     "Object types whose backing datasources are unregistered or have failed
 *      to reindex into Object Storage v1 (Phonograph) will have red error
 *      messages in the issue column of the object type page." (p.29)
 *
 * **Two rows of `ontology.md`, one mechanism** — "indexing / reindexing state
 * and errors surfaced per object type" and p.29's red messages are the same
 * thing seen from the type and from the Ontology Manager. Neither needed new
 * storage: `object_type_sources` has carried `sync_status` and `last_error`
 * since db 0003, and nothing has ever shown them.
 *
 * The server counts; this decides what the count *says*.
 */
import type { ObjectTypeSummary } from "./types";

/** p.29's two conditions, which are two problems rather than one. */
export type Issue = "none" | "unsourced" | "failing";

/**
 * What is wrong with this type, if anything.
 *
 * **`failing` outranks `unsourced`**, though they cannot both be true today: a
 * type with a failing source has at least one source by definition. Ordered
 * anyway, because the alternative is a chain whose correctness depends on a
 * fact two files away — and if a source could ever be both registered and
 * uncounted, the honest answer is still the failure.
 */
export function issue(type: ObjectTypeSummary): Issue {
  if (type.failing_source_count > 0) return "failing";
  if (type.source_count === 0) return "unsourced";
  return "none";
}

/**
 * The column's text.
 *
 * **`unsourced` is not red, and that is the decision.** p.29 names both
 * conditions, but a type nobody has pointed at data yet is the ordinary state
 * of one somebody is still building — marking it as an error would make the
 * column red on every new type and teach people to ignore it, which is worse
 * than not having the column.
 */
export function issueLabel(type: ObjectTypeSummary): string | null {
  switch (issue(type)) {
    case "failing":
      return type.failing_source_count === 1
        ? "1 source failing"
        : `${type.failing_source_count} sources failing`;
    case "unsourced":
      return "No source";
    default:
      return null;
  }
}

/** Whether the column should be red. p.29's word is "error". */
export function issueIsAnError(type: ObjectTypeSummary): boolean {
  return issue(type) === "failing";
}

/**
 * The hover, which is where the failure's own words go.
 *
 * "This type has an issue" is a fact nobody can act on. The message the sync
 * produced is the one thing that says what to fix, and it is too long for a
 * table cell — so the cell counts and the title explains.
 */
export function issueDetail(type: ObjectTypeSummary): string | null {
  switch (issue(type)) {
    case "failing":
      return (
        type.source_error ||
        "This type's data could not be loaded, and the sync did not say why."
      );
    case "unsourced":
      return (
        "Nothing has been mapped to this type yet, so it has no objects. Add a " +
        "source to point it at a dataset."
      );
    default:
      return null;
  }
}
