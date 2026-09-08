/**
 * Configuring an export (Foundry `data-connection` p.17, p.192-206; decision
 * 0014; §267).
 *
 * §265 built the rule, the store, the runner and the routes, and left all of it
 * reachable only by posting JSON — the shape §252 named, and the one this
 * project has now closed for notify rules (§258), webhooks (§261) and egress
 * policies (§264).
 *
 * The division is this repo's usual one: the server owns what is **legal**
 * (`services/exports.parse`, which refuses every case below independently),
 * this owns what a form may **offer** and what it can say before a round trip.
 *
 * **The interesting half is not validation, it is p.192.** An export's whole
 * question is whether there is anything new to send, and the answer is a
 * comparison between two numbers the API already returns on every row. Saying
 * it there — "up to date", "one version behind" — is the difference between a
 * list of exports and a list somebody can act on.
 */

/** p.195-196's six, minus the four that need a transaction log this platform
 * does not keep (decision 0014 §2). The server's `exports.MODES` is the same
 * pair; this list exists so a picker cannot offer a seventh. */
export const MODES = ["mirror", "full"] as const;

export type ExportMode = (typeof MODES)[number];

/** What each mode does, in p.195's own terms.
 *
 * **`full`'s consequence is in its label**, because p.195 says the mode "will
 * almost always result in duplicates in the external table" and somebody
 * choosing between two options should read that where they are choosing rather
 * than in a document they will not open. */
export const MODE_LABELS: Record<ExportMode, string> = {
  mirror: "Replace the table each run, so it always matches the dataset",
  full: "Append the whole dataset each run — the table keeps every run's rows",
};

/** Which source types can be a destination, and as which kind (p.17, p.192).
 * Mirrors `services/exports.DESTINATIONS`; a test compares the two so the
 * picker cannot offer a source the server would refuse. */
export const DESTINATIONS: Record<string, "table" | "file"> = {
  postgres: "table",
  mysql: "table",
  s3: "file",
};

/** Why a REST source is absent from the picker — a redirection, not a gap.
 *
 * p.17 lists webhooks beside the export types as the other way data leaves for
 * an external system, and §259-§262 built that. Said out loud because "REST is
 * missing from the dropdown" reads as something somebody should fix. */
export const REST_INSTEAD =
  "A REST source is written to with a webhook rather than an export — a " +
  "webhook already carries the method, path and body an HTTP write needs.";

/** p.197's refusal, in DuckDB's spellings.
 *
 * The parameterised forms are what actually occur — `STRUCT(a INTEGER)`,
 * `INTEGER[]`, `MAP(VARCHAR, INTEGER)` — so this matches the leading word or a
 * trailing `[]` rather than testing membership of three bare names, which
 * would match none of them. Same expression as the server's `_UNEXPORTABLE`. */
const UNEXPORTABLE = /^(struct|map|list|union)\b|\[\]$/i;

/** A schema, table or path somebody typed. Shape, not content: these reach an
 * identifier position in SQL, so what matters is that nothing here can close a
 * quoted identifier or begin a statement. */
const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_$]*$/;

export const MAX_NAME = 200;

export interface ExportDraft {
  connection_id: string;
  dataset_id: string;
  name: string;
  mode: ExportMode;
  /** Table destination. */
  schema: string;
  table: string;
  /** File destination. */
  prefix: string;
}

export function blankExport(): ExportDraft {
  return {
    connection_id: "",
    dataset_id: "",
    name: "",
    // A default that is *safe* rather than merely first: `mirror` leaves the
    // destination equal to the dataset, and `full` accumulates duplicates by
    // design. A form whose untouched state quietly appends forever is a form
    // whose default is the surprising one.
    mode: "mirror",
    schema: "",
    table: "",
    prefix: "",
  };
}

/** The kind an export against this source would be, or null if it cannot be one. */
export function kindOf(sourceType: string): "table" | "file" | null {
  return DESTINATIONS[sourceType] ?? null;
}

/** The sources that can be a destination, out of everything a project has.
 *
 * A source that *could* be one but has not been turned on (p.202) is kept and
 * flagged rather than dropped: "your admin has not enabled this" and "this kind
 * of source cannot be a destination" are different sentences, and a picker that
 * merged them would send somebody looking for the wrong fix.
 */
export function destinations<T extends { source_type: string; exports_enabled: boolean }>(
  connections: readonly T[],
): { usable: T[]; disabled: T[] } {
  const possible = connections.filter((c) => kindOf(c.source_type) !== null);
  return {
    usable: possible.filter((c) => c.exports_enabled),
    disabled: possible.filter((c) => !c.exports_enabled),
  };
}

/** The dataset columns p.197 refuses, by name and all at once. */
export function unexportableColumns(
  schema: readonly { name: string; data_type?: string; type?: string }[],
): string[] {
  return schema
    .filter((column) => UNEXPORTABLE.test(String(column.data_type ?? column.type ?? "")))
    .map((column) => column.name);
}

