/**
 * p.7's Overview tab, as the two decisions it actually contains (§345;
 * `action-types` p.7).
 *
 *     "Enter a Display name for your action type." (p.7)
 *
 *     "You can now see the full detailed view of your action type. You can
 *      make additional adjustments, like adding a Description in the Overview
 *      tab." (p.7)
 *
 * **The gap §344 found, from the other side.** The creation wizard set both and
 * nothing changed them afterwards, so an ontology import could rename an action
 * and a person could not. The server writes them now; this is what the screen
 * has to decide before it asks.
 *
 * Pure because both decisions are wording and arithmetic over two objects, and
 * a component that computed them inline could only be checked by driving a
 * browser at it.
 */

/** One action's Overview fields, as the screen holds them. */
export interface Overview {
  display_name: string;
  description: string;
}

/**
 * What a save would send, or `null` when it would send nothing.
 *
 * **Only the fields that differ**, because the PATCH treats an omitted field as
 * unchanged and writes an `action_type.rename` audit row for one that is
 * present. Sending back a display name nobody touched would put a rename in the
 * log that never happened, which makes the log worse than no log.
 *
 * `null` rather than `{}` for "nothing changed", so the caller cannot send an
 * empty body by forgetting to check — the type makes the check the only way
 * through.
 */
export function overviewEdit(
  saved: Overview,
  draft: Overview,
): { display_name?: string; description?: string } | null {
  const edit: { display_name?: string; description?: string } = {};
  // Trimmed before comparing, because the server trims before storing: without
  // this, adding a trailing space and saving reports a change and stores none.
  if (draft.display_name.trim() !== saved.display_name.trim()) {
    edit.display_name = draft.display_name.trim();
  }
  // **Not trimmed away to nothing.** An empty description is a real value that
  // clears the field, and it is `null`/absent that means "leave it alone" — so
  // "" must reach the server when the saved one was not empty.
  if (draft.description.trim() !== saved.description.trim()) {
    edit.description = draft.description.trim();
  }
  return Object.keys(edit).length ? edit : null;
}

/**
 * Why this draft cannot be saved, or `""`.
 *
 * db 0013 checks `length(display_name) BETWEEN 1 AND 200` and the route's
 * schema says the same; this says it before the round trip, because a Save
 * button that posts a name the server is certain to refuse is §214's control
 * that looks like it works.
 */
export function overviewRefusal(draft: Overview): string {
  const named = draft.display_name.trim();
  if (!named) return "An action needs a name — p.7's Display name.";
  if (named.length > 200) {
    return `A name is at most 200 characters; this one is ${named.length}.`;
  }
  if (draft.description.length > 2000) {
    return `A description is at most 2000 characters; this one is ${draft.description.length}.`;
  }
  return "";
}
