/**
 * p.8's histogram helper, over a selection on the lineage graph (§531;
 * `data-lineage` p.8).
 *
 * > "When you select multiple nodes on the graph, you will see the histogram
 * > helper. The helper displays common properties and their values alongside
 * > the number of appearances of each value on the graph. By clicking on the
 * > values, the matching nodes are highlighted." (p.8)
 *
 * p.54's Frequent Columns (§353) already counts column *names*; this counts
 * the values of the properties every node carries, which is p.8's own
 * feature. A property appears only when some selected node has a value for
 * it, so a selection of datasets is not shown an empty "Language" row.
 */
import type { PipelineNode } from "./types";

export interface HistogramValue {
  value: string;
  count: number;
  /** The node ids with this value, for the highlight and Update selection. */
  ids: string[];
}

export interface HistogramRow {
  property: string;
  label: string;
  values: HistogramValue[];
}

const KIND_WORDS: Record<PipelineNode["kind"], string> = {
  dataset: "dataset", model: "model", object_type: "object type", connection: "data source",
};

/** The properties p.8 counts here, in the order a reader asks about them:
 * what a node is, where it came from, then its state. */
export const HISTOGRAM_PROPERTIES: {
  property: string;
  label: string;
  read: (node: PipelineNode) => string | null;
}[] = [
  { property: "kind", label: "Kind", read: (n) => KIND_WORDS[n.kind] },
  { property: "origin", label: "Origin", read: (n) => n.origin },
  { property: "health_status", label: "Health", read: (n) => n.health_status },
  { property: "language", label: "Language", read: (n) => n.language },
  { property: "trigger_mode", label: "Runs", read: (n) => n.trigger_mode },
  { property: "last_run_status", label: "Last run", read: (n) => n.last_run_status },
  {
    property: "out_of_date",
    label: "Up to date",
    // Only a node that gets built has an answer: a model or an object type
    // is neither up to date nor out of it.
    read: (n) => (n.built_at === null ? null : n.out_of_date ? "out of date" : "up to date"),
  },
];

/** Every property with a value on some selected node, and each value's
 * count, most frequent first and then by value, so the order is stable. */
export function histogram(nodes: readonly PipelineNode[]): HistogramRow[] {
  const rows: HistogramRow[] = [];
  for (const { property, label, read } of HISTOGRAM_PROPERTIES) {
    const byValue = new Map<string, string[]>();
    for (const node of nodes) {
      const value = read(node);
      if (value === null || value === "") continue;
      byValue.set(value, [...(byValue.get(value) ?? []), node.id]);
    }
    if (byValue.size === 0) continue;
    const values = [...byValue.entries()]
      .map(([value, ids]) => ({ value, count: ids.length, ids }))
      .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
    rows.push({ property, label, values });
  }
  return rows;
}

/** p.8's Copy names: "The full names … are copied to the clipboard as a
 * comma-separated list." A resource here is named within its project and
 * has no folder path, so its name is its full name. In selection order. */
export function copiedNames(nodes: readonly Pick<PipelineNode, "name">[]): string {
  return nodes.map((n) => n.name).join(", ");
}

/** Which nodes a chosen value lights, or none when nothing is chosen. */
export function litByValue(
  rows: readonly HistogramRow[], chosen: { property: string; value: string } | null,
): string[] {
  if (chosen === null) return [];
  return rows.find((r) => r.property === chosen.property)
    ?.values.find((v) => v.value === chosen.value)?.ids ?? [];
}
