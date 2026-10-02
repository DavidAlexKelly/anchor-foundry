/** Rebasing a module branch onto main: a three-way merge (Foundry p.193,
 * p.619-621).
 *
 * > "Rebasing applies the changes made on the branch to the latest main
 * > version of the module." (p.619)
 * > "Workshop auto-merges changes that do not overlap. A change is only
 * > flagged as a merge conflict when the same widget, variable, section, or
 * > layout position was edited on both main and your branch" (p.620)
 *
 * The three documents are the **base** (the main version the branch was taken
 * from - `base_version`, §698), **main** as it is now, and the **branch**.
 * Everything that changed on only one side since the base is taken from that
 * side; what changed on both, differently, is a conflict, and the conflict's
 * choice says which side wins. Nothing is chosen silently: a conflict nobody
 * picked defaults to main, which is the module everybody else is already
 * looking at, and is listed until somebody does.
 *
 * **Pure, beside `changelog.ts`**, for that module's reason: a merge is
 * arithmetic over three documents, and asking a browser whether it got the
 * answer right is a slow way to check a set operation.
 *
 * **The unit of a conflict is p.620's list**, and each is a different thing:
 *
 *   * a widget's *content* - its type and props, everything but where it is;
 *   * a widget's *position* - its parent, which is p.620's third example, "A
 *     widget was moved from location A to B on main and from A to C on your
 *     branch";
 *   * a section *deleted on one side and edited on the other* (p.620's second
 *     example), where "edited" includes having children added or removed -
 *     a section main deleted while the branch put a widget in it is exactly
 *     that, and auto-merging it would drop the widget with nobody told;
 *   * a variable, an event, or one module-wide setting (routing, state saving,
 *     translations, …) - each one entry, edited on both or deleted on one.
 *
 * **Order within a section auto-merges.** Two widgets added to one section,
 * one on each side, are both kept - main's order, with the branch's additions
 * placed after the sibling they followed on the branch. Calling that a
 * conflict would make every pair of additions to the same page one, which is
 * not what p.621's example describes: its conflict is two edits to one widget.
 */

export type MergeSection = "layout" | "variables" | "events" | "settings";

export type ConflictKind =
  /** Edited differently on both sides. */
  | "changed"
  /** Deleted on main, edited on the branch. */
  | "deleted-on-main"
  /** Deleted on the branch, edited on main. */
  | "deleted-on-branch"
  /** Moved to different places on each side. */
  | "moved";

export type MergeChoice = "main" | "branch";

export interface MergeConflict {
  /** Stable across re-merges of the same three documents: `section:id`, and
   * `layout:id@position` for a move, which is a different question from the
   * same widget's content. */
  key: string;
  section: MergeSection;
  id: string;
  label: string;
  kind: ConflictKind;
}

export interface RebaseResult {
  document: Record<string, unknown>;
  conflicts: MergeConflict[];
}

type Doc = Record<string, unknown> | null | undefined;
type Entry = Record<string, unknown>;
type EntryMap = Record<string, Entry>;

/** The sections merged entry by entry. Everything else at the top of a module
 * document is a module-wide setting, merged as one entry per key. */
const SECTIONS = ["layout", "variables", "events"] as const;

/** Keys that are structure rather than content: where a node is and what is
 * in it. Merged by position, not as part of the node's content. */
const STRUCTURAL = new Set(["parent", "nodes"]);

/** JSON with object keys sorted, so two documents that differ only in key
 * order - which a round trip through the server can produce - compare
 * equal. */
function canonical(value: unknown): string {
  return JSON.stringify(value === undefined ? null : sortKeys(value));
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort()) {
      out[key] = sortKeys((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}

function same(a: unknown, b: unknown): boolean {
  return canonical(a) === canonical(b);
}

function sectionOf(document: Doc, key: string): EntryMap {
  const value = (document ?? {})[key];
  return value && typeof value === "object" && !Array.isArray(value) ? (value as EntryMap) : {};
}

function settingsOf(document: Doc): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(document ?? {})) {
    if (!(SECTIONS as readonly string[]).includes(key)) out[key] = value;
  }
  return out;
}

/** A node without its position. */
function content(node: Entry | undefined): Entry | undefined {
  if (node === undefined) return undefined;
  const out: Entry = {};
  for (const [key, value] of Object.entries(node)) {
    if (!STRUCTURAL.has(key)) out[key] = value;
  }
  return out;
}

