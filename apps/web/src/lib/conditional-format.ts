/**
 * Evaluating conditional formatting rules (Foundry `object-link-types`
 * p.102–109).
 *
 * > "Conditional formatting enables the configuration of rules for any
 * > property and dictates how that property's values will be rendered (e.g.
 * > coloring, alignment, etc.) in user facing applications." (p.102)
 *
 * **First match wins, and the order is the author's.** p.105's "Always true"
 * fallback only means anything in sequence: it is the rule you put last so
 * that something applies when nothing else did.
 *
 * **The comparison reads the raw stored value, never the formatted text.** A
 * property can carry a formatter (p.94–101) *and* rules, and p.102's own
 * example does — a number shown compactly and coloured by a threshold. If a
 * rule were handed `"$100K"` it would never be greater than 50000, because a
 * string never was greater than anything. So `formatValue` decides the text
 * and this decides the paint, from the same untouched number.
 *
 * **A rule can read a different property than the one it paints** (p.105–106),
 * which is why this takes the whole instance rather than one value.
 *
 * Pure, for `components/canvas/pure.ts`'s reason: a rule engine is exactly the
 * kind of thing a browser test can only confirm rendered *something*.
 */

import type { ConditionalRule, PropertyStyle } from "@/lib/types";

/** The style the first matching rule asks for, or null if none matched.
 *
 * `properties` is the instance's stored values, raw. `null` rather than an
 * empty object so a caller can tell "no rule applied" from "a rule applied and
 * asked for nothing" — the second cannot happen, because the server refuses
 * a rule that changes nothing, and returning `{}` for both would quietly make
 * that refusal untestable from here.
 */
export function conditionalStyle(
  rules: ConditionalRule[] | null | undefined,
  properties: Record<string, unknown>,
): PropertyStyle | null {
  if (!rules?.length) return null;
  for (const rule of rules) {
    if (matches(rule, properties)) {
      const style: PropertyStyle = {};
      if (rule.colour) style.colour = rule.colour;
      if (rule.background) style.background = rule.background;
      if (rule.align) style.align = rule.align;
      return style;
    }
  }
  return null;
}

function matches(rule: ConditionalRule, properties: Record<string, unknown>): boolean {
  if (rule.kind === "always") return true;
  const subject = properties[rule.property];
  // **Absence is not a match, and it is not a mismatch either — the rule does
  // not apply.** This has to sit *before* the negation below, not inside the
  // comparison: "is not exactly A320" is true of an object with no type at
  // all, so a rule evaluated and then flipped would quietly colour every
  // incomplete row. `is_null` is the comparison for asking about absence, and
  // it is the one comparison that wants the empty value.
  if (rule.comparison !== "is_null" && isEmpty(subject)) return false;
  const hit = test(rule, subject, properties);
  // p.105 label F: "Toggle between a True or False rule … To color all planes
  // in blue that are *not* A320, switch this to False."
  return rule.negate ? !hit : hit;
}

function test(
  rule: ConditionalRule & { kind: "standard" },
  subject: unknown,
  properties: Record<string, unknown>,
): boolean {
  if (rule.comparison === "is_null") return isEmpty(subject);

  if (rule.comparison === "boolean") return asBoolean(subject) === rule.value;

  // Handled before the comparand is worked out, because a range has no
  // comparand: it carries its own bounds rather than a value to compare with.
  if (rule.comparison === "numeric_range") {
    const n = asNumber(subject);
    if (n === null) return false;
    // Inclusive at both ends: p.105's example is a threshold a value "drops
    // underneath", and an author who types 0.8 as a max means 0.8 is still in.
    if (rule.min !== undefined && n < rule.min) return false;
    if (rule.max !== undefined && n > rule.max) return false;
    return true;
  }

  // p.105 label E: a constant, or another property's value.
  const comparand = rule.value_property !== undefined
    ? properties[rule.value_property]
    : rule.value;

  if (rule.comparison === "numeric_exact") {
    const a = asNumber(subject);
    const b = asNumber(comparand);
    return a !== null && b !== null && a === b;
  }

  const text = String(subject);
  const against = comparand === null || comparand === undefined ? "" : String(comparand);
  switch (rule.operator) {
    case "is_exactly": return text === against;
    case "contains": return text.includes(against);
    case "starts_with": return text.startsWith(against);
    case "ends_with": return text.endsWith(against);
    default: return false;
  }
}

/** What "Is null" means here (p.106's own use is "color the type in grey if
 * the value is null"). The empty string is included because a CSV sync writes
 * one for a blank cell, so a stricter reading would make the rule useless on
 * exactly the data it is for — the same call `ontology.is_missing` makes. */
function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

/** Properties are stored untyped, so a boolean commonly arrives as "true". */
function asBoolean(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  const text = String(value).trim().toLowerCase();
  if (text === "true") return true;
  if (text === "false") return false;
  return null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "boolean") return null;
  const n = Number(String(value).trim());
  return Number.isFinite(n) ? n : null;
}
