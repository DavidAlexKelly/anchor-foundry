/**
 * A function's inputs as a widget holds them (§770, §771): each parameter fed
 * from a module variable or a fixed value. One copy for an Object Table's
 * function column and a chart's function layer, since both are "configure the
 * necessary inputs for the function" (Workshop p.221).
 */

import type { FunctionVersion } from "@/lib/types";

export type FunctionInputs = Record<string, { variable: string } | { value: unknown }>;

/** Read from a saved document, keeping only the two shapes it can use. */
export function inputsOf(raw: unknown): FunctionInputs {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: FunctionInputs = {};
  for (const [name, source] of Object.entries(raw as Record<string, unknown>)) {
    if (!source || typeof source !== "object") continue;
    const it = source as Record<string, unknown>;
    if (typeof it.variable === "string" && it.variable) out[name] = { variable: it.variable };
    else if ("value" in it) out[name] = { value: it.value };
  }
  return out;
}

/** Each input as it stands now. A variable nothing has resolved is
 * undefined, which the request's JSON leaves out rather than sending empty. */
export function inputValues(
  inputs: FunctionInputs,
  resolved: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, source] of Object.entries(inputs)) {
    out[name] = "variable" in source ? resolved[source.variable] : source.value;
  }
  return out;
}

/** The first required parameter nothing feeds, other than `except`. */
export function unsetRequired(
  version: FunctionVersion,
  inputs: FunctionInputs,
  except = "",
): string | null {
  const unset = version.parameters.find(
    (p) => p.api_name !== except && p.required && !inputs[p.api_name],
  );
  return unset ? `${unset.api_name} needs a value or a variable.` : null;
}
