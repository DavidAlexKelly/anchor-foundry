/**
 * p.319-320's inline references on the Markdown widget (§632; `workshop`
 * p.316, p.319-320).
 *
 * > "Inline reference: If enabled, allows references to Ontology objects and
 * > on-click Workshop events to be embedded in the text." (p.316)
 * >
 * > "Object types: Required for using object references. Builder should select
 * > all object types which will be referenced within the Markdown widget …
 * > If an object type is referenced in the Markdown widget but not configured
 * > in this list, the object reference will not appear in the Markdown
 * > widget." (p.320)
 *
 * The syntax is `markdown.ts`'s; what an anchor looks like and when it is lit
 * is here, beside nothing React, so it is tested without a browser.
 */

import type { ConditionalRule } from "@/lib/types";
import { conditionalStyle } from "../../lib/conditional-format";
import type { Block, Inline } from "./markdown";
import { rulesOf } from "./conditional-formats";

/** p.320's Highlight color (§664): "Select a static color, inherit colors
 * from a property with Ontology formatting, or define custom rules to
 * determine color." */
export const COLOR_MODES = {
  static: "Static colour",
  property: "From a property's formatting",
  rules: "Custom rules",
} as const;
export type ColorMode = keyof typeof COLOR_MODES;

export interface ReferenceType {
  /** The object type's api_name, as p.319's `objectType="…"` names it. */
  objectType: string;
  /** p.320's Highlight color, a static one; null for the platform's accent.
   * Also what a property's or the rules' colour falls back to. */
  color: string | null;
  colorMode: ColorMode;
  /** The property whose Ontology conditional formatting colours the anchor. */
  colorProperty: string | null;
  /** The builder's own rules, §158's grammar, over the object's properties. */
  colorRules: ConditionalRule[] | null;
}

/** The configured types, read defensively: a saved document is data. */
export function referenceTypesOf(raw: unknown): ReferenceType[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: ReferenceType[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) continue;
    const e = entry as Record<string, unknown>;
    const objectType = typeof e.objectType === "string" ? e.objectType.trim() : "";
    if (!objectType || seen.has(objectType)) continue;
    seen.add(objectType);
    const color = typeof e.color === "string" && /^#[0-9a-fA-F]{6}$/.test(e.color)
      ? e.color : null;
    const colorMode: ColorMode = e.colorMode === "property" || e.colorMode === "rules" ? e.colorMode : "static";
    const colorProperty = typeof e.colorProperty === "string" && e.colorProperty.trim()
      ? e.colorProperty.trim() : null;
    out.push({ objectType, color, colorMode, colorProperty, colorRules: rulesOf(e.colorRules) });
  }
  return out;
}

/** p.320's Selection behavior. */
export const SELECTION_BEHAVIORS = {
  none: "No highlight",
  last: "Highlight last selected",
  selected: "Highlight selected reference",
} as const;
export type SelectionBehavior = keyof typeof SELECTION_BEHAVIORS;

export function selectionBehaviorOf(raw: unknown): SelectionBehavior {
  return raw === "none" || raw === "selected" ? raw : "last";
}

/**
 * Whether an anchor is drawn lit, by p.320's three behaviours:
 * - No highlight: "selecting an object reference … will not result in a
 *   selection state";
 * - Highlight last selected: "the most recently selected anchor text", which
 *   is this anchor and not every anchor naming the same object;
 * - Highlight selected reference: "based on the contents of the selected
 *   object set", so every anchor naming an object in it.
 */
export function isLit(
  behavior: SelectionBehavior,
  anchor: { index: number; primaryKey: string },
  last: number | null,
  selectedKeys: readonly string[],
): boolean {
  if (behavior === "none") return false;
  if (behavior === "last") return last === anchor.index;
  return selectedKeys.includes(anchor.primaryKey);
}

/**
 * Number every anchor in reading order, in place, and say how many there are.
 * "The most recently selected anchor text" (p.320) is one anchor, and two
 * anchors naming the same object are two places a reader could have clicked.
 */
export function numberReferences(blocks: Block[]): number {
  let next = 0;
  eachReference(blocks, (node) => {
    node.index = next;
    next += 1;
  });
  return next;
}

type Reference = Extract<Inline, { kind: "objectref" }>;

/** Every anchor, in reading order. */
function eachReference(blocks: Block[], visit: (node: Reference) => void): void {
  const inline = (nodes: Inline[]) => {
    for (const node of nodes) {
      if (node.kind === "objectref") visit(node);
      if ("children" in node) inline(node.children);
    }
  };
  const block = (b: Block) => {
    switch (b.kind) {
      case "heading": case "paragraph": inline(b.children); break;
      case "quote": b.blocks.forEach(block); break;
      case "list": b.items.forEach((item) => inline(item.children)); break;
      case "table":
        b.head.forEach(inline);
        b.rows.forEach((row) => row.forEach(inline));
        break;
      default: break;
    }
  };
  blocks.forEach(block);
}

/** The keys each type's anchors name, once each, for the types whose colour
 * is read from their objects (§664): a static colour needs none of them. */
export function keysToColor(blocks: Block[], types: readonly ReferenceType[]): Map<string, string[]> {
  const read = new Set(types.filter((t) => t.colorMode !== "static").map((t) => t.objectType));
  const out = new Map<string, string[]>();
  eachReference(blocks, (node) => {
    if (!read.has(node.objectType)) return;
    const keys = out.get(node.objectType) ?? [];
    if (!keys.includes(node.primaryKey)) keys.push(node.primaryKey);
    out.set(node.objectType, keys);
  });
  return out;
}

/** An anchor's colour: the static one, or the colour its object's properties
 * are painted by a property's Ontology rules or the builder's, the fill before
 * the text's; the static colour when nothing paints it or the object is not
 * read yet. */
export function referenceColorOf(
  type: ReferenceType, properties: Record<string, unknown> | undefined,
  propertyRules: ConditionalRule[] | null | undefined,
): string | null {
  if (type.colorMode === "static" || !properties) return type.color;
  const paint = conditionalStyle(type.colorMode === "property" ? propertyRules : type.colorRules, properties);
  return paint?.background ?? paint?.colour ?? type.color;
}
