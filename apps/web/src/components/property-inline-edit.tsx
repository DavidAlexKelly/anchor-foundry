"use client";

/** p.266's edit in place, for one property (§594, §595; `workshop` p.266,
 * `object-views` p.67, `action-types` p.135).
 *
 *     "Inline edits allow users to quickly edit values of an object in the
 *      Object Explorer results view or native Object View widgets." (p.135)
 *
 * One component for every surface that shows a property with an inline
 * action - the Property List (§594) and the standard Object View (§595) - so
 * what an edit in place is cannot differ between them. It submits the
 * property's inline action for this one object through the batch route, the
 * action's other parameters keeping the object's values (p.135).
 *
 * **Draws nothing unless the action still backs the property**
 * (`liveInlineParameter`): it is re-read here, because it can change after
 * the Ontology Manager chose it. And nothing without a project to write in,
 * which a caller that cannot name exactly one passes as null.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PropertyInput } from "@/components/property-value";
import { actions as actionApi } from "@/lib/api";
import { multipleChoice } from "@/lib/parameter-constraint";
import { liveInlineParameter } from "@/lib/property-inline-action";
import type { ObjectTypeProperty } from "@/lib/types";

export function PropertyInlineEdit({
  workspaceId, projectId, property, instanceId, value, refreshKeys, application,
}: {
  workspaceId: string;
  /** Where the write lands. Null draws no editor. */
  projectId: string | null | undefined;
  property: ObjectTypeProperty;
  instanceId: string;
  value: unknown;
  /** The queries showing this object, refreshed after a save. */
  refreshKeys: readonly (readonly unknown[])[];
  /** p.32's write source (§320), for the usage breakdown. */
  application?: string;
}) {
  const actionId = property.inline_action_type_id ?? null;
  const action = useQuery({
    queryKey: ["action-type", workspaceId, actionId],
    queryFn: () => actionApi.getType(workspaceId, actionId!),
    enabled: !!actionId,
  });
  const parameter = liveInlineParameter(action.data, property.api_name);
  const [draft, setDraft] = useState<{ value: unknown } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: () => actionApi.executeBatch(workspaceId, projectId!, actionId!, [
      { instance_id: instanceId, values: { [parameter!]: draft!.value } },
    ], application),
    onSuccess: async (result) => {
      if (!result.ok) {
        setError(result.error ?? "The edit was not saved.");
        return;
      }
      setDraft(null);
      setError(null);
      for (const queryKey of refreshKeys) {
        await queryClient.invalidateQueries({ queryKey: [...queryKey] });
      }
    },
    onError: (err: unknown) =>
      setError(err instanceof Error ? err.message : "The edit was not saved."),
  });
  if (!parameter || !projectId) return null;
  const name = property.display_name || property.api_name;
  if (!draft) {
    return (
      <button
        type="button"
        className="btn quiet canvas-property-edit"
        aria-label={`Edit ${name}`}
        onClick={() => setDraft({ value })}
      >
        Edit
      </button>
    );
  }
  return (
    <form
      className="canvas-property-editing"
      data-testid="property-inline-edit"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <PropertyInput
        workspaceId={workspaceId}
        dataType={property.data_type as never}
        structFields={property.struct_fields}
        arrayOf={property.array_of}
        // The parameter's multiple choice, as p.241 draws it in a cell (§597).
        choices={multipleChoice(
          action.data?.parameters?.find((a) => a.api_name === parameter) ?? { data_type: "" },
        )}
        label={name}
        value={draft.value as never}
        onChange={(next) => setDraft({ value: next })}
      />
      <button type="submit" className="btn" disabled={save.isPending}>Save</button>
      <button
        type="button"
        className="btn quiet"
        onClick={() => {
          setDraft(null);
          setError(null);
        }}
      >
        Cancel
      </button>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  );
}
