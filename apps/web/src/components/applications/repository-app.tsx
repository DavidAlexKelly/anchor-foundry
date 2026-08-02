"use client";

/** The repository application (ROADMAP.md phase 2, section 2).
 *
 * Read-only. Editing arrives with the editor in item 2.2, and shipping a
 * viewer first is deliberate: it makes the storage layer decision 0003 settled
 * something a person can actually look at, and every question the editor will
 * need answered - which branch, which commit, what changed - is answered here
 * without a 2 MB dependency in the way.
 *
 * A repository is a tree at a *ref*, so the ref is in the URL alongside the
 * open file. "Look at this file on this branch" has to be a link, or reviewing
 * anything means describing where to click.
 */

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { repositories as repoApi } from "@/lib/api";
import type { RepositoryTree, ResolvedResource } from "@/lib/types";

type Tab = "files" | "history";

export function RepositoryApplication({ resource }: { resource: ResolvedResource }) {
  const router = useRouter();
  const params = useSearchParams();

  const wid = resource.workspace_id;
  const pid = resource.project_id!;
  const rid = resource.kind_id;

  const tab: Tab = params.get("tab") === "history" ? "history" : "files";
  const branch = params.get("branch") ?? undefined;
  const commitId = params.get("commit") ?? undefined;
  const openPath = params.get("file") ?? undefined;

  function setParams(next: Record<string, string | undefined>) {
    const search = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(next)) {
      if (value === undefined) search.delete(key);
      else search.set(key, value);
    }
    router.replace(`?${search.toString()}`, { scroll: false });
  }

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
          {(["files", "history"] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              className={`ds-tab${t === tab ? " on" : ""}`}
              aria-current={t === tab}
              onClick={() => setParams({ tab: t })}
            >
              {t === "files" ? "Files" : "History"}
            </button>
          ))}
        </nav>
      </div>

      {tab === "files" ? (
        <FilesTab
          tree={tree.data}
          pending={tree.isPending}
          error={tree.error as Error | null}
          openPath={openPath}
          onOpen={(path) => setParams({ file: path })}
        />
      ) : (
        <HistoryTab
          wid={wid}
          pid={pid}
          rid={rid}
          branch={current}
          onOpenCommit={(id) => setParams({ commit: id, tab: "files", file: undefined })}
        />
      )}
    </div>
  );
}

function FilesTab({
  tree,
  pending,
  error,
  openPath,
  onOpen,
}: {
  tree: RepositoryTree | undefined;
  pending: boolean;
  error: Error | null;
  openPath: string | undefined;
  onOpen: (path: string) => void;
}) {
  if (pending) return <p className="state">Loading files…</p>;
  if (error) return <p className="state error">{error.message}</p>;
  if (!tree || tree.commit_id === null) {
    return (
      <p className="state">
        This repository is empty. Nothing has been committed to it yet.
      </p>
    );
  }

  const paths = Object.keys(tree.files).sort();
  // The requested file if it exists at this ref, otherwise the first. Switching
  // branches while a file is open must not blank the pane when that file does
  // not exist on the branch you moved to.
  const selected = openPath && paths.includes(openPath) ? openPath : paths[0];
  const source = selected === undefined ? undefined : tree.files[selected];

  return (
    <div className="repo-split">
      <nav className="repo-tree" aria-label="Files">
        {paths.map((path) => (
          <button
            key={path}
            type="button"
            className={`repo-file${path === selected ? " on" : ""}`}
            aria-current={path === selected}
            onClick={() => onOpen(path)}
          >
            {path}
          </button>
        ))}
      </nav>
      <div className="repo-viewer">
        {selected !== undefined && source !== undefined ? (
          <>
            <div className="repo-file-head">
              <code>{selected}</code>
              <span className="soft">{source.split("\n").length} lines</span>
            </div>
            {/* Plain text, with line numbers rendered beside it rather than
                inside it, so a copy of the file is the file. Highlighting is
                the editor's job (2.2). */}
            <pre className="repo-source">
              <code>{source}</code>
            </pre>
          </>
        ) : (
          <p className="state">This commit contains no files.</p>
        )}
      </div>
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
