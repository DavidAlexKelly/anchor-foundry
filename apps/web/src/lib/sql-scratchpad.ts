/**
 * What the SQL Scratchpad panel offers (§306; p.15).
 *
 *     "The SQL helper lets you quickly test out SQL queries. Write a SQL query
 *      and click [run] to preview the results of your query… To view queries
 *      marked as favorites, go to the [star] tab. To view a history of queries
 *      ran in the SQL helper, go to the [clock] tab." (p.15)
 *
 * The server owns every refusal — the reference syntax, the branch qualifier,
 * what the project has — and it owns the history, which is a table with a
 * retention rule. What lives here is what to *offer*: the same division
 * `explorer.ts`, `tags.ts` and `branch-columns.ts` take.
 *
 * **Nothing here parses SQL.** `scratchpad.py` is the one reader of the
 * reference syntax, and a browser-side copy that decided a query "looks like
 * it has no datasets" would be a second parser disagreeing with the one that
 * matters — the same mistake §304 avoided by sending the file to the server.
 */
import type { ScratchpadQuery, ScratchpadResult } from "./types";

/** p.15's two tabs. */
export type ScratchpadTab = "query" | "history" | "favourites";

/**
 * Whether Run can be pressed.
 *
 * Only that there is something to run. Whether it *parses* is the server's
 * answer, and guessing it here is how the panel starts refusing queries the
 * server would have accepted.
 */
export function canRun(sql: string): boolean {
  return sql.trim() !== "";
}

/**
 * What the tab says, with its count.
 *
 * The count is on the tab rather than inside it because it is the reason to
 * open the tab — "History" alone makes you click to find out whether there is
 * anything there, and the answer is usually no on a repository you have not
 * used.
 */
export function tabLabel(tab: ScratchpadTab, count: number): string {
  if (tab === "query") return "Query";
  const name = tab === "history" ? "History" : "Favourites";
  return count > 0 ? `${name} (${count})` : name;
}

/**
 * The one-line form of a query, for a list.
 *
 * **Whitespace collapsed, not the first line taken.** A query whose first line
 * is `SELECT` — which is most of them once anybody formats one — would give a
 * list of rows all reading "SELECT", and the whole point of the list is to
 * tell them apart.
 */
export function oneLine(sql: string, limit = 80): string {
  const flat = sql.replace(/\s+/g, " ").trim();
  return flat.length <= limit ? flat : `${flat.slice(0, limit - 1)}…`;
}

/**
 * What a history row says under the query.
 *
 * The run count only when it is more than one: "ran once" on every row is
 * noise, and the rows where it is not one are the queries somebody kept
 * coming back to.
 */
export function ranNote(query: ScratchpadQuery): string | null {
  return query.run_count > 1 ? `ran ${query.run_count} times` : null;
}

/** p.15's star, as a label that says what pressing it does. */
export function starLabel(query: ScratchpadQuery): string {
  return query.favourite ? "Remove from favourites" : "Add to favourites";
}

/**
 * What an empty tab says.
 *
 * **Three absences, three remedies**, and the favourites one is the one that
 * matters: an empty favourites tab beside a full history means "you have not
 * starred anything", which is a thing the reader can do right now — and a
 * shared "Nothing here" would hide it.
 */
export function emptyReason(tab: ScratchpadTab, historyCount: number): string | null {
  if (tab === "query") return null;
  if (tab === "history") {
    return (
      "Nothing yet. A query joins this list once it has run — so what is here " +
      "is what worked, not what you typed."
    );
  }
  if (historyCount > 0) {
    return "Nothing starred yet. Star a query in History to keep it here.";
  }
  return "Nothing starred yet, because nothing has run yet.";
}

/**
 * The warning over a result, or nothing.
 *
 * A scratchpad runs on a *sample*, like the Preview panel, and for the same
 * reason: it is for finding out what is in a dataset, and running the real
 * thing over every row of a large one makes the panel unusable rather than
 * accurate. A join or a `group by` over a sample gives an answer that is not
 * the answer, and a panel that did not say so would quietly mislead.
 */
export function sampleWarning(result: ScratchpadResult): string | null {
  if (!result.sampled) return null;
  const used = result.inputs
    .filter((i) => i.sampled)
    .map((i) => `${i.dataset} (${i.rows_used.toLocaleString()} of ${i.rows_available.toLocaleString()})`);
  return (
    `This ran on a sample: ${used.join(", ")}. Joins and aggregates over a ` +
    "sample give an answer, not the answer."
  );
}

/**
 * Whether the rewritten query is worth showing beside the original.
 *
 * **Only when it differs.** Backticks are Foundry's engine and not ours, so
 * somebody who typed p.15's syntax and got an error from DuckDB needs to see
 * what DuckDB was given — but a query that was not rewritten showing itself
 * twice is a panel explaining a translation that did not happen.
 */
export function showRewritten(sql: string, result: ScratchpadResult): boolean {
  return result.ran.trim() !== sql.trim();
}
