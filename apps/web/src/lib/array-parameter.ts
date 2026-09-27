/** An array's value in a form, as a list of rows (§580; db 0087, db 0118).
 *
 * > "Array properties cannot contain null elements." (`object-link-types` p.86)
 *
 * A row being typed is blank before it is anything, and a blank row sent as
 * an element would be refused by the server's coercion - "" is not an integer,
 * and p.86 refuses a null. So the rows are kept as typed while the form is
 * open and **the blank ones are dropped when it is sent** (`submittedValues`):
 * an empty row is somebody who pressed Add and changed their mind.
 *
 * Pure, and in `lib/`, because vitest cannot parse `.tsx`.
 */

/** The value as rows: a list is its rows, and anything else is none. A JSON
 * array's text (how a typed default arrives) is read as its list. */
export function arrayItems(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  // Any text is tried, and only a list kept: a check that it starts with "["
  // first said the same thing twice (it survived the sweep as equivalent).
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed;
    } catch {
      // Not a list's text; nothing to show.
    }
  }
  return [];
}

export function withItem(items: readonly unknown[], index: number, next: unknown): unknown[] {
  return items.map((item, n) => (n === index ? next : item));
}

export function withoutItem(items: readonly unknown[], index: number): unknown[] {
  return items.filter((_, n) => n !== index);
}

/** What a new row starts as: a struct's is an empty record, every other
 * element's an empty entry. Never null, which p.86 refuses. */
export function blankItem(arrayOf: string): unknown {
  return arrayOf === "struct" ? {} : "";
}

/** Whether a row has anything in it: blank text, a struct with nothing
 * filled in, and nothing at all are blank; `false` and `0` are answers. */
export function isBlankItem(item: unknown): boolean {
  if (item === null || item === undefined) return true;
  if (typeof item === "string") return item.trim() === "";
  if (typeof item === "object" && !Array.isArray(item)) {
    return Object.values(item as Record<string, unknown>).every(isBlankItem);
  }
  return false;
}

/** Whether an array answers a required parameter: a row with something in
 * it (p.116: "Setting an array property to required ensures the presence of
 * at least one item"). */
export function hasItems(value: unknown): boolean {
  return arrayItems(value).some((item) => !isBlankItem(item));
}

/** The form's values as they are sent: each array parameter's blank rows
 * dropped. Every other value is sent as it is. */
export function submittedValues(
  values: Record<string, unknown>,
  parameters: readonly { api_name: string; data_type: string }[],
): Record<string, unknown> {
  const arrays = new Set(parameters.filter((p) => p.data_type === "array").map((p) => p.api_name));
  return Object.fromEntries(Object.entries(values).map(([name, value]) => [
    name,
    arrays.has(name) && Array.isArray(value) ? value.filter((item) => !isBlankItem(item)) : value,
  ]));
}
