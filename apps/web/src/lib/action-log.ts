/**
 * The action log's optional settings, the parts a dialog decides (§586;
 * `action-types` p.168).
 *
 * > "[Optional] Summary: A customizable string to describe the action
 * > [Optional] Property values of object reference parameters (this is not
 * > supported for object reference parameters if allow multiple values is
 * > enabled)" (p.168)
 *
 * **The server checks both** (`services/action_log.py`): a summary naming
 * something the action does not have and a property its object does not have
 * are refused there, with sentences. This decides what the dialog offers:
 * the single object parameters and the object type each holds.
 */

import type { ActionParameter, ActionRule } from "@/lib/types";

export interface ReferenceChoice {
  parameter: string;
  label: string;
  /** The object type whose properties may be kept, or null when nothing says
   * which it holds (the dialog says so rather than guessing). */
  typeId: string | null;
}

/** p.168's object reference parameters: single ones only, since "this is not
 * supported for object reference parameters if allow multiple values is
 * enabled". The type is the parameter's own, or the one a rule writing
 * through it names. */
export function referenceChoices(action: {
  parameters: ActionParameter[];
  rules: Pick<ActionRule, "config">[];
}): ReferenceChoice[] {
  return (action.parameters ?? [])
    .filter((p) => p.data_type === "object")
    .map((p) => {
      const named = (action.rules ?? []).find(
        (r) => (r.config as Record<string, unknown>)?.object === p.api_name,
      );
      const fromRule = named ? (named.config as Record<string, unknown>).object_type : null;
      return {
        parameter: p.api_name,
        label: p.display_name || p.api_name,
        typeId: p.object_type_id ?? (typeof fromRule === "string" && fromRule ? fromRule : null),
      };
    });
}

/** The chosen properties with one ticked or unticked; a parameter with none
 * left is dropped, since the server refuses one naming no property. */
export function withReference(
  chosen: Record<string, string[]>,
  parameter: string,
  prop: string,
  on: boolean,
): Record<string, string[]> {
  const held = chosen[parameter] ?? [];
  const next = on
    ? (held.includes(prop) ? held : [...held, prop])
    : held.filter((p) => p !== prop);
  const out = { ...chosen };
  if (next.length) out[parameter] = next;
  else delete out[parameter];
  return out;
}

/** The kept properties in a sentence, for a log already turned on. */
export function referencesSummary(chosen: Record<string, string[]> | null | undefined): string {
  const parts = Object.entries(chosen ?? {}).map(
    ([parameter, props]) => `${parameter}: ${props.join(", ")}`,
  );
  return parts.length ? `Keeps ${parts.join("; ")}.` : "Keeps no object properties.";
}