function children(node: Entry | undefined): string[] {
  const list = node?.nodes;
  return Array.isArray(list) ? list.map(String) : [];
}

function parentOf(node: Entry | undefined): string | undefined {
  return node?.parent === undefined || node.parent === null ? undefined : String(node.parent);
}

function widgetLabel(node: Entry | undefined, id: string): string {
  const type = node?.type;
  const name =
    typeof type === "object" && type !== null
      ? String((type as { resolvedName?: unknown }).resolvedName ?? "")
      : String(type ?? "");
  return (name.replace(/^Canvas/, "") || "Widget") + (id === "ROOT" ? "" : ` (${id})`);
}

function entryLabel(entry: Entry | undefined, id: string): string {
  const label = entry?.label ?? entry?.name;
  return typeof label === "string" && label ? `${label} (${id})` : id;
}

/** One entry's three-way merge. `undefined` on either side is a deletion. */
function mergeEntry<T>(
  base: T | undefined,
  main: T | undefined,
  branch: T | undefined,
  choice: MergeChoice | undefined,
  // Whether each side counts as edited when the value itself is unchanged -
  // a section whose children changed is edited although its props are not.
  editedBesides: { main: boolean; branch: boolean } = { main: false, branch: false },
):
  | { value: T | undefined; conflict: null }
  | { value: T | undefined; conflict: ConflictKind } {
  const mainEdited = !same(base, main) || (main !== undefined && editedBesides.main);
  const branchEdited = !same(base, branch) || (branch !== undefined && editedBesides.branch);
  if (!branchEdited) return { value: main, conflict: null };
  if (!mainEdited) return { value: branch, conflict: null };
  // Both sides arrived at the same value: nothing to choose between. What else
  // each edited (a section's children) is merged by position afterwards.
  if (same(main, branch)) return { value: main, conflict: null };
  const kind: ConflictKind =
    main === undefined ? "deleted-on-main" : branch === undefined ? "deleted-on-branch" : "changed";
  return { value: choice === "branch" ? branch : main, conflict: kind };
}

function mergeMap(
  section: MergeSection,
  base: EntryMap,
  main: EntryMap,
  branch: EntryMap,
  choices: Record<string, MergeChoice>,
  conflicts: MergeConflict[],
  label: (entry: Entry | undefined, id: string) => string,
): EntryMap {
  const out: EntryMap = {};
  const ids = new Set([...Object.keys(base), ...Object.keys(main), ...Object.keys(branch)]);
  for (const id of ids) {
    const key = `${section}:${id}`;
    const merged = mergeEntry(base[id], main[id], branch[id], choices[key]);
    if (merged.conflict) {
      conflicts.push({
        key, section, id, kind: merged.conflict,
        label: label(main[id] ?? branch[id] ?? base[id], id),
      });
    }
    if (merged.value !== undefined) out[id] = merged.value;
  }
  return out;
}

