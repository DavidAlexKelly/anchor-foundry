/** p.214's Saved colors: a module-level palette that widgets *reference*.
 *
 * > "Saved colors are defined at the module level. Add colors to the Saved
 * > colors section to make them selectable when configuring custom colors in
 * > layouts and widgets, including section and page backgrounds. You can
 * > rename saved colors, set separate colors for light and dark modes, and
 * > view where each color is used across layouts and widgets in your module.
 * > **When you edit a saved color, the change propagates to all layouts,
 * > sections, and widgets that reference it**, so you can update colors
 * > across your module in one place." (p.214)
 *
 * The emphasised sentence is the whole design. A palette that copied its hex
 * into each widget would look identical on the day it was set up and would
 * stop propagating the first time anybody edited it — so a widget stores
 * `saved:c1` and resolves it on the way to the screen. Every other feature on
 * p.214 (rename, light/dark, usage) is cheap once that is true, and impossible
 * while it is not. §398 built the Unsaved half and said so at the time.
 *
 * **Not a second colour vocabulary.** `resolveColour` is the one place a
 * reference becomes a value, and `style.resolveBackground` and the Stepper's
 * pair both go through it (§292). Two resolvers would mean a saved colour that
 * worked on a section and not on a step, which is exactly the kind of gap
 * nobody reports because it reads as "that widget does not support it".
 */
import { isHex, normaliseHex } from "./hex";

/** What a stored colour value says when it means "the module's colour `c1`".
 *
 * A prefix rather than a separate prop, because every one of these values
 * arrives through one control and shares one slot — `style.resolveBackground`
 * makes that argument for presets and hexes already, and a `background` plus a
 * `backgroundRef` is how a node ends up with both set and nobody able to say
 * which won.
 *
 * `saved:` cannot collide: a hex is `#`-or-digits, a preset is a bare word
 * from a fixed list, and a free CSS colour containing a colon is not a colour.
 */
export const REF_PREFIX = "saved:";

export interface SavedColour {
  /** Stable across renames, which is why it is not the name. */
  id: string;
  name: string;
  /** Normalised hex. p.214: "set separate colors for light and dark modes". */
  light: string;
  dark: string;
}

/** p.214's palette, read out of a stored document.
 *
 * **Entries this build cannot read are dropped, not repaired** (§212): the raw
 * JSON editor can hold anything, and a palette entry with no usable colour
 * would resolve to nothing at every site that referenced it — a module full of
 * blank backgrounds rather than one colour missing from a list.
 */
export function paletteOf(raw: unknown): SavedColour[] {
  if (!Array.isArray(raw)) return [];
  const out: SavedColour[] = [];
  const seen = new Set<string>();
  for (const entry of raw) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    const it = entry as Record<string, unknown>;
    const id = typeof it.id === "string" ? it.id.trim() : "";
    const light = typeof it.light === "string" ? it.light : "";
    if (!id || seen.has(id) || !isHex(light)) continue;
    seen.add(id);
    const dark = typeof it.dark === "string" && isHex(it.dark) ? it.dark : light;
    const name = typeof it.name === "string" && it.name.trim() ? it.name.trim() : id;
    out.push({
      id, name, light: normaliseHex(light), dark: normaliseHex(dark),
    });
  }
  return out;
}

/** The value a widget stores to reference a saved colour. */
export function refTo(id: string): string {
  return `${REF_PREFIX}${id}`;
}

/** The id a stored value references, or null when it is not a reference. */
export function refIn(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (!value.startsWith(REF_PREFIX)) return null;
  const id = value.slice(REF_PREFIX.length).trim();
  return id || null;
}

/** The colour a stored value means, for the scheme on screen.
 *
 * Returns `null` for a value that is not a reference, so a caller can carry on
 * with its own rules — this function answers one question and does not try to
 * become the colour resolver for everything.
 *
 * **A reference naming nothing is `undefined`, not a colour** (§210). It is
 * neither "no colour" nor a colour: the palette entry has gone, which a
 * reverted version can do, and quietly substituting black or transparent would
 * make a real loss look like a deliberate setting.
 */
export function resolveColour(
  value: unknown,
  palette: readonly SavedColour[],
  scheme: "light" | "dark",
): string | null | undefined {
  const id = refIn(value);
  if (id === null) return null;
  const found = palette.find((c) => c.id === id);
  if (!found) return undefined;
  return scheme === "dark" ? found.dark : found.light;
}

/** Every colour in the palette, by id. */
export function byId(palette: readonly SavedColour[]): Record<string, SavedColour> {
  return Object.fromEntries(palette.map((c) => [c.id, c]));
}

/** An id nothing in this palette uses.
 *
 * Counted rather than random: a document is read by people, and `c3` in a diff
 * is a colour somebody can find. Sequential from the highest in use rather
 * than from the length, so removing an entry cannot hand its id to the next
 * colour and silently recolour every widget that referenced the old one.
 */
export function nextId(palette: readonly SavedColour[]): string {
  let highest = 0;
  for (const colour of palette) {
    const n = /^c(\d+)$/.exec(colour.id);
    if (n) highest = Math.max(highest, Number(n[1]));
  }
  return `c${highest + 1}`;
}

/** A name nothing in this palette uses.
 *
 * Names are how a builder picks a colour out of a list, so two called "Brand"
 * is a control where the right choice is unguessable. Numbered rather than
 * refused: this is reached by pressing Add, and a button that refuses is worse
 * than one that names the thing it made.
 */
export function freeName(palette: readonly SavedColour[], wanted: string): string {
  const taken = new Set(palette.map((c) => c.name.toLowerCase()));
  const base = wanted.trim() || "Colour";
  if (!taken.has(base.toLowerCase())) return base;
  for (let n = 2; ; n += 1) {
    const candidate = `${base} ${n}`;
    if (!taken.has(candidate.toLowerCase())) return candidate;
  }
}

/** Add a colour to the palette, seeded from a hex.
 *
 * The dark value starts equal to the light one rather than at some computed
 * opposite: p.214 offers the pair so a builder can *choose*, and a guessed
 * dark colour is a choice they never made appearing in their module.
 */
export function added(
  palette: readonly SavedColour[], hex: string, name = "Colour",
): SavedColour[] {
  const value = isHex(hex) ? normaliseHex(hex) : "#000000";
  return [
    ...palette,
    { id: nextId(palette), name: freeName(palette, name), light: value, dark: value },
  ];
}

/** Change one entry. Unknown ids change nothing, which is what a panel racing
 * a revert should do. */
export function updated(
  palette: readonly SavedColour[], id: string, change: Partial<Omit<SavedColour, "id">>,
): SavedColour[] {
  return palette.map((colour) => {
    if (colour.id !== id) return colour;
    const next = { ...colour };
    if (change.name !== undefined) next.name = freeName(
      palette.filter((c) => c.id !== id), change.name,
    );
    if (change.light !== undefined && isHex(change.light)) {
      next.light = normaliseHex(change.light);
    }
    if (change.dark !== undefined && isHex(change.dark)) {
      next.dark = normaliseHex(change.dark);
    }
    return next;
  });
}
