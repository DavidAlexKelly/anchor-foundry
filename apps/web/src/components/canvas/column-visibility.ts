/**
 * p.225's variable-backed column visibility, for the Object Table (§610).
 *
 * > "Variable-backed column visibility: When enabled, allows control over
 * > which columns are visible using a string array variable containing the
 * > API names of visible columns. This array variable also controls the order
 * > that columns appear in. If the string array is empty, all configured
 * > columns will be shown in the table." (p.225)
 *
 * **The array chooses among the configured columns; it does not add to
 * them.** "Configured" is p.225's own word, and it is what keeps the table's
 * settings meaningful: a column the author left out stays out, whatever a
 * variable some other widget writes happens to say. With no columns
 * configured the table shows every property, so that is what the array
 * chooses from.
 *
 * **A name that is not a column is dropped, and said** (`unknownColumns`), in
 * the builder where somebody can act on it. A variable written by a Select
 * widget is a list somebody typed or picked, and a misspelled entry
 * silently hiding nothing would look like the feature not working.
 */

/** The columns to draw, in order. `value` is the variable's resolved value,
 *  read as a document holds it (§212): anything but a list of names reads as
 *  empty, which is "all configured columns". */
export function visibleColumns(configured: readonly string[], value: unknown): string[] {
  const names = namesIn(value);
  if (names.length === 0) return [...configured];
  const known = new Set(configured);
  return names.filter((name) => known.has(name));
}

/** The names the variable holds that are not columns of this table. */
export function unknownColumns(configured: readonly string[], value: unknown): string[] {
  const known = new Set(configured);
  return namesIn(value).filter((name) => !known.has(name));
}

function namesIn(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const entry of value) {
    if (typeof entry !== "string") continue;
    const name = entry.trim();
    // Once each, in the first place it is listed: the same column twice is
    // one column, and drawing it twice would be two cells saying one thing.
    if (name && !out.includes(name)) out.push(name);
  }
  return out;
}
