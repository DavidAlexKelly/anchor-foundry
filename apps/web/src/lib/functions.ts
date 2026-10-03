/**
 * Writing and calling a function, as a form needs it (decision 0018 option B;
 * §768-§769; Foundry `functions` p.49-50, p.80).
 *
 * The server is authoritative: `services/functions.py` refuses every one of
 * these, and runs the SQL against empty inputs before it saves a version,
 * which is the check no form can make. What lives here is what a dialog can
 * say while the fields are still on screen, in the server's words.
 */

import type {
  FunctionOutput, FunctionParameter, FunctionResult, FunctionVersion,
} from "@/lib/types";

/** p.80's Workshop variable types, as the server's `SCALAR_TYPES` has them. */
export const SCALAR_TYPES = ["string", "integer", "float", "boolean", "date", "timestamp"] as const;
export const PARAMETER_TYPES = [...SCALAR_TYPES, "object", "object_set"] as const;
export const OUTPUT_KINDS: { kind: FunctionOutput["kind"]; label: string }[] = [
  { kind: "value", label: "A value" },
  { kind: "array", label: "A list of values" },
  { kind: "object_set", label: "An object set" },
  { kind: "map", label: "Values per object" },
  { kind: "aggregation", label: "Values by category, for a chart" },
  { kind: "table", label: "A table" },
  // action-types p.75's Ontology edit function (§773), for a Function rule.
  { kind: "edits", label: "Edits to objects, for an action" },
];

/** Whether a parameter names an object type: one object, or a set (§770). */
export function refersToObjects(dataType: string): boolean {
  return dataType === "object" || dataType === "object_set";
}

const NAME_RE = /^[a-z][a-z0-9_]{0,99}$/;
const VERSION_RE = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?$/;
const PARAM_RE = /\$([A-Za-z_][A-Za-z0-9_]*)/g;

export interface DraftVersion {
  version: string;
  parameters: FunctionParameter[];
  inputs: string[];
  output: FunctionOutput;
  sql: string;
}

export function blankParameter(): FunctionParameter {
  return { api_name: "", data_type: "string", object_type_id: null, required: true };
}

export function blankDraft(): DraftVersion {
  return {
    version: "1.0.0",
    parameters: [],
    inputs: [],
    output: { kind: "value", data_type: "integer" },
    sql: "",
  };
}

/** p.50's order, as the server's `version_key`: a prerelease before its
 * release, prerelease identifiers compared as text. Null when not a version. */
export function versionKey(version: string): [number, number, number, number, string] | null {
  const found = VERSION_RE.exec(version);
  if (!found) return null;
  return [Number(found[1]), Number(found[2]), Number(found[3]), found[4] ? 0 : 1, found[4] ?? ""];
}

export function compareVersions(a: string, b: string): number {
  const x = versionKey(a);
  const y = versionKey(b);
  if (!x || !y) return 0;
  for (const [i, part] of x.entries()) {
    const other = y[i] as typeof part;
    if (part !== other) return part < other ? -1 : 1;
  }
  return 0;
}

/** The version a new one starts from: the next patch after `latest`, or the
 * release a prerelease was leading to. The author may change it (p.49). */
export function nextVersion(latest: string): string {
  const key = versionKey(latest);
  if (!key) return "";
  const [major, minor, patch, released] = key;
  return released ? `${major}.${minor}.${patch + 1}` : `${major}.${minor}.${patch}`;
}

/** A stored version as the start of the next one. */
export function draftOf(stored: FunctionVersion): DraftVersion {
  return {
    version: nextVersion(stored.version),
    parameters: stored.parameters.map((p) => ({ ...p, object_type_id: p.object_type_id ?? null })),
    inputs: [...stored.inputs],
    output: { ...stored.output },
    sql: stored.sql,
  };
}

/** The `$names` the SQL uses. */
export function parametersUsed(sql: string): string[] {
  return [...new Set([...sql.matchAll(PARAM_RE)].map((m) => m[1] ?? ""))];
}

