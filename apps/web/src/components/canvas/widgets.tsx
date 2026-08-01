"use client";

/** Canvas widgets - the components a saved app's Craft.js definition is
 * built from. Each reads workspace/project id + edit-vs-run mode from
 * CanvasEnvProvider (never from its own serialised props - the same app
 * renders from more than one route), and reuses the datasets/objects/
 * actions endpoints already built elsewhere; a widget only remembers which
 * dataset/action it's bound to, never a copy of the data itself. */

import { useEditor, useNode } from "@craftjs/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useState } from "react";
import { actions as actionApi, datasets as dsApi, objects as objApi } from "@/lib/api";
import { useCanvasEnv, useCanvasParameter, useCanvasParameters } from "./context";
import { distinctValuesQuery, filteredQuery, type FilterOperator } from "./filter-sql";

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

// ---- Parameter (filter control) --------------------------------------------
/**
 * Sets a named value other widgets read (ROADMAP Canvas item 1). This is the
 * foundation the roadmap asks for before charts: a widget that *publishes*
 * state, rather than one more widget that only consumes data.
 *
 * A dropdown's options come from a dataset column's distinct values rather
 * than a list typed by the builder. A hand-typed list is a copy of the data
 * that goes stale the first time a new value appears - the same argument that
 * made object links derived rather than stored (§37).
 */
