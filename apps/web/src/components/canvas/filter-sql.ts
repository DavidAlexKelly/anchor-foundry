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
  const predicate = filterPredicate(column, operator, value);
  if (!predicate) return null;
  return `SELECT * FROM dataset WHERE ${predicate} LIMIT ${limit}`;
}

/** The WHERE body a filter parameter produces, with no SELECT around it —
 * shared by the table filter and the charts so the two cannot drift on what
 * "filtered" means. Null when there is nothing to filter by, which callers
 * read as "no filter" rather than "match nothing".
 *
 * The CAST is why a filter works against a numeric or date column at all: the
 * value arrives from a dropdown or a text box as text either way, and
 * comparing text to a BIGINT is an error rather than a non-match. */
export function filterPredicate(
  column: string | null | undefined,
  operator: FilterOperator,
  value: unknown,
): string | null {
  if (!column) return null;
  if (value === null || value === undefined || value === "") return null;
  const col = sqlIdentifier(column);
  const text = String(value);
  return operator === "contains"
    ? `CAST(${col} AS VARCHAR) ILIKE ${sqlLiteral(`%${text}%`)}`
    : `CAST(${col} AS VARCHAR) = ${sqlLiteral(text)}`;
}

/**
 * The rows behind a map bound to a dataset (ROADMAP Canvas item 4).
 *
 * Two column shapes, because both exist in real data and one of them is the
 * platform's own: a geopoint property synced back to a dataset writes
 * `"lat,lon"` into a single column, while data arriving from anywhere else
 * usually carries separate latitude and longitude columns. The returned rows
 * are `[label, point]` or `[label, lat, lon]` — the arity tells the widget
 * which shape it asked for, and `toLatLon` in `map.tsx` reads both.
 *
 * Rows with no location are **not** filtered out here. They cost a row of the
 * limit, and that is the price of being able to say "40 placed, 3 without a
 * usable location" instead of quietly showing 40 and calling it the answer.
 */
export function mapQuery(options: {
  locationColumn?: string | null;
  latColumn?: string | null;
  lonColumn?: string | null;
  labelColumn?: string | null;
  filterColumn?: string | null;
  filterOperator?: FilterOperator;
  filterValue?: unknown;
  limit?: number;
}): string | null {
  const { locationColumn, latColumn, lonColumn, labelColumn } = options;
  const usesPair = !!latColumn && !!lonColumn;
  if (!usesPair && !locationColumn) return null;

  const label = labelColumn ? sqlIdentifier(labelColumn) : "NULL";
  const columns = usesPair
    ? `${label} AS label, ${sqlIdentifier(latColumn!)} AS lat, ${sqlIdentifier(lonColumn!)} AS lon`
    : `${label} AS label, CAST(${sqlIdentifier(locationColumn!)} AS VARCHAR) AS point`;
  const where = filterPredicate(
    options.filterColumn,
    options.filterOperator ?? "equals",
    options.filterValue,
  );
  const clause = where ? ` WHERE ${where}` : "";
  return `SELECT ${columns} FROM dataset${clause} LIMIT ${options.limit ?? 500}`;
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

// ---- aggregation (ROADMAP Canvas item 2) ------------------------------------

export type ChartKind = "bar" | "line" | "pie" | "scatter";
export type Aggregate = "count" | "sum" | "avg" | "min" | "max";

/** Per-kind caps. A bar chart with 400 categories is a smear, a line with
 * 50,000 points is a solid block, and both are slow — so the cap is part of
 * the chart's definition rather than something the browser discovers. */
const LIMITS: Record<ChartKind, number> = {
  bar: 25,
  pie: 12,
  line: 200,
  scatter: 500,
};

function aggregateExpression(aggregate: Aggregate, measure: string | null | undefined): string | null {
  if (aggregate === "count") return "count(*)";
  if (!measure) return null;
  // CAST rather than TRY_CAST: a measure column that is not numeric should
  // fail visibly with DuckDB's own message, not silently sum to null and
  // draw an empty chart that looks like "no data".
  return `${aggregate}(CAST(${sqlIdentifier(measure)} AS DOUBLE))`;
}

/**
 * The query behind a chart (ROADMAP Canvas item 2).
 *
 * **Aggregation is server-side**, for a sharper version of the reason
 * filtering is: a chart that sums the preview page and labels it a total does
 * not merely show less data, it shows a *wrong number*, and a wrong number
 * with an axis on it looks authoritative. The roadmap offered "aggregated
 * client-side for small results"; there is no reliable way for the widget to
 * know a result is small before fetching it, so that option is not taken.
 *
 * No new endpoint either — `GROUP BY` through the existing query endpoint is
 * exactly the "lightweight aggregation" the item describes, and it inherits
 * the sandboxing (`enable_external_access=false`, memory limit, row cap) that
 * endpoint already applies.
 *
 * Returns null when the chart is not configured enough to draw, so the widget
 * can say what is missing instead of rendering an empty axis.
 */
export function chartQuery(options: {
  kind: ChartKind;
  dimension: string | null | undefined;
  measure: string | null | undefined;
  aggregate: Aggregate;
  filterColumn?: string | null;
  filterOperator?: FilterOperator;
  filterValue?: unknown;
}): string | null {
  const { kind, dimension, measure, aggregate } = options;
  if (!dimension) return null;

  // The filter reuses item 1's predicate verbatim, so a chart and a table
  // pointed at the same parameter always agree about which rows are in scope.
  const where = filterPredicate(
    options.filterColumn,
    options.filterOperator ?? "equals",
    options.filterValue,
  );
  const clause = where ? ` WHERE ${where}` : "";
  const dim = sqlIdentifier(dimension);

  if (kind === "scatter") {
    // No aggregation: a scatter plot's whole point is the individual points,
    // so grouping them would destroy the thing being looked at.
    if (!measure) return null;
    const y = sqlIdentifier(measure);
    const conditions = [`${dim} IS NOT NULL`, `${y} IS NOT NULL`];
    if (where) conditions.unshift(where);
    return (
      `SELECT ${dim} AS label, ${y} AS value FROM dataset ` +
      `WHERE ${conditions.join(" AND ")} LIMIT ${LIMITS.scatter}`
    );
  }

  const agg = aggregateExpression(aggregate, measure);
  if (!agg) return null;
  // A line chart is a series, so it sorts by its dimension; bar and pie
  // compare magnitudes, so they sort by value and the cap keeps the largest.
  const order = kind === "line" ? "1 ASC" : "2 DESC";
  return (
    `SELECT ${dim} AS label, ${agg} AS value FROM dataset${clause} ` +
    `GROUP BY 1 ORDER BY ${order} LIMIT ${LIMITS[kind]}`
  );
}
