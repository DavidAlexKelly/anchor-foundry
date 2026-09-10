"use client";

/** The repository application (ROADMAP.md phase 2, section 2).
 *
 * Four tabs, and they are the four questions a repository has to answer: what
 * is in it (Files, with the editor and Preview), what happened to it (History),
 * what else it could be (Branches, and the merge), and what it *does* to this
 * project (Publish).
 *
 * A repository is a tree at a *ref*, so the ref is in the URL alongside the
 * open file. "Look at this file on this branch" has to be a link, or reviewing
 * anything means describing where to click.
 *
 * Nothing here makes a commit live. Publishing is a separate act on its own
 * tab, and until somebody performs it a commit changes nothing about what runs
 * - which is the property decision 0003 was chosen for.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { Fragment, useEffect, useMemo, useState } from "react";
import { useUrlState } from "@/components/use-url-state";
import {
  discardQuestion,
  draftKey,
  readDrafts,
  saveWarning,
  writeDrafts,
} from "@/lib/editor-drafts";
import {
  activeTab,
  closeLabel,
  closeTab,
  emptyViewerNote,
  initialTabs,
  isDirty,
  openTab,
  pruneTabs,
  tabLabel,
} from "@/lib/editor-tabs";
import Link from "next/link";
import {
  ApiError,
  api as platformApi,
  code as codeApi,
  repositories as repoApi,
  resources as resourceApi,
} from "@/lib/api";
import { DESCRIPTION_TEMPLATE, ReviewSurface } from "@/components/code/review-surface";
import { describe as describeProposal, emptyReason, forRepository } from "@/lib/pull-requests";
import {
  hasChanges,
  headline,
  isGap,
  versionLabel,
  versionsEmptyNote,
  withContext,
} from "@/lib/file-changes";
import {
  emptyNote as problemsEmptyNote,
  isSourceFile,
  location as problemLocation,
  revealLine,
  summary as problemsSummary,
} from "@/lib/problems";
// Aliased, because `branch-checks.ts` next door exports a `verdict` and a
// `worstFirst` of its own. The two modules answer the same *shape* of question
// about different things - a branch's checks, a run's tests - so the collision
// is a sign the naming is right rather than a sign one of them should move.
// Aliased where they collide with this file's other vocabulary: `subtitle` and
// `emptyReason` are words several of these modules use about their own subject.
import {
  checksAreAProblem,
  checksLabel,
  proposalStateLabel,
  proposeProblem,
  pullRequestSlot,
} from "@/lib/branch-columns";
import {
  EXPLORER_KINDS,
  emptyReason as explorerEmptyReason,
  needsWorkspaceLevel,
  openHref as explorerHref,
  sections as explorerSections,
  shouldSearch,
  subtitle as explorerSubtitle,
} from "@/lib/explorer";
import {
  canCreate as canCreateTag,
  deleteQuestion as tagDeleteQuestion,
  emptyReason as tagsEmptyReason,
  nameProblem as tagNameProblem,
  subtitle as tagSubtitle,
  willPin,
} from "@/lib/tags";
import {
  andMore,
  mostRecent,
  namedFailures,
  // Aliased for the same reason the `test-runs` imports above are: this tab
  // already has a `verdict` and a `status` from `branch-checks.ts`.
  status as testStatusOf,
  summary as testSummary,
} from "@/lib/test-runs-in-checks";
import {
  canEditProject,
  durationLabel as testDuration,
  isAProblem as testsAreAProblem,
  runLabel,
  shouldPoll,
  target as testTarget,
  verdict as testVerdict,
  worstFirst as worstTestsFirst,
} from "@/lib/test-runs";
import {
  checkTarget,
  emptyReason as checksEmptyReason,
  verdict,
  verdictNote,
  worstFirst,
} from "@/lib/branch-checks";
import {
  isProtected,
  protectedReason,
  suggestedSandboxName,
} from "@/lib/protected-branches";
import {
  canChangeReviewPolicy,
  reviewPolicyEffect,
  reviewPolicyLockedReason,
  reviewPolicyScopeNote,
} from "@/lib/repo-settings";
import type {
  PublishPlan,
  RepositoryBranch,
  RepositoryBranchSummary,
  RepositoryComparison,
  RepositoryFileChanges,
  RepositoryFileVersion,
  RepositoryProblem,
  RepositoryTree,
  ResolvedResource,
  TransformPreview,
} from "@/lib/types";

// Monaco touches `window` at module scope and is ~1 MB nothing else needs.
const CodeEditor = dynamic(
  () => import("@/components/code-editor").then((m) => m.CodeEditor),
  { ssr: false, loading: () => <div className="code-editor-loading">Loading editor…</div> },
);

// **`pulls` before `publish`, because that is the order the work happens in**
// and `code-repositories.md` §1 lists Pull requests before anything of ours.
// **`checks` beside `pulls`**, which is the order `code-repositories.md` §1
// lists them and the order the work happens in: propose, then see what ran.
const TABS = ["files", "history", "branches", "pulls", "checks", "publish", "settings"] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  files: "Files",
  history: "History",
  branches: "Branches",
  pulls: "Pull requests",
  checks: "Checks",
  publish: "Publish",
  settings: "Settings",
};

export function RepositoryApplication({ resource }: { resource: ResolvedResource }) {
  const url = useUrlState();

  const wid = resource.workspace_id;
  const pid = resource.project_id!;
  const rid = resource.kind_id;

  const tab = url.oneOf("tab", TABS, "files");
  const branch = url.get("branch") ?? undefined;
  const commitId = url.get("commit") ?? undefined;
  const openPath = url.get("file") ?? undefined;

  const setParams = url.set;

  const repo = useQuery({
    queryKey: ["repo", rid],
    queryFn: () => repoApi.get(wid, pid, rid),
  });
  const branches = useQuery({
    queryKey: ["repo-branches", rid],
    queryFn: () => repoApi.branches(wid, pid, rid),
  });
  const tree = useQuery({
    queryKey: ["repo-tree", rid, branch, commitId],
    queryFn: () => repoApi.tree(wid, pid, rid, { branch, commitId }),
  });

  const current = branch ?? repo.data?.default_branch ?? "main";

  return (
    <div className="repo-app">
      <div className="repo-bar">
        <label className="repo-ref">
          Branch
          <select
            value={commitId ? "" : current}
            disabled={!!commitId}
            onChange={(e) => setParams({ branch: e.target.value, file: undefined })}
          >
            {(branches.data ?? []).map((b) => (
              <option key={b.id} value={b.name}>
                {b.name}
              </option>
            ))}
            {/* A repository nobody has committed to has no branch row at all,
                so the default has to be offered even though it does not
                exist yet. */}
            {!branches.data?.some((b) => b.name === current) && (
              <option value={current}>{current}</option>
            )}
          </select>
        </label>

        {commitId && (
          <span className="repo-pinned">
            viewing commit <code>{commitId.slice(0, 8)}</code>
            <button type="button" onClick={() => setParams({ commit: undefined })}>
              back to branch
            </button>
          </span>
        )}

        <div className="spacer" />
        <nav className="ds-tabs repo-tabs">
          {(TABS as readonly Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              className={`ds-tab${t === tab ? " on" : ""}`}
              aria-current={t === tab}
              onClick={() => setParams({ tab: t })}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </nav>
      </div>

      {tab === "files" && (
        <FilesTab
          wid={wid}
          pid={pid}
          rid={rid}
          branch={current}
          pinned={!!commitId}
          tree={tree.data}
          pending={tree.isPending}
          error={tree.error as Error | null}
          openPath={openPath}
          onOpen={(path) => setParams({ file: path })}
          defaultBranch={repo.data?.default_branch ?? "main"}
          branches={branches.data}
          onSwitchBranch={(name) => setParams({ branch: name, commit: undefined })}
        />
      )}
      {tab === "history" && (
        <HistoryTab
          wid={wid}
          pid={pid}
          rid={rid}
          branch={current}
          onOpenCommit={(id) => setParams({ commit: id, tab: "files", file: undefined })}
        />
      )}
      {tab === "settings" && <SettingsTab wid={wid} pid={pid} />}
      {tab === "checks" && (
        <ChecksTab
          wid={wid}
          pid={pid}
          rid={rid}
          branch={current}
          defaultBranch={repo.data?.default_branch ?? "main"}
          onOpenProposal={(id) => setParams({ tab: "pulls", proposal: id })}
        />
      )}
      {tab === "pulls" && (
        <PullRequestsTab
          wid={wid}
          pid={pid}
          rid={rid}
          openId={url.get("proposal") ?? undefined}
          onOpen={(id) => setParams({ proposal: id })}
          onClose={() => setParams({ proposal: undefined })}
        />
      )}
      {tab === "publish" && (
        <PublishTab
          wid={wid}
          pid={pid}
          rid={rid}
          branch={current}
          pinned={!!commitId}
        />
      )}
      {tab === "branches" && (
        <BranchesTab
          wid={wid}
          pid={pid}
          rid={rid}
          current={current}
          defaultBranch={repo.data?.default_branch ?? "main"}
          branches={branches.data}
          pending={branches.isPending}
          onSwitch={(name) =>
            setParams({ branch: name, commit: undefined, file: undefined, tab: "files" })
          }
          onOpenProposal={(id) => setParams({ tab: "pulls", proposal: id })}
          onSwitchToPublish={(name) =>
            // p.16's "Propose changes". The publish tab is where a proposal is
            // made here, so the button takes you there on that branch rather
            // than creating one from a list row - a proposal needs a summary,
            // and a button that made one without asking would put an empty
            // review in front of somebody.
            setParams({ branch: name, tab: "publish", commit: undefined })
          }
        />
      )}
    </div>
  );
}

