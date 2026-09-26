/**
 * A section's header, and p.58's three ways of drawing it (§473).
 *
 * > "Header formatting options can be added when the header is enabled on a
 * > section. There are three available: Block: The section header is in its
 * > own container above the body. Contained: The section header appears to be
 * > contained within the body area. Floating: The section header appears above
 * > the body area and is visually on the background of the parent section."
 * > (p.58)
 *
 * The header itself is p.13's "toggle on the options for Section Header", with
 * p.15's Title and icon and p.28's Description: "Use subheadings to provide
 * context for section headers as a rendered Description".
 */

export const HEADER_STYLES = {
  block: "Block",
  contained: "Contained",
  floating: "Floating",
} as const;
export type HeaderStyle = keyof typeof HEADER_STYLES;

/** Block unless it says otherwise: a header in its own bar is what reads as a
 * header at all, where the other two are refinements of where it sits. */
export function headerStyleOf(raw: unknown): HeaderStyle {
  return typeof raw === "string" && Object.hasOwn(HEADER_STYLES, raw) ? (raw as HeaderStyle) : "block";
}

/**
 * Where the section's own style block goes. **Floating moves it to the body**:
 * p.58's floating header sits "visually on the background of the parent
 * section", so the section box - its background, border and padding - has to
 * start below the header rather than around it. The other two draw the box
 * around both.
 */
export function styleTarget(showHeader: boolean, style: HeaderStyle): "section" | "body" {
  return showHeader && style === "floating" ? "body" : "section";
}

/**
 * Where the section's padding goes, which for Block is the body: p.58's
 * "in its own container above the body" is a bar the width of the box, and
 * padding around the whole section would inset it like the body's contents.
 */
export function paddingTarget(showHeader: boolean, style: HeaderStyle): "section" | "body" {
  return showHeader && style !== "contained" ? "body" : "section";
}
