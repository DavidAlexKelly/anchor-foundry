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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { repositories as repoApi } from "@/lib/api";
import type { RepositoryTree, ResolvedResource, TransformPreview } from "@/lib/types";

// Monaco touches `window` at module scope and is ~1 MB nothing else needs.
const CodeEditor = dynamic(
  () => import("@/components/code-editor").then((m) => m.CodeEditor),
  { ssr: false, loading: () => <div className="code-editor-loading">Loading editor…</div> },
);

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
  onOpen: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  // The working set: the committed tree with unsaved edits laid over it. Kept
  // apart from the query cache so a refetch cannot silently discard typing,
  // and reset only when the ref changes - switching branch or commit is a
  // deliberate act, and losing edits to it is the user's own decision.
  const [edits, setEdits] = useState<Record<string, string | null>>({});
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  useEffect(() => {
    setEdits({});
    setMessage("");
  }, [tree?.commit_id, branch]);

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

  const commit = useMutation({
    mutationFn: () =>
      repoApi.commit(wid, pid, rid, { branch, files: working, message }),
    onSuccess: () => {
      setEdits({});
      setMessage("");
      setFailure(null);
      queryClient.invalidateQueries({ queryKey: ["repo-tree", rid] });
      queryClient.invalidateQueries({ queryKey: ["repo-commits", rid] });
      queryClient.invalidateQueries({ queryKey: ["repo-branches", rid] });
    },
    onError: (e: Error) => setFailure(e.message),
  });

  if (pending) return <p className="state">Loading files…</p>;
  if (error) return <p className="state error">{error.message}</p>;

  const paths = Object.keys(working).sort();
  const selected = openPath && paths.includes(openPath) ? openPath : paths[0];
  const source = selected === undefined ? undefined : working[selected];
  // Editing is against a branch. A pinned commit is history, and history that
  // could be typed into would stop being a record of what happened.
  const readOnly = pinned;

  function addFile() {
    const path = window.prompt("New file path", "src/new.sql");
    if (!path) return;
    if (paths.includes(path)) {
      setFailure(`${path} already exists`);
      return;
    }
    setEdits((c) => ({ ...c, [path]: "" }));
    onOpen(path);
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
                onClick={() => onOpen(path)}
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
                <button
                  type="button"
                  onClick={() => setEdits((c) => ({ ...c, [selected]: null }))}
                >
                  Delete file
                </button>
              )}
            </div>
          )}
        </div>

        <div className="repo-viewer">
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
                  onChange={(next) => setEdits((c) => ({ ...c, [selected]: next }))}
                />
              </div>
              <PreviewPanel
                wid={wid}
                pid={pid}
                rid={rid}
                path={selected}
                content={source}
              />
            </>
          ) : (
            <p className="state">
              {readOnly ? "This commit contains no files." : "No files yet."}
            </p>
          )}
        </div>
      </div>

      {!readOnly && dirty && (
        <form
          className="repo-commit-bar"
          onSubmit={(e) => {
            e.preventDefault();
            commit.mutate();
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
          <button className="btn" type="submit" disabled={commit.isPending}>
            {commit.isPending ? "Committing…" : `Commit to ${branch}`}
          </button>
          <button type="button" className="repo-discard" onClick={() => setEdits({})}>
            Discard
          </button>
        </form>
      )}
      {failure && <p className="state error">{failure}</p>}
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
