/**
 * The tabs of a configured full Object View (§695; `object-views` p.34-35,
 * `workshop` p.262-263).
 *
 * > "Each tab corresponds to a single workshop module. If only one tab is
 * > configured, the tab title will be hidden when viewing the Object View …
 * > Selecting the gear icon opens a dialog that allows you to add, reorder,
 * > rename, and delete Object View tabs." (object-views p.35)
 *
 * The server keeps the view's own module as the first tab, so a view saved
 * before tabs existed is a view of one tab.
 */

/** One tab as the dialog edits it. */
export interface TabDraft {
  title: string;
  canvas_app_id: string;
  subject_variable: string;
}

/** The server's bound: db 0135's positions 1-19 after the view's own module. */
export const MAX_TABS = 20;

/** Which tab shows: the reader's pick while it still exists, else workshop
 * p.263's "Initial object view tab ID" while that exists, else the first -
 * "If not configured, the first tab will show by default." */
export function shownTab<T extends { id: string }>(
  tabs: T[], picked: string | null, initial: string | null,
): T | undefined {
  return tabs.find((t) => t.id === picked) ?? tabs.find((t) => t.id === initial) ?? tabs[0];
}

/** p.35: "If only one tab is configured, the tab title will be hidden", and
 * workshop p.262's Hide tabs: "Tabs are always hidden for object views with a
 * single tab, so this is only applicable to object views with multiple tabs." */
export function showsTabStrip(count: number, hideTabs: boolean): boolean {
  return count > 1 && !hideTabs;
}

/** p.35's reorder: the tab at `index` swapped with its neighbour, or the list
 * unchanged at either end. */
export function moveTab<T>(tabs: T[], index: number, by: -1 | 1): T[] {
  const to = index + by;
  if (index < 0 || index >= tabs.length || to < 0 || to >= tabs.length) return tabs;
  const next = [...tabs];
  [next[index], next[to]] = [next[to]!, next[index]!];
  return next;
}

/** Why the dialog cannot save yet, in a sentence, or null. The server refuses
 * each of these too; this is so the refusal is rarely how somebody finds out. */
export function tabsProblem(tabs: TabDraft[]): string | null {
  if (tabs.length === 0) return "Add a tab, or use the standard view";
  if (tabs.length > MAX_TABS) return `An object view has at most ${MAX_TABS} tabs`;
  for (const [n, tab] of tabs.entries()) {
    if (!tab.canvas_app_id) return `Choose a module for tab ${n + 1}`;
    if (!tab.subject_variable) return `Choose the variable that receives the object in tab ${n + 1}`;
    // The first tab's title may be blank: it is then its module's name.
    if (n > 0 && !tab.title.trim()) return `Give tab ${n + 1} a title`;
  }
  return null;
}

/** A saved view's tabs as the dialog starts them. The first tab's title is
 * the view's own, blank when it is the module's name, so saving without
 * touching it keeps following the module's name. */
export function draftsOf(view: {
  title: string;
  tabs: { title: string; canvas_app_id: string; subject_variable: string }[];
} | null): TabDraft[] {
  if (!view) return [{ title: "", canvas_app_id: "", subject_variable: "" }];
  return view.tabs.map((tab, n) => ({
    title: n === 0 ? view.title : tab.title,
    canvas_app_id: tab.canvas_app_id,
    subject_variable: tab.subject_variable,
  }));
}

/** workshop p.263's **Interface configuration** (§710): "a mapping from the
 * current module's variables to an object view tab's module interface".
 *
 * Held flat as `{"<tab id>:<external id>": host variable id}` - one map for
 * every tab of the view, so it joins the catalogue of mapping props the
 * server and the browser already read as references (`MAPPING_REFERENCE_PROPS`)
 * rather than needing a nested reader of its own. */
export function interfaceKey(tabId: string, externalId: string): string {
  return `${tabId}:${externalId}`;
}

/** One tab's bindings, as `CanvasParameterProvider`'s link wants them: the
 * tab module's variable id -> the host's. An external ID the module no longer
 * publishes drops out, as an embed's does; so does the view's subject, which
 * the object itself supplies (p.261) and a mapping must not outvote. */
export function tabBindings(
  mapping: Record<string, unknown> | null | undefined,
  tabId: string,
  declared: Record<string, { id: string; external_id?: string | null; interface?: unknown }>,
  subjectVariable: string,
): Record<string, string> {
  const out: Record<string, string> = {};
  const prefix = `${tabId}:`;
  for (const [key, hostVid] of Object.entries(mapping ?? {})) {
    if (!key.startsWith(prefix) || typeof hostVid !== "string" || !hostVid) continue;
    const externalId = key.slice(prefix.length);
    const target = Object.values(declared).find(
      (v) => v.interface && v.external_id === externalId,
    );
    if (target && target.id !== subjectVariable) out[target.id] = hostVid;
  }
  return out;
}
