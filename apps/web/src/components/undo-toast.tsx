"use client";

/**
 * p.154's success message, with the Undo in it (§319; `action-types` p.154-156).
 *
 * > "You can revert an action by selecting Undo in the success message after
 * > any successful action application." (p.154)
 *
 * > "The toast below is your only opportunity to revert the action." (p.155)
 *
 * **It outlives the form.** The dialog closes on success, which is right — the
 * edit is made and the object behind it has changed — so the one place the
 * Undo can live is a message the page owns. That is also why this takes an
 * action *name* and a run rather than the form's state: by the time it is
 * drawn, the form is gone.
 *
 * The wording and the decision of what to offer are in `lib/undo-toast.ts`;
 * this draws them and presses the button.
 */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { actions as actionApi, ApiError } from "@/lib/api";
import {
  appliedMessage,
  undoOffer,
  undoneMessage,
} from "@/lib/undo-toast";
import type { ActionExecuteResult } from "@/lib/types";

export function UndoToast({
  workspaceId,
  projectId,
  actionTypeId,
  actionName,
  result,
  onUndone,
  onDismiss,
}: {
  workspaceId: string;
  projectId: string;
  actionTypeId: string;
  actionName: string;
  result: ActionExecuteResult;
  /** So the page can refresh what it is showing — the object behind the toast
   * has just changed back. */
  onUndone: () => void;
  onDismiss: () => void;
}) {
  const [undone, setUndone] = useState(false);
  const offer = undoOffer(result);

  const undo = useMutation({
    mutationFn: () =>
      actionApi.undo(
        workspaceId,
        projectId,
        actionTypeId,
        offer.kind === "offer" ? offer.runId : "",
      ),
    onSuccess: () => {
      setUndone(true);
      onUndone();
    },
  });

  if (offer.kind === "none") return null;

  return (
    <div className="toast" data-testid="undo-toast" role="status">
      <span data-testid="undo-toast-message">
        {undone ? undoneMessage(actionName) : appliedMessage(actionName)}
      </span>
      {/* **The refusal is drawn, not implied by an absent button** — p.155's
          "only opportunity" is the reason. Two of the six reasons are things
          somebody can act on, and they are indistinguishable from the other
          four unless the sentence is on screen. */}
      {!undone && offer.kind === "refused" && (
        <span className="slug" data-testid="undo-refusal">{offer.why}</span>
      )}
      {!undone && offer.kind === "offer" && (
        <button
          type="button"
          className="btn quiet"
          data-testid="undo-action"
          disabled={undo.isPending}
          onClick={() => undo.mutate()}
        >
          {undo.isPending ? "Undoing…" : "Undo"}
        </button>
      )}
      {/* A failed undo says so **in place of the button**, because the run may
          now be in a state where pressing again cannot work — somebody else's
          edit landed in between, which is the one refusal that can become true
          while the toast is open. */}
      {undo.isError && (
        <span className="slug" data-testid="undo-failed">
          {undo.error instanceof ApiError
            ? undo.error.message
            : "Couldn't undo this."}
        </span>
      )}
      <button
        type="button"
        className="btn quiet"
        data-testid="undo-toast-dismiss"
        aria-label="Dismiss"
        onClick={onDismiss}
      >
        ×
      </button>
    </div>
  );
}
