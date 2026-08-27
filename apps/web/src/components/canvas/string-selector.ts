/** p.459–461's String Selector: the selection/display matrix, and what each
 * combination configures.
 *
 * > "**Option generation** — Static: Manually enter in and reorder option
 * > values… Dynamic: Select an existing or create a new string array variable to
 * > be used to generate options.
 * >
 * > **Selection**: The widget can be set to either allow for a single option
 * > selection or multiple option selections. **Selected value**: Output variable
 * > of the widget… **If the selection is set to Single, the output variable will
 * > be a string variable. If the selection is set to Multiple, the output
 * > variable will be a string array variable.**
 * >
 * > **Selection display**: If the selection is set to Single, the widget may be
 * > displayed as either a dropdown or as radio buttons… If the selection is set
 * > to Multiple, the widget may be displayed as either a dropdown or as
 * > checkboxes." (p.461)
 *
 * ---
 *
 * **The selection changes what the variable holds**, which is the same shape as
 * p.468's percent rule and the same reason this widget could not stay a mode of
 * the generic parameter control (decision 0011). Single writes a string;
 * Multiple writes an array. So a binding made under one selection is *invalid*
 * under the other — not merely odd — and something has to say so.
 *
 * **The display options are not free either.** Radio buttons exist only under
 * Single and checkboxes only under Multiple, so `display` is not a setting the
 * widget carries independently: it is a setting *within* a selection, and a
 * document can arrive naming a combination that is not one. Every read of it
 * goes through `displayOf`, which resolves an illegal pair rather than trusting
 * it — the alternative is a widget that renders radio buttons which cannot
 * express the value the variable is meant to hold.
 *
 * That makes this the matrix version of the shape §190, §191, §193, §200 and
 * §203 were each caught by: a table that has to stay complete and consistent,
 * with a test that walks it rather than a second copy of it.
 *
 * **p.444's *Checkbox* row is here, not elsewhere.** p.461 shows checkboxes are
 * a *display of a multiple selection*, not a widget of their own.
 */

export type Selection = "single" | "multiple";

export interface DisplayMode {
  label: string;
  /** p.461's per-display placeholder default. The two dropdowns have different
   * ones — "Select an option..." for single, "Search options..." for multiple —
   * which is p.461 being precise rather than inconsistent: one picks, the other
   * searches. */
  placeholder: string | null;
  /** p.461's "Radio buttons layout" / "Checkboxes layout": vertical,
   * horizontal, or a grid with a column count. Dropdowns have no layout. */
  hasLayout: boolean;
  /** p.461's "Disable clearing of dropdown options", offered on the single
   * dropdown only. */
  hasClearing: boolean;
}

/** The matrix. Keyed by selection first, because that is the setting p.461
 * makes primary and the one that decides what the variable holds. */
export const DISPLAYS: Record<Selection, Record<string, DisplayMode>> = {
  single: {
    dropdown: {
      label: "Dropdown",
      placeholder: "Select an option...",
      hasLayout: false,
      hasClearing: true,
    },
    radio: {
      label: "Radio buttons",
      placeholder: null,
      hasLayout: true,
      hasClearing: false,
    },
  },
  multiple: {
    dropdown: {
      label: "Dropdown",
      // p.461: "By default, 'Search options...' will be used".
      placeholder: "Search options...",
      hasLayout: false,
      hasClearing: false,
    },
    checkboxes: {
      label: "Checkboxes",
      placeholder: null,
      hasLayout: true,
      hasClearing: false,
    },
  },
};

export const SELECTIONS: Record<Selection, { label: string; kind: "string" | "array" }> = {
  single: { label: "Single", kind: "string" },
  multiple: { label: "Multiple", kind: "array" },
};

/** p.461's "the output variable will be a string variable… will be a string
 * array variable".
 *
 * Read by the settings panel to decide which variables to offer, and it is the
 * whole reason changing the selection has to clear the binding: the variable
 * that was legal a moment ago is now the wrong kind, and the server would
 * refuse the document with a message about a widget the author did not touch.
 */
export function outputKind(selection: unknown): "string" | "array" {
  return selectionOf(selection) === "multiple" ? "array" : "string";
}

export function selectionOf(raw: unknown): Selection {
  return raw === "multiple" ? "multiple" : "single";
}

/** The displays p.461 allows for a selection, in the order it lists them. */
export function displaysFor(selection: unknown): string[] {
  return Object.keys(DISPLAYS[selectionOf(selection)]!);
}

/** Resolve a (selection, display) pair to one that exists.
 *
 * **A document can name a pair p.461 does not have** — most obviously by
 * flipping the selection while `radio` is saved, which is one click in a panel
 * and leaves `multiple`/`radio` behind. Falling back to the selection's first
 * display draws something that can express the value; trusting the pair draws
 * radio buttons over a variable holding a list.
 */
export function displayOf(selection: unknown, raw: unknown): string {
  const allowed = DISPLAYS[selectionOf(selection)]!;
  return typeof raw === "string" && Object.hasOwn(allowed, raw)
    ? raw
    : Object.keys(allowed)[0]!;
}

