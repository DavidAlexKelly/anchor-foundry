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
import { actions as actionApi, ApiError, datasets as dsApi, objects as objApi } from "@/lib/api";
import { useCanvasEnv, useCanvasParameter, useCanvasParameters } from "./context";
import {
  chartQuery,
  distinctValuesQuery,
  filteredQuery,
  type Aggregate,
  type ChartKind,
  type FilterOperator,
} from "./filter-sql";
import { Chart, toPoints } from "./charts";
import { PropertyValue } from "@/components/property-value";

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

// ---- Object table (ROADMAP Canvas item 3) -----------------------------------
/**
 * A table bound to an object *type* rather than a raw dataset - the pattern
 * the roadmap argues real Workshop-style apps are built on, since an ontology
 * object is the thing a business user recognises and a dataset row is not.
 *
 * It reuses the Explorer's query surface (Objects item 2) as the item asks,
 * with one addition that item did not have: **exact property filtering**. `q`
 * is substring/prefix matching across every property at once, which is right
 * for a search box and wrong for a dropdown - picking the region "North" must
 * not also return a customer called "Northwind". The store Protocol has had
 * `find_by_property` since Objects item 3; this widget is what made it worth
 * exposing on the endpoint.
 *
 * Values render through the same `PropertyValue` the Objects pages use, so a
 * geopoint reads as coordinates and an attachment as a download link inside a
 * canvas app too, rather than as `[object Object]`.
 */
