/** Changing a parameter under specific circumstances, the parts a document
 * decides (§329; `action-types` p.43-46).
 *
 * > "Overrides are used to change a parameter's behavior and configuration
 * > under specific circumstances… removing the need to configure separate
 * > action types with only minor variations." (p.43)
 *
 * > "While assignees can change the status, managers will have to provide a
 * > justification. Using overrides, the Justification reason parameter can be
 * > made **required and visible for managers, while it is hidden and optional
 * > for the assignee**." (p.43)
 *
 * > "Every parameter can contain multiple override blocks, however, **if more
 * > than one is true, only the first one will be executed**." (p.45)
 *
 * > "If an override is configured to take on the same value as the default
 * > already set on the parameter, **a warning will be shown on the override
 * > itself**." (p.45)
 *
 * ---
 *
 * **Whether a block holds is not decided here, and it matters more than it did
 * for a section.** §328's conditions decide what a form draws; these decide
 * what it *asks for*, and the same resolution runs inside `bind_parameters` to
 * decide whether a submission is refused. A browser that evaluated p.45's
 * conditions itself would be a second reading of the document — and the one it
 * would disagree with is the one that governs the write. `POST
 * .../effective-parameters` answers it; what is in this file is which values to
 * watch, and what to say about a block somebody is writing.
 *
 * p.45's warning is here for the same reason every other sentence in this repo
 * is in a pure module: it is wording about a document, and the server has no
 * opinion about it because it is not a refusal. A block that sets what the
 * parameter already says is legal, useless, and exactly the kind of thing
 * somebody leaves behind while editing.
 */

import type { ActionOverrideBlock, ActionParameter } from "@platform/types";

export type OverrideBlock = ActionOverrideBlock;

function side(spec: unknown): Record<string, unknown> {
  return spec && typeof spec === "object" && !Array.isArray(spec)
    ? (spec as Record<string, unknown>)
    : {};
}

/** p.45's "then": what a block may change.
 *
 * Constraints are p.45's fourth and are absent, because the thing they would
 * override is: a parameter here has a type, a default, a `required` and a
 * `hidden`, and no value constraints for a block to narrow.
 */
export const SETTABLE = ["hidden", "required", "default"] as const;

/** Every parameter any override condition reads.
 *
 * The same question `conditionParameters` asks about sections (§328), one
 * document along: a form whose parameters carry no blocks never asks the
 * server what its parameters are, and typing in a parameter nothing is
 * conditional on is not a round trip.
 */
export function conditionParameters(parameters: ActionParameter[]): string[] {
  const named = new Set<string>();
  for (const parameter of parameters ?? []) {
    for (const block of parameter.overrides ?? []) {
      for (const condition of block.conditions ?? []) {
        for (const key of ["left", "right"]) {
          const spec = side(side(condition)[key]);
          if (spec.kind !== "parameter") continue;
          const name = String(spec.parameter ?? "").trim();
          if (name) named.add(name);
        }
      }
    }
  }
  return [...named].sort();
}

/** Whether any parameter has a block at all.
 *
 * **Separate from `conditionParameters`, and §328 paid to learn why.** p.50's
 * other condition template asks about the current user and names no parameter,
 * so a form that decided whether to ask the server by looking for parameter
 * names would never ask — and a parameter required only for a manager would be
 * required for nobody.
 */
export function hasOverrides(parameters: ActionParameter[]): boolean {
  return (parameters ?? []).some((p) => (p.overrides ?? []).length > 0);
}

/** A stable key over only the values the conditions read. */
export function overrideKey(
  parameters: ActionParameter[],
  values: Record<string, unknown>,
): string {
  return JSON.stringify(
    conditionParameters(parameters).map((name) => [name, values?.[name] ?? null]),
  );
}

/** p.45's warning: a block that sets what the parameter already says.
 *
 * > "If an override is configured to take on the same value as the default
 * > already set on the parameter, a warning will be shown on the override
 * > itself."
 *
 * **A warning rather than a refusal**, which is p.45's own choice and the right
 * one: the block is legal, it is simply doing nothing, and it is usually a
 * half-finished edit or the remains of a parameter whose default changed under
 * it. Refusing would stop somebody saving a form over a line that harms
 * nothing.
 *
 * Only the fields the block actually sets are compared — one that leaves
 * `required` alone is not "the same as the default" for a parameter that
 * happens to be optional.
 */
export function sameAsParameter(
  block: OverrideBlock,
  parameter: ActionParameter,
): string | null {
  const same: string[] = [];
  if (block?.set_hidden != null && !!block.set_hidden === !!parameter?.hidden) {
    same.push(block.set_hidden ? "hidden" : "shown");
  }
  if (block?.set_required != null && !!block.set_required === !!parameter?.required) {
    same.push(block.set_required ? "required" : "optional");
  }
  if (
    block?.set_default != null
    && JSON.stringify(block.set_default) === JSON.stringify(parameter?.default_value)
  ) {
    same.push("that default");
  }
  if (same.length === 0) return null;
  return `This override already matches the parameter: it is ${same.join(" and ")} `
    + "anyway. It will change nothing.";
}

/** What a block does, in one line, for the list p.45 calls a block header.
 *
 * > "Each block's header shows a summary of the logic." (p.45)
 */
