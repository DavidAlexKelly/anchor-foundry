/**
 * p.64's widget selector, grouped (§447; `workshop` p.64, p.220, p.276,
 * p.444, p.480).
 *
 * > "To add a widget to a module, hover over any empty section to reveal the
 * > **+ Add widget** button, then select it… Then, choose the desired widget
 * > from the **widget selector modal** that opens." (p.64)
 *
 * The button and the Unused widgets tab are §197's; what was left is the
 * grouping, and a flat list of forty is the reason it matters — a builder
 * looking for a way to filter an object set should not have to read past
 * nine charts to find one.
 *
 * **The categories are Foundry's own, and they were already written down.**
 * `docs/parity/workshop.md` lists every widget under the page its category
 * comes from — Filtering (p.444), Core display (p.220), Visualization
 * (p.276), Event-trigger and navigational (p.480) — so this is that mapping
 * made executable rather than a grouping invented here. The layout
 * primitives are §1's rather than a widget category, and they come first
 * because a module with no section has nowhere to put anything else.
 *
 * **Divergence: a panel, not a modal.** p.64 opens a modal because forty
 * entries do not fit beside a canvas; this platform put them in a column that
 * is always there, which is a different answer to the same problem and the
 * one §197's Unused widgets area was already built against. What the modal
 * buys is room, and grouping and a filter buy the same thing without taking
 * the canvas away while somebody chooses. Said here rather than left to be
 * discovered as a missing feature.
 */

export type CategoryId =
  | "layout" | "filtering" | "display" | "visualization" | "events" | "other";

export interface Category {
  id: CategoryId;
  label: string;
  /** Where the grouping comes from, shown so a builder can go and read it. */
  source: string;
}

/** In the order the panel lists them. **Layout first**, because a module with
 *  no section has nowhere to put anything else; **Other last**, because it is
 *  the group that means "not one of Foundry's". */
export const CATEGORIES: readonly Category[] = [
  { id: "layout", label: "Layout", source: "p.46" },
  { id: "filtering", label: "Filtering", source: "p.444" },
  { id: "display", label: "Core display", source: "p.220" },
  { id: "visualization", label: "Visualization", source: "p.276" },
  { id: "events", label: "Events and navigation", source: "p.480" },
  { id: "other", label: "Other", source: "ours" },
];

/**
 * Which category each widget belongs to.
 *
 * **Written out, one line each.** A rule that derived the category from the
 * component's name would be wrong the first time a widget was named for what
 * it shows rather than for what it does — `CanvasMarkdown` is Visualization
 * in p.276 and reads like display, and `CanvasStepper` is Visualization and
 * reads like navigation. The list is the mapping; there is nothing to derive
 * it from but the specification.
 */
export const CATEGORY_OF: Record<string, CategoryId> = {
  CanvasHeader: "layout",
  CanvasPage: "layout",
  CanvasSection: "layout",
  CanvasLoopSection: "layout",
  CanvasOverlay: "layout",
  CanvasContainer: "layout",

  CanvasFilterList: "filtering",
  CanvasFilterPills: "filtering",
  CanvasProminentTerms: "filtering",
  CanvasSearch: "filtering",
  CanvasUserSelect: "filtering",
  CanvasStringSelector: "filtering",
  CanvasObjectDropdown: "filtering",
  CanvasObjectSelector: "filtering",
  CanvasNumericInput: "filtering",
  CanvasTextInput: "filtering",
  CanvasDateTimePicker: "filtering",

  CanvasObjectTable: "display",
  CanvasObjectCards: "display",
  CanvasObjectViewWidget: "display",
  CanvasPropertyList: "display",
  CanvasLinksWidget: "display",
  CanvasObjectSetTitle: "display",
  CanvasText: "display",

  CanvasChart: "visualization",
  CanvasPieChart: "visualization",
  CanvasMetricCard: "visualization",
  CanvasPivotTable: "visualization",
  CanvasMap: "visualization",
  CanvasTimeSeries: "visualization",
  CanvasTimeline: "visualization",
  CanvasStepper: "visualization",
  CanvasMarkdown: "visualization",
  CanvasMediaPreview: "visualization",

  CanvasButton: "events",
  CanvasTabs: "events",
  CanvasActionForm: "events",

  CanvasEmbeddedModule: "other",
  CanvasDatasetTable: "other",
};

/** Just enough of a palette entry to group and filter one. */
export interface Entry {
  key: string;
  label: string;
  hint: string;
}

/**
 * The widgets a query keeps.
 *
 * **Label and hint both**, which is what makes the filter worth having: the
 * hints are where the words somebody actually thinks of live — "dataset"
 * finds the Dataset table *and* the Chart, because the Chart's hint says it
 * is over a dataset. Substring and case-insensitive, like `narrow` in
 * `graph-inspector.ts` and unlike §428's palette, which is a subsequence
 * because three letters are what somebody types into a command palette.
 */
export function matching(entries: readonly Entry[], query: string): Entry[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...entries];
  return entries.filter(
    (e) => e.label.toLowerCase().includes(q) || e.hint.toLowerCase().includes(q),
  );
}

/**
 * The palette, in groups, in `CATEGORIES` order.
 *
 * **An empty group is dropped rather than shown empty**, which is what makes
 * the filter readable: a search for "chart" that left five headings with
 * nothing under them would be a list of headings.
 *
 * **A widget with no category lands in Other rather than vanishing.** This is
 * a browser reading a list another module owns, and the alternative to a
 * fallback is a widget that exists and cannot be added — which is the failure
 * nobody would notice until somebody went looking for it. `widget-palette
 * .test.ts` asserts the two lists agree, so the fallback is a safety net and
 * not the plan.
 */
export function grouped(
  entries: readonly Entry[],
): { category: Category; items: Entry[] }[] {
  return CATEGORIES.map((category) => ({
    category,
    items: entries.filter((e) => (CATEGORY_OF[e.key] ?? "other") === category.id),
  })).filter((group) => group.items.length > 0);
}

/** What the panel says when a query matches nothing. **It names the query**,
 *  for `emptyNote`'s reason in `command-palette.ts`: a typo somebody can see
 *  beats a panel that might be broken. */
export function emptyNote(query: string): string {
  return `No widget matches “${query.trim()}”`;
}
