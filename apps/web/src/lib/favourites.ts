/**
 * Favourites (§312, §436; `getting-started` p.34; `ontology.md` §3).
 *
 *     "You can add and remove favorites with the star icon while navigating
 *      the folder structure or **from within an open resource** in a Palantir
 *      platform application." (p.34)
 *
 *     "When you navigate to an individual object view, you can select the star
 *      next to its title to save it as a favorite. This will add the object to
 *      your sidebar… Think of favorites as shortcuts that you can add and
 *      remove to keep frequently used resources close at hand." (p.34)
 *
 * **p.34's sidebar is two asides here, and the reason is the same one §312
 * gave for there being one.** Foundry's sidebar is platform-wide and ours is
 * not, so a favourite is listed where it can be *opened*: an object shortcut
 * beside Saved searches in the Explorer — one a shortcut back to a question,
 * the other back to an answer — and a resource shortcut in the project's
 * browser, which is the screen that opens resources. One store, one cap, two
 * lists, each next to what it leads back to.
 *
 * The server owns every refusal — who may star, how many, whether the type is
 * in this workspace. What lives here is what to *offer*, the division
 * `explorer.ts`, `tags.ts` and `sql-scratchpad.ts` already take.
 */
import type { Favourite } from "./types";

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
export function rowLabel(favourite: Favourite): string {
  const said = favourite.label.trim();
  // **The kind, never the id.** A shortcut reading `aabbccdd-…` is one nobody
  // can choose between; "Dataset" at least narrows it, and since §436 a row
  // may be a resource, whose kind is the only other thing on it.
  return said || favourite.object_type_name || kindWord(favourite) || "Shortcut";
}

/** The kind of resource a shortcut points at, in a word somebody reads —
 *  `code_repo` is a column value, not a noun. */
export function kindWord(favourite: Favourite): string | null {
  const kind = favourite.resource_kind;
  if (!kind) return null;
  return kind === "code_repo"
    ? "Repository"
    : kind.charAt(0).toUpperCase() + kind.slice(1).replace(/_/g, " ");
}

/** The object shortcuts, which the Explorer's aside can open. */
export function objectsOnly(favourites: readonly Favourite[]): Favourite[] {
  return favourites.filter((f) => f.instance_id !== null);
}

/** The resource shortcuts, which the project's browser can open. */
export function resourcesOnly(favourites: readonly Favourite[]): Favourite[] {
  return favourites.filter((f) => f.resource_id !== null);
}

/** Where a resource shortcut goes. The stable id, which is the whole reason
 *  resource ids exist: a link built from slugs stops working the moment
 *  somebody renames either, and §435 made renaming a thing people do. */
export function resourceHref(favourite: Favourite): string {
  return `/r/${favourite.resource_id}`;
}

/** What the resource list says when it is empty. Its own sentence, because it
 *  names a different star in a different place. */
export function resourcesEmptyReason(): string {
  return (
    "None yet. Open a resource and use the star in its header to keep a "
    + "shortcut to it here."
  );
}

/**
 * The line under the name.
 *
 * The type, so two shortcuts with the same label are still tellable apart —
 * and suppressed when the label *is* the type name, because a row that says
 * "Ship / Ship" has spent two lines saying one thing.
 */
export function rowSubtitle(favourite: Favourite): string | null {
  const name = favourite.object_type_name ?? kindWord(favourite);
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
