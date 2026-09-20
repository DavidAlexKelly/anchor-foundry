/** Reading a hand-typed colour.
 *
 * **Its own module to break a cycle, and the cycle is worth naming** (§414).
 * `style.ts` resolves a background and now has to ask `saved-colours.ts` what
 * a `saved:` reference means; `saved-colours.ts` has to normalise the hexes it
 * stores. Leaving these two functions in `style.ts` made the two files import
 * each other, and the alternative — a second `isHex` beside the palette — is
 * exactly the second answer §292 is about: the first time somebody allows a
 * four-digit alpha hex, one of the copies keeps refusing it.
 *
 * Both are still exported from `style.ts`, so no existing importer had to
 * change to learn where they moved.
 */

/** Whether this is a hex colour, in either spelling. */
export function isHex(value: string): boolean {
  return /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value.trim());
}

/** One spelling per colour: lowercased, `#`-prefixed, three digits expanded to
 * six.
 *
 * `#abc` and `abc` both mean `#aabbcc`. Accepting the short form and the
 * missing hash is not politeness: this value is typed by hand, and a picker
 * that silently ignored `abc` would look like a broken control. It is also
 * what makes `#FFF` and `#ffffff` one row in the Used colors panel rather
 * than two.
 */
export function normaliseHex(value: string): string {
  const raw = value.trim().replace(/^#/, "").toLowerCase();
  const full = raw.length === 3 ? raw.split("").map((c) => c + c).join("") : raw;
  return `#${full}`;
}
