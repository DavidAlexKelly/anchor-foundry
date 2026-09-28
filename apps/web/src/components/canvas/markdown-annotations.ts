/**
 * p.321-322's annotations on the Markdown widget (§637).
 *
 * > "Annotation objects capture selected text using zero-indexed numeric
 * > indices, with an inclusive start index and an exclusive end index, to
 * > represent the text selection's start and end positions. Markdown widget
 * > annotations currently do not support negative indices." (p.321)
 *
 * The indices are into the widget's Markdown source, as §636's selection
 * outputs write them, so a selection written into an annotation object is the
 * annotation drawn back over the same words. Each rendered run knows its
 * source offset, and a run is split where an annotation starts or ends.
 */

import type { ConditionalRule } from "@/lib/types";
import { conditionalStyle } from "../../lib/conditional-format";
import { itemsOf, type ButtonItem } from "./button-items";
import { rulesOf } from "./conditional-formats";

/** p.322's Highlight color (§669): "A custom color may be statically defined
 * or conditional formatting rules may be set." Only those two - p.320's third
 * way for a reference, a property's own formatting, is not offered here. */
export const ANNOTATION_COLOR_MODES = {
  static: "Static colour",
  rules: "Conditional formatting rules",
} as const;
export type AnnotationColorMode = keyof typeof ANNOTATION_COLOR_MODES;

export interface AnnotationLayer {
  /** p.321's Name, for the configuration panel. */
  name: string;
  /** p.321's Annotation object set. */
  objectSetVariable: string | null;
  /** p.321's Start index and End index: numeric properties of those objects. */
  startProperty: string;
  endProperty: string;
  /** p.322's Highlight color, a static one; null for the accent. Also what
   * the rules fall back to where none paints an annotation. */
  color: string | null;
  colorMode: AnnotationColorMode;
  /** §158's rules over the annotation object's properties (§669). */
  colorRules: ConditionalRule[] | null;
}

export function annotationLayersOf(raw: unknown): AnnotationLayer[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    if (typeof entry !== "object" || entry === null) return [];
    const e = entry as Record<string, unknown>;
    const text = (v: unknown) => (typeof v === "string" ? v.trim() : "");
    return [{
      name: text(e.name),
      objectSetVariable: text(e.objectSetVariable) || null,
      startProperty: text(e.startProperty),
      endProperty: text(e.endProperty),
      color: typeof e.color === "string" && /^#[0-9a-fA-F]{6}$/.test(e.color) ? e.color : null,
      colorMode: e.colorMode === "rules" ? "rules" : "static",
      colorRules: rulesOf(e.colorRules),
    }];
  });
}

/** p.322's Annotation formatting. */
export const ANNOTATION_FORMATS = {
  highlight: "Highlight",
  underline: "Underline",
  dashed: "Dashed underline",
  both: "Highlight and underline",
} as const;
export type AnnotationFormat = keyof typeof ANNOTATION_FORMATS;

export function annotationFormatOf(raw: unknown): AnnotationFormat {
  return raw === "underline" || raw === "dashed" || raw === "both" ? raw : "highlight";
}

export interface Annotation {
  /** The annotation object's primary key. */
  key: string;
  layer: number;
  start: number;
  end: number;
  properties: Record<string, unknown>;
}

const index = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() ? Number(v) : NaN;
  return Number.isInteger(n) && n >= 0 ? n : null;
};

/**
 * A layer's objects as annotations. An object whose indices are missing, not
 * whole, negative ("do not support negative indices"), or not a range - an
 * end at or before its start - is not drawn, and is counted so the widget
 * can say so rather than dropping it without a word.
 */
export function annotationsOf(
  layer: number,
  spec: AnnotationLayer,
  objects: readonly { primary_key: string; properties: Record<string, unknown> }[],
): { annotations: Annotation[]; unreadable: number } {
  const annotations: Annotation[] = [];
  let unreadable = 0;
  for (const object of objects) {
    const start = index(object.properties[spec.startProperty]);
    const end = index(object.properties[spec.endProperty]);
    if (start === null || end === null || end <= start) {
      unreadable += 1;
      continue;
    }
    annotations.push({ key: object.primary_key, layer, start, end, properties: object.properties });
  }
  return { annotations, unreadable };
}

/** A run of text split where annotations start and end: each piece with its
 * own offset and the annotations covering it, in the order given. */
export function segmentsOf(
  text: string,
  at: number,
  annotations: readonly Annotation[],
): { text: string; at: number; covering: Annotation[] }[] {
  const end = at + text.length;
  const cuts = new Set<number>([at, end]);
  // Each annotation's edges, held to the run: an edge outside it lands on
  // the run's own start or end, which are cuts already.
  const within = (edge: number) => Math.min(end, Math.max(at, edge));
  for (const a of annotations) {
    cuts.add(within(a.start));
    cuts.add(within(a.end));
  }
  const points = [...cuts].sort((x, y) => x - y);
  return points.slice(0, -1).map((from, n) => {
    const to = points[n + 1]!;
    return {
      text: text.slice(from - at, to - at),
      at: from,
      // Every edge inside the run is a cut, so an annotation covering a
      // piece's first character covers all of it.
      covering: annotations.filter((a) => a.start <= from && a.end > from),
    };
  });
}

/** An annotation's tooltip: p.322's "Properties to display in tooltip", one
 * `name: value` per line, the properties it has. */
export function tooltipOf(annotation: Annotation, properties: readonly string[]): string {
  return properties
    .filter((p) => annotation.properties[p] !== undefined && annotation.properties[p] !== null)
    .map((p) => `${p}: ${String(annotation.properties[p])}`)
    .join("\n");
}

/** An annotation's colour: its layer's static one, or what the layer's rules
 * paint its object's properties, the fill before the text's; the static
 * colour where no rule matches. */
export function annotationColorOf(layer: AnnotationLayer, annotation: Annotation): string | null {
  if (layer.colorMode === "static") return layer.color;
  const paint = conditionalStyle(layer.colorRules, annotation.properties);
  return paint?.background ?? paint?.colour ?? layer.color;
}

/**
 * p.322's On hover interactions (§669): "Configure on-hover interactions such
 * as actions and events, which will be displayed in the on-hover tooltip of
 * an annotation object." Each is a click the Events panel wires, as a
 * highlighted-text action is (§638), and the ids are `hover_N` so the two lists,
 * both the widget's clicks, never name the same item.
 */
export function hoverActionsOf(raw: unknown): ButtonItem[] {
  return itemsOf(raw).filter((i) => /^hover_\d+$/.test(i.id));
}

export function addHoverAction(items: readonly ButtonItem[]): ButtonItem[] {
  const taken = new Set(items.map((i) => i.id));
  let n = items.length + 1;
  while (taken.has(`hover_${n}`)) n += 1;
  return [...items, { id: `hover_${n}`, label: `Interaction ${items.length + 1}` }];
}

/** The widget's clicks as the Events panel lists them: its highlighted-text
 * actions, then its hover interactions, said as such. */
export function markdownClickItems(highlight: unknown, hover: unknown): ButtonItem[] {
  return [
    ...itemsOf(highlight),
    ...hoverActionsOf(hover).map((i) => ({ id: i.id, label: `On hover: ${i.label || "Interaction"}` })),
  ];
}
