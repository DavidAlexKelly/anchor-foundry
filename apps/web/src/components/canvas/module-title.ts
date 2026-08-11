/** What a Workshop module puts in the browser tab (Foundry p.47).
 *
 * > "Set a title for the header. This title will also be used to set the
 * > browser tab or Carbon workspace tab name. **If a title is not set, the
 * > Workshop module resource name will be used instead.**"
 *
 * Pure and separate from the components that call it because the interesting
 * part is the fallback chain, not the assignment: a header with no title, a
 * module with no header at all, and a title that is only whitespace all have to
 * land on the resource name rather than on an empty tab.
 *
 * **Interpolation is deliberately not done here.** A header title may contain
 * `{{v_id}}`, which reads a resolved variable — and variables resolve after the
 * first render, so a tab that used them would flicker from `Site {{v_name}}` to
 * `Site Alpha` on every load. Foundry's own wording is about *the* title, and a
 * stable tab name is worth more than a live one.
 */

import { useEffect } from "react";

/** The Craft.js node map, as stored. */
type Layout = Record<string, unknown>;

function headerTitle(layout: Layout | null | undefined): string | null {
  for (const node of Object.values(layout ?? {})) {
    if (typeof node !== "object" || node === null) continue;
    const record = node as { type?: unknown; props?: Record<string, unknown> };
    // A node's `type` is `{resolvedName}` from the builder and a bare string in
    // hand-written and converted documents. Both are in the stored corpus.
    const type = record.type;
    const name =
      typeof type === "object" && type !== null
        ? (type as { resolvedName?: unknown }).resolvedName
        : type;
    if (String(name ?? "") !== "CanvasHeader") continue;
    const title = record.props?.title;
    if (typeof title === "string" && title.trim()) return title.trim();
  }
  return null;
}

export function moduleTitle(
  layout: Layout | null | undefined,
  resourceName: string,
): string {
  return headerTitle(layout) ?? resourceName;
}

/** Put a module's title in the browser tab for as long as it is on screen.
 *
 * **It assigns and does not restore**, which was not the first version. That
 * one captured `document.title` and put it back on unmount, on the assumption
 * that leaving a module would otherwise strand its name in the tab for every
 * page visited afterwards. Deleting the restore left `e2e/
 * test_module_tab_title.py` entirely green: Next re-applies the route's own
 * metadata (`Anchor`, from `app/layout.tsx`) on every client-side navigation,
 * so the tab is already correct by the time a restore would run. The check for
 * it is kept — it is what would catch this being wrong — but the code it was
 * written for is gone, because a line no test can fail is a line that is not
 * being maintained.
 *
 * Not unit-tested: it is a DOM effect, and this repo's line is pure functions
 * in vitest, browser behaviour in `e2e/`. `moduleTitle` above holds all the
 * logic and is tested there; the browser suite checks the tab itself.
 */
export function useModuleTitle(
  layout: Layout | null | undefined,
  resourceName: string,
): void {
  const title = moduleTitle(layout, resourceName);
  useEffect(() => {
    // Nothing to say yet: on the published route the module's name arrives
    // with the fetch, and blanking the tab in the meantime is worse than
    // leaving `Anchor` in place until it does.
    if (!title) return;
    document.title = title;
  }, [title]);
}
