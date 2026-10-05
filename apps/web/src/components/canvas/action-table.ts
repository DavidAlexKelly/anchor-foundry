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

import type { ActionType } from "@/lib/types";
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

// ---- p.511's "CSV file upload capabilities" (§703) ---------------------------

/** A CSV file's rows, as RFC 4180 writes them: commas, double-quoted fields
 * that may hold commas, newlines and `""` for a quote, and either line ending.
 * Blank lines are dropped - a trailing newline is not a row. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  const body = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < body.length; i++) {
    const ch = body[i]!;
    if (quoted) {
      if (ch === '"') {
        if (body[i + 1] === '"') { field += '"'; i++; } else quoted = false;
      } else field += ch;
      continue;
    }
    if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      // A "\r\n" ends the row at the "\r"; the "\n" then ends an empty one,
      // which is dropped below like any blank line.
      row.push(field); field = "";
      if (row.some((cell) => cell !== "")) rows.push(row);
      row = [];
    } else field += ch;
  }
  row.push(field);
  if (row.some((cell) => cell !== "")) rows.push(row);
  return rows;
}

/** What a header names, decided once for the whole file. The object's column
 * is any of the names a person would write for it; a parameter's is its api
 * name or its display name, ignoring case and surrounding space - the two
 * names the table itself shows and the one the action is defined in. */
export interface CsvPlan {
  keyColumn: number;
  cells: { column: number; parameter: TableParameter }[];
  ignored: string[];
}

const KEY_HEADERS = new Set(["object", "primary key", "primary_key", "key"]);

export function csvPlan(header: string[], columns: TableParameter[]): CsvPlan {
  const norm = (text: string) => text.trim().toLowerCase();
  let keyColumn = -1;
  const cells: CsvPlan["cells"] = [];
  const ignored: string[] = [];
  header.forEach((name, index) => {
    const wanted = norm(name);
    if (keyColumn < 0 && KEY_HEADERS.has(wanted)) {
      keyColumn = index;
      return;
    }
    const parameter = columns.find(
      (c) => norm(c.api_name) === wanted || (c.display_name && norm(c.display_name) === wanted),
    );
    if (parameter && !cells.some((c) => c.parameter.api_name === parameter.api_name)) {
      cells.push({ column: index, parameter });
    } else if (name.trim()) {
      ignored.push(name.trim());
    }
  });
  return { keyColumn, cells, ignored };
}

/** A CSV cell as the value a cell control holds. Text is text, and the server
 * coerces it against the parameter's type as it does a typed one; a yes/no is
 * turned into one here because its control is a choice, not a box, and would
 * otherwise show a value it cannot hold. An empty cell is no value. */
export function csvValue(text: string, dataType: string | undefined): unknown {
  const trimmed = text.trim();
  if (dataType === "boolean") {
    const lower = trimmed.toLowerCase();
    if (["true", "yes", "1"].includes(lower)) return true;
    if (["false", "no", "0"].includes(lower)) return false;
  }
  return trimmed;
}

/** The file's rows as keys and the values the file gives for each. Cells the
 * file has no column for are left out, so the object's own values seed them. */
export function csvEntries(
  rows: string[][],
  plan: CsvPlan,
): { key: string; values: Record<string, unknown> }[] {
  return rows.map((row) => ({
    key: plan.keyColumn >= 0 ? (row[plan.keyColumn] ?? "").trim() : "",
    values: Object.fromEntries(plan.cells.map(({ column, parameter }) => [
      parameter.api_name, csvValue(row[column] ?? "", parameter.data_type),
    ])),
  }));
}

/** Whether these rows can go as the Object Table's batch (§796): an action
 * whose every rule changes the row's own object, which `inline_edit_refusals`
 * says, and every row about an object. Any other action goes as a batch call
 * of rows (§800), which takes creates, deletes and links too. */
export function batchable(
  actionType: Pick<ActionType, "inline_edit_refusals" | "object_type_id">,
  rows: readonly Pick<TableRow, "subjectId">[],
): boolean {
  return (actionType.inline_edit_refusals ?? []).length === 0 && !!actionType.object_type_id
    && rows.every((row) => !!row.subjectId);
}

/** Why these rows cannot go as one batch, or null (§796): p.512's "batch
 * call limits apply to the table layout", which is p.131's row limit. */
export function batchProblem(rowCount: number, limit: number): string | null {
  return rowCount > limit
    ? `One submission takes at most ${limit} rows (action-types p.131).` : null;
}

/** What a batch call of rows created or modified (§800): every row's own
 * output, for p.513's output set - none when the batch did not land. */
export function rowsTouched(result: {
  ok: boolean;
  results?: { touched?: { object_type_id: string; primary_key: string; change: string }[] }[];
}): { object_type_id: string; primary_key: string; change: string }[] {
  return result.ok ? (result.results ?? []).flatMap((r) => r.touched ?? []) : [];
}

/** What a batch's answer makes of every row it carried: all done, or all
 * refused with the batch's reason - p.138's whole-or-nothing. */
export function afterBatch(result: { ok: boolean; error?: string | null }):
    { status: "done" | "refused"; message?: string } {
  return result.ok ? { status: "done" } : { status: "refused", message: result.error ?? "Refused." };
}

