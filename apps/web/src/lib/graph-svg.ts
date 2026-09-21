/**
 * p.12's "Export graph to SVG: Generates a static image of your lineage
 * graph" (§423).
 *
 * §360 built two of p.12's three save-and-share mechanisms and its row named
 * this as the third. It is a different kind of sharing from the other two,
 * which is why it is worth having beside them rather than instead: a saved
 * graph and a share link both hand somebody a *live* graph they must have
 * access to open, and this hands them a picture. The audience for the picture
 * is the one that cannot open the link — a slide, an incident write-up, a
 * ticket.
 *
 * ---
 *
 * **Drawn from the same geometry the screen uses**, imported rather than
 * restated: `nodeX`, `nodeY`, `NODE_W` and `NODE_H` are `lib/pipeline-graph`'s,
 * and an export that laid the cards out with its own arithmetic would be a
 * second picture of the same graph — the §191 hazard this repository keeps
 * finding, and one where nothing on the screen would say which copy was wrong.
 *
 * **Colours are written out, not left as `var(--…)`.** A `var()` in a
 * standalone SVG resolves against nothing, so every stroke would fall back to
 * black and the colouring §419 built would export as a flat drawing.
 *
 * The palette is read **off the live document** rather than hardcoded, which
 * is the difference between exporting the page somebody is looking at and
 * exporting the page this module was written against: `[data-scheme="dark"]`
 * redefines six of these tokens, and a graph inside one exports with the dark
 * values because they are the ones the document resolves. The constants below
 * are the fallback for when there is no document to ask — every unit test,
 * and any render outside a browser — and `graph-svg.test.ts` reads
 * `globals.css` and asserts they still say what it says, because a drifted
 * fallback is a wrong colour nobody would ever see in the app.
 *
 * **Text is escaped and never trusted.** A dataset called `<script>` is an
 * ordinary name and an ordinary mistake; an export that pasted it in would
 * produce a file that is no longer an image of anything.
 */

import {
  GAP_X, GAP_Y, NODE_H, NODE_W, PAD, nodeX, nodeY,
} from "./pipeline-graph";

/** What this module needs of a node — the graph's shape, narrowed. */
export interface DrawableNode {
  id: string;
  kind: string;
  name: string;
  layer: number;
  position: number;
}

export interface DrawableEdge {
  from: string;
  to: string;
}

/** The tokens the export resolves, with the light-theme value of each as the
 *  fallback. Named here so a test can state what it expects without repeating
 *  a hex string that `globals.css` owns. */
export const FALLBACK: Record<string, string> = {
  "--paper": "#fafbfb",
  "--panel": "#ffffff",
  "--ink": "#16232f",
  "--ink-soft": "#5a6b7b",
  "--line": "#e2e8ed",
  "--line-strong": "#c3ceD8",
};

/** One token's value in a live document, or its fallback.
 *
 * **Trimmed**, because `getPropertyValue` returns the declaration including
 * the space after the colon, and ` #fff` is not a colour an SVG renderer
 * accepts. */
export function tokenValue(token: string, styles?: CSSStyleDeclaration): string {
  const live = styles?.getPropertyValue(token)?.trim();
  return live ? live : FALLBACK[token] ?? "#000000";
}

/** Every `var(--x)` in a value, replaced by what `--x` resolves to.
 *
 * A swatch's token is `var(--accent)` and an SVG has no idea what that is;
 * this is the one translation between the page's palette and a file that has
 * to stand on its own. A token nothing declares resolves through `FALLBACK`,
 * and one that is not in there either comes back black rather than left as
 * `var(...)` — a visible wrong colour beats an attribute the renderer drops. */
export function resolved(value: string, styles?: CSSStyleDeclaration): string {
  return value.replace(/var\((--[a-z0-9-]+)\)/gi, (_, token: string) =>
    tokenValue(token, styles));
}

