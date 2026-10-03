/**
 * An object type's icon and colour (§449; `object-link-types` p.15).
 *
 * > "**Icon:** Select the default icon to customize the icon and color of the
 * > object type; this icon and color will be displayed in user applications
 * > when a user views an object of this type."
 *
 * **An icon is a name from `lib/icons.ts` or one or two typed characters**
 * (§705). Until §705 it could only be the second - there was no icon set, so
 * an icon was an emoji or an initial, as a Page, a Button and §445's header
 * logo take one - and p.15's "Select the default icon" is the picker over the
 * first.
 *
 * **And a stored icon may be neither.** `object_types.icon` defaults to
 * `"cube"` and its column is 64 characters wide, because it was written to
 * hold a name from Foundry's set. `cube` is one of ours now; a name from
 * Foundry's set that is not is still read as a name rather than as text, and
 * the type's own initial is drawn instead - rendering it as its first two
 * letters would put part of a word nobody chose on every card. That is
 * `glyphFor`'s rule in `widgets.tsx` for a Button with no icon, reached from
 * the other side.
 *
 * **Deliberately not the same function as that one.** A canvas widget's icon
 * prop is *authored* as a glyph, so a long one there is a paste to be trimmed;
 * this one may be a name, which is a different thing to do with the same
 * input. Two rules, two reasons, said here so the next reader does not merge
 * them.
 */

import { type IconName, iconNamed } from "./icons";

/** How long an icon may be before it is read as a name rather than a glyph. */
export const MAX_GLYPH = 2;

/** Just enough of an object type to draw its mark. */
export interface Marked {
  display_name?: string;
  api_name?: string;
  icon?: string | null;
  colour?: string | null;
}

/** Whether a stored icon is a name rather than a glyph somebody typed -
 * one of ours or one from Foundry's set. */
export function isIconSetName(icon: string | null | undefined): boolean {
  const trimmed = (icon ?? "").trim();
  return trimmed.length > MAX_GLYPH;
}

/** The named icon to draw for this type (§705), or null when its icon is a
 * glyph, a blank, or a name this platform's set does not have. */
export function iconName(type: Marked): IconName | null {
  return iconNamed(type.icon) ? ((type.icon ?? "").trim() as IconName) : null;
}

/**
 * What to draw for this type as text, when `iconName` has no icon for it.
 *
 * **Never nothing.** A blank mark beside a name is a rendering fault to look
 * at; the type's own initial is at least true. `"?"` is the last resort, for
 * a type with no name at all — which the server refuses, so it is a shape the
 * browser holds rather than a state it expects.
 */
export function glyph(type: Marked): string {
  const chosen = (type.icon ?? "").trim();
  if (chosen && !isIconSetName(chosen)) return chosen;
  const named = (type.display_name ?? type.api_name ?? "").trim();
  return named ? [...named][0]!.toUpperCase() : "?";
}

/**
 * The colour behind it.
 *
 * Falls back to the theme's accent rather than to a colour of its own: a
 * default written in here is one that stops following the theme the moment the
 * theme changes, which is `titleColour`'s argument in the canvas header.
 */
export function swatch(type: Marked): string {
  const chosen = (type.colour ?? "").trim();
  return chosen || "var(--accent)";
}

/**
 * Why an icon will not be kept, or null.
 *
 * **Only about length**, because everything else is somebody's choice: an
 * emoji, a letter, a symbol, two letters. What this refuses is the paragraph
 * somebody pasted — which would be stored, read back as a name, and silently
 * drawn as an initial, so the field would look broken rather than full.
 */
export function iconProblem(icon: string): string | null {
  const trimmed = icon.trim();
  if (!trimmed || iconNamed(trimmed)) return null;
  if (isIconSetName(trimmed)) {
    return (
      `“${trimmed}” is not one of the icons here, so the type's first letter `
      + `is drawn. Choose an icon, or type one or two characters.`
    );
  }
  return null;
}

/** What the field says about a value that came from Foundry's icon set.
 *
 * Its own sentence rather than `iconProblem`'s, because it is not a problem:
 * the type was made before this platform had a control, the value is what was
 * stored, and the reader needs to know why the mark is a letter. */
export function storedNameNote(icon: string | null | undefined): string | null {
  if (!isIconSetName(icon) || iconNamed(icon)) return null;
  return (
    `“${(icon ?? "").trim()}” is an icon name from Foundry's set that this `
    + `platform does not draw — the type's first letter is drawn instead. `
    + `Choose an icon, or type one or two characters.`
  );
}

/**
 * What the field says beneath itself.
 *
 * **Which of the two sentences, decided here rather than at the control.**
 * They answer the same condition — the icon is a name rather than a glyph —
 * and differ only in who is responsible for it: a value that came with the
 * type is history to explain, and one somebody just pasted is a refusal. The
 * editor had them in a fallback chain and showed the refusal for every type
 * in the corpus, because `iconProblem` matched first on `"cube"`.
 *
 * `stored` is what the type holds. Equal means untouched.
 */
export function iconHint(icon: string, stored: string | null | undefined): string {
  if (icon === (stored ?? "")) {
    return storedNameNote(icon) ?? DEFAULT_HINT;
  }
  return iconProblem(icon) ?? DEFAULT_HINT;
}

/** What the field says when there is nothing to explain: the rule, and what
 *  an empty field does — which is a choice rather than an omission. */
export const DEFAULT_HINT =
  "An icon, or one or two characters — an emoji or an initial. Blank draws the type's first letter.";
