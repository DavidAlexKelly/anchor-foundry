"use client";

/**
 * p.137's Comments Helper (§322; `object-views` p.137).
 *
 * > "Object Explorer allows users to comment on an object, mention other
 * > users, and attach files and images. You can open the Comments Helper for
 * > any object using the **View comments** button in the header of any Object
 * > View." (p.137)
 *
 * **Above both renderings, like §312's star.** The button belongs to the
 * object, not to a view of it: the standard view owns its own title and a
 * configured view is somebody's Workshop module with no title of ours at all,
 * so anything placed inside either would exist for one kind of object and not
 * the other.
 *
 * The wording and the cutting of a body at its mentions are in
 * `lib/object-comments.ts`; this draws them and posts.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, objects as objApi } from "@/lib/api";
import {
  EMPTY_THREAD,
  authorLabel,
  buttonLabel,
  isEmpty,
  segments,
} from "@/lib/object-comments";

export function CommentsButton({
  workspaceId,
  typeId,
  instanceId,
  canComment,
}: {
  workspaceId: string;
  typeId: string;
  instanceId: string;
  /** Reading a conversation is `viewer`; adding to it is a write. The panel
   * still opens for a viewer — p.137's cooperation is worth reading even when
   * you cannot add to it — and the composer is what is absent. */
  canComment: boolean;
}) {
  const [open, setOpen] = useState(false);
  const count = useQuery({
    queryKey: ["object-comment-count", typeId, instanceId],
    queryFn: () => objApi.commentCount(workspaceId, typeId, instanceId),
  });

  return (
    <>
      <button
        type="button"
        className="btn quiet"
        data-testid="view-comments"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
      >
        {buttonLabel(count.data?.count ?? 0)}
      </button>
      {open && (
        <CommentsPanel
          workspaceId={workspaceId}
          typeId={typeId}
          instanceId={instanceId}
          canComment={canComment}
        />
      )}
    </>
  );
}

function CommentsPanel({
  workspaceId,
  typeId,
  instanceId,
  canComment,
}: {
  workspaceId: string;
  typeId: string;
  instanceId: string;
  canComment: boolean;
}) {
  const [draft, setDraft] = useState("");
  const queryClient = useQueryClient();
  const thread = useQuery({
    queryKey: ["object-comments", typeId, instanceId],
    queryFn: () => objApi.comments(workspaceId, typeId, instanceId),
  });

  const post = useMutation({
    mutationFn: () =>
      objApi.postComment(workspaceId, typeId, instanceId, draft.trim()),
    onSuccess: async () => {
      setDraft("");
      await queryClient.invalidateQueries({
        queryKey: ["object-comments", typeId, instanceId],
      });
      // The button's label is a second reader of the same fact, so it is
      // refreshed with the thread rather than left to go stale behind an open
      // panel.
      await queryClient.invalidateQueries({
        queryKey: ["object-comment-count", typeId, instanceId],
      });
    },
  });

  const comments = thread.data ?? [];

  return (
    <section className="comments-panel" data-testid="comments-panel">
      {thread.isPending && <p className="state">Loading comments…</p>}
      {thread.isError && (
        // Said rather than drawn as an empty thread: "nobody has commented"
        // and "we could not tell you" are opposite answers, and the second one
        // is the one somebody would act on wrongly.
        <p className="state error" data-testid="comments-error">
          Couldn&apos;t load the comments on this object.
        </p>
      )}
      {thread.data && isEmpty(comments) && (
        <p className="login-note" data-testid="comments-empty">{EMPTY_THREAD}</p>
      )}

      {comments.length > 0 && (
        <ol className="comment-list" data-testid="comment-list">
          {comments.map((comment) => (
            <li key={comment.id} data-testid={`comment-${comment.id}`}>
              <div className="slug">
                <strong>{authorLabel(comment)}</strong>{" "}
                {new Date(comment.created_at).toLocaleString()}
              </div>
              <p className="comment-body">
                {/* **The server's spans, not a second matcher** (§146). A
                    mention highlighted here that the server did not record is
                    a name nobody was told about. */}
                {segments(comment).map((part, i) =>
                  part.kind === "mention" ? (
                    <mark key={i} data-testid="comment-mention">{part.text}</mark>
                  ) : (
                    <span key={i}>{part.text}</span>
                  ),
                )}
              </p>
              {comment.attachments.length > 0 && (
                <ul className="link-list" data-testid="comment-attachments">
                  {comment.attachments.map((file) => (
                    <li key={file.key} className="slug">{file.filename}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}

      {canComment ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            post.mutate();
          }}
        >
          <textarea
            value={draft}
            aria-label="Add a comment"
            data-testid="comment-draft"
            placeholder="Say something — type @ to mention somebody"
            maxLength={10000}
            onChange={(e) => setDraft(e.target.value)}
          />
          {post.isError && (
            <div className="form-error">
              {post.error instanceof ApiError
                ? post.error.message
                : "Couldn't post this comment."}
            </div>
          )}
          <div className="form-actions">
            <button
              type="submit"
              className="btn"
              data-testid="comment-submit"
              disabled={post.isPending || !draft.trim()}
            >
              {post.isPending ? "Posting…" : "Comment"}
            </button>
          </div>
        </form>
      ) : (
        // **Absent with a reason, not silently missing** (§214). Somebody who
        // cannot add to a conversation should know that is why there is no box
        // rather than wonder where it went.
        <p className="login-note" data-testid="comments-read-only">
          You can read this conversation but not add to it.
        </p>
      )}
    </section>
  );
}
