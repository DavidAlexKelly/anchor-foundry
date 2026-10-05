/**
 * Function-backed variables (Workshop p.73; `functions` p.80; §772).
 *
 * > "Function: For function-backed, dynamically computed variables" (p.73)
 *
 * The document keeps one: the module variables it reads are the derivation's
 * `inputs`, as every derivation's are, so the panel's cycle and reference
 * checks see them; `config.parameters` names the parameter each input feeds,
 * in the same order; `config.values` holds the fixed ones. The panel edits it
 * as `FunctionInputs`, the shape a function column and a chart layer use, and
 * these two functions are the crossing.
 */

import type { FunctionInputs } from "./function-inputs";
import { unsetRequired } from "./function-inputs";
import { versionOf } from "./function-columns";
import type { FunctionDetail, WorkshopVariable, WorkshopVariableKind } from "@/lib/types";

type Derivation = NonNullable<WorkshopVariable["derivation"]>;

/** The service's `FUNCTION_KINDS`: p.80's mapping has a row for these and
 * none for an object, a struct, a series or a filter. */
export const FUNCTION_KINDS: readonly WorkshopVariableKind[] = [
  "string", "number", "boolean", "date", "timestamp", "array", "object_set",
];

/** The output a variable of this kind takes: `variable_aggregates._OUTPUT_FOR`. */
export function outputFor(kind: WorkshopVariableKind): "value" | "array" | "object_set" {
  return kind === "array" ? "array" : kind === "object_set" ? "object_set" : "value";
}

export interface FunctionCall {
  function_id: string;
  /** Null calls the newest (`functions` p.49). */
  version: string | null;
  inputs: FunctionInputs;
}

/** What a variable newly computed by a function starts as. */
export const NO_CALL: FunctionCall = { function_id: "", version: null, inputs: {} };

/** A saved derivation as the panel edits it. A parameter fed by a variable
 * and given a value too is the variable's, as the server reads it. */
export function callOf(derivation: Derivation): FunctionCall {
  const config = (derivation.config ?? {}) as Record<string, unknown>;
  const inputs: FunctionInputs = {};
  const values = config.values;
  if (values && typeof values === "object" && !Array.isArray(values)) {
    for (const [name, value] of Object.entries(values)) inputs[name] = { value };
  }
  const names = Array.isArray(config.parameters) ? config.parameters : [];
  names.forEach((name, i) => {
    const variable = derivation.inputs[i];
    if (typeof name === "string" && variable) inputs[name] = { variable };
  });
  return {
    function_id: typeof config.function_id === "string" ? config.function_id : "",
    version: typeof config.version === "string" && config.version ? config.version : null,
    inputs,
  };
}

/** The derivation the server reads, from what the panel holds. */
export function derivationOf(call: FunctionCall): Derivation {
  const inputs: string[] = [];
  const parameters: string[] = [];
  const values: Record<string, unknown> = {};
  for (const [name, source] of Object.entries(call.inputs)) {
    if ("variable" in source) {
      inputs.push(source.variable);
      parameters.push(name);
    } else {
      values[name] = source.value;
    }
  }
  return {
    transform: "function",
    inputs,
    config: { function_id: call.function_id, version: call.version, parameters, values },
  };
}

/** Why the variable cannot be resolved, or null: what the panel says under
 * it. The output must be what the kind holds, and a set of a type. */
export function functionVariableProblem(
  kind: WorkshopVariableKind,
  call: FunctionCall,
  fn: FunctionDetail | undefined,
): string | null {
  if (!FUNCTION_KINDS.includes(kind)) return `A function cannot fill a ${kind} variable.`;
  if (!call.function_id) return "Choose the function this variable calls.";
  if (!fn) return "The function this variable calls does not exist.";
  const version = versionOf(fn, call.version);
  if (!version) return `${fn.api_name} has no version ${call.version}.`;
  const wanted = outputFor(kind);
  if (version.output.kind !== wanted) {
    return `${fn.api_name} returns ${version.output.kind.replace("_", " ")}, and a ${kind} ` +
      `variable takes ${wanted.replace("_", " ")}.`;
  }
  return unsetRequired(version, call.inputs);
}
