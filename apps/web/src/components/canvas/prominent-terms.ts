/** p.475's **Prominent Terms**: "define prominently-used terms and phrases to
 * match on within an object set. Showcase the number of matched results, and use
 * the widget as a way to define a custom set of terms for users to apply as
 * filters."
 *
 * > "**Base object set**: Define an object set from which to base the filter
 * > options. **Property**: Select a property on which to filter. **Filter
 * > variable**: An object set filter variable that contains the currently
 * > applied filtering criteria from the widget… **Hide empty terms**: Toggle to
 * > enable/disable hiding terms that return with no results. **Terms**: *Filter
 * > using value*: The value on which to filter the object set, determining the
 * > total count of results returned to display in the term's row. Note that the
 * > filter uses an exact match. *Display name*: The name displayed in the term's
 * > row. *Icon*: Add an icon to display in the term's row." (p.475)
 *
 * ---
 *
 * **This is the Filter List with the list turned around**, and the difference is
 * the whole widget. A Filter List asks the data what values exist and offers
 * them; a Prominent Terms widget is given the values by an author and asks the
 * data how many rows each accounts for. So the same clause vocabulary and the
 * same `narrow_set` derivation carry it — a widget writes clauses, a derivation
 * makes the set (§40) — and what is new is that a term can name a value **no
 * row has**, which a Filter List can never do.
 *
 * **Each count is its own question, and it has to be.** The obvious
 * implementation is one `/object-sets/group` call, which is what the Filter List
 * does — but grouping is capped at `object_sets.MAX_GROUPS` (20) and ordered by
 * count, so a curated term naming a rare value is *absent from the response*.
 * Absent would then mean either "no rows" or "not in the top twenty", and p.475
 * hangs a visible behaviour on exactly that distinction: **Hide empty terms**
 * removes the rows "that return with no results". Hiding a row because its value
 * is unfashionable rather than unused is a lie the author cannot see and the
 * viewer cannot suspect. One `count` aggregation per term answers p.475's own
 * definition — "the total count of results returned" for that filter — exactly,
 * and `MAX_TERMS` is what keeps the fan-out bounded.
 */

/** How many terms one widget may carry.
 *
 * **A cap on a hand-typed list is really a cap on requests**, since each term
 * costs one count. Twelve is a judgement rather than a limit the server
 * enforces: p.475's widget is a short list of prominent values — the screenshot
 * shows four — and a list long enough to need scrolling is the Filter List,
 * which asks one question no matter how many values there are.
 */
export const MAX_TERMS = 12;

export interface Term {
  /** p.475's "Filter using value", matched exactly. */
  value: string;
  /** p.475's "Display name". */
  label: string;
  /** p.475's Icon. One or two characters — there is no icon library here, the
   * same ○ every icon setting in this file carries. */
  icon: string;
}

/** One configured term, read from what the document holds.
 *
 * `null` for a term with no value, because a term is *defined* by the value it
 * filters on — a row with a display name and nothing to match is a label with
 * no question behind it, and rendering one would show a count of the whole set
 * beside a name somebody typed.
 */
export function termOf(raw: unknown): Term | null {
  if (!raw || typeof raw !== "object") return null;
  const t = raw as Record<string, unknown>;
  // **Not trimmed, and this is the one place that matters.** p.475 says the
  // filter is an exact match, so " north" and "north" are different values and
  // the widget must not quietly repair one into the other — a term that was
  // typed with a stray space should return no rows and say so, which is a
  // problem the author can see and fix.
  const value = typeof t.value === "string" ? t.value : "";
  if (!value) return null;
  return {
    value,
    label: typeof t.label === "string" ? t.label.trim() : "",
    icon: typeof t.icon === "string" ? t.icon.trim().slice(0, 2) : "",
  };
}

/** The whole Terms setting, from what the document holds.
 *
 * **A blank row is kept and a valueless one is dropped, and those are the same
 * rule seen from two sides** — §225's, at a different widget. `termsOf` is what
 * the *panel* renders, so a row the author has added and not yet filled in has
 * to survive the keystroke that emptied it; `renderableTerms` is what the
 * *widget* draws, and there a term with no value is nothing to ask about.
 */