export function modeOf(selection: unknown, display: unknown): DisplayMode {
  return DISPLAYS[selectionOf(selection)]![displayOf(selection, display)]!;
}

/** p.461's placeholder: the display's default unless the author set one. */
export function placeholderOf(selection: unknown, display: unknown, custom: unknown): string {
  const set = typeof custom === "string" ? custom.trim() : "";
  if (set) return set;
  return modeOf(selection, display).placeholder ?? "";
}

// ---- options ---------------------------------------------------------------

export type OptionSource = "static" | "dynamic";

export function sourceOf(raw: unknown): OptionSource {
  return raw === "dynamic" ? "dynamic" : "static";
}

/** p.461's two ways of generating options.
 *
 * Static options are a list the author typed; dynamic ones come from a string
 * array variable. Both end up as the same list of strings, so everything below
 * this line stops caring which it was — the difference belongs to the panel.
 *
 * **Blank entries are dropped and duplicates collapse**, keeping first
 * position. An option with no text is a row somebody left empty rather than a
 * choice, and two identical options are one choice drawn twice: with a `<select>`
 * they are indistinguishable to the viewer, and with radio buttons they would
 * share a name and fight over which is checked.
 */
export function optionsOf(source: unknown, staticList: unknown, dynamic: unknown): string[] {
  const raw = sourceOf(source) === "dynamic" ? dynamic : staticList;
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const entry of raw) {
    if (typeof entry !== "string") continue;
    const text = entry.trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
  }
  return out;
}

// ---- the value -------------------------------------------------------------

/** What the widget currently holds, as a list, whatever the selection is.
 *
 * One shape for the render: a single selection is a list of nought or one. The
 * alternative is every drawing branch asking the selection again, and the
 * checkbox arm and the radio arm differing in a way nothing checks.
 *
 * **It always returns a fresh array** — `filter` and `[value]` both allocate —
 * and `pick` below relies on that: nothing downstream can reach the caller's
 * list, so the copy in `pick` is clarity rather than defence. §204's harness
 * proved it by mutating that copy into a `push` and finding nothing could tell.
 */
export function chosenOf(selection: unknown, value: unknown): string[] {
  if (selectionOf(selection) === "multiple") {
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  }
  return typeof value === "string" && value !== "" ? [value] : [];
}

/** What to store after the viewer picks, given what was already chosen.
 *
 * Single replaces; multiple toggles. `null` for an empty single selection and
 * `[]` for an empty multiple one — **not `null` for both**, because the kinds
 * differ: a `string` variable with no value is empty, and an `array` variable
 * with no value is an empty list, and a derivation reading the second would
 * break on `null` where it handles `[]` perfectly well.
 */
export function pick(
  selection: unknown,
  value: unknown,
  option: string,
): string | string[] | null {
  if (selectionOf(selection) !== "multiple") {
    // Clicking the chosen option again clears it - p.461's "clearing of the
    // selected dropdown option", which `allowClearing` may forbid; the caller
    // decides whether to offer that, this decides what it means.
    return chosenOf(selection, value)[0] === option ? null : option;
  }
  const chosen = chosenOf(selection, value);
  return chosen.includes(option)
    ? chosen.filter((c) => c !== option)
    : [...chosen, option];
}

// ---- layout ----------------------------------------------------------------

export type LayoutName = "vertical" | "horizontal" | "grid";

export const LAYOUTS: Record<LayoutName, string> = {
  vertical: "Vertical",
  horizontal: "Horizontal",
  grid: "Grid",
};

export const MIN_COLUMNS = 2;
export const MAX_COLUMNS = 8;
export const DEFAULT_COLUMNS = 3;

export function layoutOf(raw: unknown): LayoutName {
  return typeof raw === "string" && Object.hasOwn(LAYOUTS, raw)
    ? (raw as LayoutName)
    : "vertical";
}

export function columnsOf(raw: unknown): number {
  // Absence before coercion — `Number(null)` and `Number("")` are `0`, which is
  // finite, so coercing first reads "not set" as "no columns" (§203).
  if (raw === null || raw === undefined || raw === "") return DEFAULT_COLUMNS;
  const value = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(value)) return DEFAULT_COLUMNS;
  return Math.min(MAX_COLUMNS, Math.max(MIN_COLUMNS, Math.round(value)));
}

/** p.461's "vertically, horizontally, or in a grid formation with a specified
 * number of columns", as the grid-template a stylesheet cannot express without
 * knowing the count. */
export function layoutStyle(raw: unknown, columns: unknown): { gridTemplateColumns: string } {
  const layout = layoutOf(raw);
  if (layout === "vertical") return { gridTemplateColumns: "1fr" };
  if (layout === "horizontal") return { gridTemplateColumns: "repeat(auto-fit, minmax(0, max-content))" };
  return { gridTemplateColumns: `repeat(${columnsOf(columns)}, minmax(0, 1fr))` };
}
