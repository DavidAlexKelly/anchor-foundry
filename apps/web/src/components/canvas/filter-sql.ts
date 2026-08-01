/**
 * Building a filtered SELECT for a canvas widget (ROADMAP Canvas item 1).
 *
 * **Why filtering happens server-side.** The obvious shortcut is to fetch the
 * preview page and filter the rows in the browser. That would be quietly
 * wrong: the preview is a page, so the widget would be filtering *the first
 * 50 rows* while appearing to filter the dataset. A table showing "no
 * matches" because the match is on row 2,000 is worse than no filter at all.
 *
 * **On SQL by string-building.** The value comes from a viewer, so it is
 * escaped here rather than interpolated raw, and the column comes from a
 * picker populated by the dataset's own schema — a closed set, not free text.
 * Worth being precise about what this does and does not affect: the
 * `/datasets/{id}/query` endpoint already accepts arbitrary SQL from a
 * project *viewer*, so this adds no capability anyone lacked; the escaping is
 * about correctness (a value containing an apostrophe must still work) rather
 * than about a privilege boundary. The better long-term shape is structured
 * filters on the endpoint, so the server builds the SQL — recorded in STATUS
 * rather than pretended away.
 */

/** A DuckDB string literal. Doubling the quote is the standard escape and the
 * only one needed: identifiers are not user text here, and values arrive as
 * JS strings. */
export function sqlLiteral(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

/** A quoted identifier. Column names come from the dataset schema, but they
 * can still contain spaces or a double quote, and an unquoted identifier
 * would break on both. */
export function sqlIdentifier(name: string): string {
  return `"${name.replace(/"/g, '""')}"`;
}

export type FilterOperator = "equals" | "contains";

/**
 * The query a filtered dataset table runs. `dataset` is the table name the
 * query endpoint exposes for the dataset's Parquet file
 * (`dataset_engine.query` creates it) — not `src`, which is the alias the
 * *model* layer uses for its inputs.
 *
 * Returns null when there is nothing to filter by, so the caller falls back
 * to the plain preview rather than issuing `WHERE column = ''` — an unset
 * parameter means "show everything", not "show rows whose value is empty".
 */
export function filteredQuery(
  column: string | null | undefined,
  operator: FilterOperator,
  value: unknown,
  limit = 200,
): string | null {
  if (!column) return null;
  if (value === null || value === undefined || value === "") return null;
  const text = String(value);
  const col = sqlIdentifier(column);
  // CAST so a filter works against a numeric or date column too: the value
  // arrives from a dropdown or a text box as text either way, and comparing
  // text to a BIGINT is an error rather than a non-match.
  const predicate =
    operator === "contains"
      ? `CAST(${col} AS VARCHAR) ILIKE ${sqlLiteral(`%${text}%`)}`
      : `CAST(${col} AS VARCHAR) = ${sqlLiteral(text)}`;
  return `SELECT * FROM dataset WHERE ${predicate} LIMIT ${limit}`;
}

/** Distinct values of a column, for a dropdown's options. Capped: a dropdown
 * with 50,000 entries is not a dropdown, and the cap being visible here is
 * better than a widget that silently takes a minute to open. */
export function distinctValuesQuery(column: string, limit = 200): string {
  return (
    `SELECT DISTINCT ${sqlIdentifier(column)} AS value FROM dataset ` +
    `WHERE ${sqlIdentifier(column)} IS NOT NULL ORDER BY 1 LIMIT ${limit}`
  );
}
