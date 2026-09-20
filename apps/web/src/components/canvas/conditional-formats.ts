/**
 * Conditional formatting *inside a Workshop module* (`foundry_workshop` p.175,
 * and p.329's Metric Card example).
 *
 * > "Conditional formatting applies rules to determine how **numbers and
 * > sparklines** are styled. In Workshop, conditional formatting can be used
 * > to style time series property columns in the Object Table widget and time
 * > series property displays in the Metric Card widget. This formatting is
 * > local to the Workshop module, and not global to the ontology." (p.175)
 *
 * > "…displays the metric in red if its value is less than or equal to zero,
 * > and in green otherwise." (p.329)
 *
 * The same two surfaces §404 gave p.174's value formatting, and the same
 * `seriesFormats`/`valueFormat` shape beside them.
 *
 * ---
 *
 * **§158's rules, unchanged.** A rule here is an ordinary `ConditionalRule` —
 * p.105's whole grammar, first-match-wins, and the Always-true fallback that
 * has to be last. What differs is only *what the comparison reads*: the
 * ontology's rules read an instance's stored properties, and these read the
 * one number the widget is showing. So the evaluator is given a bag of exactly
 * one entry rather than a new evaluator being written (§292).
 *
 * The subject is named rather than numbered because §158's editor titles its
 * dialog after it: "Rules for latest value" is a sentence, and "Rules for
 * value" is a variable.
 *
 * ---
 *
 * **Why the module owns these and the ontology cannot**, which is the half of
 * p.175's "not global to the ontology" that is a fact rather than a policy —
 * and it is a *different* half from §404's:
 *
 * * `services/conditional_format.py` puts no base-type limit on the property a
 *   rule paints, so an ontology rule on a `time_series` property **is** savable
 *   today. Unlike value formatting, there genuinely is something that could
 *   have collided.
 * * It never arrives, though, because the Object Table's `time_series` branch
 *   renders `SeriesCell` instead of `PropertyValue`, and `PropertyValue` is the
 *   only place `conditionalStyle`'s paint is applied.
 *
 * So the two do not collide today, and this file does not pretend to arbitrate
 * between them. **What it must not do is silently become that arbitration**: if
 * the series cell is ever given the ontology's paint as well, the order has to
 * be chosen out loud, because a rule painting a `time_series` property and a
 * rule painting the number drawn from it are two authors with one cell.
 *
 * ---
 *
 * **What a rule reads is the number, not the text.** §158's own reason, one
 * layer further out: §404 may be writing that number as `"$1,235"`, and a rule
 * saying "red below 500" handed that string is a rule that never fires,
 * because a string never was below anything.
 */

import type { ConditionalRule, PropertyStyle } from "@/lib/types";
import { conditionalStyle } from "../../lib/conditional-format";

/** What the Object Table's column rules compare: p.583's "latest value of the
 * time series", which is the number in the cell. */
export const SERIES_SUBJECT = "latest value";

/** What the Metric Card's rules compare: p.328's metric value. */
export const METRIC_SUBJECT = "metric value";

/** The subject as §158's editor wants its property list — one entry, so the
 * "compare against another property" dropdown has exactly one honest answer.
 *
 * `float` rather than `integer`: p.105's comparison list is the same for both,
 * and a series of readings or an average is not a whole number.
 */
export function subjectProperties(subject: string) {
  return [{ api_name: subject, data_type: "float" as const }];
}

/**
 * One stored rule list, or `null` when there is nothing usable there.
 *
 * Defensive for §212's reason and §404's: the layout document holds whatever
 * the raw JSON editor put there. **Dropped whole rather than rule by rule** —
 * first-match-wins makes a list an ordered thing, so discarding the second of
 * three rules silently promotes the third into its place, which is a different
 * set of colours rather than a smaller one.
 */
