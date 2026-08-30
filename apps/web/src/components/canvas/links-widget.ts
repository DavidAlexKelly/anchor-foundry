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

/** One configured link: which end of which type, and p.272's label override. */
export interface ChosenLink {
  key: string;
  label?: string;
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
    out.push(
      typeof item.label === "string" && item.label.trim()
        ? { key: item.key, label: item.label }
        : { key: item.key },
    );
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
