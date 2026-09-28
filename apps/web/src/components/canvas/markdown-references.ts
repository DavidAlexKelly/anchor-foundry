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

import type { Block, Inline } from "./markdown";

export interface ReferenceType {
  /** The object type's api_name, as p.319's `objectType="…"` names it. */
  objectType: string;
  /** p.320's Highlight color, a static one; null for the platform's accent. */
  color: string | null;
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
    out.push({ objectType, color });
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
  const inline = (nodes: Inline[]) => {
    for (const node of nodes) {
      if (node.kind === "objectref") {
        node.index = next;
        next += 1;
      }
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
  return next;
}