export function rulesOf(raw: unknown): ConditionalRule[] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  for (let i = 0; i < raw.length; i += 1) {
    if (!usable(raw[i])) return null;
    // p.105's fallback is only a fallback if it is last, and the server refuses
    // one that is not. A document that holds one anyway would silently drop
    // every rule after it - so the list is refused rather than half-applied.
    if ((raw[i] as { kind?: unknown }).kind === "always" && i !== raw.length - 1) return null;
  }
  return raw as ConditionalRule[];
}

function usable(rule: unknown): boolean {
  if (!rule || typeof rule !== "object" || Array.isArray(rule)) return false;
  const it = rule as Record<string, unknown>;
  // A rule that asks for nothing is a rule that does nothing, and
  // `services/conditional_format.py` refuses one for that reason.
  if (!it.colour && !it.background && !it.align) return false;
  if (it.kind === "always") return true;
  if (it.kind !== "standard") return false;
  if (typeof it.property !== "string" || it.property === "") return false;
  return typeof it.comparison === "string";
}

/** The Object Table's per-column rule lists, keyed by property API name — the
 * same shape §404's `seriesFormats` uses, and for the same reasons. */
export function rulesByColumn(raw: unknown): Record<string, ConditionalRule[]> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Record<string, ConditionalRule[]> = {};
  for (const [name, value] of Object.entries(raw as Record<string, unknown>)) {
    const rules = rulesOf(value);
    if (rules) out[name] = rules;
  }
  return out;
}

/**
 * The paint for one number, or `null` when no rule matched.
 *
 * **A missing number is passed as one**, and the reason is a sentence about
 * §158's matcher rather than a choice made here: `matches` reads
 * `properties[rule.property]` and then asks `isEmpty` of it, so a key holding
 * `null` and a key that is not there are the same question. An empty series is
 * therefore left alone by every ordinary rule and *can* be painted by an
 * `is_null` one — which is p.106's own use of that comparison.
 *
 * This branched on the absent case until the mutation sweep showed the branch
 * changed nothing (§189: a no-op mutant reports as a survivor). The comment
 * there claimed it was saying something the two forms only agreed on by
 * coincidence, and that was the claim that was wrong — `isEmpty` is not a
 * coincidence, it is the contract. Deleted rather than tested, with the
 * contract named in its place.
 *
 * What must stay true is that a missing number is **not zero**: `?? 0` would
 * make an empty series match "at or below zero" and paint a threshold nobody
 * crossed. That is a real claim and `conditional-formats.test.ts` pins it —
 * verified by mutating this line to `?? 0`, which that test kills.
 *
 * ---
 *
 * **`pending` paints nothing, and the fallback is why.** A read in flight has
 * no number, so every threshold rule falls through to p.105's Always-true
 * rule — which matches anything and is last by construction. A loading table
 * would therefore flash every row the fallback's colour and then settle, which
 * reads as "all of these are fine" about data nobody has read yet. Distinct
 * from *no rule matched*, and for the same reason `Sparkline` distinguishes
 * "…" from "No readings": absence of an answer is not an answer.
 *
 * Found by a full-file browser run rather than by the mutation sweep — in
 * isolation the read lands before the first assertion and the window never
 * opens. The rule lives here rather than in the two widgets so there is one
 * place for it and it can be tested at all.
 */
export function paintFor(
  rules: ConditionalRule[] | null | undefined,
  subject: string,
  value: number | null | undefined,
  { pending = false }: { pending?: boolean } = {},
): PropertyStyle | null {
  if (pending || !rules?.length) return null;
  return conditionalStyle(rules, { [subject]: value ?? null });
}

/**
 * The sparkline's stroke, from the same paint as the number.
 *
 * p.175 styles *"the summarized value and the sparkline"* — one rule, two
 * marks — so this reads the rule's text colour rather than taking a colour of
 * its own. A second setting would let the two disagree about a threshold they
 * are both reporting.
 *
 * **A background is not a stroke.** A rule asking only for a background says
 * nothing about a line, and painting the line with it would draw the
 * sparkline in the colour meant to sit *behind* the number.
 */
export function strokeFor(paint: PropertyStyle | null | undefined): string | undefined {
  return paint?.colour || undefined;
}
