/**
 * The open set: several files at once in the editor (§282;
 * `code-repositories.md` §2.3, "the single biggest thing making ours feel
 * unlike an IDE").
 *
 * §281 shipped first for a stated reason — *"tabs are what make the loss
 * expensive"* — and the order paid off twice. It found a bug that tabs would
 * have multiplied, and it makes the design of this module smaller than it
 * would otherwise have been:
 *
 * **The open set is not persisted, and does not need to be, because everything
 * expensive in it already is.** The tab strip is navigation; the work is the
 * drafts, and those survive a reload under their own key. So on a reload the
 * strip is *rebuilt* — a tab for every file you have uncommitted work in, plus
 * the one your link points at. A file you opened, read, and did not change is
 * a click away in the tree, and there is no second store that can come back
 * disagreeing with the first about what you were doing.
 *
 * That gives the one invariant worth enforcing: **a file with a draft is
 * always open.** A draft in a closed tab would be work you cannot see and
 * cannot reach, which is the failure §281 was about, arriving by another road.
 */

/**
 * The strip to open with, given what was found in storage and where the link
 * points.
 *
 * Deletions are not included even though they are drafts: a deleted file has
 * no content, so its tab would be a tab that cannot show anything. It is still
 * an uncommitted change and the commit bar still counts it — the tab strip is
 * just not where it can be looked at.
 *
 * Sorted, so that two reloads of the same state produce the same strip.
 */
export function initialTabs(
  drafts: Record<string, string | null>,
  openPath: string | undefined,
): string[] {
  const tabs = Object.entries(drafts)
    .filter(([, content]) => content !== null)
    .map(([path]) => path)
    .sort();
  if (openPath !== undefined && !tabs.includes(openPath)) tabs.push(openPath);
  return tabs;
}

/**
 * Open a path.
 *
 * **A path already open is not opened twice, and does not move.** Reordering
 * the strip under somebody's cursor to put the current file last would mean
 * the tab you just clicked is never where you left it, which is worse than the
 * ordering being arbitrary.
 */
export function openTab(tabs: string[], path: string): string[] {
  return tabs.includes(path) ? tabs : [...tabs, path];
}

/**
 * Close a path, and say what to look at instead.
 *
 * **The neighbour to the right, falling back to the left.** Closing tabs is
 * something people do working forwards through a list; selecting the first tab
 * instead would throw them back to the start of the list they are working
 * through. Closing a tab that is not the active one leaves the active one
 * alone — that is the whole point of closing it.
 */
export function closeTab(
  tabs: string[],
  path: string,
  active: string | undefined,
): { tabs: string[]; active: string | undefined } {
  const at = tabs.indexOf(path);
  if (at === -1) return { tabs, active };
  const next = tabs.filter((p) => p !== path);
  if (path !== active) return { tabs: next, active };
  // `at` is where the closed tab was, so `next[at]` is the one that was to its
  // right. When it was last, `next[at]` is undefined and the left neighbour is
  // the end of what remains.
  return { tabs: next, active: next[at] ?? next[next.length - 1] };
}

/**
 * Drop tabs for files that are no longer there, keeping the order of the rest.
 *
 * A path leaves the working set when it is deleted, and when a branch switch
 * or a commit brings a tree that never had it. A tab pointing at nothing would
 * render an empty editor that looks like a file whose contents failed to load.
 */
export function pruneTabs(tabs: string[], paths: string[]): string[] {
  const present = new Set(paths);
  return tabs.filter((p) => present.has(p));
}

/**
 * What to write on a tab.
 *
 * The file name, because `src/transforms/daily_orders.sql` on six tabs is a
 * strip of ellipses — **unless another open tab has the same file name**, in
 * which case both show their full path. Two tabs both reading `t.sql` is the
 * one case where the short label stops being a label at all, and it is exactly
 * the case a repository with `main/t.sql` and `test/t.sql` produces.
 *
 * The full path is on the tab's title and on the file header regardless, so
 * the short form never hides anything that cannot be recovered.
 */
export function tabLabel(path: string, tabs: string[]): string {
  const name = path.slice(path.lastIndexOf("/") + 1);
  const shared = tabs.some((p) => p !== path && p.slice(p.lastIndexOf("/") + 1) === name);
  return shared ? path : name;
}

/** Whether this tab has uncommitted work in it, so the strip can mark it. */
export function isDirty(
  path: string,
  committed: Record<string, string>,
  drafts: Record<string, string | null>,
): boolean {
  if (!(path in drafts)) return false;
  return (committed[path] ?? null) !== drafts[path];
}

/**
 * What the close button on this tab actually does.
 *
 * **Closing a dirty tab does not discard the edit**, and that has to be said
 * on the control rather than discovered at the commit. The draft lives in the
 * working set and in storage, not in the tab, so a file closed with unsaved
 * changes is still going into the next commit — somebody who closed it meaning
 * "undo this" and was not told would commit work they thought they had thrown
 * away. Discard is a different button and says so.
 */
export function closeLabel(path: string, dirty: boolean): string {
  return dirty ? `Close ${path} (keeps your unsaved changes)` : `Close ${path}`;
}

/**
 * What an empty editor pane means, which since §282 is two different things.
 *
 * Before tabs, arriving at a repository opened its first file, and an empty
 * pane could only mean the repository was empty. **That auto-open is gone
 * deliberately**: with a strip, "nothing open" has to be a state you can
 * actually be in, or closing the last tab is a control that lies. So the pane
 * now has to say which of the two it is — a repository with no files needs a
 * file, and a repository with files needs a click.
 */
export function emptyViewerNote(fileCount: number, pinned: boolean): string {
  if (fileCount === 0) {
    return pinned ? "This commit contains no files." : "No files yet.";
  }
  return "No file open. Choose one from the tree.";
}

/**
 * The active path, given the strip.
 *
 * The URL is the source of truth for which file is open — that is what makes
 * "look at this file on this branch" a link — but a URL can name a file that
 * is not in this tree at all: a stale bookmark, a branch switch, somebody
 * else's link. Falling back to the first tab keeps the editor showing
 * *something real* rather than an empty pane, and is what the file tree did
 * before there were tabs.
 */
export function activeTab(tabs: string[], openPath: string | undefined): string | undefined {
  if (openPath !== undefined && tabs.includes(openPath)) return openPath;
  return tabs[0];
}