function FilesTab({
  wid,
  pid,
  rid,
  branch,
  pinned,
  tree,
  pending,
  error,
  openPath,
  onOpen,
  defaultBranch,
  branches,
  onSwitchBranch,
}: {
  wid: string;
  pid: string;
  rid: string;
  branch: string;
  pinned: boolean;
  tree: RepositoryTree | undefined;
  pending: boolean;
  error: Error | null;
  openPath: string | undefined;
  onOpen: (path: string | undefined) => void;
  defaultBranch: string;
  branches: RepositoryBranch[] | undefined;
  onSwitchBranch: (name: string) => void;
}) {
  const queryClient = useQueryClient();
  // The working set: the committed tree with unsaved edits laid over it. Kept
  // apart from the query cache so a refetch cannot silently discard typing,
  // and reset only when the ref changes - switching branch or commit is a
  // deliberate act, and losing edits to it is the user's own decision.
  const [edits, setEdits] = useState<Record<string, string | null>>({});
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [draftWarning, setDraftWarning] = useState<string | null>(null);

  // **Persisted, keyed by repository and branch** (§281). This state was the
  // only home for uncommitted work, so a reload lost it - and
  // `code-repositories.md` §2.3 asks for persistence *before* multi-file tabs
  // for exactly that reason: tabs are what make the loss expensive.
  const key = draftKey(rid, branch);

  // **Loaded on the branch, not on the commit.** This effect used to clear
  // `edits` whenever `tree.commit_id` changed, which is also what happens when
  // *somebody else* commits and the tree refetches - so a colleague landing a
  // change silently discarded your typing. Keying it to the branch keeps that
  // from happening, and losing edits on a deliberate branch switch is still
  // the branch switch's doing. Your own commit clears them explicitly below,
  // which is the only case that should.
  // **`loaded` is not bookkeeping - without it the save destroys the draft.**
  // `setEdits` is batched, so on the first commit the save effect below runs
  // with `edits` still `{}` - and writing an empty map *removes the key*. The
  // draft was being deleted on mount, before the load it was waiting for could
  // apply. A ref would not fix it either: a ref assigned in the load effect is
  // visible to the save effect in the same commit, which is exactly the pass
  // that must not write. It has to be state, so the two land together.
  const [loaded, setLoaded] = useState<string | null>(null);
  // **The open set is rebuilt, not restored** (§282). Everything expensive in
  // the strip is already persisted - the drafts - so a tab for every file with
  // uncommitted work, plus the one the link names, gets the session back
  // without a second store that can return disagreeing with the first.
  const [tabs, setTabs] = useState<string[]>([]);
  useEffect(() => {
    const drafts = readDrafts(key);
    setEdits(drafts);
    setTabs(initialTabs(drafts, openPath));
    setLoaded(key);
    setMessage("");
    setDraftWarning(null);
    // `openPath` is deliberately not a dependency: this seeds the strip when
    // the *branch* changes, and a later file change is the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // **There is no effect on `openPath` here, and that is deliberate** (§213).
  //
  // The obvious one to write: a deep link, the back button and a jump from the
  // History tab all move `?file=`, so the strip looks like it needs to follow
  // the URL wherever it goes. It was written, and it was the *only* way a file
  // opened - which is how §282 shipped a bug that took a browser test to find.
  // An effect keyed on a value only fires when the value **changes**, and
  // `router.replace` does not land synchronously: close the last tab and click
  // the same file in the tree before the router catches up, and `openPath`
  // reads `src/a.sql` the whole way through, cleared and set again inside a
  // window React never observes. The tab never reopened while the address bar
  // went on naming it.
  //
  // Once `openFile` below does its own opening, the effect had nothing left to
  // catch. Every route that sets `?file=` to an actual path goes through it;
  // the other three call sites (the branch select, `onOpenCommit`, `onSwitch`)
  // only ever clear it, which the effect ignored anyway. And `useUrlState`
  // replaces rather than pushes, so within this application there are no
  // history entries to go back *to* - a fresh URL is a fresh mount, and the
  // seed above handles that. Keeping it would have been a second mechanism
  // that no test could reach, which is the shape §280 deleted too.

  // Written on every change. `localStorage` is synchronous and these are small,
  // and the alternative - debouncing - would mean a reload in the debounce
  // window loses exactly the keystrokes somebody just typed.
  useEffect(() => {
    if (loaded !== key) return;
    setDraftWarning(saveWarning(writeDrafts(key, edits)));
  }, [key, edits, loaded]);

  const committed = tree?.files ?? {};
  const working = useMemo(() => {
    const merged: Record<string, string> = { ...committed };
    for (const [path, content] of Object.entries(edits)) {
      if (content === null) delete merged[path];
      else merged[path] = content;
    }
    return merged;
  }, [committed, edits]);

  const dirty = Object.entries(edits).some(
    ([path, content]) => (committed[path] ?? null) !== content,
  );

  // **The protected-branch rule** (§284; `code-repositories.md` §2.1, p.12).
  // The server owns it (`assert_branch_is_writable`); this decides what to
  // offer, which is §214's division. Shared query key with the Settings tab,
  // so flipping the gate there changes this without a second fetch.
  const policy = useQuery({
    queryKey: ["code-review-policy", pid],
    queryFn: () => codeApi.reviewPolicy(wid, pid),
  });
  const branchContext = {
    branch,
    defaultBranch,
    reviewRequired: policy.data?.require_code_review ?? false,
    // A branch with nothing on it is not protected: the first commit is how a
    // repository starts, not an edit to one.
    hasCommits: (tree?.commit_id ?? null) !== null,
  };
  const locked = !pinned && isProtected(branchContext);

  // **p.14's Problems helper** (§286). Asked for rather than live: it is a
  // round trip, and one on every keystroke would be a panel that costs more
  // than it tells you. The button says when the answer was last true.
  const [problemsOpen, setProblemsOpen] = useState(false);
  const [reveal, setReveal] = useState<{ line: number } | undefined>();
  const problems = useQuery({
    queryKey: ["repo-problems", rid, branch, edits],
    queryFn: () => repoApi.problems(wid, pid, rid, { branch, overrides: edits }),
    enabled: problemsOpen && !pinned,
  });

  const commit = useMutation({
    mutationFn: () =>
      repoApi.commit(wid, pid, rid, { branch, files: working, message }),
    onSuccess: () => {
      // The drafts are committed now, so they stop being drafts. `setEdits({})`
      // is what removes the stored key, through the effect above.
      setEdits({});
      setMessage("");
      setFailure(null);
      queryClient.invalidateQueries({ queryKey: ["repo-tree", rid] });
      queryClient.invalidateQueries({ queryKey: ["repo-commits", rid] });
      queryClient.invalidateQueries({ queryKey: ["repo-branches", rid] });
    },
    onError: (e: Error) => setFailure(e.message),
  });

  /** Commit this work to a new sandbox branch instead.
   *
   * **The alternative was a read-only editor, and it is worse.** People open a
   * file, edit it, and think about branches afterwards; an editor that refused
   * the typing would be right about the rule and wrong about the work. §214
   * asks not to take typing you will refuse to keep - so the typing is kept,
   * on a branch that can hold it, and §283 is what makes that not a detour:
   * applying the pull request moves the default branch to this commit.
   */
  const commitToSandbox = useMutation({
    mutationFn: async () => {
      const name = suggestedSandboxName((branches ?? []).map((b) => b.name));
      await repoApi.createBranch(wid, pid, rid, { name, from_branch: branch });
      await repoApi.commit(wid, pid, rid, { branch: name, files: working, message });
      return name;
    },
    onSuccess: (name) => {
      // Cleared *before* the switch: these drafts are committed now, and they
      // belong to the branch being left rather than the one being joined.
      setEdits({});
      setMessage("");
      setFailure(null);
      queryClient.invalidateQueries({ queryKey: ["repo-branches", rid] });
      queryClient.invalidateQueries({ queryKey: ["repo-tree", rid] });
      queryClient.invalidateQueries({ queryKey: ["repo-commits", rid] });
      onSwitchBranch(name);
    },
    onError: (e: Error) => setFailure(e.message),
  });

  if (pending) return <p className="state">Loading files…</p>;
  if (error) return <p className="state error">{error.message}</p>;

  const paths = Object.keys(working).sort();
  // Pruned on the way out rather than in an effect: a file leaves the working
  // set when it is deleted and when a branch switch brings a tree that never
  // had it, and deriving means the strip cannot lag behind either.
  const open = pruneTabs(tabs, paths);
  const selected = activeTab(open, openPath);
  const source = selected === undefined ? undefined : working[selected];
  // Editing is against a branch. A pinned commit is history, and history that
  // could be typed into would stop being a record of what happened.
  const readOnly = pinned;

  /** Open a file: in the strip and in the URL, in that order.
   *
   * Both, rather than letting the URL effect above do the opening, because the
   * router is asynchronous and a file re-opened before a close has landed is a
   * `?file=` that never changed - which an effect cannot see. */
  function openFile(path: string) {
    setTabs((current) => openTab(current, path));
    onOpen(path);
  }

  /** Close a tab, and go wherever `closeTab` says.
   *
   * **This does not discard the edit**, which is why the button says so: the
   * draft lives in the working set and in storage, not in the tab, so a file
   * closed with unsaved changes is still going into the next commit. */
  function close(path: string) {
    const next = closeTab(open, path, selected);
    setTabs(next.tabs);
    if (next.active !== selected) onOpen(next.active);
  }

  function addFile() {
    const path = window.prompt("New file path", "src/new.sql");
    if (!path) return;
    if (paths.includes(path)) {
      setFailure(`${path} already exists`);
      return;
    }
    setEdits((c) => ({ ...c, [path]: "" }));
    openFile(path);
  }

  /** Delete a file, and leave the strip where closing its tab would.
   *
   * Deleting is two things at once - the file goes and its tab goes - and the
   * second is what makes the neighbour rule matter: without it the deletion
   * drops you back on the first tab, which is rarely the one you were working
   * through. */
  function deleteFile(path: string) {
    setEdits((c) => ({ ...c, [path]: null }));
    close(path);
  }

  return (
    <div className="repo-work">
      {tree?.commit_id === null && !dirty && (
        <p className="state">
          This repository is empty. Add a file to make the first commit.
        </p>
      )}
      <div className="repo-split">
        <div>
          <nav className="repo-tree" aria-label="Files">
            {paths.map((path) => (
              <button
                key={path}
                type="button"
                className={`repo-file${path === selected ? " on" : ""}${
                  (committed[path] ?? null) !== (edits[path] ?? committed[path] ?? null)
                    ? " edited"
                    : ""
                }`}
                aria-current={path === selected}
                onClick={() => openFile(path)}
              >
                {path}
              </button>
            ))}
          </nav>
          {!readOnly && (
            <div className="repo-tree-actions">
              <button type="button" onClick={addFile}>
                New file
              </button>
              {selected !== undefined && (
                <button type="button" onClick={() => deleteFile(selected)}>
                  Delete file
                </button>
              )}
            </div>
          )}
        </div>

        <div className="repo-viewer">
          {/* **The strip is above the editor and outside the empty branch**,
              because tabs that vanished when the last one closed would leave
              nothing to explain where the files went. */}
          {open.length > 0 && (
            <div className="repo-tabs-strip" role="tablist" aria-label="Open files">
              {open.map((path) => {
                const dirty = isDirty(path, committed, edits);
                return (
                  <span
                    key={path}
                    className={`repo-tab${path === selected ? " on" : ""}${
                      dirty ? " edited" : ""
                    }`}
                  >
                    <button
                      type="button"
                      role="tab"
                      aria-selected={path === selected}
                      title={path}
                      onClick={() => openFile(path)}
                    >
                      {tabLabel(path, open)}
                    </button>
                    <button
                      type="button"
                      className="repo-tab-close"
                      aria-label={closeLabel(path, dirty)}
                      onClick={() => close(path)}
                    >
                      ×
                    </button>
                  </span>
                );
              })}
            </div>
          )}
          {selected !== undefined && source !== undefined ? (
            <>
              <div className="repo-file-head">
                <code>{selected}</code>
                <span className="soft">{source.split("\n").length} lines</span>
              </div>
              <div className="repo-editor">
                <CodeEditor
                  path={selected}
                  value={source}
                  readOnly={readOnly}
                  reveal={reveal}
                  onChange={(next) => setEdits((c) => ({ ...c, [selected]: next }))}
                />
              </div>
              {!pinned && (
                <ProblemsPanel
                  open={problemsOpen}
                  onToggle={() => setProblemsOpen((v) => !v)}
                  problems={problems.data?.problems}
                  pending={problems.isFetching}
                  error={problems.error as Error | null}
                  sourceFileCount={paths.filter(isSourceFile).length}
                  onOpen={(path, line) => {
                    openFile(path);
                    // A new object every time, so clicking the same problem
                    // twice scrolls back to it (§286).
                    setReveal(line === undefined ? undefined : { line });
                  }}
                />
              )}
              {!pinned && (
                <TestsPanel
                  wid={wid}
                  pid={pid}
                  rid={rid}
                  branch={branch}
                  working={working}
                  onOpen={(path, line) => {
                    openFile(path);
                    // A new object every time, so clicking the same failing
                    // test twice scrolls back to it (§286).
                    setReveal({ line });
                  }}
                />
              )}
              {!pinned && (
                <FileChangesPanel
                  wid={wid}
                  pid={pid}
                  rid={rid}
                  branch={branch}
                  path={selected}
                  // `source` *is* the working content: `working` is the
                  // committed tree with `edits` laid over it, and a path whose
                  // edit is `null` is not in `paths`, so it cannot be the
                  // selected file. A ternary here read as though it might be
                  // something else (§213).
                  content={source}
                />
              )}
              <PreviewPanel
                wid={wid}
                pid={pid}
                rid={rid}
                path={selected}
                content={source}
              />
            </>
          ) : (
            <p className="state">{emptyViewerNote(paths.length, readOnly)}</p>
          )}
          {/* **Outside the "is a file open" branch, unlike every panel above
              it**, and that is the difference rather than an oversight. Those
              four answer questions *about the current file* — its problems,
              its tests, what changed in it, what it produces — so without one
              they have no subject. The Explorer's subject is the project, and
              the moment it is most useful is before there is a file: you open
              it to find out what to write. An empty repository showing no way
              to see what the project contains would be the panel missing
              exactly when it was wanted.

              Offered to a viewer too, unlike Problems, Tests and File Changes:
              it reads a listing and writes nothing, so there is no control
              here that a viewer would be refused (§214). */}
          <ExplorerPanel wid={wid} pid={pid} />
        </div>
      </div>

      {/* **Why this branch takes no commits, and the way through** (§284).
          Above the commit bar rather than in place of the editor: the typing
          is not refused, it just lands somewhere that can hold it. */}
      {locked && (
        <p className="state repo-protected" data-testid="protected-branch">
          {protectedReason(branchContext)}
        </p>
      )}

      {!readOnly && dirty && (
        <form
          className="repo-commit-bar"
          onSubmit={(e) => {
            e.preventDefault();
            if (locked) commitToSandbox.mutate();
            else commit.mutate();
          }}
        >
          <span className="repo-dirty">
            {Object.keys(edits).length} file{Object.keys(edits).length === 1 ? "" : "s"} changed
          </span>
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="What changed, and why"
            aria-label="Commit message"
          />
          {locked ? (
            <button
              className="btn"
              type="submit"
              disabled={commitToSandbox.isPending}
              data-testid="commit-to-sandbox"
            >
              {commitToSandbox.isPending
                ? "Creating the branch…"
                : `Commit to a new branch from ${branch}`}
            </button>
          ) : (
            <button className="btn" type="submit" disabled={commit.isPending}>
              {commit.isPending ? "Committing…" : `Commit to ${branch}`}
            </button>
          )}
          {/* **Asks first** (§288). The one control here that destroys work,
              beside the one that saves it - and since §281 what it throws away
              may be days of typing rather than this session's, because the
              drafts persist. `setEdits({})` is also what removes them from
              storage, through the save effect above. */}
          <button
            type="button"
            className="repo-discard"
            onClick={() => {
              if (window.confirm(discardQuestion(Object.keys(edits).length))) {
                setEdits({});
              }
            }}
          >
            Discard
          </button>
        </form>
      )}
      {/* **Only when work is at risk** (§281). A save and a clear are the
          system working; narrating them would train people to ignore the line
          that matters. This appears when the browser is not storing drafts at
          all, or when these edits are too large to keep. */}
      {draftWarning && (
        <p className="state error" data-testid="draft-warning">{draftWarning}</p>
      )}
      {failure && <p className="state error">{failure}</p>}
    </div>
  );
}


/** Publish: make the transforms declared at this commit the project's
 * definitions (roadmap 2.5).
 *
 * The plan is shown before the button, for the same reason the merge screen
 * shows a verdict first: every refusal a publish can make is knowable without
 * publishing, and a screen that only reports them afterwards teaches people to
 * press and hope.
 *
 * Two things this has to be honest about, and neither is the happy path:
 *
 *   * **a file whose source has not changed publishes nothing**, and says so
 *     rather than manufacturing a version with an empty diff;
 *   * **a model whose file has stopped declaring a transform is left alone**
 *     and named. It holds a dataset other things read, and removing a file is
 *     not the same act as deciding that dataset should stop being produced.
 */
function PublishTab({
  wid,
  pid,
  rid,
  branch,
  pinned,
}: {
  wid: string;
  pid: string;
  rid: string;
  branch: string;
  pinned: boolean;
}) {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<PublishPlan | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [opened, setOpened] = useState<string | null>(null);

  const plan = useQuery({
    queryKey: ["repo-publish-plan", rid, branch],
    queryFn: () => repoApi.publishPlan(wid, pid, rid, { branch }),
    retry: false,
  });

  const run = useMutation({
    mutationFn: () => repoApi.publish(wid, pid, rid, { branch }),
    onSuccess: (done) => {
      setResult(done);
      setFailure(null);
      queryClient.invalidateQueries({ queryKey: ["repo-publish-plan", rid] });
    },
    onError: (e: Error) => {
      setResult(null);
      setFailure(e instanceof ApiError ? e.message : String(e));
    },
  });

  // Whether this project gates code changes. A gated project cannot publish
  // directly - it opens a proposal for the commit and publishes by applying
  // it, which is what makes the gate hold rather than be routed around.
  const policy = useQuery({
    queryKey: ["code-review-policy", pid],
    queryFn: () => codeApi.reviewPolicy(wid, pid),
  });
  const gated = policy.data?.require_code_review ?? false;

  const propose = useMutation({
    mutationFn: (input: { summary: string; commit_id: string }) =>
      codeApi.propose(wid, pid, {
        summary: input.summary,
        description: DESCRIPTION_TEMPLATE,
        source_repo_id: rid,
        source_commit_id: input.commit_id,
      }),
    onSuccess: (made) => {
      setFailure(null);
      setOpened(made.id);
    },
    onError: (e: Error) => setFailure(e instanceof ApiError ? e.message : String(e)),
  });

  // A plan is against a branch's head. Viewing a pinned commit is history, and
  // publishing history would quietly make an old snapshot live.
  if (pinned) {
    return (
      <p className="state">
        You are looking at a commit rather than a branch. Publishing is against a
        branch&apos;s head — go back to the branch to publish it.
      </p>
    );
  }
  if (plan.isPending) return <p className="state">Reading {branch}…</p>;

  const steps = result?.steps ?? plan.data?.steps ?? [];
  const orphaned = result?.orphaned ?? plan.data?.orphaned ?? [];
  const refusal = plan.isError ? (plan.error as Error).message : null;
  const commitId = result?.commit_id ?? plan.data?.commit_id ?? null;
  // After a publish, what is left to write is what the *result* says, not what
  // the plan said before it ran - a button offering to publish two transforms
  // it has just published is a small lie, and the next press proves it.
  const writes = steps.filter((s) =>
    s.action ? s.action !== "unchanged" && !result : !s.unchanged,
  ).length;

  return (
    <div className="repo-publish">
      <div className="repo-publish-head">
        <div>
          <h3>Publish {branch}</h3>
          <p className="soft">
            The transforms declared at this commit become this project&apos;s
            definitions. The source is copied into a version, so deleting the branch
            afterwards changes nothing about what runs.
          </p>
          {gated && (
            <p className="repo-publish-gated">
              This project requires code review, so a commit is not published
              directly — open a proposal for it, and applying that proposal publishes.
            </p>
          )}
        </div>
        {gated ? (
          <button
            className="btn"
            type="button"
            disabled={!!refusal || propose.isPending || steps.length === 0 || !commitId}
            onClick={() =>
              commitId &&
              propose.mutate({
                summary: `Publish ${branch} (${commitId.slice(0, 8)})`,
                commit_id: commitId,
              })
            }
          >
            {propose.isPending ? "Opening…" : "Open a proposal"}
          </button>
        ) : (
          <button
            className="btn"
            type="button"
            disabled={!!refusal || run.isPending || steps.length === 0}
            onClick={() => run.mutate()}
          >
            {run.isPending
              ? "Publishing…"
              : writes === 0 && steps.length > 0
                ? "Nothing to publish"
                : `Publish ${writes} transform${writes === 1 ? "" : "s"}`}
          </button>
        )}
      </div>

      {refusal && <p className="state error">{refusal}</p>}
      {failure && <p className="state error">{failure}</p>}
      {opened && (
        <p className="state">
          Proposal opened. Review it under Code in this project; applying it
          publishes this commit.
        </p>
      )}
      {result && (
        <p className="state">
          Published {result.steps.filter((s) => s.action !== "unchanged").length} of{" "}
          {result.steps.length}.
        </p>
      )}

      {steps.length > 0 && (
        <table className="repo-publish-table">
          <thead>
            <tr>
              <th>File</th>
              <th>Produces</th>
              <th>Reads</th>
              <th>What happens</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((s) => (
              <tr key={s.path}>
                <td>
                  <code>{s.path}</code>
                </td>
                <td>
                  <code>{s.output}</code>
                  {s.renames && (
                    <span className="soft"> (was {s.model_name})</span>
                  )}
                </td>
                <td className="soft">
                  {s.inputs.map((i) => `${i.input_alias} = ${i.dataset}`).join(", ") || "—"}
                </td>
                <td className={s.unchanged ? "soft" : ""}>
                  {s.action ??
                    (s.unchanged
                      ? "unchanged"
                      : s.model_id
                        ? "updates the live definition"
                        : "creates a transform")}
                  {s.version_number ? ` (v${s.version_number})` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {orphaned.length > 0 && (
        <div className="repo-publish-orphans">
          <strong>
            {orphaned.length} transform{orphaned.length === 1 ? "" : "s"} published from
            this repository {orphaned.length === 1 ? "is" : "are"} no longer declared here
          </strong>
          <ul>
            {orphaned.map((o) => (
              <li key={o.id}>
                <code>{o.source_path}</code> produced {o.name}
              </li>
            ))}
          </ul>
          <p className="soft">
            Left alone, not deleted — each still produces a dataset other things may
            read. Delete the transform if it should stop running.
          </p>
        </div>
      )}
    </div>
  );
}

/** Branches: create, switch, delete, and merge (roadmap 2.4).
 *
 * Merging is fast-forward only - decision 0003 chose that, and three-way text
 * merge in a browser is a product in itself. Two consequences shape this
 * screen:
 *
 *   1. **The comparison is shown before the button, not after the failure.**
 *      A merge that can only report "no" once you have pressed it teaches
 *      people to press and hope. The four states each get a sentence, and the
 *      one that cannot merge gets the files it would take to redo the work.
 *   2. **Nothing that would move a branch happens without saying so first.**
 *      The button names the branch that moves and the commit it moves to.
 */
function BranchesTab({
  wid,
  pid,
  rid,
  current,
  defaultBranch,
  branches,
  pending,
  onSwitch,
  onOpenProposal,
  onSwitchToPublish,
}: {
  wid: string;
  pid: string;
  rid: string;
  current: string;
  defaultBranch: string;
  branches: RepositoryBranch[] | undefined;
  pending: boolean;
  onSwitch: (name: string) => void;
  onOpenProposal: (id: string) => void;
  onSwitchToPublish: (name: string) => void;
}) {
  const queryClient = useQueryClient();
  const known = useMemo(() => branches ?? [], [branches]);
  const names = known.map((b) => b.name);

  // The comparison is in the URL (item 0.4): "look at what this branch has
  // that trunk does not" is a thing to send somebody, and it is the one piece
  // of this tab's state that describes a *question* rather than a form being
  // filled in. The branch being created is not - a half-typed name is not
  // something to share, and neither is a note about what just happened.
  const summaries = useQuery({
    queryKey: ["repo-branch-summary", rid],
    queryFn: () => repoApi.branchSummary(wid, pid, rid),
  });
  const columns = useMemo(
    () => new Map((summaries.data ?? []).map((row) => [row.name, row])),
    [summaries.data],
  );

  const url = useUrlState();
  const base = url.get("base") ?? defaultBranch;
  const head = url.get("head") ?? "";
  const [newName, setNewName] = useState("");
  const [from, setFrom] = useState(current);
  const [failure, setFailure] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // Derived at render rather than seeded into state by an effect: a default
  // that lives in state goes stale the moment the branch it named is deleted,
  // and a select pointing at a branch that is gone is the bug that produces.
  const headBranch = head && names.includes(head) ? head : names.find((n) => n !== base) ?? "";
  const baseBranch = names.includes(base) ? base : defaultBranch;

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["repo-branches", rid] });
    queryClient.invalidateQueries({ queryKey: ["repo-tree", rid] });
    queryClient.invalidateQueries({ queryKey: ["repo-commits", rid] });
    queryClient.invalidateQueries({ queryKey: ["repo-compare", rid] });
  }

  const comparison = useQuery({
    queryKey: ["repo-compare", rid, baseBranch, headBranch],
    queryFn: () => repoApi.compare(wid, pid, rid, baseBranch, headBranch),
    enabled: !!baseBranch && !!headBranch && baseBranch !== headBranch,
  });

  const create = useMutation({
    mutationFn: (input: { name: string; from_branch: string }) =>
      repoApi.createBranch(wid, pid, rid, input),
    onSuccess: (made) => {
      setNewName("");
      setFailure(null);
      setNote(`Created ${made.name}.`);
      refresh();
    },
    onError: (e: Error) => {
      setNote(null);
      setFailure(e.message);
    },
  });

  const remove = useMutation({
    mutationFn: (name: string) => repoApi.deleteBranch(wid, pid, rid, name),
    onSuccess: (_data, name) => {
      setFailure(null);
      setNote(`Deleted ${name}. Its commits are still here.`);
      refresh();
    },
    onError: (e: Error) => {
      setNote(null);
      setFailure(e.message);
    },
  });

  const merge = useMutation({
    mutationFn: () => repoApi.merge(wid, pid, rid, baseBranch, headBranch),
    onSuccess: (result) => {
      setFailure(null);
      setNote(
        result.merged
          ? `${baseBranch} moved to ${headBranch} — ${result.ahead_by} commit${
              result.ahead_by === 1 ? "" : "s"
            }.`
          : `Nothing to merge: ${headBranch} is already in ${baseBranch}.`,
      );
      refresh();
    },
    onError: (e: Error) => {
      setNote(null);
      setFailure(e instanceof ApiError ? e.message : String(e));
    },
  });

  if (pending) return <p className="state">Loading branches…</p>;

  const seen = comparison.data;
  const canMerge = seen?.state === "fast_forward";

  return (
    <div className="repo-branches">
      <section className="repo-branch-list">
        <h3>Branches</h3>
        <ul>
          {known.map((b) => (
            <li key={b.id} className={b.name === current ? "on" : undefined}>
              <button type="button" className="repo-branch-name" onClick={() => onSwitch(b.name)}>
                {b.name}
              </button>
              {b.name === defaultBranch && <span className="repo-branch-tag">default</span>}
              {b.name === current && <span className="repo-branch-tag">viewing</span>}
              <code className="repo-sha">
                {b.head_commit_id ? b.head_commit_id.slice(0, 8) : "no commits"}
              </code>
              {/* p.16's two columns. Rendered from one request rather than one
                  per branch - twenty branches would otherwise be twenty round
                  trips, which is how a column becomes something people wait for
                  rather than glance at. */}
              <BranchColumns
                summary={columns.get(b.name)}
                defaultBranch={defaultBranch}
                onOpenProposal={onOpenProposal}
                onPropose={onSwitchToPublish}
              />
              <button
                type="button"
                className="repo-branch-delete"
                // The default branch is not offered, because deleting it makes
                // the repository open as *empty* - which is also what losing
                // everything looks like. The API refuses it too.
                disabled={b.name === defaultBranch || remove.isPending}
                onClick={() => {
                  if (window.confirm(`Delete ${b.name}? Its commits stay.`)) {
                    remove.mutate(b.name);
                  }
                }}
              >
                Delete
              </button>
            </li>
          ))}
          {known.length === 0 && (
            <li className="soft">No branches yet — the first commit makes one.</li>
          )}
        </ul>

        <form
          className="repo-branch-new"
          onSubmit={(e) => {
            e.preventDefault();
            if (newName.trim()) {
              create.mutate({ name: newName.trim(), from_branch: from });
            }
          }}
        >
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New branch name"
            aria-label="New branch name"
          />
          <label>
            from
            <select value={from} onChange={(e) => setFrom(e.target.value)}>
              {names.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button className="btn" type="submit" disabled={create.isPending || !newName.trim()}>
            Create branch
          </button>
        </form>
      </section>

      <section className="repo-merge">
        <h3>Merge</h3>
        <div className="repo-merge-refs">
          <label>
            Into
            <select value={baseBranch} onChange={(e) => url.set({ base: e.target.value })}>
              {names.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <span aria-hidden>←</span>
          <label>
            From
            <select value={headBranch} onChange={(e) => url.set({ head: e.target.value })}>
              {names
                .filter((n) => n !== baseBranch)
                .map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
            </select>
          </label>
        </div>

        {!headBranch && (
          <p className="state">
            There is only one branch, so there is nothing to merge into it.
          </p>
        )}
        {comparison.isPending && !!headBranch && <p className="state">Comparing…</p>}
        {comparison.isError && (
          <p className="state error">{(comparison.error as Error).message}</p>
        )}

        {seen && (
          <>
            <MergeVerdict comparison={seen} />
            {(seen.commits.length > 0 || seen.ahead_by > 0) && (
              <ul className="repo-merge-commits">
                {seen.commits.map((c) => (
                  <li key={c.id}>
                    <code className="repo-sha">{c.id.slice(0, 8)}</code>{" "}
                    {c.message || <span className="soft">(no message)</span>}
                  </li>
                ))}
              </ul>
            )}
            <ul className="repo-diff">
              {seen.files.added.map((p) => (
                <li key={`a${p}`} className="added">
                  <span>added</span> {p}
                </li>
              ))}
              {seen.files.modified.map((p) => (
                <li key={`m${p}`} className="modified">
                  <span>changed</span> {p}
                </li>
              ))}
              {seen.files.deleted.map((p) => (
                <li key={`d${p}`} className="deleted">
                  <span>deleted</span> {p}
                </li>
              ))}
            </ul>
            <button
              className="btn repo-merge-go"
              type="button"
              disabled={!canMerge || merge.isPending}
              onClick={() => merge.mutate()}
            >
              {merge.isPending
                ? "Merging…"
                : canMerge
                  ? `Move ${baseBranch} to ${seen.head_commit_id?.slice(0, 8)}`
                  : "Nothing to merge"}
            </button>
          </>
        )}
      </section>

      {/* p.17: "The branches tab also lets you access a list of tags." Here
          rather than as a tab of its own, because that is where the
          specification puts it and because a tag is a name for a commit on one
          of the branches above - the two are read together. */}
      <TagsSection
        wid={wid}
        pid={pid}
        rid={rid}
        branch={current}
        hasCommits={known.some((b) => b.head_commit_id !== null)}
      />

      {note && <p className="state">{note}</p>}
      {failure && <p className="state error">{failure}</p>}
    </div>
  );
}


/** p.16's Checks and Pull request columns, for one branch row (§300).
 *
 *     "If you don't see the button to create a new Pull request, it means that
 *      a Pull request already exists for a branch." (p.16-17)
 *
 * That is a rule rather than a description: the button and the state occupy the
 * same slot, and which one is there says which situation you are in. The
 * wording rules are in `lib/branch-columns.ts`.
 */
function BranchColumns({
  summary,
  defaultBranch,
  onOpenProposal,
  onPropose,
}: {
  summary: RepositoryBranchSummary | undefined;
  defaultBranch: string;
  onOpenProposal: (id: string) => void;
  onPropose: (branch: string) => void;
}) {
  // Absent while the one request is in flight, and nothing is drawn: a column
  // that guessed "not run" and then corrected itself would be worse than one
  // that arrives a moment later, because the guess is the answer somebody acts
  // on.
  if (summary === undefined) return null;

  const slot = pullRequestSlot(summary);
  const blocked = proposeProblem(summary, defaultBranch);
  return (
    <>
      <span
        className={checksAreAProblem(summary) ? "chip brass" : "soft"}
        data-testid={`branch-checks-${summary.name}`}
      >
        {checksLabel(summary)}
      </span>
      {slot.kind === "open" && (
        <button
          type="button"
          className="btn quiet"
          style={{ padding: "2px 8px", fontSize: 11 }}
          data-testid={`branch-pr-${summary.name}`}
          title={slot.summary}
          onClick={() => onOpenProposal(slot.id)}
        >
          {proposalStateLabel(slot.state)}
        </button>
      )}
      {slot.kind === "propose" && (
        <button
          type="button"
          className="btn quiet"
          style={{ padding: "2px 8px", fontSize: 11 }}
          data-testid={`branch-propose-${summary.name}`}
          // Titled rather than hidden: p.16 makes the *absence* of this button
          // mean "a pull request already exists", so hiding it for a second
          // reason would make that sentence untrue. Disabled with the reason on
          // it says no and says why.
          title={blocked ?? undefined}
          disabled={blocked !== null}
          onClick={() => onPropose(summary.name)}
        >
          Propose changes
        </button>
      )}
    </>
  );
}


/** p.17's tags: "like immutable branches".
 *
 *     "A tag can be used to mark a significant version of the code for future
 *      reference by giving it a version number or name… A tag can be created
 *      from the current version of a branch, or from any arbitrary commit."
 *
 * **The immutability is the database's** (db 0072's trigger), and the naming
 * convention is the repository's own `repoSettings.json` read at the commit
 * being tagged - so this offers, and refuses nothing the server would not.
 * The wording rules are in `lib/tags.ts`.
 */
function TagsSection({
  wid,
  pid,
  rid,
  branch,
  hasCommits,
}: {
  wid: string;
  pid: string;
  rid: string;
  branch: string;
  hasCommits: boolean;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState<string | null>(null);

  const tags = useQuery({
    queryKey: ["repo-tags", rid],
    queryFn: () => repoApi.tags(wid, pid, rid),
  });

  const create = useMutation({
    mutationFn: () =>
      repoApi.createTag(wid, pid, rid, {
        name: name.trim(),
        branch,
        message: message.trim() || undefined,
      }),
    onSuccess: () => {
      setName("");
      setMessage("");
      setFailure(null);
      queryClient.invalidateQueries({ queryKey: ["repo-tags", rid] });
    },
    // **The server's own sentence, unchanged.** When a repository set an
    // `errorMessage` in `repoSettings.json` that is what arrives here, and it
    // was written by somebody for their colleagues (p.17).
    onError: (e: Error) => setFailure(e instanceof ApiError ? e.message : String(e)),
  });

  const remove = useMutation({
    mutationFn: (tagId: string) => repoApi.deleteTag(wid, pid, rid, tagId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["repo-tags", rid] }),
    onError: (e: Error) => setFailure(e instanceof ApiError ? e.message : String(e)),
  });

  const rows = tags.data ?? [];
  const problem = tagNameProblem(name);
  const empty = tags.isSuccess ? tagsEmptyReason(rows.length, hasCommits) : null;

  return (
    <section className="repo-branch-list" data-testid="tags-section">
      <h3>Tags</h3>
      {empty && <p className="state" data-testid="tags-empty">{empty}</p>}
      {rows.length > 0 && (
        <ul data-testid="tags-list">
          {rows.map((t) => (
            <li key={t.id}>
              <span className="repo-branch-name" data-testid={`tag-${t.name}`}>{t.name}</span>
              <code className="repo-sha">{tagSubtitle(t)}</code>
              <button
                type="button"
                className="repo-branch-delete"
                data-testid={`tag-delete-${t.name}`}
                onClick={() => {
                  // It asks, and it says what is *not* at risk: p.17 warns
                  // about deleting branches because that can lose work, and a
                  // tag cannot.
                  if (window.confirm(tagDeleteQuestion(t))) remove.mutate(t.id);
                }}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
      {hasCommits && (
        <form
          className="repo-branch-new"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <input
            type="text"
            value={name}
            placeholder="1.4.0"
            data-testid="tag-name"
            onChange={(e) => setName(e.target.value)}
          />
          <input
            type="text"
            value={message}
            placeholder="why this version matters (optional)"
            data-testid="tag-message"
            onChange={(e) => setMessage(e.target.value)}
          />
          <button
            type="submit"
            data-testid="tag-create"
            disabled={!canCreateTag(name) || create.isPending}
          >
            New Tag
          </button>
          {/* A tag can never be moved, so this is the one moment it can be got
              right - a form that did not say which commit would be asking for
              a permanent decision blind. */}
          <span className="soft" data-testid="tag-will-pin">{willPin(branch, undefined)}</span>
        </form>
      )}
      {problem && <p className="state error" data-testid="tag-name-problem">{problem}</p>}
      {failure && <p className="state error" data-testid="tag-failure">{failure}</p>}
    </section>
  );
}

/** The four states in a sentence each, and the refused one in a paragraph.
 *
 * `diverged` gets the most words on purpose: it is the only state where the
 * person has to do something, and "cannot merge" without saying what to do
 * instead is where a fast-forward-only rule turns into a dead end. */
function MergeVerdict({ comparison }: { comparison: RepositoryComparison }) {
  const { base, head, state, ahead_by: ahead, behind_by: behind, files } = comparison;
  const touched = [...files.added, ...files.modified, ...files.deleted].sort();

  if (state === "identical") {
    return (
      <p className="repo-merge-verdict identical">
        <strong>{head}</strong> and <strong>{base}</strong> point at the same commit. Nothing
        to merge.
      </p>
    );
  }
  if (state === "contained") {
    return (
      <p className="repo-merge-verdict contained">
        <strong>{head}</strong> is already in <strong>{base}</strong>, which has moved{" "}
        {behind} commit{behind === 1 ? "" : "s"} further. Nothing to merge.
      </p>
    );
  }
  if (state === "fast_forward") {
    return (
      <p className="repo-merge-verdict fast-forward">
        <strong>{base}</strong> can fast-forward to <strong>{head}</strong>: {ahead} commit
        {ahead === 1 ? "" : "s"} and {touched.length} file{touched.length === 1 ? "" : "s"}.
        No merge commit — the pointer moves to commits that already exist.
      </p>
    );
  }
  return (
    <div className="repo-merge-verdict diverged">
      <p>
        <strong>{head}</strong> and <strong>{base}</strong> have diverged: {ahead} commit
        {ahead === 1 ? "" : "s"} on {head} that {base} does not have, and {behind} on {base}{" "}
        that {head} does not.
      </p>
      <p>
        Merging here is fast-forward only, so this cannot be resolved by moving a pointer.
        Start a branch from <strong>{base}</strong> and commit{" "}
        {touched.length === 0 ? "your work" : `these ${touched.length} files`} there.
      </p>
    </div>
  );
}

function HistoryTab({
  wid,
  pid,
  rid,
  branch,
  onOpenCommit,
}: {
  wid: string;
  pid: string;
  rid: string;
  branch: string;
  onOpenCommit: (id: string) => void;
}) {
  const commits = useQuery({
    queryKey: ["repo-commits", rid, branch],
    queryFn: () => repoApi.commits(wid, pid, rid, branch),
  });
  if (commits.isPending) return <p className="state">Loading history…</p>;
  if (commits.isError) return <p className="state error">{(commits.error as Error).message}</p>;
  if (commits.data.length === 0) return <p className="state">No commits on {branch} yet.</p>;

  return (
    <ul className="repo-history">
      {commits.data.map((c) => (
        <li key={c.id}>
          <CommitRow
            wid={wid}
            pid={pid}
            rid={rid}
            commit={c}
            onOpen={() => onOpenCommit(c.id)}
          />
        </li>
      ))}
    </ul>
  );
}

function CommitRow({
  wid,
  pid,
  rid,
  commit,
  onOpen,
}: {
  wid: string;
  pid: string;
  rid: string;
  commit: { id: string; message: string; created_at: string };
  onOpen: () => void;
}) {
  // One request per commit, and only for what is on screen. A history endpoint
  // that returned every diff would do the work whether or not anybody looked.
  const diff = useQuery({
    queryKey: ["repo-diff", rid, commit.id],
    queryFn: () => repoApi.diff(wid, pid, rid, commit.id),
  });

  return (
    <div className="repo-commit">
      <div className="repo-commit-head">
        <button type="button" className="repo-commit-open" onClick={onOpen}>
          {commit.message || <span className="soft">(no message)</span>}
        </button>
        <code className="repo-sha">{commit.id.slice(0, 8)}</code>
        <span className="soft">{new Date(commit.created_at).toLocaleString()}</span>
      </div>
      {diff.data && (
        <ul className="repo-diff">
          {diff.data.added.map((p) => (
            <li key={`a${p}`} className="added">
              <span>added</span> {p}
            </li>
          ))}
          {diff.data.modified.map((p) => (
            <li key={`m${p}`} className="modified">
              <span>changed</span> {p}
            </li>
          ))}
          {diff.data.deleted.map((p) => (
            <li key={`d${p}`} className="deleted">
              <span>deleted</span> {p}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Preview: run this file's transform against a sample of its inputs and show
 * what comes back, without committing anything (roadmap 2.6).
 *
 * Three things this has to get right, and only the first is the obvious one:
 *
 *   1. it previews **what is on screen**, including unsaved edits, because
 *      that is the question a person is actually asking;
 *   2. it says loudly when the answer came from a **sample**, because a row
 *      count over the first thousand rows of a join is not the row count and
 *      a table that did not say so would be believed;
 *   3. it shows what the change would do to the dataset this transform already
 *      writes, which is the difference between finding out now and finding out
 *      after the pipeline ran.
 *
 * Nothing runs on its own. A preview reads datasets and costs real work, so it
 * happens when somebody asks for it rather than on every keystroke.
 */
function PreviewPanel({
  wid,
  pid,
  rid,
  path,
  content,
}: {
  wid: string;
  pid: string;
  rid: string;
  path: string;
  content: string;
}) {
  const [result, setResult] = useState<TransformPreview | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  // A result belongs to the text it came from. Keeping the path here and
  // clearing on change stops a preview of one file being read as a preview of
  // the next one - the failure mode of every stale panel.
  useEffect(() => {
    setResult(null);
    setFailure(null);
  }, [path]);

  const run = useMutation({
    mutationFn: () => repoApi.preview(wid, pid, rid, { path, content }),
    onSuccess: (data) => {
      setResult(data);
      setFailure(null);
    },
    onError: (e: Error) => {
      setResult(null);
      setFailure(e.message);
    },
  });

  const changes = result?.schema_changes;

  return (
    <section className="repo-preview">
      <div className="repo-preview-bar">
        <button
          type="button"
          className="btn"
          onClick={() => run.mutate()}
          disabled={run.isPending}
        >
          {run.isPending ? "Running…" : "Preview"}
        </button>
        <span className="soft">
          Runs against a sample. Writes nothing.
        </span>
      </div>

      {failure && <p className="state error">{failure}</p>}

      {result && (
        <>
          <div className="repo-preview-meta">
            <span>
              → <code>{result.output}</code>
            </span>
            <span>
              {result.row_count.toLocaleString()} row
              {result.row_count === 1 ? "" : "s"}
              {result.sampled && " from the sample"}
            </span>
            {result.inputs.map((input) => (
              <span key={input.alias} className={input.sampled ? "warn" : "soft"}>
                {input.alias} = {input.dataset}
                {input.sampled
                  ? ` (${input.rows_used.toLocaleString()} of ${input.rows_available.toLocaleString()})`
                  : ""}
              </span>
            ))}
          </div>

          {result.sampled && (
            <p className="repo-preview-warning">
              This ran on the first {result.inputs
                .filter((i) => i.sampled)
                .map((i) => i.rows_used.toLocaleString())
                .join(" / ")}{" "}
              rows of its inputs. Joins and aggregates over a sample give an
              answer, not the answer.
            </p>
          )}

          {changes && (
            <div className="repo-preview-drift">
              <strong>This would change {result.output}:</strong>
              <ul>
                {(changes.added ?? []).map((c) => (
                  <li key={`a${c.name}`} className="added">
                    adds <code>{c.name}</code> ({c.data_type})
                  </li>
                ))}
                {(changes.removed ?? []).map((c) => (
                  <li key={`r${c.name}`} className="deleted">
                    drops <code>{c.name}</code> ({c.data_type})
                  </li>
                ))}
                {(changes.retyped ?? []).map((c) => (
                  <li key={`t${c.name}`} className="modified">
                    <code>{c.name}</code> becomes {c.to} (was {c.from})
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="repo-preview-table">
            <table>
              <thead>
                <tr>
                  {result.columns.map((c) => (
                    <th key={c.name}>
                      {c.name}
                      <span className="soft">{c.data_type}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((value, j) => (
                      <td key={j}>
                        {value === null ? <span className="soft">null</span> : String(value)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.truncated && (
            <p className="soft">
              Showing {result.rows.length} of {result.row_count.toLocaleString()} rows.
            </p>
          )}
        </>
      )}
    </section>
  );
}

/**
 * p.18–19's Pull requests tab (§276; `code-repositories.md` §1, §4).
 *
 * The review *surface* is not new — `ReviewSurface` has been a shared
 * component since §60, which is why it takes a proposal id and nothing else.
 * What is new is that it is reachable from the repository the proposal is
 * about, rather than only from the project's Code pillar page, which B.1
 * deletes.
 *
 * **Deep-linkable, because a review is a thing people send each other.** The
 * open proposal lives in the URL beside the tab, so a link opens on the
 * proposal rather than on a list somebody then has to search.
 */
function PullRequestsTab({
  wid,
  pid,
  rid,
  openId,
  onOpen,
  onClose,
}: {
  wid: string;
  pid: string;
  rid: string;
  openId?: string;
  onOpen: (id: string) => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const proposals = useQuery({
    queryKey: ["code-proposals", pid],
    queryFn: () => codeApi.proposals(wid, pid, "open"),
  });

  // Asked of the project and filtered here rather than asked of the
  // repository, because the endpoint is project-scoped (db 0039 hangs a
  // proposal off a project and *optionally* off a repository) - and because
  // the count of what is elsewhere is what makes an empty tab legible.
  const all = proposals.data ?? [];
  const ours = forRepository(all, rid);
  const empty = proposals.isSuccess ? emptyReason(all, rid) : null;

  if (openId) {
    return (
      <div className="code-review-mode">
        <div className="canvas-settings-head">
          <strong>Reviewing a proposal</strong>
          <button
            type="button"
            className="btn quiet"
            style={{ padding: "3px 9px", fontSize: 12 }}
            data-testid="pulls-back"
            onClick={onClose}
          >
            Back to pull requests
          </button>
        </div>
        <ReviewSurface
          workspaceId={wid}
          projectId={pid}
          proposalId={openId}
          canReview
          onChanged={() => {
            queryClient.invalidateQueries({ queryKey: ["code-proposals", pid] });
          }}
        />
      </div>
    );
  }

  return (
    <section className="code-open-proposals" data-testid="pulls-list">
      {proposals.isPending && <div className="state">Loading proposals…</div>}
      {empty && (
        // **Says where the others are rather than looking like nothing is
        // happening.** A reviewer sent a link, finding an empty tab, needs to
        // tell "already dealt with" from "not here" - and the typed-changes
        // shape belongs to no repository, so it genuinely is somewhere else.
        <p className="login-note" data-testid="pulls-empty">{empty}</p>
      )}
      <ul className="code-log">
        {ours.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              className="code-log-entry"
              data-testid={`pull-${p.id}`}
              onClick={() => onOpen(p.id)}
            >
              <span className="code-log-summary">{p.summary}</span>
              <span className="code-log-meta">
                <span className="chip brass">{describeProposal(p)}</span>
                {p.created_by_email ?? "unknown"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * p.20's Settings tab (§279; `code-repositories.md` §1, §6).
 *
 * **It exists because of what §278 found**: `setReviewPolicy` had exactly one
 * control in the product, on the Code pillar page B.1 deletes. Nothing would
 * have errored when that page went — a project would simply have lost the
 * ability to require review of its transforms, which is a governance setting
 * rather than a convenience.
 *
 * One setting so far, and the tab is worth having for that one. p.20's other
 * groups — personal editor preferences, compute usage, ontology imports —
 * are `code-repositories.md` §6's ○ rows and are not built.
 */
function SettingsTab({ wid, pid }: { wid: string; pid: string }) {
  const queryClient = useQueryClient();
  const [failure, setFailure] = useState<string | null>(null);

  const project = useQuery({
    queryKey: ["project", wid, pid],
    queryFn: () => platformApi.project(wid, pid),
  });
  const policy = useQuery({
    queryKey: ["code-review-policy", pid],
    queryFn: () => codeApi.reviewPolicy(wid, pid),
  });
  const repositories = useQuery({
    queryKey: ["repositories", pid],
    queryFn: () => repoApi.list(wid, pid),
  });

  const set = useMutation({
    mutationFn: (required: boolean) => codeApi.setReviewPolicy(wid, pid, required),
    onSuccess: (next) => {
      setFailure(null);
      queryClient.setQueryData(["code-review-policy", pid], next);
      // The Models screen reads this to decide whether a transform's body is
      // editable (§277), so it has to hear about the change.
      queryClient.invalidateQueries({ queryKey: ["models", pid] });
    },
    onError: (e: Error) =>
      setFailure(e instanceof ApiError ? e.message : "Couldn't change it."),
  });

  const role = project.data?.effective_role ?? "viewer";
  const locked = reviewPolicyLockedReason(role);
  // **What was asked for while it is in flight, what the server says after.**
  // The box is controlled by the server's answer, which is right - this is a
  // governance setting and the screen should not claim it changed until it
  // did. But between the click and the response React resets the input to the
  // old value, so a reader sees it flick back and then forward again, and
  // Playwright's `check()` reports that the click did not take. Showing the
  // requested value *only while the mutation is pending* keeps the honesty and
  // loses the flicker: on failure it snaps back, which is the truth.
  const required = set.isPending
    ? (set.variables as boolean)
    : policy.data?.require_code_review ?? false;

  return (
    <section className="repo-settings" data-testid="settings-tab">
      <p className="field-label">Code review</p>
      <label className="row-actions" style={{ alignItems: "center", gap: 8 }}>
        <input
          type="checkbox"
          data-testid="settings-require-review"
          checked={required}
          // **Not disabled while the mutation is in flight.** A PUT of a
          // boolean is idempotent, so guarding against a second click buys
          // nothing - and the box going disabled for the ~50ms of the round
          // trip is long enough for a reader to see it grey out, and long
          // enough that Playwright's `check()` re-reads it mid-flight and
          // reports "clicking the checkbox did not change its state". A guard
          // whose only effect is a flicker is not a guard.
          disabled={!canChangeReviewPolicy(role) || policy.isPending}
          onChange={(e) => set.mutate(e.target.checked)}
        />
        <span>Require review before a transform changes</span>
      </label>
      <p className="login-note" data-testid="settings-review-effect">
        {reviewPolicyEffect(required)}
      </p>
      {/* **The divergence, said out loud.** Foundry sets this per repository;
          ours is per project, because the gate has to cover transforms no
          repository holds. Somebody who discovered that by flipping it in one
          repository and finding it flipped in another would be right to be
          annoyed. */}
      <p className="login-note" data-testid="settings-review-scope">
        {reviewPolicyScopeNote(repositories.data?.length ?? 1)}
      </p>
      {locked && (
        <p className="login-note" data-testid="settings-review-locked">{locked}</p>
      )}
      {failure && <div className="form-error">{failure}</div>}
    </section>
  );
}


/** p.19's Checks tab (§285), the last of `code-repositories.md` §1's five.
 *
 * **A divergence stated on the screen rather than papered over.** Foundry runs
 * checks on a *commit*: you commit to a sandbox and checks start. Ours run on a
 * *proposal*, because the schema check asks what the code would do to the
 * project's datasets and a commit nobody has proposed has not said which change
 * it means to make. Since §284 a sandbox is where work happens and a proposal
 * is how it lands, so every commit that matters is on its way to being one -
 * but a tab that implied a per-commit runner exists would promise something the
 * product does not do.
 *
 * The branch comes from the application's own selector rather than a second one
 * inside the tab: p.19 says "use the dropdown branch menu", and there is one.
 */
function ChecksTab({
  wid,
  pid,
  rid,
  branch,
  defaultBranch,
  onOpenProposal,
}: {
  wid: string;
  pid: string;
  rid: string;
  branch: string;
  defaultBranch: string;
  onOpenProposal: (id: string) => void;
}) {
  const checks = useQuery({
    queryKey: ["repo-checks", rid, branch],
    queryFn: () => repoApi.branchChecks(wid, pid, rid, branch),
  });
  // **p.19: "The Checks tab will also include the output of any unit tests
  // that have been defined for your repo."** (§296.)
  //
  // A second query rather than a second field on the first, because the two
  // are not the same kind of thing here: a check belongs to a *proposal*
  // (§285) and a test run belongs to a *branch and a working set* (db 0071).
  // Folding them into one response would make the API claim a scope neither
  // has.
  const testRuns = useQuery({
    queryKey: ["repo-test-runs", rid, branch],
    queryFn: () => repoApi.testRuns(wid, pid, rid, branch),
  });

  if (checks.isPending) return <p className="state">Loading checks…</p>;
  if (checks.error) return <p className="state error">{(checks.error as Error).message}</p>;

  const data = checks.data!;
  const rows = worstFirst(data.checks);
  const state = verdict(rows);
  const latestRun = mostRecent(testRuns.data ?? []);
  const testStatus = testStatusOf(latestRun);

  return (
    <section className="repo-checks" data-testid="checks-tab">
      <p className={`repo-checks-verdict ${state}`} data-testid="checks-verdict">
        <span className="chip">{state}</span> {verdictNote(rows)}
      </p>
      {/* Said once, where somebody reading a thin list would otherwise assume
          the runner is broken rather than that it runs somewhere else. */}
      <p className="soft" data-testid="checks-scope">
        Checks run on a pull request rather than on every commit, so these are
        the checks of the proposals made over commits on {branch}. Foundry runs
        them per commit; ours ask what the code would do to this project&apos;s
        datasets, which a commit nobody has proposed has not said.
      </p>

      {/* **The unit tests, and labelled as what they are.** They sit above the
          proposal checks because they are about this branch as it stands,
          which is the question somebody opening this tab has first - and they
          carry their own scope line for the same reason the checks do. */}
      {/* **`repo-check-tests`, not `repo-check`.** The first version reused the
          proposal check's class and three of §285's tests went red counting
          `.repo-check`: they were right, and the class was the bug. A unit
          test run is not a proposal check - different scope, different origin
          (db 0071) - and sharing the class made "how many checks ran on this
          branch" answer a different question by one. The styling is shared
          deliberately; the identity is not. */}
      <div className={`repo-check-tests ${testStatus}`} data-testid="checks-tests">
        <div className="repo-check-head">
          <span className="chip">{testStatus === "none" ? "not run" : testStatus}</span>
          <code>unit tests</code>
          <span className="soft">on {branch}</span>
        </div>
        <p className="repo-check-summary" data-testid="checks-tests-summary">
          {testSummary(latestRun)}
        </p>
        {namedFailures(latestRun).length > 0 && (
          <ul className="repo-check-detail" data-testid="checks-tests-failures">
            {namedFailures(latestRun).map((id) => (
              <li key={id}><code>{id}</code></li>
            ))}
            {andMore(latestRun) && <li className="soft">{andMore(latestRun)}</li>}
          </ul>
        )}
      </div>

      {rows.length === 0 ? (
        <p className="state">
          {checksEmptyReason(data.head_commit_id !== null, branch === defaultBranch)}
        </p>
      ) : (
        <ul className="repo-check-list">
          {rows.map((c) => (
            <li key={c.id} className={`repo-check ${c.status}`}>
              <div className="repo-check-head">
                <span className="chip">{c.status}</span>
                <code>{c.name}</code>
                <span className="soft">{checkTarget(c)}</span>
                <span className="soft" style={{ marginLeft: "auto" }}>
                  {new Date(c.ran_at).toLocaleString()}
                </span>
              </div>
              <p className="repo-check-summary">{c.summary}</p>
              {/* p.19: "Click on a specific check to view more detailed
                  information." The detail a check has is the change it is
                  about, so this opens that rather than a dialog of its own. */}
              <button
                type="button"
                className="repo-check-open"
                onClick={() => onOpenProposal(c.proposal_id)}
              >
                {c.proposal_summary}
              </button>{" "}
              <span className="soft">{c.proposal_state}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}


/** p.14's Problems helper (§286; `code-repositories.md` §2.4).
 *
 * "The Problems helper tells you about any issues detected in your code. Click
 * on a specific issue listed here to open up the problematic code."
 *
 * **Everything it reports is something the publish already refuses.** What the
 * panel changes is *when* you hear about it, and that it names a line rather
 * than a commit - a refusal at publish time is a refusal hours after the
 * mistake, about the whole snapshot.
 *
 * Collapsed until asked for, like Preview beside it: this is a round trip, and
 * one on every keystroke would be a panel that costs more than it tells you.
 */
function ProblemsPanel({
  open,
  onToggle,
  problems,
  pending,
  error,
  sourceFileCount,
  onOpen,
}: {
  open: boolean;
  onToggle: () => void;
  problems: RepositoryProblem[] | undefined;
  pending: boolean;
  error: Error | null;
  sourceFileCount: number;
  onOpen: (path: string, line: number | undefined) => void;
}) {
  return (
    <section className="repo-problems" data-testid="problems-panel">
      <div className="repo-problems-head">
        <button type="button" className="btn quiet" onClick={onToggle}>
          {open ? "Hide problems" : "Problems"}
        </button>
        {open && problems && (
          <span className="soft" data-testid="problems-summary">
            {problemsSummary(problems)}
          </span>
        )}
      </div>
      {open && pending && <p className="state">Checking…</p>}
      {open && error && <p className="state error">{error.message}</p>}
      {open && problems && problems.length === 0 && !pending && (
        <p className="state">{problemsEmptyNote(sourceFileCount)}</p>
      )}
      {open && problems && problems.length > 0 && (
        <ul className="repo-problem-list">
          {problems.map((p) => (
            <li key={`${p.path}:${p.line}:${p.message}`} className={`repo-problem ${p.severity}`}>
              <button
                type="button"
                className="repo-problem-open"
                onClick={() => onOpen(p.path, revealLine(p))}
              >
                <span className="chip">{p.severity}</span>
                <code>{problemLocation(p)}</code>
                <span>{p.message}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}


/** p.14's Tests helper (§295; `code-repositories.md` §8).
 *
 * "When your repository contains unit tests, the Tests Helper lets you run
 * those tests and displays their results."
 *
 * **Asked for, and then watched.** Unlike Problems next door, this cannot
 * answer from one request: running unit tests is running customer Python, and
 * decision 0004 confines that to a process holding no platform credentials. So
 * pressing the button queues a job (db 0071) and the panel polls until it has
 * an answer - which is why `shouldPoll` is a named rule rather than an inline
 * comparison, since it going false is the only thing that ever stops it.
 *
 * The wording rules are in `lib/test-runs.ts`. What is here is the seam.
 */
function TestsPanel({
  wid,
  pid,
  rid,
  branch,
  working,
  onOpen,
}: {
  wid: string;
  pid: string;
  rid: string;
  branch: string;
  working: Record<string, string>;
  onOpen: (path: string, line: number) => void;
}) {
  const [open, setOpen] = useState(false);
  // **The route's floor, asked for rather than inferred.** Running tests
  // executes code the caller supplied, so `POST /tests` is editor-level - the
  // line `preview_transform` draws. The first version of this took `!readOnly`
  // from the editor, which is about a *pinned commit* and is therefore always
  // true inside this panel: a control offered to a viewer who would be refused
  // (§214), dressed as a check. On the key the Settings tab already uses, so
  // this is the same cached answer rather than a second request.
  const project = useQuery({
    queryKey: ["project", wid, pid],
    queryFn: () => platformApi.project(wid, pid),
    enabled: open,
  });
  const canRun = canEditProject(project.data?.effective_role ?? "viewer");
  const [runId, setRunId] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const run = useQuery({
    queryKey: ["repo-test-run", rid, runId],
    queryFn: () => repoApi.testRun(wid, pid, rid, runId!),
    enabled: open && runId !== null,
    // **The panel polls because there is nothing to push to it.** A job's
    // answer arrives in a table, and this is the only way to learn it landed.
    // `false` once settled, so a finished run stops asking rather than
    // polling for the life of the page.
    refetchInterval: (query) => (shouldPoll(query.state.data) ? 1500 : false),
  });

  const start = useMutation({
    mutationFn: () =>
      // **The whole working set, not a delta.** Problems sends `edits` over a
      // commit the server already has; here the *files themselves* are what
      // gets stored and run (db 0071), and the server lays these over the
      // branch. Sending only the edits would run the committed version of
      // every file somebody had not touched, which is the right answer to a
      // question nobody asked.
      repoApi.runTests(wid, pid, rid, { branch, overrides: working }),
    onSuccess: (made) => {
      setFailure(null);
      setRunId(made.id);
    },
    onError: (error) => setFailure((error as Error).message),
  });

  const current = run.data;
  return (
    <section className="repo-problems" data-testid="tests-panel">
      <div className="repo-problems-head">
        <button
          type="button"
          className="btn quiet"
          data-testid="tests-toggle"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Hide tests" : "Tests"}
        </button>
        {open && canRun && (
          <button
            type="button"
            className="btn quiet"
            data-testid="tests-run"
            disabled={start.isPending || shouldPoll(current)}
            onClick={() => start.mutate()}
          >
            {runLabel(current)}
          </button>
        )}
        {open && (
          <span
            className={testsAreAProblem(current) ? "chip brass" : "soft"}
            data-testid="tests-verdict"
          >
            {testVerdict(current)}
          </span>
        )}
      </div>
      {open && failure && (
        <p className="state error" data-testid="tests-error">{failure}</p>
      )}
      {open && current?.outcomes && current.outcomes.length > 0 && (
        <ul className="repo-problem-list" data-testid="tests-list">
          {worstTestsFirst(current.outcomes).map((o) => {
            const jump = testTarget(o);
            const took = testDuration(o);
            return (
              <li key={o.id} className={`repo-problem ${o.outcome}`}>
                <button
                  type="button"
                  className="repo-problem-open"
                  data-testid={`test-${o.outcome}`}
                  // **Disabled rather than inert when there is nowhere to go.**
                  // pytest names no file for a collection error, and a row that
                  // jumped somewhere plausible and wrong is worse than one that
                  // does not jump.
                  disabled={jump === null}
                  onClick={() => jump && onOpen(jump.path, jump.line)}
                >
                  <span className="chip">{o.outcome}</span>
                  <code>{o.id}</code>
                  {o.message && <span>{o.message}</span>}
                  {took && <span className="soft">{took}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}


/** p.13's Foundry Explorer helper (§303; `code-repositories.md` §2.4).
 *
 * "The Foundry Explorer helper is a file navigation interface that lets you
 *  quickly browse all files and folders. Once you select a specific dataset,
 *  you can click 'Open' to view the full dataset."
 *
 * **Ours browses the platform, not the repository**, and the reason is in
 * `explorer.ts`: the Files tab beside this one is already a file tree, and a
 * second one would be a second answer to what is in this repository. What the
 * editor cannot see is everything *outside* it — which is precisely what a
 * transform reads and writes.
 *
 * Collapsed until asked for, like every panel in this column. It is a round
 * trip, and this one is over a listing that does not change while you type.
 */
function ExplorerPanel({ wid, pid }: { wid: string; pid: string }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  // **The query is part of the key, but only once it is a query.** Below the
  // threshold `shouldSearch` sends nothing, so keying on the raw text would
  // fetch an identical unfiltered listing again for every character typed and
  // filed under a different key — a cache that grows and never hits.
  const search = shouldSearch(query) ? query.trim() : "";
  const listing = useQuery({
    queryKey: ["repo-explorer", wid, pid, search],
    queryFn: () =>
      resourceApi.list(wid, pid, {
        kind: EXPLORER_KINDS,
        search: search || undefined,
        // Object types belong to the workspace rather than to a project, so
        // without this their section is empty in every project forever.
        includeWorkspaceLevel: needsWorkspaceLevel(EXPLORER_KINDS),
        limit: 100,
      }),
    enabled: open,
  });

  const found = listing.data?.resources ?? [];
  const nothing = explorerEmptyReason(found.length, query);

  return (
    <section className="repo-explorer" data-testid="explorer-panel">
      <div className="repo-problems-head">
        <button
          type="button"
          className="btn quiet"
          onClick={() => setOpen((v) => !v)}
          data-testid="explorer-toggle"
        >
          {open ? "Hide explorer" : "Explorer"}
        </button>
      </div>
      {open && (
        <div className="repo-explorer-body">
          <input
            type="search"
            aria-label="Search datasets and object types"
            data-testid="explorer-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search"
          />
          {listing.isPending ? (
            <p className="state">Looking…</p>
          ) : listing.error ? (
            <p className="state error">{(listing.error as Error).message}</p>
          ) : nothing ? (
            <p className="state" data-testid="explorer-empty">
              {nothing}
            </p>
          ) : (
            explorerSections(found).map((section) => (
              <div key={section.kind} data-testid={`explorer-${section.kind}`}>
                <h4>{section.label}</h4>
                {section.rows.length === 0 ? (
                  // Drawn rather than skipped: "this project has none" and
                  // "this panel does not do those" look identical when the
                  // heading is missing, and only one is actionable.
                  <p className="state soft">None in this project.</p>
                ) : (
                  <ul className="repo-explorer-list">
                    {section.rows.map((row) => (
                      <li key={row.id}>
                        <span className="repo-explorer-name">{row.name}</span>
                        {explorerSubtitle(row) && (
                          <span className="soft">{explorerSubtitle(row)}</span>
                        )}
                        <Link href={explorerHref(row)} data-testid={`explorer-open-${row.name}`}>
                          Open
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </section>
  );
}

/** p.14's File Changes helper (§287; `code-repositories.md` §2.4).
 *
 * "The File Changes helper can be used to view any uncommitted changes to the
 * current file, as well as compare previous versions of the file."
 *
 * **The diff is built by the same aligner the review surface uses.** A second
 * alignment would be a second answer the first time either was improved, and
 * "what changed" is the one question a repository must not have two answers to.
 *
 * Collapsed until asked for, like Problems and Preview beside it: it is a round
 * trip, and one on every keystroke would cost more than it tells you.
 */
function FileChangesPanel({
  wid,
  pid,
  rid,
  branch,
  path,
  content,
}: {
  wid: string;
  pid: string;
  rid: string;
  branch: string;
  path: string;
  content: string | null;
}) {
  const [open, setOpen] = useState(false);
  // **Which commit to compare against**, or the branch head when nothing is
  // chosen. p.14's "compare previous versions" is this one control.
  const [against, setAgainst] = useState<string | undefined>();

  const changes = useQuery({
    queryKey: ["repo-file-changes", rid, branch, path, content, against],
    queryFn: () =>
      repoApi.fileChanges(wid, pid, rid, {
        path,
        branch,
        content,
        against_commit_id: against,
      }),
    enabled: open,
  });
  const versions = useQuery({
    queryKey: ["repo-file-history", rid, branch, path],
    queryFn: () => repoApi.fileHistory(wid, pid, rid, path, branch),
    enabled: open,
  });

  // A file switch is a different question, so a comparison chosen for the last
  // one is not an answer to this one.
  useEffect(() => setAgainst(undefined), [path, branch]);

  const data: RepositoryFileChanges | undefined = changes.data;
  const rows = data ? withContext(data.rows) : [];
  const list: RepositoryFileVersion[] = versions.data ?? [];

  return (
    <section className="repo-changes" data-testid="file-changes-panel">
      <div className="repo-changes-head">
        <button type="button" className="btn quiet" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide file changes" : "File changes"}
        </button>
        {open && data && (
          <span className="soft" data-testid="file-changes-headline">
            {headline(data)}
          </span>
        )}
        {open && (
          <label className="soft" style={{ marginLeft: "auto" }}>
            Compare with{" "}
            <select
              aria-label="Compare with"
              value={against ?? ""}
              onChange={(e) => setAgainst(e.target.value || undefined)}
            >
              <option value="">the latest commit</option>
              {list.map((v) => (
                <option key={v.id} value={v.id}>
                  {versionLabel(v)}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {open && changes.isFetching && <p className="state">Comparing…</p>}
      {open && changes.error && (
        <p className="state error">{(changes.error as Error).message}</p>
      )}
      {open && data && !hasChanges(data) && !changes.isFetching && (
        <p className="state">{headline(data)}</p>
      )}
      {open && !versions.isFetching && list.length === 0 && data && (
        <p className="soft" data-testid="file-changes-versions-empty">
          {versionsEmptyNote(data.state)}
        </p>
      )}
      {open && data && hasChanges(data) && (
        <table className="repo-diff-table">
          <tbody>
            {rows.map((r, i) => (
              <Fragment key={`${r.live_line ?? "x"}-${r.proposed_line ?? "x"}-${i}`}>
                {isGap(data.rows, rows, i) && (
                  <tr className="repo-diff-gap">
                    <td colSpan={4}>…</td>
                  </tr>
                )}
                <tr className={`repo-diff-row ${r.kind}`}>
                  <td className="repo-diff-num">{r.live_line ?? ""}</td>
                  <td className="repo-diff-text">{r.live_text ?? ""}</td>
                  <td className="repo-diff-num">{r.proposed_line ?? ""}</td>
                  <td className="repo-diff-text">{r.proposed_text ?? ""}</td>
                </tr>
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
