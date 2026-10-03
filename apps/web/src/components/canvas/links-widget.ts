/** p.268-272's Links widget: "the links relationship between objects and
 * provide exploration into those paths".
 *
 * > "**Link types to display**: By default, all links are shown in the links
 * > widget. By choosing "Specify link types", granular controls and features
 * > such as link level sorting can be configured. … **Default link expand**:
 * > Specify the number of links that will be auto-expanded by default in the
 * > first level." (p.270-271)
 *
 * > "**Link type**: Once a starting object set has been selected, choose the
 * > link type from a dropdown to be displayed on the widget. **Link type label
 * > override**: The link type's label can be overridden with a new label for the
 * > link type." (p.272)
 *
 * ---
 *
 * **A link is identified by its type *and its direction*, never by the type
 * alone.** The server returns a link type once per end it occupies, and a
 * self-link — Person manages Person — comes back **twice** on purpose, because
 * "my manager" and "my reports" are different questions with the same
 * `link_type_id`. Every selection, override and expansion here is keyed on the
 * pair; keying on the id would make configuring one of a self-link's two
 * directions silently configure both, and there is nothing on screen that would
 * look wrong.
 */

import { OBJECT_PARAM, encodeObject } from "../../lib/object-links";
import { PRIMARY_KEY } from "./object-table-selection";

export interface LinkGroup {
  link_type_id: string;
  direction: string;
  side_name: string;
  total: number;
}

/** p.270's "Link types to display". */
export const LINK_MODES: Record<string, string> = {
  all: "All link types",
  specify: "Specify link types",
};

export function modeOf(raw: unknown): string {
  return raw === "specify" ? "specify" : "all";
}

/** One configured link: which end of which type, p.272's label override, and
 * p.272's **Sort linked object by** (§548) - the server's own sort string, a
 * property name with a leading `-` for descending. */
export interface ChosenLink {
  key: string;
  label?: string;
  sort?: string;
  /** p.272's Display properties in object preview (§549): the linked type's
   * properties its preview shows in place of the prominent ones. */
  preview?: string[];
}

/** The identity of one row: **the type and the end**, not the type.
 *
 * See the note at the top — a self-link occupies both ends and is returned
 * twice, so `link_type_id` alone names two different questions.
 */
export function linkKey(group: Pick<LinkGroup, "link_type_id" | "direction">): string {
  return `${group.link_type_id}:${group.direction}`;
}

/** What a saved document's link selection amounts to.
 *
 * Tolerant, because this prop is an array of objects and the raw JSON editor
 * can put anything in it: entries that are not objects, or carry no key, are
 * dropped rather than rendered as a row nothing can fill.
 */
export function chosenOf(raw: unknown): ChosenLink[] {
  if (!Array.isArray(raw)) return [];
  const out: ChosenLink[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const item = entry as Partial<ChosenLink>;
    if (typeof item.key !== "string" || !item.key) continue;
    const named = Array.isArray(item.preview)
      ? item.preview.filter((p): p is string => typeof p === "string" && !!p) : [];
    out.push({
      key: item.key,
      ...(typeof item.label === "string" && item.label.trim() ? { label: item.label } : {}),
      ...(typeof item.sort === "string" && item.sort.replace(/^-/, "")
        ? { sort: item.sort } : {}),
      ...(named.length ? { preview: named } : {}),
    });
  }
  return out;
}

/** The link rows to draw, in order.
 *
 * In `specify` mode the *configured* order wins, and a configured link the
 * object type no longer has is dropped — a link type can be deleted long after
 * a widget was pointed at it, and an empty row labelled with a link nobody
 * recognises is worse than no row. In `all` mode the server's order stands.
 */
export function visibleLinks<G extends LinkGroup>(
  groups: readonly G[], mode: unknown, chosen: readonly ChosenLink[],
): G[] {
  if (modeOf(mode) !== "specify") return [...groups];
  return chosen
    .map((c) => groups.find((g) => linkKey(g) === c.key))
    .filter((g): g is G => !!g);
}

/** p.272's label override, falling back to the side's own name.
 *
 * `side_name` rather than the link type's display name: the server has already
 * resolved which end is being traversed *to*, and a link called "manages" reads
 * backwards on the inbound side.
 */
export function labelFor(group: LinkGroup, chosen: readonly ChosenLink[]): string {
  const found = chosen.find((c) => c.key === linkKey(group));
  return found?.label ?? group.side_name;
}

/** p.271's "Default link expand": how many rows open on load. */
export const MAX_DEFAULT_EXPAND = 20;

export function defaultExpandOf(raw: unknown): number {
  const value = Number(raw);
  if (!Number.isFinite(value)) return 0;
  return Math.min(MAX_DEFAULT_EXPAND, Math.max(0, Math.floor(value)));
}

/** Which rows are open before anybody has clicked.
 *
 * **The first `n` of what is actually shown**, not of what the server returned:
 * p.271 says "auto-expanded by default in the first level", and a widget
 * configured to show two link types that opened a third the author had hidden
 * would be expanding something nobody can see.
 */
export function initiallyExpanded(
  visible: readonly LinkGroup[], count: number,
): string[] {
  return visible.slice(0, count).map(linkKey);
}

