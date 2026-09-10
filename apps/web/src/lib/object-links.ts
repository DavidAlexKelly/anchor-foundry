/**
 * A link to one object (§309; `ontology.md` §3; `getting-started` p.34).
 *
 * The Object Explorer's *search* has been linkable since saved searches were
 * built — "send me the link to that" is the reason they exist. The object you
 * open **from** that search was not: it lived in `useState`, so a reader who
 * found something and wanted to show somebody could send them the search and
 * a sentence saying which row.
 *
 * **This is also the prerequisite for favouriting an object** (`ontology.md`'s
 * other ○ row, `getting-started` p.34: "select the star next to its title to
 * save it as a favorite"). A favourite is a shortcut, and a shortcut needs
 * somewhere to point — so the link comes first, and the two rows turn out to
 * be one mechanism.
 *
 * The whole module is the query parameter's grammar. It is here rather than
 * inline for `resource-filter.ts`'s reason: a query string is a small public
 * interface, because links get shared, bookmarked and truncated by mail
 * clients, and rules about one are cheap to get wrong and invisible when wrong.
 */

/** The query parameter. One key, not two, so a half-copied link is *malformed*
 * rather than plausibly meaning something else — `?objectType=…` with no
 * instance would otherwise look like a filter. */
export const OBJECT_PARAM = "object";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ObjectRef = { typeId: string; instanceId: string };

/**
 * The link's value for one object.
 *
 * **Both halves, and the type is not redundant.** The instance store is
 * partitioned by object type — one index per type — so reading a single
 * instance takes both ids. A link carrying only the instance id could not be
 * resolved without searching every type in the workspace, which is a query
 * this platform deliberately does not have.
 */
export function encodeObject(ref: ObjectRef): string {
  return `${ref.typeId}:${ref.instanceId}`;
}

/**
 * The object a link names, or `null` if it does not name one.
 *
 * **`null` rather than a throw, and the caller shows the search.** A link in a
 * chat message gets truncated, a URL gets hand-edited, and an object gets
 * deleted between somebody sending a link and somebody following it. None of
 * those deserves an error page: the reader arrived wanting to look at this
 * workspace's objects, and the search is where that starts.
 *
 * Both halves are checked as UUIDs, because they go into a request path. A
 * value that is not one cannot name an object here, so the check costs a
 * round trip that could only ever 404 — and it keeps anything else out of the
 * URL this browser builds.
 */
export function decodeObject(raw: string | null): ObjectRef | null {
  if (!raw) return null;
  const at = raw.indexOf(":");
  if (at <= 0) return null;
  const typeId = raw.slice(0, at);
  const instanceId = raw.slice(at + 1);
  if (!UUID.test(typeId) || !UUID.test(instanceId)) return null;
  return { typeId, instanceId };
}

/**
 * Whether two references are the same object.
 *
 * Used to decide whether an open object needs re-fetching when the URL
 * changes. Comparing the encoded strings would work too and would be wrong
 * the first time either half's case differed — a UUID pasted from somewhere
 * that upper-cases them is the same object.
 */
export function sameObject(a: ObjectRef | null, b: ObjectRef | null): boolean {
  if (a === null || b === null) return a === b;
  return (
    a.typeId.toLowerCase() === b.typeId.toLowerCase() &&
    a.instanceId.toLowerCase() === b.instanceId.toLowerCase()
  );
}

/**
 * What to say when a link names an object that is not there.
 *
 * **It says which of the two things went wrong**, because the remedies differ:
 * an object that has been deleted is gone and the reader should stop looking,
 * while a link that arrived broken can be asked for again. Distinguishable
 * only by whether the link parsed at all, which is the most this browser can
 * honestly tell.
 */
export function missingNote(parsed: boolean): string {
  return parsed
    ? "That object is no longer here — it may have been deleted, or the sync that " +
        "produced it may have dropped it."
    : "That link does not name an object. It may have been cut short on its way here.";
}
