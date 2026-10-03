/**
 * An action's Function rule (`action-types` p.22, p.75-83; §773; decision
 * 0018 option B).
 *
 * > "Function rule: Can be used to reference an Ontology edit function whose
 * > inputs are derived from parameters of the action. When this rule is
 * > present, no other rule may be configured" (p.22)
 *
 * The rule names a function whose output is `edits`, a version, whether that
 * version auto-upgrades (p.81), and where each of the function's parameters
 * comes from: an action parameter, a fixed value, or the object the action
 * is run on. The server's `actions.function_rule_problem` and
 * `resolve_function_version` are the same rules; these say them in the form.
 */

import { versionKey } from "./functions";
import type { FunctionDetail, FunctionParameter, FunctionVersion } from "./types";

export type FunctionRuleInput = { parameter: string } | { value: unknown } | { subject: true };

export interface FunctionRuleConfig {
  function_id: string;
  /** The version the rule was set up against: pinned, or with `auto_upgrade`
   * the minimum of p.81's range. */
  version: string;
  auto_upgrade: boolean;
  inputs: Record<string, FunctionRuleInput>;
}

export const BLANK_FUNCTION_RULE: FunctionRuleConfig = {
  function_id: "", version: "", auto_upgrade: false, inputs: {},
};

/** Read from a saved rule, keeping only the shapes it can use. */
export function functionRuleOf(raw: unknown): FunctionRuleConfig {
  const it = raw && typeof raw === "object" && !Array.isArray(raw)
    ? raw as Record<string, unknown> : {};
  const inputs: Record<string, FunctionRuleInput> = {};
  const given = it.inputs && typeof it.inputs === "object" && !Array.isArray(it.inputs)
    ? it.inputs as Record<string, unknown> : {};
  for (const [name, source] of Object.entries(given)) {
    if (!source || typeof source !== "object") continue;
    const s = source as Record<string, unknown>;
    if (s.subject === true) inputs[name] = { subject: true };
    else if (typeof s.parameter === "string" && s.parameter) inputs[name] = { parameter: s.parameter };
    else if ("value" in s) inputs[name] = { value: s.value };
  }
  return {
    function_id: typeof it.function_id === "string" ? it.function_id : "",
    version: typeof it.version === "string" ? it.version : "",
    auto_upgrade: it.auto_upgrade === true,
    inputs,
  };
}

/** p.82: "Auto upgrades are disabled for function versions of the form 0.y.z". */
export function canAutoUpgrade(version: string): boolean {
  const key = versionKey(version);
  return !!key && key[0] > 0;
}

/** The version the action runs: the pinned one, or with p.81's auto upgrade
 * the newest release of the same major at or above it. A prerelease is not
 * in the range: it is not a release. */
export function resolveVersion(
  fn: FunctionDetail | undefined,
  config: FunctionRuleConfig,
): FunctionVersion | undefined {
  const pinned = fn?.versions.find((v) => v.version === config.version);
  if (!fn || !pinned || !config.auto_upgrade || !canAutoUpgrade(config.version)) return pinned;
  const floor = versionKey(config.version)!;
  let best = pinned;
  let bestKey = floor;
  for (const v of fn.versions) {
    const key = versionKey(v.version);
    if (!key || key[0] !== floor[0] || key[3] === 0) continue;
    if (compareKeys(key, bestKey) > 0) {
      best = v;
      bestKey = key;
    }
  }
  return best;
}

function compareKeys(a: ReturnType<typeof versionKey>, b: ReturnType<typeof versionKey>): number {
  for (let i = 0; i < 5; i++) {
    const x = a![i]!;
    const y = b![i]!;
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

/** Each function parameter's source when a function is chosen (p.79: "all
 * inputs of the function will automatically be created as parameters"): an
 * object of the action's own type is the object it runs on, and every other
 * parameter an action parameter of the same name. An object set has no
 * action parameter to come from, so it is left for a value. */
export function defaultInputs(
  version: FunctionVersion,
  subjectTypeId: string | null,
): Record<string, FunctionRuleInput> {
  const inputs: Record<string, FunctionRuleInput> = {};
  let subjectTaken = false;
  for (const p of version.parameters) {
    if (p.data_type === "object" && p.object_type_id === subjectTypeId && !subjectTaken) {
      inputs[p.api_name] = { subject: true };
      subjectTaken = true;
    } else if (p.data_type !== "object_set") {
      inputs[p.api_name] = { parameter: p.api_name };
    }
  }
  return inputs;
}

/** The action parameters p.79 creates for the function's inputs: one for
 * each input read from a parameter the action does not have yet. */
export interface CreatedParameter {
  api_name: string;
  display_name: string;
  data_type: string;
  object_type_id: string | null;
  required: boolean;
}

export function parametersToCreate(
  version: FunctionVersion,
  inputs: Record<string, FunctionRuleInput>,
  existing: readonly string[],
): CreatedParameter[] {
  const byName = new Map<string, FunctionParameter>(version.parameters.map((p) => [p.api_name, p]));
  const out: CreatedParameter[] = [];
  for (const source of Object.values(inputs)) {
    if (!("parameter" in source) || existing.includes(source.parameter)) continue;
    const p = byName.get(source.parameter);
    if (!p || p.data_type === "object_set") continue;
    out.push({
      api_name: p.api_name,
      display_name: p.display_name || p.api_name,
      data_type: p.data_type,
      object_type_id: p.object_type_id ?? null,
      required: p.required,
    });
  }
  return out;
}

/** Why the rule cannot run, or null: what the form says under it. */
export function functionRuleProblem(
  config: FunctionRuleConfig,
  fn: FunctionDetail | undefined,
  parameters: readonly string[],
  subjectTypeId: string | null,
): string | null {
  if (!config.function_id) return "Choose the function this action calls.";
  if (!fn) return "The function this rule calls does not exist.";
  if (!config.version) return "Choose the version this action calls.";
  const pinned = fn.versions.find((v) => v.version === config.version);
  if (!pinned) return `${fn.api_name} has no version ${config.version}.`;
  if (config.auto_upgrade && !canAutoUpgrade(config.version)) {
    return "A 0.y.z version cannot auto-upgrade (action-types p.82).";
  }
  if (pinned.output.kind !== "edits") {
    return `${fn.api_name} is not an edit function: it returns ${pinned.output.kind}.`;
  }
  for (const p of pinned.parameters) {
    const source = config.inputs[p.api_name];
    if (!source) {
      if (p.required) return `${p.api_name} needs a parameter, a value or this object.`;
      continue;
    }
    if ("parameter" in source && !parameters.includes(source.parameter)) {
      return `${p.api_name} reads ${source.parameter}, which is not a parameter of this action.`;
    }
    if ("subject" in source && (p.data_type !== "object" || p.object_type_id !== subjectTypeId)) {
      return `${p.api_name} is not an object of this action's type, so it cannot be this object.`;
    }
  }
  return null;
}
