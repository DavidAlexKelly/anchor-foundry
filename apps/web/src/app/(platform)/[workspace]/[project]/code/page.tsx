"use client";

/**
 * The Code pillar (ROADMAP Code item 2).
 *
 * There is no "new repository" button, and its absence is the design:
 * `docs/decisions/0001-where-code-lives.md` decided this pillar renders the
 * transform history Models already writes rather than storing code a second
 * time, because a run is pinned to the exact definition that produced it and
 * a git ref cannot promise that. So a project's transforms *are* the
 * repository - this page is the file tree, the source, the diff and the
 * commit log over them.
 *
 * The one thing it can do that the inline Models editor cannot is stage
 * several files and save them as **one change set**, which is the only
 * genuinely new concept here: before it, "these three transforms changed
 * together, for one reason" could not be said.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { ApiError, code as codeApi } from "@/lib/api";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import { DESCRIPTION_TEMPLATE, ReviewSurface } from "@/components/code/review-surface";
import type { CodeFile, CodeHistoryEntry } from "@/lib/types";

function DiffText({ text }: { text: string }) {
  if (!text.trim()) {
    return <p className="canvas-widget-empty">No difference between these versions.</p>;
  }
  return (
    <pre className="code-diff">
      {text.split("\n").map((line, i) => {
        const kind =
          line.startsWith("+++") || line.startsWith("---")
            ? "meta"
            : line.startsWith("@@")
              ? "hunk"
              : line.startsWith("+")
                ? "add"
                : line.startsWith("-")
                  ? "del"
                  : "ctx";
        return (
          <span key={i} className={`diff-line diff-${kind}`}>
            {line || " "}
          </span>
        );
      })}
    </pre>
  );
}

function HistoryList({
  entries,
  onOpen,
}: {
  entries: CodeHistoryEntry[];
  onOpen: (entry: CodeHistoryEntry) => void;
}) {
  if (entries.length === 0) {
    return <p className="canvas-widget-empty">No edits recorded yet.</p>;
  }
  return (
    <ul className="code-log">
      {entries.map((entry) => (
        <li key={`${entry.kind}-${entry.id}`}>
          <button type="button" className="code-log-entry" onClick={() => onOpen(entry)}>
            <span className="code-log-summary">{entry.summary}</span>
            <span className="code-log-meta">
              {/* Two kinds of entry, deliberately: a standalone save from the
                  Models editor is a real edit with no message, and inventing
                  one for it would claim an intention nobody expressed. */}
              <span className={`chip${entry.kind === "change_set" ? " brass" : ""}`}>
                {entry.kind === "change_set"
                  ? `${entry.model_count} file${entry.model_count === 1 ? "" : "s"}`
                  : "single save"}
              </span>
              {entry.created_by_email ?? "unknown"} ·{" "}
              {new Date(entry.created_at).toLocaleString()}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function CodePage() {
  const params = useParams<{ workspace: string; project: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const queryClient = useQueryClient();

  const [selected, setSelected] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState("");
  // Prefilled, and editable to nothing. A template that cannot be emptied is a
  // template that gets submitted with its headings still blank.
  const [description, setDescription] = useState(DESCRIPTION_TEMPLATE);
  const [viewing, setViewing] = useState<CodeHistoryEntry | null>(null);
  const [openProposal, setOpenProposal] = useState<string | null>(null);

  const ready = !!workspace && !!project;
  const tree = useQuery({
    queryKey: ["code-tree", project?.id],
    queryFn: () => codeApi.tree(workspace!.id, project!.id),
    enabled: ready,
  });
  const files = useMemo(() => tree.data ?? [], [tree.data]);
  const current: CodeFile | undefined = files.find((f) => f.id === selected) ?? files[0];

  const file = useQuery({
    queryKey: ["code-file", current?.id, current?.current_version],
    queryFn: () => codeApi.file(workspace!.id, project!.id, current!.id),
    enabled: ready && !!current,
  });
  const history = useQuery({
    queryKey: ["code-history", project?.id],
    queryFn: () => codeApi.history(workspace!.id, project!.id),
    enabled: ready,
  });
  const changeSet = useQuery({
    queryKey: ["code-change-set", viewing?.id],
    queryFn: () => codeApi.changeSet(workspace!.id, project!.id, viewing!.id),
    enabled: ready && viewing?.kind === "change_set",
  });
  const versionDiff = useQuery({
    queryKey: ["code-diff", viewing?.id, viewing?.model_id, viewing?.version_number],
    queryFn: () =>
      codeApi.diff(
        workspace!.id,
        project!.id,
        viewing!.model_id!,
        (viewing!.version_number ?? 1) - 1 || null,
        viewing!.version_number ?? undefined,
      ),
    enabled: ready && viewing?.kind === "version" && !!viewing?.model_id,
  });

  const policy = useQuery({
    queryKey: ["code-review-policy", project?.id],
    queryFn: () => codeApi.reviewPolicy(workspace!.id, project!.id),
    enabled: ready,
  });
  const proposals = useQuery({
    queryKey: ["code-proposals", project?.id],
    queryFn: () => codeApi.proposals(workspace!.id, project!.id, "open"),
    enabled: ready,
  });

  const canEdit = project ? project.effective_role !== "viewer" : false;
  const isOwner = project?.effective_role === "owner";
  const reviewRequired = policy.data?.require_code_review ?? false;
  const stagedCount = Object.keys(drafts).length;

  const refreshAll = async () => {
    setDrafts({});
    setSummary("");
    setDescription(DESCRIPTION_TEMPLATE);
    await queryClient.invalidateQueries({ queryKey: ["code-tree", project?.id] });
    await queryClient.invalidateQueries({ queryKey: ["code-history", project?.id] });
    await queryClient.invalidateQueries({ queryKey: ["code-proposals", project?.id] });
    await queryClient.invalidateQueries({ queryKey: ["code-file"] });
  };

  const save = useMutation({
    mutationFn: () =>
      codeApi.saveChangeSet(workspace!.id, project!.id, {
        summary,
        changes: Object.entries(drafts).map(([model_id, code]) => ({ model_id, code })),
      }),
    onSuccess: refreshAll,
  });
  const propose = useMutation({
    mutationFn: () =>
      codeApi.propose(workspace!.id, project!.id, {
        summary,
        description,
        changes: Object.entries(drafts).map(([model_id, code]) => ({ model_id, code })),
      }),
    onSuccess: async (created) => {
      await refreshAll();
      setOpenProposal(created.id);
    },
  });
  const setPolicy = useMutation({
    mutationFn: (required: boolean) =>
      codeApi.setReviewPolicy(workspace!.id, project!.id, required),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["code-review-policy", project?.id] });
    },
  });

  const body = current ? drafts[current.id] ?? file.data?.code ?? "" : "";

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · code</p>
          <h1>Code</h1>
          <p className="sub">
            Every transform in this project, with the history Models already keeps.
            Editing here writes the same versions a run resolves against.
          </p>
        </div>
        <div className="row-actions">
          {/* The gate is a property of the project, so it is stated wherever
              code is edited rather than hidden in a settings page. */}
          <span className={`chip${reviewRequired ? " brass" : ""}`}>
            {reviewRequired ? "review required" : "direct edits allowed"}
          </span>
          {isOwner && (
            <button
              type="button"
              className="btn quiet"
              disabled={setPolicy.isPending}
              onClick={() => setPolicy.mutate(!reviewRequired)}
            >
              {reviewRequired ? "Allow direct edits" : "Require review"}
            </button>
          )}
        </div>
      </div>

      {tree.isPending && <div className="state">Loading…</div>}
      {tree.isError && (
        <div className="state error">Couldn&apos;t load this project&apos;s code.</div>
      )}
      {tree.data && files.length === 0 && (
        <div className="empty">
          <h2>No transforms yet</h2>
          <p>
            A project&apos;s models are its code. Create one under{" "}
            <Link href={`/${params.workspace}/${params.project}/models`}>Models</Link> and
            it appears here as a file.
          </p>
        </div>
      )}

      {openProposal && workspace && project && (
        <div className="code-review-mode">
          <div className="canvas-settings-head">
            <strong>Reviewing a proposal</strong>
            <button
              type="button"
              className="btn quiet"
              style={{ padding: "3px 9px", fontSize: 12 }}
              onClick={() => setOpenProposal(null)}
            >
              Back to the editor
            </button>
          </div>
          <ReviewSurface
            workspaceId={workspace.id}
            projectId={project.id}
            proposalId={openProposal}
            canReview={canEdit}
            onChanged={refreshAll}
          />
        </div>
      )}

      {files.length > 0 && !openProposal && (
        <div className="code-shell">
          <aside className="code-tree">
            <p className="field-label">Files</p>
            <ul>
              {files.map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    className={`code-tree-item${current?.id === f.id ? " current" : ""}`}
                    onClick={() => setSelected(f.id)}
                  >
                    <span>{f.path}</span>
                    <span className="code-tree-meta">
                      {drafts[f.id] !== undefined ? "edited" : `v${f.current_version ?? 1}`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>

          <section className="code-main">
            {current && (
              <>
                <div className="code-file-head">
                  <strong>{current.path}</strong>
                  <span className="code-tree-meta">
                    {current.language} · v{file.data?.version_number ?? current.current_version}
                  </span>
                </div>
                <textarea
                  className="code-editor"
                  spellCheck={false}
                  value={body}
                  readOnly={!canEdit}
                  aria-label={`Source of ${current.path}`}
                  onChange={(e) => setDrafts((d) => ({ ...d, [current.id]: e.target.value }))}
                />
              </>
            )}

            {canEdit && stagedCount > 0 && (
              <div className="code-commit">
                <p className="field-label">
                  {stagedCount} file{stagedCount === 1 ? "" : "s"} staged
                </p>
                <p className="canvas-widget-empty">
                  {reviewRequired
                    ? "This project requires review, so these files become a proposal: nothing takes effect until somebody else approves it and it is applied."
                    : "Saving writes one version per changed file, grouped under this message — files whose content is unchanged are skipped, and if none of them changed the whole save is refused."}
                </p>
                <input
                  type="text"
                  value={summary}
                  placeholder="What does this change do?"
                  aria-label="Change summary"
                  onChange={(e) => setSummary(e.target.value)}
                />
                {reviewRequired && (
                  <textarea
                    className="code-description"
                    rows={7}
                    value={description}
                    aria-label="Proposal description"
                    placeholder="What this changes, why, and how it was checked"
                    onChange={(e) => setDescription(e.target.value)}
                  />
                )}
                {(save.isError || propose.isError) && (
                  <div className="form-error">
                    {(save.error ?? propose.error) instanceof ApiError
                      ? (save.error ?? propose.error as ApiError).message
                      : "Couldn't save this change."}
                  </div>
                )}
                <div className="row-actions">
                  {reviewRequired ? (
                    <button
                      type="button"
                      className="btn"
                      disabled={!summary.trim() || propose.isPending}
                      onClick={() => propose.mutate()}
                    >
                      {propose.isPending ? "Opening…" : "Open proposal"}
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="btn"
                        disabled={!summary.trim() || save.isPending}
                        onClick={() => save.mutate()}
                      >
                        {save.isPending ? "Saving…" : "Save change set"}
                      </button>
                      <button
                        type="button"
                        className="btn quiet"
                        disabled={!summary.trim() || propose.isPending}
                        onClick={() => propose.mutate()}
                      >
                        Propose instead
                      </button>
                    </>
                  )}
                  <button
                    type="button"
                    className="btn quiet"
                    onClick={() => {
                      setDrafts({});
                      setSummary("");
                    }}
                  >
                    Discard
                  </button>
                </div>
              </div>
            )}
          </section>

          <aside className="code-side">
            {proposals.data && proposals.data.length > 0 && (
              <>
                <p className="field-label">Open proposals</p>
                <ul className="code-log">
                  {proposals.data.map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        className="code-log-entry"
                        onClick={() => {
                          setViewing(null);
                          setOpenProposal(p.id);
                        }}
                      >
                        <span className="code-log-summary">{p.summary}</span>
                        <span className="code-log-meta">
                          <span className="chip brass">
                            {p.file_count} file{p.file_count === 1 ? "" : "s"}
                          </span>
                          {p.created_by_email ?? "unknown"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <p className="field-label">History</p>
            {history.data && <HistoryList entries={history.data} onOpen={setViewing} />}
            {viewing && (
              <div className="code-detail">
                <div className="canvas-settings-head">
                  <strong>{viewing.summary}</strong>
                  <button
                    type="button"
                    className="btn quiet"
                    style={{ padding: "3px 9px", fontSize: 12 }}
                    onClick={() => setViewing(null)}
                  >
                    Close
                  </button>
                </div>
                {viewing.kind === "change_set" && changeSet.data && (
                  <>
                    {changeSet.data.description && <p>{changeSet.data.description}</p>}
                    <ul className="code-log">
                      {changeSet.data.models.map((m) => (
                        <li key={m.model_id} className="code-change-file">
                          {m.path}{" "}
                          <span className="code-tree-meta">
                            v{m.previous_version ?? "—"} → v{m.version_number}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                {viewing.kind === "version" && versionDiff.data && (
                  <DiffText text={versionDiff.data.diff} />
                )}
              </div>
            )}
          </aside>
        </div>
      )}
    </main>
  );
}
