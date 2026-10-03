/**
 * An Object Table's function-backed columns (Workshop p.221; §770).
 *
 * > "Choose Use a runtime input to pass only the objects currently displayed
 * > in the Object Table and thus optimize the performance of our function."
 * > (p.221)
 *
 * The runtime input is the only one built: the page's primary keys go to the
 * column's `object_set` parameter, so a call is one page of rows, never the
 * whole set. Every other parameter comes from a module variable, which is
 * p.221's "change what is displayed based on user input elsewhere", or a fixed
 * value.
 */

import type { FunctionColumn } from "./derived-columns";
import { inputValues, unsetRequired } from "./function-inputs";
import type { FunctionDetail, FunctionResult, FunctionVersion } from "@/lib/types";

/** The version a column calls: the one it names, or the newest. */
export function versionOf(
  fn: FunctionDetail | undefined,
  version: string | null,
): FunctionVersion | undefined {
  if (!fn) return undefined;
  return version ? fn.versions.find((v) => v.version === version) : fn.versions[0];
}

/** What makes two columns one call: function, version and inputs. Two columns
 * showing two fields of one map share it, which is p.221's "single function
 * that produces multiple function-backed properties". */
export function callKey(column: FunctionColumn): string {
  const inputs = Object.keys(column.inputs).sort().map((k) => [k, column.inputs[k]]);
  return JSON.stringify([column.function_id, column.version, column.objects_parameter, inputs]);
}

/** What a call sends: the page's objects, and each other input as it stands.
 * A variable nothing has resolved yet is undefined, which the request's JSON
 * leaves out rather than sending empty. */
export function callValues(
  column: FunctionColumn,
  keys: readonly string[],
  resolved: Record<string, unknown>,
): Record<string, unknown> {
  return { ...inputValues(column.inputs, resolved), [column.objects_parameter]: [...keys] };
}

/** One row's value: its entry's field, or the first field when none is
 * named. Undefined when the map has nothing for the row. */
export function cellOf(
  result: FunctionResult | undefined,
  key: string,
  field: string,
): unknown {
  const entry = result?.entries?.[key];
  if (!entry) return undefined;
  const name = field || result?.columns?.[0]?.name || "";
  return entry[name];
}

/** Why this column cannot be drawn, or null - the sentence the panel shows,
 * and the reason a table draws nothing for it rather than an error per row. */
export function columnProblem(
  column: FunctionColumn,
  fn: FunctionDetail | undefined,
  objectTypeId: string,
): string | null {
  if (!fn) return "The function this column calls does not exist.";
  const version = versionOf(fn, column.version);
  if (!version) return `${fn.api_name} has no version ${column.version}.`;
  if (version.output.kind !== "map") {
    return `${fn.api_name} does not give a value per object (Workshop p.221).`;
  }
  if (version.output.object_type_id !== objectTypeId) {
    return `${fn.api_name} gives values for another object type.`;
  }
  const objects = version.parameters.find((p) => p.api_name === column.objects_parameter);
  if (!objects || objects.data_type !== "object_set" || objects.object_type_id !== objectTypeId) {
    return "Choose the parameter that receives the table's objects.";
  }
  return unsetRequired(version, column.inputs, column.objects_parameter);
}

/** The parameters a table's objects can go to: object sets of its type. */
export function objectParameters(version: FunctionVersion | undefined, objectTypeId: string) {
  return (version?.parameters ?? []).filter(
    (p) => p.data_type === "object_set" && p.object_type_id === objectTypeId,
  );
}
