/**
 * What the repository's command palette can do (§428; `code-repositories`
 * p.11).
 *
 * p.11 puts the palette under "the core functionalities available in your
 * Code Repository", so the commands are that list: get to a tab, switch a
 * branch, open a file, come back from a pinned commit. Nothing here is a new
 * capability — every one of these is a control already on the page, and the
 * palette is a second way to reach it. That is deliberate: a palette that
 * could do something no button could would be a feature hidden behind a key
 * nobody presses.
 *
 * **The tab list lives here rather than in `repository-app.tsx`** so that the
 * palette and the tab bar cannot disagree about what the tabs are (§292). A
 * seventh tab added to one and not the other is a tab the palette cannot
 * reach, and nothing would say so.
 *
 * **A command that cannot run is still built, disabled, with the reason.** The
 * alternative — leaving it out — makes the palette's list change shape as the
 * page does, so a reader who found "Back to branch" once and cannot find it
 * again learns that the palette is unreliable rather than that they are not
 * viewing a commit (§214).
 */

import type { Command } from "./command-palette";

// **`pulls` before `publish`, because that is the order the work happens in**
// and `code-repositories.md` §1 lists Pull requests before anything of ours.
// **`checks` beside `pulls`**, which is the order `code-repositories.md` §1
// lists them and the order the work happens in: propose, then see what ran.
export const TABS = [
  "files", "docs", "history", "branches", "pulls", "checks", "publish", "settings",
] as const;
export type Tab = (typeof TABS)[number];

export const TAB_LABELS: Record<Tab, string> = {
  files: "Files",
  // p.67's in-product documentation (§442). Beside Files, because it is a file
  // in the repository and the one the rest of the tab is read through.
  docs: "Docs",
  history: "History",
  branches: "Branches",
  pulls: "Pull requests",
  checks: "Checks",
  publish: "Publish",
  settings: "Settings",
};

/** What a hint has to add for each tab: the word somebody would type when
 *  they do not know what this product calls the tab. "diff" finds Pull
 *  requests, "log" finds History, "deploy" finds Publish.
 *
 *  **Every word here is written out again in the test**, which is not
 *  duplication for its own sake: a test that walked this table would lose a
 *  case whenever a word was deleted from it and go on passing, which is the
 *  shape of a check that cannot fail (§213). The list the test holds is what
 *  makes a deletion visible. */
const TAB_HINTS: Record<Tab, string[]> = {
  files: ["code", "tree", "editor"],
  docs: ["readme", "documentation"],
  history: ["commits", "log"],
  branches: ["merge"],
  pulls: ["pull requests", "proposals", "review", "diff"],
  checks: ["ci", "tests"],
  publish: ["deploy", "release"],
  settings: ["configuration", "policy"],
};

export interface RepositoryState {
  tab: Tab;
  /** The branch the page is showing. */
  branch: string;
  /** Every branch the repository has, in the order the bar lists them. */
  branches: readonly string[];
  /** Every path in the tree at the current ref. */
  files: readonly string[];
  /** The file open in the editor, if any. */
  openFile: string | null;
  /** True while the page is pinned to a commit rather than following a
   *  branch — which is when the branch picker is disabled. */
  pinned: boolean;
}

export interface RepositoryActions {
  goToTab: (tab: Tab) => void;
  switchBranch: (name: string) => void;
  openFile: (path: string) => void;
  backToBranch: () => void;
}

export function repositoryCommands(
  state: RepositoryState, actions: RepositoryActions,
): Command[] {
  const commands: Command[] = [];

  for (const tab of TABS) {
    commands.push({
      id: `tab:${tab}`,
      label: TAB_LABELS[tab],
      group: "Go to",
      hints: TAB_HINTS[tab],
      enabled: tab !== state.tab,
      note: "already here",
      run: () => actions.goToTab(tab),
    });
  }

  for (const name of state.branches) {
    commands.push({
      id: `branch:${name}`,
      label: `Switch to ${name}`,
      group: "Branch",
      hints: ["checkout", "ref"],
      // **Disabled while a commit is pinned, because the bar's picker is.**
      // Switching branch from here would work — it clears the commit on the
      // way — but a palette that quietly does something the visible control
      // refuses is a page with two answers to the same question (§214). The
      // way off a pinned commit is the command below, which says so.
      enabled: !state.pinned && name !== state.branch,
      note: state.pinned ? "viewing a commit" : "already on this branch",
      run: () => actions.switchBranch(name),
    });
  }

  for (const path of state.files) {
    commands.push({
      id: `file:${path}`,
      label: path,
      group: "Open",
      hints: ["file"],
      // Enabled even for the file already open: running it from another tab
      // is how you get back to the editor, which is a different thing from
      // opening the file and the reason this is not a no-op.
      enabled: true,
      run: () => actions.openFile(path),
    });
  }

  commands.push({
    id: "unpin",
    label: "Back to the branch",
    group: "Repository",
    hints: ["unpin", "leave commit", "latest"],
    enabled: state.pinned,
    note: "not viewing a commit",
    run: () => actions.backToBranch(),
  });

  return commands;
}