/** The first reason this version could not be saved, or null. */
export function draftProblem(draft: DraftVersion, latest: string | null): string | null {
  if (!versionKey(draft.version)) {
    return `${draft.version || "That"} is not a version such as 1.0.0.`;
  }
  if (latest && compareVersions(draft.version, latest) <= 0) {
    return `A new version must come after ${latest}; a published one never changes.`;
  }
  const seen = new Set<string>();
  for (const [index, p] of draft.parameters.entries()) {
    if (!NAME_RE.test(p.api_name)) {
      return `Parameter ${index + 1} needs a name in lower case, such as region.`;
    }
    if (seen.has(p.api_name)) return `Two parameters are called ${p.api_name}.`;
    seen.add(p.api_name);
    if (refersToObjects(p.data_type) && !p.object_type_id) {
      return `Choose the object type ${p.api_name} refers to.`;
    }
  }
  if ((draft.output.kind === "value" || draft.output.kind === "array") && !draft.output.data_type) {
    return "Choose the type of value it returns.";
  }
  if (draft.output.kind === "object_set" && !draft.output.object_type_id) {
    return "Choose the object type of the set it returns.";
  }
  if (draft.output.kind === "map" && !draft.output.object_type_id) {
    return "Choose the object type it gives values for.";
  }
  if (draft.output.kind === "edits" && !draft.output.object_type_id) {
    return "Choose the object type it edits.";
  }
  if (!draft.sql.trim()) return "Write the query.";
  const used = parametersUsed(draft.sql);
  const undeclared = used.filter((n) => !seen.has(n));
  if (undeclared.length) return `The query uses $${undeclared[0]}, which no parameter declares.`;
  const unused = [...seen].filter((n) => !used.includes(n));
  if (unused.length) return `${unused[0]} is declared and the query never uses $${unused[0]}.`;
  return null;
}

/** The request body for a version: only the fields its kinds use. */
export function bodyOf(draft: DraftVersion): Record<string, unknown> {
  const output: Record<string, unknown> = { kind: draft.output.kind };
  if (draft.output.kind === "value" || draft.output.kind === "array") {
    output.data_type = draft.output.data_type;
  }
  if (draft.output.kind === "object_set" || draft.output.kind === "map"
      || draft.output.kind === "edits") {
    output.object_type_id = draft.output.object_type_id;
  }
  return {
    version: draft.version,
    parameters: draft.parameters.map((p) => ({
      api_name: p.api_name,
      data_type: p.data_type,
      required: p.required,
      ...(refersToObjects(p.data_type) ? { object_type_id: p.object_type_id } : {}),
    })),
    inputs: draft.inputs,
    output,
    sql: draft.sql,
  };
}

/** What was typed into a run's fields, as the values the parameters take.
 * Blank is left out, so an optional parameter goes unset. A number that is
 * not one is sent as typed, for the server to refuse by name. */
export function valuesFor(
  parameters: FunctionParameter[],
  typed: Record<string, string>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const p of parameters) {
    const raw = (typed[p.api_name] ?? "").trim();
    if (raw === "") continue;
    if (p.data_type === "integer" || p.data_type === "float") {
      out[p.api_name] = Number.isFinite(Number(raw)) ? Number(raw) : raw;
    } else if (p.data_type === "object_set") {
      // Primary keys, comma separated, as the run dialog takes them.
      out[p.api_name] = raw.split(",").map((k) => k.trim()).filter(Boolean);
    } else if (p.data_type === "boolean") {
      out[p.api_name] = raw === "true" ? true : raw === "false" ? false : raw;
    } else {
      out[p.api_name] = raw;
    }
  }
  return out;
}

/** A result in one line, for the run dialog's heading. */
export function resultLine(result: FunctionResult): string {
  if (result.kind === "value") {
    return result.value === null || result.value === undefined ? "No value" : String(result.value);
  }
  if (result.kind === "aggregation") {
    const n = result.buckets?.length ?? 0;
    return `${n} ${n === 1 ? "bucket" : "buckets"}`;
  }
  if (result.kind === "table") {
    const n = result.rows?.length ?? 0;
    return `${n} ${n === 1 ? "row" : "rows"}${result.truncated ? " (the first of more)" : ""}`;
  }
  if (result.kind === "edits") {
    const n = result.edits?.length ?? 0;
    return `${n} ${n === 1 ? "edit" : "edits"}`;
  }
  const n = result.kind === "map"
    ? Object.keys(result.entries ?? {}).length : result.values?.length ?? 0;
  const noun = result.kind === "array" ? "value" : "object";
  return `${n} ${n === 1 ? noun : `${noun}s`}`;
}
