/** Style formatting for pages, sections and widgets (Foundry `workshop` p.57-62).
 *
 * > "Workshop offers control over various style formatting settings… Configuration
 * > options include header formatting, background colors, border styles, and
 * > more. These options are available at the page, section, and widget levels."
 * > (p.57)
 *
 * Unglamorous, and most of the distance between "a canvas" and "looks like
 * Workshop". Almost all of it is a value written into a style attribute - which
 * is exactly why it belongs in a pure module with its own tests rather than in
 * three settings panels: the values are p.62's own numbers, and a panel that
 * quietly used 20px where the page says 24 would look right and be wrong.
 *
 * **The one rule rather than a value** is p.59-60's brightness switch:
 *
 * > "When a custom background color is applied to a section, widgets within
 * > that section automatically switch between light and dark mode based on the
 * > brightness of the background, ensuring text and controls remain legible."
 *
 * That is a decision about a colour, not a colour, and it is the thing here
 * that can be wrong in a way nobody notices until a module is unreadable.
 *
 * **Two divergences, named rather than implied.** There is no dark-mode preset
 * ladder: p.58 offers "five preset shades for both light mode and dark mode",
 * and this platform has one theme, so a dark ladder would be five swatches
 * that look wrong on every page they appear on. Adding a dark theme is a
 * platform-wide decision and not Workshop's to make. And there are no
 * Blueprint colour shortcuts (p.58, p.59), because Blueprint is Palantir's own
 * design system and is not a dependency here; a custom hex reaches the same
 * colours by typing them.
 */

/** p.58's presets, as a ladder from the page's own paper to its strongest rule.
 *
 * Named by depth rather than by colour so a future dark ladder can reuse the
 * names, and drawn from the tokens the rest of the platform already uses -
 * a sixth palette nobody else shares is how a canvas stops looking like the
 * product it sits in. */
export const BACKGROUND_PRESETS = {
  transparent: "",
  "shade-1": "#ffffff",
  "shade-2": "#fafbfb",
  "shade-3": "#f1f4f6",
  "shade-4": "#e2e8ed",
  "shade-5": "#c3ced8",
} as const;

export type BackgroundPreset = keyof typeof BACKGROUND_PRESETS;

export const BACKGROUND_LABELS: Record<BackgroundPreset, string> = {
  transparent: "Transparent",
  "shade-1": "White",
  "shade-2": "Paper",
  "shade-3": "Shade",
  "shade-4": "Deeper",
  "shade-5": "Deepest",
};

/** p.62's five padding options, with p.62's own numbers.
 *
 * `[top/bottom, left/right]`. Regular and Large are *not* square, which is the
 * detail worth encoding here rather than in a panel: "24 pixels of top/bottom
 * padding and 48 pixels of left/right padding" is a sentence somebody has to
 * read carefully once, and a single number per option is the shape that quietly
 * loses it. */
export const PADDINGS = {
  none: [0, 0],
  compact: [16, 16],
  regular: [24, 48],
  large: [40, 62],
} as const;

export type PaddingName = keyof typeof PADDINGS | "custom";

export const PADDING_LABELS: Record<PaddingName, string> = {
  none: "No padding",
  compact: "Compact — 16px",
  regular: "Regular — 24 / 48px",
  large: "Large — 40 / 62px",
  custom: "Custom",
};

/** p.60's four border styles, "giving the appearance of different elevation
 * levels within a module". */
export const BORDERS = ["bordered", "shadow-outer", "shadow-inner", "borderless"] as const;

export type BorderName = (typeof BORDERS)[number];

export const BORDER_LABELS: Record<BorderName, string> = {
  bordered: "Bordered",
  "shadow-outer": "Outer drop shadow",
  "shadow-inner": "Inner shadow",
  borderless: "Borderless",
};

/** The style props a page, section or widget can carry.
 *
 * Every one is optional and every one falls back to what the canvas did before
 * this existed, so a module saved by an older builder renders unchanged - the
 * whole corpus predates these props.
 */
export interface StyleProps {
  background?: string | null;
  padding?: PaddingName | null;
  /** Only read when `padding` is `custom`: `[top/bottom, left/right]`. */
  customPadding?: readonly [number, number] | null;
  border?: BorderName | null;
}

/** The CSS colour a background prop means, or `null` for transparent.
 *
 * Takes a preset name *or* a custom hex (p.59: "apply a custom hex color to
 * section and page backgrounds"), because the two arrive through one control
 * and separating them into two props is how a section ends up with both set
 * and nobody able to say which won.
 *
 * **Anything else passes through untouched**, which is compatibility rather
 * than looseness: a Container's `background` has been a free-text CSS colour
 * since the first canvas, and every module in the corpus that set one is
 * holding a value this function did not invent. Rejecting `red` in the name of
 * validation would blank a background somebody is looking at.
 */
