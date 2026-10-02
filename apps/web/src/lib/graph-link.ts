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
    layout: view.layout,
    // p.11's moved cards (§606), one `pos` per card as `<node>@<x>,<y>`: a
    // node id has no `@` in it, so the last one splits it from its place.
    pos: view.positions && Object.keys(view.positions).length > 0
      ? Object.entries(view.positions).map(([id, at]) => `${id}@${at.x},${at.y}`)
      : undefined,
    // p.38's custom colours (§682), one `paint` per card as `<node>@<colour>`.
    paint: view.paints && Object.keys(view.paints).length > 0
      ? Object.entries(view.paints).map(([id, paint]) => `${id}@${paint}`)
      : undefined,
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
  const layout = params.get("layout");
  if (layout) view.layout = layout;
  // Read as written, and a part that is not a place is skipped rather than
  // the link refused - `movesIn` narrows what the graph draws from it.
  const positions: Record<string, { x: number; y: number }> = {};
  for (const entry of params.getAll("pos")) {
    const at = entry.lastIndexOf("@");
    const [x, y] = entry.slice(at + 1).split(",").map(Number);
    if (at > 0 && Number.isFinite(x) && Number.isFinite(y)) {
      positions[entry.slice(0, at)] = { x: x!, y: y! };
    }
  }
  if (Object.keys(positions).length > 0) view.positions = positions;
  // Read as written; `paintsIn` narrows it to the palette.
  const paints: Record<string, string> = {};
  for (const entry of params.getAll("paint")) {
    const at = entry.lastIndexOf("@");
    if (at > 0) paints[entry.slice(0, at)] = entry.slice(at + 1);
  }
  if (Object.keys(paints).length > 0) view.paints = paints;
  return view;
}
