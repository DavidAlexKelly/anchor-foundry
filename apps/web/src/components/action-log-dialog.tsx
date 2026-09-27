"use client";

/**
 * Turning on an action log, or changing its summary (§586; `action-types`
 * p.167-168).
 *
 * > "[Optional] Summary: A customizable string to describe the action
 * > [Optional] Property values of object reference parameters" (p.168)
 *
 * Both are optional, so "Turn on" with nothing filled in is §554's log. The
 * properties are columns, so they are chosen once, here; the summary is a
 * template every log has a column for, so it can be changed afterwards.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import { ApiError, actions as actionApi, objects as objApi } from "@/lib/api";
import { referenceChoices, referencesSummary, withReference } from "@/lib/action-log";
import type { ActionType } from "@/lib/types";

function PropertyChecks({
  workspaceId, parameter, typeId, chosen, onChange,
}: {
  workspaceId: string;
  parameter: string;
  typeId: string;
  chosen: Record<string, string[]>;
  onChange: (next: Record<string, string[]>) => void;
}) {
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId),
  });
  return (
    <div className="row-actions" data-log-reference={parameter}>
      {(type.data?.properties ?? []).map((p) => (
        <label key={p.api_name} style={{ fontSize: 12.5 }}>
          <input
            type="checkbox"
            aria-label={`Keep ${parameter} ${p.api_name}`}
            checked={(chosen[parameter] ?? []).includes(p.api_name)}
            onChange={(e) => onChange(withReference(chosen, parameter, p.api_name, e.target.checked))}
          />
          {" "}{p.display_name || p.api_name}
        </label>
      ))}
    </div>
  );
}

export function ActionLogDialog({
  workspaceId, projectId, action, onClose,
}: {
  workspaceId: string;
  projectId: string;
  action: ActionType;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const on = !!action.log_object_type_id;
  const [summary, setSummary] = useState(action.log_summary ?? "");
  const [chosen, setChosen] = useState<Record<string, string[]>>({});
  const choices = referenceChoices(action);

  const save = useMutation({
    mutationFn: async () => {
      if (on) {
        await actionApi.setLogSummary(workspaceId, action.id, summary.trim() ? summary : null);
      } else {
        await actionApi.enableLog(workspaceId, projectId, action.id, {
          summary: summary.trim() ? summary : null,
          reference_properties: chosen,
        });
      }
    },
    onSuccess: async () => {
      for (const key of ["action-types", "object-types", "link-types"]) {
        await queryClient.invalidateQueries({ queryKey: [key, workspaceId] });
      }
      await queryClient.invalidateQueries({ queryKey: ["object-sources", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
      onClose();
    },
  });

  return (
    <Dialog open title={on ? "Action log summary" : "Turn on the action log"} onClose={onClose}>
      <p className="field-hint">
        p.167: every submission becomes an object of a [LOG] type, linked to
        what it edited. p.168&rsquo;s two optional fields are below; both are
        read from the objects as they were when the action was submitted.
      </p>
      <Field
        label="Summary"
        hint={"Optional. Write {{{parameter}}}, {{{parameter.property}}} for an object "
          + "parameter, or {{{current_user}}}."}
      >
        <textarea
          data-testid="log-summary"
          rows={2}
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
        />
      </Field>
      {on ? (
        <p className="field-hint" data-testid="log-references">
          {referencesSummary(action.log_reference_properties)} Properties are
          chosen when the log is turned on, since each is a column.
        </p>
      ) : (
        <Field label="Object properties to keep"
               hint="Optional. p.168: for single object reference parameters.">
          {choices.length === 0 ? (
            <p className="field-hint" data-testid="log-no-references">
              This action has no single object reference parameter.
            </p>
          ) : choices.map((choice) => (
            <div key={choice.parameter}>
              <span className="field-label">{choice.label}</span>
              {choice.typeId ? (
                <PropertyChecks
                  workspaceId={workspaceId}
                  parameter={choice.parameter}
                  typeId={choice.typeId}
                  chosen={chosen}
                  onChange={setChosen}
                />
              ) : (
                <p className="field-hint">
                  Nothing says which object type it holds, so there is nothing to keep.
                </p>
              )}
            </div>
          ))}
        </Field>
      )}
      {save.isError && (
        <div className="form-error" data-testid="log-error">
          {save.error instanceof ApiError ? save.error.message : "Couldn't save the action log."}
        </div>
      )}
      <div className="form-actions">
        <button className="btn quiet" onClick={onClose}>Cancel</button>
        <button className="btn" disabled={save.isPending} onClick={() => save.mutate()}>
          {on ? "Save" : "Turn on"}
        </button>
      </div>
    </Dialog>
  );
}
