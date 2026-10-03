/** The file sync form (§751; decision 0021; `data-connection` p.160-164).
 *
 *  p.160 names four ingestion modes and says each is "the low-level settings
 *  required to achieve the desired behavior": a transaction type and whether
 *  Exclude files already synced is on. The form offers the four by name and
 *  writes the two settings, so nobody has to know that a trailing window is a
 *  SNAPSHOT with the exclusion on. The filters p.164 adds beside them are
 *  fields of their own.
 */
import type { FileSyncFilters } from "./types";

export type Transaction = "SNAPSHOT" | "APPEND" | "UPDATE";
export type Ingestion = "batch" | "append" | "update" | "trailing";

/** p.160-162's four, in p.160's order, each with what it does to the dataset. */
export const INGESTIONS: { key: Ingestion; label: string; says: string }[] = [
  { key: "batch", label: "Batch mirror",
    says: "Every run takes every file in the folder, and the dataset is exactly those files." },
  { key: "append", label: "Incremental mirror (APPEND)",
    says: "Every run takes only files it has not taken before, and adds them to the dataset." },
  { key: "update", label: "Incremental mirror with changes (UPDATE)",
    says: "Every run takes new files and files that have changed; a changed file's rows replace its old ones." },
  { key: "trailing", label: "Trailing window",
    says: "Every run takes only new files, and the dataset is just those." },
];

/** The ingestion mode a stored sync is, read back from its two settings. */
export function ingestionOf(
  transaction: Transaction | null | undefined, filters: FileSyncFilters | null | undefined,
): Ingestion {
  const excluded = !!filters?.exclude_synced;
  if (transaction === "APPEND") return "append";
  if (transaction === "UPDATE") return "update";
  return excluded ? "trailing" : "batch";
}

/** What the form's fields say, before they are a request. Strings because
 *  they are inputs; empty is a filter not set. */
export interface FileSyncFields {
  ingestion: Ingestion;
  byModified: boolean;
  bySize: boolean;
  pathMatches: string;
  pathNotMatches: string;
  anyPathMatches: string;
  modifiedAfter: string;
  sizeMin: string;
  sizeMax: string;
  atLeast: string;
  limit: string;
}

export const BLANK_FIELDS: FileSyncFields = {
  ingestion: "batch", byModified: true, bySize: false, pathMatches: "", pathNotMatches: "",
  anyPathMatches: "", modifiedAfter: "", sizeMin: "", sizeMax: "", atLeast: "", limit: "",
};

/** The fields a stored sync's settings fill in. */
export function fieldsOf(
  transaction: Transaction | null | undefined, filters: FileSyncFilters | null | undefined,
): FileSyncFields {
  const f = filters ?? {};
  const ingestion = ingestionOf(transaction, f);
  const text = (n: number | undefined) => (n === undefined ? "" : String(n));
  return {
    ingestion,
    byModified: ingestion === "update" ? !!f.exclude_synced?.by_modified : true,
    // Only an UPDATE stores a size option: the server refuses one elsewhere.
    bySize: !!f.exclude_synced?.by_size,
    pathMatches: f.path_matches ?? "",
    pathNotMatches: f.path_not_matches ?? "",
    anyPathMatches: f.any_path_matches ?? "",
    modifiedAfter: (f.modified_after ?? "").slice(0, 10),
    sizeMin: text(f.size_min),
    sizeMax: text(f.size_max),
    atLeast: text(f.at_least),
    limit: text(f.limit),
  };
}

/** A count a person typed, or a sentence saying why it is not one. */
function count(value: string, name: string, least: number): number | string | undefined {
  const trimmed = value.trim();
  if (trimmed === "") return undefined;
  const n = Number(trimmed);
  if (!Number.isInteger(n) || n < least) return `${name} is a whole number of at least ${least}.`;
  return n;
}

/** The request the fields make, or the first thing wrong with them. The
 *  server checks all of it again; this is so a typo is said beside the field
 *  rather than after a round trip. */
export function payloadOf(fields: FileSyncFields):
  | { ok: true; file_transaction: Transaction; file_filters: FileSyncFilters }
  | { ok: false; problem: string } {
  const filters: FileSyncFilters = {};
  if (fields.ingestion !== "batch") {
    const changes = fields.ingestion === "update";
    if (changes && !fields.byModified && !fields.bySize) {
      return { ok: false, problem: "An UPDATE sync needs a way to see a file change: its modified date, its size, or both." };
    }
    filters.exclude_synced = {
      by_modified: changes && fields.byModified,
      by_size: changes && fields.bySize,
    };
  }
  for (const [key, value] of [
    ["path_matches", fields.pathMatches],
    ["path_not_matches", fields.pathNotMatches],
    ["any_path_matches", fields.anyPathMatches],
  ] as const) {
    if (value.trim()) filters[key] = value.trim();
  }
  if (fields.modifiedAfter.trim()) filters.modified_after = fields.modifiedAfter.trim();
  for (const [key, value, name, least] of [
    ["size_min", fields.sizeMin, "The smallest size", 0],
    ["size_max", fields.sizeMax, "The largest size", 0],
    ["at_least", fields.atLeast, "At least", 1],
    ["limit", fields.limit, "The file limit", 1],
  ] as const) {
    const n = count(value, name, least);
    if (typeof n === "string") return { ok: false, problem: n };
    if (n !== undefined) filters[key] = n;
  }
  if (filters.size_min !== undefined && filters.size_max !== undefined
      && filters.size_min > filters.size_max) {
    return { ok: false, problem: "The smallest size is larger than the largest, so no file could pass." };
  }
  const file_transaction: Transaction =
    fields.ingestion === "append" ? "APPEND" : fields.ingestion === "update" ? "UPDATE" : "SNAPSHOT";
  return { ok: true, file_transaction, file_filters: filters };
}

/** The configured sync, in a line. */
export function describeFileSync(schedule: {
  sync_source_schema: string | null;
  sync_file_transaction?: Transaction | null;
  sync_file_filters?: FileSyncFilters | null;
}): string {
  const where = schedule.sync_source_schema ? `${schedule.sync_source_schema}/` : "the prefix's root";
  const mode = INGESTIONS.find(
    (i) => i.key === ingestionOf(schedule.sync_file_transaction, schedule.sync_file_filters))!;
  return `${mode.label} of the files in ${where}`;
}

/** What a run took, in a line. */
export function tookText(files: readonly string[]): string {
  if (files.length === 0) return "No files to take.";
  const shown = files.slice(0, 5).join(", ");
  const more = files.length > 5 ? ` and ${files.length - 5} more` : "";
  return `Took ${files.length} ${files.length === 1 ? "file" : "files"}: ${shown}${more}.`;
}
