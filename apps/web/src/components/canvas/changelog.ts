/** What changed between two versions of a Workshop module (Foundry p.193).
 *
 * > "Use the Changelog panel to visualize differences between module versions…
 * > The Changelog panel highlights **additions, deletions, changes, moves, and
 * > newly unused elements**."
 *
 * The five words in that sentence are the five kinds of entry this produces,
 * and they are not interchangeable. A widget that moved has the same props it
 * had before, so calling it "changed" would bury the one thing that is
 * different about it; a variable nothing reads any more is not deleted, and
 * saying so would send somebody looking for a deletion that never happened.
 *
 * **Pure, and in `components/canvas/` rather than in the panel**, for the same
 * reason `pure.ts` exists: a diff is arithmetic over two documents, and asking
 * a browser whether it got the answer right is a slow and imprecise way to
 * check a set difference. The panel that draws this is checked in `e2e/`.
 *
 * **What "moved" means here.** A node's position is its parent plus its index
 * among that parent's children - Craft.js stores both, and a widget dragged
 * from one section to another changes only the first while one dragged up a
 * column changes only the second. Both are moves; neither is a prop change.
 *
 * **§183 added p.193's other two halves**: `changeDetail` is "inspect JSON
 * diffs to see the exact modifications", and `changeTree` is "review a visual
 * hierarchy to understand how changes relate to nested components". Both are
 * separate functions rather than extra keys on `Change`, for two reasons: a
 * detail nobody expanded is work nobody asked for, and `Change` is the shape
 * this module's own tests compare against wholesale.
 */

export type ChangeKind = "added" | "deleted" | "changed" | "moved" | "unused";

export interface Change {
  /** The node, variable or event id. */
  id: string;
  /** What to call it on screen - a widget's type, a variable's label. */
  label: string;
  kind: ChangeKind;
}

export interface ModuleChangelog {
  widgets: Change[];
  variables: Change[];
  events: Change[];
}

type Doc = Record<string, unknown> | null | undefined;

function section(document: Doc, key: string): Record<string, Record<string, unknown>> {
  const value = (document ?? {})[key as keyof typeof document];
  return (value && typeof value === "object" ? value : {}) as Record<
    string,
    Record<string, unknown>
  >;
}

/** A node's type, in either shape the corpus stores: `{resolvedName}` from the
 * builder, a bare string in hand-written and converted documents. */
function widgetName(node: Record<string, unknown> | undefined): string {
  const type = node?.type;
  if (typeof type === "object" && type !== null) {
    return String((type as { resolvedName?: unknown }).resolvedName ?? "widget");
  }
  return String(type ?? "widget");
}

/** Where a node sits: its parent, and its index among that parent's children. */
function position(
  layout: Record<string, Record<string, unknown>>,
  id: string,
): { parent: string; index: number } {
  const node = layout[id] ?? {};
  const parent = String(node.parent ?? "");
  const siblings = (layout[parent]?.nodes ?? []) as unknown[];
  return { parent, index: Array.isArray(siblings) ? siblings.indexOf(id) : -1 };
}

/** True when two values differ, compared as stored. */
function differs(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) !== JSON.stringify(b ?? null);
}

/** Every variable and event id a layout references.
 *
 * Read from the *whole* node, not from a list of known prop names: widgets
 * bind variables through a dozen differently-named props (`objectSetVariable`,
 * `subjectVariable`, `selectionVariable`, …), and a list of them would go
 * stale the first time somebody adds a widget - silently, by reporting a
 * variable as unused because nothing knew to look at the prop that reads it.
 */
function referenced(document: Doc): Set<string> {
  const seen = new Set<string>();
  const walk = (value: unknown) => {
    if (typeof value === "string") {
      seen.add(value);
      // `{{v_id}}` interpolation, which is how text and action values read a
      // variable without naming it in a prop of its own.
      for (const match of value.matchAll(/\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g)) {
        seen.add(match[1]!);
      }
      return;
    }
    if (Array.isArray(value)) return value.forEach(walk);
    if (value && typeof value === "object") return Object.values(value).forEach(walk);
  };
  walk(section(document, "layout"));
  // An event's config names variables too - a `set_variable` effect writes one
  // and a `run_action` reads its subject from one.
  walk(section(document, "events"));
  return seen;
}

function diffMap(
  before: Record<string, Record<string, unknown>>,
  after: Record<string, Record<string, unknown>>,
  label: (entry: Record<string, unknown> | undefined, id: string) => string,
): Change[] {
  const changes: Change[] = [];
  for (const id of Object.keys(after)) {
    if (!(id in before)) {
      changes.push({ id, label: label(after[id], id), kind: "added" });
    } else if (differs(before[id], after[id])) {
      changes.push({ id, label: label(after[id], id), kind: "changed" });
    }
  }
  for (const id of Object.keys(before)) {
    if (!(id in after)) changes.push({ id, label: label(before[id], id), kind: "deleted" });
  }
  return changes;
}

