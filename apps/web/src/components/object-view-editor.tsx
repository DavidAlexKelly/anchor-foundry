"use client";

/**
 * Nominating a Workshop module as an object type's view (parity
 * `docs/parity/ontology.md` §4.2; Foundry `object-views` p.2–4).
 *
 * **Two choices, and the second depends on the first.** Which module, and
 * which of *its* variables receives the object. The second list is empty until
 * a module is chosen and says so, because "no single-object variable" is a
 * fact about that module and the fix is in the module, not here.
 *
 * **Only published modules are offered.** An object view is read by whoever
 * can read the object, and an unpublished module is readable only inside its
 * own project - so nominating one would configure a view that renders for its
 * author and fails for everybody else. The server refuses it too; this narrows
 * the list so the refusal is rarely the way somebody finds out.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import { canvas as canvasApi, objects as objApi } from "@/lib/api";
import { variablesOf } from "@/lib/workshop-module";

export function ObjectViewEditor({
  workspaceId,
  typeId,
  typeName,
  onClose,
}: {
  workspaceId: string;
  typeId: string;
  typeName: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [failure, setFailure] = useState<string | null>(null);

  const current = useQuery({
    queryKey: ["object-view", workspaceId, typeId],
    queryFn: () => objApi.getView(workspaceId, typeId),
  });
  const published = useQuery({
    queryKey: ["published-canvas-apps", workspaceId],
    queryFn: () => canvasApi.listPublished(workspaceId),
  });

  const [appId, setAppId] = useState<string>("");
  const [variable, setVariable] = useState<string>("");
  // The saved choice is the starting point, once it has arrived. Held in state
  // rather than derived so an edit is not thrown away by a refetch.
  const chosenApp = appId || current.data?.canvas_app_id || "";
  const chosenVariable = appId ? variable : (variable || current.data?.subject_variable || "");

  // **The chosen module's document only.** Its variables are the second
  // dropdown, and fetching every published module's document to populate a
  // list nobody has opened would cost one request per app in the workspace.
  // Keyed the way the viewer keys it, so opening this dialog and then the view
  // costs one fetch rather than two.
  const document = useQuery({
    queryKey: ["published-canvas-app", chosenApp],
    queryFn: () => canvasApi.getPublished(workspaceId, chosenApp),
    enabled: !!chosenApp,
  });
  const subjects = Object.values(variablesOf(document.data?.definition)).filter(
    (v) => v.kind === "single_object",
  );

  const save = useMutation({
    mutationFn: () =>
      objApi.setView(workspaceId, typeId, {
        canvas_app_id: chosenApp,
        subject_variable: chosenVariable,
      }),
    onSuccess: async () => {
      setFailure(null);
      await queryClient.invalidateQueries({ queryKey: ["object-view", workspaceId, typeId] });
      onClose();
    },
    onError: (e: Error) => setFailure(e.message),
  });

  const clear = useMutation({
    mutationFn: () => objApi.clearView(workspaceId, typeId),
    onSuccess: async () => {
      setFailure(null);
      await queryClient.invalidateQueries({ queryKey: ["object-view", workspaceId, typeId] });
      onClose();
    },
    onError: (e: Error) => setFailure(e.message),
  });

  return (
    <Dialog open title={`Object view · ${typeName}`} onClose={onClose}>
      {failure && <p className="state error" data-testid="object-view-error">{failure}</p>}
      <p className="field-hint">
        A configured view is a published Workshop module standing in for the generated
        one. Readers can always switch back to the standard view.
      </p>

      <Field label="Module">
        <select
          value={chosenApp}
          aria-label="Object view module"
          onChange={(e) => {
            setAppId(e.target.value);
            // The variable belonged to the previous module. Keeping it would
            // send a name the new module has never heard of and get a refusal
            // about a field the person did not touch.
            setVariable("");
          }}
        >
          <option value="">Choose…</option>
          {(published.data ?? []).map((app) => (
            <option key={app.id} value={app.id}>{app.name}</option>
          ))}
        </select>
      </Field>

      <Field label="Receives the object as">
        <select
          value={chosenVariable}
          aria-label="Object view subject variable"
          onChange={(e) => setVariable(e.target.value)}
          disabled={!chosenApp}
        >
          <option value="">Choose…</option>
          {subjects.map((v) => (
            <option key={v.id} value={v.id}>{v.label || v.id}</option>
          ))}
        </select>
      </Field>
      {chosenApp && document.data && subjects.length === 0 && (
        <p className="field-hint" data-testid="no-subject-variable">
          This module has no single-object variable, so there is nowhere for the object to
          arrive. Add one in the module&apos;s Variables panel.
        </p>
      )}

      <div className="row-actions" style={{ marginTop: 16 }}>
        <button
          className="btn"
          disabled={!chosenApp || !chosenVariable || save.isPending}
          onClick={() => save.mutate()}
        >
          Save
        </button>
        {current.data && (
          <button
            className="btn quiet"
            disabled={clear.isPending}
            onClick={() => clear.mutate()}
          >
            Use the standard view
          </button>
        )}
      </div>
    </Dialog>
  );
}