export function CanvasParameterControl({
  name = "",
  label = "Filter",
  control = "select",
  datasetId = null,
  column = null,
}: {
  name?: string;
  label?: string;
  control?: "select" | "text";
  datasetId?: string | null;
  column?: string | null;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const { values, set } = useCanvasParameters();
  const current = name ? values[name] : undefined;

  const options = useQuery({
    queryKey: ["canvas-parameter-options", datasetId, column],
    queryFn: () => dsApi.query(workspaceId, projectId, datasetId!, distinctValuesQuery(column!)),
    enabled: control === "select" && !!datasetId && !!column,
  });

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!name && (
        <p className="canvas-widget-empty">
          Filter - give it a parameter name in Settings, then point a table at it
        </p>
      )}
      {name && (
        <label className="field" style={{ maxWidth: 320 }}>
          <span className="field-label">{label}</span>
          {control === "select" ? (
            <select
              aria-label={label}
              value={current === undefined || current === null ? "" : String(current)}
              onChange={(e) => set(name, e.target.value || null)}
            >
              {/* "All" is the default, and it is the empty value: a filter
                  that starts filtered looks like an app with no data. */}
              <option value="">All</option>
              {options.data?.rows.map((row, i) => (
                <option key={i} value={String(row[0])}>
                  {String(row[0])}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="search"
              aria-label={label}
              value={current === undefined || current === null ? "" : String(current)}
              onChange={(e) => set(name, e.target.value || null)}
              placeholder="Type to filter…"
            />
          )}
          {control === "select" && !column && (
            <span className="field-hint">Pick a dataset column in Settings to fill this list</span>
          )}
        </label>
      )}
    </div>
  );
}

function ParameterSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    name,
    label,
    control,
    datasetId,
    column,
    actions: { setProp },
  } = useNode((node) => ({
    name: node.data.props.name,
    label: node.data.props.label,
    control: node.data.props.control,
    datasetId: node.data.props.datasetId,
    column: node.data.props.column,
  }));
  const list = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });
  const dataset = list.data?.find((d) => d.id === datasetId);

  return (
    <>
      <label className="field">
        <span className="field-label">Parameter name</span>
        <input
          type="text"
          value={name || ""}
          placeholder="region"
          onChange={(e) => setProp((p: { name: string }) => (p.name = e.target.value))}
        />
        <span className="field-hint">Tables reference this name to filter by it</span>
      </label>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          type="text"
          value={label || ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Control</span>
        <select
          value={control || "select"}
          onChange={(e) => setProp((p: { control: string }) => (p.control = e.target.value))}
        >
          <option value="select">Dropdown</option>
          <option value="text">Search box</option>
        </select>
      </label>
      {control !== "text" && (
        <>
          <label className="field">
            <span className="field-label">Options from dataset</span>
            <select
              value={datasetId || ""}
              onChange={(e) =>
                setProp((p: { datasetId: string | null; column: string | null }) => {
                  p.datasetId = e.target.value || null;
                  p.column = null;  // a column name means nothing against another dataset
                })
              }
            >
              <option value="">Choose…</option>
              {list.data?.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Column</span>
            <select
              value={column || ""}
              disabled={!dataset}
              onChange={(e) => setProp((p: { column: string | null }) => (p.column = e.target.value || null))}
            >
              <option value="">Choose…</option>
              {dataset?.table_schema.map((c) => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          </label>
        </>
      )}
    </>
  );
}

CanvasParameterControl.craft = {
  displayName: "Filter",
  props: { name: "", label: "Filter", control: "select", datasetId: null, column: null },
  related: { settings: ParameterSettings },
};

// ---- Dataset table --------------------------------------------------------------
export function CanvasDatasetTable({
  datasetId = null,
  filterColumn = null,
  filterParameter = null,
  filterOperator = "equals",
}: {
  datasetId?: string | null;
  filterColumn?: string | null;
  filterParameter?: string | null;
  filterOperator?: FilterOperator;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const parameterValue = useCanvasParameter(filterParameter);
  const sql = filteredQuery(filterColumn, filterOperator, parameterValue);

  // Two queries rather than one with a branch inside: they have different
  // cache keys and different lifetimes - the unfiltered preview is shared
  // with every other widget on the same dataset, the filtered one is keyed to
  // a value that changes as the viewer types.
  const preview = useQuery({
    queryKey: ["canvas-widget-preview", datasetId],
    queryFn: () => dsApi.preview(workspaceId, projectId, datasetId!),
    enabled: !!datasetId && sql === null,
  });
  const filtered = useQuery({
    queryKey: ["canvas-widget-filtered", datasetId, sql],
    queryFn: () => dsApi.query(workspaceId, projectId, datasetId!, sql!),
    enabled: !!datasetId && sql !== null,
  });
  const active = sql === null ? preview : filtered;

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!datasetId && <p className="canvas-widget-empty">Table - pick a dataset in Settings</p>}
      {datasetId && active.isPending && <p className="canvas-widget-empty">Loading…</p>}
      {active.isError && (
        <p className="canvas-widget-empty">Couldn&apos;t load rows for this filter.</p>
      )}
      {active.data && (
        <>
          {sql !== null && (
            <p className="canvas-widget-empty">
              Filtered by {filterParameter}: {String(parameterValue)} — {active.data.rows.length} row
              {active.data.rows.length === 1 ? "" : "s"}
            </p>
          )}
          <div className="data-grid">
            <table>
              <thead>
                <tr>
                  {active.data.columns.map((c) => (
                    <th key={c.name}>{c.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {active.data.rows.slice(0, 25).map((row, i) => (
                  <tr key={i}>
                    {row.map((v, j) => (
                      <td key={j}>{v === null ? "" : String(v)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function DatasetTableSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    datasetId,
    filterColumn,
    filterParameter,
    filterOperator,
    actions: { setProp },
  } = useNode((node) => ({
    datasetId: node.data.props.datasetId,
    filterColumn: node.data.props.filterColumn,
    filterParameter: node.data.props.filterParameter,
    filterOperator: node.data.props.filterOperator,
  }));
  const list = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });
  const dataset = list.data?.find((d) => d.id === datasetId);
  return (
    <>
      <label className="field">
        <span className="field-label">Dataset</span>
        <select
          value={datasetId || ""}
          onChange={(e) =>
            setProp((p: { datasetId: string | null; filterColumn: string | null }) => {
              p.datasetId = e.target.value || null;
              p.filterColumn = null;
            })
          }
        >
          <option value="">Choose…</option>
          {list.data?.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Filter column</span>
        <select
          value={filterColumn || ""}
          disabled={!dataset}
          onChange={(e) => setProp((p: { filterColumn: string | null }) => (p.filterColumn = e.target.value || null))}
        >
          <option value="">No filter</option>
          {dataset?.table_schema.map((c) => (
            <option key={c.name} value={c.name}>{c.name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Filter parameter</span>
        <input
          type="text"
          value={filterParameter || ""}
          placeholder="region"
          onChange={(e) =>
            setProp((p: { filterParameter: string | null }) => (p.filterParameter = e.target.value || null))
          }
        />
        <span className="field-hint">The name set on a Filter widget</span>
      </label>
      <label className="field">
        <span className="field-label">Match</span>
        <select
          value={filterOperator || "equals"}
          onChange={(e) => setProp((p: { filterOperator: string }) => (p.filterOperator = e.target.value))}
        >
          <option value="equals">Exactly equals</option>
          <option value="contains">Contains</option>
        </select>
      </label>
    </>
  );
}

CanvasDatasetTable.craft = {
  displayName: "Dataset table",
  props: {
    datasetId: null,
    filterColumn: null,
    filterParameter: null,
    filterOperator: "equals",
  },
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
      {!actionType && <p className="canvas-widget-empty">Action form - pick an action in Settings</p>}
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
          {!live && <p className="canvas-widget-empty">Submitting is disabled while editing - use Preview to try it.</p>}
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
  CanvasParameterControl,
  CanvasDatasetTable,
  CanvasActionForm,
};

export const PALETTE: { key: keyof typeof CANVAS_RESOLVER; label: string; hint: string }[] = [
  { key: "CanvasContainer", label: "Container", hint: "A box to arrange other widgets in" },
  { key: "CanvasText", label: "Text", hint: "A heading or paragraph" },
  { key: "CanvasParameterControl", label: "Filter", hint: "A dropdown or search box other widgets filter by" },
  { key: "CanvasDatasetTable", label: "Dataset table", hint: "Preview rows from a dataset" },
  { key: "CanvasActionForm", label: "Action form", hint: "Write back to an object instance" },
];

/** Toolbox drag-source button - creates a new node of `Component` when
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
