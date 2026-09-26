/** "The size of the table" (§509; `dataset-preview` p.3).
 *
 * > "About: Information including … the size of the table …" (p.3)
 *
 * The Details tab already said how many rows. This adds the other two
 * measures a reader means by size: how many columns, and how much storage the
 * current version takes. The bytes come from the version list, which already
 * measures every version for the History tab.
 */
import { bytesText } from "./bytes";
import type { DatasetVersion } from "./types";

/** The current version's size, or the reason there is none.
 *
 * Three states, said differently. The versions not loaded yet is
 * `undefined`, and shows the columns alone rather than a guess. A version
 * whose file is missing is `null`, and says so, because "it cannot be
 * measured" and "it is empty" send a reader to different places. */
export function sizeText(columns: number, bytes: number | null | undefined): string {
  const cols = `${columns} column${columns === 1 ? "" : "s"}`;
  if (bytes === undefined) return cols;
  if (bytes === null) return `${cols} · not measured: its file is not in storage`;
  return `${cols} · ${bytesText(bytes)} in storage`;
}

/** The current version's bytes out of the version list, `undefined` while it
 * is not in the list (not loaded, or the list is out of date). */
export function currentBytes(
  versions: Pick<DatasetVersion, "version_number" | "size_bytes">[] | undefined,
  current: number,
): number | null | undefined {
  const row = versions?.find((v) => v.version_number === current);
  return row ? (row.size_bytes ?? null) : undefined;
}
