/** p.465's Text Input: the formats it comes in, and what each one configures.
 *
 * > "**Placeholder**: Define placeholder text to be displayed in the input field
 * > when no text has been inputted by the user.
 * >
 * > **Format**: Set the format of the input field to a single line, a multi-line
 * > text area, or a Markdown editor.
 * >
 * > **Single line** — *Event on enter*: set event(s) to be triggered when the
 * > enter key is pressed.
 * > **Text area** — *Initial height*: set the initial height of the text input
 * > area." (p.465)
 *
 * ---
 *
 * **The format is not a styling choice; it decides which other settings exist.**
 * p.465 lists "event on enter" under Single line and "initial height" under Text
 * area, and the asymmetry is not editorial tidiness — in a text area the enter
 * key *inserts a newline*, so a widget that also fired an event on it would be
 * fighting the person typing into it. So the catalogue below carries what each
 * format has, the settings panel renders from the catalogue, and the widget asks
 * the catalogue rather than testing the format string in three places.
 *
 * That makes it the same shape as §190's parity row, §191's `REFERENCE_PROPS`,
 * §193's effect catalogue and §200's `PROP_DIRECTION`: a list that has to stay
 * complete, with a test that compares it against its subject rather than against
 * a second copy of itself.
 *
 * **Markdown is absent, deliberately.** p.465 lists three formats and p.466
 * describes the third as "a rich text editing experience powered by the same
 * editor used in Notepad" with a formatting toolbar and a raw/rich toggle. That
 * is an editor, not a format flag, and it belongs to the Markdown row in
 * `workshop.md`'s build order. Offering it here as a third option that rendered
 * a plain textarea would be the thing every catalogue in this codebase exists to
 * avoid: a choice that does not do what it says.
 */

export interface TextFormat {
  label: string;
  /** p.465's "Event on enter", which only Single line has — see above. */
  submitsOnEnter: boolean;
  /** p.465's "Initial height", which only Text area has. */
  hasHeight: boolean;
  /** Whether the field is a `<textarea>` rather than an `<input>`. */
  multiline: boolean;
}

export const TEXT_FORMATS: Record<string, TextFormat> = {
  line: { label: "Single line", submitsOnEnter: true, hasHeight: false, multiline: false },
  area: { label: "Text area", submitsOnEnter: false, hasHeight: true, multiline: true },
};

export type TextFormatName = keyof typeof TEXT_FORMATS;

/** p.465's default, and the answer for anything unrecognised.
 *
 * A saved document can name a format this build does not have — an app authored
 * against a later version, or one whose Markdown format arrives before its
 * editor does. Falling back to a single line renders *something the viewer can
 * type into*, which is the failure worth having: the alternative is a widget
 * that draws nothing and an app with a hole where a field was.
 */
export const DEFAULT_FORMAT: TextFormatName = "line";

export function formatOf(raw: unknown): TextFormatName {
  // `Object.hasOwn`, not `in`: `"constructor" in TEXT_FORMATS` is true for a
  // plain object, so a document naming it would resolve to a "format" that is
  // a function — and the widget would then read `.multiline` off it and get
  // `undefined`, which is a falsy answer to a question that was never asked.
  return typeof raw === "string" && Object.hasOwn(TEXT_FORMATS, raw) ? raw : DEFAULT_FORMAT;
}

export function settingsOf(raw: unknown): TextFormat {
  return TEXT_FORMATS[formatOf(raw)]!;
}

/** Whether pressing enter in this format should fire p.465's event.
 *
 * Asked of the catalogue rather than compared against `"line"` at the call
 * site, because the call site is the widget's keydown handler and a second
 * place that knows which formats submit is a second place to get it wrong when
 * Markdown lands.
 */
export function submitsOnEnter(raw: unknown): boolean {
  return settingsOf(raw).submitsOnEnter;
}

/** p.465's "Initial height", in rows.
 *
 * **Rows rather than pixels**, which is a divergence and a deliberate one:
 * p.465 does not say what the unit is, and a pixel height set by an author is
 * wrong the moment a viewer's font size differs from theirs. Rows scale with
 * the text they hold.
 */
export const MIN_ROWS = 2;
export const MAX_ROWS = 30;
export const DEFAULT_ROWS = 4;

export function rowsOf(raw: unknown): number {
  // **`Number(null)` and `Number("")` are both `0`**, and zero is finite — so
  // coercing first would read "not set" as "no rows at all" and clamp it to
  // the minimum. Absence is decided before any arithmetic.
  if (raw === null || raw === undefined || raw === "") return DEFAULT_ROWS;
  const value = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(value)) return DEFAULT_ROWS;
  // Rounded before clamping: `2.6` is an author dragging a control, and
  // truncating it to 2 rather than 3 loses the row they were asking for.
  return Math.min(MAX_ROWS, Math.max(MIN_ROWS, Math.round(value)));
}

/** What the viewer typed → what the variable holds.
 *
 * Empty is `null`, matching p.468's Numeric Input rather than storing `""`.
 * The two are not the same question: a `is_empty` transform answers `true` for
 * both, but a variable holding `""` has been *set to the empty string* while one
 * holding `null` has no value — and the difference shows up the moment somebody
 * reads it in a `concat` or writes it through an action.
 *
 * Whitespace is kept. A field where somebody typed two spaces holds two spaces:
 * trimming here would make the widget quietly disagree with what is on screen,
 * and a trim belongs in the transform that needs one.
 */
export function toStored(text: string): string | null {
  return text === "" ? null : text;
}

/** What the variable holds → what the field shows. */
export function toDisplay(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : String(value);
}
