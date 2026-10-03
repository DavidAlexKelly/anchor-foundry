/** p.62's **Inner section style** (§704).
 *
 * > "Inner section style: Optionally select one of various pre-defined section
 * > styles to be applied to all children sections" (p.62)
 *
 * The list itself is a picture on p.62 rather than text, which is why the row
 * sat at ○ for so long: the extracted PDF stops at the colon. Rendered, it is
 * eight swatches, each a "Title" over a body - **Classic**, **Classic
 * elevated**, **Classic gray**, **Minimal**, **Minimal elevated**, **Minimal
 * ghost**, **Muted white** and **Muted gray**.
 *
 * **Every one of them is a combination of three settings a section already
 * has**, which is what makes them presets rather than a fourth styling system:
 * p.58's header format (the Classic swatches draw the title in a bar divided
 * from the body, Block; the Minimal ones draw it on the parent's background
 * above a box, Floating; the Muted ones inside the box with no rule,
 * Contained), p.60's border (the elevated ones cast a shadow, the Muted ones
 * an inner one, the ghost none) and p.58's background (white, a grey body, or
 * the ghost's nothing).
 *
 * **A preset fills what a child section leaves unset, and nothing it has
 * set.** "Applied to" could also mean overwriting, but a section somebody
 * gave a red background on purpose and that came back white because its
 * parent was restyled has lost work without being asked. A section built
 * before §704 stored `headerStyle: "block"` as a default rather than a choice,
 * so it keeps Block under a Minimal parent; its settings say a preset reaches
 * it and offer to clear its own three values (`ownLook`).
 *
 * **Children, not descendants**: the sections directly inside the page or
 * section that names the style. That is p.62's word, and it is also what lets
 * two levels differ - a page of Classic panels each holding Minimal cards is
 * the page naming one and each panel the other.
 */

import type { BorderName } from "./style";
import type { HeaderStyle } from "./section-header";

export interface InnerSectionStyle {
  label: string;
  headerStyle: HeaderStyle;
  border: BorderName;
  /** The section's box. */
  background: string;
  /** The body under a Block bar, when it differs from the box: Classic gray
   * keeps a white bar over a grey body. */
  body?: string;
}

export const INNER_SECTION_STYLES = {
  classic: { label: "Classic", headerStyle: "block", border: "bordered", background: "shade-1" },
  "classic-elevated": {
    label: "Classic elevated", headerStyle: "block", border: "shadow-outer", background: "shade-1",
  },
  "classic-gray": {
    label: "Classic gray", headerStyle: "block", border: "bordered", background: "shade-1",
    body: "shade-3",
  },
  minimal: { label: "Minimal", headerStyle: "floating", border: "bordered", background: "shade-1" },
  "minimal-elevated": {
    label: "Minimal elevated", headerStyle: "floating", border: "shadow-outer",
    background: "shade-1",
  },
  "minimal-ghost": {
    label: "Minimal ghost", headerStyle: "floating", border: "borderless", background: "transparent",
  },
  "muted-white": {
    label: "Muted white", headerStyle: "contained", border: "shadow-inner", background: "shade-1",
  },
  "muted-gray": {
    label: "Muted gray", headerStyle: "contained", border: "shadow-inner", background: "shade-3",
  },
} as const satisfies Record<string, InnerSectionStyle>;

export type InnerSectionStyleName = keyof typeof INNER_SECTION_STYLES;

/** The preset a stored value names, or `null` for none - including a name
 * this build does not know, which draws the children as their own settings
 * say rather than failing the page. */
export function innerStyleOf(raw: unknown): InnerSectionStyle | null {
  return typeof raw === "string" && Object.hasOwn(INNER_SECTION_STYLES, raw)
    ? INNER_SECTION_STYLES[raw as InnerSectionStyleName]
    : null;
}

/** A section's three own values, as stored. `null`/`undefined` is unset; an
 * empty background is unset too, because the Background control never writes
 * one (its Transparent writes `"transparent"`, which is a choice). */
export interface OwnLook {
  headerStyle?: string | null;
  border?: BorderName | null;
  background?: string | null;
}

function unset(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

/** What a section draws with: its own value where it has one, the inherited
 * preset's where it does not, and the section's old defaults (Block, no
 * border, no background) where there is neither. `body` is the preset's body
 * background, and only when the box's background is the preset's too - a
 * section that chose its own colour has chosen the body's with it. */
export function sectionLook(own: OwnLook, inherited: unknown): {
  headerStyle: string | null | undefined;
  border: BorderName | null;
  background: string | null;
  body: string | null;
} {
  const preset = innerStyleOf(inherited);
  const ownBackground = !unset(own.background);
  return {
    headerStyle: unset(own.headerStyle) ? preset?.headerStyle ?? null : own.headerStyle,
    border: unset(own.border) ? preset?.border ?? null : own.border!,
    background: ownBackground ? own.background! : preset?.background ?? null,
    body: ownBackground ? null : preset?.body ?? null,
  };
}

/** Which of a section's own values hide the preset reaching it - what the
 * settings' "use the inner section style" would clear. Empty when there is
 * no preset, since then nothing is hidden. */
export function ownLook(own: OwnLook, inherited: unknown): (keyof OwnLook)[] {
  if (innerStyleOf(inherited) === null) return [];
  return (["headerStyle", "border", "background"] as const).filter((key) => !unset(own[key]));
}
