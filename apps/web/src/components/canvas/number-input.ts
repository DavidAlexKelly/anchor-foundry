/** p.468's Numeric Input: what the viewer types, and what the variable holds.
 *
 * > "**Show grouping**: If toggled on, formats the numeric input with a comma
 * > style thousands separator.
 * >
 * > **Unit suffix**: If toggled on, displays a read-only suffix in the
 * > right-hand side of the widget's input field. The suffix can be text, an
 * > icon of choice, or a percent sign. **If the percent sign is selected, the
 * > output variable of the widget will be the user-entered value divided by 100
 * > to convert the value to percentage form.**" (p.468)
 *
 * ---
 *
 * **The percent sentence is why this is a module and not four lines in a
 * component** (decision 0011). It makes the displayed value and the stored
 * value different numbers, for one setting, in one direction — so every
 * conversion has to happen in exactly one place or the two drift, and the way
 * they drift is silent: a field showing `8.2` over a variable holding `0.082`
 * looks correct from either side alone.
 *
 * Three things this gets right that a naive `Number(text)` does not:
 *
 *   - **Empty is `null`, not `0`.** They are different answers. A numeric input
 *     nobody has touched has no value; one somebody typed `0` into has the
 *     value zero, and a filter reading the second should not behave like the
 *     first.
 *   - **A half-typed number is not a number yet.** `-`, `1.`, `1e` are all
 *     states of typing, and parsing them to `NaN` (or worse, to `1`) makes the
 *     field fight the person using it.
 *   - **Dividing by 100 is not exact in binary.** `8.2 / 100` is
 *     `0.08199999999999999`, and multiplying that back gives `8.199999999999999`
 *     — so a value that survives a round trip on paper does not survive one in
 *     a float. Both directions round to a fixed number of significant digits,
 *     which is what makes `toStored`/`toDisplay` an actual round trip.
 */

/** p.468's "The suffix can be text, an icon of choice, or a percent sign."
 *
 * `percent` is listed here beside the other two because that is where p.468
 * puts it — it is a *suffix choice*, and the arithmetic is a consequence of
 * choosing it rather than a setting of its own. Modelling it as a separate
 * "divide by 100" toggle would let an author have one without the other, which
 * p.468 does not offer and which would put an unlabelled percentage on screen.
 */
export type SuffixKind = "none" | "text" | "percent";

export interface NumberFormat {
  grouping?: boolean;
  suffix?: SuffixKind;
}

/** Enough digits that no realistic entry is truncated, few enough that the
 * float noise from ÷100 and ×100 is rounded away. 12 is chosen against the
 * worst case that matters: a percentage typed to two decimals over a value in
 * the billions still has room. */
const SIGNIFICANT = 12;

function round(value: number): number {
  // `toPrecision` then back through `Number`, so `0.08199999999999999` becomes
  // `0.082` and `1234567` stays `1234567` rather than becoming `1.234567e6`.
  return Number(Number(value).toPrecision(SIGNIFICANT));
}

/** Whether `text` is on the way to being a number rather than finished.
 *
 * These are the states a field passes through while somebody types, and each
 * one has to be left alone: committing them would either clear what they are
 * typing or commit a different number than the one they are halfway through.
 */
export function isPartial(text: string): boolean {
  const t = text.trim();
  if (t === "" || t === "-" || t === "+") return true;
  // A trailing separator: "1." on the way to "1.5".
  if (/^[+-]?\d*\.$/.test(t)) return true;
  // Exponent notation mid-flight: "1e", "1e-".
  if (/[eE][+-]?$/.test(t)) return true;
  return false;
}

/** What the viewer typed → what the variable holds.
 *
 * `null` for an empty field and for anything that is not a number, which are
 * the same answer to the only question the variable can hold: there is no
 * value here. A half-typed entry is `undefined` instead — **a third answer,
 * and the distinction is load-bearing**: `null` means "clear the variable",
 * `undefined` means "do not write anything yet", and collapsing them makes a
 * field clear the variable on the keystroke between `1` and `1.5`.
 */
export function toStored(text: string, format: NumberFormat = {}): number | null | undefined {
  if (isPartial(text)) return text.trim() === "" ? null : undefined;
  // Grouping separators come back in: the field shows them, so the field can
  // be edited with them in place.
  const cleaned = text.trim().replace(/,/g, "");
  if (!/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(cleaned)) return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value)) return null;
  return format.suffix === "percent" ? round(value / 100) : round(value);
}

/** What the variable holds → what the field shows.
 *
 * The inverse of `toStored` for every value `toStored` can produce, which is
 * the property the tests beside this module assert directly rather than by
 * example: a widget where typing a number and reading it back gives a
 * different number is a widget that edits its own data.
 */
export function toDisplay(value: unknown, format: NumberFormat = {}): string {
  if (value === null || value === undefined || value === "") return "";
  const raw = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(raw)) return "";
  const shown = round(format.suffix === "percent" ? raw * 100 : raw);
  if (!format.grouping) return String(shown);
  return group(shown);
}

/** p.468's "comma style thousands separator", applied to the integer part only.
 *
 * Hand-rolled rather than `toLocaleString`, and the reason is not preference:
 * `toLocaleString` follows the *viewer's* locale, so the same app would show
 * `1,234.5` to one reader and `1.234,5` to another while the variable held one
 * number. p.468 says "comma style", which is a format, not a localisation.
 */
function group(value: number): string {
  const text = String(value);
  // Exponent form has no thousands to separate, and inserting commas into one
  // produces something that is not a number at all.
  if (text.includes("e") || text.includes("E")) return text;
  const [whole, fraction] = text.split(".");
  const sign = whole!.startsWith("-") ? "-" : "";
  const digits = sign ? whole!.slice(1) : whole!;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction === undefined ? `${sign}${grouped}` : `${sign}${grouped}.${fraction}`;
}

/** p.468's "Include option to reset to default value… a button on the widget
 * for clearing out the input field."
 *
 * Offered only when there is something to clear. A reset button over an empty
 * field is a control that does nothing, which reads as a broken one.
 */
export function canReset(value: unknown): boolean {
  return value !== null && value !== undefined && value !== "";
}

/** What the suffix shows, or `null` for none.
 *
 * The percent sign is the string `%` rather than a flag the component branches
 * on, so the render has one path: p.468's three suffix kinds differ in what
 * they display and in nothing else about the markup.
 */
export function suffixText(format: NumberFormat, text: string | null | undefined): string | null {
  if (format.suffix === "percent") return "%";
  if (format.suffix === "text") {
    const trimmed = (text ?? "").trim();
    return trimmed === "" ? null : trimmed;
  }
  return null;
}
