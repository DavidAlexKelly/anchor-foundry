/**
 * A lineage graph's view, in the address bar (§360; `data-lineage` p.12).
 *
 * > "**Get quick share link**: Generates a shareable link that provides
 * > read-only access to your graph." (p.12)
 *
 * **There is no share button here, and that is deliberate.**
 * `CopyLinkButton` already exists and copies `window.location.href`, with the
 * reasoning written beside it: "the address bar already says where you are,
 * and a button that rebuilt the link from component state could disagree with
 * it." So the work is to keep the URL *true* — put the view in it as the view
 * changes — and let the button that already works do the sharing. Building a
 * second one would be the §191 hazard this repository keeps finding.
 *
 * Putting the view in the URL also fixes something the pipeline page had since
 * it was written: a reload lost everything, because none of it was anywhere.
 *
 * Short keys because a selection is node ids and a node id is 44 characters;
 * `sel` forty times over is already a long URL without spelling it out.
 */

import type { GraphView } from "@/lib/pipeline-graph";

/** What `useUrlState().set` takes: a value, a list, or nothing to remove it. */
type Change = Record<string, string | string[] | undefined>;

/**
 * The view as URL parameters, with the empty parts removed rather than blank.
 *
 * `undefined` is `set`'s "delete this key", so a view that loses its column
 * takes the parameter out of the link instead of leaving `col=` behind — a
 * key whose value is its default has no business in a shared link, which is
 * `useUrlState`'s own rule.
 */
export function toParams(view: GraphView): Change {
  return {
    focus: view.focus,
    col: view.column,
    q: view.query,
    kind: view.kinds && view.kinds.length > 0 ? view.kinds : undefined,
    sel: view.selected && view.selected.length > 0 ? view.selected : undefined,
    colour: view.colouring,
  };
}

/**
 * The view a link carries, or an empty one.
 *
 * **Nothing here is trusted.** A URL is typed by hand and pasted by people, so
 * this reads what it recognises and ignores the rest; the graph then draws a
 * view that is missing a part rather than refusing to draw at all. The server
 * refuses a malformed `focus` when it is *saved* (`saved_graphs.parse`), which
 * is the place where refusing helps somebody.
 */
export function fromParams(params: URLSearchParams): GraphView {
  const view: GraphView = {};
  const focus = params.get("focus");
  if (focus) view.focus = focus;
  const column = params.get("col");
  if (column) view.column = column;
  const query = params.get("q");
  if (query) view.query = query;
  const kinds = params.getAll("kind").filter(Boolean);
  if (kinds.length > 0) view.kinds = kinds;
  const selected = params.getAll("sel").filter(Boolean);
  if (selected.length > 0) view.selected = selected;
  // Read as typed and narrowed by `colouringIn` where the graph reads it, for
  // the reason nothing else here is validated either: a link somebody
  // mistyped should open on a graph missing a part, not on a refusal.
  const colouring = params.get("colour");
  if (colouring) view.colouring = colouring;
  return view;
}
