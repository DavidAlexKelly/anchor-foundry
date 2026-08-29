/** p.265-266's Property List: "a list of properties from a single provided object".
 *
 * > "**Input object set**: The input variable which determines the object data
 * > that will be displayed within the widget. If the object set contains more
 * > than one object, only the first object will be displayed within the
 * > widget. … **Layout**: Adjusts the positioning of properties displayed in the
 * > widget. Property values can either be displayed adjacent to their
 * > corresponding property type labels or below. **Property configuration**:
 * > Select which properties to be displayed in the widget and specify the number
 * > of columns displayed. … **Hide null properties**: If enabled, null
 * > properties will be hidden from the list." (p.265-266)
 *
 * ---
 *
 * **The widget is a list and two questions about it**: which properties, and
 * how they are arranged. Both are decided from a saved document and a resolved
 * instance, so both are pure — and the one that has to be got right is the
 * first, because a property list that quietly drops a row is a fact somebody
 * does not learn.
 */

/** p.265's Layout. */
export const LAYOUTS: Record<string, string> = {
  adjacent: "Beside the label",
  below: "Under the label",
};

export const DEFAULT_LAYOUT = "adjacent";

export function layoutOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(LAYOUTS, raw) ? raw : DEFAULT_LAYOUT;
}

/** p.266's "specify the number of columns displayed". */
export const MIN_COLUMNS = 1;
export const MAX_COLUMNS = 6;

export function columnsOf(raw: unknown): number {
  // No absence guard: the default is the floor, so a coerced `0` already lands
  // on the right answer and a guard in front of it could never change one
  // (§208's finding, and §203's read the other way round).
  const value = Number(raw);
  if (!Number.isFinite(value)) return MIN_COLUMNS;
  return Math.min(MAX_COLUMNS, Math.max(MIN_COLUMNS, Math.floor(value)));
}

export function hideNullOf(raw: unknown): boolean {
  return raw === true;
}

/** What p.266 means by a null property.
 *
 * The empty string counts. A property mapped from a CSV column that was blank
 * arrives as `""` rather than as `null`, and a list that hid one and kept the
 * other would look arbitrary to the person reading it — they cannot see which
 * of the two the store happens to hold.
 */
export function isNull(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

export interface Property {
  api_name: string;
  display_name?: string | null;
}

export interface VisibleInput<P extends Property> {
  /** Every property the object type declares. */
  all: readonly P[];
  /** p.266's selection, in the order to show them. Blank means all of them. */
  chosen: string;
  /** The object's values, or `undefined` while it is still resolving. */
  values: Record<string, unknown> | undefined;
  hideNull: boolean;
}

/** The properties to draw, in order.
 *
 * Three rules, and each is a thing that goes wrong quietly:
 *
 * * **The configured order wins**, because p.266 calls it selecting which
 *   properties to display and an author who lists three has said something
 *   about the order too.
 * * **A name that matches nothing is dropped rather than drawn empty.** A
 *   property can be removed from the object type long after a widget was
 *   pointed at it, and a blank row labelled with a name nobody recognises is
 *   worse than no row.
 * * **Nulls are only hidden once there is something to judge.** While the
 *   instance is unresolved every value is `undefined`, so hiding then would
 *   empty the widget on every load and fill it a moment later — the rule §210
 *   applies to whether a widget renders at all, one level down.
 */
export function visibleProperties<P extends Property>(
  { all, chosen, values, hideNull }: VisibleInput<P>,
): P[] {
  const wanted = String(chosen || "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  const ordered = wanted.length
    ? wanted.map((name) => all.find((p) => p.api_name === name)).filter((p): p is P => !!p)
    : [...all];
  if (!hideNull || values === undefined) return ordered;
  return ordered.filter((p) => !isNull(values[p.api_name]));
}

/** The grid p.266's column count asks for. */
export function gridStyle(columns: number): { gridTemplateColumns: string } {
  return { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` };
}
