/**
 * p.222's Configure columns, the viewer's own column choice (§612).
 *
 * > "Users in View mode can also choose to configure the columns shown to
 * > them. By selecting Configure columns from the arrow next to a column
 * > header, viewers can choose the columns and the order to display them in
 * > the Object Table." (p.222)
 *
 * > "Hide column configuration: When enabled, hides the Configure columns
 * > option present in view mode from the table's header menu." (p.225)
 *
 * **The viewer chooses among what the table offers**: the configured columns,
 * narrowed by p.225's column variable where there is one (§610). A viewer
 * cannot reach a column the author left out, for §610's reason - the table's
 * settings still mean something.
 *
 * **Held per viewer, in the browser**, keyed by the widget. It is a reading
 * preference, like a sort a person clicks, and the module is shared: a choice
 * written into the document would change the table for everyone who opens it.
 */

/** What the table draws for this viewer. `chosen` is null for "as the table
 *  is configured". Names no longer offered - a column the author has since
 *  removed - are dropped; a choice left with nothing is no choice. */
export function viewerColumnsOf(available: readonly string[], chosen: readonly string[] | null): string[] {
  if (!chosen) return [...available];
  const offered = new Set(available);
  const kept = chosen.filter((name) => offered.has(name));
  return kept.length > 0 ? kept : [...available];
}

/** The choice after a checkbox. Adding goes to the end, which is where a
 *  column a person just asked for is easiest to find; removing the last one
 *  is refused, since a table of keys alone is a list the viewer cannot get
 *  back from without knowing to press Reset. */
export function toggled(
  available: readonly string[], chosen: readonly string[] | null, name: string,
): string[] {
  const current = viewerColumnsOf(available, chosen);
  if (current.includes(name)) {
    return current.length > 1 ? current.filter((n) => n !== name) : current;
  }
  return available.includes(name) ? [...current, name] : current;
}

/** The choice with one column moved a place up (-1) or down (+1). */
export function moved(
  available: readonly string[], chosen: readonly string[] | null, name: string, delta: -1 | 1,
): string[] {
  const current = viewerColumnsOf(available, chosen);
  const from = current.indexOf(name);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= current.length) return current;
  const next = [...current];
  [next[from], next[to]] = [next[to]!, next[from]!];
  return next;
}

/** Where a viewer's choice is kept: per widget, per object type, so a table
 *  pointed at another type does not inherit names that mean nothing there. */
export function storageKey(nodeId: string, typeId: string | null | undefined): string {
  return `anchor.table-columns.${nodeId}.${typeId ?? ""}`;
}

/** A stored choice, read defensively: anything but a list of names is none. */
export function storedChoice(raw: string | null): string[] | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw);
    if (!Array.isArray(value)) return null;
    const names = value.filter((v): v is string => typeof v === "string" && v !== "");
    return names.length ? names : null;
  } catch {
    return null;
  }
}
