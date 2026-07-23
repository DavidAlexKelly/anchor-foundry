"use client";

/** Canvas widgets — the components a saved app's Craft.js definition is
 * built from. Each reads workspace/project id + edit-vs-run mode from
 * CanvasEnvProvider (never from its own serialised props — the same app
 * renders from more than one route), and reuses the datasets/objects/
 * actions endpoints already built elsewhere; a widget only remembers which
 * dataset/action it's bound to, never a copy of the data itself. */

import { useEditor, useNode } from "@craftjs/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useState } from "react";
import { actions as actionApi, datasets as dsApi, objects as objApi } from "@/lib/api";
import { useCanvasEnv } from "./context";

function connectDragDrop(node: HTMLElement | null, connect: (el: HTMLElement) => HTMLElement, drag: (el: HTMLElement) => HTMLElement) {
  if (node) connect(drag(node));
}

// ---- Container (layout) ------------------------------------------------------
export function CanvasContainer({
  children,
  background,
  padding,
}: {
  children?: React.ReactNode;
  background?: string;
  padding?: number;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  return (
    <div
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className="canvas-block"
      style={{ background: background || "transparent", padding: padding ?? 12 }}
    >
      {children}
    </div>
  );
}

function ContainerSettings() {
  const {
    background,
    padding,
    actions: { setProp },
  } = useNode((node) => ({ background: node.data.props.background, padding: node.data.props.padding }));
  return (
    <>
      <label className="field">
        <span className="field-label">Background</span>
        <input
          type="text"
          value={background || ""}
          placeholder="transparent"
          onChange={(e) => setProp((p: { background: string }) => (p.background = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Padding (px)</span>
        <input
          type="text"
          value={padding ?? 12}
          onChange={(e) => setProp((p: { padding: number }) => (p.padding = Number(e.target.value) || 0))}
        />
      </label>
    </>
  );
}

CanvasContainer.craft = {
  displayName: "Container",
  props: { background: "", padding: 12 },
  related: { settings: ContainerSettings },
};

// ---- Text ---------------------------------------------------------------------
export function CanvasText({ text = "Text", tag = "p" }: { text?: string; tag?: "h1" | "h2" | "p" }) {
  const {
    connectors: { connect, drag },
  } = useNode();
  return React.createElement(
    tag,
    { ref: (ref: HTMLElement | null) => connectDragDrop(ref, connect, drag), style: { margin: 0 } },
    text,
  );
}

function TextSettings() {
  const {
    text,
    tag,
    actions: { setProp },
  } = useNode((node) => ({ text: node.data.props.text, tag: node.data.props.tag }));
  return (
    <>
      <label className="field">
        <span className="field-label">Text</span>
        <textarea value={text} onChange={(e) => setProp((p: { text: string }) => (p.text = e.target.value))} />
      </label>
      <label className="field">
        <span className="field-label">Style</span>
        <select value={tag || "p"} onChange={(e) => setProp((p: { tag: string }) => (p.tag = e.target.value))}>
          <option value="h1">Heading 1</option>
          <option value="h2">Heading 2</option>
          <option value="p">Paragraph</option>
        </select>
      </label>
    </>
  );
}

CanvasText.craft = {
  displayName: "Text",
  props: { text: "Text", tag: "p" },
  related: { settings: TextSettings },
};

// ---- Dataset table --------------------------------------------------------------
export function CanvasDatasetTable({ datasetId = null }: { datasetId?: string | null }) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const preview = useQuery({
    queryKey: ["canvas-widget-preview", datasetId],
    queryFn: () => dsApi.preview(workspaceId, projectId, datasetId!),
    enabled: !!datasetId,
  });

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!datasetId && <p className="canvas-widget-empty">Table — pick a dataset in Settings</p>}
      {datasetId && preview.isPending && <p className="canvas-widget-empty">Loading…</p>}
      {preview.data && (
        <div className="data-grid">
          <table>
            <thead>
              <tr>
                {preview.data.columns.map((c) => (
                  <th key={c.name}>{c.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.data.rows.slice(0, 25).map((row, i) => (
                <tr key={i}>
                  {row.map((v, j) => (
                    <td key={j}>{v === null ? "" : String(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DatasetTableSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    datasetId,
    actions: { setProp },
  } = useNode((node) => ({ datasetId: node.data.props.datasetId }));
  const list = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });
  return (
    <label className="field">
      <span className="field-label">Dataset</span>
      <select
        value={datasetId || ""}
        onChange={(e) => setProp((p: { datasetId: string | null }) => (p.datasetId = e.target.value || null))}
      >
        <option value="">Choose…</option>
        {list.data?.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>
    </label>
  );
}

CanvasDatasetTable.craft = {
  displayName: "Dataset table",
  props: { datasetId: null },
  related: { settings: DatasetTableSettings },
};

// ---- Action form (write-back) --------------------------------------------------
export function CanvasActionForm({ actionTypeId = null }: { actionTypeId?: string | null }) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId, mode } = useCanvasEnv();
  const queryClient = useQueryClient();

  const actionTypesQ = useQuery({
    queryKey: ["action-types", workspaceId],
    queryFn: () => actionApi.listTypes(workspaceId),
  });
  const actionType = actionTypesQ.data?.find((a) => a.id === actionTypeId) ?? null;

  const instancesQ = useQuery({
    queryKey: ["canvas-widget-instances", actionType?.object_type_id],
    queryFn: () => objApi.listInstances(workspaceId, actionType!.object_type_id, 25, 0),
    enabled: !!actionType,
  });

  const [instanceId, setInstanceId] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const execute = useMutation({
    mutationFn: () => actionApi.execute(workspaceId, projectId, actionType!.id, instanceId, values),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["canvas-widget-instances"] });
    },
  });

  const live = mode === "run";

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!actionType && <p className="canvas-widget-empty">Action form — pick an action in Settings</p>}
      {actionType && (
        <form
          className="card"
          onSubmit={(e) => {
            e.preventDefault();
            if (live) execute.mutate();
          }}
        >
          <h3 style={{ marginTop: 0 }}>{actionType.display_name}</h3>
          <label className="field">
            <span className="field-label">Record</span>
            <select value={instanceId} onChange={(e) => setInstanceId(e.target.value)} disabled={!live}>
              <option value="">Choose…</option>
              {instancesQ.data?.items.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.primary_key}
                </option>
              ))}
            </select>
          </label>
          {actionType.editable_properties.map((prop) => (
            <label className="field" key={prop}>
              <span className="field-label">{prop}</span>
              <input
                type="text"
                value={values[prop] ?? ""}
                onChange={(e) => setValues({ ...values, [prop]: e.target.value })}
                disabled={!live}
              />
            </label>
          ))}
          <button type="submit" className="btn" disabled={!live || !instanceId || execute.isPending}>
            {execute.isPending ? "Submitting…" : "Submit"}
          </button>
          {!live && <p className="canvas-widget-empty">Submitting is disabled while editing — use Preview to try it.</p>}
          {execute.isSuccess && execute.data.ok && <p className="login-note">Saved.</p>}
          {execute.isSuccess && !execute.data.ok && <div className="form-error">{execute.data.error}</div>}
        </form>
      )}
    </div>
  );
}

function ActionFormSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    actionTypeId,
    actions: { setProp },
  } = useNode((node) => ({ actionTypeId: node.data.props.actionTypeId }));
  const list = useQuery({
    queryKey: ["action-types", workspaceId],
    queryFn: () => actionApi.listTypes(workspaceId),
  });
  return (
    <label className="field">
      <span className="field-label">Action</span>
      <select
        value={actionTypeId || ""}
        onChange={(e) => setProp((p: { actionTypeId: string | null }) => (p.actionTypeId = e.target.value || null))}
      >
        <option value="">Choose…</option>
        {list.data?.map((a) => (
          <option key={a.id} value={a.id}>
            {a.display_name}
          </option>
        ))}
      </select>
    </label>
  );
}

CanvasActionForm.craft = {
  displayName: "Action form",
  props: { actionTypeId: null },
  related: { settings: ActionFormSettings },
};

export const CANVAS_RESOLVER = {
  CanvasContainer,
  CanvasText,
  CanvasDatasetTable,
  CanvasActionForm,
};

export const PALETTE: { key: keyof typeof CANVAS_RESOLVER; label: string; hint: string }[] = [
  { key: "CanvasContainer", label: "Container", hint: "A box to arrange other widgets in" },
  { key: "CanvasText", label: "Text", hint: "A heading or paragraph" },
  { key: "CanvasDatasetTable", label: "Dataset table", hint: "Preview rows from a dataset" },
  { key: "CanvasActionForm", label: "Action form", hint: "Write back to an object instance" },
];

/** Toolbox drag-source button — creates a new node of `Component` when
 * dropped onto the canvas. Kept here since it needs the same
 * `useEditor().connectors.create` every palette entry shares. */
export function PaletteItem({ componentKey, label, hint }: { componentKey: keyof typeof CANVAS_RESOLVER; label: string; hint: string }) {
  const { connectors } = useEditor();
  const Component = CANVAS_RESOLVER[componentKey];
  return (
    <div
      ref={(ref) => {
        if (ref) connectors.create(ref, <Component />);
      }}
      className="canvas-palette-item"
      title={hint}
    >
      <strong>{label}</strong>
      <span>{hint}</span>
    </div>
  );
}