/** What the form says about a draft, or null when it has nothing to say. */
export function problem(
  draft: ExportDraft,
  context: {
    sourceType: string | null;
    datasetSchema?: readonly { name: string; data_type?: string; type?: string }[];
    existingNames?: readonly string[];
  },
): string | null {
  if (!draft.connection_id) return "Choose the source to export to.";
  if (!draft.dataset_id) return "Choose the dataset to export.";

  const kind = context.sourceType ? kindOf(context.sourceType) : null;
  if (context.sourceType === "rest") return REST_INSTEAD;
  if (kind === null) return "That source cannot be an export destination.";

  const name = draft.name.trim();
  if (!name) return "Name this export.";
  if (name.length > MAX_NAME) return `A name is at most ${MAX_NAME} characters.`;
  if ((context.existingNames ?? []).includes(name)) {
    return `This project already has an export called ${name}.`;
  }

  // p.197, checked here because the dataset's schema is on screen. The server
  // refuses it too; a form that only found out on Save would be one somebody
  // has already left.
  const refused = unexportableColumns(context.datasetSchema ?? []);
  if (refused.length) {
    return (
      "p.197: Array, Map and Struct columns cannot be exported, and this " +
      `dataset has ${[...refused].sort().join(", ")}.`
    );
  }

  if (kind === "table") {
    if (!draft.table.trim()) return "Name the table to write to.";
    for (const [label, value] of [["table", draft.table], ["schema", draft.schema]] as const) {
      const trimmed = value.trim();
      if (trimmed && !IDENTIFIER.test(trimmed)) {
        return `“${trimmed}” is not a ${label} name — letters, digits and underscores, starting with a letter or underscore.`;
      }
    }
    if (!MODES.includes(draft.mode)) return "Choose how this export writes.";
    return null;
  }

  const prefix = draft.prefix.trim().replace(/^\/+/, "");
  if (!prefix) return "Name the path to write files under.";
  if (prefix.includes("..")) return "A path may not contain “..”.";
  return null;
}

/** The draft as the API takes it. Only meaningful once {@link problem} is null. */
export function toPayload(
  draft: ExportDraft,
  sourceType: string,
): Record<string, unknown> {
  const kind = kindOf(sourceType);
  return {
    connection_id: draft.connection_id,
    dataset_id: draft.dataset_id,
    name: draft.name.trim(),
    // **Null, not the empty string.** db 0069 constrains a file export to have
    // no mode, and `""` is a value the enum cast would refuse — the sort of
    // difference that reaches a person as a 500 quoting a constraint.
    mode: kind === "table" ? draft.mode : null,
    destination:
      kind === "table"
        ? { schema: draft.schema.trim(), table: draft.table.trim() }
        : { prefix: draft.prefix.trim().replace(/^\/+/, "") },
  };
}

/** One line for a list: what this export does, in the destination's terms. */
export function summarise(row: {
  kind: string;
  mode: string | null;
  destination: Record<string, unknown>;
}): string {
  if (row.kind === "file") return `files to ${String(row.destination.prefix ?? "")}`;
  const table = String(row.destination.table ?? "");
  const schema = String(row.destination.schema ?? "");
  const where = schema ? `${schema}.${table}` : table;
  return `${row.mode === "mirror" ? "replaces" : "appends to"} ${where}`;
}

/** **p.192's question, answered on the row.**
 *
 * "Prior to June 2025, exports have been marked as `failed` if there are no new
 * files or rows to be exported during a build. From June 2025 onward, exports
 * with no new files or rows to be exported will be marked as `success`."
 *
 * That change makes "nothing happened" a *success*, which is right and leaves
 * a list of green runs that says nothing about whether the destination is
 * current. This is the sentence that does say it — and `full` gets its own,
 * because for that mode "behind" is not a state it can be in: p.195's use is a
 * destination that empties itself, so every run has something to send.
 */
export function freshness(row: {
  mode: string | null;
  last_version: number | null;
  dataset_version: number;
}): { label: string; behind: boolean } {
  if (row.last_version === null) {
    return { label: "never run", behind: row.dataset_version > 0 };
  }
  if (row.mode === "full") {
    return { label: `last exported v${row.last_version}`, behind: false };
  }
  const gap = row.dataset_version - row.last_version;
  if (gap <= 0) return { label: `up to date (v${row.last_version})`, behind: false };
  return {
    label: gap === 1 ? "one version behind" : `${gap} versions behind`,
    behind: true,
  };
}

/** How a run reads in the history (p.206).
 *
 * A skip is its own word rather than a second kind of success, because "nothing
 * happened" and "nothing ran" are exactly the two answers somebody reading a
 * history is trying to tell apart — and after p.192 they both look like a green
 * tick.
 */
export function runLabel(run: {
  status: string;
  skipped: boolean;
  rows_written: number;
  dataset_version: number | null;
}): string {
  if (run.status === "failed") return "failed";
  if (run.skipped) return `nothing new (v${run.dataset_version ?? "?"})`;
  return `${run.rows_written.toLocaleString()} row${run.rows_written === 1 ? "" : "s"}`;
}
