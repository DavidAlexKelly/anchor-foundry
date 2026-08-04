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
  useCanvasPage,
  useCanvasParameter,
  useCanvasParameters,
  useCanvasVariable,
  useCanvasVariables,
} from "./context";
import { eventsFor, interpolate, run as runEvents, useEventContext } from "./events";
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
/** Whether a layout node bound to a `visibleWhen` variable should render, and
 * how the builder shows one that is hidden (roadmap 1.7).
 *
 * Foundry's example: a section that appears only when a set is non-empty.
 * `is_empty`/`is_not_empty` have existed in the variable graph since item 1.2
 * precisely for this, so the condition is *a variable*, not an expression
 * language invented here - anything a viewer's state can decide is already
 * expressible as a derivation, and a second grammar would be a second thing to
 * validate, explain and keep in step.
 *
 * **Unresolved means visible.** `undefined` is "the first resolve has not come
 * back yet", and a section that vanished until it did would flash on every
 * load. Only an explicitly falsy value hides - the rule the Button's gate
 * already follows (§81).
 *
 * **In the builder a hidden node still renders, marked.** Hiding it there
 * would make it uneditable and hide from the author that it exists, which is
 * the argument §77 made for pages and is the same argument.
 */
function useVisibility(variableId: string | null | undefined): {
  hidden: boolean;
  marker: string | null;
} {
  const { mode } = useCanvasEnv();
  const { resolved, declared } = useCanvasVariables();
  if (!variableId) return { hidden: false, marker: null };
  const value = resolved[variableId];
  const hidden = value !== undefined && !value;
  if (!hidden) return { hidden: false, marker: null };
  if (mode === "edit") {
    const label = declared[variableId]?.label || variableId;
    return { hidden: false, marker: `hidden unless ${label}` };
  }
  return { hidden: true, marker: null };
}

