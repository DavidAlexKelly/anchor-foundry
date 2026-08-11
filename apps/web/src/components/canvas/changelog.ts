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
 * **What is deliberately not built:** the JSON diff view and the visual
 * hierarchy p.193 also describes. This answers *what* changed; showing the
 * exact modification is a second piece of work, and the rebasing UI that p.193
 * says reuses this panel needs branching first, which we do not have.
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