export function diffModules(before: Doc, after: Doc): ModuleChangelog {
  const beforeLayout = section(before, "layout");
  const afterLayout = section(after, "layout");

  const widgets: Change[] = [];
  for (const id of Object.keys(afterLayout)) {
    const label = widgetName(afterLayout[id]);
    if (!(id in beforeLayout)) {
      widgets.push({ id, label, kind: "added" });
      continue;
    }
    // **Moved is checked before changed, and the props are compared without
    // the position.** A node carries its parent and its siblings' order inside
    // the same object, so a plain deep comparison calls every move a change
    // and p.193 lists them as different things.
    const was = position(beforeLayout, id);
    const now = position(afterLayout, id);
    const propsChanged = differs(beforeLayout[id]?.props, afterLayout[id]?.props);
    if (propsChanged) {
      widgets.push({ id, label, kind: "changed" });
    } else if (was.parent !== now.parent || was.index !== now.index) {
      widgets.push({ id, label, kind: "moved" });
    }
  }
  for (const id of Object.keys(beforeLayout)) {
    if (!(id in afterLayout)) {
      widgets.push({ id, label: widgetName(beforeLayout[id]), kind: "deleted" });
    }
  }

  const variables = diffMap(
    section(before, "variables"),
    section(after, "variables"),
    (entry, id) => String(entry?.label || id),
  );
  // p.193's "newly unused": declared in both versions, read in the old one and
  // in nothing now. Not a deletion - the variable is still there, and saying
  // "deleted" would send somebody looking for a removal that never happened.
  const readBefore = referenced(before);
  const readAfter = referenced(after);
  for (const id of Object.keys(section(after, "variables"))) {
    if (!(id in section(before, "variables"))) continue;
    if (readBefore.has(id) && !readAfter.has(id)) {
      variables.push({
        id,
        label: String(section(after, "variables")[id]?.label || id),
        kind: "unused",
      });
    }
  }

  const events = diffMap(
    section(before, "events"),
    section(after, "events"),
    (entry, id) => {
      const effects = entry?.effects;
      const first = Array.isArray(effects) ? (effects[0] as Record<string, unknown>) : undefined;
      return first ? String(first.type ?? id) : id;
    },
  );

  return { widgets, variables, events };
}

/** True when nothing changed at all - the case a panel has to say something
 * about rather than drawing three empty lists. */
export function isEmptyChangelog(changelog: ModuleChangelog): boolean {
  return (
    changelog.widgets.length === 0 &&
    changelog.variables.length === 0 &&
    changelog.events.length === 0
  );
}

// ---- p.193's JSON diff: "the exact modifications" ---------------------------

/** One leaf that differs, named by where it sits.
 *
 * **Leaf by leaf rather than line by line.** p.193 says "JSON diffs", and the
 * obvious reading is two pretty-printed blocks with a line gutter - but a line
 * diff of re-serialised JSON reports noise nobody changed: a key inserted
 * earlier in an object shifts every line under it, and re-indenting a nested
 * object rewrites lines whose values are identical. A path and its two values
 * is the modification itself, and it is the same answer however the two
 * documents happen to be serialised.
 */
