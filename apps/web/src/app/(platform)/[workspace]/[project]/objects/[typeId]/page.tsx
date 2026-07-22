"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { actions as actionApi, ApiError, objects as objApi } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import { useProjectBySlug, useWorkspaceBySlug } from "@/components/use-workspace";
import type { ActionType, ObjectInstance } from "@/lib/types";

const PAGE_SIZE = 50;

function EditInstanceDialog({
  workspaceId,
  projectId,
  instance,
  actionTypes,
  onClose,
}: {
  workspaceId: string;
  projectId: string;
  instance: ObjectInstance;
  actionTypes: ActionType[];
  onClose: () => void;
}) {
  const [actionTypeId, setActionTypeId] = useState(actionTypes[0]?.id ?? "");
  const activeAction = actionTypes.find((a) => a.id === actionTypeId) ?? actionTypes[0];
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(
      (activeAction?.editable_properties ?? []).map((p) => [
        p, instance.properties[p] == null ? "" : String(instance.properties[p]),
      ]),
    ),
  );
  const queryClient = useQueryClient();

  const execute = useMutation({
    mutationFn: () => actionApi.execute(workspaceId, projectId, activeAction!.id, instance.id, values),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["object-instances"] });
      onClose();
    },
  });

  function selectAction(id: string) {
    setActionTypeId(id);
    const next = actionTypes.find((a) => a.id === id);
    setValues(
      Object.fromEntries(
        (next?.editable_properties ?? []).map((p) => [
          p, instance.properties[p] == null ? "" : String(instance.properties[p]),
        ]),
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
          <Field key={p} label={p}>
            <input
              type="text"
              value={values[p] ?? ""}
              onChange={(e) => setValues({ ...values, [p]: e.target.value })}
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

  const type = useQuery({
    queryKey: ["object-type", params.typeId],
    queryFn: () => objApi.getType(workspace!.id, params.typeId),
    enabled: !!workspace,
  });
  const instances = useQuery({
    queryKey: ["object-instances", params.typeId, page],
    queryFn: () => objApi.listInstances(workspace!.id, params.typeId, PAGE_SIZE, page * PAGE_SIZE),
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
            <table className="table">
              <thead>
                <tr>
                  <th>Primary key</th>
                  {properties.map((p) => (
                    <th key={p.api_name}>{p.display_name || p.api_name}</th>
                  ))}
                  <th>Updated</th>
                  {canEdit && <th aria-label="Actions" />}
                </tr>
              </thead>
              <tbody>
                {rows.map((instance) => (
                  <tr key={instance.id}>
                    <td className="slug">{instance.primary_key}</td>
                    {properties.map((p) => (
                      <td key={p.api_name}>
                        {instance.properties[p.api_name] === null ||
                        instance.properties[p.api_name] === undefined
                          ? <span style={{ color: "var(--ink-soft)" }}>—</span>
                          : String(instance.properties[p.api_name])}
                      </td>
                    ))}
                    <td className="count">{new Date(instance.updated_at).toLocaleString()}</td>
                    {canEdit && (
                      <td>
                        <button
                          className="btn quiet"
                          style={{ padding: "3px 9px", fontSize: 12 }}
                          onClick={() => setEditing(instance)}
                        >
                          Edit
                        </button>
                      </td>
                    )}
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

      {editing && workspace && project && actionTypes.data && (
        <EditInstanceDialog
          workspaceId={workspace.id}
          projectId={project.id}
          instance={editing}
          actionTypes={actionTypes.data}
          onClose={() => setEditing(null)}
        />
      )}
    </main>
  );
}
