/**
 * The Widget setup tab's shape (Foundry `workshop` p.65-67).
 *
 * > "The core configuration options of a widget live within the Widget setup
 * > tab. This is where a module builder will configure the input and output
 * > variables of a widget (that is, the data that initially populates a widget
 * > and, when applicable, the data that is then produced and output by the
 * > widget) as well as any additional configuration and display options."
 * > (p.65)
 *
 * **Variables first, then the configuration they make sense of.** Foundry's
 * own worked example is a Filter List: the Object Set input comes first, the
 * filter options come second, and the Filter Output comes last - and the order
 * is not decoration. p.66 says the middle section "is revealed in more detail
 * once the Object Set is populated", because a list of properties to filter on
 * is a question nobody can answer before something has said which object set
 * the properties belong to.
 *
 * So the panel has three slots and one rule:
 *
 * * **Inputs** - what populates the widget. Always shown; they are the first
 *   decision.
 * * **Configuration** - everything the inputs make answerable. Hidden until the
 *   inputs it depends on are bound.
 * * **Outputs** - what the widget produces for other widgets to read.
 *
 * The rule lives here rather than in each panel because "shown when" is the
 * one part somebody can get wrong in a way nothing reports: configuration
 * revealed too early is a form full of empty dropdowns, and revealed too late
 * is a widget that looks unfinishable.
 */

/** One thing the configuration waits on: a single input, or a set of inputs
 * any one of which will do.
 *
 * **The alternative is not a convenience.** Every object-set widget takes
 * *either* a bound object set variable *or* an object type picked directly -
 * p.65's "the data that initially populates a widget", arrived at two ways.
 * Treating those as two separate requirements would mean a widget could never
 * reveal its configuration, because binding either one leaves the other
 * empty by design. §178 converted three widgets that happen to have a single
 * input and did not need this; the first widget with a choice does.
 */
export type SetupRequirement = string | readonly string[];

function bound(
  bindings: Readonly<Record<string, string | null | undefined>>,
  name: string,
): boolean {
  const value = bindings[name];
  return typeof value === "string" && value.trim().length > 0;
}

function satisfied(
  bindings: Readonly<Record<string, string | null | undefined>>,
  requirement: SetupRequirement,
): boolean {
  return typeof requirement === "string"
    ? bound(bindings, requirement)
    // An empty alternative is *not* satisfied - it would mean "any of
    // nothing", and reading that as ready would reveal a configuration whose
    // inputs somebody forgot to name. `some` on an empty array is already
    // false, so that falls out rather than needing a guard: an earlier version
    // wrote `requirement.length > 0 &&` in front of this, and mutation testing
    // showed it changed no behaviour at all. Two spellings of one rule, and
    // the redundant one is the one that can drift.
    : requirement.some((name) => bound(bindings, name));
}

/** Whether a widget's configuration section can be answered yet.
 *
 * `required` names the input bindings the configuration depends on - a string
 * for one that must be bound, or an array for a choice where any one will do.
 * Empty means "nothing to wait for", which is the common case and must stay
 * permissive: a widget with no inputs whose configuration never appeared would
 * be a widget nobody can set up.
 */
export function configReady(
  bindings: Readonly<Record<string, string | null | undefined>>,
  required: readonly SetupRequirement[],
): boolean {
  return required.every((requirement) => satisfied(bindings, requirement));
}

/** "a", "a and b", "a, b and c" - and the same shapes with "or".
 *
 * **Written once because both branches below need it**, which only became
 * obvious when a widget turned up with three alternatives. The choice arm used
 * to join with a plain `" or "`, which reads fine for the two the Object table
 * has ("a set or a type") and badly for the Chart's three ("a series or a set
 * or a dataset") - while the all-of arm three lines below had the comma form
 * all along. One rule, two conjunctions.
 */
function joined(names: readonly string[], conjunction: "and" | "or"): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} ${conjunction} ${names[names.length - 1]}`;
}

/** What to say in place of the configuration that is not ready yet.
 *
 * Naming the input rather than saying "configure this widget first" is the
 * whole value: p.66's example has one input, but a widget with three would
 * otherwise leave somebody guessing which of them is holding the rest back.
 */
export function configWaitingFor(
  bindings: Readonly<Record<string, string | null | undefined>>,
  required: readonly SetupRequirement[],
  labels: Readonly<Record<string, string>> = {},
): string | null {
  const missing = required.filter(
    (requirement) => !satisfied(bindings, requirement),
  );
  if (!missing.length) return null;
  // A choice reads as a choice: "an object set or an object type", because
  // naming only the first would send somebody to fill in a field they do not
  // need and leave the one they do.
  const named = missing.map((requirement) =>
    typeof requirement === "string"
      ? labels[requirement] ?? requirement
      : joined(requirement.map((name) => labels[name] ?? name), "or"),
  );
  return `Pick ${joined(named, "and")} first — the rest depends on it.`;
}

/** The order p.65 gives, as data rather than as the order somebody happened to
 * write the JSX in.
 *
 * Exported so the panel and its tests agree about it without either one
 * restating it. */
export const SETUP_SECTIONS = ["inputs", "configuration", "outputs"] as const;

export type SetupSection = (typeof SETUP_SECTIONS)[number];

export const SECTION_LABELS: Record<SetupSection, string> = {
  inputs: "Inputs",
  configuration: "Configuration",
  outputs: "Outputs",
};

/** p.65's own words for what each section is, short enough for a panel.
 *
 * Kept beside the labels because the distinction between an input and an
 * output is the thing a module builder is learning the first few times, and
 * "the data that initially populates a widget" versus "the data that is then
 * produced" is Foundry's own way of putting it. */
export const SECTION_HINTS: Record<SetupSection, string> = {
  inputs: "What populates this widget",
  configuration: "How it behaves, once its inputs are set",
  outputs: "What it produces for other widgets to read",
};