export function CanvasContainer({
  children,
  background,
  padding,
  visibleWhen = null,
}: {
  children?: React.ReactNode;
  background?: string;
  padding?: number;
  /** A variable that must be truthy for this box to show (roadmap 1.7). */
  visibleWhen?: string | null;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { hidden, marker } = useVisibility(visibleWhen);
  if (hidden) return null;
  return (
    <div
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className="canvas-block"
      style={{ background: background || "transparent", padding: padding ?? 12 }}
    >
      {marker && <p className="canvas-hidden-marker">{marker}</p>}
      {children}
    </div>
  );
}

/** The one control every node that can be conditionally shown uses, so the
 * wording and the "always" option are written once. */
function VisibilityField({
  value,
  onChange,
}: {
  value: string | null | undefined;
  onChange: (next: string | null) => void;
}) {
  const { declared } = useCanvasVariables();
  return (
    <label className="field">
      <span className="field-label">Shown when</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        <option value="">Always</option>
        {Object.values(declared).map((v) => (
          <option key={v.id} value={v.id}>
            {v.label || v.id}
          </option>
        ))}
      </select>
      <span className="field-hint">
        Hidden while this variable is empty or false — Is not empty makes one
      </span>
    </label>
  );
}

function ContainerSettings() {
  const {
    background,
    padding,
    visibleWhen,
    actions: { setProp },
  } = useNode((node) => ({
    background: node.data.props.background,
    padding: node.data.props.padding,
    visibleWhen: node.data.props.visibleWhen,
  }));
  return (
    <>
      <VisibilityField
        value={visibleWhen}
        onChange={(next) => setProp((p: { visibleWhen: string | null }) => (p.visibleWhen = next))}
      />
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
  props: { background: "", padding: 12, visibleWhen: null },
  related: { settings: ContainerSettings },
};

// ---- Text ---------------------------------------------------------------------
export function CanvasText({ text = "Text", tag = "p" }: { text?: string; tag?: "h1" | "h2" | "p" }) {
  const {
    connectors: { connect, drag },
  } = useNode();
  // `{{v_id}}` reads a resolved variable (roadmap 1.3). Without this an event
  // that sets a variable has nothing to show for itself, and "did the click
  // work" is only answerable by watching the network tab.
  const { resolved } = useCanvasVariables();
  const rendered = interpolate(text ?? "", resolved);
  return React.createElement(
    tag,
    { ref: (ref: HTMLElement | null) => connectDragDrop(ref, connect, drag), style: { margin: 0 } },
    rendered,
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
        <span className="field-hint">
          {"{{v_id}}"} shows a variable&apos;s current value
        </span>
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

// ---- Filter List -----------------------------------------------------------
/**
 * The canonical Workshop widget (roadmap 1.5, priority 1): property-aware
 * filters over an object set.
 *
 * **It reads a set and writes clauses; a derivation makes the narrowed set.**
 * The widget does not produce an object-set variable directly, and that is the
 * design rather than a shortcut. Object-set variables resolve on the server -
 * that is what makes "how many are there" and "the next page" answerable at
 * all (`services/object_sets.py`) - so a widget that wrote a set would be a
 * second place sets come from, with no rule for which one wins. Instead the
 * widget writes a plain list of clauses, and a `narrow_set` variable applies
 * them to the input set. Widgets write values; derivations make sets.
 *
 * **The options are the data's, with counts, not a list somebody typed.** Each
 * property's values come from `/object-sets/group` against the *input* set, so
 * they are always the values that actually exist, and each carries how many
 * rows it accounts for. A hand-typed list goes stale the first time a new
 * value appears - the argument that made object links derived rather than
 * stored (§37) and dropdown options come from a column (Canvas item 1).
 *
 * **Counts come from the unfiltered input set on purpose.** Recomputing them
 * against the *narrowed* set would make every count go to zero except the ones
 * you already picked, and a filter list whose other options all read "0" tells
 * you nothing about what selecting them would do.
 */
export function CanvasFilterList({
  objectSetVariable = null,
  variable = null,
  properties = "",
  title = "Filters",
}: {
  /** The set to offer filters over. */
  objectSetVariable?: string | null;
  /** The variable this widget writes its clauses into. A `narrow_set`
   * derivation reads it and the input set, and produces the filtered set
   * every other widget then points at. */
  variable?: string | null;
  /** Property api_names to offer, comma-separated. Blank means "none yet" -
   * a filter list over every property of a wide type would be a wall. */
  properties?: string;
  title?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const { set } = useCanvasParameters();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const chosen = useCanvasParameter(variable);

  const names = String(properties || "")
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);

  // What is currently selected, per property, read back from the variable this
  // widget writes - so the checkboxes reflect the document's state rather than
  // a second copy of it held here.
  const selected: Record<string, string[]> = {};
  for (const clause of Array.isArray(chosen) ? chosen : []) {
    const c = clause as { property?: string; op?: string; value?: unknown };
    if (!c.property) continue;
    selected[c.property] = Array.isArray(c.value) ? c.value.map(String) : [String(c.value)];
  }

  const toggle = (property: string, value: string) => {
    const current = selected[property] ?? [];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    const merged = { ...selected, [property]: next };
    const clauses = Object.entries(merged)
      .filter(([, values]) => values.length > 0)
      // One value is `eq`, several are `in`. Both mean the same thing on both
      // stores; sending a one-element `in` would work too, but `eq` is what a
      // reader of the saved document expects to see for a single choice.
      .map(([prop, values]) =>
        values.length === 1
          ? { property: prop, op: "eq", value: values[0] }
          : { property: prop, op: "in", value: values },
      );
    if (variable) set(variable, clauses);
  };

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      <p className="field-label">{title}</p>
      {!objectSetVariable || !variable ? (
        <p className="canvas-widget-empty">
          Filter list - point it at an object set and at the variable it writes in Settings
        </p>
      ) : names.length === 0 ? (
        <p className="canvas-widget-empty">Choose properties to filter on in Settings</p>
      ) : (
        names.map((property) => (
          <FilterListProperty
            key={property}
            workspaceId={workspaceId}
            definition={setDefinition}
            property={property}
            selected={selected[property] ?? []}
            onToggle={(value) => toggle(property, value)}
          />
        ))
      )}
    </div>
  );
}

function FilterListProperty({
  workspaceId,
  definition,
  property,
  selected,
  onToggle,
}: {
  workspaceId: string;
  definition: unknown;
  property: string;
  selected: string[];
  onToggle: (value: string) => void;
}) {
  const result = useQuery({
    queryKey: ["canvas-filter-list", property, JSON.stringify(definition ?? null)],
    queryFn: () => objApi.groupObjectSet(workspaceId, definition, property),
    enabled: !!definition,
  });
  return (
    <fieldset className="canvas-filter-group">
      <legend>{property}</legend>
      {result.isError && (
        <p className="canvas-widget-empty">Couldn&apos;t read this property&apos;s values.</p>
      )}
      {result.data?.truncated && (
        <p className="canvas-widget-empty">showing the most common values</p>
      )}
      {(result.data?.groups ?? []).map((group) => (
        <label key={group.value} className="canvas-filter-option">
          <input
            type="checkbox"
            checked={selected.includes(group.value)}
            onChange={() => onToggle(group.value)}
          />
          <span>{group.value}</span>
          <span className="canvas-filter-count">{group.count}</span>
        </label>
      ))}
      {result.data && result.data.groups.length === 0 && (
        <p className="canvas-widget-empty">no values</p>
      )}
    </fieldset>
  );
}

function FilterListSettings() {
  const {
    objectSetVariable,
    variable,
    properties,
    title,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    variable: node.data.props.variable,
    properties: node.data.props.properties,
    title: node.data.props.title,
  }));
  const { declared } = useCanvasVariables();
  const sets = Object.values(declared).filter((v) => v.kind === "object_set");
  const arrays = Object.values(declared).filter((v) => v.kind === "array");
  return (
    <>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          value={title ?? ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Object set</span>
        <select
          value={objectSetVariable ?? ""}
          onChange={(e) =>
            setProp(
              (p: { objectSetVariable: string | null }) =>
                (p.objectSetVariable = e.target.value || null),
            )
          }
        >
          <option value="">Pick a set</option>
          {sets.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label || v.id}
            </option>
          ))}
        </select>
        <span className="field-hint">The set the options are read from</span>
      </label>
      <label className="field">
        <span className="field-label">Writes its filters to</span>
        <select
          value={variable ?? ""}
          onChange={(e) =>
            setProp((p: { variable: string | null }) => (p.variable = e.target.value || null))
          }
        >
          <option value="">Pick a variable</option>
          {arrays.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label || v.id}
            </option>
          ))}
        </select>
        <span className="field-hint">
          An array variable. Point a narrow_set variable at it and the set to get the
          filtered set other widgets read.
        </span>
      </label>
      <label className="field">
        <span className="field-label">Properties</span>
        <input
          value={properties ?? ""}
          placeholder="region, status"
          onChange={(e) =>
            setProp((p: { properties: string }) => (p.properties = e.target.value))
          }
        />
        <span className="field-hint">Comma-separated property names to offer</span>
      </label>
    </>
  );
}

