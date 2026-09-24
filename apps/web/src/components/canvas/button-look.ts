/**
 * How a Button Group button looks (`workshop` p.486; §461).
 *
 * > "Button color: … You can choose either a preset "intent" with an associated
 * > color, or specify a custom color. Intent options and their associated
 * > colors include none, primary (blue), success (green), warning (amber), and
 * > danger (red). You can use the custom option to pick from a wider variety of
 * > color options, including setting a color using a hex code." (p.486)
 *
 * > "Minimal style: If enabled, this option removes the border from a button.
 * > If a color has been applied, the background color and text color of the
 * > button / menu item will be reversed … Tag style: … a more narrow tag
 * > styling. Large style: … increases the overall size of a button. Fill
 * > available horizontal space…" (p.486)
 *
 * Pure: the widget asks this for a class list and, for a custom colour, an
 * inline style, so every combination can be checked without a browser.
 */

export const INTENTS = ["none", "primary", "success", "warning", "danger", "custom"] as const;
export type Intent = (typeof INTENTS)[number];

export interface ButtonLookInput {
  intent?: string | null;
  /** The pre-§461 prop: primary, quiet or danger. Read when `intent` is not
   * set, so a button saved before p.486's intents existed looks as it did. */
  style?: string | null;
  customColour?: string | null;
  minimal?: boolean | null;
  tag?: boolean | null;
  large?: boolean | null;
  fill?: boolean | null;
}

export interface ButtonLook {
  className: string;
  style: Record<string, string>;
}

/** A custom colour, only when it is one: `#rgb` or `#rrggbb`. Anything else
 * would be written into a style attribute, and a style is not the place for
 * whatever somebody typed into a text box. */
export function customColourOf(value: unknown): string | null {
  return typeof value === "string" && /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value.trim())
    ? value.trim().toLowerCase()
    : null;
}

/** Which intent a button has: the one set, or the one its old `style` meant. */
export function intentOf(input: ButtonLookInput): Intent {
  const set = input.intent;
  if (typeof set === "string" && (INTENTS as readonly string[]).includes(set)) {
    // A custom intent with no usable colour is a button with no colour at
    // all, which is `none` - not a primary one, which is what it would get
    // from a class list that silently dropped the style.
    if (set === "custom" && !customColourOf(input.customColour)) return "none";
    return set as Intent;
  }
  if (input.style === "quiet") return "none";
  if (input.style === "danger") return "danger";
  return "primary";
}

export function buttonLook(input: ButtonLookInput): ButtonLook {
  const intent = intentOf(input);
  const classes = ["btn", `btn-intent-${intent}`];
  if (input.minimal) classes.push("btn-minimal");
  if (input.tag) classes.push("btn-tag");
  if (input.large) classes.push("btn-large");
  if (input.fill) classes.push("btn-fill");
  const style: Record<string, string> = {};
  const colour = intent === "custom" ? customColourOf(input.customColour) : null;
  if (colour) {
    // p.486's reversal, for a colour no class can know in advance: filled by
    // default, the colour as text on nothing when minimal.
    if (input.minimal) {
      style.color = colour;
      style.background = "transparent";
    } else {
      style.background = colour;
      style.borderColor = colour;
      style.color = readableOn(colour);
    }
  }
  return { className: classes.join(" "), style };
}

/** White or near-black, whichever reads on `hex`. The relative-luminance
 * threshold WCAG uses, so a pale custom colour does not get white text. */
export function readableOn(hex: string): string {
  const full = hex.length === 4
    ? `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}`
    : hex;
  const channel = (i: number) => {
    const c = parseInt(full.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  return luminance > 0.179 ? "#16232f" : "#ffffff";
}
