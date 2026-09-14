"use client";

/**
 * p.7's Overview tab: what an action is called (§345; `action-types` p.7).
 *
 * > "Enter a Display name for your action type." (p.7)
 *
 * > "You can now see the full detailed view of your action type. You can make
 * > additional adjustments, like adding a Description in the Overview tab."
 * > (p.7)
 *
 * **A dialog rather than fields in the listing**, like every other edit on this
 * screen: the row is a summary of several actions and a text input in it turns
 * a listing into a form nobody asked to open.
 *
 * The decisions are in `lib/action-overview.ts`; this only draws them.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { actions as actionApi, ApiError } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { overviewEdit, overviewRefusal } from "@/lib/action-overview";
import type { ActionType } from "@/lib/types";

export function ActionOverviewDialog({
  workspaceId,
  action,
  onClose,
}: {
  workspaceId: string;
  action: ActionType;
  onClose: () => void;
}) {
  const saved = {
    display_name: action.display_name,
    description: action.description ?? "",
  };
  const [draft, setDraft] = useState(saved);
  const queryClient = useQueryClient();

  const saving = useMutation({
    mutationFn: (edit: { display_name?: string; description?: string }) =>
      actionApi.rename(workspaceId, action.id, edit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["action-types"] });
      onClose();
    },
  });

  const refusal = overviewRefusal(draft);
  const edit = overviewEdit(saved, draft);

  return (
    <Dialog open title={`Overview · ${action.api_name}`} onClose={onClose}>
      <Field
        label="Display name"
        hint="What people see on the button and in every listing."
      >
        <input
          data-testid="action-overview-name"
          value={draft.display_name}
          onChange={(e) => setDraft({ ...draft, display_name: e.target.value })}
        />
      </Field>
      <Field label="Description" hint="Optional. What the action is for.">
        <textarea
          data-testid="action-overview-description"
          rows={3}
          value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
        />
      </Field>
      {/* The api_name is shown and not editable: it is what every saved
          Workshop module and every ontology file names this action by
          (decision 0007), so changing it is a different operation from
          renaming and this screen is not it. */}
      <p className="field-hint" data-testid="action-overview-api-name">
        API name: {action.api_name} — not editable; it is how saved modules and
        ontology files name this action.
      </p>

      {refusal && (
        <p className="form-error" data-testid="action-overview-refusal">
          {refusal}
        </p>
      )}
      {saving.isError && (
        <p className="form-error" data-testid="action-overview-error">
          {saving.error instanceof ApiError
            ? saving.error.message
            : "Couldn't save this."}
        </p>
      )}
      <div className="form-actions">
        <button className="btn quiet" onClick={onClose}>Cancel</button>
        <button
          className="btn"
          data-testid="action-overview-save"
          // Disabled when nothing changed as well as when the draft is
          // refused: a Save that would send an empty body is a button that
          // does nothing, and one that writes back an untouched name would
          // put a rename in the audit log that never happened.
          disabled={!!refusal || edit === null || saving.isPending}
          onClick={() => edit && saving.mutate(edit)}
        >
          {saving.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </Dialog>
  );
}
