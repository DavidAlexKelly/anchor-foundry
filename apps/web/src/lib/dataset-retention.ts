/** How a dataset's retention policy reads on its History tab (§966; db 0170,
 * 0171; docs/decisions/0005-dataset-retention.md). */
import type { DatasetRetention } from "./types";
import { bytesText } from "./bytes";

/** Version numbers as the shortest true list: runs become ranges. */
export function versionsText(numbers: number[]): string {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b);
  const parts: string[] = [];
  let start = sorted[0];
  let end = start;
  for (const n of sorted.slice(1).concat([NaN])) {
    if (start === undefined || end === undefined) break;
    if (n === end + 1) {
      end = n;
      continue;
    }
    parts.push(start === end ? `v${start}` : end === start + 1 ? `v${start}, v${end}` : `v${start}–v${end}`);
    start = n;
    end = n;
  }
  return parts.join(", ");
}

function plural(n: number, one: string, many: string): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** What keeping the versions costs, and what the policy is. */
export function retentionText(r: DatasetRetention): string {
  const cost = `Keeping ${plural(r.versions - (r.expired ?? 0), "version", "versions")} of this dataset costs ${bytesText(r.total_bytes)}.`;
  const policy =
    r.keep_versions == null
      ? " Every version is kept: nothing is removed unless a retention policy says so."
      : ` The newest ${plural(r.keep_versions, "version is", "versions are")} kept, and each night older versions' data is removed — never the current version, one an export still needs, or one another version reads. Their records stay.`;
  const removed = r.expired
    ? ` ${plural(r.expired, "version's", "versions'")} data has been removed already.`
    : "";
  const missing = r.unmeasured
    ? ` ${plural(r.unmeasured, "version is", "versions are")} no longer in storage and not counted here.`
    : "";
  return cost + policy + removed + missing;
}

/** What the saved policy will remove at the next sweep, or "". */
export function tonightText(r: DatasetRetention): string {
  const going = r.would_expire ?? [];
  if (r.keep_versions == null || going.length === 0) return "";
  return `Tonight ${versionsText(going)} (${bytesText(r.would_free_bytes ?? 0)}) will be removed.`;
}

/** What a policy being typed would remove, said before it is saved. */
export function previewText(r: DatasetRetention, keep: number): string {
  const going = r.would_expire ?? [];
  if (going.length === 0) {
    return `Keeping the newest ${plural(keep, "version", "versions")} would remove nothing now.`;
  }
  return `Keeping the newest ${plural(keep, "version", "versions")} would remove ${versionsText(going)} (${bytesText(r.would_free_bytes ?? 0)}), tonight.`;
}

/** The number typed into "Keep the newest", or null when it is not one. */
export function parseKeep(input: string): number | null {
  const text = input.trim();
  if (!/^[0-9]+$/.test(text)) return null;
  const n = Number(text);
  return n >= 1 && n <= 1_000_000 ? n : null;
}

/** A version whose data a policy removed: why it cannot be read, or "". */
export function whyExpired(version: { expired_at?: string | null }): string {
  return version.expired_at ? "this version's data was removed by the retention policy" : "";
}
