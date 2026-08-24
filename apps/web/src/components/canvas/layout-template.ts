/** p.52's layout template picker, and what applying one does to a page.
 *
 * > "You can also explore other layout templates using the layout template
 * > picker at the bottom of the page. You can preview what each layout would
 * > look like by hovering over its icon. If you would like to use a template,
 * > you can select that icon; the page layout will update to the one you
 * > selected." (p.52-53)
 *
 * And the default a new page starts from:
 *
 * > "The below screenshot showcases the default, unconfigured page that is
 * > initialized with two vertically divided sections beneath the module-wide
 * > header" (p.52)
 *
 * ---
 *
 * **The design question p.53 does not answer: what happens to the widgets
 * already on the page.** "The page layout will update" is a sentence about
 * layout, and the picker is described on a page that was created moments ago,
 * so the intended use is plainly a starting point. But the control is always
 * there, and a builder will click it on a page they have spent an hour on.
 *
 * Deleting their widgets to honour a one-click control is the failure this
 * repo spends most of its time removing, so applying a template **never loses
 * a widget**. The sections are replaced; their *contents* are carried into the
 * new sections positionally — old section 1's widgets into new section 1, and
 * so on — with anything past the new template's count landing in the last
 * section rather than nowhere. A widget sitting directly on the page, with no
 * section around it, goes into the first.
 *
 * That rule does the obvious thing in the two cases that matter: an empty page
 * gets the template and nothing else happens, and a page whose section count
 * matches the template keeps every widget exactly where it was. The case it
 * handles rather than solves — narrowing three sections to two — piles the
 * surplus into the last section, which is visible, undoable, and not a
 * deletion.
 *
 * **Why a pure module over the serialised node map.** The same argument
 * `clipboard.ts` makes, and it applies harder here: the layout *is* the
 * serialised map (decision 0002), so transforming the map and handing it to
 * `actions.deserialize` is one code path rather than two — and "applying a
 * template quietly dropped a widget" is invisible until somebody goes looking
 * for the widget.
 *
 * ---
 *
 * **Divergence: the icons are not Foundry's.** p.52 shows a row of glyphs we
 * cannot reproduce and does not name the templates behind them. The set below
 * is ours, chosen to span what a `CanvasSection` can actually express — a
 * count of sections, and each one's direction and weights — and each is
 * previewed by drawing its own shape rather than by shipping an image, so the
 * preview cannot drift from what the template does.
 */
import type { LayoutNodes } from "../../lib/workshop-module";

/** One serialised Craft node, in the shape the layout stores. Kept structural
 * and local for the reason `clipboard.ts` keeps its copy: this module reads a
 * document that can arrive from anywhere. */
interface LayoutNode {
  type?: { resolvedName?: string } | string;
  isCanvas?: boolean;
  props?: Record<string, unknown>;
  parent?: string | null;
  nodes?: string[];
  linkedNodes?: Record<string, string>;
  custom?: Record<string, unknown>;
}

/** One section a template lays down.
 *
 * `direction` and `weights` are `CanvasSection`'s own props, not a parallel
 * vocabulary — a template is a *starting configuration* of sections, so
 * anything it can set is something the author can then change by hand in the
 * settings panel, and anything it cannot set is a section prop that does not
 * exist.
 */
export interface TemplateSection {
  direction: "columns" | "rows" | "flow" | "toolbar";
  /** `CanvasSection`'s comma-separated relative widths. Empty means equal. */
  weights?: string;
  /** Seeds the section's title so a fresh page names its own regions. */
  title?: string;
}

export interface LayoutTemplate {
  key: string;
  label: string;
  /** What the picker says on hover, beside the drawn preview. */
  hint: string;
  sections: readonly TemplateSection[];
}

/** p.52's default for a new page: "two vertically divided sections".
 *
 * Read as two sections stacked one above the other — the division runs across
 * the page, dividing it vertically. **The other reading is defensible**: "a
 * vertical divider", meaning side by side. It is written down because the
 * screenshot that would settle it is an image, and because the two produce
 * visibly different new pages. Stacked wins on the tiebreak that a page lays
 * its children out in a column, so this is the arrangement a page expresses
 * directly rather than through a wrapper section that exists only to hold two
 * others.
 */
export const DEFAULT_TEMPLATE = "two-rows";

export const TEMPLATES: readonly LayoutTemplate[] = [
  {
    key: "two-rows",
    label: "Two sections",
    hint: "p.52's default for a new page: two sections, one above the other",
    sections: [{ direction: "columns" }, { direction: "columns" }],
  },
  {
    key: "single",
    label: "One section",
    hint: "a single section filling the page",
    sections: [{ direction: "columns" }],
  },
  {
    key: "three-rows",
    label: "Three sections",
    hint: "three sections stacked",
    sections: [{ direction: "columns" }, { direction: "columns" }, { direction: "columns" }],
  },
  {
    key: "sidebar",
    label: "Sidebar and body",
    hint: "one section laying its widgets out as a narrow column beside a wide one",
    sections: [{ direction: "columns", weights: "1,3" }],
  },
  {
    key: "toolbar-and-body",
    label: "Toolbar over a body",
    hint: "a toolbar strip over a section — p.54's Toolbar, for buttons and metric cards",
    sections: [
      { direction: "toolbar", title: "Toolbar" },
      { direction: "columns" },
    ],
  },
  {
    key: "stacked-rows",
    label: "Stacked widgets",
    hint: "one section stacking its widgets vertically — p.54's Rows",
    sections: [{ direction: "rows" }],
  },
];

