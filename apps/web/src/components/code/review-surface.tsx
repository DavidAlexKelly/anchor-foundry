"use client";

/** The pull request review surface (ROADMAP.md phase 2, item 2.7).
 *
 * Anchor already had proposals, reviews, blockers and a gate - the *governance*
 * half, built as `STATUS.md` §45–§47. What it had was a side panel showing a
 * unified diff and four buttons. What a review is actually made of is missing
 * from that: you cannot point at a line, you cannot say "I have read this one",
 * and two versions of a file cannot be seen at once.
 *
 * Three things this has to get right, and the third is the one that is easy to
 * get wrong:
 *
 *   1. **Side by side, with line numbers that mean something.** The alignment
 *      comes from the API (`files[].rows`), not from parsing a unified diff in
 *      the browser - a comment anchored to a number recovered from a rendering
 *      is anchored to a parser bug waiting to happen.
 *   2. **A comment hangs on a line of a side**, and is written where it hangs.
 *      Clicking a line opens the box against that line; there is no "which file
 *      and which line did you mean" form, because that form is how comments end
 *      up on the wrong line.
 *   3. **An outdated comment is shown, marked.** The proposal moved under it,
 *      so its line number is about text nobody will apply - but it said
 *      something true when it was written, and hiding it loses the reason a
 *      change was made.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, code as codeApi } from "@/lib/api";
import type {
  CodeCheck,
  CodeDiffRow,
  CodeProposalComment,
  CodeProposalDetail,
  CodeProposalFile,
} from "@/lib/types";

/** Prefilled into a new proposal's description. Foundry's Code Repositories
 * offers pull request description templates; this is the built-in one.
 *
 * It is deliberately *not* per project yet. A configurable template needs
 * somewhere to live, and the place it belongs in every system that has one is
 * the repository - which proposals are not yet connected to (they change
 * `models`, not a branch). Shipping a project-level setting now would put it in
 * the wrong place and make moving it a migration.
 */
export const DESCRIPTION_TEMPLATE = `## What this changes

## Why

## How it was checked
`;