/** Open or close one row, keeping the order stable so React does not remount. */
export function toggleExpanded(open: readonly string[], key: string): string[] {
  return open.includes(key) ? open.filter((k) => k !== key) : [...open, key];
}

/**
 * p.271's linked objects configuration (§547).
 *
 * > "Enable exploration on link types: At each link type level, enable a
 * > button to allow viewing the link type in Object Explorer. Enable open
 * > object view on linked objects: For each linked object, enable a button to
 * > allow opening the linked object's Object View in Object Explorer. Enable
 * > object preview on hover: When hovering over on the title of a linked
 * > object, preview the linked object's properties. By default, the popover
 * > includes the linked object's prominent properties …" (p.271)
 */

/** A linked object's title: its type's title property, or its key when that
 * is empty - a blank row would be a link to nothing anybody can name. */
export function titleOf(
  item: { primary_key: string; properties: Record<string, unknown> },
  titleProperty: string | null | undefined,
): string {
  const value = titleProperty ? item.properties[titleProperty] : undefined;
  return value === null || value === undefined || String(value).trim() === ""
    ? item.primary_key : String(value);
}

/** p.271's default preview: the type's prominent properties, in the type's
 * order, and never its hidden ones - or p.272's specified ones for a link
 * that names them (§549), in the order it names them. A name the type no
 * longer has is dropped rather than drawn as a row with nothing in it. */
export function previewProperties<P extends { api_name: string; visibility?: string }>(
  properties: readonly P[],
  specified?: readonly string[],
): P[] {
  if (specified && specified.length) {
    return specified
      .map((name) => properties.find((p) => p.api_name === name))
      .filter((p): p is P => !!p);
  }
  return properties.filter((p) => p.visibility === "prominent");
}

/** The properties a chosen link's preview specifies, if it does. */
export function previewOf(chosen: readonly ChosenLink[], key: string): string[] | undefined {
  return chosen.find((c) => c.key === key)?.preview;
}

/** Where a linked object's Object View opens: the Object Explorer with it
 * open, which is the link the Explorer itself writes (§309). */
export function objectViewHref(workspaceSlug: string, typeId: string, instanceId: string): string {
  const params = new URLSearchParams({ [OBJECT_PARAM]: encodeObject({ typeId, instanceId }) });
  return `/${workspaceSlug}/explore?${params.toString()}`;
}

/**
 * p.272's **Sort linked object by** (§548).
 *
 * > "Sort linked object by: Once a link type is chosen, a property and sorting
 * > direction can be configured." (p.272)
 *
 * The traversal that draws every link returns each one's first page in the
 * store's own order, and reordering *that page* would sort the first ten of
 * the link and claim to have sorted the link. So a sorted link asks for its
 * first page again, sorted, as the set it is: the far type where the far
 * property is this object's value - the Explorer's own reading of a link
 * (`linkSubsetHref`). The server orders by the property's declared type, and
 * refuses text, whose order the two stores do not agree on.
 *
 * **A link through p.197's join table is a hop, not a match** (§552): the far
 * objects do not hold this object's key, the join table's rows do, so the set
 * is the far type reached from this one object by the link.
 *
 * Null when the link names nothing to match, as it then has no objects.
 */
export function sortedLinkQuery(
  group: {
    link_type_id: string; far_type_id: string; far_property: string; matched_value: unknown;
    join_table?: boolean;
    /** §666: through backing objects, from this object's `near_property`. */
    backed?: boolean;
    near_property?: string;
  },
  sort: string | undefined,
  nearTypeId?: string,
): { definition: unknown; sort: string } | null {
  if (!sort || group.matched_value === null || group.matched_value === undefined) return null;
  const value = String(group.matched_value);
  if (group.join_table || group.backed) {
    if (!nearTypeId) return null;
    return {
      definition: {
        object_type_id: group.far_type_id,
        via: {
          link_type_id: group.link_type_id,
          base: {
            object_type_id: nearTypeId,
            // A join table's value is the key; a backed link's is its near
            // property's, which may be the key too.
            filters: [{ property: group.backed ? group.near_property ?? PRIMARY_KEY : PRIMARY_KEY, op: "eq", value }],
          },
        },
      },
      sort,
    };
  }
  return {
    definition: {
      object_type_id: group.far_type_id,
      filters: [{ property: group.far_property, op: "eq", value }],
    },
    sort,
  };
}

/** A link's first page, as the instance-links read returns it
 * (`routes/objects.LINK_PREVIEW_LIMIT`), so a sorted link shows as many. */
export const LINK_PAGE = 10;

/** The sort a chosen link carries, for its row in the panel. */
export function sortOf(chosen: readonly ChosenLink[], key: string): string | undefined {
  return chosen.find((c) => c.key === key)?.sort;
}

/** p.268's further exploration (§712): "The Flight Alert's linked Departure
 * Airport has been expanded further in this screenshot to show its links".
 * A linked object opens to its own links, and theirs, to this many levels
 * below the widget's object - links run in cycles (a person's manager's
 * reports include the person), so an unbounded tree is one a reader could
 * expand forever. */
export const MAX_LINK_DEPTH = 4;

/** Whether an object `depth` levels below the widget's object may open to
 * its own links; the widget's object is level 0, its linked objects level 1. */
export function expandsFurther(depth: number): boolean {
  return depth < MAX_LINK_DEPTH;
}