export function CanvasObjectTable({
  objectTypeId = null,
  filterProperty = null,
  filterParameter = null,
  searchParameter = null,
  pageSize = 25,
}: {
  objectTypeId?: string | null;
  filterProperty?: string | null;
  filterParameter?: string | null;
  searchParameter?: string | null;
  pageSize?: number;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const searchValue = useCanvasParameter(searchParameter);

  const type = useQuery({
    queryKey: ["object-type", objectTypeId],
    queryFn: () => objApi.getType(workspaceId, objectTypeId!),
    enabled: !!objectTypeId,
  });

  // An exact property filter and a free-text search are different questions,
  // so the widget picks one rather than pretending to combine them: the
  // endpoint's property filter is its own read path, not a refinement of `q`.
  const useProperty = !!filterProperty && filterValue !== undefined && filterValue !== null
    && filterValue !== "";
  const page = useQuery({
    queryKey: [
      "canvas-object-table", objectTypeId, useProperty ? filterProperty : null,
      useProperty ? String(filterValue) : null, searchValue ?? null, pageSize,
    ],
    queryFn: () =>
      objApi.explore(workspaceId, {
        typeIds: [objectTypeId!],
        ...(useProperty
          ? { property: filterProperty!, value: String(filterValue) }
          : { q: searchValue ? String(searchValue) : undefined }),
        limit: pageSize,
      }),
    enabled: !!objectTypeId,
  });

  const properties = type.data?.properties ?? [];

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectTypeId && (
        <p className="canvas-widget-empty">Object table - pick an object type in Settings</p>
      )}
      {objectTypeId && page.isPending && <p className="canvas-widget-empty">Loading…</p>}
      {page.isError && <p className="canvas-widget-empty">Couldn&apos;t load these objects.</p>}
      {page.data && (
        <>
          <p className="canvas-widget-empty">
            {page.data.total.toLocaleString()} {type.data?.display_name ?? "object"}
            {page.data.total === 1 ? "" : "s"}
            {useProperty ? ` where ${filterProperty} = ${String(filterValue)}` : ""}
            {!useProperty && searchValue ? ` matching “${String(searchValue)}”` : ""}
          </p>
          <div className="data-grid">
            <table>
              <thead>
                <tr>
                  <th>Key</th>
                  {properties.map((p) => (
                    <th key={p.api_name}>{p.display_name || p.api_name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {page.data.items.map((instance) => (
                  <tr key={instance.id}>
                    <td>{instance.primary_key}</td>
                    {properties.map((p) => (
                      <td key={p.api_name}>
                        <PropertyValue
                          workspaceId={workspaceId}
                          dataType={p.data_type}
                          value={instance.properties[p.api_name]}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {page.data.total > page.data.items.length && (
            <p className="canvas-widget-empty">
              Showing the first {page.data.items.length} of {page.data.total.toLocaleString()}.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function ObjectTableSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectTypeId, filterProperty, filterParameter, searchParameter, pageSize,
    actions: { setProp },
  } = useNode((node) => ({
    objectTypeId: node.data.props.objectTypeId,
    filterProperty: node.data.props.filterProperty,
    filterParameter: node.data.props.filterParameter,
    searchParameter: node.data.props.searchParameter,
    pageSize: node.data.props.pageSize,
  }));
  const types = useQuery({
    queryKey: ["object-types", workspaceId],
    queryFn: () => objApi.listTypes(workspaceId),
  });
  const detail = useQuery({
    queryKey: ["object-type", objectTypeId],
    queryFn: () => objApi.getType(workspaceId, objectTypeId!),
    enabled: !!objectTypeId,
  });

  return (
    <>
      <label className="field">
        <span className="field-label">Object type</span>
        <select
          value={objectTypeId || ""}
          onChange={(e) =>
            setProp((p: Record<string, unknown>) => {
              p.objectTypeId = e.target.value || null;
              p.filterProperty = null;  // property names are per-type
            })
          }
        >
          <option value="">Choose…</option>
          {types.data?.map((t) => (
            <option key={t.id} value={t.id}>{t.display_name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Filter property</span>
        <select
          value={filterProperty || ""}
          disabled={!objectTypeId}
          onChange={(e) =>
            setProp((p: { filterProperty: string | null }) => (p.filterProperty = e.target.value || null))
          }
        >
          <option value="">No property filter</option>
          <option value="$primary_key">Primary key</option>
          {detail.data?.properties.map((p) => (
            <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
          ))}
        </select>
        <span className="field-hint">Exact match — for a dropdown</span>
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
      </label>
      <label className="field">
        <span className="field-label">Search parameter</span>
        <input
          type="text"
          value={searchParameter || ""}
          placeholder="search"
          onChange={(e) =>
            setProp((p: { searchParameter: string | null }) => (p.searchParameter = e.target.value || null))
          }
        />
        <span className="field-hint">Substring across every property — for a search box</span>
      </label>
      <label className="field">
        <span className="field-label">Rows</span>
        <input
          type="number"
          value={pageSize ?? 25}
          min={1}
          max={200}
          onChange={(e) =>
            setProp((p: { pageSize: number }) => (p.pageSize = Math.max(1, Math.min(200, Number(e.target.value) || 25))))
          }
        />
      </label>
    </>
  );
}

CanvasObjectTable.craft = {
  displayName: "Object table",
  props: {
    objectTypeId: null, filterProperty: null, filterParameter: null,
    searchParameter: null, pageSize: 25,
  },
  related: { settings: ObjectTableSettings },
};

// ---- Chart (ROADMAP Canvas item 2) ------------------------------------------
/**
 * The "BI" half of "app/BI builder". Bound to a dataset, aggregated by the
 * server, and reactive to a filter parameter through the same predicate the
 * dataset table uses - so a chart and a table pointed at one parameter always
 * agree about which rows are in scope.
 */
export function CanvasChart({
  datasetId = null,
  kind = "bar",
  dimension = null,
  measure = null,
  aggregate = "count",
  title = "",
  filterColumn = null,
  filterParameter = null,
  filterOperator = "equals",
}: {
  datasetId?: string | null;
  kind?: ChartKind;
  dimension?: string | null;
  measure?: string | null;
  aggregate?: Aggregate;
  title?: string;
  filterColumn?: string | null;
  filterParameter?: string | null;
  filterOperator?: FilterOperator;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const sql = chartQuery({
    kind, dimension, measure, aggregate,
    filterColumn, filterOperator, filterValue,
  });

  const result = useQuery({
    queryKey: ["canvas-chart", datasetId, sql],
    queryFn: () => dsApi.query(workspaceId, projectId, datasetId!, sql!),
    enabled: !!datasetId && sql !== null,
  });

  const needs =
    !datasetId ? "pick a dataset in Settings"
    : !dimension ? (kind === "scatter" ? "pick an X column" : "pick a category column")
    : (kind === "scatter" || aggregate !== "count") && !measure
      ? (kind === "scatter" ? "pick a Y column" : `pick a column to ${aggregate}`)
      : null;

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {title && <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>{title}</h3>}
      {needs && <p className="canvas-widget-empty">Chart - {needs}</p>}
      {!needs && result.isPending && <p className="canvas-widget-empty">Loading…</p>}
      {result.isError && (
        // The engine's own message, not a generic failure: "Conversion Error:
        // Could not convert string 'north' to DOUBLE" tells a builder exactly
        // which column they picked by mistake.
        <p className="canvas-widget-empty">
          {result.error instanceof ApiError ? result.error.message : "Couldn't run this chart."}
        </p>
      )}
      {result.data && <Chart kind={kind} points={toPoints(result.data.rows)} />}
      {result.data && filterParameter && filterValue ? (
        <p className="canvas-widget-empty">
          Filtered by {filterParameter}: {String(filterValue)}
        </p>
      ) : null}
    </div>
  );
}

function ChartSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    datasetId, kind, dimension, measure, aggregate, title,
    filterColumn, filterParameter, filterOperator,
    actions: { setProp },
  } = useNode((node) => ({
    datasetId: node.data.props.datasetId,
    kind: node.data.props.kind,
    dimension: node.data.props.dimension,
    measure: node.data.props.measure,
    aggregate: node.data.props.aggregate,
    title: node.data.props.title,
    filterColumn: node.data.props.filterColumn,
    filterParameter: node.data.props.filterParameter,
    filterOperator: node.data.props.filterOperator,
  }));
  const list = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });
  const dataset = list.data?.find((d) => d.id === datasetId);
  const columns = dataset?.table_schema ?? [];
  const scatter = kind === "scatter";

  return (
    <>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          type="text"
          value={title || ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Chart type</span>
        <select value={kind || "bar"} onChange={(e) => setProp((p: { kind: string }) => (p.kind = e.target.value))}>
          <option value="bar">Bar</option>
          <option value="line">Line</option>
          <option value="pie">Pie</option>
          <option value="scatter">Scatter</option>
        </select>
      </label>
      <label className="field">
        <span className="field-label">Dataset</span>
        <select
          value={datasetId || ""}
          onChange={(e) =>
            setProp((p: Record<string, unknown>) => {
              p.datasetId = e.target.value || null;
              // Column names mean nothing against a different dataset.
              p.dimension = null;
              p.measure = null;
              p.filterColumn = null;
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
        <span className="field-label">{scatter ? "X column" : "Category"}</span>
        <select
          value={dimension || ""}
          disabled={!dataset}
          onChange={(e) => setProp((p: { dimension: string | null }) => (p.dimension = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      </label>
      {!scatter && (
        <label className="field">
          <span className="field-label">Measure</span>
          <select
            value={aggregate || "count"}
            onChange={(e) => setProp((p: { aggregate: string }) => (p.aggregate = e.target.value))}
          >
            <option value="count">Count of rows</option>
            <option value="sum">Sum of…</option>
            <option value="avg">Average of…</option>
            <option value="min">Minimum of…</option>
            <option value="max">Maximum of…</option>
          </select>
        </label>
      )}
      {(scatter || aggregate !== "count") && (
        <label className="field">
          <span className="field-label">{scatter ? "Y column" : "Of column"}</span>
          <select
            value={measure || ""}
            disabled={!dataset}
            onChange={(e) => setProp((p: { measure: string | null }) => (p.measure = e.target.value || null))}
          >
            <option value="">Choose…</option>
            {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
        </label>
      )}
      <label className="field">
        <span className="field-label">Filter column</span>
        <select
          value={filterColumn || ""}
          disabled={!dataset}
          onChange={(e) => setProp((p: { filterColumn: string | null }) => (p.filterColumn = e.target.value || null))}
        >
          <option value="">No filter</option>
          {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
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

CanvasChart.craft = {
  displayName: "Chart",
  props: {
    datasetId: null, kind: "bar", dimension: null, measure: null,
    aggregate: "count", title: "", filterColumn: null,
    filterParameter: null, filterOperator: "equals",
  },
  related: { settings: ChartSettings },
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
  CanvasObjectTable,
  CanvasChart,
  CanvasActionForm,
};

export const PALETTE: { key: keyof typeof CANVAS_RESOLVER; label: string; hint: string }[] = [
  { key: "CanvasContainer", label: "Container", hint: "A box to arrange other widgets in" },
  { key: "CanvasText", label: "Text", hint: "A heading or paragraph" },
  { key: "CanvasParameterControl", label: "Filter", hint: "A dropdown or search box other widgets filter by" },
  { key: "CanvasDatasetTable", label: "Dataset table", hint: "Preview rows from a dataset" },
  { key: "CanvasObjectTable", label: "Object table", hint: "Live rows from an ontology object type" },
  { key: "CanvasChart", label: "Chart", hint: "Bar, line, pie or scatter over a dataset" },
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
