/**
 * p.197's join table dataset, as the link-type dialogs hold one (§552).
 *
 * > "Join table dataset: For "many-to-many" cardinality link types. This
 * > option allows you to use a join table dataset to back the link." (p.197)
 *
 * > "Select a dataset that contains columns matching the primary keys for both
 * > selected object types. A column can only be mapped to one primary key."
 * > (p.200)
 *
 * The server checks all of this (`ontology._normalise_join_table`); the form
 * checks it first so the Save button says why it is off rather than sending a
 * draft to be refused. Pure, so the rules are tested without a dialog.
 */

import type { LinkCardinality, LinkType } from "@platform/types";

export interface JoinTableDraft {
  dataset: string;
  from: string;
  to: string;
}

export const NO_JOIN_TABLE: JoinTableDraft = { dataset: "", from: "", to: "" };

/** The draft a link already has, for the dialog that edits its join. */
export function draftOf(link: Pick<LinkType, "join_dataset_id" | "join_from_column" | "join_to_column">): JoinTableDraft {
  return {
    dataset: link.join_dataset_id ?? "",
    from: link.join_from_column ?? "",
    to: link.join_to_column ?? "",
  };
}

/** Whether anything of a join table has been chosen. */
export function isChosen(draft: JoinTableDraft): boolean {
  return !!(draft.dataset || draft.from || draft.to);
}

/** Why this draft cannot be saved, or `null` when it can - including when
 * nothing is chosen, which is a link joined on its properties or on nothing. */
export function joinTableProblem(draft: JoinTableDraft, cardinality: LinkCardinality): string | null {
  if (!isChosen(draft)) return null;
  if (cardinality !== "many_to_many") {
    return "A join table backs a many-to-many link.";
  }
  if (!draft.dataset || !draft.from || !draft.to) {
    return "Choose the dataset, and the column holding each end's primary key.";
  }
  if (draft.from === draft.to) return "Each end needs its own column.";
  return null;
}

/** The request's fields: all three, or all null to clear a join table. */
export function joinTablePayload(draft: JoinTableDraft): {
  join_dataset_id: string | null; join_from_column: string | null; join_to_column: string | null;
} {
  const chosen = !!(draft.dataset && draft.from && draft.to);
  return {
    join_dataset_id: chosen ? draft.dataset : null,
    join_from_column: chosen ? draft.from : null,
    join_to_column: chosen ? draft.to : null,
  };
}

/** What the link table says a link joins on. */
export function joinDescription(
  link: Pick<LinkType, "from_property" | "to_property" | "join_dataset_id" | "join_from_column" | "join_to_column">,
  label: (property: string) => string,
): string {
  if (link.join_dataset_id) {
    return `join table: ${link.join_from_column} ↔ ${link.join_to_column}`;
  }
  if (link.join_from_column) {
    // db 0115: the dataset was deleted and the columns kept.
    return "not traversable - its join table was deleted";
  }
  if (link.from_property && link.to_property) {
    return `${label(link.from_property)} = ${label(link.to_property)}`;
  }
  return "not traversable";
}
