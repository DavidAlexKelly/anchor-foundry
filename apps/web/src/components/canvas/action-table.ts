/** `workshop` p.511's **Action table** (§702), the arithmetic.
 *
 * > "Action tables (previously known as Action grids) are recommended for
 * > large-scale datasets or when data is sourced from CSV files. They support
 * > live editing within your Workshop application … The table layout offers
 * > several benefits, including keyboard navigation and CSV file upload
 * > capabilities." (p.511)
 *
 * A row is one submission of the action: the object it is about (every action
 * here has a subject) and a value for each parameter the table draws. Pure, for
 * `action-form.ts`'s reason - what a row lacks and which rows collide are
 * questions with answers, not things to ask a browser.
 */

import { seedActionForm } from "./pure";

export interface TableParameter {
  api_name: string;
  display_name?: string;
  data_type?: string;
  required?: boolean;
  hidden?: boolean;
  default_value?: unknown;
}

export type RowStatus = "draft" | "submitting" | "done" | "refused";

export interface TableRow {
  /** Stable for the life of the table, so React keeps a row's inputs when
   * another row is deleted above it. */
  key: number;
  /** The object this row's submission is about. "" until one is picked. */
  subjectId: string;
  values: Record<string, unknown>;
  status: RowStatus;
  /** Why it was refused, in the server's or the table's words. */
  message?: string;
}

/** The columns: every parameter the form would draw. A hidden parameter is
 * seeded and sent as it is, never drawn (p.25), as on the form. */
export function tableColumns<P extends TableParameter>(parameters: P[]): P[] {
  return parameters.filter((p) => !p.hidden);
}

/** A row for `subject`, its values seeded as the form seeds them - from the
 * object, then the widget's local defaults, then the parameter's own (p.27,
 * p.512) - so a row shows the object it edits rather than empty boxes. */
export function rowFor(
  key: number,
  parameters: TableParameter[],
  subject: { id: string; properties?: Record<string, unknown> } | null,
  localDefaults: Record<string, unknown>,
): TableRow {
  return {
    key,
    subjectId: subject?.id ?? "",
    values: seedActionForm(parameters as never, subject?.properties ?? {}, localDefaults),
    status: "draft",
  };
}

function blank(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

/** What is wrong with each row before anything is sent, by row key.
 *
 * Three things, each a refusal the server would make a row later - and by
 * then the rows before it would have been written:
 *
 *   * no object picked;
 *   * a required parameter left empty;
 *   * **the same object in two rows** - p.512: "the requirement that edits do
 *     not conflict". Two rows editing one object would each overwrite the
 *     other, and which won would depend on the order they were sent in.
 *
 * Rows already submitted are not checked: they are done.
 */
export function rowProblems(
  rows: TableRow[],
  columns: TableParameter[],
): Map<number, string> {
  const problems = new Map<number, string>();
  const firstRowOf = new Map<string, number>();
  rows.forEach((row, index) => {
    if (row.status === "done") return;
    if (!row.subjectId) {
      problems.set(row.key, "Choose an object for this row.");
      return;
    }
    const earlier = firstRowOf.get(row.subjectId);
    if (earlier !== undefined) {
      problems.set(
        row.key,
        `This object is also in row ${earlier + 1}, and two edits to one object would conflict.`,
      );
      return;
    }
    firstRowOf.set(row.subjectId, index);
    const missing = columns.filter((c) => c.required && blank(row.values[c.api_name]));
    if (missing.length > 0) {
      problems.set(
        row.key,
        `${missing.map((c) => c.display_name || c.api_name).join(", ")} is required.`,
      );
    }
  });
  return problems;
}

/** Where Enter and Shift+Enter move from a cell: the same column one row
 * down or up, or nowhere at either end. Tab and Shift+Tab are the browser's,
 * along the row - a spreadsheet's two directions, without taking the arrow
 * keys from the select boxes and number fields that already use them. */
export function nextCell(
  row: number,
  column: number,
  rows: number,
  direction: "down" | "up",
): { row: number; column: number } | null {
  const next = direction === "down" ? row + 1 : row - 1;
  if (next < 0 || next >= rows) return null;
  return { row: next, column };
}

/** The rows a Submit sends: everything not already done. */
export function pendingRows(rows: TableRow[]): TableRow[] {
  return rows.filter((row) => row.status !== "done");
}
