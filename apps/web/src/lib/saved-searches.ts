/**
 * What the saved-searches list says when it is empty (§310).
 *
 * A pure module for two sentences, and the reason is a regression it is here
 * to make impossible. §308 asserted this empty state in a browser test, and
 * the only way to *have* an empty one is a workspace nobody has saved a search
 * in — so the test created a workspace. `workspaces.list_for_user` orders by
 * name, `Module` in the browser suite takes `workspaces[0]`, and the new
 * workspace sorted before the seeded one: every test built after it landed in
 * the wrong workspace, and the row persisted in the dev database so it poisoned
 * later runs too.
 *
 * **The lesson is not "name it carefully".** An empty state is a sentence, and
 * a sentence is the cheapest possible thing to check without a browser — the
 * browser was buying nothing and costing shared state. `explorer.ts` and
 * `sql-scratchpad.ts` already take this division; this is the same one, arrived
 * at the expensive way.
 */

/**
 * **Two absences with two remedies**, and only one is something the reader can
 * act on: an editor can make the list non-empty, and a viewer cannot — so
 * telling a viewer to "Save this search" points at a button they do not have.
 */
export function emptyReason(canEdit: boolean): string {
  return canEdit
    ? "None yet. Search for something, then Save this search — everyone in the workspace sees it."
    : "None yet. An editor can save one, and it appears here for everybody.";
}