/** p.620's "the same widget … section, or layout position", for the layout. */
function mergeLayout(
  base: EntryMap,
  main: EntryMap,
  branch: EntryMap,
  choices: Record<string, MergeChoice>,
  conflicts: MergeConflict[],
): EntryMap {
  const ids = [...new Set([...Object.keys(main), ...Object.keys(branch), ...Object.keys(base)])];
  const contents: EntryMap = {};
  const parents: Record<string, string | undefined> = {};

  for (const id of ids) {
    const key = `layout:${id}`;
    // A section whose children changed is edited, although nothing on the
    // node itself is: deleting it on the other side would drop them. So is a
    // widget that was moved - deleting it on the other side discards a
    // decision about where it belongs.
    const structureChanged = (side: EntryMap) =>
      side[id] !== undefined && base[id] !== undefined
      && (!same(children(base[id]), children(side[id]))
        || parentOf(base[id]) !== parentOf(side[id]));
    const childrenChanged = { main: structureChanged(main), branch: structureChanged(branch) };
    const merged = mergeEntry(
      content(base[id]), content(main[id]), content(branch[id]), choices[key], childrenChanged,
    );
    if (merged.conflict) {
      conflicts.push({
        key, section: "layout", id, kind: merged.conflict,
        label: widgetLabel(main[id] ?? branch[id] ?? base[id], id),
      });
    }
    if (merged.value === undefined) continue;
    contents[id] = merged.value;

    // Where it is. Only a question for a node both sides still have: one side
    // deleting it was the content question above.
    const position = mergeEntry(
      parentOf(base[id]), parentOf(main[id]), parentOf(branch[id]), choices[`${key}@position`],
    );
    if (position.conflict === "changed" && main[id] && branch[id]) {
      conflicts.push({
        key: `${key}@position`, section: "layout", id, kind: "moved",
        label: widgetLabel(main[id] ?? branch[id], id),
      });
    }
    // A node only one side has is where that side put it.
    parents[id] =
      main[id] && branch[id] ? position.value
        : main[id] ? parentOf(main[id]) : parentOf(branch[id]);
  }

  // Each parent's children: the ids whose merged parent it is, in main's order,
  // with the branch's own additions after the sibling they followed there.
  const out: EntryMap = {};
  for (const id of Object.keys(contents)) {
    const wanted = Object.keys(contents).filter((child) => parents[child] === id);
    const wantedSet = new Set(wanted);
    const fromBase = children(base[id]);
    const fromMain = children(main[id]).filter((c) => wantedSet.has(c));
    const fromBranch = children(branch[id]).filter((c) => wantedSet.has(c));
    let order: string[];
    if (same(children(main[id]), fromBase)) {
      // Only the branch reordered (or nothing did): its order stands.
      order = fromBranch;
    } else {
      order = [...fromMain];
      fromBranch.forEach((child, index) => {
        if (order.includes(child)) return;
        const before = fromBranch.slice(0, index).reverse().find((c) => order.includes(c));
        order.splice(before === undefined ? 0 : order.indexOf(before) + 1, 0, child);
      });
    }
    for (const child of wanted) if (!order.includes(child)) order.push(child);
    const node: Entry = { ...contents[id] };
    if (parents[id] !== undefined) node.parent = parents[id];
    if (order.length > 0 || main[id]?.nodes !== undefined || branch[id]?.nodes !== undefined) {
      node.nodes = order;
    }
    out[id] = node;
  }

  // A node whose parent is gone is not on any page. It can only arise from a
  // choice - keeping a widget main deleted the section of - and a widget
  // nobody can see or select is worse than one that is not there.
  const reachable = (id: string, seen = new Set<string>()): boolean => {
    if (id === "ROOT") return true;
    if (seen.has(id)) return false;
    seen.add(id);
    const parent = out[id]?.parent;
    return typeof parent === "string" && parent in out && reachable(parent, seen);
  };
  // No parent's list needs trimming afterwards: a node pruned here has no
  // parent left in `out` to list it.
  for (const id of Object.keys(out)) {
    if ("ROOT" in out && !reachable(id)) delete out[id];
  }
  return out;
}

/** Rebase `branch` onto `main`, both descended from `base`.
 *
 * `choices` maps a conflict's `key` to the side that wins it; a conflict not
 * in it takes main's side and is still listed. Calling this again with more
 * choices is how a builder switches a conflict between Main and Branch
 * (p.621) - the document is rebuilt rather than patched, so switching back and
 * forth cannot accumulate anything.
 */
export function rebase(
  base: Doc,
  main: Doc,
  branch: Doc,
  choices: Record<string, MergeChoice> = {},
): RebaseResult {
  const conflicts: MergeConflict[] = [];
  const settings = mergeMap(
    "settings",
    settingsOf(base) as EntryMap, settingsOf(main) as EntryMap, settingsOf(branch) as EntryMap,
    choices, conflicts, (_entry, id) => id,
  );
  const document: Record<string, unknown> = { ...settings };
  document.layout = mergeLayout(
    sectionOf(base, "layout"), sectionOf(main, "layout"), sectionOf(branch, "layout"),
    choices, conflicts,
  );
  for (const section of ["variables", "events"] as const) {
    document[section] = mergeMap(
      section, sectionOf(base, section), sectionOf(main, section), sectionOf(branch, section),
      choices, conflicts, entryLabel,
    );
  }
  conflicts.sort((a, b) => a.key.localeCompare(b.key));
  return { document, conflicts };
}

/** What each conflict looks like in a sentence, for the list a builder works
 * through. p.620's own three examples are three of these. */
export function describeConflict(conflict: MergeConflict): string {
  switch (conflict.kind) {
    case "changed":
      return "edited on main and on this branch";
    case "deleted-on-main":
      return "deleted on main and edited on this branch";
    case "deleted-on-branch":
      return "deleted on this branch and edited on main";
    case "moved":
      return "moved to different places on main and on this branch";
  }
}