export interface FieldChange {
  /** Dotted, with array indices in brackets: `props.columns[1]`. */
  path: string;
  kind: "added" | "removed" | "changed";
  /** Absent on an addition. */
  before?: unknown;
  /** Absent on a removal. */
  after?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function join(prefix: string, key: string): string {
  return prefix ? `${prefix}.${key}` : key;
}

/** Every leaf that differs between two values.
 *
 * Recurses through objects and arrays and stops at anything else, so the paths
 * name the smallest thing that actually changed. Two values of *different*
 * shapes - an object replaced by a string, say - are one change at that path
 * rather than a removal of every leaf beneath it followed by an addition,
 * because "this became a string" is what happened.
 */
export function fieldChanges(before: unknown, after: unknown, prefix = ""): FieldChange[] {
  if (!differs(before, after)) return [];

  if (isRecord(before) && isRecord(after)) {
    const changes: FieldChange[] = [];
    // Every key of either side, in the after-document's order first so a
    // reader sees the current shape and then whatever it lost.
    const keys = [...Object.keys(after), ...Object.keys(before).filter((k) => !(k in after))];
    for (const key of keys) {
      changes.push(...fieldChanges(before[key], after[key], join(prefix, key)));
    }
    return changes;
  }

  if (Array.isArray(before) && Array.isArray(after)) {
    const changes: FieldChange[] = [];
    for (let i = 0; i < Math.max(before.length, after.length); i += 1) {
      changes.push(...fieldChanges(before[i], after[i], `${prefix}[${i}]`));
    }
    return changes;
  }

  if (before === undefined) return [{ path: prefix, kind: "added", after }];
  if (after === undefined) return [{ path: prefix, kind: "removed", before }];
  return [{ path: prefix, kind: "changed", before, after }];
}

/** Which part of a document a change came from, so the detail can be looked up
 * again without the panel knowing the document's shape. */
export type ChangeArea = "widgets" | "variables" | "events";

/** The exact modifications behind one entry in the changelog (p.193).
 *
 * A widget is compared on its **props**, matching `diffModules`: the parent and
 * sibling order live in the same object and are the move, not the change. A
 * move reports that position as its modification, because "it is in a
 * different section now" is the only thing that happened to it - and a move
 * with an empty detail would read as a panel that failed to load one.
 */
export function changeDetail(before: Doc, after: Doc, change: Change, area: ChangeArea): FieldChange[] {
  if (area !== "widgets") {
    const key = area === "variables" ? "variables" : "events";
    return fieldChanges(section(before, key)[change.id], section(after, key)[change.id]);
  }

  const beforeLayout = section(before, "layout");
  const afterLayout = section(after, "layout");
  if (change.kind === "moved") {
    const was = position(beforeLayout, change.id);
    const now = position(afterLayout, change.id);
    return fieldChanges(was, now);
  }
  return fieldChanges(beforeLayout[change.id]?.props, afterLayout[change.id]?.props);
}

// ---- p.193's visual hierarchy ----------------------------------------------

/** A node in the layout tree, carrying its change if it has one.
 *
 * `kind` is null for a node that did not itself change and is only present to
 * hold a changed descendant - which is the whole point of the hierarchy, and
 * the reason this is a tree rather than a list with indentation baked in.
 */
export interface ChangeNode {
  id: string;
  label: string;
  kind: ChangeKind | null;
  children: ChangeNode[];
}

/** The widget changes arranged as p.193's "visual hierarchy… how changes
 * relate to nested components".
 *
 * **Pruned to branches that contain a change.** The unpruned tree is the whole
 * module, and a changelog that redraws the module buries the four things that
 * moved; a flat list of only the changed nodes loses the nesting that the
 * sentence is asking for. So a node survives when it changed or when one of
 * its descendants did.
 *
 * Built from the *after* layout, with deleted nodes grafted back in at the
 * position they held in the *before* layout - otherwise the one kind of change
 * that has no node to hang off would be the one kind the hierarchy cannot
 * show.
 */
export function changeTree(before: Doc, after: Doc, widgets: Change[]): ChangeNode[] {
  const beforeLayout = section(before, "layout");
  const afterLayout = section(after, "layout");
  const kinds = new Map(widgets.map((change) => [change.id, change.kind]));

  const parentOf = (id: string): string => {
    const layout = id in afterLayout ? afterLayout : beforeLayout;
    return String(layout[id]?.parent ?? "");
  };

  // Children in the after-document's order, with each deleted node put back
  // beside the sibling it used to follow.
  const childrenOf = (id: string): string[] => {
    const live = ((afterLayout[id]?.nodes ?? []) as unknown[]).map(String);
    const gone = Object.keys(beforeLayout).filter(
      (child) => !(child in afterLayout) && String(beforeLayout[child]?.parent ?? "") === id,
    );
    return [...live, ...gone];
  };

  const build = (id: string): ChangeNode | null => {
    const children = childrenOf(id)
      .map(build)
      .filter((node): node is ChangeNode => node !== null);
    const kind = kinds.get(id) ?? null;
    if (kind === null && children.length === 0) return null;
    return {
      id,
      label: widgetName(afterLayout[id] ?? beforeLayout[id]),
      kind,
      children,
    };
  };

  // `ROOT` is Craft.js's own container. It is walked but never drawn - "the
  // module changed" is not news, and a tree with one permanent root wastes the
  // indentation the hierarchy exists to spend.
  const ids = new Set([...Object.keys(afterLayout), ...Object.keys(beforeLayout)]);
  const top = childrenOf("ROOT");
  const isRoot = (id: string): boolean => {
    if (id === "ROOT") return false;
    const parent = parentOf(id);
    return parent === "" || parent === "ROOT" || !ids.has(parent);
  };
  // ROOT's own children in the order it lists them, then anything orphaned -
  // a node whose parent is missing is a document this panel did not write, and
  // dropping its changes silently is the failure worth avoiding.
  const ordered = [
    ...top.filter(isRoot),
    ...[...ids].filter((id) => isRoot(id) && !top.includes(id)),
  ];
  return ordered
    .map(build)
    .filter((node): node is ChangeNode => node !== null);
}
