/**
 * Exploring a source (`data-connection` p.142-143; decision 0015; §269).
 *
 * §268 built `preview()` on every connector and put it behind a route, and
 * left it reachable only by posting JSON — the shape §252 named, closed here as
 * it was for notify rules (§258), webhooks (§261), egress policies (§264) and
 * exports (§267).
 *
 * p.143 gives the screen four panels. Two of them are this module's business:
 *
 *   1. "Find and add tables and views from the source system… Use the free
 *      text search helper to find specific tables, or browse the tree."
 *   3. "Table details: Preview a sample of the selected table."
 *
 * The other two are not built and decision 0015 §7 says why: the relationship
 * graph needs foreign keys `DiscoveredColumn` does not carry, and Foundry says
 * of its own graph that it "is not always available".
 *
 * **The half worth reading is what the screen has to say about the sample.**
 * A preview is a *sample* — unordered, capped, and occasionally shortened — and
 * a table of rows that says none of that is a table somebody will reason about
 * as though it were the data. Every function below that returns a sentence
 * exists because of a specific wrong conclusion a silent screen invites.
 */
import type { DiscoveredTable, SourcePreview } from "./types";

/** How a table matched a search, so the tree can say why it is there.
 *
 * `column` is the interesting one. p.143 asks for a helper that finds
 * "specific tables", and searching column names as well is what makes it
 * useful — "which table has `customer_email`" is the question people actually
 * arrive with. But a table appearing under a query that is nowhere in its name
 * looks like a bug, so the match says where it came from.
 */
export type MatchKind = "name" | "schema" | "column";

export interface Match {
  table: DiscoveredTable;
  kind: MatchKind;
  /** The column that matched, when `kind` is `"column"`. */
  via: string | null;
}

/** A discovered entry's identity: the (schema, name) pair, as one string.
 *
 * `schema.name` split on the first dot is ambiguous the moment a schema
 * contains one, which object storage makes ordinary — a "schema" there is a
 * folder. The separator is a character that cannot occur in either half.
 */
export const KEY_SEP = "\u0000";

export function tableKey(t: { schema_name: string; name: string }): string {
  return `${t.schema_name}${KEY_SEP}${t.name}`;
}

/** What a table is called on screen. A file at the root of an object-storage
 * prefix has no folder, and showing it as `.orders.csv` would be noise. */
export function tableLabel(t: { schema_name: string; name: string }): string {
  return t.schema_name ? `${t.schema_name}/${t.name}` : t.name;
}

/** p.143's free-text helper.
 *
 * Case-insensitive and a substring rather than a prefix, because a table
 * called `stg_customer_orders` is one somebody looks for by typing `orders`.
 * Name first, then schema, then columns — so a table whose *name* matches is
 * never reported as a column match, which would be true and useless.
 */
export function search(
  tables: readonly DiscoveredTable[],
  query: string,
): Match[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return tables.map((table) => ({ table, kind: "name", via: null }));

  const found: Match[] = [];
  for (const table of tables) {
    if (table.name.toLowerCase().includes(needle)) {
      found.push({ table, kind: "name", via: null });
      continue;
    }
    if (table.schema_name.toLowerCase().includes(needle)) {
      found.push({ table, kind: "schema", via: null });
      continue;
    }
    const column = table.columns.find((c) => c.name.toLowerCase().includes(needle));
    if (column) found.push({ table, kind: "column", via: column.name });
  }
  return found;
}

/** Why a match is in the list, or null when it needs no explanation. */
export function matchNote(match: Match): string | null {
  if (match.kind === "column") return `matched column ${match.via}`;
  if (match.kind === "schema") return `matched folder ${match.table.schema_name}`;
  return null;
}

/** The tree, grouped as p.143 draws it. Insertion order is kept rather than
 * sorted: `discover` returns a source's own ordering, and re-sorting would
 * hide the fact that two schemas came back interleaved. */
export function bySchema(matches: readonly Match[]): [string, Match[]][] {
  const groups = new Map<string, Match[]>();
  for (const match of matches) {
    const key = match.table.schema_name;
    const list = groups.get(key);
    if (list) list.push(match);
    else groups.set(key, [match]);
  }
  return [...groups.entries()];
}

