/**
 * Copying conditional formatting from one property to others (§388;
 * `object-link-types` p.107).
 *
 * > "1. Select the property from which you want to copy the conditional
 * >  formatting rule. 2. ... select the Copy rules button to open the Copy
 * >  rule dialog. 3. Select the properties to which you want to copy the
 * >  conditional formatting rules. **If the properties you are copying to
 * >  already have their own conditional formatting rules, they will be
 * >  overwritten by the new rules.**" (p.107)
 *
 * The last sentence is the whole design question, and Foundry answers it:
 * copying **overwrites**. So the only thing left to decide is whether the
 * reader finds that out before or after — and §214 has been the same answer
 * every time this shape has come up (§386's build summary, §387's schedule
 * summary). It is said before the click, and the properties whose rules are
 * about to go are named.
 *
 * **Which properties can be copied to is not a judgement about types.** A
 * rule may read a property other than the one it paints (p.105 label B), so a
 * rule set carried to another property still refers to whatever it referred
 * to before and goes on meaning the same thing. What it must not do is land
 * on the property it came from, which would be a no-op dressed as an action.
 */
import type { ConditionalRule } from "@/lib/types";

export interface FormattedProperty {
  api_name: string;
  conditional_format?: ConditionalRule[] | null;
}

/**
 * The properties a copy could go to: everything named, except the source.
 *
 * **Named**, because a property whose `api_name` is still blank is a row
 * somebody is part-way through adding, and copying onto it would put rules on
 * something that cannot be referred to yet.
 */
export function copyTargets<T extends FormattedProperty>(
  properties: readonly T[],
  fromApiName: string,
): T[] {
  return properties.filter((p) => p.api_name.trim() && p.api_name !== fromApiName);
}

/** Of the chosen targets, the ones that already have rules of their own. */
export function willOverwrite<T extends FormattedProperty>(
  properties: readonly T[],
  chosen: readonly string[],
): T[] {
  const picked = new Set(chosen);
  return properties.filter(
    (p) => picked.has(p.api_name) && (p.conditional_format?.length ?? 0) > 0,
  );
}

/**
 * What the dialog says before the copy happens.
 *
 * **The overwrite is the sentence, not the count of what is being copied.**
 * How many properties receive the rules is visible in the list the reader
 * just ticked; which of them lose rules they already had is not, and it is
 * the half that cannot be undone by ticking a box differently.
 */
export function copySummary<T extends FormattedProperty>(
  properties: readonly T[],
  chosen: readonly string[],
): string {
  if (chosen.length === 0) return "choose the properties to copy these rules to";
  const losing = willOverwrite(properties, chosen);
  const to = `copy to ${chosen.length} propert${chosen.length === 1 ? "y" : "ies"}`;
  if (losing.length === 0) return to;
  const named = losing.length <= 3 ? ` (${losing.map((p) => p.api_name).join(", ")})` : "";
  return `${to}, overwriting the rules on ${losing.length}${named}`;
}

/**
 * The properties with the rules copied onto the chosen ones.
 *
 * **A fresh array per target, not the same one shared.** Rules are edited in
 * place elsewhere in this editor, and handing five properties one array would
 * make editing any of them edit all five — a bug that would look like the
 * copy having worked.
 */
export function copyRulesTo<T extends FormattedProperty>(
  properties: readonly T[],
  rules: readonly ConditionalRule[],
  chosen: readonly string[],
): T[] {
  const picked = new Set(chosen);
  return properties.map((p) =>
    picked.has(p.api_name) && p.api_name.trim()
      ? { ...p, conditional_format: rules.map((r) => ({ ...r })) }
      : p,
  );
}
