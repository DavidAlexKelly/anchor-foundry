/**
 * p.489's Export event, as the file it writes (`workshop` p.489; §459).
 *
 * > "Export events take an object set variable as an input and trigger the
 * > export of the objects in the object set to either Excel or the user's
 * > clipboard. An application builder may optionally configure a file name and
 * > select the set of properties that should be included in the export."
 *
 * **CSV where p.489 says Excel**, which is the format p.489 itself falls back
 * to whenever the columns are not plain properties; `EXPORT_FORMATS` in
 * `workshop_events.py` says why there is no XLSX writer. The clipboard gets
 * **tab-separated** text instead, because that is what a spreadsheet makes
 * rows and columns of when it is pasted into one.
 *
 * Pure, so what is written can be checked without a browser: the effect in
 * `events.ts` fetches the rows and hands them here, and the download and the
 * clipboard are the only parts that are not.
 */

/** One row as the object set read returns it. */
export interface ExportRow {
  primary_key: string;
  properties: Record<string, unknown>;
}

/** A property as the object type describes it. */
export interface ExportProperty {
  api_name: string;
  display_name?: string | null;
}

export interface Column {
  /** `null` for the primary key, which is not a property. */
  apiName: string | null;
  header: string;
}

/** The most rows one export writes. A set larger than this is refused with a
 * sentence rather than cut short: a file that silently holds the first ten
 * thousand of fifty thousand objects reads as all of them. */
export const MAX_EXPORT_ROWS = 10000;

/** The columns, in the order the file has them.
 *
 * **The key first, always**: it is the one column that says which object a
 * row is, and a file without it cannot be joined back to anything. Then the
 * chosen properties in the order they were chosen, or every property in the
 * type's order when none were. A chosen name the type does not have keeps its
 * column, headed by the name, because dropping it would change the columns
 * under somebody's spreadsheet without a word.
 */
export function exportColumns(
  properties: readonly ExportProperty[],
  chosen?: readonly string[] | null,
): Column[] {
  const byName = new Map(properties.map((p) => [p.api_name, p]));
  const names = chosen && chosen.length > 0 ? chosen : properties.map((p) => p.api_name);
  return [
    { apiName: null, header: "Key" },
    ...names.map((name) => ({
      apiName: name,
      header: byName.get(name)?.display_name || name,
    })),
  ];
}

/** A value as text. Null is empty, not "null"; a structure is its JSON. */
function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** One CSV cell.
 *
 * **A cell that starts like a formula is written as text.** A spreadsheet
 * opening this file evaluates `=HYPERLINK(...)` or `+cmd|...` in a cell as a
 * formula, and the values are whatever somebody typed into a property - so a
 * leading `=`, `+`, `-`, `@` or tab gets an apostrophe in front, which the
 * spreadsheet shows as the text it was.
 */
export function csvCell(value: unknown): string {
  let cell = text(value);
  // Strings only: a number is a number, and "-5" written as "'-5" would turn
  // every negative figure in the file into text nobody can sum.
  if (typeof value === "string" && /^[=+\-@\t\r]/.test(cell)) cell = `'${cell}`;
  return /[",\r\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;
}

function valueOf(row: ExportRow, column: Column): unknown {
  return column.apiName === null ? row.primary_key : row.properties[column.apiName];
}

/** The file: a header row, then one row per object, CRLF as RFC 4180 has it. */
export function csvOf(columns: readonly Column[], rows: readonly ExportRow[]): string {
  const lines = [
    columns.map((c) => csvCell(c.header)).join(","),
    ...rows.map((row) => columns.map((c) => csvCell(valueOf(row, c))).join(",")),
  ];
  return `${lines.join("\r\n")}\r\n`;
}

/** The clipboard's text: tab-separated, which is what a spreadsheet splits a
 * paste on. A tab or line break inside a value would split it into cells of
 * its own, so each becomes a space. */
export function tsvOf(columns: readonly Column[], rows: readonly ExportRow[]): string {
  const cell = (value: unknown) => text(value).replace(/[\t\r\n]+/g, " ");
  return [
    columns.map((c) => cell(c.header)).join("\t"),
    ...rows.map((row) => columns.map((c) => cell(valueOf(row, c))).join("\t")),
  ].join("\n");
}

/** The download's name: the configured one, or the type and today's date.
 *
 * Reduced to characters every file system takes, and given a `.csv` ending
 * once - a builder who typed "sites.csv" should not get "sites.csv.csv".
 */
export function exportFileName(configured: string | null | undefined, typeName: string, now: Date): string {
  const day = now.toISOString().slice(0, 10);
  const base = (configured ?? "").trim() || `${typeName || "objects"} ${day}`;
  const safe = base.replace(/\.csv$/i, "").replace(/[^A-Za-z0-9 ._-]+/g, "_").trim() || "objects";
  return `${safe}.csv`;
}

/** Every row of a set, a page at a time, or a refusal when there are more
 * than `MAX_EXPORT_ROWS`.
 *
 * **Paged because store reads are**, and stopped by a short page for the
 * reason `collectKeys` gives: the set shrank between the count and the read.
 */
export async function collectRows(
  fetchPage: (offset: number, limit: number) => Promise<readonly ExportRow[]>,
  total: number,
  pageSize = 50,
): Promise<{ rows: ExportRow[] } | { refused: string }> {
  if (total > MAX_EXPORT_ROWS) {
    return {
      refused: `This set has ${total.toLocaleString()} objects; an export writes at most ${MAX_EXPORT_ROWS.toLocaleString()}. Narrow it first.`,
    };
  }
  const rows: ExportRow[] = [];
  for (let offset = 0; offset < total; offset += pageSize) {
    const page = await fetchPage(offset, pageSize);
    rows.push(...page);
    if (page.length < pageSize) break;
  }
  return { rows };
}

/** The derivations that keep their input set's object type. A traversal does
 * not: it lands on the far side of a link. */
const SAME_TYPE = new Set(["narrow_set", "filter_set"]);

/** Which object type a set variable holds, when the document alone can say.
 *
 * For the panel's property list. A set with its own definition names its
 * type; one narrowed or filtered from another has that one's. Anything else -
 * a traversal, a cycle nobody saved, a variable that is not a set - answers
 * `null`, and the panel asks for property names as text instead of guessing.
 */
export function staticTypeOf(
  variableId: string,
  variables: Record<string, {
    kind?: string;
    object_set?: { object_type_id?: string } | null;
    derivation?: { transform?: string; inputs?: string[] } | null;
  }>,
): string | null {
  const seen = new Set<string>();
  let current: string | undefined = variableId;
  while (current && !seen.has(current)) {
    seen.add(current);
    const variable: (typeof variables)[string] | undefined = variables[current];
    if (!variable || variable.kind !== "object_set") return null;
    if (variable.object_set?.object_type_id) return variable.object_set.object_type_id;
    const derivation: { transform?: string; inputs?: string[] } | null | undefined =
      variable.derivation;
    if (!derivation || !SAME_TYPE.has(derivation.transform ?? "")) return null;
    current = derivation.inputs?.[0];
  }
  return null;
}
