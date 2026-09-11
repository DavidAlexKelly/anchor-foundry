"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { actions as actionApi, ApiError, objects as objApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { LinkExplorerDialog, type LinkStop } from "@/components/instance-links";
import { PropertyInput, PropertyValue } from "@/components/property-value";
import { conditionalStyle } from "@/lib/conditional-format";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import { UndoToast } from "@/components/undo-toast";
import { ActionMetricsSection } from "@/components/action-metrics-panel";
import { UsagePanel } from "@/components/usage-panel";
import type {
  ActionExecuteResult,
  ActionType,
  ObjectInstance,
  PropertyDataType,
} from "@/lib/types";

const PAGE_SIZE = 50;

function EditInstanceDialog({
  workspaceId,
  projectId,
  instance,
  actionTypes,
  propertyTypes,
  onClose,
  onApplied,
}: {
  workspaceId: string;
  projectId: string;
  instance: ObjectInstance;
  actionTypes: ActionType[];
  propertyTypes: Record<string, PropertyDataType>;
  onClose: () => void;
  /** What was applied, for p.154's success message. The dialog is gone by the
   * time it is drawn, so the action's name travels with the result — there is
   * nothing left to look it up on. */
  onApplied: (
    result: ActionExecuteResult, actionTypeId: string, actionName: string,
  ) => void;
}) {
  const [actionTypeId, setActionTypeId] = useState(actionTypes[0]?.id ?? "");
  const activeAction = actionTypes.find((a) => a.id === actionTypeId) ?? actionTypes[0];
  // Values keep their real types now (roadmap Objects item 4): the API's
  // check is strict, so sending "7" for an integer property is refused.
  const [values, setValues] = useState<Record<string, unknown>>(
    Object.fromEntries(
      (activeAction?.editable_properties ?? []).map((p) => [p, instance.properties[p] ?? null]),
    ),
  );
  const queryClient = useQueryClient();

  const execute = useMutation({
    mutationFn: () => actionApi.execute(workspaceId, projectId, activeAction!.id, instance.id, values),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["object-instances"] });
      // **p.154's Undo lives outside this dialog**, because the dialog is
      // about to close and the success message is the thing that carries it.
      // Handed up rather than drawn here: the page owns the toast, so it
      // survives the form that produced it.
      onApplied(result, activeAction!.id, activeAction!.display_name);
      onClose();
    },
  });

  function selectAction(id: string) {
    setActionTypeId(id);
    const next = actionTypes.find((a) => a.id === id);
    setValues(
      Object.fromEntries(
        (next?.editable_properties ?? []).map((p) => [p, instance.properties[p] ?? null]),
      ),
    );
  }

  return (
    <Dialog open title={`Edit ${instance.primary_key}`} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); execute.mutate(); }}>
        {actionTypes.length > 1 && (
          <Field label="Action">
            <select value={actionTypeId} onChange={(e) => selectAction(e.target.value)}>
              {actionTypes.map((a) => (
                <option key={a.id} value={a.id}>{a.display_name}</option>
              ))}
            </select>
          </Field>
        )}
        {(activeAction?.editable_properties ?? []).map((p) => (
          <Field key={p} label={p} hint={propertyTypes[p]}>
            <PropertyInput
              workspaceId={workspaceId}
              dataType={propertyTypes[p]}
              value={values[p]}
              onChange={(next) => setValues({ ...values, [p]: next })}
              label={p}
            />
          </Field>
        ))}
        {execute.isError && (
          <div className="form-error">
            {execute.error instanceof ApiError ? execute.error.message : "Couldn't save this change."}
          </div>
        )}
        {execute.data && !execute.data.ok && (
          <div className="form-error">{execute.data.error}</div>
        )}
        <div className="form-actions">
          <button type="button" className="btn quiet" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn" disabled={execute.isPending || !activeAction}>
            {execute.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export default function ObjectInstancesPage() {
  const params = useParams<{ workspace: string; project: string; typeId: string }>();
  const { workspace } = useWorkspaceBySlug(params.workspace);
  const { project } = useProjectBySlug(workspace?.id, params.project);
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<ObjectInstance | null>(null);
  const [exploring, setExploring] = useState<LinkStop | null>(null);
  // The last application, for p.154's success message. **One at a time**: a
  // stack of toasts would be a stack of undos, and p.156's rule that only the
  // most recent edit to an object can be undone would make all but the top one
  // a button that refuses.
  const [applied, setApplied] = useState<{
    result: ActionExecuteResult;
    actionTypeId: string;
    actionName: string;
  } | null>(null);
  const queryClient = useQueryClient();

  const type = useQuery({
    queryKey: ["object-type", params.typeId],
    queryFn: () => objApi.getType(workspace!.id, params.typeId),
    enabled: !!workspace,
  });
  const instances = useQuery({
    queryKey: ["object-instances", params.typeId, page],
    // **Named as the Ontology Manager, so this read is not counted** (§320;
    // `ontology-manager` p.32: "any object type or link type usage happening
    // in Ontology Manager is not included"). This page and the Object Explorer
    // list a type's objects through the same route, so the label is the only
    // thing that tells them apart — and somebody deciding whether to rename a
    // property must not become the type's most active user for having looked.
    queryFn: () => objApi.listInstances(
      workspace!.id, params.typeId, PAGE_SIZE, page * PAGE_SIZE, "ontology_manager",
    ),
    enabled: !!workspace,
  });
  const actionTypes = useQuery({
    queryKey: ["action-types", workspace?.id, params.typeId],
    queryFn: () => actionApi.listTypes(workspace!.id, params.typeId),
    enabled: !!workspace,
  });

  const properties = type.data?.properties ?? [];
  const rows = instances.data?.items ?? [];
  const total = instances.data?.total ?? 0;
  const hasNext = (page + 1) * PAGE_SIZE < total;
  const canEdit = (project ? project.effective_role !== "viewer" : false) && (actionTypes.data?.length ?? 0) > 0;

  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · objects</p>
          <h1>{type.data?.display_name ?? "Instances"}</h1>
        </div>
        <Link href={`/${params.workspace}/${params.project}/objects`} className="btn quiet">
          Back to Objects
        </Link>
      </div>

      {(type.isPending || instances.isPending) && <div className="state">Loading instances…</div>}
      {(type.isError || instances.isError) && (
        <div className="state error">Couldn&apos;t load instances. Refresh to try again.</div>
      )}

      {type.data && instances.data && total === 0 && (
        <div className="empty">
          <h2>No instances yet</h2>
          <p>
            This object type has no materialised instances. Map a dataset to it and sync from
            the Objects page to populate this view.
          </p>
        </div>
      )}

      {type.data && rows.length > 0 && (
        <>
          <p className="sub" style={{ marginBottom: 12 }}>
            {total.toLocaleString()} instance{total === 1 ? "" : "s"}
          </p>
          <div style={{ overflowX: "auto" }}>
            {/* **Named, because this page has two tables now** (§321). §320's
                usage panel added a second, and `get_by_role("table")` in a
                sibling suite went from unambiguous to a strict-mode violation
                — four tests, red in CI, for a change that touched none of
                them. A role is a claim about what an element *is*; a test id
                is a claim about *which one*, and a page that grows a second of
                anything needs the second kind. */}
            <table className="table" data-testid="instances-table">
              <thead>
                <tr>
                  <th>Primary key</th>
                  {properties.map((p) => (
                    <th key={p.api_name}>{p.display_name || p.api_name}</th>
                  ))}
                  <th>Updated</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {rows.map((instance) => (
                  <tr key={instance.id}>
                    <td className="slug">{instance.primary_key}</td>
                    {properties.map((p) => (
                      <td key={p.api_name}>
                        <PropertyValue
                          workspaceId={workspace!.id}
                          dataType={p.data_type}
                          valueFormat={p.value_format}
                          structFields={p.struct_fields}
                          style={conditionalStyle(p.conditional_format, instance.properties)}
                          value={instance.properties[p.api_name]}
                        />
                      </td>
                    ))}
                    <td className="count">{new Date(instance.updated_at).toLocaleString()}</td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="btn quiet"
                          style={{ padding: "3px 9px", fontSize: 12 }}
                          onClick={() =>
                            setExploring({
                              typeId: params.typeId,
                              typeName: type.data?.display_name ?? "Object",
                              instance,
                            })
                          }
                        >
                          Explore
                        </button>
                        {canEdit && (
                          <button
                            className="btn quiet"
                            style={{ padding: "3px 9px", fontSize: 12 }}
                            onClick={() => setEditing(instance)}
                          >
                            Edit
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row-actions" style={{ marginTop: 14, justifyContent: "flex-end" }}>
            <button
              className="btn quiet"
              style={{ padding: "4px 12px", fontSize: 12.5 }}
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              Previous
            </button>
            <span className="count">
              {page * PAGE_SIZE + 1}–{Math.min(total, (page + 1) * PAGE_SIZE)} of {total}
            </span>
            <button
              className="btn quiet"
              style={{ padding: "4px 12px", fontSize: 12.5 }}
              disabled={!hasNext}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}

      {exploring && workspace && (
        <LinkExplorerDialog
          workspaceSlug={params.workspace}
          workspaceId={workspace.id}
          browseHref={(typeId) => `/${params.workspace}/${params.project}/objects/${typeId}`}
          start={exploring}
          onClose={() => setExploring(null)}
        />
      )}

      {editing && workspace && project && actionTypes.data && (
        <EditInstanceDialog
          workspaceId={workspace.id}
          projectId={project.id}
          instance={editing}
          actionTypes={actionTypes.data}
          propertyTypes={Object.fromEntries(
            properties.map((p) => [p.api_name, p.data_type]),
          )}
          onClose={() => setEditing(null)}
          onApplied={(result, id, name) =>
            setApplied({ result, actionTypeId: id, actionName: name })
          }
        />
      )}

      {/* **p.154's success message, and the only place the Undo can live.**
          The dialog above closes on success — the edit is made — so a button
          inside it would go with it. p.155 calls this toast "your only
          opportunity to revert the action". */}
      {applied && workspace && project && (
        <UndoToast
          workspaceId={workspace.id}
          projectId={project.id}
          actionTypeId={applied.actionTypeId}
          actionName={applied.actionName}
          result={applied.result}
          onUndone={() =>
            queryClient.invalidateQueries({ queryKey: ["object-instances"] })
          }
          onDismiss={() => setApplied(null)}
        />
      )}
      {/* p.33's usage summary, on the page about the type it is about. Last,
          because it is what somebody consults *before* changing something
          above it rather than something they came here to do. */}
      {workspace && <UsagePanel workspaceId={workspace.id} typeId={params.typeId} />}
      {/* p.164's action metrics, below the usage they belong beside: the usage
          panel says who relies on this type, and this says whether the thing
          they do to it is working. Both are consulted before changing
          something above them rather than being why somebody came here. */}
      {workspace && actionTypes.data && (
        <ActionMetricsSection
          workspaceId={workspace.id}
          actionTypes={actionTypes.data}
        />
      )}
    </main>
  );
}