CanvasFilterList.craft = {
  displayName: "Filter list",
  props: { objectSetVariable: null, variable: null, properties: "", title: "Filters" },
  related: { settings: FilterListSettings },
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
  columns = "",
  sort = "recent",
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
  /** Which properties to show, in order, comma-separated. Blank means all of
   * them - a table that showed nothing until somebody configured it would look
   * broken on the first drop. */
  columns?: string;
  /** One of the server's `object_sets.SORTS`. Sorting *by a property* is
   * refused there rather than here, because untyped properties would order
   * differently on the two stores; the settings panel therefore offers what
   * the server accepts rather than a column-header click that sometimes 422s. */
  sort?: string;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const eventContext = useEventContext(undefined, useOverlayIds());
  const filterValue = useCanvasParameter(filterParameter);
  const searchValue = useCanvasParameter(searchParameter);
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending, events: moduleEvents } = useCanvasVariables();
  const usingSet = !!objectSetVariable;
  const [offset, setOffset] = useState(0);

  // Paging is *runtime* state, like a page or a variable value (decision 0002
  // §3): a saved app opens on the first page for every viewer. It also has to
  // reset when the set changes, or narrowing a filter while on page 3 leaves a
  // viewer looking at an empty table that has rows.
  const setKey = JSON.stringify(setDefinition ?? null);
  const [lastKey, setLastKey] = useState(setKey);
  if (setKey !== lastKey) {
    setLastKey(setKey);
    setOffset(0);
  }

  const setPage = useQuery({
    queryKey: ["canvas-object-set", objectSetVariable, setKey, pageSize, offset, sort],
    queryFn: () =>
      objApi.evaluateObjectSet(workspaceId, setDefinition, {
        limit: pageSize,
        offset,
        sort,
      }),
    // Not until the definition has resolved. Querying with `undefined` would
    // ask the server to evaluate nothing and render "0 objects", which is an
    // answer this widget does not have yet.
    enabled: usingSet && !!setDefinition,
    // The previous page stays on screen while the next one loads, rather than
    // the table emptying and jumping - the rows are about to be replaced, not
    // gone.
    placeholderData: (previous) => previous,
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

  const all = type.data?.properties ?? [];
  // Configured order wins, and a name that matches nothing is dropped rather
  // than rendered as an empty column: a property can be removed from the type
  // long after a table was pointed at it.
  const wanted = String(columns || "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
  const properties = wanted.length
    ? wanted.map((name) => all.find((p) => p.api_name === name)).filter((p) => !!p)
    : all;

  // One shape for both paths, so everything below reads the same. The set path
  // returns `instances`; the explore path returns `items`.
  const rows = usingSet ? setPage.data?.instances : page.data?.items;
  const total = usingSet ? setPage.data?.total : page.data?.total;
  const active = usingSet ? setPage : page;
  const setFilters =
    ((setDefinition as { filters?: { property: string; value: unknown }[] } | undefined)
      ?.filters) ?? [];

  // Row selection (roadmap 1.3). The widget does not decide what a click
  // *means* - it announces that a row was chosen and hands over the row, and
  // the module's events say what happens. That is the difference between a
  // widget with a hardcoded behaviour and one an app author can wire.
  const rowEvents = eventsFor(moduleEvents, nodeId, "row_select");
  const rowsAreClickable = rowEvents.length > 0;
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
                  <tr
                    key={instance.id}
                    className={rowsAreClickable ? "row-clickable" : undefined}
                    onClick={
                      rowsAreClickable
                        ? () =>
                            runEvents(rowEvents, {
                              ...eventContext,
                              payload: {
                                primary_key: instance.primary_key,
                                ...instance.properties,
                              },
                              // The same row twice, deliberately: flattened
                              // above for `{{...}}` in a label, and whole here
                              // for a `single_object` variable, which needs to
                              // know which field is the key.
                              object: {
                                // The row twice, deliberately: flattened above
                                // for `{{...}}` in a label, and whole here for
                                // a `single_object` variable, which needs to
                                // know which field is the key - and the id,
                                // which is what the write APIs take.
                                id: instance.id,
                                // The table's own type, not the row's: every
                                // row in one table is one type, and the row
                                // payload does not carry it.
                                object_type_id: effectiveTypeId ?? undefined,
                                primary_key: instance.primary_key,
                                properties: instance.properties,
                              },
                            })
                        : undefined
                    }
                  >
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
          {usingSet && total > rows.length && (
            <div className="canvas-table-pager">
              <button
                type="button"
                className="btn quiet"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
              >
                Previous
              </button>
              <span className="canvas-widget-empty">
                {offset + 1}–{offset + rows.length} of {total.toLocaleString()}
              </span>
              <button
                type="button"
                className="btn quiet"
                disabled={offset + rows.length >= total}
                onClick={() => setOffset(offset + pageSize)}
              >
                Next
              </button>
            </div>
          )}
          {!usingSet && total > rows.length && (
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
    objectSetVariable, pageSize, columns, sort,
    actions: { setProp },
  } = useNode((node) => ({
    objectTypeId: node.data.props.objectTypeId,
    filterProperty: node.data.props.filterProperty,
    filterParameter: node.data.props.filterParameter,
    searchParameter: node.data.props.searchParameter,
    objectSetVariable: node.data.props.objectSetVariable,
    pageSize: node.data.props.pageSize,
    columns: node.data.props.columns,
    sort: node.data.props.sort,
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
        <span className="field-label">Rows per page</span>
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
      <label className="field">
        <span className="field-label">Columns</span>
        <input
          type="text"
          value={columns ?? ""}
          placeholder="every property"
          onChange={(e) => setProp((p: { columns: string }) => (p.columns = e.target.value))}
        />
        <span className="field-hint">
          Property names in the order to show them. Blank shows all of them.
        </span>
      </label>
      <label className="field">
        <span className="field-label">Sort by</span>
        <select
          value={sort ?? "recent"}
          onChange={(e) => setProp((p: { sort: string }) => (p.sort = e.target.value))}
        >
          <option value="recent">Last changed, newest first</option>
          <option value="oldest">Last changed, oldest first</option>
          <option value="key">Key, A–Z</option>
          <option value="-key">Key, Z–A</option>
        </select>
        {/* Not a click on a column header, deliberately. Properties are stored
            untyped, so the server refuses to order by one - and a header that
            sometimes errored would be worse than one that never invited the
            click. See `object_sets.SORTS`. */}
        <span className="field-hint">
          Sorting by a property needs its declared type behind it — see the ontology roadmap
        </span>
      </label>
    </>
  );
}

CanvasObjectTable.craft = {
  displayName: "Object table",
  props: {
    objectTypeId: null, filterProperty: null, filterParameter: null,
    searchParameter: null, pageSize: 25, columns: "", sort: "recent",
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
  objectSetVariable = null,
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
  /** An `object_set` variable to plot (roadmap 1.5). When set, this map reads
   * the same set the table and the chart do, narrowed once on the server -
   * rather than running its own type-and-filter query beside them and drifting
   * from what the rest of the app is showing. Takes precedence over the inline
   * type/filter props, as it does on every other set-aware widget. */
  objectSetVariable?: string | null;
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
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const searchValue = useCanvasParameter(searchParameter);
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending, events: moduleEvents } = useCanvasVariables();
  const eventContext = useEventContext(undefined, useOverlayIds());
  const usingSet = source === "objects" && !!objectSetVariable;

  const setPage = useQuery({
    queryKey: ["canvas-map-set", objectSetVariable, JSON.stringify(setDefinition ?? null), limit],
    queryFn: () =>
      objApi.evaluateObjectSet(workspaceId, setDefinition, { limit: Math.min(limit, 200) }),
    enabled: usingSet && !!setDefinition,
  });

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
    enabled: source === "objects" && !usingSet && !!objectTypeId && !!locationProperty,
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
      for (const instance of (usingSet ? setPage.data?.instances : objectPage.data?.items) ?? []) {
        const at = toLatLon(instance.properties[locationProperty!]);
        if (!at) {
          bad += 1;
          continue;
        }
        const label = labelProperty ? instance.properties[labelProperty] : null;
        collected.push({
          id: instance.id,
          label: label === null || label === undefined ? instance.primary_key : String(label),
          // The instance rides along so a pin click can emit the object it
          // stands for, the way a row click does (§84). Without it the map
          // would be the one widget that can show an object and not hand it on.
          instance,
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
  }, [source, usingSet, setPage.data, objectPage.data, datasetRows.data,
      locationProperty, labelProperty]);

  const needs =
    source === "objects"
      ? usingSet
        ? !locationProperty ? "pick the geopoint property to plot" : null
        : !objectTypeId ? "pick an object type in Settings"
        : !locationProperty ? "pick the geopoint property to plot"
        : null
      : !datasetId ? "pick a dataset in Settings"
        : sql === null ? "pick a location column, or a latitude and longitude pair"
        : null;
  const query = source === "objects" ? (usingSet ? setPage : objectPage) : datasetRows;
  // Pin selection (roadmap 1.5). The map does not decide what a click *means*
  // any more than the table does: it says an object was picked and the
  // module's events say what happens.
  const pinEvents = eventsFor(moduleEvents, nodeId, "row_select");

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {needs && <p className="canvas-widget-empty">Map — {needs}</p>}
      {!needs && query.isPending && <p className="canvas-widget-empty">Loading…</p>}
      {!needs && query.isError && (
        <p className="canvas-widget-empty">
          {query.error instanceof ApiError ? query.error.message : "Couldn't load these points."}
        </p>
      )}
      {usingSet && variablesPending && (
        <p className="canvas-widget-empty">Resolving the object set…</p>
      )}
      {!needs && query.data && (
        <MapCanvas
          points={points}
          unplaceable={unplaceable}
          total={
            source === "objects"
              ? (usingSet ? setPage.data?.total : objectPage.data?.total)
              : undefined
          }
          atLimit={
            source === "dataset" && (datasetRows.data?.rows.length ?? 0) >= (limit ?? 500)
          }
          onSelect={
            pinEvents.length > 0
              ? (point) =>
                  runEvents(pinEvents, {
                    ...eventContext,
                    payload: {
                      primary_key: point.instance?.primary_key,
                      ...(point.instance?.properties ?? {}),
                    },
                    object: point.instance
                      ? {
                          id: point.instance.id,
                          object_type_id:
                            (setDefinition as { object_type_id?: string } | undefined)
                              ?.object_type_id ?? objectTypeId ?? undefined,
                          primary_key: point.instance.primary_key,
                          properties: point.instance.properties,
                        }
                      : undefined,
                  })
              : undefined
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
    objectSetVariable,
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
    objectSetVariable: node.data.props.objectSetVariable,
  }));
  const { declared } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  // The type behind the bound set, so the geopoint picker can offer that
  // type's properties - the set names its type, so the author does not.
  const setTypeId =
    (declared[objectSetVariable ?? ""]?.object_set as { object_type_id?: string } | undefined)
      ?.object_type_id ?? null;
  const effectiveTypeId = objectSetVariable ? setTypeId : objectTypeId;
  const types = useQuery({
    queryKey: ["object-types", workspaceId],
    queryFn: () => objApi.listTypes(workspaceId),
    enabled: source === "objects",
  });
  const detail = useQuery({
    queryKey: ["object-type", effectiveTypeId],
    queryFn: () => objApi.getType(workspaceId, effectiveTypeId!),
    enabled: source === "objects" && !!effectiveTypeId,
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
          {/* The variable binding comes first because it *replaces* the type
              and filter fields under it - the same ordering the object table
              uses, for the same reason: offering them equally invites
              configuring both and wondering which won. */}
          <label className="field">
            <span className="field-label">Object set variable</span>
            <select
              value={objectSetVariable || ""}
              onChange={(e) =>
                setProp((p: Record<string, unknown>) => {
                  p.objectSetVariable = e.target.value || null;
                })
              }
            >
              <option value="">Not bound — use the type below</option>
              {setVariables.map((v) => (
                <option key={v.id} value={v.id}>{v.label || v.id}</option>
              ))}
            </select>
            <span className="field-hint">
              Reads the same set as every other widget bound to it
            </span>
          </label>
          <label className="field" hidden={!!objectSetVariable}>
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
              disabled={!effectiveTypeId}
              onChange={(e) =>
                setProp((p: { locationProperty: string | null }) => (p.locationProperty = e.target.value || null))
              }
            >
              <option value="">Choose…</option>
              {geopoints.map((p) => (
                <option key={p.api_name} value={p.api_name}>{p.api_name}</option>
              ))}
            </select>
            {effectiveTypeId && geopoints.length === 0 && (
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
    source: "objects",
    objectSetVariable: null, objectTypeId: null, locationProperty: null, labelProperty: null,
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
export function CanvasActionForm({
  actionTypeId = null,
  subjectVariable = null,
}: {
  actionTypeId?: string | null;
  /** A `single_object` variable naming what to edit (roadmap 1.5, the inline
   * action form). Bound, the form edits the object somebody picked and the
   * record dropdown disappears — which is the difference between a form beside
   * an app and a form *in* one. Unbound, it keeps the dropdown, so the apps
   * built before this still work. */
  subjectVariable?: string | null;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId, mode } = useCanvasEnv();
  const queryClient = useQueryClient();
  const subject = useCanvasVariable(subjectVariable) as
    | { id?: string; primary_key?: unknown; properties?: Record<string, unknown> }
    | undefined;
  const { set: setParameter } = useCanvasParameters();

  const actionTypesQ = useQuery({
    queryKey: ["action-types", workspaceId],
    queryFn: () => actionApi.listTypes(workspaceId),
  });
  const actionType = actionTypesQ.data?.find((a) => a.id === actionTypeId) ?? null;

  const instancesQ = useQuery({
    queryKey: ["canvas-widget-instances", actionType?.object_type_id],
    queryFn: () => objApi.listInstances(workspaceId, actionType!.object_type_id, 25, 0),
    enabled: !!actionType && !subjectVariable,
  });

  const [picked, setPicked] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const instanceId = subjectVariable ? String(subject?.id ?? "") : picked;

  // The fields start at what the object currently says, so the form shows the
  // thing being edited rather than an empty box beside it. Re-seeded whenever
  // the subject changes - picking a different row and finding the last one's
  // values still typed in would be an edit about to go to the wrong object.
  const subjectKey = subjectVariable ? String(subject?.id ?? "") : "";
  const [seeded, setSeeded] = useState<string | null>(null);
  if (subjectVariable && subjectKey !== seeded) {
    setSeeded(subjectKey);
    const from = subject?.properties ?? {};
    setValues(
      Object.fromEntries(
        (actionType?.editable_properties ?? []).map((p) => [
          p,
          from[p] === undefined || from[p] === null ? "" : String(from[p]),
        ]),
      ),
    );
  }

  const execute = useMutation({
    mutationFn: () => actionApi.execute(workspaceId, projectId, actionType!.id, instanceId, values),
    onSuccess: async (result) => {
      if (!result.ok) return;
      // Everything reading this object type reads a *set*, and the set is now
      // one write out of date.
      await queryClient.invalidateQueries({ queryKey: ["canvas-widget-instances"] });
      await queryClient.invalidateQueries({ queryKey: ["canvas-object-set"] });
      await queryClient.invalidateQueries({ queryKey: ["canvas-map-set"] });
      await queryClient.invalidateQueries({ queryKey: ["canvas-filter-list"] });
      // And so is the subject variable, which holds the object as it was when
      // it was picked (§84). The widget that changed it is the one place that
      // knows what it now says, so it writes it back rather than leaving a
      // detail panel showing the values you just replaced.
      if (subjectVariable && subject) {
        setParameter(subjectVariable, {
          ...subject,
          properties: { ...(subject.properties ?? {}), ...values },
        });
      }
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
          {subjectVariable ? (
            <p className="canvas-widget-empty">
              {subject?.id
                ? `Editing ${String(subject.primary_key ?? "")}`
                : "Nothing picked yet — select an object to edit it"}
            </p>
          ) : (
            <label className="field">
              <span className="field-label">Record</span>
              <select value={picked} onChange={(e) => setPicked(e.target.value)} disabled={!live}>
                <option value="">Choose…</option>
                {instancesQ.data?.items.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.primary_key}
                  </option>
                ))}
              </select>
            </label>
          )}
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
    subjectVariable,
    actions: { setProp },
  } = useNode((node) => ({
    actionTypeId: node.data.props.actionTypeId,
    subjectVariable: node.data.props.subjectVariable,
  }));
  const { declared } = useCanvasVariables();
  const objects = Object.values(declared).filter((v) => v.kind === "single_object");
  const list = useQuery({
    queryKey: ["action-types", workspaceId],
    queryFn: () => actionApi.listTypes(workspaceId),
  });
  return (
    <>
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
      <label className="field">
        <span className="field-label">Edits</span>
        <select
          value={subjectVariable || ""}
          onChange={(e) =>
            setProp(
              (p: { subjectVariable: string | null }) =>
                (p.subjectVariable = e.target.value || null),
            )
          }
        >
          <option value="">Whatever the viewer picks from a list</option>
          {objects.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label || v.id}
            </option>
          ))}
        </select>
        <span className="field-hint">
          A single-object variable — what a row or pin selection writes
        </span>
      </label>
    </>
  );
}

CanvasActionForm.craft = {
  displayName: "Action form",
  props: { actionTypeId: null, subjectVariable: null },
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

/** Which top-level nodes are overlays rather than pages.
 *
 * Read from the tree, like the page list, rather than passed down: a widget
 * firing a `navigate` has no other way to know whether its target covers the
 * page or replaces it, and a second stored copy of that fact would disagree
 * with the tree the first time somebody changed a node's type.
 */
function useOverlayIds(): Set<string> {
  const { query } = useEditor();
  try {
    const ids = (query.node("ROOT").get().data.nodes ?? []) as string[];
    return new Set(ids.filter((id) => query.node(id).get()?.data?.name === "CanvasOverlay"));
  } catch {
    return new Set();
  }
}

/** The children of a canvas node, one entry per child widget.
 *
 * Craft.js hands a canvas node its children as a *single* Fragment holding one
 * element per child, and `React.Children.toArray` does not look inside a
 * Fragment - so the obvious `toArray(children)` returns a one-element array no
 * matter how many widgets the section contains. A section built on it laid
 * everything out in one column and looked, from the outside, like a section
 * that simply did not work; nothing errored. Unwrap the Fragment, once, here.
 */
function childList(children: React.ReactNode): React.ReactNode[] {
  const top = React.Children.toArray(children);
  const only = top.length === 1 ? top[0] : null;
  if (React.isValidElement(only) && only.type === React.Fragment) {
    return React.Children.toArray((only.props as { children?: React.ReactNode }).children);
  }
  return top;
}

/** A section: the thing that stops an app being one column (roadmap 1.4).
 *
 * Foundry's sections subdivide a page as columns, rows, tabs or toolbars.
 * Columns and rows are here; a tabbed section is the Tabs widget over pages,
 * which is the same idea one level up, and a toolbar is a row with different
 * padding rather than a different concept.
 *
 * **Widths are proportions, not pixels.** A section's children share the space
 * by weight, so a two-column split stays a two-column split on a narrower
 * screen instead of overflowing. Drag-to-resize is a UI affordance over these
 * same numbers and is not built - the numbers are, so an app can be laid out
 * today and the handle can arrive later without a format change.
 *
 * **Below a threshold, columns stack.** A three-column section on a phone is
 * three unreadable columns; the roadmap asks for responsive rules per section
 * type, and for a column section the rule is "stop being columns".
 */
export function CanvasSection({
  direction = "columns",
  weights = "",
  gap = 12,
  visibleWhen = null,
  children,
}: {
  direction?: "columns" | "rows";
  /** A variable that must be truthy for this section to show (roadmap 1.7) -
   * Foundry's own example of the feature, and the reason it lives on the
   * layout nodes rather than on every widget: hiding a section hides what is
   * in it, which is what "this part of the page does not apply yet" means. */
  visibleWhen?: string | null;
  /** Comma-separated proportions, one per child: "2,1" is two-thirds and a
   * third. Blank, or short, means equal - a section should lay out sensibly
   * before anybody has configured it. */
  weights?: string;
  gap?: number;
  children?: React.ReactNode;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { hidden, marker } = useVisibility(visibleWhen);
  const parts = childList(children);
  const parsed = String(weights || "")
    .split(",")
    .map((w) => Number(w.trim()))
    .filter((w) => Number.isFinite(w) && w > 0);

  if (hidden) return null;
  return (
    <div
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-section canvas-section--${direction}`}
    >
      {marker && <p className="canvas-hidden-marker">{marker}</p>}
      {/* A section fills itself with its children, so in the builder there is
          otherwise nowhere to click that is the section rather than a widget
          inside it - and its settings (proportions, direction, gap) would be
          unreachable. The label is that click target, and says what the
          section is doing, the way a page's label does. */}
      {mode === "edit" && (
        <p className="canvas-section-label">
          {direction === "columns" ? "Columns" : "Rows"}
          {parsed.length > 1 ? ` · ${parsed.join(":")}` : ""}
        </p>
      )}
      <div className="canvas-section-parts" style={{ gap }}>
        {parts.map((child, index) => (
          <div
            key={index}
            className="canvas-section-part"
            // `flex-grow` rather than a width: the children then share whatever
            // is left after gaps, so the arithmetic does not have to know how
            // many gaps there are.
            style={{ flexGrow: parsed[index] ?? 1, flexBasis: 0, minWidth: 0 }}
          >
            {child}
          </div>
        ))}
        {parts.length === 0 && (
          <p className="canvas-widget-empty">Section - drop widgets in to split the page</p>
        )}
      </div>
    </div>
  );
}

function SectionSettings() {
  const {
    direction,
    weights,
    gap,
    visibleWhen,
    actions: { setProp },
  } = useNode((node) => ({
    direction: node.data.props.direction,
    weights: node.data.props.weights,
    gap: node.data.props.gap,
    visibleWhen: node.data.props.visibleWhen,
  }));
  return (
    <>
      <VisibilityField
        value={visibleWhen}
        onChange={(next) => setProp((p: { visibleWhen: string | null }) => (p.visibleWhen = next))}
      />
      <label className="field">
        <span className="field-label">Arrange as</span>
        <select
          value={direction ?? "columns"}
          onChange={(e) => setProp((p: { direction: string }) => (p.direction = e.target.value))}
        >
          <option value="columns">Columns</option>
          <option value="rows">Rows</option>
        </select>
      </label>
      <label className="field">
        <span className="field-label">Proportions</span>
        <input
          value={weights ?? ""}
          placeholder="equal"
          onChange={(e) => setProp((p: { weights: string }) => (p.weights = e.target.value))}
        />
        <span className="field-hint">
          One number per widget, e.g. 2,1 for two-thirds and a third
        </span>
      </label>
      <label className="field">
        <span className="field-label">Gap</span>
        <input
          type="number"
          value={gap ?? 12}
          onChange={(e) => setProp((p: { gap: number }) => (p.gap = Number(e.target.value)))}
        />
      </label>
    </>
  );
}

CanvasSection.craft = {
  displayName: "Section",
  props: { direction: "columns", weights: "", gap: 12, visibleWhen: null },
  isCanvas: true,
  related: { settings: SectionSettings },
};

/** The module header (roadmap 1.4).
 *
 * Foundry's persistent toolbar: the module-wide title, the tabs that move
 * between pages, and any buttons that apply to the whole module.
 *
 * **Why this is a node type and a toolbar section is not** (§78 refused that
 * one as "a row with different padding"): a header differs in *behaviour*,
 * not decoration. It is pinned while the page beneath it scrolls, and there
 * is **at most one per module** — a rule the server enforces, because two
 * things both claiming to be the module-wide toolbar is a document nobody can
 * render sensibly.
 *
 * It persists across page changes for a structural reason rather than a
 * special case: it is not inside a page, and only pages hide themselves when
 * another page is showing.
 */
export function CanvasHeader({
  title = "",
  sticky = true,
  children,
}: {
  title?: string;
  sticky?: boolean;
  children?: React.ReactNode;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  // `{{v_id}}` like every other text, so a header can name what the viewer is
  // looking at rather than only what the app is called.
  const { resolved } = useCanvasVariables();
  return (
    <header
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-header${sticky ? " canvas-header--sticky" : ""}`}
    >
      {title.trim() && <p className="canvas-header-title">{interpolate(title, resolved)}</p>}
      {children}
    </header>
  );
}

function HeaderSettings() {
  const {
    title,
    sticky,
    actions: { setProp },
  } = useNode((node) => ({ title: node.data.props.title, sticky: node.data.props.sticky }));
  return (
    <>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          value={title ?? ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
        <span className="field-hint">{"{{v_id}}"} shows a variable&apos;s current value</span>
      </label>
      <label className="field">
        <span className="field-label">Stays put while the page scrolls</span>
        <input
          type="checkbox"
          checked={sticky ?? true}
          onChange={(e) => setProp((p: { sticky: boolean }) => (p.sticky = e.target.checked))}
        />
      </label>
    </>
  );
}

CanvasHeader.craft = {
  displayName: "Header",
  props: { title: "", sticky: true },
  isCanvas: true,
  related: { settings: HeaderSettings },
};

/** A page (roadmap 1.4).
 *
 * A page is a **node in the layout tree**, not a separate document. That keeps
 * decision 0002's "the layout is a Craft.js tree" true, keeps the builder
 * editing one tree, and means the set of pages is *read* from the layout
 * rather than stored beside it — a second copy of that fact would disagree
 * with the first the moment somebody deleted a page.
 *
 * **In the builder every page is visible**, stacked and labelled. Hiding all
 * but one would make the other pages uneditable without a page switcher in the
 * chrome, and would hide from the author that they exist. In the running app
 * exactly one shows.
 */
export function CanvasPage({
  title = "Page",
  children,
}: {
  title?: string;
  children?: React.ReactNode;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { current } = useCanvasPage();
  const { query } = useEditor();

  // No page selected yet means "show the first one". Read from the tree rather
  // than seeded into state at mount: the layout decides which page is first,
  // and a copy of that decision in state would disagree the moment somebody
  // reordered them.
  let active = current === nodeId;
  if (current === null) {
    try {
      const root = query.node("ROOT").get();
      const first = (root.data.nodes ?? []).find(
        (id: string) => query.node(id).get()?.data?.name === "CanvasPage",
      );
      active = first === nodeId;
    } catch {
      active = true; // no tree to ask (a bare render); showing beats blanking
    }
  }

  if (mode === "run" && !active) return null;

  return (
    <section
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-page${active ? " on" : ""}`}
    >
      {mode === "edit" && (
        <p className="canvas-page-label">
          {title}
          {active ? " · shown first" : ""}
        </p>
      )}
      {children}
    </section>
  );
}

function PageSettings() {
  const {
    title,
    actions: { setProp },
  } = useNode((node) => ({ title: node.data.props.title }));
  return (
    <label className="field">
      <span className="field-label">Page title</span>
      <input
        value={title ?? ""}
        onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
      />
      <span className="field-hint">Shown on a Tabs widget</span>
    </label>
  );
}

CanvasPage.craft = {
  displayName: "Page",
  props: { title: "Page" },
  isCanvas: true,
  related: { settings: PageSettings },
};

/** An overlay: a layer over the page rather than a page you go to.
 *
 * Foundry's modals and drawers, for content that should not navigate you away.
 * The same kind of node as a page, so `navigate` targets either and the
 * difference is what the browser does with it - and the difference matters:
 * closing an overlay returns you to the page underneath, which "navigate to
 * a page" has no way to express.
 *
 * **In the builder it renders inline**, like a page, so it is editable and
 * visible. It only becomes a layer in the running app.
 */
export function CanvasOverlay({
  title = "Overlay",
  variant = "modal",
  children,
}: {
  title?: string;
  variant?: "modal" | "drawer";
  children?: React.ReactNode;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { overlay, closeOverlay } = useCanvasPage();
  const open = overlay === nodeId;

  if (mode === "run" && !open) return null;

  const body = (
    <section
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-overlay canvas-overlay--${variant}`}
      role={mode === "run" ? "dialog" : undefined}
      aria-modal={mode === "run" ? true : undefined}
      aria-label={title}
    >
      <div className="canvas-overlay-head">
        <strong>{title}</strong>
        {mode === "run" && (
          <button type="button" className="btn quiet" onClick={closeOverlay}>
            Close
          </button>
        )}
        {mode === "edit" && <span className="soft">overlay</span>}
      </div>
      {children}
    </section>
  );

  if (mode !== "run") return body;
  return (
    // The scrim closes it. An overlay you can only leave through its own
    // button is one a viewer gets stuck in the moment that button is off
    // screen.
    <div className="canvas-scrim" onClick={closeOverlay}>
      <div onClick={(e) => e.stopPropagation()}>{body}</div>
    </div>
  );
}

function OverlaySettings() {
  const {
    title,
    variant,
    actions: { setProp },
  } = useNode((node) => ({ title: node.data.props.title, variant: node.data.props.variant }));
  return (
    <>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          value={title ?? ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Shows as</span>
        <select
          value={variant ?? "modal"}
          onChange={(e) => setProp((p: { variant: string }) => (p.variant = e.target.value))}
        >
          <option value="modal">Modal (centred)</option>
          <option value="drawer">Drawer (from the side)</option>
        </select>
      </label>
    </>
  );
}

CanvasOverlay.craft = {
  displayName: "Overlay",
  props: { title: "Overlay", variant: "modal" },
  isCanvas: true,
  related: { settings: OverlaySettings },
};

/** Tabs: one button per page, navigating through the event system.
 *
 * It does not call `go` directly. A tab click fires the module's `click`
 * events for this widget exactly as a button would, so "what does this tab
 * do" is answered by the same list as every other trigger — and a tab can set
 * a variable on the way if somebody wires one. The common case (a tab per
 * page, navigating to it) is generated by the settings panel rather than
 * hardcoded here.
 */
export function CanvasTabs() {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { query } = useEditor();
  const { current, go } = useCanvasPage();
  const eventContext = useEventContext(undefined, useOverlayIds());
  const { events: moduleEvents } = useCanvasVariables();

  const pages: { id: string; title: string }[] = [];
  try {
    for (const id of query.node("ROOT").get().data.nodes ?? []) {
      const node = query.node(id).get();
      if (node?.data?.name === "CanvasPage") {
        pages.push({ id, title: String(node.data.props.title ?? "Page") });
      }
    }
  } catch {
    /* no tree to ask */
  }
  const activeId = current ?? pages[0]?.id ?? null;

  return (
    <nav
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className="canvas-tabs"
      aria-label="Pages"
    >
      {pages.length === 0 && <span className="canvas-widget-empty">Add a page to this app</span>}
      {pages.map((page) => (
        <button
          key={page.id}
          type="button"
          className={`canvas-tab${page.id === activeId ? " on" : ""}`}
          aria-current={page.id === activeId}
          onClick={() => {
            const wired = eventsFor(moduleEvents, nodeId, "click");
            if (wired.length > 0) {
              runEvents(wired, { ...eventContext,
                                 payload: { page: page.id, title: page.title } });
            }
            // The tab still navigates when nothing is wired. A tab bar that
            // did nothing until somebody configured an event would look
            // broken, and "go to the page this tab is for" is the only thing
            // a tab could reasonably mean.
            go(page.id);
          }}
        >
          {page.title}
        </button>
      ))}
    </nav>
  );
}

CanvasTabs.craft = { displayName: "Tabs", props: {} };

/** A button: the event system's primary trigger surface (roadmap 1.5, and the
 * trigger source 1.3 was missing).
 *
 * **One button is one node, and Foundry's "Button Group" is a row of them in
 * a Section.** A trigger is `(node, on)` — so a group holding several buttons
 * would need a third part naming *which* button, in every event, in the saved
 * format, to express something the layout already expresses. The row is the
 * grouping; the node is the button.
 *
 * **A button with nothing wired to it does nothing, and says so in the
 * builder.** Unlike Tabs, there is no default meaning to fall back on: a tab
 * self-evidently goes to its page, while a button could mean anything. Silence
 * would be indistinguishable from a broken click, so the builder labels it.
 *
 * **`enabledVariable` is what makes it a widget rather than a control.** The
 * rule for every widget in item 1.5 is that it consumes input variables and
 * emits output variables: this one consumes a variable to decide whether it
 * can be pressed at all — "Clear selection", greyed out until something is
 * selected — and emits whatever its events write.
 */
export function CanvasButton({
  label = "Button",
  style = "primary",
  enabledVariable = null,
}: {
  label?: string;
  style?: "primary" | "quiet" | "danger";
  /** A variable that must be truthy for the button to be pressable. Unset
   * means always pressable — an app whose buttons are all dead until somebody
   * declares a variable would look broken. */
  enabledVariable?: string | null;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { resolved, events: moduleEvents } = useCanvasVariables();
  const eventContext = useEventContext(undefined, useOverlayIds());

  const wired = eventsFor(moduleEvents, nodeId, "click");
  const gate = enabledVariable ? resolved[enabledVariable] : undefined;
  // Only an explicitly falsy value disables. `undefined` is "not resolved
  // yet", which must not read as "not allowed" - a button that is dead until
  // the first resolve lands is a button people click twice.
  const disabled =
    mode === "edit" || (!!enabledVariable && gate !== undefined && !gate);

  return (
    <span ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-button-wrap">
      <button
        type="button"
        className={`btn${style === "primary" ? "" : ` ${style}`}`}
        disabled={disabled}
        onClick={() => {
          if (mode === "edit") return;
          if (wired.length > 0) runEvents(wired, eventContext);
        }}
      >
        {interpolate(label ?? "", resolved)}
      </button>
      {mode === "edit" && wired.length === 0 && (
        <span className="canvas-widget-empty"> nothing wired to this click yet</span>
      )}
    </span>
  );
}

function ButtonSettings() {
  const {
    label,
    style,
    enabledVariable,
    actions: { setProp },
  } = useNode((node) => ({
    label: node.data.props.label,
    style: node.data.props.style,
    enabledVariable: node.data.props.enabledVariable,
  }));
  const { declared } = useCanvasVariables();
  return (
    <>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          value={label ?? ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
        <span className="field-hint">{"{{v_id}}"} shows a variable&apos;s current value</span>
      </label>
      <label className="field">
        <span className="field-label">Style</span>
        <select
          value={style ?? "primary"}
          onChange={(e) => setProp((p: { style: string }) => (p.style = e.target.value))}
        >
          <option value="primary">Primary</option>
          <option value="quiet">Quiet</option>
          <option value="danger">Danger</option>
        </select>
      </label>
      <label className="field">
        <span className="field-label">Pressable when</span>
        <select
          value={enabledVariable ?? ""}
          onChange={(e) =>
            setProp(
              (p: { enabledVariable: string | null }) =>
                (p.enabledVariable = e.target.value || null),
            )
          }
        >
          <option value="">Always</option>
          {Object.values(declared).map((v) => (
            <option key={v.id} value={v.id}>
              {v.label || v.id}
            </option>
          ))}
        </select>
        <span className="field-hint">
          The button is greyed out while this variable is empty or false
        </span>
      </label>
    </>
  );
}

CanvasButton.craft = {
  displayName: "Button",
  props: { label: "Button", style: "primary", enabledVariable: null },
  related: { settings: ButtonSettings },
};

export const CANVAS_RESOLVER = {
  CanvasHeader,
  CanvasPage,
  CanvasOverlay,
  CanvasSection,
  CanvasTabs,
  CanvasButton,
  CanvasContainer,
  CanvasText,
  CanvasFilterList,
  CanvasParameterControl,
  CanvasDatasetTable,
  CanvasObjectTable,
  CanvasChart,
  CanvasMap,
  CanvasMetricCard,
  CanvasActionForm,
};

export const PALETTE: { key: keyof typeof CANVAS_RESOLVER; label: string; hint: string }[] = [
  { key: "CanvasHeader", label: "Header", hint: "A toolbar above every page; one per module" },
  { key: "CanvasPage", label: "Page", hint: "A screen of the app; Tabs move between them" },
  { key: "CanvasSection", label: "Section", hint: "Split a page into columns or rows" },
  { key: "CanvasOverlay", label: "Overlay", hint: "A modal or drawer over the page" },
  { key: "CanvasTabs", label: "Tabs", hint: "One button per page" },
  { key: "CanvasButton", label: "Button", hint: "Runs the events wired to its click" },
  { key: "CanvasContainer", label: "Container", hint: "A box to arrange other widgets in" },
  { key: "CanvasText", label: "Text", hint: "A heading or paragraph" },
  { key: "CanvasFilterList", label: "Filter list", hint: "Property filters over an object set, with counts" },
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