export function templateFor(key: string): LayoutTemplate | undefined {
  return TEMPLATES.find((t) => t.key === key);
}

function nodeAt(layout: LayoutNodes, id: string): LayoutNode | null {
  const node = layout[id];
  return node && typeof node === "object" ? (node as LayoutNode) : null;
}

function childrenOf(node: LayoutNode): string[] {
  const direct = Array.isArray(node.nodes) ? node.nodes : [];
  const linked = node.linkedNodes ? Object.values(node.linkedNodes) : [];
  return [...direct, ...linked].filter((id): id is string => typeof id === "string");
}

function resolvedName(node: LayoutNode): string {
  const t = node.type;
  return typeof t === "string" ? t : (t?.resolvedName ?? "");
}

/** The widgets a page holds, grouped the way its current sections group them.
 *
 * One group per existing section, in document order, plus — as the **first**
 * group — any widget sitting directly on the page with no section around it.
 * That ordering is deliberate: a bare widget is above the sections it is
 * mixed in with far more often than below, and putting it first keeps it at
 * the top of the page it was already at the top of.
 *
 * Exported because it is the whole of what "carried across" means, and a rule
 * about not losing widgets deserves to be checkable on its own rather than
 * only through the transform that uses it.
 */
export function pageGroups(layout: LayoutNodes, pageId: string): string[][] {
  const page = nodeAt(layout, pageId);
  if (!page) return [];
  const loose: string[] = [];
  const groups: string[][] = [];
  for (const childId of childrenOf(page)) {
    const child = nodeAt(layout, childId);
    if (!child) continue;
    if (resolvedName(child) === "CanvasSection") {
      groups.push(childrenOf(child));
    } else {
      loose.push(childId);
    }
  }
  return loose.length > 0 ? [loose, ...groups] : groups;
}

/** Spread `groups` across `count` sections, keeping order and losing nothing.
 *
 * Group *i* goes to section *i* while there is one; everything past the last
 * section joins it. Fewer groups than sections leaves the extra sections
 * empty, which is what a template promising three regions should look like
 * even if only two had anything in them.
 */
export function distribute(groups: readonly string[][], count: number): string[][] {
  const out: string[][] = Array.from({ length: Math.max(count, 0) }, () => []);
  if (out.length === 0) return out;
  groups.forEach((group, i) => {
    const target = Math.min(i, out.length - 1);
    out[target]!.push(...group);
  });
  return out;
}

export interface ApplyResult {
  layout: LayoutNodes;
  /** The ids of the sections the template laid down, in order. Returned rather
   * than left to be re-derived: the caller selects the first one so the author
   * lands somewhere useful, and re-finding it by walking the result would be a
   * second implementation of this function's own ordering. */
  sections: string[];
}

/** Replace `pageId`'s sections with `template`'s, carrying every widget across.
 *
 * `mintId` supplies fresh node ids — passed in rather than generated here so
 * the transform is deterministic under test, the same arrangement `paste`
 * uses.
 *
 * The old section nodes are dropped and new ones minted rather than edited in
 * place. Editing would have kept ids stable and looked tidier, and it is
 * wrong: a section carries `collapsible`, `visibleWhen`, `tabs`, a backing
 * variable and a style block, and a template that silently kept a *previous*
 * template's collapse rule would be a layout that does not match its own
 * picture. A template lays down sections as it describes them; anything else
 * is a section the author configured, and it is gone with the section.
 */
export function applyTemplate(
  layout: LayoutNodes,
  pageId: string,
  template: LayoutTemplate,
  mintId: () => string,
): ApplyResult {
  const page = nodeAt(layout, pageId);
  if (!page) return { layout, sections: [] };

  const groups = pageGroups(layout, pageId);
  const spread = distribute(groups, template.sections.length);

  // Every old section on this page disappears; its contents do not. Collected
  // before anything is written so the drop is one set lookup rather than a
  // walk repeated per node.
  const oldSections = new Set(
    childrenOf(page).filter((id) => {
      const child = nodeAt(layout, id);
      return !!child && resolvedName(child) === "CanvasSection";
    }),
  );

  const sectionIds = template.sections.map(() => mintId());
  const out: LayoutNodes = {};
  for (const [id, node] of Object.entries(layout)) {
    if (oldSections.has(id)) continue;
    out[id] = node;
  }

  template.sections.forEach((spec, i) => {
    const id = sectionIds[i]!;
    out[id] = {
      type: { resolvedName: "CanvasSection" },
      isCanvas: true,
      props: {
        direction: spec.direction,
        ...(spec.weights ? { weights: spec.weights } : {}),
        ...(spec.title ? { title: spec.title } : {}),
      },
      parent: pageId,
      nodes: [...spread[i]!],
      linkedNodes: {},
    } as LayoutNodes[string];
  });

  // The page now lists exactly the template's sections. Anything that was a
  // direct child and is not a section has been rehomed into one of them, so
  // leaving it in this list as well would have it drawn twice.
  out[pageId] = { ...page, nodes: sectionIds, linkedNodes: {} } as LayoutNodes[string];

  // Every carried widget's `parent` has to follow it, or the document says one
  // thing about where a widget lives and its new parent says another - and
  // Craft believes the parent pointer.
  spread.forEach((ids, i) => {
    for (const id of ids) {
      const node = nodeAt(out, id);
      if (node) out[id] = { ...node, parent: sectionIds[i]! } as LayoutNodes[string];
    }
  });

  return { layout: out, sections: sectionIds };
}
