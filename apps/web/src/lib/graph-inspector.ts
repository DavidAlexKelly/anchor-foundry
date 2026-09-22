/**
 * The graph's own Preview and Code panels (§439; `data-lineage` p.45-47).
 *
 * > "To see a preview of a dataset or media set, select it in your data
 * > lineage graph, then choose the **Preview** tab in the bottom left of the
 * > interface." (p.45)
 *
 * > "When the dataset preview expands, you can scroll through the first 300
 * > rows of the selected dataset. You can also search for specific columns
 * > using the **Search columns…** field… Select the **Code** tab to view the
 * > code logic of the selected dataset or media set. From the Code view, you
 * > can make quick edits, search for items, or open the code in the
 * > repository." (p.47)
 *
 * **The point is the word "without".** The graph already had an *Open* button,
 * and Open answers neither of p.45's questions: it leaves the picture the
 * reader was asking them about. Somebody tracing why a column is wrong three
 * hops downstream needs to see the rows and the transform of each hop in turn,
 * and a tab that sends them to another application loses the selection, the
 * colouring and the layout every time.
 *
 * **Two of p.47's four verbs are here and two are not**, which is a decision
 * rather than a stopping point:
 *
 *   - *scroll the rows* and *search the columns* — built;
 *   - *open the code in the repository* — built, as a link, because the
 *     repository application already opens a file from `?file=`;
 *   - *make quick edits* — ○, and it stays ○. This platform has one editor for
 *     a transform's body, in the repository application, and `services/
 *     models.py` refuses a direct edit to a repository-authored model at all
 *     (db 0038). A second editor on a lineage graph would either be a control
 *     that cannot save (§214) or a second implementation of the same rules
 *     (§292). The link is the honest version of that verb.
 *
 * Pure and in `lib/` because vitest cannot parse `.tsx`. What the panel *is*
 * is a component; which tabs a node offers, and which columns a query keeps,
 * is arithmetic — and the tab question is the one with a real bug in it.
 */
import type { PipelineGraph, PipelineNode, TabularResult } from "./types";

export type InspectorTab = "preview" | "code";

/** p.45's two tab names, kept verbatim. */
export const TAB_LABELS: Record<InspectorTab, string> = {
  preview: "Preview",
  code: "Code",
};

/**
 * The transform that writes this dataset, or null.
 *
 * Read off the edges the graph already carries rather than asked for: an edge
 * into a dataset comes from the model that builds it, and the graph is the one
 * place that fact is already assembled. A second query would be a second
 * answer to a question this object answers (§292).
 *
 * **Null is p.47's own case**, not an error: "Uploaded and writeback datasets
 * do not have associated code to view in Data Lineage." An uploaded dataset is
 * a root of the graph, and a root has nothing pointing into it.
 */
export function producerOf(graph: PipelineGraph, nodeId: string): PipelineNode | null {
  const from = graph.edges.filter((e) => e.to === nodeId).map((e) => e.from);
  for (const node of graph.nodes) {
    if (node.kind === "model" && from.includes(node.id)) return node;
  }
  return null;
}

/**
 * Which tabs a selected node offers, in p.45's order.
 *
 * **A tab that would be empty is not drawn**, which is the same rule §214
 * keeps arriving at: a Code tab on an uploaded dataset would open onto a
 * sentence apologising for itself, and a reader who clicked it learned only
 * that the tab was a lie. `noCodeNote` says it where it is useful — beside the
 * tabs that *are* there — rather than behind one that is not.
 *
 * An object type and a data source get neither: neither holds rows of its own
 * here, and neither is written by a transform.
 */
export function tabsFor(node: PipelineNode, graph: PipelineGraph): InspectorTab[] {
  if (node.kind === "model") return ["code"];
  if (node.kind !== "dataset") return [];
  return producerOf(graph, node.id) ? ["preview", "code"] : ["preview"];
}

