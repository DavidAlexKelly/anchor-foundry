/**
 * A property's type classes (§671; db 0133; `object-link-types` p.91), and
 * the one this platform reads: `workshop` p.222's `hubble:icon`.
 *
 * > "Type classes: Apply type classes as additional metadata that can be
 * > interpreted by applications." (object-link-types p.91)
 * >
 * > "If your object has a property that stores a URL to an image, you can
 * > add the type class hubble:icon to display the image instead of the icon
 * > that was selected when setting up the object type." (workshop p.222)
 */

/** `services/type_classes.py`'s shape, so the editor says what the server
 * would refuse before a save does. */
const SHAPE = /^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$/;

/** What the editor's box holds as the list it saves: comma- or
 * space-separated, each once, and the ones not `kind:name` named. */
export function typeClassesOf(text: string): { classes: string[]; bad: string[] } {
  const classes: string[] = [];
  const bad: string[] = [];
  for (const part of text.split(/[\s,]+/)) {
    if (!part) continue;
    if (!SHAPE.test(part) || part.length > 100) {
      bad.push(part);
    } else if (!classes.includes(part)) {
      classes.push(part);
    }
  }
  return { classes, bad };
}

export const ICON_CLASS = "hubble:icon";

/** The property whose value is each object's image, by p.222's type class;
 * the first, if several carry it. */
export function iconPropertyOf(
  properties: readonly { api_name: string; type_classes?: string[] }[],
): string | null {
  return properties.find((p) => p.type_classes?.includes(ICON_CLASS))?.api_name ?? null;
}

/** An image URL a page may load: http or https only, so a value can name a
 * picture and not a script. */
export function imageUrlOf(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    // The URL parser trims the whitespace around a value itself (a trim here
    // survived the sweep as equivalent).
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}