/** Whether a sync can read this entry (`isSyncable`'s rule, on the tree).
 *
 * Views are excluded from *syncing* and included in *previewing*, which is not
 * an inconsistency: a view is exactly the thing somebody wants to look at
 * before finding out they cannot sync it. p.143 says "tables and views" for
 * exploration and this platform has always said tables for syncs.
 */
export function isSyncable(t: { kind: string }): boolean {
  return t.kind !== "view";
}

/** Why the Create-a-sync button is unavailable, or null when it is not. */
export function syncBlockedReason(t: { kind: string }): string | null {
  return t.kind === "view"
    ? "A sync reads tables and files; this is a view. Preview it here, or sync the tables behind it."
    : null;
}

/** p.145: "Explore and create syncs … begin creating syncs directly from the
 * exploration view." The dataset a sync from here would default to.
 *
 * The table's own name, with the folder dropped: an object-storage entry is
 * `nested/regions.csv`, and a dataset called that would be one nobody could
 * find. `SyncDialog` applies the same default, and this is the same rule in
 * the one place both can reach.
 */
export function defaultDatasetName(t: { name: string }): string {
  return t.name;
}

/** What the sample is, in a sentence the screen puts above it.
 *
 * **The row count alone is a lie by omission.** "50 rows" beside a table of
 * fifty rows reads as the table having fifty rows, which is exactly the wrong
 * conclusion and the one somebody will carry into a decision about a sync.
 */
export function sampleSummary(preview: SourcePreview): string {
  const rows = preview.rows.length;
  const columns = preview.columns.length;
  if (rows === 0) {
    return columns === 0
      ? "No rows, and no columns — this source returned nothing at all."
      : `No rows. The ${count(columns, "column")} are there; the table is empty.`;
  }
  // "all 12 rows" and "50 of more than 50 rows" are the two states, and the
  // difference is the whole point: the first is the table, the second is a
  // sample of it, and a bare "50 rows" would read as the first while meaning
  // the second.
  const many = preview.more ? `${rows} of more than ${rows}` : `all ${rows}`;
  return `${many} ${plural(rows, "row")}, ${count(columns, "column")}.`;
}

/** Decision 0015 §5, said where the rows are.
 *
 * There is no ORDER BY, so these are not the first rows and are not stable
 * between presses. p.161 uses the phrase for the equivalent choice on the file
 * side: "a non-deterministic subset". Only said when it could mislead — with
 * every row on screen there is no subset to be non-deterministic about.
 */
export function sampleCaveat(preview: SourcePreview): string | null {
  return preview.more
    ? "These are a sample, not the first rows — the source chooses which, and may choose differently next time."
    : null;
}

/** Decision 0015 §4's one inexactness, counted.
 *
 * A shortened value and a real one ending in an ellipsis are indistinguishable
 * on the cell, so the count is what tells somebody that shortening happened at
 * all. Nothing is said when nothing was shortened.
 */
export function shortenedNote(preview: SourcePreview): string | null {
  const n = preview.truncated_cells;
  if (n <= 0) return null;
  return `${count(n, "long value")} shortened to fit — the sync stores ${
    n === 1 ? "it" : "them"
  } whole.`;
}

/** A cell as the screen shows it.
 *
 * **`null` gets a word, not a blank.** The server takes care to send `null`
 * rather than `""` precisely so an empty column can be told from a missing
 * one, and rendering both as an empty cell would throw that away at the last
 * step.
 */
export function cell(value: string | null): { text: string; isNull: boolean } {
  return value === null ? { text: "null", isNull: true } : { text: value, isNull: false };
}

/** The word, pluralised. Two helpers rather than one that sometimes includes
 * the number, because a helper whose output has to be regexed by its caller is
 * two functions wearing one name. */
function plural(n: number, word: string): string {
  return n === 1 ? word : `${word}s`;
}

/** The number and the word. */
function count(n: number, word: string): string {
  return `${n} ${plural(n, word)}`;
}
