/**
 * Favourite objects (§312; `getting-started` p.34; `ontology.md` §3).
 *
 *     "When you navigate to an individual object view, you can select the star
 *      next to its title to save it as a favorite. This will add the object to
 *      your sidebar… Think of favorites as shortcuts that you can add and
 *      remove to keep frequently used resources close at hand." (p.34)
 *
 * **p.34's sidebar is the Explorer's aside here**, beside Saved searches, and
 * the two belong together: one is a shortcut back to a question, the other a
 * shortcut back to an answer. Foundry's sidebar is platform-wide and ours is
 * not, so putting these anywhere else would mean inventing a surface to hold
 * four items.
 *
 * The server owns every refusal — who may star, how many, whether the type is
 * in this workspace. What lives here is what to *offer*, the division
 * `explorer.ts`, `tags.ts` and `sql-scratchpad.ts` already take.
 */
import type { ObjectFavourite } from "./types";

/**
 * What the star says it will do.
 *
 * **What pressing it does, not what the state is.** A control labelled
 * "Favourite" leaves somebody working out whether that is a description or an
 * instruction; `tags.ts` made the same choice about its delete button.
 */
export function starLabel(isFavourite: boolean): string {
  return isFavourite ? "Remove from favourites" : "Add to favourites";
}

/** The glyph, filled once it is kept. */
export function starGlyph(isFavourite: boolean): string {
  return isFavourite ? "★" : "☆";
}

/**
 * What a row in the list is called.
 *
 * The label stored when it was starred, which may be out of date — db 0074
 * takes that trade deliberately, because resolving ten titles is ten reads
 * against the instance store before a sidebar of ten shortcuts can draw.
 *
 * **The fallback is the type's name, never the instance's UUID.** A shortcut
 * reading `aabbccdd-…` is one nobody can choose between; one reading "Ship"
 * at least narrows it, and the type name is already on the row.
 */
export function rowLabel(favourite: ObjectFavourite): string {
  const said = favourite.label.trim();
  return said || favourite.object_type_name || "Object";
}

/**
 * The line under the name.
 *
 * The type, so two shortcuts with the same label are still tellable apart —
 * and suppressed when the label *is* the type name, because a row that says
 * "Ship / Ship" has spent two lines saying one thing.
 */
export function rowSubtitle(favourite: ObjectFavourite): string | null {
  const name = favourite.object_type_name;
  if (!name) return null;
  return rowLabel(favourite) === name ? null : name;
}

/**
 * What the empty list says.
 *
 * It names the verb and where to find it, because a star on an object view is
 * not something somebody finds by looking at an empty panel.
 */
export function emptyReason(): string {
  return (
    "None yet. Open an object and use the star beside its title to keep a " +
    "shortcut to it here."
  );
}

/**
 * Whether the star should be drawn at all.
 *
 * **Not while the answer is unknown.** An unfilled star means "not a
 * favourite", so drawing one before the server has said would tell somebody
 * their shortcut is gone — and the press that follows would remove a
 * favourite they still had. Absent for the moment it takes to find out is the
 * honest state, and it is the same rule `status-bar.ts` applies to a problem
 * count nobody has asked for yet.
 */
export function canShowStar(known: boolean): boolean {
  return known;
}
