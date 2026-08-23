/** A Tabs section and the variable that can drive it (Foundry `workshop`
 * p.54, p.84).
 *
 * > "**Tabs**: Adds tabs to the top of a section and allows module builders to
 * > configure different configurations of widgets within each tab of a
 * > section." (p.54)
 *
 * A *section* layout, which is the detail that matters and the one this repo
 * previously substituted away. The Tabs **widget** here switches pages, and
 * `CanvasSection`'s own comment called that "the same idea one level up" — but
 * it is not, because a module has exactly one set of pages. Two independent
 * tab groups side by side on one page, which p.54 describes as ordinary, could
 * not be expressed at all, and p.84's rule below had nowhere to live.
 *
 * > "For each Tab section in the module, a Switch to {tab name} event will be
 * > added for each tab in the section. **Unlike** the Switch to {page name},
 * > and section collapse state events, events that change the selected tab
 * > **will also update the value of the string variable** configured for
 * > Variable-Based Tab Selection if a variable is configured." (p.84)
 *
 * So this is §185 and §189's sentence with the negation removed, and the
 * temptation is to conclude that the arithmetic is different too. It is not.
 * **The write-back is in the wiring, not in the resolution**: a tab switch
 * still has to show the new tab *now*, while the variable's new value needs a
 * debounce and a server round trip to come back. For those few hundred
 * milliseconds the event and the variable disagree in exactly the way p.81's
 * do, and something still has to say which is on screen.
 *
 * The answer is the same one, for the same reason — **the most recent
 * instruction wins** — and the difference p.84 describes is that here the two
 * *converge*: the write lands, the variable comes back agreeing, and the
 * override is retired by a value it no longer differs from. `collapse.ts` and
 * `page-selection.ts` describe a disagreement that persists; this describes
 * one that heals. Same function, different ending.
 */

/** The tab labels for a section, one per child.
 *
 * `spec` is the author's comma-separated list, in the same idiom as the
 * section's `weights` — one field editing a per-child list, so a Tabs section
 * is configured the way a Columns section already is rather than by inventing
 * a second shape.
 *
 * **Missing entries become "Tab 3", not the child widget's name.** Reading the
 * child's name would need an editor query from inside the section and would
 * make the tab bar say "Section" over a section, which tells a reader nothing.
 * A numbered placeholder is visibly a placeholder.
 *
 * **Duplicates are made unique**, because a tab name is an address: p.84's
 * event and the backing variable both name a tab by its label, and two tabs
 * called "Details" leave both with no answer. Suffixed rather than refused —
 * a section is drawn while it is being configured, and an author halfway
 * through typing should see a tab bar, not an error.
 */
export function tabLabels(spec: string | null | undefined, count: number): string[] {
  const given = String(spec || "")
    .split(",")
    .map((name) => name.trim());
  const out: string[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < count; index += 1) {
    const base = given[index] || `Tab ${index + 1}`;
    let name = base;
    let suffix = 2;
    while (seen.has(name)) {
      name = `${base} ${suffix}`;
      suffix += 1;
    }
    seen.add(name);
    out.push(name);
  }
  return out;
}

/** The tab a backing variable's value names, or null for "nothing this section
 * has".
 *
 * Matched against the labels rather than parsed, because a tab name is
 * whatever the author typed. Trimmed for `asPageId`'s reason — the labels are
 * trimmed too, so a value differing only by a space would miss the tab it
 * obviously means. A non-string is not coerced, for `asPageId`'s other reason:
 * a tab called "2" is a name somebody could have typed, so coercing the number
 * 2 would make an ill-typed variable land on a real tab by accident.
 */
export function asTabName(value: unknown, labels: readonly string[]): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return labels.includes(text) ? text : null;
}

/** A Switch-to-tab event's instruction, and the variable value it was given
 * against. Same shape and same argument as `CollapseOverride` and
 * `PageOverride`. */
export interface TabOverride {
  name: string;
  /** The backing variable's tab name when this override was set, or `null` for
   * a section with no backing variable — and also for one whose variable held
   * something this section has no tab for. */
  against: string | null;
}

/** Which tab is showing right now.
 *
 * `variable` is the backing variable's resolved value, or `undefined` when the
 * section has no Variable-Based Tab Selection.
 *
 * Returns the **first** tab when nothing names one, which is p.54's own
 * behaviour for a section you have just given tabs to, and is the only answer
 * that cannot leave a section showing nothing. Null only when there are no
 * tabs at all.
 */
export function activeTab(
  override: TabOverride | undefined,
  variable: unknown,
  labels: readonly string[],
): string | null {
  const first = labels[0] ?? null;
  // An override naming a tab that has since been renamed or removed is stale,
  // and honouring it would show nothing. Checked here rather than at the call
  // site because the labels are what makes it answerable.
  const chosen = override && labels.includes(override.name) ? override : undefined;
  if (variable === undefined) return chosen ? chosen.name : first;
  const now = asTabName(variable, labels);
  if (chosen && chosen.against === now) return chosen.name;
  return now ?? first;
}
