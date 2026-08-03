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
import {
  useCanvasEnv,
  useCanvasParameter,
  useCanvasParameters,
  useCanvasVariable,
  useCanvasVariables,
} from "./context";
import {
  chartQuery,
  distinctValuesQuery,
  filteredQuery,
  mapQuery,
  type Aggregate,
  type ChartKind,
  type FilterOperator,
} from "./filter-sql";
import { Chart, toPoints } from "./charts";
import { MapCanvas, toLatLon, type MapPoint } from "./map";
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
  objectSetVariable = null,
  pageSize = 25,
}: {
  objectTypeId?: string | null;
  filterProperty?: string | null;
  filterParameter?: string | null;
  searchParameter?: string | null;
  /** An `object_set` variable to read (roadmap 1.2). When set, this table and
   * every other consumer of that variable read *one* set, narrowed once on the
   * server, rather than each filtering its own copy. Takes precedence over the
   * inline type/filter props, which are the pre-variable way of saying the
   * same thing and stay for apps that have not been rewired. */
  objectSetVariable?: string | null;
  pageSize?: number;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const searchValue = useCanvasParameter(searchParameter);
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();
  const usingSet = !!objectSetVariable;

  const setPage = useQuery({
    queryKey: ["canvas-object-set", objectSetVariable, JSON.stringify(setDefinition ?? null), pageSize],
    queryFn: () => objApi.evaluateObjectSet(workspaceId, setDefinition, { limit: pageSize }),
    // Not until the definition has resolved. Querying with `undefined` would
    // ask the server to evaluate nothing and render "0 objects", which is an
    // answer this widget does not have yet.
    enabled: usingSet && !!setDefinition,
  });

  const effectiveTypeId = usingSet
    ? ((setDefinition as { object_type_id?: string } | undefined)?.object_type_id ?? null)
    : objectTypeId;
  const type = useQuery({
    queryKey: ["object-type", effectiveTypeId],
    queryFn: () => objApi.getType(workspaceId, effectiveTypeId!),
    enabled: !!effectiveTypeId,
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

  // One shape for both paths, so everything below reads the same. The set path
  // returns `instances`; the explore path returns `items`.
  const rows = usingSet ? setPage.data?.instances : page.data?.items;
  const total = usingSet ? setPage.data?.total : page.data?.total;
  const active = usingSet ? setPage : page;
  const setFilters =
    ((setDefinition as { filters?: { property: string; value: unknown }[] } | undefined)
      ?.filters) ?? [];

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!usingSet && !objectTypeId && (
        <p className="canvas-widget-empty">Object table - pick an object type in Settings</p>
      )}
      {usingSet && (variablesPending || (!setDefinition && !active.isError)) && (
        <p className="canvas-widget-empty">Resolving the object set…</p>
      )}
      {!usingSet && objectTypeId && page.isPending && (
        <p className="canvas-widget-empty">Loading…</p>
      )}
      {active.isError && <p className="canvas-widget-empty">Couldn&apos;t load these objects.</p>}
      {rows && total !== undefined && (
        <>
          <p className="canvas-widget-empty">
            {total.toLocaleString()} {type.data?.display_name ?? "object"}
            {total === 1 ? "" : "s"}
            {/* The set says what narrowed it. A table that showed a filtered
                count with no sign it was filtered is the same trap as a
                sampled preview that does not say so. */}
            {usingSet && setFilters.length > 0
              ? ` where ${setFilters
                  .map((f) => `${f.property} = ${String(f.value)}`)
                  .join(" and ")}`
              : ""}
            {!usingSet && useProperty ? ` where ${filterProperty} = ${String(filterValue)}` : ""}
            {!usingSet && !useProperty && searchValue
              ? ` matching “${String(searchValue)}”`
              : ""}
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
                {rows.map((instance) => (
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
          {total > rows.length && (
            <p className="canvas-widget-empty">
              Showing the first {rows.length} of {total.toLocaleString()}.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function ObjectTableSettings() {
  const { workspaceId } = useCanvasEnv();
  const { declared } = useCanvasVariables();
  const {
    objectTypeId, filterProperty, filterParameter, searchParameter,
    objectSetVariable, pageSize,
    actions: { setProp },
  } = useNode((node) => ({
    objectTypeId: node.data.props.objectTypeId,
    filterProperty: node.data.props.filterProperty,
    filterParameter: node.data.props.filterParameter,
    searchParameter: node.data.props.searchParameter,
    objectSetVariable: node.data.props.objectSetVariable,
    pageSize: node.data.props.pageSize,
  }));
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
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
      {/* The variable binding comes first because it *replaces* the three
          fields under it. Offering them equally would invite configuring both
          and wondering which won. */}
      <label className="field">
        <span className="field-label">Object set variable</span>
        <select
          value={objectSetVariable || ""}
          onChange={(e) =>
            setProp((p: { objectSetVariable: string | null }) =>
              (p.objectSetVariable = e.target.value || null))
          }
        >
          <option value="">Not bound — configure below</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {setVariables.length === 0
            ? "No object set variables yet — add one in the Variables tab"
            : "Reads a set every other widget can read too"}
        </span>
      </label>
      <label className="field">
        <span className="field-label">Object type</span>
        <select
          disabled={!!objectSetVariable}
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

// ---- Map (ROADMAP Canvas item 4) --------------------------------------------
/**
 * Pins on a map, from either half of the platform: an object type's geopoint
 * property, or a dataset's location column(s). Both paths end in the same
 * `toLatLon`, because the platform writes a geopoint back to a dataset column
 * as "lat,lon" - a widget that understood the ontology's shape but not the
 * dataset's would fail against the very datasets its objects came from.
 *
 * Rows whose location cannot be read are counted and reported rather than
 * dropped: "3 without a usable location" is a fact about the data, and it is
 * the fact somebody needs in order to go and fix it.
 */
export function CanvasMap({
  source = "objects",
  objectTypeId = null,
  locationProperty = null,
  labelProperty = null,
  datasetId = null,
  locationColumn = null,
  latColumn = null,
  lonColumn = null,
  labelColumn = null,
  filterProperty = null,
  filterColumn = null,
  filterOperator = "equals",
  filterParameter = null,
  searchParameter = null,
  limit = 500,
}: {
  source?: "objects" | "dataset";
  objectTypeId?: string | null;
  locationProperty?: string | null;
  labelProperty?: string | null;
  datasetId?: string | null;
  locationColumn?: string | null;
  latColumn?: string | null;
  lonColumn?: string | null;
  labelColumn?: string | null;
  filterProperty?: string | null;
  filterColumn?: string | null;
  filterOperator?: FilterOperator;
  filterParameter?: string | null;
  searchParameter?: string | null;
  limit?: number;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const searchValue = useCanvasParameter(searchParameter);

  const usesProperty = !!filterProperty && filterValue !== undefined && filterValue !== null
    && filterValue !== "";
  // The explorer endpoint's own page cap. Asking for more is a 422, and
  // raising that bound platform-wide to suit one widget would be the wrong
  // way round - the map reports what it could not fetch instead.
  const objectLimit = Math.min(limit, 200);
  const objectPage = useQuery({
    queryKey: [
      "canvas-map-objects", objectTypeId, locationProperty,
      usesProperty ? filterProperty : null, usesProperty ? String(filterValue) : null,
      searchValue ?? null, objectLimit,
    ],
    queryFn: () =>
      objApi.explore(workspaceId, {
        typeIds: [objectTypeId!],
        ...(usesProperty
          ? { property: filterProperty!, value: String(filterValue) }
          : { q: searchValue ? String(searchValue) : undefined }),
        limit: objectLimit,
      }),
    enabled: source === "objects" && !!objectTypeId && !!locationProperty,
  });

  const sql = mapQuery({
    locationColumn, latColumn, lonColumn, labelColumn,
    filterColumn, filterOperator, filterValue, limit,
  });
  const datasetRows = useQuery({
    queryKey: ["canvas-map-dataset", datasetId, sql],
    queryFn: () => dsApi.query(workspaceId, projectId, datasetId!, sql!),
    enabled: source === "dataset" && !!datasetId && sql !== null,
  });

  const { points, unplaceable } = React.useMemo(() => {
    const collected: MapPoint[] = [];
    let bad = 0;
    if (source === "objects") {
      for (const instance of objectPage.data?.items ?? []) {
        const at = toLatLon(instance.properties[locationProperty!]);
        if (!at) {
          bad += 1;
          continue;
        }
        const label = labelProperty ? instance.properties[labelProperty] : null;
        collected.push({
          id: instance.id,
          label: label === null || label === undefined ? instance.primary_key : String(label),
          ...at,
        });
      }
    } else {
      const rows = datasetRows.data?.rows ?? [];
      rows.forEach((row, index) => {
        // Arity is the discriminator `mapQuery` set up: [label, point] for a
        // single location column, [label, lat, lon] for a pair.
        const at = row.length > 2 ? toLatLon([row[1], row[2]]) : toLatLon(row[1]);
        if (!at) {
          bad += 1;
          return;
        }
        collected.push({
          id: String(index),
          label: row[0] === null || row[0] === undefined ? `Row ${index + 1}` : String(row[0]),
          ...at,
        });
      });
    }
    return { points: collected, unplaceable: bad };
  }, [source, objectPage.data, datasetRows.data, locationProperty, labelProperty]);

  const needs =
    source === "objects"
      ? !objectTypeId ? "pick an object type in Settings"
        : !locationProperty ? "pick the geopoint property to plot"
        : null
      : !datasetId ? "pick a dataset in Settings"
        : sql === null ? "pick a location column, or a latitude and longitude pair"
        : null;
  const query = source === "objects" ? objectPage : datasetRows;

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {needs && <p className="canvas-widget-empty">Map — {needs}</p>}
      {!needs && query.isPending && <p className="canvas-widget-empty">Loading…</p>}
      {!needs && query.isError && (
        <p className="canvas-widget-empty">
          {query.error instanceof ApiError ? query.error.message : "Couldn't load these points."}
        </p>
      )}
      {!needs && query.data && (
        <MapCanvas
          points={points}
          unplaceable={unplaceable}
          total={source === "objects" ? objectPage.data?.total : undefined}
          atLimit={
            source === "dataset" && (datasetRows.data?.rows.length ?? 0) >= (limit ?? 500)
          }
        />
      )}
    </div>
  );
}

function MapSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    source, objectTypeId, locationProperty, labelProperty, datasetId,
    locationColumn, latColumn, lonColumn, labelColumn,
    filterProperty, filterColumn, filterOperator, filterParameter, searchParameter,
    actions: { setProp },
  } = useNode((node) => ({
    source: node.data.props.source,
    objectTypeId: node.data.props.objectTypeId,
    locationProperty: node.data.props.locationProperty,
    labelProperty: node.data.props.labelProperty,
    datasetId: node.data.props.datasetId,
    locationColumn: node.data.props.locationColumn,
    latColumn: node.data.props.latColumn,
    lonColumn: node.data.props.lonColumn,
    labelColumn: node.data.props.labelColumn,
    filterProperty: node.data.props.filterProperty,
    filterColumn: node.data.props.filterColumn,
    filterOperator: node.data.props.filterOperator,
    filterParameter: node.data.props.filterParameter,
    searchParameter: node.data.props.searchParameter,
  }));
  const types = useQuery({
    queryKey: ["object-types", workspaceId],
    queryFn: () => objApi.listTypes(workspaceId),
    enabled: source === "objects",
  });
  const detail = useQuery({
    queryKey: ["object-type", objectTypeId],
    queryFn: () => objApi.getType(workspaceId, objectTypeId!),
    enabled: source === "objects" && !!objectTypeId,
  });
  const datasetList = useQuery({
    queryKey: ["datasets", workspaceId, projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
    enabled: source === "dataset",
  });
  const columns = (datasetList.data?.find((d) => d.id === datasetId)?.table_schema ?? [])
    .map((c) => c.name);
  // Only geopoint properties are offered: a map of a string property would
  // plot nothing and say nothing about why.
  const geopoints = (detail.data?.properties ?? []).filter((p) => p.data_type === "geopoint");

  return (
    <>
      <label className="field">
        <span className="field-label">Points from</span>
        <select
          value={source}
          onChange={(e) => setProp((p: Record<string, unknown>) => (p.source = e.target.value))}
        >
          <option value="objects">An object type</option>
          <option value="dataset">A dataset</option>
        </select>
      </label>
      {source === "objects" ? (
        <>
          <label className="field">
            <span className="field-label">Object type</span>
            <select
              value={objectTypeId || ""}
              onChange={(e) =>
                setProp((p: Record<string, unknown>) => {
                  p.objectTypeId = e.target.value || null;
                  p.locationProperty = null;
                  p.labelProperty = null;
                  p.filterProperty = null;
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
            <span className="field-label">Location property</span>
            <select
              value={locationProperty || ""}
              disabled={!objectTypeId}
              onChange={(e) =>
                setProp((p: { locationProperty: string | null }) => (p.locationProperty = e.target.value || null))
              }
            >
              <option value="">Choose…</option>
              {geopoints.map((p) => (
                <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
              ))}
            </select>
            {objectTypeId && geopoints.length === 0 && (
              <span className="field-hint">This type has no geopoint property</span>
            )}
          </label>
          <label className="field">
            <span className="field-label">Label property</span>
            <select
              value={labelProperty || ""}
              disabled={!objectTypeId}
              onChange={(e) =>
                setProp((p: { labelProperty: string | null }) => (p.labelProperty = e.target.value || null))
              }
            >
              <option value="">Primary key</option>
              {detail.data?.properties.map((p) => (
                <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
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
          </label>
        </>
      ) : (
        <>
          <label className="field">
            <span className="field-label">Dataset</span>
            <select
              value={datasetId || ""}
              onChange={(e) =>
                setProp((p: Record<string, unknown>) => {
                  p.datasetId = e.target.value || null;
                  p.locationColumn = null;
                  p.latColumn = null;
                  p.lonColumn = null;
                  p.labelColumn = null;
                  p.filterColumn = null;
                })
              }
            >
              <option value="">Choose…</option>
              {datasetList.data?.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Location column</span>
            <select
              value={locationColumn || ""}
              disabled={!datasetId}
              onChange={(e) =>
                setProp((p: { locationColumn: string | null }) => (p.locationColumn = e.target.value || null))
              }
            >
              <option value="">None</option>
              {columns.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <span className="field-hint">A &quot;lat,lon&quot; column — what a synced geopoint writes</span>
          </label>
          <label className="field">
            <span className="field-label">Latitude column</span>
            <select
              value={latColumn || ""}
              disabled={!datasetId}
              onChange={(e) =>
                setProp((p: { latColumn: string | null }) => (p.latColumn = e.target.value || null))
              }
            >
              <option value="">None</option>
              {columns.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Longitude column</span>
            <select
              value={lonColumn || ""}
              disabled={!datasetId}
              onChange={(e) =>
                setProp((p: { lonColumn: string | null }) => (p.lonColumn = e.target.value || null))
              }
            >
              <option value="">None</option>
              {columns.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <span className="field-hint">A latitude/longitude pair wins over the column above</span>
          </label>
          <label className="field">
            <span className="field-label">Label column</span>
            <select
              value={labelColumn || ""}
              disabled={!datasetId}
              onChange={(e) =>
                setProp((p: { labelColumn: string | null }) => (p.labelColumn = e.target.value || null))
              }
            >
              <option value="">Row number</option>
              {columns.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Filter column</span>
            <select
              value={filterColumn || ""}
              disabled={!datasetId}
              onChange={(e) =>
                setProp((p: { filterColumn: string | null }) => (p.filterColumn = e.target.value || null))
              }
            >
              <option value="">No filter</option>
              {columns.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Filter match</span>
            <select
              value={filterOperator || "equals"}
              onChange={(e) =>
                setProp((p: { filterOperator: FilterOperator }) => (p.filterOperator = e.target.value as FilterOperator))
              }
            >
              <option value="equals">Equals</option>
              <option value="contains">Contains</option>
            </select>
          </label>
        </>
      )}
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
    </>
  );
}

CanvasMap.craft = {
  displayName: "Map",
  props: {
    source: "objects", objectTypeId: null, locationProperty: null, labelProperty: null,
    datasetId: null, locationColumn: null, latColumn: null, lonColumn: null, labelColumn: null,
    filterProperty: null, filterColumn: null, filterOperator: "equals",
    filterParameter: null, searchParameter: null, limit: 500,
  },
  related: { settings: MapSettings },
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
  objectSetVariable = null,
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
  /** An `object_set` variable to plot instead of a dataset (roadmap 1.5).
   * Grouped counts only: a grouped *sum* has the same untyped-property problem
   * a plain sum does, so the two stores would disagree about the bar heights.
   * See `services/object_sets.py`. */
  objectSetVariable?: string | null;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();
  const usingSet = !!objectSetVariable;

  const sql = chartQuery({
    kind, dimension, measure, aggregate,
    filterColumn, filterOperator, filterValue,
  });

  const datasetResult = useQuery({
    queryKey: ["canvas-chart", datasetId, sql],
    queryFn: () => dsApi.query(workspaceId, projectId, datasetId!, sql!),
    enabled: !usingSet && !!datasetId && sql !== null,
  });
  const setResult = useQuery({
    queryKey: [
      "canvas-chart-set", objectSetVariable,
      JSON.stringify(setDefinition ?? null), dimension,
    ],
    queryFn: () => objApi.groupObjectSet(workspaceId, setDefinition, dimension!),
    enabled: usingSet && !!setDefinition && !!dimension,
  });

  const result = usingSet ? setResult : datasetResult;
  const points = usingSet
    ? (setResult.data?.groups ?? []).map((g) => ({ label: g.value, value: g.count }))
    : datasetResult.data
      ? toPoints(datasetResult.data.rows)
      : null;

  const needs = usingSet
    ? (!dimension ? "pick a property to group by" : null)
    : !datasetId ? "pick a dataset in Settings"
    : !dimension ? (kind === "scatter" ? "pick an X column" : "pick a category column")
    : (kind === "scatter" || aggregate !== "count") && !measure
      ? (kind === "scatter" ? "pick a Y column" : `pick a column to ${aggregate}`)
      : null;

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {title && <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>{title}</h3>}
      {needs && <p className="canvas-widget-empty">Chart - {needs}</p>}
      {!needs && (result.isPending || (usingSet && variablesPending)) && (
        <p className="canvas-widget-empty">Loading…</p>
      )}
      {result.isError && (
        // The engine's own message, not a generic failure: "Conversion Error:
        // Could not convert string 'north' to DOUBLE" tells a builder exactly
        // which column they picked by mistake.
        <p className="canvas-widget-empty">
          {result.error instanceof ApiError ? result.error.message : "Couldn't run this chart."}
        </p>
      )}
      {points && <Chart kind={kind} points={points} />}
      {/* Said, not hidden: a chart drawing the top 20 of 300 without a word is
          the same trap as a preview that sampled and did not mention it. */}
      {usingSet && setResult.data?.truncated && (
        <p className="canvas-widget-empty">
          Showing the largest {setResult.data.groups.length} of{" "}
          {setResult.data.distinct_total.toLocaleString()} values.
        </p>
      )}
      {!usingSet && datasetResult.data && filterParameter && filterValue ? (
        <p className="canvas-widget-empty">
          Filtered by {filterParameter}: {String(filterValue)}
        </p>
      ) : null}
    </div>
  );
}

function ChartSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    datasetId, kind, dimension, measure, aggregate, title,
    filterColumn, filterParameter, filterOperator, objectSetVariable,
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
    objectSetVariable: node.data.props.objectSetVariable,
  }));
  const list = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const setTypeId = (resolved[objectSetVariable as string] as
    { object_type_id?: string } | undefined)?.object_type_id;
  const setType = useQuery({
    queryKey: ["object-type", setTypeId],
    queryFn: () => objApi.getType(workspaceId, setTypeId!),
    enabled: !!setTypeId,
  });
  const dataset = list.data?.find((d) => d.id === datasetId);
  // The dimension picker offers the set's properties when plotting a set, and
  // the dataset's columns otherwise - one control, whichever source is in
  // play, rather than two that can both be half-filled.
  const columns = objectSetVariable
    ? (setType.data?.properties ?? []).map((prop) => ({ name: prop.api_name, data_type: prop.data_type }))
    : dataset?.table_schema ?? [];
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
      {/* An object set replaces the dataset, so it is offered first and
          disables what it replaces - rather than letting both be configured
          and leaving whoever reads the app to guess which won. */}
      <label className="field">
        <span className="field-label">Object set variable</span>
        <select
          value={objectSetVariable || ""}
          onChange={(e) =>
            setProp((p: Record<string, unknown>) => {
              p.objectSetVariable = e.target.value || null;
              p.dimension = null; // property names are per-source
            })
          }
        >
          <option value="">Not bound — plot a dataset</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        {objectSetVariable && (
          <span className="field-hint">Counts objects in each group</span>
        )}
      </label>
      <label className="field">
        <span className="field-label">Dataset</span>
        <select
          disabled={!!objectSetVariable}
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
    objectSetVariable: null,
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

/** A Metric Card: one number over an object set (roadmap 1.5).
 *
 * The widget Workshop apps lead with, and the one that makes an object set
 * worth having as a shared thing: the card, the table and the chart all read
 * *the same* variable, so "127 sites" and the rows under it cannot disagree.
 *
 * Only `count` and `count_distinct` are offered, because those are the two the
 * two stores answer identically over untyped properties - see
 * `services/object_sets.py`. A sum would be right on one deployment and absent
 * on another.
 */
export function CanvasMetricCard({
  objectSetVariable = null,
  aggregation = "count",
  property = null,
  label = "",
}: {
  objectSetVariable?: string | null;
  aggregation?: "count" | "count_distinct";
  property?: string | null;
  label?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();

  const metric = useQuery({
    queryKey: [
      "canvas-metric", objectSetVariable, JSON.stringify(setDefinition ?? null),
      aggregation, property,
    ],
    queryFn: () =>
      objApi.aggregateObjectSet(workspaceId, setDefinition, {
        aggregation,
        property: property ?? undefined,
      }),
    enabled: !!objectSetVariable && !!setDefinition,
  });

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      <div className="metric-card">
        <span className="metric-label">{label || "Metric"}</span>
        {!objectSetVariable ? (
          <p className="canvas-widget-empty">Pick an object set variable in Settings</p>
        ) : variablesPending || metric.isPending ? (
          // Not "0". A card that showed a number it did not have would be
          // believed, and nobody re-reads a figure that looked fine.
          <span className="metric-value soft">…</span>
        ) : metric.isError ? (
          <p className="canvas-widget-empty">{(metric.error as Error).message}</p>
        ) : (
          <span className="metric-value">{metric.data!.value.toLocaleString()}</span>
        )}
      </div>
    </div>
  );
}

function MetricCardSettings() {
  const { workspaceId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    objectSetVariable, aggregation, property, label,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    aggregation: node.data.props.aggregation,
    property: node.data.props.property,
    label: node.data.props.label,
  }));
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  // Which type the chosen set draws from, so the property picker offers that
  // type's properties rather than a free-text box that fails at read time.
  const typeId = (resolved[objectSetVariable as string] as { object_type_id?: string } | undefined)
    ?.object_type_id;
  const detail = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });

  return (
    <>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          value={label ?? ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Object set variable</span>
        <select
          value={objectSetVariable || ""}
          onChange={(e) =>
            setProp((p: { objectSetVariable: string | null }) =>
              (p.objectSetVariable = e.target.value || null))
          }
        >
          <option value="">Choose…</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Shows</span>
        <select
          value={aggregation ?? "count"}
          onChange={(e) =>
            setProp((p: { aggregation: string }) => (p.aggregation = e.target.value))
          }
        >
          <option value="count">How many</option>
          <option value="count_distinct">How many distinct values</option>
        </select>
        <span className="field-hint">
          Sums and averages need typed properties — see the ontology roadmap
        </span>
      </label>
      {aggregation === "count_distinct" && (
        <label className="field">
          <span className="field-label">Of property</span>
          <select
            value={property || ""}
            onChange={(e) =>
              setProp((p: { property: string | null }) => (p.property = e.target.value || null))
            }
          >
            <option value="">Choose…</option>
            {detail.data?.properties.map((prop) => (
              <option key={prop.api_name} value={prop.api_name}>{prop.api_name}</option>
            ))}
          </select>
        </label>
      )}
    </>
  );
}

CanvasMetricCard.craft = {
  displayName: "Metric card",
  props: { objectSetVariable: null, aggregation: "count", property: null, label: "" },
  related: { settings: MetricCardSettings },
};

export const CANVAS_RESOLVER = {
  CanvasContainer,
  CanvasText,
  CanvasParameterControl,
  CanvasDatasetTable,
  CanvasObjectTable,
  CanvasChart,
  CanvasMap,
  CanvasMetricCard,
  CanvasActionForm,
};

export const PALETTE: { key: keyof typeof CANVAS_RESOLVER; label: string; hint: string }[] = [
  { key: "CanvasContainer", label: "Container", hint: "A box to arrange other widgets in" },
  { key: "CanvasText", label: "Text", hint: "A heading or paragraph" },
  { key: "CanvasParameterControl", label: "Filter", hint: "A dropdown or search box other widgets filter by" },
  { key: "CanvasDatasetTable", label: "Dataset table", hint: "Preview rows from a dataset" },
  { key: "CanvasObjectTable", label: "Object table", hint: "Live rows from an ontology object type" },
  { key: "CanvasChart", label: "Chart", hint: "Bar, line, pie or scatter over a dataset" },
  { key: "CanvasMap", label: "Map", hint: "Pins from a geopoint property or location columns" },
  { key: "CanvasMetricCard", label: "Metric card", hint: "One number over an object set" },
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
