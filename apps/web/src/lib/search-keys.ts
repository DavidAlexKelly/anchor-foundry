/** The ontology search, from the keyboard (§515; `ontology-manager` p.28).
 *
 * > "You can use the up-arrow and down-arrow keys on your keyboard to move
 * > through search results and see previews for the selected results. You can
 * > select Open or use the Enter key to open the selected result." (p.28)
 *
 * Pure, and in `lib/`, because vitest cannot parse `.tsx`.
 */
import type { OntologySearchHit } from "./types";
import { KIND_LABELS } from "./search-destination";

/** The selected result after a key, clamped to the list: the arrows stop at
 * the ends rather than wrapping, and a list that shrank under the selection
 * keeps the last row selected rather than none. */
export function nextIndex(current: number, count: number, key: string): number {
  if (count === 0) return 0;
  if (key === "ArrowDown") return Math.min(count - 1, current + 1);
  if (key === "ArrowUp") return Math.max(0, current - 1);
  return Math.min(current, count - 1);
}

/** p.28's preview of the selected result: what it is, its names, why it
 * matched, and where it lives or how widely it is used. */
export function previewRows(hit: OntologySearchHit): [string, string][] {
  const rows: [string, string][] = [
    ["Kind", KIND_LABELS[hit.kind]],
    ["Name", hit.display_name || hit.api_name],
    ["API name", hit.api_name],
    ["Matched", `${hit.matched_field}: ${hit.matched_value}`],
  ];
  if (hit.object_type_id) rows.push(["On", hit.object_type_name]);
  // A function's count is its versions, not its users (§777).
  if (hit.usage_count !== null) {
    rows.push([hit.kind === "function" ? "Versions" : "Used by", String(hit.usage_count)]);
  }
  return rows;
}
