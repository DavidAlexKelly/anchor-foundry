/**
 * p.402–403's Edit History widget (§471): one object's edits, as a reader
 * sees them. What is recorded is §470's (`services/object_edits.py`).
 *
 * > "Edits sort order: Specify how edits should be ordered, either
 * > oldest-to-newest or newest-to-oldest. Property configuration: Select the
 * > properties to be displayed in the widget. You may also choose to display
 * > all properties on an object." (p.403)
 */

export const EDIT_ORDERS = { newest: "Newest first", oldest: "Oldest first" } as const;
export type EditOrder = keyof typeof EDIT_ORDERS;

/** Newest first unless told otherwise: a history is read to find out what
 * happened lately. */
export function editOrderOf(raw: unknown): EditOrder {
  return raw === "oldest" ? "oldest" : "newest";
}

/** p.403's Property configuration: the chosen api_names, or `null` for all of
 * them - which is what an empty choice means, rather than none. */
export function chosenProperties(raw: unknown): string[] | null {
  const names = String(raw ?? "").split(",").map((p) => p.trim()).filter(Boolean);
  return names.length ? names : null;
}

/** A recorded value as a reader reads it. **Empty is said**, because "went
 * from 3 to nothing" and "went from 3 to an empty string" are both "nothing"
 * to a reader and neither should render as a blank that looks like a bug. */
export function valueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(empty)";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export interface Edit {
  kind: "modify" | "create" | "delete";
  property: string | null;
  before: unknown;
  after: unknown;
}

/** What an edit did, in a line. A create or delete names no property: p.402
 * lists edits to an object, and those are edits to the whole of it. */
export function editSummary(edit: Edit, labelOf: (property: string) => string): string {
  if (edit.kind === "create") return "Created";
  if (edit.kind === "delete") return "Deleted";
  return `${labelOf(edit.property ?? "")}: ${valueText(edit.before)} → ${valueText(edit.after)}`;
}