export function ReviewSurface({
  workspaceId,
  projectId,
  proposalId,
  canReview,
  onChanged,
}: {
  workspaceId: string;
  projectId: string;
  proposalId: string;
  canReview: boolean;
  onChanged?: () => void;
}) {
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const [failure, setFailure] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["code-proposal", proposalId],
    queryFn: () => codeApi.proposal(workspaceId, projectId, proposalId),
  });

  // Every mutation here returns the whole proposal, so the cache is *set* from
  // the response rather than invalidated and refetched. A refetch would put a
  // spinner over a diff somebody is reading.
  function landed(next: CodeProposalDetail) {
    queryClient.setQueryData(["code-proposal", proposalId], next);
    setFailure(null);
    onChanged?.();
  }
  const fail = (e: Error) =>
    setFailure(e instanceof ApiError ? e.message : "That didn't work.");

  const act = useMutation({
    mutationFn: (action: "approve" | "request_changes" | "apply" | "withdraw") => {
      if (action === "apply") return codeApi.applyProposal(workspaceId, projectId, proposalId);
      if (action === "withdraw") return codeApi.withdrawProposal(workspaceId, projectId, proposalId);
      return codeApi.review(workspaceId, projectId, proposalId, {
        verdict: action,
        comment,
      });
    },
    onSuccess: (next) => {
      setComment("");
      landed(next);
    },
    onError: fail,
  });

  const say = useMutation({
    mutationFn: (input: {
      model_id: string;
      side: "live" | "proposed";
      line: number | null;
      body: string;
    }) => codeApi.comment(workspaceId, projectId, proposalId, input),
    onSuccess: landed,
    onError: fail,
  });

  const settle = useMutation({
    mutationFn: (input: { id: string; resolved: boolean }) =>
      codeApi.resolveComment(workspaceId, projectId, proposalId, input.id, input.resolved),
    onSuccess: landed,
    onError: fail,
  });

  const mark = useMutation({
    mutationFn: (input: { model_id: string; read: boolean }) =>
      codeApi.markFileRead(workspaceId, projectId, proposalId, input),
    onSuccess: landed,
    onError: fail,
  });

  const check = useMutation({
    mutationFn: () => codeApi.runChecks(workspaceId, projectId, proposalId),
    onSuccess: landed,
    onError: fail,
  });

  if (detail.isPending) return <p className="state">Loading review…</p>;
  if (detail.isError) return <p className="state error">{(detail.error as Error).message}</p>;

  const p = detail.data;
  const open = p.state === "open";
  const unresolved = p.comments.filter((c) => !c.resolved_at && !c.outdated).length;

  return (
    <div className="review">
      <header className="review-head">
        <div>
          <h2>{p.summary}</h2>
          <p className="review-meta">
            <span className={`chip${open ? "" : " brass"}`}>{p.state}</span>{" "}
            {p.created_by_email ?? "unknown"} · {new Date(p.created_at).toLocaleString()} ·{" "}
            {p.files.length} file{p.files.length === 1 ? "" : "s"}
            {unresolved > 0 && (
              <>
                {" · "}
                <span className="review-unresolved">
                  {unresolved} unresolved comment{unresolved === 1 ? "" : "s"}
                </span>
              </>
            )}
          </p>
        </div>
      </header>

      {p.description && <pre className="review-description">{p.description}</pre>}

      <ChecksPanel
        checks={p.checks}
        open={open}
        canRun={canReview}
        running={check.isPending}
        onRun={() => check.mutate()}
      />

      {p.files.map((file) => (
        <FileReview
          key={file.model_id}
          file={file}
          open={open}
          onSay={(side, line, body) =>
            say.mutate({ model_id: file.model_id, side, line, body })
          }
          onSettle={(id, resolved) => settle.mutate({ id, resolved })}
          onMark={(read) => mark.mutate({ model_id: file.model_id, read })}
          busy={say.isPending || mark.isPending}
        />
      ))}

      {p.reviews.length > 0 && (
        <ul className="review-verdicts">
          {p.reviews.map((r) => (
            <li key={r.id}>
              <span className={`chip${r.verdict === "approve" ? "" : " brass"}`}>
                {r.verdict === "approve" ? "approved" : "changes requested"}
              </span>{" "}
              {r.reviewer_email ?? "unknown"}
              {r.comment ? ` — ${r.comment}` : ""}
              <span className="soft"> {new Date(r.created_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}

      {p.blockers.length > 0 && (
        <ul className="code-blockers">
          {p.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
      {failure && <p className="state error">{failure}</p>}

      {canReview && open && (
        <div className="review-actions">
          <input
            type="text"
            value={comment}
            placeholder="Comment on the whole proposal (optional)"
            aria-label="Review comment"
            onChange={(e) => setComment(e.target.value)}
          />
          <button type="button" className="btn quiet" onClick={() => act.mutate("approve")}>
            Approve
          </button>
          <button
            type="button"
            className="btn quiet"
            onClick={() => act.mutate("request_changes")}
          >
            Request changes
          </button>
          <button
            type="button"
            className="btn"
            disabled={p.blockers.length > 0 || act.isPending}
            onClick={() => act.mutate("apply")}
          >
            Apply
          </button>
          <button type="button" className="btn quiet" onClick={() => act.mutate("withdraw")}>
            Withdraw
          </button>
        </div>
      )}
    </div>
  );
}

/** Checks (roadmap 2.8): what ran, what it found, and — loudly — when nothing
 * has run against the code as it now stands.
 *
 * Silence is the thing this panel exists to stop being mistaken for a pass. A
 * proposal with no checks and a proposal whose checks all went stale both look
 * like "no problems found" unless somebody says otherwise, so both get a
 * sentence rather than an empty space.
 */
function ChecksPanel({
  checks,
  open,
  canRun,
  running,
  onRun,
}: {
  checks: CodeCheck[];
  open: boolean;
  canRun: boolean;
  running: boolean;
  onRun: () => void;
}) {
  const current = checks.filter((c) => !c.stale);
  const stale = checks.filter((c) => c.stale);
  const failed = current.filter((c) => c.status === "fail").length;
  const warned = current.filter((c) => c.status === "warn").length;
  const errored = current.filter((c) => c.status === "error").length;

  return (
    <section className="review-checks">
      <header className="review-checks-head">
        <strong>Checks</strong>
        {current.length === 0 ? (
          <span className="review-checks-none">
            {stale.length > 0
              ? "None have run against the code as it now stands."
              : "None have run."}
          </span>
        ) : (
          <span className="review-checks-tally">
            {failed > 0 && <span className="fail">{failed} failed</span>}
            {warned > 0 && <span className="warn">{warned} warning</span>}
            {errored > 0 && <span className="error">{errored} could not run</span>}
            {failed === 0 && warned === 0 && errored === 0 && (
              <span className="pass">all passed</span>
            )}
          </span>
        )}
        {canRun && open && (
          <button type="button" className="btn quiet review-checks-run" onClick={onRun} disabled={running}>
            {running ? "Running…" : current.length ? "Run again" : "Run checks"}
          </button>
        )}
      </header>

      {checks.length > 0 && (
        <ul className="review-check-list">
          {[...current, ...stale].map((c) => (
            <li key={c.id} className={`${c.status}${c.stale ? " stale" : ""}`}>
              <span className="review-check-status">{c.status}</span>
              <span className="review-check-name">{c.name}</span>
              <span className="review-check-summary">{c.summary}</span>
              {c.stale && (
                <span className="review-tag" title="The proposal changed after this ran">
                  stale
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** One file: the aligned diff, its comments in place, and the read mark. */
function FileReview({
  file,
  open,
  onSay,
  onSettle,
  onMark,
  busy,
}: {
  file: CodeProposalFile;
  open: boolean;
  onSay: (side: "live" | "proposed", line: number | null, body: string) => void;
  onSettle: (id: string, resolved: boolean) => void;
  onMark: (read: boolean) => void;
  busy: boolean;
}) {
  // Which line the comment box is open against, as "side:line". Held here
  // rather than on the row so opening a second box closes the first: two open
  // boxes is two half-written comments and one of them gets lost.
  const [openAt, setOpenAt] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [collapsed, setCollapsed] = useState(false);

  const stale = file.base_version !== file.current_version;
  const fileComments = file.comments.filter((c) => c.line === null);

  function commentsAt(side: "live" | "proposed", line: number | null) {
    return file.comments.filter((c) => c.side === side && c.line === line);
  }

  function submit(side: "live" | "proposed", line: number | null) {
    if (!draft.trim()) return;
    onSay(side, line, draft.trim());
    setDraft("");
    setOpenAt(null);
  }

  return (
    <section className="review-file">
      <header className="review-file-head">
        <button
          type="button"
          className="review-file-toggle"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? "▸" : "▾"} {file.path ?? file.model_name}
        </button>
        <span className="code-tree-meta">
          proposed against v{file.base_version}
          {stale && ` · live is now v${file.current_version}`}
        </span>
        {file.read_by.length > 0 && (
          <span className="review-read-by">
            read by {file.read_by.map((m) => m.reviewer_email ?? "someone").join(", ")}
          </span>
        )}
        {open && (
          <button
            type="button"
            className="review-mark"
            onClick={() => onMark(file.read_by.length === 0)}
            disabled={busy}
          >
            {file.read_by.length > 0 ? "Unmark" : "Mark as read"}
          </button>
        )}
      </header>

      {!collapsed && (
        <>
          <table className="review-diff">
            <tbody>
              {file.rows.map((row, i) => (
                <DiffLine
                  key={i}
                  row={row}
                  open={open}
                  openAt={openAt}
                  draft={draft}
                  onDraft={setDraft}
                  onOpenAt={(key) => {
                    setOpenAt(key);
                    setDraft("");
                  }}
                  commentsAt={commentsAt}
                  onSettle={onSettle}
                  onSubmit={submit}
                />
              ))}
            </tbody>
          </table>

          {fileComments.length > 0 && (
            <div className="review-file-comments">
              {fileComments.map((c) => (
                <CommentBubble key={c.id} comment={c} onSettle={onSettle} />
              ))}
            </div>
          )}
          {open && (
            <div className="review-file-say">
              {openAt === "file" ? (
                <CommentBox
                  value={draft}
                  onChange={setDraft}
                  onCancel={() => setOpenAt(null)}
                  onSubmit={() => submit("proposed", null)}
                  label={`Comment on ${file.path ?? file.model_name}`}
                />
              ) : (
                <button type="button" className="review-say-link" onClick={() => setOpenAt("file")}>
                  Comment on this file
                </button>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function DiffLine({
  row,
  open,
  openAt,
  draft,
  onDraft,
  onOpenAt,
  commentsAt,
  onSettle,
  onSubmit,
}: {
  row: CodeDiffRow;
  open: boolean;
  openAt: string | null;
  draft: string;
  onDraft: (v: string) => void;
  onOpenAt: (key: string) => void;
  commentsAt: (side: "live" | "proposed", line: number | null) => CodeProposalComment[];
  onSettle: (id: string, resolved: boolean) => void;
  onSubmit: (side: "live" | "proposed", line: number | null) => void;
}) {
  const liveKey = row.live_line === null ? null : `live:${row.live_line}`;
  const proposedKey = row.proposed_line === null ? null : `proposed:${row.proposed_line}`;
  const attached = [
    ...(row.live_line === null ? [] : commentsAt("live", row.live_line)),
    ...(row.proposed_line === null ? [] : commentsAt("proposed", row.proposed_line)),
  ];
  const boxKey = openAt === liveKey ? liveKey : openAt === proposedKey ? proposedKey : null;

  return (
    <>
      <tr className={`review-line ${row.kind}`}>
        <Side
          n={row.live_line}
          text={row.live_text}
          side="live"
          kind={row.kind}
          clickable={open && row.live_line !== null}
          onClick={() => liveKey && onOpenAt(liveKey)}
        />
        <Side
          n={row.proposed_line}
          text={row.proposed_text}
          side="proposed"
          kind={row.kind}
          clickable={open && row.proposed_line !== null}
          onClick={() => proposedKey && onOpenAt(proposedKey)}
        />
      </tr>
      {(attached.length > 0 || boxKey) && (
        <tr className="review-thread-row">
          <td colSpan={4}>
            {attached.map((c) => (
              <CommentBubble key={c.id} comment={c} onSettle={onSettle} />
            ))}
            {boxKey && (
              <CommentBox
                value={draft}
                onChange={onDraft}
                onCancel={() => onOpenAt("")}
                onSubmit={() =>
                  onSubmit(
                    boxKey.startsWith("live") ? "live" : "proposed",
                    Number(boxKey.split(":")[1]),
                  )
                }
                label={`Comment on line ${boxKey.split(":")[1]}`}
              />
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function Side({
  n,
  text,
  side,
  kind,
  clickable,
  onClick,
}: {
  n: number | null;
  text: string | null;
  side: "live" | "proposed";
  kind: CodeDiffRow["kind"];
  clickable: boolean;
  onClick: () => void;
}) {
  // An empty cell on one side is not "line zero" - it is the absence of a line,
  // and giving it a number would make it commentable.
  const filled = n !== null;
  const tone = !filled
    ? "blank"
    : kind === "same"
      ? "same"
      : side === "live"
        ? kind === "added"
          ? "blank"
          : "removed"
        : kind === "removed"
          ? "blank"
          : "added";
  return (
    <>
      <td className={`review-num ${tone}`}>{filled ? n : ""}</td>
      <td className={`review-code ${tone}`}>
        {clickable && (
          <button
            type="button"
            className="review-add-comment"
            aria-label={`Comment on ${side} line ${n}`}
            onClick={onClick}
          >
            +
          </button>
        )}
        <code>{text ?? ""}</code>
      </td>
    </>
  );
}

function CommentBubble({
  comment,
  onSettle,
}: {
  comment: CodeProposalComment;
  onSettle: (id: string, resolved: boolean) => void;
}) {
  return (
    <div
      className={`review-comment${comment.outdated ? " outdated" : ""}${
        comment.resolved_at ? " resolved" : ""
      }`}
    >
      <p className="review-comment-meta">
        <strong>{comment.author_email ?? "unknown"}</strong>{" "}
        <span className="soft">{new Date(comment.created_at).toLocaleString()}</span>
        {comment.outdated && (
          <span className="review-tag" title="The proposal changed after this was written">
            outdated
          </span>
        )}
        {comment.resolved_at && <span className="review-tag">resolved</span>}
      </p>
      <p className="review-comment-body">{comment.body}</p>
      <button
        type="button"
        className="review-say-link"
        onClick={() => onSettle(comment.id, !comment.resolved_at)}
      >
        {comment.resolved_at ? "Reopen" : "Resolve"}
      </button>
    </div>
  );
}

function CommentBox({
  value,
  onChange,
  onCancel,
  onSubmit,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
  label: string;
}) {
  return (
    <form
      className="review-comment-box"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={label}
        aria-label={label}
        rows={3}
        autoFocus
      />
      <div className="row-actions">
        <button className="btn" type="submit" disabled={!value.trim()}>
          Comment
        </button>
        <button type="button" className="btn quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