/** Text that cannot close the element it sits in. */
export function escaped(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** A label cut to what fits a card, with an ellipsis when it was cut.
 *
 * SVG has no text wrapping and no overflow, so a long name would run across
 * its neighbours and off the page. **Measured in characters rather than
 * pixels**, which is an approximation and is said so here: the alternative is
 * a canvas measurement, and an export that needed a canvas could not be a pure
 * function with unit tests. */
export function clipped(text: string, limit: number): string {
  if (limit <= 0) return "";
  if (text.length <= limit) return text;
  if (limit === 1) return "…";
  return `${text.slice(0, limit - 1)}…`;
}

export interface SvgOptions {
  /** What each node's left bar says, by node id — §419's `swatchFor` applied
   *  by the caller, so the picture carries whatever reading was on screen
   *  rather than a second rule about colour. */
  colours?: Record<string, string>;
  /** Node ids drawn as selected. The export is of the graph *as it looked*,
   *  and a selection is part of how it looked. */
  selected?: readonly string[];
  /** The live document's computed style, for resolving `var(--…)`. Absent in
   *  a unit test, which is what `FALLBACK` is for. */
  styles?: CSSStyleDeclaration;
  /** Put in the picture's `<title>`, which is what a screen reader announces
   *  and what most viewers show as the file's name. */
  title?: string;
}

/** A cubic bezier from one node's right edge to the next node's left edge —
 *  the same curve the component draws, for the same reason the geometry is
 *  shared. */
function edgePath(from: DrawableNode, to: DrawableNode): string {
  const x1 = nodeX(from.layer) + NODE_W;
  const y1 = nodeY(from.position) + NODE_H / 2;
  const x2 = nodeX(to.layer);
  const y2 = nodeY(to.position) + NODE_H / 2;
  const bend = Math.max(30, (x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
}

/** The graph as a standalone SVG document.
 *
 * **An empty graph still produces a document**, with a minimum size rather
 * than a zero-by-zero canvas: a file no viewer will open is a worse answer
 * than a picture of an empty project, and "the export is broken" is what a
 * reader would conclude from the first (§214).
 */
export function svgFor(
  nodes: readonly DrawableNode[],
  edges: readonly DrawableEdge[],
  options: SvgOptions = {},
): string {
  const { colours = {}, selected = [], styles, title = "Lineage graph" } = options;
  const chosen = new Set(selected);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const colour = (token: string) => resolved(token, styles);

  const layers = Math.max(1, ...nodes.map((n) => n.layer + 1));
  const rows = Math.max(1, ...nodes.map((n) => n.position + 1));
  const width = Math.max(PAD + layers * (NODE_W + GAP_X), 400);
  const height = PAD * 2 + rows * (NODE_H + GAP_Y);

  const parts: string[] = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" `
      + `viewBox="0 0 ${width} ${height}" font-family="system-ui, sans-serif">`,
    `<title>${escaped(title)}</title>`,
    `<rect width="${width}" height="${height}" fill="${colour("var(--paper)")}"/>`,
  ];

  for (const edge of edges) {
    const from = byId.get(edge.from);
    const to = byId.get(edge.to);
    // An edge to a node that is not drawn is not drawn either — a line
    // reaching off the picture would read as a node the export lost.
    if (!from || !to) continue;
    parts.push(
      `<path d="${edgePath(from, to)}" fill="none" `
        + `stroke="${colour("var(--line-strong)")}" stroke-width="1.5"/>`,
    );
  }

  for (const node of nodes) {
    const x = nodeX(node.layer);
    const y = nodeY(node.position);
    const bar = colours[node.id];
    parts.push(
      `<g data-node="${escaped(node.id)}">`,
      `<rect x="${x}" y="${y}" width="${NODE_W}" height="${NODE_H}" rx="6" `
        + `fill="${colour("var(--panel)")}" `
        + `stroke="${colour(chosen.has(node.id) ? "var(--ink)" : "var(--line-strong)")}" `
        + `stroke-width="${chosen.has(node.id) ? 2 : 1}"/>`,
    );
    if (bar) {
      parts.push(
        `<rect x="${x}" y="${y}" width="4" height="${NODE_H}" fill="${colour(bar)}"/>`,
      );
    }
    parts.push(
      `<text x="${x + 11}" y="${y + 20}" font-size="10" `
        + `fill="${colour("var(--ink-soft)")}">`
        + `${escaped(node.kind === "object_type" ? "object type"
          : node.kind === "connection" ? "data source" : node.kind)}</text>`,
      `<text x="${x + 11}" y="${y + 38}" font-size="13" `
        + `fill="${colour("var(--ink)")}">${escaped(clipped(node.name, 24))}</text>`,
      "</g>",
    );
  }

  parts.push("</svg>");
  return parts.join("\n");
}

/** A filename somebody will find again, with no characters a filesystem
 *  refuses. The date is the point: an exported picture is a claim about a
 *  moment, and two of them a week apart are otherwise indistinguishable. */
export function svgFilename(project: string, on: Date): string {
  const slug = project.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const day = on.toISOString().slice(0, 10);
  return `${slug || "lineage"}-${day}.svg`;
}