/**
 * Which tab stays open when the selection moves.
 *
 * **By name, and falling back to the first rather than to nothing.** Selecting
 * one dataset after another should keep the reader on Preview — that is the
 * whole workflow p.45 describes, hop by hop down a pipeline. But the tabs a
 * node offers are not the same for every node, so a panel that simply kept its
 * state would sit on `"code"` over an uploaded dataset and render nothing at
 * all, with a tab strip that highlighted a tab it was not showing.
 */
export function keepTab(tabs: readonly InspectorTab[], open: InspectorTab | null): InspectorTab | null {
  if (tabs.length === 0) return null;
  if (open !== null && tabs.includes(open)) return open;
  return tabs[0]!;
}

/** Why there is no Code tab on this node, for the reader looking for one.
 *
 * p.47's sentence in this platform's vocabulary. It names the two ways a
 * dataset gets here without a transform, because "no code" alone reads as
 * something missing rather than as something true. */
export function noCodeNote(node: PipelineNode): string | null {
  if (node.kind !== "dataset") return null;
  return (
    "Nothing in this project builds this dataset — it was uploaded, or filled "
    + "by a data source — so there is no transform to read."
  );
}

/**
 * p.47's *Search columns…*, over a preview's column names.
 *
 * Substring and case-insensitive, which is what a field called *search* means
 * where §428's palette is a subsequence: a palette is typed in three letters
 * and a column name is one somebody half-remembers.
 *
 * **The same object back when the query is empty.** A panel keyed on the
 * result would re-render on every keystroke that changed nothing, and a table
 * of three hundred rows is exactly where that is felt.
 */
export function narrow(result: TabularResult, query: string): TabularResult {
  const q = query.trim().toLowerCase();
  if (!q) return result;
  const keep = result.columns
    .map((column, index) => ({ column, index }))
    .filter(({ column }) => column.name.toLowerCase().includes(q));
  return {
    ...result,
    columns: keep.map((k) => k.column),
    rows: result.rows.map((row) => keep.map((k) => row[k.index])),
  };
}

/**
 * What the panel says about a column search that hid something.
 *
 * **Null when nothing is hidden**, because a count on a table nobody filtered
 * is noise. A search that matched nothing gets a sentence rather than an empty
 * table — §226's rule, which is that a table of no columns answers nothing and
 * looks exactly like a dataset with no columns.
 */
export function columnsNote(result: TabularResult, query: string): string | null {
  if (!query.trim()) return null;
  const kept = narrow(result, query).columns.length;
  const total = result.columns.length;
  if (kept === total) return null;
  if (kept === 0) return `No column matches “${query.trim()}”`;
  return `${kept} of ${total} columns`;
}

/**
 * What the preview says it is showing.
 *
 * **Says it is a sample whenever it is one**, which is `truncated`'s job — the
 * reader who scrolls to the bottom of three hundred rows and finds no more has
 * to be told whether that is the dataset or the window. p.47 is explicit that
 * it is a window.
 */
export function previewNote(result: TabularResult): string {
  const shown = result.rows.length;
  if (!result.truncated) {
    return shown === 1 ? "1 row" : `${shown.toLocaleString()} rows`;
  }
  return `First ${shown.toLocaleString()} of ${result.total_rows.toLocaleString()} rows`;
}

/**
 * p.47's "open the code in the repository".
 *
 * The repository application opens a file from `?file=`, which is the address
 * §428's command palette already navigates by — so this is a link rather than
 * a second way to open a file, and it survives the repository being renamed
 * because `/r/{id}` is the stable address (§435).
 *
 * Null when the transform is authored directly: there is no file to open, and
 * a link to the repository's root would be a link somewhere the reader did not
 * ask to go.
 */
export function fileHref(
  repository: { resource_id: string } | null | undefined,
  path: string | null,
): string | null {
  if (!repository || !path) return null;
  return `/r/${repository.resource_id}?file=${encodeURIComponent(path)}`;
}