export function termsOf(raw: unknown): Term[] {
  if (!Array.isArray(raw)) return [];
  const out: Term[] = [];
  for (const item of raw) {
    if (out.length >= MAX_TERMS) break;
    out.push(termOf(item) ?? blankTerm());
  }
  return out;
}

/** The terms the widget has a question to ask about. */
export function renderableTerms(terms: readonly Term[]): Term[] {
  const seen = new Set<string>();
  const out: Term[] = [];
  for (const term of terms) {
    // **Repeats are dropped rather than counted twice.** Two rows filtering on
    // the same value are two identical requests and two identical numbers, and
    // ticking one would light up the other — the clause list holds values, not
    // rows, so the widget cannot tell them apart afterwards.
    if (!term.value || seen.has(term.value)) continue;
    seen.add(term.value);
    out.push(term);
  }
  return out;
}

export function blankTerm(): Term {
  return { value: "", label: "", icon: "" };
}

/** What a term's row is called. p.475's Display name, or the value it matches —
 * a row with no name still has to be pickable, and the value is the truest
 * label available. */
export function labelOf(term: Term): string {
  return term.label || term.value;
}

/** p.475's Hide empty terms.
 *
 * **A count that has not arrived is not a count of zero**, and the difference is
 * this function's reason to exist. `undefined` means the request is in flight or
 * failed; `0` means the platform answered and there are none. Treating the first
 * as the second makes every term vanish on load and reappear, and makes a failed
 * request look like a deliberate hide — so an unknown count keeps its row
 * whatever the setting says.
 */
export function visibleTerms(
  terms: readonly Term[],
  counts: Readonly<Record<string, number | undefined>>,
  hideEmpty: unknown,
): Term[] {
  if (hideEmpty !== true) return [...terms];
  return terms.filter((term) => counts[term.value] !== 0);
}

/** The clause list the widget writes, from the values currently picked.
 *
 * The Filter List's vocabulary exactly (§40): one value is `eq`, several are
 * `in`, and an empty selection writes **no clause for the property at all**
 * rather than an empty `in` — p.475's filter variable holds "the currently
 * applied filtering criteria", and none applied is no criterion, not a criterion
 * matching nothing.
 */
export function toClauses(
  property: string,
  values: readonly string[],
): { property: string; op: string; value: unknown }[] {
  if (!property || values.length === 0) return [];
  return values.length === 1
    ? [{ property, op: "eq", value: values[0] }]
    : [{ property, op: "in", value: [...values] }];
}

/** Which terms are currently on, read back from the variable this widget writes.
 *
 * **Read back rather than held here**, for the reason the Filter List gives:
 * the document's state is the state, and a second copy in the widget is a second
 * answer that drifts the first time anything else writes the variable.
 */
export function selectedValues(raw: unknown, property: string): string[] {
  if (!property || !Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const clause of raw) {
    const c = clause as { property?: unknown; value?: unknown };
    if (c?.property !== property) continue;
    const values = Array.isArray(c.value) ? c.value : [c.value];
    for (const v of values) {
      if (typeof v !== "string" && typeof v !== "number") continue;
      const text = String(v);
      if (!out.includes(text)) out.push(text);
    }
  }
  return out;
}

/** One term toggled, giving the values that should now be selected. */
export function toggled(values: readonly string[], value: string): string[] {
  return values.includes(value)
    ? values.filter((v) => v !== value)
    : [...values, value];
}

/** What a term's row shows where its number goes.
 *
 * A count that has not arrived shows nothing rather than `0`, which is the same
 * distinction `visibleTerms` turns on and the reason §229's Metric Card shows
 * `—`: a number on screen is believed, so the moment before it is known must not
 * look like an answer.
 */
export function countLabel(count: number | undefined): string {
  return count === undefined ? "" : count.toLocaleString();
}