export function resolveBackground(value: string | null | undefined): string | null {
  if (!value) return null;
  if (value in BACKGROUND_PRESETS) {
    return BACKGROUND_PRESETS[value as BackgroundPreset] || null;
  }
  if (isHex(value)) return normaliseHex(value);
  const raw = value.trim();
  return raw === "transparent" || raw === "" ? null : raw;
}

function isHex(value: string): boolean {
  return /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value.trim());
}

/** `#abc` and `abc` both mean `#aabbcc`. Accepting the short form and the
 * missing hash is not politeness: this value is typed by hand, and a picker
 * that silently ignored `abc` would look like a broken control. */
function normaliseHex(value: string): string {
  const raw = value.trim().replace(/^#/, "").toLowerCase();
  const full = raw.length === 3 ? raw.split("").map((c) => c + c).join("") : raw;
  return `#${full}`;
}

/** How bright a colour is, 0 (black) to 1 (white).
 *
 * WCAG's relative luminance, which linearises each channel before weighting
 * it. The naive average of the three channels is the tempting shortcut and it
 * is wrong in the direction that matters: it calls a saturated blue and a
 * saturated yellow equally bright, and only one of them can carry dark text.
 */
export function relativeLuminance(hex: string): number {
  const value = normaliseHex(hex).slice(1);
  const channels = [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) =>
    c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  ) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG's own crossover between "black text reads better" and "white text
 * reads better", derived from its contrast formula rather than guessed.
 *
 * Contrast against white is `1.05 / (L + 0.05)`; against black it is
 * `(L + 0.05) / 0.05`. They are equal at `L = sqrt(1.05 * 0.05) - 0.05`, which
 * is this number. A round 0.5 is the obvious threshold and it is far too high:
 * it would put white text on a mid-grey that black text reads better on.
 */
export const LIGHT_TEXT_BELOW = Math.sqrt(1.05 * 0.05) - 0.05;

/** p.59-60's rule: does this background need light text on it?
 *
 * `null`/transparent is not dark - a transparent section inherits whatever is
 * behind it, and claiming to know that colour is how a section flips to white
 * text over a white page.
 */
export function isDarkBackground(value: string | null | undefined): boolean {
  const colour = resolveBackground(value);
  // Only a colour whose brightness can actually be *computed* counts. A
  // free-text `red` or `var(--panel)` is a real background this cannot measure,
  // and guessing would flip a section's text on a value nobody read.
  if (colour === null || !isHex(colour)) return false;
  return relativeLuminance(colour) <= LIGHT_TEXT_BELOW;
}

/** The padding a style means, as `[top/bottom, left/right]` pixels. */
export function paddingFor(props: StyleProps): readonly [number, number] {
  const name = props.padding ?? "none";
  if (name === "custom") {
    const custom = props.customPadding;
    // A custom padding with nothing set is "none", not a crash and not a
    // silent fall back to Regular - the builder chose Custom and left it, and
    // the honest reading of that is no padding yet.
    return [Math.max(0, custom?.[0] ?? 0), Math.max(0, custom?.[1] ?? 0)];
  }
  return PADDINGS[name] ?? PADDINGS.none;
}

/** What p.60's four border styles look like, in this platform's own tokens. */
function borderCss(border: BorderName): { border?: string; boxShadow?: string } {
  switch (border) {
    case "bordered":
      return { border: "1px solid var(--line)" };
    case "shadow-outer":
      return { border: "1px solid var(--line)", boxShadow: "0 4px 14px rgba(22, 35, 47, 0.12)" };
    case "shadow-inner":
      return { border: "1px solid var(--line)", boxShadow: "inset 0 2px 6px rgba(22, 35, 47, 0.12)" };
    case "borderless":
      return {};
  }
}

/** The whole style block as inline CSS.
 *
 * Inline rather than a class per combination: background is an arbitrary hex,
 * so at least one of these values can never be enumerated into a stylesheet,
 * and splitting the block across both mechanisms is how one half of it ends up
 * applying and the other silently not.
 */
export function styleFor(props: StyleProps): React.CSSProperties {
  const background = resolveBackground(props.background);
  const [block, inline] = paddingFor(props);
  return {
    ...(background ? { background } : {}),
    ...(block || inline ? { padding: `${block}px ${inline}px` } : {}),
    ...(props.border ? borderCss(props.border) : {}),
    ...(props.border && props.border !== "borderless" ? { borderRadius: "var(--radius)" } : {}),
  };
}

/** The value for the `data-scheme` attribute a styled element carries, or
 * `undefined` when it should not carry one.
 *
 * **An attribute rather than a set of colours** because p.59-60 is about
 * everything *inside*: "widgets within that section automatically switch". One
 * attribute, and the stylesheet redefines the ink and line tokens beneath it,
 * so a widget written years before this feature inherits legible colours
 * without knowing the feature exists. Colouring the widgets individually would
 * mean touching every one of them, and missing one would be invisible until
 * somebody picked a dark background.
 */
export function schemeFor(props: StyleProps): "dark" | undefined {
  return isDarkBackground(props.background) ? "dark" : undefined;
}
