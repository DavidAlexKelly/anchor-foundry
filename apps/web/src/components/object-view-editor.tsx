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
 *
 * **A full view is a list of tabs (§695)**, `object-views` p.35's gear dialog:
 * "add, reorder, rename, and delete Object View tabs", each tab a module and
 * the variable that receives the object. The list is saved whole. The first
 * tab is the view's own module, and its title may be left blank to follow the
 * module's name. **Divergence**: p.35's "Deleting a tab also deletes the
 * Workshop module that the tab contains" - a tab here points at a published
 * module that is an app in its own right, which deleting a tab leaves alone,
 * as clearing the view always has.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog, Field } from "@/components/dialog";
import { canvas as canvasApi, objects as objApi } from "@/lib/api";
import { variablesOf } from "@/lib/workshop-module";
import { MAX_TABS, draftsOf, moveTab, tabsProblem, type TabDraft } from "@/lib/object-view-tabs";

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

  // The saved tabs are the starting point, once they have arrived. Held in
  // state from the first edit on, so an edit is not thrown away by a refetch.
  const [edited, setEdited] = useState<TabDraft[] | null>(null);
  const tabs = edited ?? (current.isPending ? [] : draftsOf(current.data ?? null));
  const problem = tabsProblem(tabs);
  const change = (next: TabDraft[]) => setEdited(next);
  const update = (n: number, patch: Partial<TabDraft>) =>
    change(tabs.map((tab, i) => (i === n ? { ...tab, ...patch } : tab)));

  const done = async () => {
    setFailure(null);
    await queryClient.invalidateQueries({ queryKey: ["object-view", workspaceId, typeId] });
    onClose();
  };
  const save = useMutation({
    mutationFn: () => objApi.setViewTabs(workspaceId, typeId, tabs),
    onSuccess: done,
    onError: (e: Error) => setFailure(e.message),
  });
  const clear = useMutation({
    mutationFn: () => objApi.clearView(workspaceId, typeId),
    onSuccess: done,
    onError: (e: Error) => setFailure(e.message),
  });

  return (
    <Dialog open title={`Object view · ${typeName}`} onClose={onClose}>
      {failure && <p className="state error" data-testid="object-view-error">{failure}</p>}
      <p className="field-hint">
        A configured view is a published Workshop module standing in for the generated
        one. Readers can always switch back to the standard view. Each tab is a module;
        with one tab, its title is not shown.
      </p>

      {tabs.map((tab, n) => (
        <TabFields
          key={n}
          workspaceId={workspaceId}
          n={n}
          count={tabs.length}
          tab={tab}
          modules={published.data ?? []}
          onChange={(patch) => update(n, patch)}
          onMove={(by) => change(moveTab(tabs, n, by))}
          onDelete={() => change(tabs.filter((_, i) => i !== n))}
        />
      ))}
      <button
        type="button"
        className="btn quiet"
        disabled={tabs.length >= MAX_TABS || current.isPending}
        onClick={() => change([...tabs, { title: "", canvas_app_id: "", subject_variable: "" }])}
      >
        Add tab
      </button>

      <div className="row-actions" style={{ marginTop: 16 }}>
        <button
          className="btn"
          disabled={!!problem || save.isPending}
          title={problem ?? undefined}
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
      {problem && edited && <p className="field-hint" data-testid="object-view-tabs-problem">{problem}</p>}
    </Dialog>
  );
}

/** One tab: its title, its module, and which of *that* module's variables
 * receives the object. */
function TabFields({ workspaceId, n, count, tab, modules, onChange, onMove, onDelete }: {
  workspaceId: string;
  n: number;
  count: number;
  tab: TabDraft;
  modules: { id: string; name: string }[];
  onChange: (patch: Partial<TabDraft>) => void;
  onMove: (by: -1 | 1) => void;
  onDelete: () => void;
}) {
  // **The chosen module's document only.** Its variables are the second
  // dropdown, and fetching every published module's document to populate a
  // list nobody has opened would cost one request per app in the workspace.
  // Keyed the way the viewer keys it, so opening this dialog and then the view
  // costs one fetch rather than two.
  const document = useQuery({
    queryKey: ["published-canvas-app", tab.canvas_app_id],
    queryFn: () => canvasApi.getPublished(workspaceId, tab.canvas_app_id),
    enabled: !!tab.canvas_app_id,
  });
  const subjects = Object.values(variablesOf(document.data?.definition)).filter(
    (v) => v.kind === "single_object",
  );
  const label = `Tab ${n + 1}`;
  return (
    <fieldset className="object-view-tab" data-testid="object-view-tab">
      <legend>{label}</legend>
      <Field label="Title">
        <input
          type="text"
          value={tab.title}
          aria-label={`${label} title`}
          maxLength={100}
          placeholder={n === 0 ? "The module's name" : "Required"}
          onChange={(e) => onChange({ title: e.target.value })}
        />
      </Field>
      <Field label="Module">
        <select
          value={tab.canvas_app_id}
          aria-label={`${label} module`}
          onChange={(e) =>
            // The variable belonged to the previous module. Keeping it would
            // send a name the new module has never heard of and get a refusal
            // about a field the person did not touch.
            onChange({ canvas_app_id: e.target.value, subject_variable: "" })}
        >
          <option value="">Choose…</option>
          {modules.map((app) => (
            <option key={app.id} value={app.id}>{app.name}</option>
          ))}
        </select>
      </Field>
      <Field label="Receives the object as">
        <select
          value={tab.subject_variable}
          aria-label={`${label} subject variable`}
          onChange={(e) => onChange({ subject_variable: e.target.value })}
          disabled={!tab.canvas_app_id}
        >
          <option value="">Choose…</option>
          {subjects.map((v) => (
            <option key={v.id} value={v.id}>{v.label || v.id}</option>
          ))}
        </select>
      </Field>
      {tab.canvas_app_id && document.data && subjects.length === 0 && (
        <p className="field-hint" data-testid="no-subject-variable">
          This module has no single-object variable, so there is nowhere for the object to
          arrive. Add one in the module&apos;s Variables panel.
        </p>
      )}
      {count > 1 && (
        <div className="row-actions">
          <button type="button" className="btn quiet" aria-label={`Move ${label} up`}
            disabled={n === 0} onClick={() => onMove(-1)}>↑</button>
          <button type="button" className="btn quiet" aria-label={`Move ${label} down`}
            disabled={n === count - 1} onClick={() => onMove(1)}>↓</button>
          <button type="button" className="btn quiet" aria-label={`Delete ${label}`}
            onClick={onDelete}>Delete</button>
        </div>
      )}
    </fieldset>
  );
}