export function thenSummary(block: OverrideBlock): string {
  const parts: string[] = [];
  if (block?.set_hidden != null) parts.push(block.set_hidden ? "hide it" : "show it");
  if (block?.set_required != null) {
    parts.push(block.set_required ? "require it" : "make it optional");
  }
  if (block?.set_default != null) {
    parts.push(`default it to ${JSON.stringify(block.set_default)}`);
  }
  // `replace_overrides` refuses a block that sets nothing, so this is what a
  // half-written one says while somebody is still filling it in.
  return parts.length ? parts.join(", ") : "change nothing yet";
}

/** How many conditions have to hold, said rather than counted on screen. */
export function ifSummary(block: OverrideBlock): string {
  const count = (block?.conditions ?? []).length;
  if (count === 0) return "always — which this build refuses to save";
  return count === 1 ? "one condition holds" : `all ${count} conditions hold`;
}

/** p.45's first-match rule, said where somebody can act on it.
 *
 * > "You can add multiple override blocks to a single parameter. If more than
 * > one block is true, only the first override is executed." (p.46)
 *
 * Only worth saying when there is more than one block: on a parameter with a
 * single block the sentence is about a situation that cannot arise, and a note
 * that is always on screen is one nobody reads when it matters.
 */
export function orderNote(blocks: OverrideBlock[]): string | null {
  if ((blocks ?? []).length < 2) return null;
  return "If more than one of these holds, only the first is applied (p.45).";
}

/** A block as Add override leaves it.
 *
 * One empty condition rather than none: the server refuses a block with no
 * conditions, and an editor that started somebody in a state it will not save
 * is a control that looks like it works (§214). The condition is blank, which
 * the save refuses by naming the parameter it does not read — but the row is
 * on screen to be filled in.
 */
export function blankBlock(): OverrideBlock {
  return {
    id: "",
    sort_order: 0,
    conditions: [{
      left: { kind: "parameter", parameter: "" },
      operator: "is",
      right: { kind: "value", value: "" },
    }],
    set_hidden: null,
    set_required: null,
    set_default: null,
  };
}

export interface ConditionDraft {
  parameter: string;
  operator: string;
  value: string;
}

/** One condition, as the panel edits it.
 *
 * The stored shape is decision 0007's, general enough to compare two
 * parameters or ask about the current user; the panel offers the case p.43
 * describes — a prior parameter against a value — plus the current user, which
 * is p.43's own example and cannot be expressed any other way.
 */
export function conditionDraft(condition: unknown): ConditionDraft {
  const c = side(condition);
  const left = side(c.left);
  const right = side(c.right);
  return {
    parameter: left.kind === "current_user"
      ? CURRENT_USER
      : String(left.parameter ?? ""),
    operator: String(c.operator ?? "is"),
    value: right.kind === "value" ? String(right.value ?? "") : "",
  };
}

/** The dropdown entry standing for p.50's other condition template. Not a
 * parameter name: an api_name cannot contain `$`, so nothing a builder declares
 * can collide with it. */
export const CURRENT_USER = "$current_user";

export function conditionValue(draft: ConditionDraft): Record<string, unknown> {
  const left = draft.parameter === CURRENT_USER
    ? { kind: "current_user", attribute: "id" }
    : { kind: "parameter", parameter: draft.parameter };
  return {
    left,
    operator: draft.operator || "is",
    right: { kind: "value", value: draft.value },
  };
}

/** The parameters p.45 lets this one's conditions read.
 *
 * > "only parameters which appear above the current parameter in the form
 * > hierarchy can be referenced in override conditions" (p.45)
 *
 * **Narrowing what is declarable, not validating.** The server refuses a block
 * that reads below itself, and this is why nobody meets that refusal by the
 * obvious route — the dropdown does not offer what the save will reject.
 */
export function readableBefore(
  order: string[],
  apiName: string,
): string[] {
  const at = (order ?? []).indexOf(apiName);
  return at < 0 ? [] : (order ?? []).slice(0, at);
}

/** §328's form order, which is what p.45 means by "the form hierarchy".
 *
 * The same arrangement the form draws and the server computes: the parameters
 * no section claimed, then each section's in turn. A parameter inside a hidden
 * section still has a position, because p.45's rule is about what a condition
 * may *read* and a hidden section's parameters are still submitted.
 */
export function formOrder(
  parameters: { api_name: string }[],
  sections: { id: string; parameters: string[] }[],
): string[] {
  const declared = (parameters ?? []).map((p) => p.api_name);
  const known = new Set(declared);
  const inside = (sections ?? []).map((s) =>
    (s.parameters ?? []).filter((n) => known.has(n)));
  const taken = new Set(inside.flat());
  return [...declared.filter((n) => !taken.has(n)), ...inside.flat()];
}

export function moveBlock(
  blocks: OverrideBlock[],
  index: number,
  delta: number,
): OverrideBlock[] {
  const next = [...(blocks ?? [])];
  const to = index + delta;
  if (index < 0 || index >= next.length || to < 0 || to >= next.length) return next;
  const moved = next.splice(index, 1);
  next.splice(to, 0, ...moved);
  return next;
}
