"use client";

/** Canvas widgets - the components a saved app's Craft.js definition is
 * built from. Each reads workspace/project id + edit-vs-run mode from
 * CanvasEnvProvider (never from its own serialised props - the same app
 * renders from more than one route), and reuses the datasets/objects/
 * actions endpoints already built elsewhere; a widget only remembers which
 * dataset/action it's bound to, never a copy of the data itself. */

import { Editor, Frame, useEditor, useNode } from "@craftjs/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  actions as actionApi, ApiError, canvas as canvasApi, datasets as dsApi,
  objects as objApi,
} from "@/lib/api";
import { eventsOf, layoutOf, variablesOf } from "@/lib/workshop-module";
import { VariableBridge } from "./VariableBridge";
import { WidgetSetup } from "./WidgetSetup";
import { StyleFields } from "./StyleFields";
import {
  schemeFor, styleFor, type BorderName, type PaddingName, type StyleProps,
} from "./style";
import { asCollapsed, collapseState } from "./collapse";
import { arrayEntries, pageOf } from "./loop-array";
import {
  canReset, suffixText as suffixTextOf, toDisplay, toStored, type SuffixKind,
} from "./number-input";
import {
  formatOf, MAX_ROWS, MIN_ROWS, rowsOf, settingsOf, TEXT_FORMATS,
  toDisplay as toTextDisplay, toStored as toTextStored,
} from "./text-input";
import {
  chosenOf, columnsOf, DISPLAYS, displayOf, displaysFor, LAYOUTS,
  layoutOf as optionLayoutOf, layoutStyle, MAX_COLUMNS, MIN_COLUMNS, modeOf,
  optionsOf, outputKind, pick, placeholderOf, SELECTIONS,
  selectionOf as pickModeOf, sourceOf,
} from "./string-selector";
import {
  COMMON_ZONES, DATE_FORMATS, DEFAULT_DATE_FORMAT, DEFAULT_PRECISION,
  PRECISIONS, TIME_FORMATS, ZONE_MODES, formatDisplay, fromLocalInput, isZone,
  toLocalInput, zoneLabel, zoneOf, type Precision,
} from "./date-time";
import {
  ALIGNMENTS, alignmentOf, blockAlignment, columnAlignment, parse as parseMarkdown,
  sourceOf as markdownSourceOf, textOf as markdownTextOf,
  type Align, type Block, type Inline,
} from "./markdown";
import {
  autoSelectKey, hasSelection, keysOf, selectionClauses, toggle as toggleKey,
} from "./object-table-selection";
import {
  DEFAULT_LINES, EMPTY_MODES, MAX_LINES, cellStyle, emptyMessageOf, emptyModeOf,
  fillsCellOf, fitColumnsOf, frozenOf, linesOf, narrowHeadersOf, noValueOf,
  rowMinHeight, stickyLefts, wrapOf,
} from "./object-table-display";
import {
  overrideFor, renderWhenEmptyOf, shouldRender, showIconOf, singleOf, titleFor,
} from "./object-set-title";
import {
  LAYOUTS as PROPERTY_LAYOUTS,
  // **Aliased, and the aliases are load-bearing.** `MIN_COLUMNS`/`MAX_COLUMNS`
  // already mean 2 and 8 in this file, from the String Selector's option grid;
  // p.266's are 1 and 6. Without the rename the panel would have offered a
  // minimum of two columns for a widget whose model clamps to one - a
  // typechecking, silently wrong control.
  MAX_COLUMNS as PROPERTY_MAX_COLUMNS, MIN_COLUMNS as PROPERTY_MIN_COLUMNS,
  columnsOf as propertyColumnsOf, gridStyle as propertyGridStyle, hideNullOf,
  layoutOf as propertyLayoutOf, visibleProperties,
} from "./property-list";
import { LayoutTemplatePicker } from "./LayoutTemplatePicker";
import { activeTab, asTabName, tabLabels } from "./tab-selection";
import { CanvasNode } from "./SettingsPanel";
import {
  CanvasHeaderCollapsedContext,
  CanvasParameterProvider,
  useCanvasEnv,
  useHeaderCollapsed,
  useCanvasPage,
  useCanvasParameter,
  useCanvasParameters,
  useCanvasVariable,
  useCanvasVariables,
} from "./context";
import { eventsFor, interpolate, run as runEvents, useEventContext } from "./events";
import { invalidateCanvasReads } from "./refresh";
import { describeSet, selectionOf, useOnScreen, useSetPage } from "./object-set";
import {
  MIN_SHARE, formatWeights, inputTypeFor, parseWeights, pivotClauses, resizeWeights,
  roundWeight, seedActionForm, seriesLabel, seriesPointLabel, type PivotPick,
} from "./pure";
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
import { conditionalStyle } from "@/lib/conditional-format";

/** The grid's own line height, in pixels (`globals.css`, `.data-grid td`).
 * p.224's line count is a multiple of this, so the two have to agree; a test
 * pins the stylesheet to it. */
const LINE_HEIGHT = 18;

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
  border = null,
  visibleWhen = null,
}: {
  children?: React.ReactNode;
  background?: string;
  padding?: number;
  /** p.60's border styles, which "can be configured on sections and widgets".
   * A widget gets no p.62 padding control - that page says "pages and
   * sections" - and this container's own numeric `padding` is older than the
   * style block and keeps its meaning. */
  border?: BorderName | null;
  /** A variable that must be truthy for this box to show (roadmap 1.7). */
  visibleWhen?: string | null;
}) {
  const {
    connectors: { connect, drag },
    childIds,
  } = useNode((node) => ({ childIds: node.data.nodes ?? [] }));
  const { query } = useEditor();
  const { hidden, marker } = useVisibility(visibleWhen);
  // **A vertical header turns this container into a row** (p.47: "on the left
  // of the module"). Decided here rather than by the header, because the thing
  // that has to change is the *parent's* direction and a child cannot set it.
  //
  // Read explicitly rather than with a CSS `:has()` selector: an undefined or
  // unsupported selector is silently nothing, which this repo has already been
  // caught by twice, and the failure would be a header rendered above the page
  // instead of beside it - wrong, but not obviously broken.
  const asideHeader = childIds.some((cid: string) => {
    try {
      const node = query.node(cid).get();
      return node?.data?.name === "CanvasHeader"
        && node.data.props.orientation === "vertical";
    } catch {
      return false;
    }
  });
  if (hidden) return null;
  return (
    <div
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-block${asideHeader ? " canvas-block--aside" : ""}`}
      // p.59-60's rule reaches everything inside, so it is an attribute on the
      // box rather than a colour on each widget: the stylesheet redefines the
      // ink and line tokens beneath it and a widget written years ago inherits
      // legible colours without knowing the feature exists.
      data-scheme={schemeFor({ background })}
      style={{
        ...styleFor({ background, border }),
        // This container's own padding, which predates p.62's scale and is a
        // plain number. Written after the style block so it wins - the two
        // would otherwise both emit `padding` and the order would decide.
        padding: padding ?? 12,
        ...(background ? {} : { background: "transparent" }),
      }}
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

/** The style block bound to one node's props (p.57-62).
 *
 * Three panels need the same four controls writing the same four props, and
 * the only thing that differs between them is which controls p.57-62 offers at
 * that level. Repeating the wiring three times is how one of them ends up
 * writing `customPadding` and the other two not.
 */
function NodeStyleFields({ padding = false, border = false }: {
  padding?: boolean; border?: boolean;
}) {
  const {
    style,
    actions: { setProp },
  } = useNode((node) => ({
    style: {
      background: node.data.props.background,
      padding: node.data.props.padding,
      customPadding: node.data.props.customPadding,
      border: node.data.props.border,
    } as StyleProps,
  }));
  return (
    <StyleFields
      props={style}
      padding={padding}
      border={border}
      set={(key, value) =>
        setProp((p: Record<string, unknown>) => {
          p[key] = value;
        })
      }
    />
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
      {/* p.58's backgrounds and p.60's borders reach widgets; p.62's padding
          scale does not - that page says "pages and sections", and this box's
          own numeric padding below is older and means something else. */}
      <NodeStyleFields border />
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
  props: { background: "", padding: 12, border: null, visibleWhen: null },
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
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, mode } = useCanvasEnv();
  const { set } = useCanvasParameters();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const chosen = useCanvasParameter(variable);
  const { events: moduleEvents } = useCanvasVariables();
  const changed = eventsFor(moduleEvents, nodeId, "change");
  const eventContext = useEventContext(undefined, useOverlayIds());

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
    // Ticking and unticking are both `change` - Foundry's select and deselect
    // on a dropdown. One trigger with the value and whether it is now on, not
    // two triggers every document and every panel would have to know about.
    if (mode === "run" && changed.length > 0) {
      runEvents(changed, {
        ...eventContext,
        payload: { value, property, selected: next.includes(value) ? "true" : "" },
      });
    }
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
  // p.65-67's worked example, in p.65's order: the Object Set that populates
  // the widget, the filter options that set makes answerable, then the Filter
  // Output. p.66 keeps the middle one out of the way until the first is
  // bound - "revealed in more detail once the Object Set is populated".
  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
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
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          value={title ?? ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
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
      </>}
      outputs={<>
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
      </>}
    />
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
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId, mode } = useCanvasEnv();
  const { values, set } = useCanvasParameters();
  const current = name ? values[name] : undefined;

  // The `change` trigger (roadmap 1.3). It was offered by the events panel and
  // accepted by the server from the start, and no widget fired it - so an app
  // author could wire "when this dropdown changes, go to a page", save it, and
  // watch it do nothing. Firing here is what makes the offer true.
  const { events: moduleEvents } = useCanvasVariables();
  const changed = eventsFor(moduleEvents, nodeId, "change");
  const overlayIds = useOverlayIds();
  const eventContext = useEventContext(undefined, overlayIds);
  function choose(next: string | null) {
    set(name, next);
    // `{{value}}` in an effect is what was just chosen. Empty for "All",
    // because that is what it means - not "no event".
    // Not while arranging the page: a `navigate` fired by touching a control
    // in the builder would move the builder off the page being edited.
    if (mode === "run" && changed.length > 0) {
      runEvents(changed, { ...eventContext, payload: { value: next ?? "" } });
    }
  }

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
              onChange={(e) => choose(e.target.value || null)}
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
              onChange={(e) => choose(e.target.value || null)}
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

  // **The widget that is nearly all output.** p.65 splits a widget into what
  // populates it and "the data that is then produced and output by the
  // widget" - and a Filter produces without consuming: its parameter name is
  // what every other widget reads. Its only input is the optional dataset the
  // dropdown's options come from, which is why `requires` is empty: a widget
  // whose configuration waited for an input it may not have is a widget
  // nobody can set up.
  return (
    <WidgetSetup
      outputs={<>
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
      </>}
      configuration={<>
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
      </>}
    />
  );
}

/** **Not in the palette any more** (decision 0011, completed in §205): all four
 * of p.459–468's named input widgets exist, so this is no longer what an author
 * should reach for. It stays in the resolver because saved documents contain it
 * — Craft maps a node's `resolvedName` to a component, and a document naming one
 * the resolver lacks does not degrade, it fails to render. It also keeps the one
 * capability no named widget has: p.461's options are static or from a string
 * array variable, never from a dataset query. */
CanvasParameterControl.craft = {
  displayName: "Filter",
  props: { name: "", label: "Filter", control: "select", datasetId: null, column: null },
  related: { settings: ParameterSettings },
};

// ---- Numeric Input (p.468) ------------------------------------------------------
/** p.468's Numeric Input, the first of decision 0011's named input widgets.
 *
 * The arithmetic is in `number-input.ts` and tested without a browser — which
 * matters most for p.468's percent suffix, where what the viewer types and what
 * the variable holds are different numbers.
 *
 * **The field is uncontrolled while it is being typed into**, and that is not
 * laziness. Driving `value` from the variable on every keystroke means the text
 * is reformatted mid-entry: turn grouping on, type `1234`, and the caret jumps
 * as a comma appears under it. So the text is local state, the variable is
 * written on every recognised value, and the text is re-derived from the
 * variable only when the variable changes from somewhere else.
 */
export function CanvasNumericInput({
  name = "",
  label = "",
  grouping = false,
  allowReset = false,
  prefix = "",
  suffix = "none",
  suffixText: suffixLabel = "",
}: {
  name?: string;
  label?: string;
  grouping?: boolean;
  allowReset?: boolean;
  prefix?: string;
  suffix?: SuffixKind;
  suffixText?: string;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { values, set } = useCanvasParameters();
  const stored = name ? values[name] : undefined;
  const format = useMemo(() => ({ grouping, suffix }), [grouping, suffix]);

  // The text the field shows. Seeded from the variable and re-seeded whenever
  // the variable changes underneath - an event, another widget, a recompute -
  // but not on our own writes, which is what `settled` compares against.
  const settled = toDisplay(stored, format);
  const [text, setText] = useState(settled);
  const [lastSeen, setLastSeen] = useState(settled);
  if (settled !== lastSeen) {
    setLastSeen(settled);
    setText(settled);
  }

  const { events: moduleEvents } = useCanvasVariables();
  const changed = eventsFor(moduleEvents, nodeId, "change");
  const overlayIds = useOverlayIds();
  const eventContext = useEventContext(undefined, overlayIds);

  function write(next: string) {
    setText(next);
    const value = toStored(next, format);
    // `undefined` is "still typing" and writes nothing - see `number-input.ts`.
    if (value === undefined) return;
    setLastSeen(toDisplay(value, format));
    set(name, value);
    // Not while arranging the page: an event fired by touching a control in
    // the builder would move the builder off the page being edited.
    if (mode === "run" && changed.length > 0) {
      runEvents(changed, { ...eventContext, payload: { value: value === null ? "" : String(value) } });
    }
  }

  const unit = suffixTextOf(format, suffixLabel);
  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!name ? (
        <p className="canvas-widget-empty">
          Numeric input - bind a number variable in Settings
        </p>
      ) : (
        <label className="field canvas-number" style={{ maxWidth: 320 }}>
          {label && <span className="field-label">{label}</span>}
          <span className="canvas-number-row">
            {prefix.trim() && (
              <span className="canvas-number-affix" aria-hidden="true">{prefix.trim()}</span>
            )}
            <input
              // `text`, not `number`: a number input hides what was typed when
              // the browser considers it invalid, so `toStored`'s "still
              // typing" state would be invisible to it - and p.468's grouping
              // separators are not valid in one at all.
              type="text"
              inputMode="decimal"
              aria-label={label || "Numeric input"}
              data-testid="numeric-input"
              value={text}
              onChange={(e) => write(e.target.value)}
            />
            {unit && (
              <span className="canvas-number-affix" aria-hidden="true">{unit}</span>
            )}
            {allowReset && canReset(stored) && (
              <button
                type="button"
                className="btn quiet canvas-number-reset"
                data-testid="numeric-reset"
                onClick={() => write("")}
              >
                Clear
              </button>
            )}
          </span>
        </label>
      )}
    </div>
  );
}

function NumericInputSettings() {
  const {
    name, label, grouping, allowReset, prefix, suffix, suffixText: suffixLabel,
    actions: { setProp },
  } = useNode((node) => ({
    name: node.data.props.name,
    label: node.data.props.label,
    grouping: node.data.props.grouping,
    allowReset: node.data.props.allowReset,
    prefix: node.data.props.prefix,
    suffix: node.data.props.suffix,
    suffixText: node.data.props.suffixText,
  }));
  const { declared } = useCanvasVariables();
  // p.468's "Numeric value" output. Only `number` variables are offered: the
  // widget writes a number, and binding it to a string would produce a
  // document the server accepts and a value nothing downstream can use.
  const numbers = Object.values(declared).filter((v) => v.kind === "number");

  return (
    <WidgetSetup
      outputs={<>
      <label className="field">
        <span className="field-label">Numeric value</span>
        <select
          value={name || ""}
          data-testid="numeric-variable"
          onChange={(e) => setProp((p: { name: string }) => (p.name = e.target.value))}
        >
          <option value="">Choose…</option>
          {numbers.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {numbers.length === 0
            ? "Declare a number variable in the Variables panel first"
            : "Where the number the viewer types is stored"}
        </span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          type="text"
          value={label || ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={!!grouping}
          data-testid="numeric-grouping"
          onChange={(e) => setProp((p: { grouping: boolean }) => (p.grouping = e.target.checked))}
        />
        <span className="field-label">Show grouping</span>
        <span className="field-hint">A comma every three digits</span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={!!allowReset}
          data-testid="numeric-allow-reset"
          onChange={(e) => setProp((p: { allowReset: boolean }) => (p.allowReset = e.target.checked))}
        />
        <span className="field-label">Include option to reset</span>
      </label>
      <label className="field">
        <span className="field-label">Unit prefix</span>
        <input
          type="text"
          value={prefix || ""}
          placeholder="$"
          data-testid="numeric-prefix"
          onChange={(e) => setProp((p: { prefix: string }) => (p.prefix = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Unit suffix</span>
        <select
          value={suffix || "none"}
          data-testid="numeric-suffix"
          onChange={(e) => setProp((p: { suffix: string }) => (p.suffix = e.target.value))}
        >
          <option value="none">None</option>
          <option value="text">Text</option>
          <option value="percent">Percent sign</option>
        </select>
        {/* p.468 is explicit that this is not a display option, so it is said
            here rather than discovered by an author whose numbers are all a
            hundred times too small. */}
        {suffix === "percent" && (
          <span className="field-hint">
            The variable holds what was typed divided by 100 — typing 25 stores 0.25
          </span>
        )}
      </label>
      {suffix === "text" && (
        <label className="field">
          <span className="field-label">Suffix text</span>
          <input
            type="text"
            value={suffixLabel || ""}
            placeholder="kg"
            data-testid="numeric-suffix-text"
            onChange={(e) => setProp((p: { suffixText: string }) => (p.suffixText = e.target.value))}
          />
        </label>
      )}
      </>}
    />
  );
}

CanvasNumericInput.craft = {
  displayName: "Numeric input",
  props: {
    name: "", label: "", grouping: false, allowReset: false,
    prefix: "", suffix: "none", suffixText: "",
  },
  related: { settings: NumericInputSettings },
};

// ---- Text Input (p.465) ---------------------------------------------------------
/** p.465's Text Input, decision 0011's second named input widget.
 *
 * Which settings each format has is in `text-input.ts` and tested without a
 * browser — including the rule that makes the asymmetry more than editorial:
 * **enter submits on a single line and not in a text area**, because in a text
 * area the enter key inserts a newline and a widget that also fired an event on
 * it would be fighting the person typing.
 *
 * Uncontrolled while being typed into, for §202's reason: the variable is
 * written on every keystroke, and the text is re-derived from the variable only
 * when it changes from somewhere else.
 */
export function CanvasTextInput({
  name = "",
  label = "",
  placeholder = "",
  format = "line",
  rows = 4,
}: {
  name?: string;
  label?: string;
  placeholder?: string;
  format?: string;
  rows?: number;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { values, set } = useCanvasParameters();
  const stored = name ? values[name] : undefined;
  const shape = settingsOf(format);

  const settled = toTextDisplay(stored);
  const [text, setText] = useState(settled);
  const [lastSeen, setLastSeen] = useState(settled);
  if (settled !== lastSeen) {
    setLastSeen(settled);
    setText(settled);
  }

  const { events: moduleEvents } = useCanvasVariables();
  const changed = eventsFor(moduleEvents, nodeId, "change");
  const submitted = eventsFor(moduleEvents, nodeId, "submit");
  const overlayIds = useOverlayIds();
  const eventContext = useEventContext(undefined, overlayIds);

  function write(next: string) {
    setText(next);
    const value = toTextStored(next);
    setLastSeen(toTextDisplay(value));
    set(name, value);
    if (mode === "run" && changed.length > 0) {
      runEvents(changed, { ...eventContext, payload: { value: next } });
    }
  }

  /** p.465's "Event on enter". Asked of the catalogue rather than compared
   * against `"line"` here — a second place that knows which formats submit is
   * a second place to get it wrong when Markdown lands. */
  function keyDown(e: React.KeyboardEvent) {
    if (e.key !== "Enter" || !shape.submitsOnEnter) return;
    // Stopped so the keypress does not also reach a form or a parent handler
    // that would do something else with it.
    e.preventDefault();
    if (mode === "run" && submitted.length > 0) {
      runEvents(submitted, { ...eventContext, payload: { value: text } });
    }
  }

  const shared = {
    "aria-label": label || "Text input",
    "data-testid": "text-input",
    value: text,
    placeholder,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      write(e.target.value),
    onKeyDown: keyDown,
  };
  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!name ? (
        <p className="canvas-widget-empty">
          Text input - bind a string variable in Settings
        </p>
      ) : (
        <label className="field" style={{ maxWidth: 420 }}>
          {label && <span className="field-label">{label}</span>}
          {shape.multiline
            ? <textarea {...shared} rows={rowsOf(rows)} />
            : <input type="text" {...shared} />}
        </label>
      )}
    </div>
  );
}

function TextInputSettings() {
  const {
    name, label, placeholder, format, rows,
    actions: { setProp },
  } = useNode((node) => ({
    name: node.data.props.name,
    label: node.data.props.label,
    placeholder: node.data.props.placeholder,
    format: node.data.props.format,
    rows: node.data.props.rows,
  }));
  const { declared } = useCanvasVariables();
  // p.465's "String value" output.
  const strings = Object.values(declared).filter((v) => v.kind === "string");
  const shape = settingsOf(format);

  return (
    <WidgetSetup
      outputs={<>
      <label className="field">
        <span className="field-label">String value</span>
        <select
          value={name || ""}
          data-testid="text-variable"
          onChange={(e) => setProp((p: { name: string }) => (p.name = e.target.value))}
        >
          <option value="">Choose…</option>
          {strings.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {strings.length === 0
            ? "Declare a string variable in the Variables panel first"
            : "Where the text the viewer types is stored"}
        </span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          type="text"
          value={label || ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Placeholder</span>
        <input
          type="text"
          value={placeholder || ""}
          data-testid="text-placeholder"
          onChange={(e) =>
            setProp((p: { placeholder: string }) => (p.placeholder = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Format</span>
        <select
          value={formatOf(format)}
          data-testid="text-format"
          onChange={(e) => setProp((p: { format: string }) => (p.format = e.target.value))}
        >
          {/* Rendered from the catalogue, so an option can never name a format
              the widget does not draw - and p.466's Markdown editor stays out
              until it exists. */}
          {Object.entries(TEXT_FORMATS).map(([key, f]) => (
            <option key={key} value={key}>{f.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {shape.submitsOnEnter
            ? "Enter fires this widget's Submitted events"
            : "Enter inserts a new line, so there is no Submitted event here"}
        </span>
      </label>
      {shape.hasHeight && (
        <label className="field">
          <span className="field-label">Initial height</span>
          <input
            type="number"
            min={MIN_ROWS}
            max={MAX_ROWS}
            value={rowsOf(rows)}
            data-testid="text-rows"
            onChange={(e) => setProp((p: { rows: number }) => (p.rows = Number(e.target.value)))}
          />
          <span className="field-hint">In rows, so it scales with the viewer&apos;s text</span>
        </label>
      )}
      </>}
    />
  );
}

CanvasTextInput.craft = {
  displayName: "Text input",
  props: { name: "", label: "", placeholder: "", format: "line", rows: 4 },
  related: { settings: TextInputSettings },
};

// ---- String Selector (p.459-461) ------------------------------------------------
/** p.461's String Selector, decision 0011's third named input widget.
 *
 * The selection/display matrix, the option list and what a pick means are all
 * in `string-selector.ts` and tested without a browser. What is here is the
 * four render arms and the panel.
 *
 * **Nothing branches on the raw props.** Every read goes through `displayOf` /
 * `modeOf`, so a document naming a pair p.461 does not have - `multiple` with
 * `radio`, which is one click in the panel away - draws something that can
 * express the value rather than radio buttons over a list.
 */
export function CanvasStringSelector({
  name = "",
  label = "",
  selection = "single",
  display = "dropdown",
  optionSource = "static",
  options: staticOptions = [],
  optionsVariable = "",
  placeholder = "",
  allowClearing = true,
  layout = "vertical",
  columns = 3,
}: {
  name?: string;
  label?: string;
  selection?: string;
  display?: string;
  optionSource?: string;
  options?: string[];
  optionsVariable?: string;
  placeholder?: string;
  allowClearing?: boolean;
  layout?: string;
  columns?: number;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { values, set } = useCanvasParameters();
  const { resolved, events: moduleEvents } = useCanvasVariables();

  const shown = displayOf(selection, display);
  const shape = modeOf(selection, display);
  const stored = name ? values[name] : undefined;
  const chosen = chosenOf(selection, stored);
  const options = optionsOf(
    optionSource, staticOptions, optionsVariable ? resolved[optionsVariable] : undefined,
  );

  const changed = eventsFor(moduleEvents, nodeId, "change");
  const overlayIds = useOverlayIds();
  const eventContext = useEventContext(undefined, overlayIds);

  function choose(option: string) {
    const next = pick(selection, stored, option);
    set(name, next);
    if (mode === "run" && changed.length > 0) {
      runEvents(changed, {
        ...eventContext,
        payload: { value: Array.isArray(next) ? next.join(", ") : next ?? "" },
      });
    }
  }

  const text = placeholderOf(selection, display, placeholder);
  const listId = `sel-${nodeId}`;
  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!name ? (
        <p className="canvas-widget-empty">
          String selector - bind a {outputKind(selection)} variable in Settings
        </p>
      ) : (
        <div className="field canvas-selector" style={{ maxWidth: 420 }}>
          {label && <span className="field-label">{label}</span>}

          {shown === "dropdown" && pickModeOf(selection) === "single" && (
            <select
              aria-label={label || "String selector"}
              data-testid="selector-dropdown"
              value={chosen[0] ?? ""}
              onChange={(e) => set(name, e.target.value || null)}
            >
              {/* p.461's "Disable clearing of the selected dropdown option":
                  the empty row *is* the clearing affordance, so forbidding one
                  removes the other. */}
              {(allowClearing || chosen.length === 0) && <option value="">{text}</option>}
              {options.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          )}

          {shown === "dropdown" && pickModeOf(selection) === "multiple" && (
            // p.461's multiple dropdown. A native `<select multiple>` rather
            // than a token field: it is the control a browser already gives
            // keyboard and screen-reader support for, and a hand-rolled one
            // would be a second thing to get those right in.
            <select
              multiple
              aria-label={label || "String selector"}
              data-testid="selector-dropdown"
              size={Math.min(6, Math.max(2, options.length))}
              value={chosen}
              onChange={(e) =>
                set(name, [...e.target.selectedOptions].map((o) => o.value))}
            >
              {options.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          )}

          {shape.hasLayout && (
            <div
              className="canvas-selector-options"
              data-testid="selector-options"
              style={layoutStyle(layout, columns)}
              role={shown === "radio" ? "radiogroup" : "group"}
              aria-label={label || "String selector"}
            >
              {options.map((o) => (
                <label key={o} className="canvas-selector-option">
                  <input
                    type={shown === "radio" ? "radio" : "checkbox"}
                    name={listId}
                    value={o}
                    checked={chosen.includes(o)}
                    onChange={() => choose(o)}
                  />
                  <span>{o}</span>
                </label>
              ))}
            </div>
          )}

          {options.length === 0 && (
            <span className="field-hint">
              {sourceOf(optionSource) === "dynamic"
                ? "No options yet — the array variable this reads is empty"
                : "No options yet — add some in Settings"}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function StringSelectorSettings() {
  const {
    name, label, selection, display, optionSource, options, optionsVariable,
    placeholder, allowClearing, layout, columns,
    actions: { setProp },
  } = useNode((node) => ({
    name: node.data.props.name,
    label: node.data.props.label,
    selection: node.data.props.selection,
    display: node.data.props.display,
    optionSource: node.data.props.optionSource,
    options: node.data.props.options,
    optionsVariable: node.data.props.optionsVariable,
    placeholder: node.data.props.placeholder,
    allowClearing: node.data.props.allowClearing,
    layout: node.data.props.layout,
    columns: node.data.props.columns,
  }));
  const { declared } = useCanvasVariables();
  const kind = outputKind(selection);
  // p.461's "the output variable will be a string variable… will be a string
  // array variable" - so which variables are offered *depends on the
  // selection*, and changing it invalidates the binding below.
  const targets = Object.values(declared).filter((v) => v.kind === kind);
  const arrays = Object.values(declared).filter((v) => v.kind === "array");
  const shape = modeOf(selection, display);
  const list: string[] = Array.isArray(options) ? options : [];

  return (
    <WidgetSetup
      outputs={<>
      <label className="field">
        <span className="field-label">Selected value</span>
        <select
          value={name || ""}
          data-testid="selector-variable"
          onChange={(e) => setProp((p: { name: string }) => (p.name = e.target.value))}
        >
          <option value="">Choose…</option>
          {targets.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {targets.length === 0
            ? `Declare a ${kind} variable in the Variables panel first`
            : `A ${kind} variable, because the selection is ${SELECTIONS[pickModeOf(selection)].label.toLowerCase()}`}
        </span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          type="text"
          value={label || ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Selection</span>
        <select
          value={pickModeOf(selection)}
          data-testid="selector-selection"
          onChange={(e) =>
            setProp((p: {
              selection: string; display: string; name: string;
            }) => {
              p.selection = e.target.value;
              // **Both are cleared, and neither is optional.** The display may
              // not exist under the new selection (p.461 gives radio buttons to
              // Single and checkboxes to Multiple), and the bound variable is
              // now the wrong *kind* - so keeping it would save a document the
              // server refuses, naming a widget the author did not touch.
              p.display = displayOf(e.target.value, undefined);
              p.name = "";
            })}
        >
          {Object.entries(SELECTIONS).map(([key, s]) => (
            <option key={key} value={key}>{s.label}</option>
          ))}
        </select>
        <span className="field-hint">Changing this clears the bound variable — the kind differs</span>
      </label>
      <label className="field">
        <span className="field-label">Display as</span>
        <select
          value={displayOf(selection, display)}
          data-testid="selector-display"
          onChange={(e) => setProp((p: { display: string }) => (p.display = e.target.value))}
        >
          {displaysFor(selection).map((d) => (
            <option key={d} value={d}>
              {DISPLAYS[pickModeOf(selection)][d]!.label}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span className="field-label">Options from</span>
        <select
          value={sourceOf(optionSource)}
          data-testid="selector-source"
          onChange={(e) =>
            setProp((p: { optionSource: string }) => (p.optionSource = e.target.value))}
        >
          <option value="static">A list I type</option>
          <option value="dynamic">A string array variable</option>
        </select>
      </label>
      {sourceOf(optionSource) === "dynamic" ? (
        <label className="field">
          <span className="field-label">Options variable</span>
          <select
            value={optionsVariable || ""}
            data-testid="selector-options-variable"
            onChange={(e) =>
              setProp((p: { optionsVariable: string }) => (p.optionsVariable = e.target.value))}
          >
            <option value="">Choose…</option>
            {arrays.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
        </label>
      ) : (
        <label className="field">
          <span className="field-label">Options</span>
          {/* One per line, which is the shortest thing that also lets p.461's
              "reorder option values" happen by editing. A row of inputs with
              up/down buttons is more chrome for the same edit. */}
          <textarea
            rows={4}
            value={list.join("\n")}
            data-testid="selector-options-list"
            onChange={(e) =>
              setProp((p: { options: string[] }) => (p.options = e.target.value.split("\n")))}
          />
          <span className="field-hint">One per line, in the order they appear</span>
        </label>
      )}

      {shape.placeholder !== null && (
        <label className="field">
          <span className="field-label">Placeholder</span>
          <input
            type="text"
            value={placeholder || ""}
            placeholder={shape.placeholder}
            data-testid="selector-placeholder"
            onChange={(e) =>
              setProp((p: { placeholder: string }) => (p.placeholder = e.target.value))}
          />
        </label>
      )}
      {shape.hasClearing && (
        <label className="field canvas-toggle">
          <input
            type="checkbox"
            checked={allowClearing !== false}
            data-testid="selector-allow-clearing"
            onChange={(e) =>
              setProp((p: { allowClearing: boolean }) => (p.allowClearing = e.target.checked))}
          />
          <span className="field-label">Allow clearing the selection</span>
        </label>
      )}
      {shape.hasLayout && (
        <>
          <label className="field">
            <span className="field-label">Layout</span>
            <select
              value={optionLayoutOf(layout)}
              data-testid="selector-layout"
              onChange={(e) => setProp((p: { layout: string }) => (p.layout = e.target.value))}
            >
              {Object.entries(LAYOUTS).map(([key, l]) => (
                <option key={key} value={key}>{l}</option>
              ))}
            </select>
          </label>
          {optionLayoutOf(layout) === "grid" && (
            <label className="field">
              <span className="field-label">Columns</span>
              <input
                type="number"
                min={MIN_COLUMNS}
                max={MAX_COLUMNS}
                value={columnsOf(columns)}
                data-testid="selector-columns"
                onChange={(e) =>
                  setProp((p: { columns: number }) => (p.columns = Number(e.target.value)))}
              />
            </label>
          )}
        </>
      )}
      </>}
    />
  );
}

CanvasStringSelector.craft = {
  displayName: "String selector",
  props: {
    name: "", label: "", selection: "single", display: "dropdown",
    optionSource: "static", options: [], optionsVariable: "",
    placeholder: "", allowClearing: true, layout: "vertical", columns: 3,
  },
  related: { settings: StringSelectorSettings },
};

// ---- Date and Time Picker (p.463-464) -------------------------------------------
/** p.463-464's Date and Time Picker, decision 0011's fourth and last named
 * input widget.
 *
 * Everything about instants and zones is in `date-time.ts` and tested without a
 * browser. **The rule this widget exists to keep** is that the zone changes how
 * the value is read and written and never what the variable holds — the mirror
 * of p.468's percent suffix, and the inversion is why both needed splitting out.
 *
 * The control is one `<input type="datetime-local">` whose value is the wall
 * clock *in the chosen zone*, with `step` from the precision — which is also
 * what makes the browser show the seconds and milliseconds boxes.
 */
export function CanvasDateTimePicker({
  name = "",
  label = "",
  dateFormat = "iso",
  timeFormat = "h24",
  precision = "minute",
  zoneMode = "local",
  timezone = "UTC",
  timezoneVariable = "",
  zoneEditable = false,
}: {
  name?: string;
  label?: string;
  dateFormat?: string;
  timeFormat?: string;
  precision?: string;
  zoneMode?: string;
  timezone?: string;
  timezoneVariable?: string;
  zoneEditable?: boolean;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { values, set } = useCanvasParameters();
  const { resolved, events: moduleEvents } = useCanvasVariables();

  const shape = PRECISIONS[precision as Precision] ?? PRECISIONS[DEFAULT_PRECISION];
  const step = shape.step;
  const grain = (Object.hasOwn(PRECISIONS, precision) ? precision : DEFAULT_PRECISION) as Precision;
  const configured = zoneOf(
    zoneMode, timezone, timezoneVariable ? resolved[timezoneVariable] : undefined,
  );
  // p.464's "Timezone user editable". The viewer's choice lives here rather
  // than in a variable: it changes how *this* reader sees the value, and
  // writing it to the document would change it for everybody.
  const [chosenZone, setChosenZone] = useState<string | null>(null);
  const zone = zoneEditable && chosenZone && isZone(chosenZone) ? chosenZone : configured;

  const stored = name ? values[name] : undefined;
  const shown = toLocalInput(stored, zone, grain);

  const changed = eventsFor(moduleEvents, nodeId, "change");
  const overlayIds = useOverlayIds();
  const eventContext = useEventContext(undefined, overlayIds);

  function write(text: string) {
    const instant = fromLocalInput(text, zone, grain);
    set(name, instant);
    if (mode === "run" && changed.length > 0) {
      runEvents(changed, { ...eventContext, payload: { value: instant ?? "" } });
    }
  }

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!name ? (
        <p className="canvas-widget-empty">
          Date and time - bind a timestamp variable in Settings
        </p>
      ) : (
        <div className="field canvas-datetime" style={{ maxWidth: 420 }}>
          {label && <span className="field-label">{label}</span>}
          <input
            type="datetime-local"
            aria-label={label || "Date and time"}
            data-testid="datetime-input"
            step={step}
            value={shown}
            onChange={(e) => write(e.target.value)}
          />
          {zoneEditable ? (
            <select
              aria-label="Timezone"
              data-testid="datetime-zone"
              value={zone}
              onChange={(e) => setChosenZone(e.target.value)}
            >
              {/* The configured zone is always present, even when it is not one
                  of the common ones - otherwise a module pinned to a zone this
                  list omits would silently move the viewer somewhere else. */}
              {[...new Set([configured, ...COMMON_ZONES])].map((z) => (
                <option key={z} value={z}>{zoneLabel(z, stored)}</option>
              ))}
            </select>
          ) : (
            // **Named even when it cannot be changed.** Two viewers in
            // different zones otherwise see different times in a field that
            // looks identical, and neither can tell why.
            <span className="field-hint" data-testid="datetime-zone-label">
              {zoneLabel(zone, stored)}
            </span>
          )}
          {shown && (
            <span className="field-hint" data-testid="datetime-display">
              {formatDisplay(stored, zone, dateFormat, timeFormat, grain)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function DateTimePickerSettings() {
  const {
    name, label, dateFormat, timeFormat, precision, zoneMode, timezone,
    timezoneVariable, zoneEditable,
    actions: { setProp },
  } = useNode((node) => ({
    name: node.data.props.name,
    label: node.data.props.label,
    dateFormat: node.data.props.dateFormat,
    timeFormat: node.data.props.timeFormat,
    precision: node.data.props.precision,
    zoneMode: node.data.props.zoneMode,
    timezone: node.data.props.timezone,
    timezoneVariable: node.data.props.timezoneVariable,
    zoneEditable: node.data.props.zoneEditable,
  }));
  const { declared } = useCanvasVariables();
  // p.463's "Selected timestamp" output.
  const timestamps = Object.values(declared).filter((v) => v.kind === "timestamp");
  const strings = Object.values(declared).filter((v) => v.kind === "string");

  return (
    <WidgetSetup
      outputs={<>
      <label className="field">
        <span className="field-label">Selected timestamp</span>
        <select
          value={name || ""}
          data-testid="datetime-variable"
          onChange={(e) => setProp((p: { name: string }) => (p.name = e.target.value))}
        >
          <option value="">Choose…</option>
          {timestamps.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {timestamps.length === 0
            ? "Declare a timestamp variable in the Variables panel first"
            : "Holds the instant, not the wall clock — the timezone below only changes how it reads"}
        </span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          type="text"
          value={label || ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Date format</span>
        <select
          value={dateFormat || DEFAULT_DATE_FORMAT}
          data-testid="datetime-date-format"
          onChange={(e) => setProp((p: { dateFormat: string }) => (p.dateFormat = e.target.value))}
        >
          {Object.entries(DATE_FORMATS).map(([key, f]) => (
            <option key={key} value={key}>{f.label}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Time format</span>
        <select
          value={timeFormat || "h24"}
          data-testid="datetime-time-format"
          onChange={(e) => setProp((p: { timeFormat: string }) => (p.timeFormat = e.target.value))}
        >
          {Object.entries(TIME_FORMATS).map(([key, l]) => (
            <option key={key} value={key}>{l}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Time precision</span>
        <select
          value={precision || DEFAULT_PRECISION}
          data-testid="datetime-precision"
          onChange={(e) => setProp((p: { precision: string }) => (p.precision = e.target.value))}
        >
          {Object.entries(PRECISIONS).map(([key, p]) => (
            <option key={key} value={key}>{p.label}</option>
          ))}
        </select>
        <span className="field-hint">Anything finer is dropped from the stored value, not just hidden</span>
      </label>
      <label className="field">
        <span className="field-label">Default timezone</span>
        <select
          value={zoneMode || "local"}
          data-testid="datetime-zone-mode"
          onChange={(e) => setProp((p: { zoneMode: string }) => (p.zoneMode = e.target.value))}
        >
          {Object.entries(ZONE_MODES).map(([key, l]) => (
            <option key={key} value={key}>{l}</option>
          ))}
        </select>
      </label>
      {zoneMode === "fixed" && (
        <label className="field">
          <span className="field-label">Timezone</span>
          <select
            value={timezone || "UTC"}
            data-testid="datetime-timezone"
            onChange={(e) => setProp((p: { timezone: string }) => (p.timezone = e.target.value))}
          >
            {COMMON_ZONES.map((z) => (
              <option key={z} value={z}>{z}</option>
            ))}
          </select>
        </label>
      )}
      {zoneMode === "variable" && (
        <label className="field">
          <span className="field-label">Timezone variable</span>
          <select
            value={timezoneVariable || ""}
            data-testid="datetime-timezone-variable"
            onChange={(e) =>
              setProp((p: { timezoneVariable: string }) => (p.timezoneVariable = e.target.value))}
          >
            <option value="">Choose…</option>
            {strings.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
          <span className="field-hint">
            An IANA name like Europe/London. Anything else falls back to the viewer&apos;s own zone
          </span>
        </label>
      )}
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={!!zoneEditable}
          data-testid="datetime-zone-editable"
          onChange={(e) =>
            setProp((p: { zoneEditable: boolean }) => (p.zoneEditable = e.target.checked))}
        />
        <span className="field-label">Timezone user editable</span>
        <span className="field-hint">Changes what this reader sees, never the stored instant</span>
      </label>
      </>}
    />
  );
}

CanvasDateTimePicker.craft = {
  displayName: "Date and time",
  props: {
    name: "", label: "", dateFormat: "iso", timeFormat: "h24",
    precision: "minute", zoneMode: "local", timezone: "UTC",
    timezoneVariable: "", zoneEditable: false,
  },
  related: { settings: DateTimePickerSettings },
};

// ---- Markdown -------------------------------------------------------------------
/** p.314-319's Markdown widget.
 *
 * The parsing, the URL rule and p.317's two alignment precedences all live in
 * `markdown.ts` and are tested without a browser. What is here is the part that
 * has to be React: turning the tree into elements.
 *
 * **There is no `dangerouslySetInnerHTML` in this file, and that is the design
 * rather than an accident.** `parseMarkdown` returns plain objects, so every
 * string below reaches the DOM as a text child, which React escapes. Raw HTML
 * an author typed is shown as the characters they typed.
 */
function renderInline(nodes: Inline[]): React.ReactNode {
  return nodes.map((node, index) => {
    switch (node.kind) {
      case "text":
        return <React.Fragment key={index}>{node.text}</React.Fragment>;
      case "code":
        return <code key={index}>{node.text}</code>;
      case "strong":
        return <strong key={index}>{renderInline(node.children)}</strong>;
      case "em":
        return <em key={index}>{renderInline(node.children)}</em>;
      case "del":
        return <del key={index}>{renderInline(node.children)}</del>;
      case "mark":
        return <mark key={index}>{renderInline(node.children)}</mark>;
      case "break":
        return <br key={index} />;
      case "link":
        // `noreferrer` as well as `noopener`: an app's Markdown is written by
        // one person and read by the workspace, and the reader did not choose
        // to tell the destination where they came from.
        return (
          <a key={index} href={node.href} target="_blank" rel="noreferrer noopener">
            {renderInline(node.children)}
          </a>
        );
      case "image":
        return <img key={index} src={node.src} alt={node.alt} />;
    }
  });
}

function renderBlock(block: Block, key: number, widget: Align): React.ReactNode {
  // p.317's "Code blocks remain left-aligned and full-width regardless of the
  // selected alignment", decided in the model rather than here.
  const style = { textAlign: blockAlignment(block, widget) } as React.CSSProperties;
  switch (block.kind) {
    case "heading":
      return React.createElement(
        `h${block.level}`,
        { key, style, className: "canvas-markdown-heading" },
        renderInline(block.children),
      );
    case "paragraph":
      return <p key={key} style={style}>{renderInline(block.children)}</p>;
    case "code":
      // **The style is applied here too, and that is the point.** Leaving it off
      // let the browser compute `start`, which looks left-aligned and is only
      // left-aligned by inheritance - so `blockAlignment`'s answer for the one
      // block kind it exists for was computed and thrown away, and any future
      // rule setting `text-align` on the container would have taken code blocks
      // with it. The browser suite caught it as `start` != `left`.
      return (
        <pre key={key} style={style} className="canvas-markdown-code">
          <code>{block.text}</code>
        </pre>
      );
    case "rule":
      return <hr key={key} />;
    case "quote":
      return (
        <blockquote key={key} className="canvas-markdown-quote">
          {block.blocks.map((b, i) => renderBlock(b, i, widget))}
        </blockquote>
      );
    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag key={key} style={style} className="canvas-markdown-list">
          {block.items.map((item, i) => (
            <li key={i} className={item.done === undefined ? undefined : "canvas-markdown-task"}>
              {item.done !== undefined && (
                // Shown, and not editable: p.318 lists a task list as a
                // *syntax*, so the tick is what the author wrote. A checkbox a
                // viewer could clear would be a control with nowhere to put the
                // answer.
                <input type="checkbox" checked={item.done} readOnly disabled />
              )}
              {renderInline(item.children)}
            </li>
          ))}
        </Tag>
      );
    }
    case "table":
      return (
        <table key={key} className="canvas-markdown-table">
          <thead>
            <tr>
              {block.head.map((cell, i) => (
                <th key={i} style={{ textAlign: columnAlignment(block.align[i] ?? null, widget) }}>
                  {renderInline(cell)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, i) => (
                  <td key={i} style={{ textAlign: columnAlignment(block.align[i] ?? null, widget) }}>
                    {renderInline(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
  }
}

export function CanvasMarkdown({
  source = "text",
  text = "",
  textVariable = "",
  monospace = false,
  scrolling = false,
  wordWrap = true,
  breaks = true,
  alignment = "left",
}: {
  source?: string;
  text?: string;
  textVariable?: string;
  monospace?: boolean;
  scrolling?: boolean;
  wordWrap?: boolean;
  breaks?: boolean;
  alignment?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { resolved } = useCanvasVariables();

  const raw = markdownTextOf(
    source, text, textVariable ? resolved[textVariable] : undefined,
  );
  // **`{{v_id}}` is expanded in typed text only.** It is what `CanvasText` does
  // and what an author moving to this widget will expect to keep working. It is
  // deliberately *not* done to text arriving from a variable: that text is data,
  // and data that can name variables is data that reads them.
  const filled = markdownSourceOf(source) === "text" ? interpolate(raw, resolved) : raw;
  const widgetAlign = alignmentOf(alignment);
  const blocks = parseMarkdown(filled, { breaks: breaks !== false });

  const classes = ["canvas-markdown"];
  if (monospace) classes.push("canvas-markdown-mono");
  if (scrolling) classes.push("canvas-markdown-scrolling");
  // p.317's "Allow long word wrap", default on: a long URL breaks onto the next
  // line rather than pushing the widget wider than its column.
  if (wordWrap !== false) classes.push("canvas-markdown-wrap");

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {blocks.length === 0 ? (
        <p className="canvas-widget-empty">Markdown - add text in Settings</p>
      ) : (
        <div className={classes.join(" ")} data-testid="markdown">
          {blocks.map((block, i) => renderBlock(block, i, widgetAlign))}
        </div>
      )}
    </div>
  );
}

function MarkdownSettings() {
  const {
    source, text, textVariable, monospace, scrolling, wordWrap, breaks, alignment,
    actions: { setProp },
  } = useNode((node) => ({
    source: node.data.props.source,
    text: node.data.props.text,
    textVariable: node.data.props.textVariable,
    monospace: node.data.props.monospace,
    scrolling: node.data.props.scrolling,
    wordWrap: node.data.props.wordWrap,
    breaks: node.data.props.breaks,
    alignment: node.data.props.alignment,
  }));
  const { declared } = useCanvasVariables();
  const strings = Object.values(declared).filter((v) => v.kind === "string");

  return (
    <WidgetSetup
      inputs={<>
      <label className="field">
        <span className="field-label">Input data</span>
        <select
          value={markdownSourceOf(source)}
          data-testid="markdown-source"
          onChange={(e) => setProp((p: { source: string }) => (p.source = e.target.value))}
        >
          <option value="text">Text</option>
          <option value="variable">Variable</option>
        </select>
      </label>
      {markdownSourceOf(source) === "text" ? (
        <label className="field">
          <span className="field-label">Text</span>
          <textarea
            value={text || ""}
            rows={8}
            data-testid="markdown-text"
            onChange={(e) => setProp((p: { text: string }) => (p.text = e.target.value))}
          />
          <span className="field-hint">
            {"{{v_id}}"} shows a variable&apos;s current value
          </span>
        </label>
      ) : (
        <label className="field">
          <span className="field-label">Text variable</span>
          <select
            value={textVariable || ""}
            data-testid="markdown-variable"
            onChange={(e) =>
              setProp((p: { textVariable: string }) => (p.textVariable = e.target.value))}
          >
            <option value="">Choose…</option>
            {strings.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
          <span className="field-hint">
            {strings.length === 0
              ? "Declare a string variable in the Variables panel first"
              : "Its value is rendered as Markdown, and is not scanned for {{v_id}}"}
          </span>
        </label>
      )}
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Text alignment</span>
        <select
          value={alignmentOf(alignment)}
          data-testid="markdown-alignment"
          onChange={(e) => setProp((p: { alignment: string }) => (p.alignment = e.target.value))}
        >
          {Object.entries(ALIGNMENTS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        <span className="field-hint">
          A table column that names its own alignment keeps it, and code blocks stay left
        </span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={breaks !== false}
          data-testid="markdown-breaks"
          onChange={(e) => setProp((p: { breaks: boolean }) => (p.breaks = e.target.checked))}
        />
        <span className="field-label">Break on newlines</span>
        <span className="field-hint">
          Off follows standard Markdown, where a single newline is a space
        </span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={!!monospace}
          data-testid="markdown-monospace"
          onChange={(e) => setProp((p: { monospace: boolean }) => (p.monospace = e.target.checked))}
        />
        <span className="field-label">Enable monospace font</span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={!!scrolling}
          data-testid="markdown-scrolling"
          onChange={(e) => setProp((p: { scrolling: boolean }) => (p.scrolling = e.target.checked))}
        />
        <span className="field-label">Enable scrolling</span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={wordWrap !== false}
          data-testid="markdown-wrap"
          onChange={(e) => setProp((p: { wordWrap: boolean }) => (p.wordWrap = e.target.checked))}
        />
        <span className="field-label">Allow long word wrap</span>
        <span className="field-hint">
          A long unbroken string breaks onto the next line instead of overflowing
        </span>
      </label>
      </>}
    />
  );
}

CanvasMarkdown.craft = {
  displayName: "Markdown",
  props: {
    source: "text", text: "", textVariable: "", monospace: false,
    scrolling: false, wordWrap: true, breaks: true, alignment: "left",
  },
  related: { settings: MarkdownSettings },
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
  // p.66's disclosure, with a dataset in the object set's place: a column
  // picker is a question nobody can answer before something has said which
  // table the columns belong to - which is why binding the dataset clears the
  // column beside it.
  return (
    <WidgetSetup
      bindings={{ datasetId }}
      requires={["datasetId"]}
      labels={{ datasetId: "a dataset" }}
      inputs={<>
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
      </>}
      configuration={<>
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
      </>}
    />
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
  activeVariable = null,
  autoSelect = true,
  multiSelect = false,
  selectedVariable = null,
  lines = 1,
  valueWrap = false,
  frozenColumns = 0,
  emptyMode = "default",
  emptyMessage = "",
  customNoValue = false,
  noValueText = "",
  fitColumns = true,
  narrowHeaders = false,
  formatFillsCell = false,
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
  /** p.224's **Active object**: the row a viewer highlighted, as clauses a
   * `narrow_set` derivation turns into an object set. Clauses rather than a
   * finished definition so the meaning is recomputed against whatever the
   * table's set currently is - see `object-table-selection.ts`. */
  activeVariable?: string | null;
  /** p.224's setting, as the positive: the panel offers "Disable active object
   * auto-selection", which is this turned off. */
  autoSelect?: boolean;
  /** p.224's **Enable multi-select**. */
  multiSelect?: boolean;
  /** p.224's **Selected objects**, "only in use and populated if the Enable
   * multi-select toggle is set to true". */
  selectedVariable?: string | null;
  /** p.224's Display & formatting block. Each is read through
   * `object-table-display.ts` rather than used raw: a saved document holds
   * whatever an author or the raw JSON editor put there, and `Number(null)`
   * is a perfectly finite `0`. */
  lines?: number;
  valueWrap?: boolean;
  frozenColumns?: number;
  emptyMode?: string;
  emptyMessage?: string;
  customNoValue?: boolean;
  noValueText?: string;
  fitColumns?: boolean;
  narrowHeaders?: boolean;
  formatFillsCell?: boolean;
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

  // p.224's two outputs. **The variables are the source of truth**, not a copy
  // in component state: a table holding its own set would disagree with the
  // variable the moment anything else wrote to it — an event that clears the
  // selection, a saved state restored on load — and the checkboxes would show
  // one answer while every downstream widget acted on another.
  const { set: setParameter } = useCanvasParameters();
  const activeRaw = useCanvasParameter(activeVariable);
  const selectedRaw = useCanvasParameter(selectedVariable);
  const activeKeys = keysOf(activeRaw);
  const selectedKeys = keysOf(selectedRaw);
  // **Stated, not merely empty.** A variable this widget has never written
  // holds no clauses at all, and no clauses means *no narrowing* - so an
  // "empty" active object would hand every downstream widget the whole table.
  // `hasSelection` is how the widget knows it still has to say so.
  const activeStated = hasSelection(activeRaw);
  const selectedStated = hasSelection(selectedRaw);
  const [screenRef, onScreen] = useOnScreen();

  // p.224-225's Display & formatting, resolved once.
  const rowLines = linesOf(lines);
  const wrapValues = wrapOf(valueWrap);
  const cell = cellStyle(rowLines, wrapValues);
  const minHeight = rowMinHeight(rowLines, LINE_HEIGHT);
  const fillsCell = fillsCellOf(formatFillsCell);
  const emptyText = noValueOf(customNoValue, noValueText);
  // **Measured, because a sticky column's offset is the running total of the
  // widths before it** and CSS cannot add those up. Remeasured whenever the
  // columns or the frozen count change; a width that is not there yet reads as
  // zero, which puts a column at the left edge for one frame rather than
  // unpinning every column after it.
  const headRef = useRef<HTMLTableRowElement | null>(null);
  const [widths, setWidths] = useState<number[]>([]);

  // Paging is *runtime* state, like a page or a variable value (decision 0002
  // §3): a saved app opens on the first page for every viewer. The hook holds
  // it, and the reset-when-the-set-changes rule with it - shared with the Card
  // List rather than written twice (see `object-set.ts`).
  const setPage = useSetPage(workspaceId, usingSet ? setDefinition : null, {
    pageSize,
    sort,
    variablesPending,
  });
  const { offset, setOffset } = setPage;

  const effectiveTypeId = usingSet ? setPage.typeId : objectTypeId;
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
  const rows = usingSet ? setPage.rows : page.data?.items;
  const total = usingSet ? setPage.total : page.data?.total;
  const active = usingSet
    ? { isError: setPage.isError, isPending: setPage.isPending }
    : { isError: page.isError, isPending: page.isPending };
  const setFilters = setPage.filters;

  // Row selection (roadmap 1.3). The widget does not decide what a click
  // *means* - it announces that a row was chosen and hands over the row, and
  // the module's events say what happens. That is the difference between a
  // widget with a hardcoded behaviour and one an app author can wire.
  const rowEvents = eventsFor(moduleEvents, nodeId, "row_select");
  // **Every row is clickable once there is somewhere to put the answer.** It
  // used to take an event: before p.224's outputs the only thing a click could
  // do was fire one, so a table with no events had nothing to say. Now a click
  // also sets the active object, and a table bound to that variable is
  // interactive whether or not anybody wired an event to it.
  const rowsAreClickable = rowEvents.length > 0 || !!activeVariable;

  const chooseActive = (key: string) => {
    if (activeVariable) setParameter(activeVariable, selectionClauses([key]));
  };

  // p.224's auto-selection, in an effect because it is a *write* — doing it
  // during render would set a variable while React is drawing the widget that
  // reads it.
  const autoKey = autoSelectKey({
    rows, current: activeKeys, enabled: autoSelect !== false, visible: onScreen,
  });
  useEffect(() => {
    if (!activeVariable) return;
    if (autoKey) {
      setParameter(activeVariable, selectionClauses([autoKey]));
      return;
    }
    // p.224's "results in an empty active object at load time", written down
    // rather than left unsaid - see `activeStated` above.
    if (!activeStated) setParameter(activeVariable, selectionClauses([]));
    // `setParameter` is stable for the life of the provider; listing it would
    // re-run this on every render of every widget in the module.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoKey, activeVariable, activeStated]);

  useEffect(() => {
    // p.224: the Selected objects variable "will only be in use and populated
    // if the Enable multi-select toggle is set to true" - so an unbound or
    // single-select table leaves it alone entirely.
    if (!multiSelect || !selectedVariable || selectedStated) return;
    setParameter(selectedVariable, selectionClauses([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [multiSelect, selectedVariable, selectedStated]);

  const columnCount = properties.length + 1 + (multiSelect && selectedVariable ? 1 : 0);
  const frozen = frozenOf(frozenColumns, columnCount);
  useEffect(() => {
    const head = headRef.current;
    if (!head || frozen === 0) return;
    setWidths(Array.from(head.children, (cellEl) => (cellEl as HTMLElement).offsetWidth));
  }, [frozen, columnCount, rows?.length, rowLines, wrapValues, fitColumns]);
  const lefts = stickyLefts(widths, frozen);
  const stick = (index: number) => {
    const left = lefts[index];
    return left === null || left === undefined
      ? undefined
      : ({ position: "sticky", left, zIndex: 1 } as React.CSSProperties);
  };
  return (
    <div
      ref={(ref) => {
        connectDragDrop(ref, connect, drag);
        screenRef(ref);
      }}
      className="canvas-block"
    >
      {!usingSet && !objectTypeId && (
        <p className="canvas-widget-empty">Object table - pick an object type in Settings</p>
      )}
      {usingSet && setPage.unresolved && (
        <p className="canvas-widget-empty">Resolving the object set…</p>
      )}
      {!usingSet && objectTypeId && page.isPending && (
        <p className="canvas-widget-empty">Loading…</p>
      )}
      {active.isError && <p className="canvas-widget-empty">Couldn&apos;t load these objects.</p>}
      {rows && total !== undefined && (
        <>
          {/* p.224's Empty state message, in place of the count line: a table
              with nothing in it should say so in the author's words rather
              than announce a zero. */}
          {total === 0 ? (
            <p className="canvas-widget-empty" data-testid="table-empty-state">
              {emptyMessageOf(emptyMode, emptyMessage)}
            </p>
          ) : (
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
          )}
          <div
            className={[
              "data-grid",
              // p.225's "Enable narrow headers". A class rather than a style,
              // because it is the header's own padding and belongs with the
              // rest of the grid's rules.
              narrowHeadersOf(narrowHeaders) ? "data-grid--narrow" : "",
            ].filter(Boolean).join(" ")}
          >
            {/* p.225's "Fit columns horizontally": full width, or the columns'
                natural widths with the grid scrolling past them. */}
            <table style={fitColumnsOf(fitColumns) ? undefined : { width: "auto" }}>
              <thead>
                <tr ref={headRef}>
                  {multiSelect && selectedVariable && (
                    <th className="canvas-table-check" style={stick(0)}>
                      <input
                        type="checkbox"
                        aria-label="Select all rows on this page"
                        data-testid="table-select-all"
                        checked={rows.length > 0 && rows.every(
                          (r) => selectedKeys.includes(r.primary_key),
                        )}
                        onChange={(e) =>
                          setParameter(selectedVariable, selectionClauses(
                            // **This page, not the whole set.** Checking a box
                            // that selects rows nobody has seen is a promise
                            // the widget cannot keep: it only has the page it
                            // fetched, and the set may be a million rows.
                            e.target.checked
                              ? Array.from(new Set([
                                ...selectedKeys, ...rows.map((r) => r.primary_key),
                              ]))
                              : selectedKeys.filter(
                                (k) => !rows.some((r) => r.primary_key === k),
                              ),
                          ))}
                      />
                    </th>
                  )}
                  <th style={stick(multiSelect && selectedVariable ? 1 : 0)}>Key</th>
                  {properties.map((p, column) => (
                    <th
                      key={p.api_name}
                      style={stick(column + 1 + (multiSelect && selectedVariable ? 1 : 0))}
                    >
                      {p.display_name || p.api_name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((instance) => (
                  <tr
                    key={instance.id}
                    className={[
                      rowsAreClickable ? "row-clickable" : "",
                      activeKeys.includes(instance.primary_key) ? "row-active" : "",
                    ].filter(Boolean).join(" ") || undefined}
                    // The active row is announced rather than only coloured: a
                    // highlight nobody can hear is not a selection.
                    aria-current={
                      activeKeys.includes(instance.primary_key) ? "true" : undefined
                    }
                    onClick={
                      rowsAreClickable
                        ? () => {
                          chooseActive(instance.primary_key);
                          runEvents(rowEvents, {
                            ...eventContext,
                            ...selectionOf(instance, effectiveTypeId),
                          });
                        }
                        : undefined
                    }
                  >
                    {multiSelect && selectedVariable && (
                      <td className="canvas-table-check" style={stick(0)}>
                        <input
                          type="checkbox"
                          aria-label={`Select ${instance.primary_key}`}
                          checked={selectedKeys.includes(instance.primary_key)}
                          // **Stops the click reaching the row.** Checking a box
                          // is not choosing an active object, and without this
                          // one click would do both — and fire the row's events
                          // as a side effect of ticking a checkbox.
                          onClick={(e) => e.stopPropagation()}
                          onChange={() =>
                            setParameter(selectedVariable, selectionClauses(
                              toggleKey(selectedKeys, instance.primary_key),
                            ))}
                        />
                      </td>
                    )}
                    <td
                      style={{
                        // **`height`, not `minHeight`**, and the harness is
                        // why the comment says what it says. `height` on a
                        // table cell is *defined* to act as a minimum;
                        // `min-height` on one is undefined, and Chromium
                        // happens to honour it - so swapping them survives this
                        // browser suite, which is an equivalent mutant here and
                        // a difference somewhere else. The defined one is the
                        // one to rely on.
                        height: minHeight,
                        ...stick(multiSelect && selectedVariable ? 1 : 0),
                      }}
                    >
                      {/* **The clamp lives on an inner element**, because
                          `-webkit-box` would stop the `<td>` being a table cell
                          and take the column widths with it. */}
                      <div style={cell}>{instance.primary_key}</div>
                    </td>
                    {properties.map((p, column) => {
                      const paint = conditionalStyle(
                        p.conditional_format, instance.properties,
                      );
                      return (
                        <td
                          key={p.api_name}
                          style={{
                            height: minHeight,
                            // p.225's "Conditional formatting colors entire
                            // cell". The rule is evaluated once either way; the
                            // toggle only decides where the colour lands.
                            ...(fillsCell && paint?.background
                              ? { background: paint.background }
                              : {}),
                            ...stick(column + 1 + (multiSelect && selectedVariable ? 1 : 0)),
                          }}
                        >
                          <div style={cell}>
                            <PropertyValue
                              workspaceId={workspaceId}
                              dataType={p.data_type}
                              valueFormat={p.value_format}
                              style={paint}
                              value={instance.properties[p.api_name]}
                              emptyText={emptyText}
                            />
                          </div>
                        </td>
                      );
                    })}
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
    activeVariable, autoSelect, multiSelect, selectedVariable,
    lines, valueWrap, frozenColumns, emptyMode, emptyMessage,
    customNoValue, noValueText, fitColumns, narrowHeaders, formatFillsCell,
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
    activeVariable: node.data.props.activeVariable,
    autoSelect: node.data.props.autoSelect,
    multiSelect: node.data.props.multiSelect,
    selectedVariable: node.data.props.selectedVariable,
    lines: node.data.props.lines,
    valueWrap: node.data.props.valueWrap,
    frozenColumns: node.data.props.frozenColumns,
    emptyMode: node.data.props.emptyMode,
    emptyMessage: node.data.props.emptyMessage,
    customNoValue: node.data.props.customNoValue,
    noValueText: node.data.props.noValueText,
    fitColumns: node.data.props.fitColumns,
    narrowHeaders: node.data.props.narrowHeaders,
    formatFillsCell: node.data.props.formatFillsCell,
  }));
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  // **`array`, not `object_set`.** p.224 calls these outputs object sets and
  // they end up as ones, but what the widget *writes* is the clause list a
  // `narrow_set` derivation reads - so the variable to bind here is the array
  // in the middle. Offering object-set variables would invite binding the
  // derived one and overwriting the thing that derives it.
  const clauseVariables = Object.values(declared).filter((v) => v.kind === "array");
  const types = useQuery({
    queryKey: ["object-types", workspaceId],
    queryFn: () => objApi.listTypes(workspaceId),
  });
  const detail = useQuery({
    queryKey: ["object-type", objectTypeId],
    queryFn: () => objApi.getType(workspaceId, objectTypeId!),
    enabled: !!objectTypeId,
  });

  // p.65's order, and p.66's disclosure. **A choice rather than a
  // requirement**: this widget is populated either by a bound object set or
  // by an object type picked directly, so waiting for both would be waiting
  // for something nobody is meant to supply.
  return (
    <WidgetSetup
      bindings={{ objectSetVariable, objectTypeId }}
      requires={[["objectSetVariable", "objectTypeId"]]}
      labels={{
        objectSetVariable: "an object set",
        objectTypeId: "an object type",
      }}
      inputs={<>
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
      </>}
      configuration={<>
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
      {/* p.224-225's Display & formatting, in p.224's order. */}
      <label className="field">
        <span className="field-label">Number of lines to display per row</span>
        <input
          type="number"
          min={1}
          max={MAX_LINES}
          value={linesOf(lines)}
          data-testid="table-lines"
          onChange={(e) => setProp((p: { lines: number }) => (p.lines = Number(e.target.value)))}
        />
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={wrapOf(valueWrap)}
          data-testid="table-wrap"
          onChange={(e) => setProp((p: { valueWrap: boolean }) => (p.valueWrap = e.target.checked))}
        />
        <span className="field-label">Enable value wrapping</span>
      </label>
      <label className="field">
        <span className="field-label">Number of frozen columns</span>
        <input
          type="number"
          min={0}
          value={Number(frozenColumns) || 0}
          data-testid="table-frozen"
          onChange={(e) =>
            setProp((p: { frozenColumns: number }) => (p.frozenColumns = Number(e.target.value)))}
        />
        <span className="field-hint">Counted from the left, including the checkbox column</span>
      </label>
      <label className="field">
        <span className="field-label">Empty state message</span>
        <select
          value={emptyModeOf(emptyMode)}
          data-testid="table-empty-mode"
          onChange={(e) => setProp((p: { emptyMode: string }) => (p.emptyMode = e.target.value))}
        >
          {Object.entries(EMPTY_MODES).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </label>
      {emptyModeOf(emptyMode) === "custom" && (
        <label className="field">
          <span className="field-label">Message</span>
          <input
            type="text"
            value={emptyMessage || ""}
            data-testid="table-empty-message"
            onChange={(e) =>
              setProp((p: { emptyMessage: string }) => (p.emptyMessage = e.target.value))}
          />
          {/* p.224's Custom option also takes an icon. There is no icon picker
              on this platform - the same reason p.468's icon suffix is ○ - so
              the message is the half that can be honoured. */}
          <span className="field-hint">Blank falls back to “No objects found”</span>
        </label>
      )}
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={customNoValue === true}
          data-testid="table-custom-no-value"
          onChange={(e) =>
            setProp((p: { customNoValue: boolean }) => (p.customNoValue = e.target.checked))}
        />
        <span className="field-label">Custom &ldquo;No value&rdquo; display</span>
      </label>
      {customNoValue === true && (
        <label className="field">
          <span className="field-label">Shown for an empty cell</span>
          <input
            type="text"
            value={noValueText ?? ""}
            data-testid="table-no-value-text"
            onChange={(e) =>
              setProp((p: { noValueText: string }) => (p.noValueText = e.target.value))}
          />
          <span className="field-hint">Blank shows nothing at all, which is a real answer</span>
        </label>
      )}
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={fitColumnsOf(fitColumns)}
          data-testid="table-fit-columns"
          onChange={(e) =>
            setProp((p: { fitColumns: boolean }) => (p.fitColumns = e.target.checked))}
        />
        <span className="field-label">Fit columns horizontally</span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={narrowHeadersOf(narrowHeaders)}
          data-testid="table-narrow-headers"
          onChange={(e) =>
            setProp((p: { narrowHeaders: boolean }) => (p.narrowHeaders = e.target.checked))}
        />
        <span className="field-label">Enable narrow headers</span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={fillsCellOf(formatFillsCell)}
          data-testid="table-format-fills-cell"
          onChange={(e) =>
            setProp((p: { formatFillsCell: boolean }) => (p.formatFillsCell = e.target.checked))}
        />
        <span className="field-label">Conditional formatting colors entire cell</span>
        <span className="field-hint">
          The rules themselves come from the Ontology Manager
        </span>
      </label>
      </>}
      outputs={<>
      {/* p.224's Selection block, in p.224's order. */}
      <label className="field">
        <span className="field-label">Active object</span>
        <select
          value={activeVariable || ""}
          data-testid="table-active-variable"
          onChange={(e) =>
            setProp((p: { activeVariable: string | null }) =>
              (p.activeVariable = e.target.value || null))}
        >
          <option value="">None</option>
          {clauseVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {clauseVariables.length === 0
            ? "Declare an array variable in the Variables panel, then derive an object set from it with narrow set"
            : "Holds the clauses that pick the highlighted row; derive an object set from it with narrow set"}
        </span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={autoSelect === false}
          data-testid="table-disable-auto-select"
          onChange={(e) =>
            setProp((p: { autoSelect: boolean }) => (p.autoSelect = !e.target.checked))}
        />
        <span className="field-label">Disable active object auto-selection</span>
        {/* Stored as the positive and shown as the negative, because p.224
            words it as the negative and an author looking for that sentence
            should find it. The prop is the positive so a document that omits
            it gets p.224's default rather than the opposite. */}
        <span className="field-hint">
          By default the first row is active at load, once the widget is on screen
        </span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={!!multiSelect}
          data-testid="table-multi-select"
          onChange={(e) =>
            setProp((p: { multiSelect: boolean }) => (p.multiSelect = e.target.checked))}
        />
        <span className="field-label">Enable multi-select</span>
      </label>
      {multiSelect && (
        <label className="field">
          <span className="field-label">Selected objects</span>
          <select
            value={selectedVariable || ""}
            data-testid="table-selected-variable"
            onChange={(e) =>
              setProp((p: { selectedVariable: string | null }) =>
                (p.selectedVariable = e.target.value || null))}
          >
            <option value="">None</option>
            {clauseVariables.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
          <span className="field-hint">
            Empty means nothing is selected, not everything — the clauses say so explicitly
          </span>
        </label>
      )}
      </>}
    />
  );
}

CanvasObjectTable.craft = {
  displayName: "Object table",
  props: {
    objectTypeId: null, filterProperty: null, filterParameter: null,
    searchParameter: null, pageSize: 25, columns: "", sort: "recent",
    activeVariable: null, autoSelect: true, multiSelect: false,
    selectedVariable: null, lines: DEFAULT_LINES, valueWrap: false,
    frozenColumns: 0, emptyMode: "default", emptyMessage: "",
    customNoValue: false, noValueText: "", fitColumns: true,
    narrowHeaders: false, formatFillsCell: false,
  },
  related: { settings: ObjectTableSettings },
};

// ---- Object set title (p.274) ---------------------------------------------------
/** p.274's Object Set Title: "a summary of a given object set as a title".
 *
 * The string and the decision about whether to draw at all are in
 * `object-set-title.ts`. What is here is the three things that need the server:
 * the set's count, the first object's title when p.274 wants one, and the object
 * type behind it.
 *
 * **`Enable drag` is not built.** p.274 makes it conditional on a "data bank
 * service" and on the set holding fewer than 500 objects; there is no such
 * service here, and a drag source that no drop zone accepts is an affordance
 * that promises something nothing will do.
 */
export function CanvasObjectSetTitle({
  objectSetVariable = null,
  single = false,
  showIcon = false,
  titleOverride = "",
  renderWhenEmpty = false,
  placeholderTypeId = null,
}: {
  objectSetVariable?: string | null;
  /** p.274's Contains single object. */
  single?: boolean;
  showIcon?: boolean;
  /** p.274's Title override, which it says is "only available when Contains
   * single object is disabled" - enforced on the *value* rather than only in
   * the panel, so a stale one cannot rename somebody's object. */
  titleOverride?: string;
  renderWhenEmpty?: boolean;
  /** p.274: "Allows selection of an object type to display as a placeholder if
   * the inputted object set is empty." */
  placeholderTypeId?: string | null;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, mode } = useCanvasEnv();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();

  // One row, because that is all p.274 ever shows: the count comes back with
  // it, and a page of twenty-five would be twenty-four rows fetched to be
  // thrown away on every resolve.
  const setPage = useSetPage(workspaceId, setDefinition, {
    pageSize: 1, variablesPending,
  });

  const holdsOne = singleOf(single);
  const empty = renderWhenEmptyOf(renderWhenEmpty);
  // The placeholder type stands in only when the set is empty and p.274's
  // toggle asked for one; otherwise the set's own type is the subject.
  const showingPlaceholder = empty && setPage.total === 0 && !!placeholderTypeId;
  const typeId = showingPlaceholder ? placeholderTypeId : setPage.typeId;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });

  const titleProperty = (type.data?.properties ?? []).find(
    (p) => p.id === type.data?.title_property_id,
  );
  const first = setPage.rows?.[0];
  const objectTitle = first && titleProperty
    ? String(first.properties[titleProperty.api_name] ?? "")
    : undefined;

  const title = titleFor({
    single: holdsOne,
    typeName: type.data?.display_name,
    objectTitle,
    total: setPage.total,
    override: titleOverride,
  });

  const draws = shouldRender({
    resolved: !setPage.unresolved,
    total: setPage.total,
    renderWhenEmpty: empty || showingPlaceholder,
  });

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectSetVariable ? (
        <p className="canvas-widget-empty">Object set title - bind an object set in Settings</p>
      ) : !draws ? (
        // p.274: "Widget will not render in the module view if the inputted
        // object set is empty." **In the module view** - a builder who cannot
        // see the widget cannot select it to turn the setting back off, so the
        // canvas says why instead of going blank.
        mode === "run" ? null : (
          <p className="canvas-widget-empty" data-testid="set-title-hidden">
            Hidden: the object set is empty
          </p>
        )
      ) : (
        <h3 className="canvas-set-title" data-testid="set-title">
          {showIconOf(showIcon) && (
            // **A mark in the type's colour, not the named icon**, because this
            // platform has no icon set - the `icon` field holds a name like
            // `cube` and nothing has ever drawn one. The name travels as the
            // accessible label so it is readable rather than merely absent.
            <span
              className="canvas-set-title-icon"
              data-testid="set-title-icon"
              aria-label={type.data?.icon ?? "object type"}
              style={{ background: type.data?.colour || "var(--accent)" }}
            />
          )}
          <span>{title}</span>
        </h3>
      )}
    </div>
  );
}

function ObjectSetTitleSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, single, showIcon, titleOverride, renderWhenEmpty,
    placeholderTypeId,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    single: node.data.props.single,
    showIcon: node.data.props.showIcon,
    titleOverride: node.data.props.titleOverride,
    renderWhenEmpty: node.data.props.renderWhenEmpty,
    placeholderTypeId: node.data.props.placeholderTypeId,
  }));
  const { declared } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const types = useQuery({
    queryKey: ["object-types", workspaceId],
    queryFn: () => objApi.listTypes(workspaceId),
  });

  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Input object set</span>
        <select
          value={objectSetVariable || ""}
          data-testid="set-title-variable"
          onChange={(e) =>
            setProp((p: { objectSetVariable: string | null }) =>
              (p.objectSetVariable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
      </label>
      </>}
      configuration={<>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={singleOf(single)}
          data-testid="set-title-single"
          onChange={(e) => setProp((p: { single: boolean }) => (p.single = e.target.checked))}
        />
        <span className="field-label">Contains single object</span>
        <span className="field-hint">Shows that object&apos;s title instead of a count</span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={showIconOf(showIcon)}
          data-testid="set-title-icon-toggle"
          onChange={(e) => setProp((p: { showIcon: boolean }) => (p.showIcon = e.target.checked))}
        />
        <span className="field-label">Show icon</span>
      </label>
      {/* p.274: "This option is only available when Contains single object is
          disabled." */}
      {!singleOf(single) && (
        <label className="field">
          <span className="field-label">Title override</span>
          <input
            type="text"
            value={titleOverride || ""}
            data-testid="set-title-override"
            onChange={(e) =>
              setProp((p: { titleOverride: string }) => (p.titleOverride = e.target.value))}
          />
          <span className="field-hint">Blank uses the object type and the count</span>
        </label>
      )}
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={renderWhenEmptyOf(renderWhenEmpty)}
          data-testid="set-title-render-empty"
          onChange={(e) =>
            setProp((p: { renderWhenEmpty: boolean }) =>
              (p.renderWhenEmpty = e.target.checked))}
        />
        <span className="field-label">Render widget when the object set is empty</span>
        <span className="field-hint">Off by default: the widget disappears instead</span>
      </label>
      {renderWhenEmptyOf(renderWhenEmpty) && (
        <label className="field">
          <span className="field-label">Placeholder object type</span>
          <select
            value={placeholderTypeId || ""}
            data-testid="set-title-placeholder"
            onChange={(e) =>
              setProp((p: { placeholderTypeId: string | null }) =>
                (p.placeholderTypeId = e.target.value || null))}
          >
            <option value="">None</option>
            {(types.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>{t.display_name}</option>
            ))}
          </select>
          <span className="field-hint">
            Named so an empty widget still says what it would have shown
          </span>
        </label>
      )}
      </>}
    />
  );
}

CanvasObjectSetTitle.craft = {
  displayName: "Object set title",
  props: {
    objectSetVariable: null, single: false, showIcon: false,
    titleOverride: "", renderWhenEmpty: false, placeholderTypeId: null,
  },
  related: { settings: ObjectSetTitleSettings },
};

// ---- Property list (p.265-266) --------------------------------------------------
/** p.265-266's Property List: "a list of properties from a single provided object".
 *
 * Which properties and how they are arranged is `property-list.ts`. What is here
 * is the fetch — one object out of a set, plus the type that says what its
 * properties are called and how to draw each one.
 *
 * **Not built, and named rather than approximated**: p.265's "Load data from
 * scenario" (there are no Scenarios here), p.266's security markings (no
 * markings), and p.266's **inline editing**, which it says is configured "by
 * configuring an inline action for the property in the Ontology Manager" - that
 * is `workshop.md`'s build-order item 6, and a Property List that offered an
 * edit no action backs would be a control that does nothing.
 */
export function CanvasPropertyList({
  objectSetVariable = null,
  layout = "adjacent",
  properties = "",
  columns = 1,
  hideNull = false,
}: {
  objectSetVariable?: string | null;
  /** p.265's Layout: the value beside its label, or under it. */
  layout?: string;
  /** p.266's selection, in the order to show them. Blank means all of them. */
  properties?: string;
  columns?: number;
  hideNull?: boolean;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();

  // p.265: "If the object set contains more than one object, only the first
  // object will be displayed within the widget." One row is all it ever needs.
  const setPage = useSetPage(workspaceId, setDefinition, {
    pageSize: 1, variablesPending,
  });
  const type = useQuery({
    queryKey: ["object-type", setPage.typeId],
    queryFn: () => objApi.getType(workspaceId, setPage.typeId!),
    enabled: !!setPage.typeId,
  });

  const instance = setPage.rows?.[0];
  const shown = visibleProperties({
    all: type.data?.properties ?? [],
    chosen: properties,
    values: instance?.properties,
    hideNull: hideNullOf(hideNull),
  });
  const stacked = propertyLayoutOf(layout) === "below";

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectSetVariable ? (
        <p className="canvas-widget-empty">Property list - bind an object set in Settings</p>
      ) : setPage.unresolved ? (
        <p className="canvas-widget-empty">Resolving the object set…</p>
      ) : !instance ? (
        // Distinct from "resolving", because they are different facts and only
        // one of them is worth an author's attention.
        <p className="canvas-widget-empty" data-testid="property-list-empty">
          No object to show
        </p>
      ) : (
        <dl
          className={`canvas-property-list${stacked ? " canvas-property-list--stacked" : ""}`}
          data-testid="property-list"
          style={propertyGridStyle(propertyColumnsOf(columns))}
        >
          {shown.map((p) => (
            <div className="canvas-property" key={p.api_name} data-testid="property-row">
              <dt>{p.display_name || p.api_name}</dt>
              <dd>
                <PropertyValue
                  workspaceId={workspaceId}
                  dataType={p.data_type}
                  valueFormat={p.value_format}
                  style={conditionalStyle(p.conditional_format, instance.properties)}
                  value={instance.properties[p.api_name]}
                />
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function PropertyListSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, layout, properties, columns, hideNull,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    layout: node.data.props.layout,
    properties: node.data.props.properties,
    columns: node.data.props.columns,
    hideNull: node.data.props.hideNull,
  }));
  const { declared, resolved } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  // The set's own type, so the property names offered are the ones this widget
  // will actually be able to draw - a free-text list would let an author name
  // a property that silently never appears.
  const bound = objectSetVariable ? resolved[objectSetVariable] : undefined;
  const typeId = (bound as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });

  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Input object set</span>
        <select
          value={objectSetVariable || ""}
          data-testid="property-list-variable"
          onChange={(e) =>
            setProp((p: { objectSetVariable: string | null }) =>
              (p.objectSetVariable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          Only the first object is shown, which is what p.265 says a set of several does
        </span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Layout</span>
        <select
          value={propertyLayoutOf(layout)}
          data-testid="property-list-layout"
          onChange={(e) => setProp((p: { layout: string }) => (p.layout = e.target.value))}
        >
          {Object.entries(PROPERTY_LAYOUTS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Properties</span>
        <input
          type="text"
          value={properties ?? ""}
          placeholder="every property"
          data-testid="property-list-properties"
          onChange={(e) =>
            setProp((p: { properties: string }) => (p.properties = e.target.value))}
        />
        <span className="field-hint">
          {type.data
            ? `Names in the order to show them. Available: ${
              (type.data.properties ?? []).map((p) => p.api_name).join(", ")}`
            : "Names in the order to show them. Blank shows all of them."}
        </span>
      </label>
      <label className="field">
        <span className="field-label">Columns</span>
        <input
          type="number"
          min={PROPERTY_MIN_COLUMNS}
          max={PROPERTY_MAX_COLUMNS}
          value={propertyColumnsOf(columns)}
          data-testid="property-list-columns"
          onChange={(e) =>
            setProp((p: { columns: number }) => (p.columns = Number(e.target.value)))}
        />
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={hideNullOf(hideNull)}
          data-testid="property-list-hide-null"
          onChange={(e) => setProp((p: { hideNull: boolean }) => (p.hideNull = e.target.checked))}
        />
        <span className="field-label">Hide null properties</span>
        <span className="field-hint">A blank value counts, not only a missing one</span>
      </label>
      </>}
    />
  );
}

CanvasPropertyList.craft = {
  displayName: "Property list",
  props: {
    objectSetVariable: null, layout: "adjacent", properties: "",
    columns: 1, hideNull: false,
  },
  related: { settings: PropertyListSettings },
};

// ---- Search (roadmap 1.5) ---------------------------------------------------
/**
 * A search box that narrows an object set.
 *
 * **It writes clauses, like every other narrowing widget**, so the Filter
 * List, a chart drill-down and this compose instead of competing. Each owns
 * *its own* clause variable and they chain — `narrow_set(narrow_set(all,
 * filters), search)` — rather than sharing one, which would make two widgets
 * overwrite each other's answer and produce a set that depends on which was
 * touched last.
 *
 * **`starts_with`, not "contains", and that is the server's decision showing
 * through.** A substring match is `ILIKE '%x%'` on Postgres and a wildcard
 * query on OpenSearch, neither of which uses an index — fine on a hundred
 * objects and pathological on a million, which is the cost server-side
 * evaluation exists to avoid. A prefix is indexable on both, and the two
 * stores agree about it. The widget says "starts with" rather than "search"
 * on its own hint, because a box that quietly did something narrower than the
 * word on it is how somebody concludes their data is missing.
 *
 * **One property, named in Settings.** Searching every property at once is the
 * Object Explorer's job (item 4.1) and it is a different query — the store's
 * `search`, not a set filter. A widget that offered it here would be a second
 * path to a set, with no rule for which definition wins.
 */
export function CanvasSearch({
  objectSetVariable = null,
  variable = null,
  property = null,
  label = "Search",
}: {
  /** The set this searches, used only to offer its properties in Settings —
   *  the narrowing happens through `variable`, not here. */
  objectSetVariable?: string | null;
  /** Where the clause goes. A `narrow_set` derivation reads it. */
  variable?: string | null;
  property?: string | null;
  label?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const written = useCanvasParameter(variable);
  const { set } = useCanvasParameters();

  // What is currently searched for, read back out of the variable this widget
  // writes rather than kept beside it - so the box reflects the document's
  // state, and clearing the clause elsewhere clears the box.
  const current = (() => {
    for (const clause of Array.isArray(written) ? written : []) {
      const c = clause as { property?: string; op?: string; value?: unknown };
      if (c.property === property && c.op === "starts_with") return String(c.value ?? "");
    }
    return "";
  })();

  const ready = !!variable && !!property;
  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!ready ? (
        <p className="canvas-widget-empty">
          Search - pick a property and the variable it writes in Settings
        </p>
      ) : (
        <label className="field" style={{ maxWidth: 360 }}>
          <span className="field-label">{label}</span>
          <input
            type="search"
            value={current}
            placeholder={`${property} starts with…`}
            aria-label={label}
            // A write per keystroke is fine: `VariableBridge` debounces the
            // resolve, so this costs one request per pause rather than one per
            // character. Debouncing again here would only delay the box.
            onChange={(e) =>
              set(
                variable!,
                e.target.value
                  ? [{ property, op: "starts_with", value: e.target.value }]
                  // Empty is *no filter*, not a filter for nothing: an empty
                  // search box must show everything, and `narrow_set` reads an
                  // empty list as "no narrowing" for exactly that reason.
                  : [],
              )
            }
          />
          <span className="field-hint">Matches values that start with what you type</span>
        </label>
      )}
    </div>
  );
}

function SearchSettings() {
  const { workspaceId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    objectSetVariable, variable, property, label,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    variable: node.data.props.variable,
    property: node.data.props.property,
    label: node.data.props.label,
  }));
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const clauseVariables = Object.values(declared).filter(
    (v) => v.kind === "array" && !v.derivation,
  );
  const typeId = (resolved[objectSetVariable as string] as
    { object_type_id?: string } | undefined)?.object_type_id;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });

  // p.65's order, and p.66's disclosure: the property list is read from the
  // set's object type, so it is a question nothing can answer until the set
  // is bound - which is p.66's own example, one widget over.
  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Object set</span>
        <select
          value={objectSetVariable || ""}
          onChange={(e) =>
            setProp((p: Record<string, unknown>) => {
              p.objectSetVariable = e.target.value || null;
              p.property = null; // property names mean nothing against another type
            })
          }
        >
          <option value="">Choose…</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">Which set&apos;s properties to offer below</span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Property</span>
        <select
          value={property || ""}
          disabled={!type.data}
          onChange={(e) => setProp((p: { property: string | null }) => (p.property = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {(type.data?.properties ?? []).map((prop) => (
            <option key={prop.api_name} value={prop.api_name}>{prop.api_name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          type="text"
          value={label || ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      </>}
      outputs={<>
      <label className="field">
        <span className="field-label">Writes to</span>
        <select
          value={variable || ""}
          onChange={(e) => setProp((p: { variable: string | null }) => (p.variable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {clauseVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        {/* Its own variable, not one shared with a Filter List: two widgets
            writing one clause list overwrite each other, and the set then
            depends on which was touched last. Chain the derivations instead. */}
        <span className="field-hint">
          {clauseVariables.length === 0
            ? "Declare an array variable, and derive a narrowed set from it"
            : "Give this its own variable, and chain the narrow_set derivations"}
        </span>
      </label>
      </>}
    />
  );
}

CanvasSearch.craft = {
  displayName: "Search",
  props: { objectSetVariable: null, variable: null, property: null, label: "Search" },
  related: { settings: SearchSettings },
};

// ---- Object card list (roadmap 1.5) -----------------------------------------
/**
 * The card-shaped alternative to the object table.
 *
 * **Set-only, deliberately.** The table still carries a pre-variable path
 * where it names an object type and a filter parameter itself; a new widget
 * does not, because item 1.5's rule is that a widget consumes input variables
 * and emits output variables — one that reaches for a type id directly cannot
 * be wired to anything, which is the flaw in the original eight.
 *
 * **What makes it a card list rather than a table with rounded corners.** A
 * table is for comparing many objects across the same columns; cards are for
 * reading one object at a time, so a card leads with a *heading* — the type's
 * title property, or the key when it has none — and shows a few fields under
 * it. Six is the cap: past that a card is a table row that has been folded,
 * and the table is the better widget.
 *
 * It fires the same `row_select` the table does, with the same payload, so
 * everything already wired to a table can be pointed at this instead.
 */
const CARD_FIELD_CAP = 6;

export function CanvasObjectCards({
  objectSetVariable = null,
  fields = "",
  pageSize = 12,
  sort = "recent",
}: {
  objectSetVariable?: string | null;
  /** Property api_names to show under the heading, in order, comma-separated.
   *  Blank means the first few the type declares — a card that showed nothing
   *  until configured would look broken on the first drop, the same argument
   *  the table's blank `columns` makes. */
  fields?: string;
  pageSize?: number;
  sort?: string;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const eventContext = useEventContext(undefined, useOverlayIds());
  const definition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending, events: moduleEvents } = useCanvasVariables();
  const page = useSetPage(workspaceId, objectSetVariable ? definition : null, {
    pageSize,
    sort,
    variablesPending,
  });

  const type = useQuery({
    queryKey: ["object-type", page.typeId],
    queryFn: () => objApi.getType(workspaceId, page.typeId!),
    enabled: !!page.typeId,
  });
  const all = type.data?.properties ?? [];
  const titleProperty = all.find((p) => p.id === type.data?.title_property_id);
  const wanted = String(fields || "")
    .split(",")
    .map((f) => f.trim())
    .filter(Boolean);
  // A configured name that matches nothing is dropped rather than rendered as
  // an empty line: a property can be removed from the type long after a card
  // list was pointed at it.
  const shown = (wanted.length
    ? wanted.map((name) => all.find((p) => p.api_name === name)).filter((p) => !!p)
    : all.filter((p) => p.id !== type.data?.title_property_id)
  ).slice(0, CARD_FIELD_CAP);

  const rowEvents = eventsFor(moduleEvents, nodeId, "row_select");
  const clickable = rowEvents.length > 0;

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectSetVariable && (
        <p className="canvas-widget-empty">Card list - point it at an object set in Settings</p>
      )}
      {objectSetVariable && page.unresolved && (
        <p className="canvas-widget-empty">Resolving the object set…</p>
      )}
      {page.isError && <p className="canvas-widget-empty">Couldn&apos;t load these objects.</p>}
      {page.rows && page.total !== undefined && (
        <>
          <p className="canvas-widget-empty">
            {describeSet(page.total, type.data?.display_name, page.filters)}
          </p>
          {page.rows.length === 0 && (
            <p className="canvas-widget-empty">Nothing in this set.</p>
          )}
          <div className="canvas-cards">
            {page.rows.map((instance) => {
              const heading = titleProperty
                ? instance.properties[titleProperty.api_name]
                : undefined;
              const chosen = selectionOf(instance, page.typeId);
              return (
                <article
                  key={instance.id}
                  className={`canvas-card${clickable ? " clickable" : ""}`}
                  // A card is a click target only where a click does
                  // something. An article that highlights on hover and then
                  // ignores you is worse than one that does not.
                  {...(clickable
                    ? {
                        role: "button",
                        tabIndex: 0,
                        onClick: () =>
                          runEvents(rowEvents, { ...eventContext, ...chosen }),
                        onKeyDown: (e: React.KeyboardEvent) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            runEvents(rowEvents, { ...eventContext, ...chosen });
                          }
                        },
                      }
                    : {})}
                >
                  <h4>
                    {heading === undefined || heading === null || heading === ""
                      ? instance.primary_key
                      : String(heading)}
                  </h4>
                  {/* The key is always shown, even when it is also the
                      heading: it is what identifies the object to every other
                      part of the platform, and a card you cannot match back to
                      a row is a card you cannot act on. */}
                  <p className="canvas-card-key">{instance.primary_key}</p>
                  <dl>
                    {shown.map((p) => (
                      <div key={p.api_name}>
                        <dt>{p.display_name || p.api_name}</dt>
                        <dd>
                          <PropertyValue
                            workspaceId={workspaceId}
                            dataType={p.data_type}
                            valueFormat={p.value_format}
                            style={conditionalStyle(p.conditional_format, instance.properties)}
                            value={instance.properties[p.api_name]}
                          />
                        </dd>
                      </div>
                    ))}
                  </dl>
                </article>
              );
            })}
          </div>
          {page.total > page.rows.length && (
            <div className="canvas-table-pager">
              <button
                type="button"
                className="btn quiet"
                disabled={page.offset === 0}
                onClick={() => page.setOffset(Math.max(0, page.offset - pageSize))}
              >
                Previous
              </button>
              <span className="canvas-widget-empty">
                {page.offset + 1}–{page.offset + page.rows.length} of{" "}
                {page.total.toLocaleString()}
              </span>
              <button
                type="button"
                className="btn quiet"
                disabled={page.offset + page.rows.length >= page.total}
                onClick={() => page.setOffset(page.offset + pageSize)}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ObjectCardsSettings() {
  const { workspaceId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    objectSetVariable, fields, pageSize, sort,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    fields: node.data.props.fields,
    pageSize: node.data.props.pageSize,
    sort: node.data.props.sort,
  }));
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const typeId = (resolved[objectSetVariable as string] as
    { object_type_id?: string } | undefined)?.object_type_id;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });

  // p.65's order: the set that populates the cards, then how they look.
  // p.66 keeps the field list out of the way until the set names a type -
  // property names mean nothing before then, which is why binding the set
  // clears them.
  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Object set</span>
        <select
          value={objectSetVariable || ""}
          onChange={(e) =>
            setProp((p: Record<string, unknown>) => {
              p.objectSetVariable = e.target.value || null;
              p.fields = ""; // property names mean nothing against another type
            })
          }
        >
          <option value="">Choose…</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Fields</span>
        <input
          type="text"
          value={fields || ""}
          placeholder="blank for the first few"
          onChange={(e) => setProp((p: { fields: string }) => (p.fields = e.target.value))}
        />
        <span className="field-hint">
          {type.data
            ? `Comma-separated, at most ${CARD_FIELD_CAP}. Available: ${
                type.data.properties.map((p) => p.api_name).join(", ")
              }`
            : `Comma-separated, at most ${CARD_FIELD_CAP}`}
        </span>
      </label>
      <label className="field">
        <span className="field-label">Cards per page</span>
        <input
          type="number"
          min={1}
          max={100}
          value={pageSize ?? 12}
          onChange={(e) =>
            setProp((p: { pageSize: number }) => (p.pageSize = Number(e.target.value) || 12))
          }
        />
      </label>
      <label className="field">
        <span className="field-label">Order</span>
        <select
          value={sort || "recent"}
          onChange={(e) => setProp((p: { sort: string }) => (p.sort = e.target.value))}
        >
          <option value="recent">Most recently changed</option>
          <option value="key">By key</option>
        </select>
        {/* Sorting by a property is refused by the server, because untyped
            properties order differently on the two stores. Offering what it
            accepts beats a control that sometimes 422s. */}
        <span className="field-hint">Sorting by a property is not available yet</span>
      </label>
      </>}
    />
  );
}

CanvasObjectCards.craft = {
  displayName: "Card list",
  props: { objectSetVariable: null, fields: "", pageSize: 12, sort: "recent" },
  related: { settings: ObjectCardsSettings },
};

// ---- Pivot table (roadmap 1.5) ----------------------------------------------
/**
 * Counts by two properties at once: regions down the side, statuses across the
 * top, how many of each in the middle.
 *
 * **The axes are the chart's numbers.** The server builds each one with the
 * same grouped count a bar chart plots, so a row total here and a bar there
 * cannot disagree. That has a visible consequence this widget is careful to
 * state rather than hide: a row's cells can sum to *less* than its total,
 * because an object with no value for the column property is in no cell, and
 * because the columns are capped. A pivot whose margins were the sum of its
 * cells would look tidier and would quietly contradict the chart beside it.
 *
 * **Counts only**, like every other aggregation over a set — instance
 * properties are stored untyped, so a cross-tab of sums would mean one thing
 * on Postgres and nothing at all on OpenSearch (`services/object_sets.py`, and
 * `docs/decisions/0006-typed-instance-properties.md` for what would change it).
 *
 * Clicking a cell narrows, by the same mechanism the chart's drill-down uses:
 * it writes equality *clauses* into a variable a `narrow_set` derivation
 * reads. Two clauses rather than one is the only difference — a cell is the
 * intersection of a row and a column, which is exactly what it looks like.
 */
export function CanvasPivotTable({
  objectSetVariable = null,
  rowProperty = null,
  columnProperty = null,
  drilldownVariable = null,
  title = "",
}: {
  objectSetVariable?: string | null;
  rowProperty?: string | null;
  columnProperty?: string | null;
  /** Where a click on a cell or a header writes its clauses. Same mechanism as
   *  the chart's drill-down, and clauses for the same reason: object sets
   *  resolve on the server, so a widget that wrote one would be a second place
   *  sets come from with no rule for which wins. */
  drilldownVariable?: string | null;
  title?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const definition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();
  const { set: setParameter } = useCanvasParameters();
  const drilled = useCanvasParameter(drilldownVariable);

  const ready = !!objectSetVariable && !!rowProperty && !!columnProperty;
  const grid = useQuery({
    queryKey: [
      "canvas-pivot", objectSetVariable, JSON.stringify(definition ?? null),
      rowProperty, columnProperty,
    ],
    queryFn: () =>
      objApi.crossTabObjectSet(workspaceId, definition, rowProperty!, columnProperty!),
    enabled: ready && !!definition,
  });

  const canDrill = ready && !!drilldownVariable;
  // What is currently narrowed, read back out of the variable this widget
  // writes rather than held beside it — so the grid reflects the document's
  // state, including a clause a Filter List set.
  const pick: PivotPick = (() => {
    const found: PivotPick = { row: null, column: null };
    for (const clause of Array.isArray(drilled) ? drilled : []) {
      const c = clause as { property?: string; op?: string; value?: unknown };
      if (c.op !== "eq") continue;
      if (c.property === rowProperty) found.row = String(c.value);
      if (c.property === columnProperty) found.column = String(c.value);
    }
    return found;
  })();

  const apply = (next: PivotPick) => {
    // Clicking what is already picked clears it. Without that there is no way
    // back out from inside the grid, and a filter you cannot remove is one you
    // have to remember you applied.
    const same = next.row === pick.row && next.column === pick.column;
    setParameter(
      drilldownVariable!,
      same ? [] : pivotClauses(next, rowProperty!, columnProperty!),
    );
  };

  const data = grid.data;
  const covered = data ? data.cells.reduce((t, row) => t + row.reduce((a, b) => a + b, 0), 0) : 0;

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {title && <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>{title}</h3>}
      {!ready && (
        <p className="canvas-widget-empty">
          Pivot table - point it at an object set and pick two properties in Settings
        </p>
      )}
      {ready && (variablesPending || grid.isPending) && (
        <p className="canvas-widget-empty">Loading…</p>
      )}
      {grid.isError && (
        <p className="canvas-widget-empty">
          {grid.error instanceof ApiError ? grid.error.message : "Couldn't build this pivot."}
        </p>
      )}
      {data && (
        <>
          <div className="canvas-pivot-scroll">
            <table className="canvas-pivot">
              <thead>
                <tr>
                  <th scope="col" className="canvas-pivot-corner">
                    {rowProperty} \ {columnProperty}
                  </th>
                  {data.columns.map((column) => (
                    <th key={column.value} scope="col">
                      <PivotHeading
                        label={column.value}
                        count={column.count}
                        selected={pick.column === column.value && pick.row === null}
                        onPick={
                          canDrill
                            ? () => apply({ row: null, column: column.value })
                            : undefined
                        }
                        describe={`${columnProperty} = ${column.value}`}
                      />
                    </th>
                  ))}
                  <th scope="col" className="canvas-pivot-total">Total</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, r) => (
                  <tr key={row.value}>
                    <th scope="row">
                      <PivotHeading
                        label={row.value}
                        count={row.count}
                        selected={pick.row === row.value && pick.column === null}
                        onPick={
                          canDrill ? () => apply({ row: row.value, column: null }) : undefined
                        }
                        describe={`${rowProperty} = ${row.value}`}
                      />
                    </th>
                    {data.columns.map((column, c) => {
                      const count = data.cells[r]?.[c] ?? 0;
                      const selected = pick.row === row.value && pick.column === column.value;
                      return (
                        <td
                          key={column.value}
                          className={`canvas-pivot-cell${selected ? " selected" : ""}`}
                        >
                          {/* An empty cell is not a click target: narrowing to
                              nothing is a thing a viewer can do by accident and
                              never on purpose. */}
                          {canDrill && count > 0 ? (
                            <button
                              type="button"
                              aria-pressed={selected}
                              aria-label={`Filter to ${rowProperty} = ${row.value}, ${columnProperty} = ${column.value}`}
                              onClick={() => apply({ row: row.value, column: column.value })}
                            >
                              {count.toLocaleString()}
                            </button>
                          ) : (
                            count.toLocaleString()
                          )}
                        </td>
                      );
                    })}
                    <td className="canvas-pivot-total">{row.count.toLocaleString()}</td>
                  </tr>
                ))}
                <tr className="canvas-pivot-total">
                  <th scope="row">Total</th>
                  {data.columns.map((column) => (
                    <td key={column.value}>{column.count.toLocaleString()}</td>
                  ))}
                  <td>{data.total.toLocaleString()}</td>
                </tr>
              </tbody>
            </table>
          </div>
          {data.rows.length === 0 && <p className="canvas-widget-empty">Nothing in this set.</p>}
          {/* The margins are whole rows and whole columns, so they can exceed
              the cells. Said once, with the gap named, rather than left for a
              viewer to find by adding up a row. */}
          {covered < data.total && (
            <p className="canvas-widget-empty">
              Totals count every object; the cells count objects with both values.{" "}
              {(data.total - covered).toLocaleString()} of {data.total.toLocaleString()} are
              outside the grid.
            </p>
          )}
          {(data.rows_truncated || data.columns_truncated) && (
            <p className="canvas-widget-empty">
              {data.rows_truncated &&
                `Showing the largest ${data.rows.length} of ${data.row_distinct_total.toLocaleString()} ${rowProperty} values. `}
              {data.columns_truncated &&
                `Showing the largest ${data.columns.length} of ${data.column_distinct_total.toLocaleString()} ${columnProperty} values.`}
            </p>
          )}
          {canDrill && (pick.row !== null || pick.column !== null) && (
            <p className="canvas-widget-empty">
              Narrowed to{" "}
              {[
                pick.row !== null ? `${rowProperty} = ${pick.row}` : null,
                pick.column !== null ? `${columnProperty} = ${pick.column}` : null,
              ]
                .filter(Boolean)
                .join(" and ")}
              .{" "}
              <button
                type="button"
                className="btn quiet"
                style={{ padding: "1px 7px", fontSize: 12 }}
                onClick={() => setParameter(drilldownVariable!, [])}
              >
                Clear
              </button>
            </p>
          )}
        </>
      )}
    </div>
  );
}

/** An axis heading: the value, its whole count, and a click that narrows to it
 *  where something is wired to receive that. */
function PivotHeading({
  label, count, selected, onPick, describe,
}: {
  label: string;
  count: number;
  selected: boolean;
  onPick?: () => void;
  describe: string;
}) {
  const inner = (
    <>
      {label} <span className="canvas-pivot-count">{count.toLocaleString()}</span>
    </>
  );
  if (!onPick) return <>{inner}</>;
  return (
    <button type="button" aria-pressed={selected} aria-label={`Filter to ${describe}`} onClick={onPick}>
      {inner}
    </button>
  );
}

function PivotTableSettings() {
  const { workspaceId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    objectSetVariable, rowProperty, columnProperty, drilldownVariable, title,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    rowProperty: node.data.props.rowProperty,
    columnProperty: node.data.props.columnProperty,
    drilldownVariable: node.data.props.drilldownVariable,
    title: node.data.props.title,
  }));
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const clauseVariables = Object.values(declared).filter(
    (v) => v.kind === "array" && !v.derivation,
  );
  const typeId = (resolved[objectSetVariable as string] as
    { object_type_id?: string } | undefined)?.object_type_id;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const properties = type.data?.properties ?? [];

  // All three of p.65's sections, and this is the widget that shows why they
  // are three: the set populates the grid, the two axes are what that set
  // makes answerable, and the drill-down variable is "the data that is then
  // produced and output by the widget".
  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Object set</span>
        <select
          value={objectSetVariable || ""}
          onChange={(e) =>
            setProp((p: Record<string, unknown>) => {
              p.objectSetVariable = e.target.value || null;
              // Property names mean nothing against another type.
              p.rowProperty = null;
              p.columnProperty = null;
            })
          }
        >
          <option value="">Choose…</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Rows</span>
        <select
          value={rowProperty || ""}
          disabled={!type.data}
          onChange={(e) =>
            setProp((p: { rowProperty: string | null }) => (p.rowProperty = e.target.value || null))
          }
        >
          <option value="">Choose…</option>
          {properties.map((prop) => (
            <option key={prop.api_name} value={prop.api_name}>{prop.api_name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Columns</span>
        <select
          value={columnProperty || ""}
          disabled={!type.data}
          onChange={(e) =>
            setProp((p: { columnProperty: string | null }) =>
              (p.columnProperty = e.target.value || null))
          }
        >
          <option value="">Choose…</option>
          {/* The row property is not offered here: a cross-tab of a property
              against itself is its own diagonal, and the server refuses it.
              Not offering it beats a control that 422s. */}
          {properties.filter((prop) => prop.api_name !== rowProperty).map((prop) => (
            <option key={prop.api_name} value={prop.api_name}>{prop.api_name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          type="text"
          value={title || ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      </>}
      outputs={<>
      <label className="field">
        <span className="field-label">Clicking a cell writes to</span>
        <select
          value={drilldownVariable || ""}
          onChange={(e) =>
            setProp((p: { drilldownVariable: string | null }) =>
              (p.drilldownVariable = e.target.value || null))
          }
        >
          <option value="">Nothing - the grid is a report</option>
          {clauseVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {clauseVariables.length === 0
            ? "Declare an array variable, and derive a narrowed set from it"
            : "Give this its own variable, and chain the narrow_set derivations"}
        </span>
      </label>
      </>}
    />
  );
}

CanvasPivotTable.craft = {
  displayName: "Pivot table",
  props: {
    objectSetVariable: null, rowProperty: null, columnProperty: null,
    drilldownVariable: null, title: "",
  },
  related: { settings: PivotTableSettings },
};

// ---- Time series (roadmap 1.5) ----------------------------------------------
/**
 * How many objects in a set last changed in each time bucket.
 *
 * **It plots `updated_at`, and it says so on the widget.** That is a real
 * limitation rather than a stand-in for a business date: a resync moves every
 * object in a set to today, so this answers *"what has been changing"* and not
 * *"when did things happen"*. The two look identical as a line, which is why
 * the caption is not optional — a viewer who reads this as an events-over-time
 * chart has been misled by the shape.
 *
 * A date *property* is the other question and is blocked: properties are
 * stored untyped, so bucketing one means guessing whether "03/04" is March or
 * April, and the two stores would guess differently
 * (`docs/decisions/0006-typed-instance-properties.md`).
 *
 * **No drill-down, deliberately.** Every narrowing widget writes property
 * equality clauses; a time bucket is a *range* over a system field, which is
 * not in that vocabulary and would need the ordered operators the same
 * decision holds. Inventing a second narrowing mechanism for one widget would
 * be two answers to one question — the same reason the scatter chart takes no
 * drill.
 *
 * The line itself is the existing `Chart`, not a second renderer: gaps are
 * already filled by the server, so a plain line over the points is correct.
 */
const SERIES_INTERVALS = ["day", "week", "month"] as const;

export function CanvasTimeSeries({
  objectSetVariable = null,
  interval = "day",
  title = "",
}: {
  objectSetVariable?: string | null;
  interval?: string;
  title?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const definition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();

  const series = useQuery({
    queryKey: [
      "canvas-series", objectSetVariable, JSON.stringify(definition ?? null), interval,
    ],
    queryFn: () => objApi.timeSeriesObjectSet(workspaceId, definition, interval),
    enabled: !!objectSetVariable && !!definition,
  });

  const points = (series.data?.points ?? []).map((p) => ({
    label: seriesLabel(p.start, series.data!.interval),
    value: p.count,
  }));

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {title && <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>{title}</h3>}
      {!objectSetVariable && (
        <p className="canvas-widget-empty">
          Time series - point it at an object set in Settings
        </p>
      )}
      {objectSetVariable && (variablesPending || series.isPending) && (
        <p className="canvas-widget-empty">Loading…</p>
      )}
      {series.isError && (
        // The server's own sentence: "that range is more than 200 day buckets"
        // tells a builder which control to change, where "couldn't load" does
        // not.
        <p className="canvas-widget-empty">
          {series.error instanceof ApiError
            ? series.error.message
            : "Couldn't build this series."}
        </p>
      )}
      {series.data && points.length === 0 && (
        <p className="canvas-widget-empty">Nothing in this set.</p>
      )}
      {series.data && points.length > 0 && (
        <>
          <Chart kind="line" points={points} />
          {/* Not a tooltip and not optional. A line of counts over time reads
              as "when these things happened" unless it says otherwise, and it
              is not that. */}
          <p className="canvas-widget-empty">
            When each object last changed, by {series.data.interval}, in UTC -
            not a business date.{" "}
            {series.data.total.toLocaleString()} objects across {points.length}{" "}
            {series.data.interval}
            {points.length === 1 ? "" : "s"}.
          </p>
        </>
      )}
    </div>
  );
}

function TimeSeriesSettings() {
  const { declared } = useCanvasVariables();
  const {
    objectSetVariable, interval, title,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    interval: node.data.props.interval,
    title: node.data.props.title,
  }));
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");

  // No outputs: this widget reads a set and draws it. An empty Outputs
  // heading would promise a control that does not exist.
  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Object set</span>
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
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Bucket</span>
        <select
          value={interval || "day"}
          onChange={(e) => setProp((p: { interval: string }) => (p.interval = e.target.value))}
        >
          {SERIES_INTERVALS.map((i) => (
            <option key={i} value={i}>{`By ${i}`}</option>
          ))}
        </select>
        {/* There is no property picker here on purpose, and the absence needs
            explaining or it reads as an oversight. */}
        <span className="field-hint">
          Plots when each object last changed. Bucketing by a date property
          needs the declared property type behind it (decision 0006).
        </span>
      </label>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          type="text"
          value={title || ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      </>}
    />
  );
}

CanvasTimeSeries.craft = {
  displayName: "Time series",
  props: { objectSetVariable: null, interval: "day", title: "" },
  related: { settings: TimeSeriesSettings },
};


// ---- embedded module (roadmap 1.5, priority 4) -------------------------------
/**
 * One Workshop module inside another.
 *
 * **The inner module is shown, not edited.** Its `<Editor>` is always
 * `enabled={false}`, in the builder as well as the viewer: editing a module
 * means opening it, and a nested editable canvas would put two documents' undo
 * stacks, selections and drag targets on one screen with no way to say which
 * one a gesture meant.
 *
 * **It resolves its own variables, and shares none with its host.** A shared
 * namespace would collide the first time two modules both declared `v_filter`,
 * and the collision would be silent — the inner module would quietly read the
 * outer one's value and look like it was working. Passing values in needs an
 * explicit mapping, which is a format change and its own item; until then the
 * boundary is a wall rather than a leak, and the Settings panel says so.
 *
 * **What may be embedded is settled on the server** (`routes/canvas.py`): a
 * module cannot embed itself, close a cycle, name a module outside its
 * project, or nest deeper than three. Those are refused when the *author*
 * saves, because a cycle discovered here would be a browser that hangs and a
 * viewer who cannot do anything about it.
 */
export function CanvasEmbeddedModule({
  moduleId = null,
  title = "",
  interface: mapping = {},
}: {
  moduleId?: string | null;
  title?: string;
  /** child external ID -> host variable id. Keyed by external ID because that
   * is the name the child publishes; the host side is a variable id because
   * that is what this document uses everywhere else. */
  interface?: Record<string, string>;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  // The host's side of the boundary. `resolved` rather than raw values because
  // the host's *definition* is what backs a mapped variable (p.127) - and a
  // definition's output is its resolved value, not whatever a widget last typed
  // into it. `set` is the write path back, which is what makes the sharing
  // two-way: "any change to a variable value in either the child or parent
  // module will be reflected in all modules where the variable is mapped".
  const host = useCanvasVariables();
  const hostParams = useCanvasParameters();

  const embedded = useQuery({
    queryKey: ["canvas-embedded", workspaceId, projectId, moduleId],
    queryFn: () => canvasApi.get(workspaceId, projectId, moduleId!),
    enabled: !!moduleId,
  });

  const definition = embedded.data?.definition;
  const layout = definition ? layoutOf(definition) : null;
  const childVariables = definition ? variablesOf(definition) : {};

  // The mapping arrives keyed by external ID; everything downstream works in
  // variable ids, so it is translated once, here. An external ID the child no
  // longer publishes simply drops out - the save path refuses that document,
  // but a child edited *after* the host was saved can still produce one, and a
  // viewer should get a module missing one input rather than a crash.
  const bindings: Record<string, string> = {};
  for (const [externalId, hostVid] of Object.entries(mapping)) {
    if (!hostVid) continue;
    const target = Object.values(childVariables).find((v) => v.external_id === externalId);
    if (target) bindings[target.id] = hostVid;
  }
  const boundIds = Object.keys(bindings);

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {title && <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>{title}</h3>}
      {!moduleId && (
        <p className="canvas-widget-empty">
          Embedded module - choose one in Settings
        </p>
      )}
      {moduleId && embedded.isPending && <p className="canvas-widget-empty">Loading…</p>}
      {embedded.isError && (
        // Names the module rather than saying "something went wrong": the most
        // likely cause is a viewer who cannot open it, and that is worth being
        // able to tell apart from a module that is broken.
        <p className="canvas-widget-empty">
          {embedded.error instanceof ApiError && embedded.error.status === 403
            ? "You do not have access to the module embedded here."
            : "Couldn't load the embedded module."}
        </p>
      )}
      {layout && Object.keys(layout).length === 0 && (
        <p className="canvas-widget-empty">
          {embedded.data?.name ?? "That module"} has nothing on it yet.
        </p>
      )}
      {layout && Object.keys(layout).length > 0 && (
        <div
          className="canvas-embedded"
          data-module={moduleId ?? ""}
          data-bound={boundIds.join(",")}
        >
          {/* Its own parameter scope, linked to the host for exactly the
              variables that were mapped. Everything else stays private, which
              is what keeps two modules that both declare `v_filter` from
              silently reading each other's value. */}
          <CanvasParameterProvider
            link={{ bindings, values: host.resolved, set: hostParams.set }}
          >
            {/* Its own bridge, so the inner module's variables resolve against
                the inner module. Sharing the outer one would resolve the wrong
                declarations against the wrong document. */}
            <VariableBridge
              workspaceId={workspaceId}
              projectId={projectId}
              appId={moduleId!}
              declared={childVariables}
              events={eventsOf(definition) as never}
              bound={boundIds}
            >
              <Editor resolver={CANVAS_RESOLVER} enabled={false} onRender={CanvasNode}>
                <Frame data={JSON.stringify(layout)} />
              </Editor>
            </VariableBridge>
          </CanvasParameterProvider>
        </div>
      )}
    </div>
  );
}

function EmbeddedModuleSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    moduleId, title,
    actions: { setProp },
  } = useNode((node) => ({
    moduleId: node.data.props.moduleId,
    title: node.data.props.title,
  }));
  const apps = useQuery({
    queryKey: ["canvas-apps", workspaceId, projectId],
    queryFn: () => canvasApi.list(workspaceId, projectId),
  });

  // p.127 puts the disclosure in its own words, and puts the mapping on the
  // configuration side while it is at it: "Once a child module is selected,
  // the module interface for the child module will be shown in the widget
  // **configuration panel**." Before a module is chosen there is no interface
  // to map onto - `InterfaceMapping` used to answer that by rendering `null`,
  // which is the silent version of the same thing.
  return (
    <WidgetSetup
      bindings={{ moduleId }}
      requires={["moduleId"]}
      labels={{ moduleId: "a module" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Module</span>
        <select
          value={moduleId || ""}
          onChange={(e) =>
            setProp((p: { moduleId: string | null }) => (p.moduleId = e.target.value || null))
          }
        >
          <option value="">Choose…</option>
          {(apps.data ?? []).map((app) => (
            <option key={app.id} value={app.id}>{app.name}</option>
          ))}
        </select>
      </label>
      </>}
      configuration={<>
      <InterfaceMapping moduleId={moduleId} />
      <label className="field">
        <span className="field-label">Title</span>
        <input
          type="text"
          value={title || ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      </>}
    />
  );
}

/** The child's interface, and what this module passes into it (Foundry p.127).
 *
 * > "Once a child module is selected, the module interface for the child module
 * > will be shown in the widget configuration panel. This allows you to map
 * > parent module variables to child module interface variables."
 *
 * Only same-kind host variables are offered per row, because a mismatch is a
 * save the API refuses — offering it here would be building a dropdown whose
 * purpose is to produce an error. The other three refusals cannot be prevented
 * by a dropdown and are left to the API, which is where they belong. */
function InterfaceMapping({
  moduleId,
  except = null,
}: {
  moduleId: string | null;
  /** An external ID the caller configures itself, so it is not offered twice.
   * A Loop layout owns its item variable - it supplies one object per copy -
   * and listing it here as well would be two controls writing one mapping. */
  except?: string | null;
}) {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    mapping,
    actions: { setProp },
  } = useNode((node) => ({ mapping: node.data.props.interface ?? {} }));
  const hostVariables = useCanvasVariables().declared;

  const child = useQuery({
    queryKey: ["canvas-embedded", workspaceId, projectId, moduleId],
    queryFn: () => canvasApi.get(workspaceId, projectId, moduleId!),
    enabled: !!moduleId,
  });

  if (!moduleId) return null;
  if (child.isPending) return <p className="field-hint">Loading its interface…</p>;

  const published = Object.values(
    child.data?.definition ? variablesOf(child.data.definition) : {},
  ).filter((v) => v.interface && v.external_id && v.external_id !== except);

  if (published.length === 0) {
    return (
      <p className="field-hint">
        That module publishes no interface variables, so nothing can be passed
        into it. A variable joins the interface by being given an external ID
        with the interface toggle on.
      </p>
    );
  }

  return (
    <div className="field" data-testid="embed-interface">
      <span className="field-label">Passed into it</span>
      {published.map((variable) => {
        const externalId = variable.external_id!;
        const compatible = Object.values(hostVariables).filter((h) => h.kind === variable.kind);
        return (
          <label key={externalId} className="field">
            <span className="field-label">
              {variable.interface?.display_name || variable.label}
              {variable.interface?.required && <em> (required)</em>}
            </span>
            <select
              value={(mapping as Record<string, string>)[externalId] ?? ""}
              data-testid={`embed-map-${externalId}`}
              onChange={(e) =>
                setProp((p: { interface?: Record<string, string> }) => {
                  const next = { ...(p.interface ?? {}) };
                  if (e.target.value) next[externalId] = e.target.value;
                  else delete next[externalId];
                  p.interface = next;
                })
              }
            >
              <option value="">Not passed — it uses its own definition</option>
              {compatible.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.label}
                </option>
              ))}
            </select>
            {variable.interface?.description && (
              <span className="field-hint">{variable.interface.description}</span>
            )}
            {compatible.length === 0 && (
              <span className="field-hint">
                This module has no {variable.kind} variable to pass in.
              </span>
            )}
          </label>
        );
      })}
      {/* The consequence people get backwards, said where the choice is made. */}
      <span className="field-hint">
        A mapped variable is backed by <em>this</em> module&apos;s definition — the
        embedded module&apos;s own default and derivation are ignored for it.
      </span>
    </div>
  );
}

CanvasEmbeddedModule.craft = {
  displayName: "Embedded module",
  props: { moduleId: null, title: "", interface: {} },
  related: { settings: EmbeddedModuleSettings },
};

// ---- Loop layout (parity workshop.md §1.3; Foundry p.129-136) ---------------
/**
 * One embedded module per object in a set.
 *
 * > "Loop layouts allow you to loop over an object set or array, displaying an
 * > embedded module for each object in the set or each entry in the array used
 * > as input." (p.129)
 *
 * **Why this is not just a card list.** An Object Table or Card List has a
 * fixed set of features; a loop layout renders a whole *module* per object, so
 * "any feature combination available in Workshop" can be used for each one
 * (p.129) — its own widgets, its own events, its own actions. Foundry's own
 * example is a kanban board where each ticket is a module instance.
 *
 * **It was unblocked by the module interface**, not built alongside it: p.135
 * says loop variable mapping "works the same way as the embedded module
 * interface configuration", so this is that mechanism applied per row rather
 * than a second one.
 *
 * **The loop variable is per-instance; every other mapping is shared.** p.135
 * is explicit — the other interface variables are "the same variable reference
 * for each looped instance, allowing variable state to be shared across looped
 * instances and the parent module". So the object goes in as a seeded value on
 * a provider keyed by the object's own id, and everything else goes through the
 * host link that `CanvasEmbeddedModule` already uses.
 *
 * **Sorting is not offered**, and that is decision 0006 rather than an
 * omission: properties are stored untyped, so an ordered comparison means one
 * thing on Postgres and another on OpenSearch. p.132 also notes Foundry applies
 * a primary key sort behind any user sort "to ensure a consistent ordering" —
 * which is what the object set evaluation already does, so the order is stable
 * even without the control.
 */
export function CanvasLoopSection({
  source = "object_set",
  arrayVariable = null,
  objectSetVariable = null,
  moduleId = null,
  itemVariable = null,
  interface: mapping = {},
  paging = "limit",
  maxItems = 12,
  pageSize = 12,
  display = "list",
  maxColumns = 3,
  minCardWidth = 220,
}: {
  /** p.133's two sources. An older document has no `source` at all, which is
   * why the default is the arm that already existed rather than a required
   * choice — adding this setting must not change what a saved module does. */
  source?: "object_set" | "array";
  /** p.133: "the first configuration is the array to loop through". */
  arrayVariable?: string | null;
  objectSetVariable?: string | null;
  moduleId?: string | null;
  /** The child's interface variable, by external ID, that receives each object. */
  itemVariable?: string | null;
  interface?: Record<string, string>;
  paging?: "limit" | "paged";
  maxItems?: number;
  pageSize?: number;
  display?: "list" | "grid";
  maxColumns?: number;
  minCardWidth?: number;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId, mode } = useCanvasEnv();
  const host = useCanvasVariables();
  const hostParams = useCanvasParameters();

  const definition = useCanvasVariable(objectSetVariable);
  const child = useQuery({
    queryKey: ["canvas-embedded", workspaceId, projectId, moduleId],
    queryFn: () => canvasApi.get(workspaceId, projectId, moduleId!),
    enabled: !!moduleId,
  });
  const childVariables = child.data?.definition ? variablesOf(child.data.definition) : {};
  const byExternalId = (externalId: string | null) =>
    externalId
      ? Object.values(childVariables).find((v) => v.external_id === externalId) ?? null
      : null;

  const itemTarget = byExternalId(itemVariable);
  // Everything except the loop variable, resolved the same way the Embedded
  // Module widget resolves its mapping.
  const shared: Record<string, string> = {};
  for (const [externalId, hostVid] of Object.entries(mapping)) {
    if (!hostVid || externalId === itemVariable) continue;
    const target = byExternalId(externalId);
    if (target) shared[target.id] = hostVid;
  }

  // `limit` shows one page of at most `maxItems`; `paged` walks the set
  // (p.134). Both are a page size to `useSetPage`; only the controls differ.
  const size = paging === "paged" ? Math.max(1, pageSize) : Math.max(1, maxItems);
  const page = useSetPage(workspaceId, definition, {
    pageSize: size,
    variablesPending: host.pending,
  });

  // p.133's array arm. Its entries are already resolved and in memory, so
  // paging is a slice - see `loop-array.ts` for why position is the key.
  const overArray = source === "array";
  const [arrayPage, setArrayPage] = useState(0);
  const entries = arrayEntries(overArray ? host.resolved[arrayVariable ?? ""] : undefined);
  const arraySlice = pageOf(entries, { paging, maxItems, pageSize, page: arrayPage });

  const layout = child.data?.definition ? layoutOf(child.data.definition) : null;
  const sourceChosen = overArray ? !!arrayVariable : !!objectSetVariable;
  const ready = sourceChosen && !!moduleId && !!itemTarget && !!layout;

  if (mode === "edit" && !ready) {
    return (
      <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
        <p className="canvas-widget-empty">
          {!sourceChosen
            ? overArray
              ? "Loop — choose an array in Settings"
              : "Loop — choose an object set in Settings"
            : !moduleId
              ? "Loop — choose a module to repeat"
              : !itemTarget
                ? `Loop — choose which of that module's interface variables receives each ${overArray ? "entry" : "object"}`
                : "Loading…"}
        </p>
      </div>
    );
  }

  // One list for both arms, so everything below this line is written once.
  // The key is the object's id for a set and the entry's **position** for an
  // array (p.133 orders copies by position, and an array may hold the same
  // value twice - keying by value would collapse two copies into one).
  const copies: { key: string; seed: unknown }[] = overArray
    ? arraySlice.rows.map((row) => ({ key: `entry-${row.index}`, seed: row.value }))
    : (page.rows ?? []).map((instance) => ({
        key: instance.id,
        seed: selectionOf(instance, page.typeId).object,
      }));
  const rows = copies;
  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!overArray && page.unresolved && <p className="canvas-widget-empty">Loading…</p>}
      {!overArray && page.isError && (
        <p className="canvas-widget-empty">Couldn&apos;t load the objects to loop over.</p>
      )}
      {ready && rows.length === 0 && (overArray || (!page.unresolved && !page.isError)) && (
        <p className="canvas-widget-empty">
          {overArray ? "Nothing in that array." : "Nothing in that set."}
        </p>
      )}
      {ready && (
        <div
          className={`canvas-loop canvas-loop--${display}`}
          data-count={rows.length}
          style={
            display === "grid"
              ? {
                  // `auto-fill` with a floor rather than a fixed column count:
                  // p.134 configures *both* a max column count and a minimum
                  // card width, and a card narrower than its minimum is the
                  // failure the minimum exists to prevent - so the width wins
                  // and the maximum caps what a wide screen does with the room.
                  gridTemplateColumns: `repeat(auto-fill, minmax(${minCardWidth}px, 1fr))`,
                  maxWidth: maxColumns > 0 ? maxColumns * (minCardWidth + 12) : undefined,
                }
              : undefined
          }
        >
          {rows.map((copy) => (
            <div className="canvas-loop-item" key={copy.key}>
              {/* Keyed by the object's id, so each object gets its own provider
                  and its own layout state - p.129: each instance "functions
                  independently from other embedded module instances, and has
                  its own variable scope and layout state". A shared provider
                  would make selecting a row in one card select it in all. */}
              <CanvasParameterProvider
                seed={{ [itemTarget!.id]: copy.seed }}
                link={{ bindings: shared, values: host.resolved, set: hostParams.set }}
              >
                <VariableBridge
                  workspaceId={workspaceId}
                  projectId={projectId}
                  appId={moduleId!}
                  declared={childVariables}
                  events={eventsOf(child.data!.definition) as never}
                  bound={[itemTarget!.id, ...Object.keys(shared)]}
                >
                  <Editor resolver={CANVAS_RESOLVER} enabled={false} onRender={CanvasNode}>
                    <Frame data={JSON.stringify(layout)} />
                  </Editor>
                </VariableBridge>
              </CanvasParameterProvider>
            </div>
          ))}
        </div>
      )}
      {ready && overArray && paging === "paged" && arraySlice.pageCount > 1 && (
        <div className="canvas-loop-pager">
          <button
            type="button"
            className="btn quiet"
            disabled={arrayPage === 0}
            onClick={() => setArrayPage((n) => Math.max(0, n - 1))}
          >
            Previous
          </button>
          <span className="soft">
            Page {Math.min(arrayPage, arraySlice.pageCount - 1) + 1} of {arraySlice.pageCount}
          </span>
          <button
            type="button"
            className="btn quiet"
            disabled={arrayPage >= arraySlice.pageCount - 1}
            onClick={() => setArrayPage((n) => n + 1)}
          >
            Next
          </button>
        </div>
      )}
      {ready && !overArray && paging === "paged" && (page.total ?? 0) > size && (
        <div className="canvas-loop-pager">
          <button
            type="button"
            className="btn quiet"
            disabled={page.offset === 0}
            onClick={() => page.setOffset(Math.max(0, page.offset - size))}
          >
            Previous
          </button>
          <span className="soft">
            {page.offset + 1}–{Math.min(page.offset + size, page.total ?? 0)} of {page.total}
          </span>
          <button
            type="button"
            className="btn quiet"
            disabled={page.offset + size >= (page.total ?? 0)}
            onClick={() => page.setOffset(page.offset + size)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function LoopSectionSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    source, arrayVariable,
    objectSetVariable, moduleId, itemVariable, mapping,
    paging, maxItems, pageSize, display, maxColumns, minCardWidth,
    actions: { setProp },
  } = useNode((node) => ({
    source: node.data.props.source ?? "object_set",
    arrayVariable: node.data.props.arrayVariable,
    objectSetVariable: node.data.props.objectSetVariable,
    moduleId: node.data.props.moduleId,
    itemVariable: node.data.props.itemVariable,
    mapping: node.data.props.interface ?? {},
    paging: node.data.props.paging,
    maxItems: node.data.props.maxItems,
    pageSize: node.data.props.pageSize,
    display: node.data.props.display,
    maxColumns: node.data.props.maxColumns,
    minCardWidth: node.data.props.minCardWidth,
  }));
  const { declared } = useCanvasVariables();
  const apps = useQuery({
    queryKey: ["canvas-apps", workspaceId, projectId],
    queryFn: () => canvasApi.list(workspaceId, projectId),
  });
  const child = useQuery({
    queryKey: ["canvas-embedded", workspaceId, projectId, moduleId],
    queryFn: () => canvasApi.get(workspaceId, projectId, moduleId!),
    enabled: !!moduleId,
  });
  const published = Object.values(
    child.data?.definition ? variablesOf(child.data.definition) : {},
  ).filter((v) => v.interface && v.external_id);
  // p.134: the child "must have a module interface object set variable if
  // configured to loop over an object set". Ours is `single_object`, which is
  // the kind that actually describes one object - see the spec note.
  // p.134: the child needs "a module interface object set variable if
  // configured to loop over an object set, or a variable typed to the array
  // type if configured to loop over an array" - and p.134 settles what "the
  // array type" means two sentences later, where the struct-typed variable
  // renders *each entry*. So the candidates are the elements' kind, and an
  // untyped array offers none, which is what the server refuses at save.
  const overArray = source === "array";
  const looped = overArray
    ? Object.values(declared).find((v) => v.id === arrayVariable) ?? null
    : null;
  const itemKind = overArray ? looped?.element ?? null : "single_object";
  const candidates = itemKind ? published.filter((v) => v.kind === itemKind) : [];

  // **The widget that needs `requires` in its original all-of form.** §179
  // taught it a choice for the Object table, which takes an object set *or* an
  // object type; a Loop takes a set *and* a module, and neither alone leaves
  // anything to configure - "Receives each object" reads the module's published
  // interface (p.134) and the paging options count items from the set.
  return (
    <WidgetSetup
      bindings={overArray ? { arrayVariable, moduleId } : { objectSetVariable, moduleId }}
      requires={overArray ? ["arrayVariable", "moduleId"] : ["objectSetVariable", "moduleId"]}
      labels={{
        objectSetVariable: "an object set",
        arrayVariable: "an array",
        moduleId: "a module",
      }}
      inputs={<>
      {/* p.133's two sources. First, because everything below it depends on
          which one is chosen - the thing being looped, and then which of the
          child's variables can receive an entry. */}
      <label className="field">
        <span className="field-label">Loop over</span>
        <select
          value={source}
          data-testid="loop-source"
          onChange={(e) => {
            const next = e.target.value;
            setProp((p: Record<string, unknown>) => {
              p.source = next;
              // The old source's binding is cleared, and so is the item
              // variable: it was chosen to match the *other* kind, and a
              // stale one would be a mapping the server refuses at save with
              // a message about the child rather than about this switch.
              p.objectSetVariable = null;
              p.arrayVariable = null;
              p.itemVariable = null;
            });
          }}
        >
          <option value="object_set">An object set</option>
          <option value="array">An array</option>
        </select>
      </label>

      {overArray ? (
        <label className="field">
          <span className="field-label">Array to loop through</span>
          <select
            value={arrayVariable ?? ""}
            data-testid="loop-array"
            onChange={(e) =>
              setProp((p: { arrayVariable: string | null }) =>
                (p.arrayVariable = e.target.value || null))
            }
          >
            <option value="">Choose…</option>
            {Object.values(declared)
              .filter((v) => v.kind === "array")
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}{v.element ? ` (${v.element})` : " — untyped"}
                </option>
              ))}
          </select>
          {/* Named rather than hidden: an untyped array is offered because it
              is a real variable an author may have meant to type, and saying
              why it cannot be used beats leaving it off the list with no
              explanation. */}
          {looped && !looped.element && (
            <span className="field-hint">
              That array has no entry type, so nothing can receive an entry. Set one
              on the variable first (p.132).
            </span>
          )}
        </label>
      ) : (
        <label className="field">
          <span className="field-label">Object set to loop through</span>
          <select
            value={objectSetVariable ?? ""}
            data-testid="loop-set"
            onChange={(e) =>
              setProp((p: { objectSetVariable: string | null }) =>
                (p.objectSetVariable = e.target.value || null))
            }
          >
            <option value="">Choose…</option>
            {Object.values(declared)
              .filter((v) => v.kind === "object_set")
              .map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
          </select>
        </label>
      )}

      <label className="field">
        <span className="field-label">Module to repeat</span>
        <select
          value={moduleId ?? ""}
          data-testid="loop-module"
          onChange={(e) =>
            setProp((p: { moduleId: string | null }) => (p.moduleId = e.target.value || null))
          }
        >
          <option value="">Choose…</option>
          {(apps.data ?? []).map((app) => (
            <option key={app.id} value={app.id}>{app.name}</option>
          ))}
        </select>
      </label>
      </>}
      configuration={<>
      {/* No `moduleId &&` guard any more: this whole section only renders once
          `requires` is satisfied, and a module is half of that. Two spellings
          of one rule, and §170's precedent says delete the redundant one. */}
      <label className="field">
        <span className="field-label">
          Receives each {overArray ? "entry" : "object"}
        </span>
        <select
          value={itemVariable ?? ""}
          data-testid="loop-item"
          onChange={(e) =>
            setProp((p: { itemVariable: string | null }) =>
              (p.itemVariable = e.target.value || null))
          }
        >
          <option value="">Choose…</option>
          {candidates.map((v) => (
            <option key={v.external_id} value={v.external_id!}>
              {v.interface?.display_name || v.label}
            </option>
          ))}
        </select>
        {candidates.length === 0 && (
          <span className="field-hint">
            That module publishes no single-object interface variable, so there
            is nowhere to put each object. Add one in its Variables panel.
          </span>
        )}
        {/* p.135's warning, carried across rather than left to be discovered. */}
        <span className="field-hint">
          Each copy gets its own object. Changing this variable inside the
          module itself is not supported.
        </span>
      </label>

      <label className="field">
        <span className="field-label">Paging</span>
        <select
          value={paging ?? "limit"}
          data-testid="loop-paging"
          onChange={(e) => setProp((p: { paging: string }) => (p.paging = e.target.value))}
        >
          <option value="limit">Limit — one page, up to a maximum</option>
          <option value="paged">Paged</option>
        </select>
      </label>
      {paging === "paged" ? (
        <label className="field">
          <span className="field-label">Items per page</span>
          <input
            type="number" min={1}
            value={pageSize ?? 12}
            onChange={(e) => setProp((p: { pageSize: number }) => (p.pageSize = Number(e.target.value) || 1))}
          />
        </label>
      ) : (
        <label className="field">
          <span className="field-label">Max items to display</span>
          <input
            type="number" min={1}
            value={maxItems ?? 12}
            data-testid="loop-max"
            onChange={(e) => setProp((p: { maxItems: number }) => (p.maxItems = Number(e.target.value) || 1))}
          />
        </label>
      )}

      <label className="field">
        <span className="field-label">Display</span>
        <select
          value={display ?? "list"}
          data-testid="loop-display"
          onChange={(e) => setProp((p: { display: string }) => (p.display = e.target.value))}
        >
          <option value="list">List</option>
          <option value="grid">Grid</option>
        </select>
      </label>
      {display === "grid" && (
        <>
          <label className="field">
            <span className="field-label">Max columns</span>
            <input
              type="number" min={1}
              value={maxColumns ?? 3}
              onChange={(e) => setProp((p: { maxColumns: number }) => (p.maxColumns = Number(e.target.value) || 1))}
            />
          </label>
          <label className="field">
            <span className="field-label">Min card width (px)</span>
            <input
              type="number" min={80}
              value={minCardWidth ?? 220}
              onChange={(e) => setProp((p: { minCardWidth: number }) => (p.minCardWidth = Number(e.target.value) || 80))}
            />
          </label>
        </>
      )}

      {/* The `moduleId &&` half of this condition went the same way as the one
          above; the length comparison is the part that still says something. */}
      {published.length > candidates.length && (
        <InterfaceMapping moduleId={moduleId} except={itemVariable} />
      )}

      {/* Said rather than offered. Decision 0006: properties are stored
          untyped, so an ordered comparison means one thing on Postgres and
          another on OpenSearch. */}
      <p className="field-hint">
        Sorting by a property is not available yet — see
        <code> docs/decisions/0006</code>. The order is the set&apos;s own, which
        is stable.
      </p>
      </>}
    />
  );
}

CanvasLoopSection.craft = {
  displayName: "Loop",
  props: {
    source: "object_set", arrayVariable: null,
    objectSetVariable: null, moduleId: null, itemVariable: null, interface: {},
    paging: "limit", maxItems: 12, pageSize: 12,
    display: "list", maxColumns: 3, minCardWidth: 220,
  },
  related: { settings: LoopSectionSettings },
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

  const objects = source === "objects";

  // **The first panel whose `requires` is not a literal.** Every conversion
  // before this one had one fixed set of inputs; a Map has two, and which of
  // them the configuration is waiting on depends on the toggle above them. So
  // the rule is computed from `source` - a map pointed at a dataset must not
  // sit waiting for an object type nobody is going to pick.
  //
  // "Points from" itself lives in Inputs rather than above the sections. It is
  // not a variable, but it decides *which* variable populates the widget, and
  // p.65's "the data that initially populates a widget" is the question it
  // asks the first half of.
  return (
    <WidgetSetup
      bindings={objects ? { objectSetVariable, objectTypeId } : { datasetId }}
      requires={objects ? [["objectSetVariable", "objectTypeId"]] : ["datasetId"]}
      labels={{
        objectSetVariable: "an object set",
        objectTypeId: "an object type",
        datasetId: "a dataset",
      }}
      inputs={<>
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
      {objects ? (
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
        </>
      )}
      </>}
      configuration={<>
      {objects ? (
        <>
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
          {/* **`effectiveTypeId`, not `objectTypeId`** - the options below come
              from the type behind whichever input is bound, and a map bound to
              an object set variable has no `objectTypeId` at all. Guarding on
              one of the two ways the type can arrive left this control and the
              one under it permanently disabled with their options loaded and
              sitting in the DOM, while `Location property` beside them - which
              already guarded on the right thing - worked. Three siblings
              reading one query, two of them asking the wrong question. */}
          <label className="field">
            <span className="field-label">Label property</span>
            <select
              value={labelProperty || ""}
              disabled={!effectiveTypeId}
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
              disabled={!effectiveTypeId}
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
      {/* Outside the branch, because a parameter name means the same thing to
          both sources - it is the name a Filter widget publishes. */}
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
      </>}
    />
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
  seriesVariable = null,
  drilldownVariable = null,
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
  /** A `time_series_set` variable to plot instead of either (p.280's third
   * "Data input" option: "The Time series set option allows a Workshop time
   * series set variable to be used as input. This configures a time series
   * chart, with the time range on the X axis, and the time series values of
   * the variable on the Y axis").
   *
   * **Forced to a line**, because p.281 says so — "If the data input is a time
   * series set, only the Line Chart option is supported" — and because it is
   * right: a bar per reading over an unbucketed series is a comb, and a pie of
   * readings answers nothing.
   *
   * **No drill-down**, for the reason the time series widget has none: a point
   * on a series is an *instant*, and narrowing on one would need range
   * operators the untyped-property decision holds (§87). */
  seriesVariable?: string | null;
  /** Where a click on a bar or a slice writes its clause (roadmap 1.5,
   * drill-down). Clauses rather than a set, for the reason the Filter List
   * writes clauses: object sets resolve on the server, and a widget that wrote
   * one would be a second place sets come from with no rule for which wins.
   *
   * **This is equality, which is why it is buildable and the map's area
   * selection is not.** `property = "north"` means the same thing on Postgres
   * and on OpenSearch whatever the property's declared type; `lat > 51.5`
   * does not, and that is the untyped-property blocker (§87) that also holds
   * ordered operators, numeric aggregations and property sorts. */
  drilldownVariable?: string | null;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();
  const { set: setParameter } = useCanvasParameters();
  const drilled = useCanvasParameter(drilldownVariable);
  // A time series set beats an object set beats a dataset. One order, stated
  // once, rather than three sources that can all be half-configured and a
  // reader left to guess which won.
  const seriesRef = useCanvasVariable(seriesVariable) as {
    object_type_id: string; instance_id: string;
    property: string; interval: string; aggregate: string;
  } | null;
  const usingSeries = !!seriesVariable;
  const usingSet = !usingSeries && !!objectSetVariable;

  // Drill-down needs a set to narrow and a property to narrow it on, so it is
  // offered only where both exist. A dataset-backed chart has no set: there is
  // nothing for a clause to mean, and inventing a second mechanism for it
  // would be two answers to one question.
  const canDrill = usingSet && !!drilldownVariable && !!dimension;
  // What is currently drilled into, read back out of the variable the chart
  // writes rather than held here as a second copy - so the chart reflects the
  // document's state, including a clause something else set.
  const drilledLabel = (() => {
    for (const clause of Array.isArray(drilled) ? drilled : []) {
      const c = clause as { property?: string; op?: string; value?: unknown };
      if (c.property === dimension && c.op === "eq") return String(c.value);
    }
    return null;
  })();

  const sql = chartQuery({
    kind, dimension, measure, aggregate,
    filterColumn, filterOperator, filterValue,
  });

  const datasetResult = useQuery({
    queryKey: ["canvas-chart", datasetId, sql],
    queryFn: () => dsApi.query(workspaceId, projectId, datasetId!, sql!),
    enabled: !usingSet && !usingSeries && !!datasetId && sql !== null,
  });
  const setResult = useQuery({
    queryKey: [
      "canvas-chart-set", objectSetVariable,
      JSON.stringify(setDefinition ?? null), dimension,
    ],
    queryFn: () => objApi.groupObjectSet(workspaceId, setDefinition, dimension!),
    enabled: usingSet && !!setDefinition && !!dimension,
  });

  // The variable resolves to a *question* (decision 0009: points stay in the
  // dataset they arrived in), so the widget asks it - nothing was copied into
  // the document to make this chart possible.
  const seriesResult = useQuery({
    queryKey: ["canvas-chart-series", JSON.stringify(seriesRef ?? null)],
    queryFn: () =>
      objApi.seriesPoints(
        workspaceId, seriesRef!.object_type_id, seriesRef!.instance_id,
        seriesRef!.property,
        { interval: seriesRef!.interval, aggregate: seriesRef!.aggregate },
      ),
    enabled: usingSeries && !!seriesRef,
  });

  // A reading with no value is a *gap*, and `Number(null)` is 0 - a finite
  // number that plots as a real measurement of zero (the bug §149 caught in
  // `plot`). Dropped rather than zeroed, and the count is said below.
  const readings = (seriesResult.data?.points ?? []).filter(
    (p) => p.value !== null && p.value !== "" && Number.isFinite(Number(p.value)),
  );

  const result = usingSeries ? seriesResult : usingSet ? setResult : datasetResult;
  const points = usingSeries
    ? seriesResult.data
      ? readings.map((p) => ({
          label: seriesPointLabel(p.at, seriesRef!.interval),
          value: Number(p.value),
        }))
      : null
    : usingSet
    ? (setResult.data?.groups ?? []).map((g) => ({ label: g.value, value: g.count }))
    : datasetResult.data
      ? toPoints(datasetResult.data.rows)
      : null;

  const needs = usingSeries
    ? (!seriesRef ? "nothing picked yet" : null)
    : usingSet
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
      {!needs && (result.isPending || ((usingSet || usingSeries) && variablesPending)) && (
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
      {usingSeries && seriesResult.data && points?.length === 0 && (
        // Declared, mapped, and empty. Saying so beats an axis with nothing on
        // it, which reads as a chart that failed to draw.
        <p className="canvas-widget-empty">No readings for this object yet.</p>
      )}
      {/* Only the series path swaps an empty chart for a sentence; the other
          two are left exactly as they were. */}
      {points && !(usingSeries && points.length === 0) && (
        <Chart
          /* p.281: "If the data input is a time series set, only the Line
             Chart option is supported." */
          kind={usingSeries ? "line" : kind}
          points={points}
          drill={
            canDrill
              ? {
                  selected: drilledLabel,
                  // Clicking what is already drilled into clears it. Without
                  // that there is no way back out from inside the chart, and
                  // a filter you cannot remove is a filter you have to
                  // remember you applied.
                  onSelect: (label) =>
                    setParameter(
                      drilldownVariable!,
                      label === drilledLabel
                        ? []
                        : [{ property: dimension, op: "eq", value: label }],
                    ),
                }
              : undefined
          }
        />
      )}
      {canDrill && drilledLabel !== null && (
        <p className="canvas-widget-empty">
          Drilled into {dimension} = {drilledLabel}.{" "}
          <button
            type="button"
            className="btn quiet"
            style={{ padding: "1px 7px", fontSize: 12 }}
            onClick={() => setParameter(drilldownVariable!, [])}
          >
            Clear
          </button>
        </p>
      )}
      {usingSeries && seriesResult.data && points && points.length > 0 && (
        <p className="canvas-widget-empty" data-testid="chart-series-caption">
          {seriesRef!.property}, {seriesRef!.interval === "none"
            ? "every reading"
            : `by ${seriesRef!.interval} (${seriesRef!.aggregate})`}
          , in UTC. {points.length} point{points.length === 1 ? "" : "s"}
          {/* Said, not hidden - the same rule as the truncation notice below.
              A gap dropped in silence is a chart that looks complete. */}
          {seriesResult.data.points.length > points.length &&
            `, ${seriesResult.data.points.length - points.length} with no reading skipped`}
          {seriesResult.data.truncated && `, cut short at the point cap`}.
        </p>
      )}
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
    filterColumn, filterParameter, filterOperator, objectSetVariable, seriesVariable,
    drilldownVariable,
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
    seriesVariable: node.data.props.seriesVariable,
    drilldownVariable: node.data.props.drilldownVariable,
  }));
  const list = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => dsApi.list(workspaceId, projectId),
  });
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const seriesVariables = Object.values(declared).filter(
    (v) => v.kind === "time_series_set",
  );
  // Where a drill-down writes its clause: an `array` variable, the same kind
  // the Filter List writes its clauses into, so one `narrow_set` derivation
  // reads either - or both, if a chart and a filter list narrow the same set.
  // Derived ones are absent because they are computed from their inputs and a
  // write to one has no meaning.
  const clauseVariables = Object.values(declared).filter(
    (v) => v.kind === "array" && !v.derivation,
  );
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

  // **p.280's three "Data input" options are one choice, not three inputs.**
  // §179's alternative was built for the Object table's two; this is the same
  // rule with a third arm, and it has to be - requiring all three would wait
  // for two sources nobody is meant to supply, and requiring none would offer
  // a category picker with nothing behind it.
  //
  // The title used to be the first control in this panel. It describes a chart
  // that cannot be drawn until something says what to plot, which is §179's
  // Metric card exactly.
  return (
    <WidgetSetup
      bindings={{ seriesVariable, objectSetVariable, datasetId }}
      requires={[["seriesVariable", "objectSetVariable", "datasetId"]]}
      labels={{
        seriesVariable: "a time series set",
        objectSetVariable: "an object set",
        datasetId: "a dataset",
      }}
      inputs={<>
      {/* p.280's three "Data input" options, offered in the order they take
          precedence, each disabling what it replaces - rather than letting
          several be configured and leaving whoever reads the app to guess
          which won. */}
      <label className="field">
        <span className="field-label">Time series set variable</span>
        <select
          value={seriesVariable || ""}
          onChange={(e) =>
            setProp((p: Record<string, unknown>) => {
              p.seriesVariable = e.target.value || null;
            })
          }
        >
          <option value="">Not bound — plot a set or a dataset</option>
          {seriesVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {seriesVariables.length === 0
            ? "No time series set variables yet — add one in the Variables tab"
            : /* p.281, and it is not a limitation worth hiding: a bar per
                 reading is a comb, and a pie of readings answers nothing. */
              "Drawn as a line; the bucket and summariser are on the variable"}
        </span>
      </label>
      <label className="field">
        <span className="field-label">Object set variable</span>
        <select
          value={objectSetVariable || ""}
          disabled={!!seriesVariable}
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
      </>}
      configuration={<>
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
        <span className="field-label">Title</span>
        <input
          type="text"
          value={title || ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      {/* **`columns`, not `dataset`.** These three pickers are populated from
          whichever source is bound - the set's properties or the dataset's
          columns, computed above as exactly that. Guarding them on `dataset`
          asked about one of the two ways their options arrive, so a chart
          plotting an object set had a Category, an "Of column" and a Filter
          column that were disabled with their options already loaded. Ask
          about the options, not about one of the sources they can come from. */}
      <label className="field">
        <span className="field-label">{scatter ? "X column" : "Category"}</span>
        <select
          value={dimension || ""}
          disabled={!columns.length}
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
            disabled={!columns.length}
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
          disabled={!columns.length}
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
      </>}
      /* p.65's "the data that is then produced and output by the widget", and
         only where there is a set to narrow: a dataset-backed or series-backed
         chart has no set, so a clause would have nothing to mean - and the
         section is omitted rather than shown empty. */
      outputs={objectSetVariable ? (
        <label className="field">
          <span className="field-label">Drill-down writes to</span>
          <select
            value={drilldownVariable || ""}
            onChange={(e) =>
              setProp((p: { drilldownVariable: string | null }) =>
                (p.drilldownVariable = e.target.value || null))
            }
          >
            <option value="">Not bound — the chart is a picture</option>
            {clauseVariables.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
          <span className="field-hint">
            {clauseVariables.length === 0
              ? "Declare an array variable, and derive a narrowed set from it"
              : "Clicking a bar or slice narrows the set to that category"}
          </span>
        </label>
      ) : undefined}
    />
  );
}

CanvasChart.craft = {
  displayName: "Chart",
  props: {
    datasetId: null, kind: "bar", dimension: null, measure: null,
    aggregate: "count", title: "", filterColumn: null,
    filterParameter: null, filterOperator: "equals",
    objectSetVariable: null, seriesVariable: null, drilldownVariable: null,
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
  // the chosen object changes - picking a different row and finding the last
  // one's values still typed in would be an edit about to go to the wrong
  // object.
  //
  // **Both ways of choosing, not only the bound one.** This used to seed only
  // when a `subjectVariable` was set, so the dropdown form started blank - and
  // once parameters arrived that stopped being cosmetic: a hidden parameter is
  // seeded rather than typed (p.25), so in the dropdown form it was never sent
  // at all and its rule quietly wrote nothing.
  const chosen = subjectVariable
    ? subject
    : instancesQ.data?.items.find((i) => i.id === picked);
  const chosenKey = String(chosen?.id ?? "");
  const [seeded, setSeeded] = useState<string | null>(null);
  if (chosenKey !== seeded) {
    setSeeded(chosenKey);
    setValues(seedActionForm(actionType?.parameters ?? [], chosen?.properties ?? {}));
  }

  const execute = useMutation({
    mutationFn: () => actionApi.execute(workspaceId, projectId, actionType!.id, instanceId, values),
    onSuccess: async (result) => {
      if (!result.ok) return;
      // Everything reading this object type reads a *set*, and the set is now
      // one write out of date. By prefix rather than by a list of four names:
      // the list had already missed the object table, so submitting this form
      // left it showing the value the submit had replaced.
      await invalidateCanvasReads(queryClient);
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
  // p.25: hidden parameters are supplied by the caller and never drawn. The
  // form still sends them - `values` carries every parameter it seeded.
  const visible = (actionType?.parameters ?? []).filter((p) => !p.hidden);
  const missingRequired = visible.filter(
    (p) => p.required && !String(values[p.api_name] ?? "").trim(),
  );

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
          {visible.map((parameter) => (
            <label className="field" key={parameter.api_name} data-parameter={parameter.api_name}>
              <span className="field-label">
                {parameter.display_name || parameter.api_name}
                {parameter.required && <span aria-hidden> *</span>}
              </span>
              <input
                type={inputTypeFor(parameter.data_type)}
                value={values[parameter.api_name] ?? ""}
                required={parameter.required}
                aria-required={parameter.required}
                onChange={(e) => setValues({ ...values, [parameter.api_name]: e.target.value })}
                disabled={!live}
              />
            </label>
          ))}
          <button
            type="submit"
            className="btn"
            disabled={!live || !instanceId || execute.isPending || missingRequired.length > 0}
          >
            {execute.isPending ? "Submitting…" : "Submit"}
          </button>
          {missingRequired.length > 0 && live && (
            <p className="canvas-widget-empty" data-testid="action-form-missing">
              {missingRequired.map((p) => p.display_name || p.api_name).join(", ")} is required.
            </p>
          )}
          {!live && <p className="canvas-widget-empty">Submitting is disabled while editing - use Preview to try it.</p>}
          {execute.isSuccess && execute.data.ok && <p className="login-note">Saved.</p>}
          {execute.isSuccess && !execute.data.ok && <div className="form-error">{execute.data.error}</div>}
          {/* **A refused submission, in the criterion's own words** (p.56).
              The server sends back the failure message the builder wrote, and
              this draws it unchanged. The form deliberately does *not*
              evaluate criteria itself to grey the button out in advance: that
              would be a second implementation of a rule that governs writes,
              in another language, free to disagree with the first - and this
              repo has already paid for mirrored logic more than once. */}
          {execute.isError && (
            <div className="form-error" data-testid="action-form-refused">
              {(execute.error as Error).message}
            </div>
          )}
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
  // The action type is the input: until one is chosen there is no form, so
  // "which variable does it edit" is a question about nothing. Note the *lack*
  // of a `subjectVariable` requirement - leaving it unset is a real answer
  // ("whatever the viewer picks"), not an unfinished one, so it belongs under
  // configuration rather than beside the action.
  return (
    <WidgetSetup
      bindings={{ actionTypeId }}
      requires={["actionTypeId"]}
      labels={{ actionTypeId: "an action" }}
      inputs={<>
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
      </>}
      configuration={<>
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
      </>}
    />
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

  // **The set moved above the label**, which is the point of p.65's order
  // rather than a tidy-up: the label describes a number this widget cannot
  // produce until something has said which set to count, so asking for it
  // first asks somebody to name a thing they have not chosen yet.
  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
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
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          value={label ?? ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
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
      </>}
    />
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
 * screen instead of overflowing.
 *
 * **Drag-to-resize is an affordance over those same numbers** (roadmap 1.4,
 * the last item on it). The handle writes `weights` - the prop the Settings
 * field edits - so there is one description of the layout and dragging is a
 * way of typing it. A resize that stored pixels beside the proportions would
 * be a second answer to "how wide is this", and the two would disagree the
 * first time a window changed size.
 *
 * **Only in the builder.** A viewer dragging a divider is editing the saved
 * document, and decision 0002 rules that out for the same reason a viewer's
 * filters are not saved: a module is a definition, not a session. So the
 * handles are edit-mode only, and what a viewer sees is what the author laid
 * out.
 *
 * **Below a threshold, columns stack.** A three-column section on a phone is
 * three unreadable columns; the roadmap asks for responsive rules per section
 * type, and for a column section the rule is "stop being columns".
 */
const SECTION_LABELS: Record<string, string> = {
  columns: "Columns",
  rows: "Rows",
  tabs: "Tabs",
  flow: "Flow",
  toolbar: "Toolbar",
};

export function CanvasSection({
  direction = "columns",
  weights = "",
  gap = 12,
  minHeight = 0,
  visibleWhen = null,
  scroll = false,
  background = null,
  padding = null,
  customPadding = null,
  border = null,
  collapsible = false,
  collapsedByDefault = false,
  collapsedWhen = null,
  title = "",
  tabs = "",
  tabVariable = null,
  children,
}: {
  /** p.55: "Collapsible sections, with Expand / Collapse / Toggle events".
   * A collapsible section draws a header with its own control; p.82's three
   * events act on it from anywhere in the module. */
  collapsible?: boolean;
  collapsedByDefault?: boolean;
  /** p.82's "Boolean variable backing the collapse state" - and the variable
   * those three events pointedly do **not** write. */
  collapsedWhen?: string | null;
  /** Shown in the collapsible header. A section that collapses to a bare
   * chevron is a section nobody can identify once it is shut. */
  title?: string;
  /** p.57-62's style block. A section gets all three - p.58 offers
   * backgrounds on sections, p.60 borders, p.62 padding - which is the only
   * one of the three levels that does. */
  background?: string | null;
  padding?: PaddingName | null;
  customPadding?: readonly [number, number] | null;
  border?: BorderName | null;
  /** Foundry's section layouts (p.54).
   *
   * - **Tabs** — "adds tabs to the top of a section and allows module builders
   *   to configure different configurations of widgets within each tab". One
   *   child per tab; a tab holding several widgets is a child that is itself a
   *   section, which is p.54's own "a layout, which itself may contain one or
   *   more sections". **This used to be the Tabs *widget*, which switches
   *   pages** - a substitution this file's own comment called "the same idea
   *   one level up". It is not: a module has one set of pages, so two
   *   independent tab groups side by side could not be expressed, and p.84's
   *   Variable-Based Tab Selection had nothing to attach to.
   *
   * - **Flow** — "turns the current section in a vertically scrolling container
   *   to allow module building to configure widgets that stretch beyond the
   *   displayed interface of a module". So: rows, content-height children, and
   *   it scrolls. Distinct from Rows-with-scrolling because a Flow child keeps
   *   its natural height rather than sharing the section's out by weight.
   * - **Toolbar** — "configures sections to function as a horizontal toolbar
   *   optimized for smaller widgets like Button Groups or Metric Cards". So:
   *   columns, but children take the width they need instead of an equal share,
   *   which is what stops three buttons spreading across a whole page. */
  direction?: "columns" | "rows" | "tabs" | "flow" | "toolbar";
  /** Tabs only: comma-separated tab names, one per child, in the same idiom as
   * `weights`. Blank or short entries become "Tab 3". */
  tabs?: string;
  /** Tabs only: p.84's Variable-Based Tab Selection - the string variable
   * holding the selected tab's name. **Unlike `collapsedWhen` one field up,
   * this one *is* written** when the tab changes, which is p.84's own stated
   * difference from the page and section events. */
  tabVariable?: string | null;
  /** Rows only: p.54's "Enable scrolling" option. */
  scroll?: boolean;
  /** How tall a **row** section is, in pixels. Blank means "as tall as its
   *  contents", which is the sensible default and the reason proportions on a
   *  row section did nothing until this existed: `flex-grow` shares out *free*
   *  space, and a column of content-height children has none, so `weights` of
   *  "3,1" laid out exactly like "1,1". The Settings panel said otherwise and
   *  the widget's own docstring claimed it worked.
   *
   *  Found by the drag-to-resize test, which is the first thing that ever
   *  asked a row section to change shape. Columns were never affected: a row
   *  of children in a full-width container has free space by construction. */
  minHeight?: number;
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
    id: nodeId,
    connectors: { connect, drag },
    actions: { setProp },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { hidden, marker } = useVisibility(visibleWhen);
  // p.82's collapse state. Read even when this section is not collapsible, so
  // the hook order does not depend on a prop somebody can toggle.
  const { collapsed: overrides, setCollapsed } = useCanvasPage();
  const backing = useCanvasVariable(collapsedWhen);
  const shut = collapsible
    && collapseState(
      overrides[nodeId],
      collapsedWhen ? backing : undefined,
      collapsedByDefault,
    );
  // Only Columns and Rows divide their space between children, so only they
  // have proportions to configure or handles to drag. Tabs, Flow and Toolbar
  // are about *not* doing that.
  const shares = direction === "columns" || direction === "rows";
  const parts = childList(children);

  // p.54's Tabs layout and p.84's variable. Computed unconditionally, for the
  // reason the collapse block above gives: a hook whose presence depends on a
  // prop somebody can toggle is a hook-order bug waiting for the first author
  // who changes the layout dropdown.
  const { tabs: tabOverrides, setTab } = useCanvasPage();
  const { set: setVariable } = useCanvasParameters();
  const tabbed = direction === "tabs";
  const labels = tabbed ? tabLabels(tabs, parts.length) : [];
  const tabBacking = useCanvasVariable(tabVariable);
  const showing = activeTab(
    tabOverrides[nodeId],
    tabVariable ? tabBacking : undefined,
    labels,
  );
  const chooseTab = (name: string) => {
    setTab(nodeId, { name, against: asTabName(tabBacking, labels) });
    // **p.84's whole difference from p.81 and p.82, in one line.** "Events
    // that change the selected tab will also update the value of the string
    // variable configured for Variable-Based Tab Selection." The override
    // above is still needed - the write takes a debounce and a round trip to
    // come back, and the tab has to move now - but it retires when the
    // variable returns agreeing with it.
    if (tabVariable) setVariable(tabVariable, name);
  };
  const parsed = parseWeights(weights, parts.length);

  const partsRef = React.useRef<HTMLDivElement>(null);
  // What the section looks like *during* a drag. Deliberately transient: the
  // prop is written once, on release, so a drag is one undo step rather than
  // one per pixel — and there is no second copy of the layout at rest.
  const [dragging, setDragging] = React.useState<number[] | null>(null);
  const effective = dragging ?? parsed;

  const commit = (next: number[]) => {
    setProp((p: { weights: string }) => (p.weights = formatWeights(next)));
  };
  const resized = (index: number, share: number) => resizeWeights(effective, index, share);

  const onHandleDown = (index: number) => (event: React.PointerEvent<HTMLDivElement>) => {
    const container = partsRef.current;
    if (!container) return;
    const kids = Array.from(
      container.querySelectorAll<HTMLElement>(":scope > .canvas-section-part"),
    );
    const first = kids[index];
    const second = kids[index + 1];
    if (!first || !second) return;
    const horizontal = direction === "columns";
    const origin = horizontal ? first.getBoundingClientRect().left
                              : first.getBoundingClientRect().top;
    const span = horizontal
      ? first.offsetWidth + second.offsetWidth
      : first.offsetHeight + second.offsetHeight;
    if (span <= 0) return;

    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const move = (moveEvent: PointerEvent) => {
      const position = horizontal ? moveEvent.clientX : moveEvent.clientY;
      setDragging(resized(index, (position - origin) / span));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      // Read the final layout from state rather than from the last event: a
      // release with no move in between must not write a value nothing
      // computed.
      setDragging((current) => {
        if (current) commit(current);
        return null;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  /** Arrow keys move a boundary by a step. A splitter that only responds to a
   *  drag is one a keyboard user cannot operate at all, and the layout is the
   *  part of the builder least recoverable by other means. */
  const onHandleKey = (index: number) => (event: React.KeyboardEvent) => {
    const back = direction === "columns" ? "ArrowLeft" : "ArrowUp";
    const forward = direction === "columns" ? "ArrowRight" : "ArrowDown";
    if (event.key !== back && event.key !== forward) return;
    event.preventDefault();
    const pair = (effective[index] ?? 1) + (effective[index + 1] ?? 1);
    const current = (effective[index] ?? 1) / pair;
    commit(resized(index, current + (event.key === forward ? 0.05 : -0.05)));
  };

  if (hidden) return null;
  return (
    <div
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-section canvas-section--${direction}`}
      // p.59-60: "widgets within that section automatically switch between
      // light and dark mode based on the brightness of the background".
      data-scheme={schemeFor({ background })}
      style={styleFor({ background, padding, customPadding, border })}
    >
      {marker && <p className="canvas-hidden-marker">{marker}</p>}
      {collapsible && (
        <button
          type="button"
          className="canvas-section-toggle"
          data-testid={`section-toggle-${nodeId}`}
          aria-expanded={!shut}
          onClick={() =>
            setCollapsed(nodeId, {
              collapsed: !shut,
              // The same bookkeeping p.82's events do: remember what the
              // backing variable said, so a later change to it takes over
              // again rather than being outvoted forever by one click.
              against: collapsedWhen ? asCollapsed(backing) : null,
            })
          }
        >
          <span aria-hidden="true">{shut ? "▸" : "▾"}</span> {title || "Section"}
        </button>
      )}
      {tabbed && labels.length > 0 && (
        // `tablist`/`tab`/`tabpanel` rather than a row of buttons: the roles
        // are what make arrow keys, "tab 2 of 3" and the panel association
        // work for anything that is not a mouse, and a tab bar is exactly the
        // widget those roles were written for.
        <div className="canvas-tabstrip" role="tablist" aria-label={title || "Tabs"}>
          {labels.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              id={`${nodeId}-tab-${name}`}
              aria-selected={name === showing}
              aria-controls={`${nodeId}-panel-${name}`}
              // Only the selected tab is in the tab order; the rest are
              // reached with the arrow keys, which is the tablist convention
              // and stops a five-tab section costing five presses to pass.
              tabIndex={name === showing ? 0 : -1}
              className={`canvas-tabstrip-tab${name === showing ? " on" : ""}`}
              onClick={() => chooseTab(name)}
              onKeyDown={(event) => {
                const step = event.key === "ArrowRight" ? 1
                  : event.key === "ArrowLeft" ? -1 : 0;
                if (!step) return;
                event.preventDefault();
                // `showing` is one of `labels` whenever there is a tab at all,
                // and this handler only exists on a rendered tab - but the
                // index arithmetic is written so that neither fact has to be
                // true for it to be safe.
                const at = showing ? labels.indexOf(showing) : 0;
                const next = labels[(at + step + labels.length) % labels.length];
                if (next) chooseTab(next);
              }}
            >
              {name}
            </button>
          ))}
        </div>
      )}
      {/* A section fills itself with its children, so in the builder there is
          otherwise nowhere to click that is the section rather than a widget
          inside it - and its settings (proportions, direction, gap) would be
          unreachable. The label is that click target, and says what the
          section is doing, the way a page's label does. */}
      {mode === "edit" && (
        <p className="canvas-section-label">
          {SECTION_LABELS[direction] ?? "Section"}
          {shares && parts.length > 1 ? ` · ${parsed.map(roundWeight).join(":")}` : ""}
        </p>
      )}
      <div
        className="canvas-section-parts"
        // `hidden` rather than not rendering: a collapsed section keeps its
        // children mounted, so a table inside one does not refetch every time
        // somebody opens it - and a widget that was mid-edit is still there.
        hidden={shut}
        style={{
          gap,
          ...(direction === "rows" && minHeight > 0 ? { minHeight } : {}),
          ...(direction === "rows" && scroll ? { overflowY: "auto" } : {}),
          ...(direction === "flow" && minHeight > 0 ? { maxHeight: minHeight } : {}),
        }}
        ref={partsRef}
      >
        {parts.map((child, index) => (
          <React.Fragment key={index}>
            <div
              className="canvas-section-part"
              {...(tabbed
                ? {
                  role: "tabpanel",
                  id: `${nodeId}-panel-${labels[index]}`,
                  "aria-labelledby": `${nodeId}-tab-${labels[index]}`,
                  // **In the builder every tab is on screen**, stacked, for
                  // `CanvasPage`'s reason one level up: hiding all but one
                  // would make the other tabs uneditable without a tab
                  // switcher in the chrome, and would hide from the author
                  // that they exist. In the running app exactly one shows.
                  //
                  // `hidden` rather than unmounted, like a collapsed section:
                  // a table in a tab nobody is looking at should not refetch
                  // every time somebody comes back to it.
                  hidden: mode === "run" && labels[index] !== showing,
                }
                : {})}
              // `flex-grow` rather than a width: the children then share
              // whatever is left after gaps, so the arithmetic does not have to
              // know how many gaps there are.
              style={
                shares
                  ? { flexGrow: effective[index] ?? 1, flexBasis: 0, minWidth: 0 }
                  // Flow and Toolbar children keep their natural size: a
                  // toolbar whose three buttons each took a third of the page
                  // is not a toolbar, and a flow whose children were squeezed
                  // to fit would defeat the scrolling it exists for.
                  : { flexGrow: 0, flexShrink: 0, minWidth: 0 }
              }
            >
              {child}
            </div>
            {/* A handle sits *between* parts, so there is one fewer than there
                are children — and none at all in a viewer, where the layout is
                the author's rather than the reader's. */}
            {mode === "edit"
              && index < parts.length - 1
              && shares && (direction === "columns" || minHeight > 0) && (
              <div
                role="separator"
                tabIndex={0}
                aria-orientation={direction === "columns" ? "vertical" : "horizontal"}
                aria-label={`Resize ${direction === "columns" ? "columns" : "rows"} ${
                  index + 1} and ${index + 2}`}
                aria-valuenow={Math.round(
                  ((effective[index] ?? 1)
                    / ((effective[index] ?? 1) + (effective[index + 1] ?? 1))) * 100,
                )}
                aria-valuemin={Math.round(MIN_SHARE * 100)}
                aria-valuemax={Math.round((1 - MIN_SHARE) * 100)}
                className={`canvas-section-handle canvas-section-handle--${direction}`}
                onPointerDown={onHandleDown(index)}
                onKeyDown={onHandleKey(index)}
              />
            )}
          </React.Fragment>
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
    scroll,
    weights,
    gap,
    minHeight,
    visibleWhen,
    collapsible,
    collapsedByDefault,
    collapsedWhen,
    title,
    tabs,
    tabVariable,
    actions: { setProp },
  } = useNode((node) => ({
    direction: node.data.props.direction,
    scroll: node.data.props.scroll,
    weights: node.data.props.weights,
    gap: node.data.props.gap,
    minHeight: node.data.props.minHeight,
    visibleWhen: node.data.props.visibleWhen,
    collapsible: node.data.props.collapsible,
    collapsedByDefault: node.data.props.collapsedByDefault,
    collapsedWhen: node.data.props.collapsedWhen,
    title: node.data.props.title,
    tabs: node.data.props.tabs,
    tabVariable: node.data.props.tabVariable,
  }));
  const { declared } = useCanvasVariables();
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
          <option value="tabs">Tabs</option>
          <option value="flow">Flow</option>
          <option value="toolbar">Toolbar</option>
        </select>
        <span className="field-hint">
          {direction === "flow"
            ? "A vertically scrolling container for content taller than the screen"
            : direction === "toolbar"
              ? "A horizontal strip; its widgets keep their own width"
              : direction === "tabs"
                ? "One tab per widget in it; put a section in a tab to hold several"
                : "Its widgets share the space by the proportions below"}
        </span>
      </label>
      {direction === "tabs" && (
        <>
          <label className="field">
            <span className="field-label">Tab names</span>
            <input
              value={tabs ?? ""}
              placeholder="Tab 1, Tab 2"
              data-testid="section-tabs"
              onChange={(e) => setProp((p: { tabs: string }) => (p.tabs = e.target.value))}
            />
            <span className="field-hint">
              One name per widget, comma separated. A name is how an event and
              a variable address a tab, so duplicates get a number.
            </span>
          </label>
          <label className="field">
            <span className="field-label">Tab from a variable</span>
            <select
              value={tabVariable ?? ""}
              data-testid="section-tab-variable"
              onChange={(e) =>
                setProp((p: { tabVariable: string | null }) => {
                  p.tabVariable = e.target.value || null;
                })
              }
            >
              <option value="">Tabs are chosen by clicking only</option>
              {Object.values(declared)
                .filter((v) => v.kind === "string")
                .map((v) => (
                  <option key={v.id} value={v.id}>{v.label}</option>
                ))}
            </select>
            {/* p.84's difference from p.81 and p.82, said here because an
                author who has met the other two will expect this one to
                behave the same way and it does not. */}
            <span className="field-hint">
              Holds the selected tab&apos;s name. Unlike a page or a section,
              changing the tab <strong>does</strong> write this variable back.
            </span>
          </label>
        </>
      )}
      {(direction ?? "columns") !== "flow" && direction !== "toolbar" && (
      <label className="field">
        <span className="field-label">Proportions</span>
        <input
          value={weights ?? ""}
          placeholder="equal"
          onChange={(e) => setProp((p: { weights: string }) => (p.weights = e.target.value))}
        />
        <span className="field-hint">
          {direction === "rows" && !(minHeight > 0)
            ? "Set a height below - a row section with no height has no space to share out"
            : "One number per widget, e.g. 2,1 for two-thirds and a third. Drag the handles between them"}
        </span>
      </label>
      )}
      {direction === "rows" && (
        <label className="vars-toggle field">
          <input
            type="checkbox"
            checked={!!scroll}
            data-testid="section-scroll"
            onChange={(e) => setProp((p: { scroll: boolean }) => (p.scroll = e.target.checked))}
          />
          Enable scrolling
        </label>
      )}
      {(direction === "rows" || direction === "flow") && (
        <label className="field">
          <span className="field-label">Height</span>
          <input
            type="number"
            min={0}
            value={minHeight ?? 0}
            placeholder="as tall as its contents"
            onChange={(e) =>
              setProp((p: { minHeight: number }) => (p.minHeight = Number(e.target.value) || 0))
            }
          />
          {/* Columns need no equivalent: a row of children in a full-width
              container has free space by construction. */}
          <span className="field-hint">
            In pixels. Proportions only apply once there is a height to divide
          </span>
        </label>
      )}
      <label className="field">
        <span className="field-label">Gap</span>
        <input
          type="number"
          value={gap ?? 12}
          onChange={(e) => setProp((p: { gap: number }) => (p.gap = Number(e.target.value)))}
        />
        {/* Not p.62's padding, and kept apart from it: gap is the space
            *between* children, padding is the space around all of them. */}
        <span className="field-hint">Between its widgets, not around them</span>
      </label>
      {/* p.55's collapsible sections. Its own block rather than folded into
          the style fields: collapsing is behaviour, and p.82 gives it three
          events - none of which the style block has. */}
      <label className="vars-toggle field">
        <input
          type="checkbox"
          checked={!!collapsible}
          data-testid="section-collapsible"
          onChange={(e) => setProp((p: { collapsible: boolean }) => (p.collapsible = e.target.checked))}
        />
        Collapsible
      </label>
      {collapsible && (
        <>
          <label className="field">
            <span className="field-label">Header</span>
            <input
              value={title ?? ""}
              placeholder="Section"
              data-testid="section-title"
              onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
            />
            <span className="field-hint">
              A section that collapses to a bare chevron is one nobody can
              identify once it is shut
            </span>
          </label>
          <label className="vars-toggle field">
            <input
              type="checkbox"
              checked={!!collapsedByDefault}
              data-testid="section-collapsed-default"
              onChange={(e) =>
                setProp((p: { collapsedByDefault: boolean }) =>
                  (p.collapsedByDefault = e.target.checked))
              }
            />
            Start collapsed
          </label>
          <label className="field">
            <span className="field-label">Collapsed when</span>
            <select
              value={collapsedWhen ?? ""}
              data-testid="section-collapsed-when"
              onChange={(e) =>
                setProp((p: { collapsedWhen: string | null }) =>
                  (p.collapsedWhen = e.target.value || null))
              }
            >
              <option value="">Not bound — the control above decides</option>
              {Object.values(declared)
                .filter((v) => v.kind === "boolean")
                .map((v) => (
                  <option key={v.id} value={v.id}>{v.label || v.id}</option>
                ))}
            </select>
            {/* p.82, carried across rather than left to be discovered - it is
                the sentence somebody will otherwise meet as a bug. */}
            <span className="field-hint">
              Expand, Collapse and Toggle events do not write this variable.
              Add a Set variable event beside them to keep the two in step.
            </span>
          </label>
        </>
      )}
      <NodeStyleFields padding border />
    </>
  );
}

CanvasSection.craft = {
  displayName: "Section",
  props: {
    direction: "columns", weights: "", gap: 12, minHeight: 0, visibleWhen: null, scroll: false,
    background: null, padding: null, customPadding: null, border: null,
    collapsible: false, collapsedByDefault: false, collapsedWhen: null, title: "",
    tabs: "", tabVariable: null,
  },
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
  orientation = "horizontal",
  height = 0,
  width = 220,
  collapsible = false,
  collapsedByDefault = false,
  children,
}: {
  title?: string;
  sticky?: boolean;
  /** p.47: "horizontal (at the top) or vertical (on the left) of the module". */
  orientation?: "horizontal" | "vertical";
  /** Horizontal only (p.47). 0 means "as tall as its contents". */
  height?: number;
  /** Vertical only (p.48). */
  width?: number;
  /** Vertical only (p.48), with the option to start collapsed. */
  collapsible?: boolean;
  collapsedByDefault?: boolean;
  children?: React.ReactNode;
}) {
  const {
    connectors: { connect, drag },
    childIds,
  } = useNode((node) => ({ childIds: node.data.nodes ?? [] }));
  const { query } = useEditor();
  // `{{v_id}}` like every other text, so a header can name what the viewer is
  // looking at rather than only what the app is called.
  const { resolved } = useCanvasVariables();
  const vertical = orientation === "vertical";
  const [collapsed, setCollapsed] = useState(collapsible && collapsedByDefault);
  // Collapsing is a vertical-header affordance (p.48); a horizontal header that
  // had been collapsed and then switched would otherwise stay hidden with no
  // control left to undo it.
  const isCollapsed = vertical && collapsible && collapsed;

  // **p.49, and it is a rule rather than a style**: "When enabling collapsed
  // headers, the Button Group and Tabs widgets will also have collapsed states
  // that will only show the icons; the text will be dropped in this state. All
  // other widgets will be hidden when a module header is collapsed."
  //
  // Which means the header has to know what *kind* each child is, and a React
  // element cannot be asked - Craft wraps it. The node ids are in the same
  // order as the rendered children, so the two zip together.
  const parts = childList(children);
  const names = childIds.map((cid: string) => {
    try {
      return String(query.node(cid).get().data.name ?? "");
    } catch {
      return "";
    }
  });
  const visible = isCollapsed
    ? parts.filter((_, i) => COLLAPSED_WIDGETS.includes(names[i] ?? ""))
    : parts;

  return (
    <CanvasHeaderCollapsedContext.Provider value={isCollapsed}>
      <header
        ref={(ref) => connectDragDrop(ref, connect, drag)}
        className={[
          "canvas-header",
          `canvas-header--${orientation}`,
          sticky ? "canvas-header--sticky" : "",
          isCollapsed ? "canvas-header--collapsed" : "",
        ].filter(Boolean).join(" ")}
        data-collapsed={isCollapsed ? "true" : "false"}
        style={
          vertical
            ? { width: isCollapsed ? 56 : width, flex: `0 0 ${isCollapsed ? 56 : width}px` }
            : height > 0
              ? { minHeight: height }
              : undefined
        }
      >
        {vertical && collapsible && (
          <button
            type="button"
            className="canvas-header-toggle"
            aria-expanded={!isCollapsed}
            aria-label={isCollapsed ? "Expand the header" : "Collapse the header"}
            onClick={() => setCollapsed((was) => !was)}
          >
            {isCollapsed ? "»" : "«"}
          </button>
        )}
        {/* The title goes with the text: p.49 drops labels in the collapsed
            state, and a title is nothing but a label. */}
        {!isCollapsed && title.trim() && (
          <p className="canvas-header-title">{interpolate(title, resolved)}</p>
        )}
        {visible}
      </header>
    </CanvasHeaderCollapsedContext.Provider>
  );
}

/** The only two widgets that survive a collapsed header (p.49). */
const COLLAPSED_WIDGETS = ["CanvasButton", "CanvasTabs"];

/** What to draw where the text used to be.
 *
 * Foundry drops the label and shows the configured icon. With no icon picker,
 * an unset icon falls back to the label's first character rather than to
 * nothing - a collapsed header of blank buttons is worse than an approximate
 * glyph, because there is no way to tell which one is which. */
function glyphFor(icon: string | undefined, label: string | undefined): string {
  const chosen = (icon ?? "").trim();
  if (chosen) return chosen;
  return (label ?? "").trim().charAt(0).toUpperCase() || "•";
}

function HeaderSettings() {
  const {
    title, sticky, orientation, height, width, collapsible, collapsedByDefault,
    actions: { setProp },
  } = useNode((node) => ({
    title: node.data.props.title,
    sticky: node.data.props.sticky,
    orientation: node.data.props.orientation,
    height: node.data.props.height,
    width: node.data.props.width,
    collapsible: node.data.props.collapsible,
    collapsedByDefault: node.data.props.collapsedByDefault,
  }));
  const vertical = orientation === "vertical";
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
        <span className="field-label">Orientation</span>
        <select
          value={orientation ?? "horizontal"}
          data-testid="header-orientation"
          onChange={(e) => setProp((p: { orientation: string }) => (p.orientation = e.target.value))}
        >
          <option value="horizontal">Horizontal — at the top</option>
          <option value="vertical">Vertical — on the left</option>
        </select>
      </label>
      {vertical ? (
        <>
          <label className="field">
            <span className="field-label">Width (px)</span>
            <input
              type="number" min={80}
              value={width ?? 220}
              data-testid="header-width"
              onChange={(e) => setProp((p: { width: number }) => (p.width = Number(e.target.value) || 80))}
            />
          </label>
          <label className="vars-toggle field">
            <input
              type="checkbox"
              checked={!!collapsible}
              data-testid="header-collapsible"
              onChange={(e) => setProp((p: { collapsible: boolean }) => (p.collapsible = e.target.checked))}
            />
            Collapsible
          </label>
          {collapsible && (
            <label className="vars-toggle field">
              <input
                type="checkbox"
                checked={!!collapsedByDefault}
                data-testid="header-collapsed-default"
                onChange={(e) =>
                  setProp((p: { collapsedByDefault: boolean }) => (p.collapsedByDefault = e.target.checked))
                }
              />
              Collapsed by default
            </label>
          )}
          {/* p.49's rule, said where somebody chooses it rather than found by
              wondering where the rest of the header went. */}
          <p className="field-hint">
            Collapsed, only Button and Tabs widgets show — as icons, with their
            labels dropped. Everything else in the header is hidden.
          </p>
        </>
      ) : (
        <label className="field">
          <span className="field-label">Height (px)</span>
          <input
            type="number" min={0}
            value={height ?? 0}
            placeholder="as tall as its contents"
            onChange={(e) => setProp((p: { height: number }) => (p.height = Number(e.target.value) || 0))}
          />
        </label>
      )}
      <label className="vars-toggle field">
        <input
          type="checkbox"
          checked={sticky ?? true}
          onChange={(e) => setProp((p: { sticky: boolean }) => (p.sticky = e.target.checked))}
        />
        Stays put while the page scrolls
      </label>
    </>
  );
}

CanvasHeader.craft = {
  displayName: "Header",
  props: {
    title: "", sticky: true, orientation: "horizontal",
    height: 0, width: 220, collapsible: false, collapsedByDefault: false,
  },
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
  background = null,
  padding = null,
  customPadding = null,
  children,
}: {
  title?: string;
  /** p.57-62's style block, minus the border: p.60 names "sections and
   * widgets" and stops there, and a page is neither. */
  background?: string | null;
  padding?: PaddingName | null;
  customPadding?: readonly [number, number] | null;
  /** The author-set ID this page appears under in the URL, when routing is on
   * (p.197). Read off the layout by `pageIdOf` rather than through props,
   * because the *viewer* needs it for a page it is not rendering; declared
   * here so the settings form and `craft.props` agree it exists. */
  pageId?: string;
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
      data-scheme={schemeFor({ background })}
      style={styleFor({ background, padding, customPadding })}
    >
      {mode === "edit" && (
        <p className="canvas-page-label">
          {title}
          {active ? " · shown first" : ""}
        </p>
      )}
      {children}
      {/* p.52's picker, "at the bottom of the page" and only while editing:
          it is an authoring control, and a reader has no layout to choose. */}
      {mode === "edit" && <LayoutTemplatePicker pageId={nodeId} />}
    </section>
  );
}

function PageSettings() {
  const {
    title,
    icon,
    pageId,
    actions: { setProp },
  } = useNode((node) => ({
    title: node.data.props.title,
    icon: node.data.props.icon,
    pageId: node.data.props.pageId,
  }));
  return (
    <>
      <label className="field">
        <span className="field-label">Page title</span>
        <input
          value={title ?? ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
        <span className="field-hint">Shown on a Tabs widget</span>
      </label>
      <label className="field">
        <span className="field-label">Icon</span>
        <input
          value={icon ?? ""}
          maxLength={2}
          data-testid="page-icon"
          placeholder={(title ?? "P").charAt(0).toUpperCase()}
          onChange={(e) => setProp((p: { icon: string }) => (p.icon = e.target.value))}
        />
        {/* The tab is what carries it, which is why it is configured on the
            page rather than on the Tabs widget: one Tabs widget draws a button
            per page, so an icon on the widget could only be one icon. */}
        <span className="field-hint">
          Shown instead of the title on a Tabs widget in a collapsed header.
        </span>
      </label>
      {/* p.197: "For pages without a defined page ID, no page ID will be
          written to the URL; users will be returned to the module's default
          page on page load." Author-set rather than the node id, which is
          generated and changes when a page is recreated - a link built from
          one would expire for a reason nobody could see. */}
      <label className="field">
        <span className="field-label">Page ID</span>
        <input
          value={pageId ?? ""}
          data-testid="page-id"
          placeholder="none"
          onChange={(e) => setProp((p: { pageId: string }) => (p.pageId = e.target.value))}
        />
        <span className="field-hint">
          Appears in the URL when routing is on. A page with no ID is reached
          by opening the module.
        </span>
      </label>
      {/* No border: p.60 names "sections and widgets" and stops there. */}
      <NodeStyleFields padding />
    </>
  );
}

CanvasPage.craft = {
  displayName: "Page",
  props: {
    title: "Page", icon: "", pageId: "",
    background: null, padding: null, customPadding: null,
  },
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

  // p.49: in a collapsed header a Tabs widget "will only show the icons; the
  // text will be dropped". The icon belongs to the *page*, because that is what
  // each tab stands for.
  const collapsed = useHeaderCollapsed();
  const pages: { id: string; title: string; icon: string }[] = [];
  try {
    for (const id of query.node("ROOT").get().data.nodes ?? []) {
      const node = query.node(id).get();
      if (node?.data?.name === "CanvasPage") {
        pages.push({
          id,
          title: String(node.data.props.title ?? "Page"),
          icon: String(node.data.props.icon ?? ""),
        });
      }
    }
  } catch {
    /* no tree to ask */
  }
  const activeId = current ?? pages[0]?.id ?? null;

  return (
    <nav
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-tabs${collapsed ? " canvas-tabs--collapsed" : ""}`}
      aria-label="Pages"
    >
      {pages.length === 0 && <span className="canvas-widget-empty">Add a page to this app</span>}
      {pages.map((page) => (
        <button
          key={page.id}
          type="button"
          className={`canvas-tab${page.id === activeId ? " on" : ""}`}
          aria-current={page.id === activeId}
          title={collapsed ? page.title : undefined}
          aria-label={collapsed ? page.title : undefined}
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
          {collapsed ? glyphFor(page.icon, page.title) : page.title}
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
  icon = "",
  style = "primary",
  enabledVariable = null,
}: {
  label?: string;
  /** Shown instead of the label in a collapsed header (p.49). One or two
   * characters - an emoji, an initial. **Foundry offers an icon library and we
   * do not**, so this is the divergence: the behaviour (drop the text, show a
   * glyph) is faithful, the picker is not built. */
  icon?: string;
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

  const collapsed = useHeaderCollapsed();
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
        className={`btn${style === "primary" ? "" : ` ${style}`}${collapsed ? " btn-collapsed" : ""}`}
        disabled={disabled}
        // The label becomes the accessible name when the text is dropped, so a
        // collapsed header is still navigable by anything that is not eyes.
        title={collapsed ? interpolate(label ?? "", resolved) : undefined}
        aria-label={collapsed ? interpolate(label ?? "", resolved) : undefined}
        onClick={() => {
          if (mode === "edit") return;
          if (wired.length > 0) runEvents(wired, eventContext);
        }}
      >
        {collapsed ? glyphFor(icon, label) : interpolate(label ?? "", resolved)}
      </button>
      {mode === "edit" && !collapsed && wired.length === 0 && (
        <span className="canvas-widget-empty"> nothing wired to this click yet</span>
      )}
    </span>
  );
}

function ButtonSettings() {
  const {
    label,
    icon,
    style,
    enabledVariable,
    actions: { setProp },
  } = useNode((node) => ({
    label: node.data.props.label,
    icon: node.data.props.icon,
    style: node.data.props.style,
    enabledVariable: node.data.props.enabledVariable,
  }));
  const { declared } = useCanvasVariables();
  // p.65 in full: the tab configures "the input and output variables of a
  // widget … **as well as** any additional configuration and display options".
  // A Button's label, icon and style are display options by that sentence's own
  // words; the variable it reads to decide whether it is pressable is an input.
  // No `requires`, for the Parameter control's reason (§180) - "Always" is a
  // real answer, so a panel that waited for this would never open.
  return (
    <WidgetSetup
      inputs={<>
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
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          value={label ?? ""}
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
        <span className="field-hint">{"{{v_id}}"} shows a variable&apos;s current value</span>
      </label>
      <label className="field">
        <span className="field-label">Icon</span>
        <input
          value={icon ?? ""}
          maxLength={2}
          data-testid="button-icon"
          placeholder={(label ?? "B").charAt(0).toUpperCase()}
          onChange={(e) => setProp((p: { icon: string }) => (p.icon = e.target.value))}
        />
        <span className="field-hint">
          Shown instead of the label in a collapsed header. Blank uses the first letter.
        </span>
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
      </>}
    />
  );
}

CanvasButton.craft = {
  displayName: "Button",
  props: { label: "Button", icon: "", style: "primary", enabledVariable: null },
  related: { settings: ButtonSettings },
};

/** p.68's *Unused widgets* holding node: in the module, on no page.
 *
 * **It renders nothing, in both modes, and that is the whole component.**
 * Parked widgets are listed by the Layout panel, not drawn on the canvas -
 * p.68 puts the area "at the bottom of the Layouts section in the left side
 * panel", and a holding node that drew its children would put every parked
 * widget on the page for every reader.
 *
 * It is a Craft canvas node all the same, because that is what lets it *hold*
 * children through a serialise/deserialise round trip - and being in the node
 * map is what makes `usages()` count a parked widget's variables, which is the
 * reason this design was chosen over a sibling key on the document
 * (`docs/decisions/0010-unused-widgets.md`).
 *
 * The `children` prop is deliberately accepted and deliberately not rendered.
 * Craft passes it; dropping it on the floor is the behaviour.
 */
export function CanvasUnused({ children: _children }: { children?: React.ReactNode }) {
  return null;
}

CanvasUnused.craft = {
  displayName: "Unused widgets",
  props: {},
  isCanvas: true,
};

export const CANVAS_RESOLVER = {
  CanvasHeader,
  CanvasPage,
  CanvasOverlay,
  CanvasUnused,
  CanvasSection,
  CanvasTabs,
  CanvasButton,
  CanvasContainer,
  CanvasText,
  CanvasFilterList,
  CanvasParameterControl,
  CanvasNumericInput,
  CanvasTextInput,
  CanvasStringSelector,
  CanvasDateTimePicker,
  CanvasMarkdown,
  CanvasObjectSetTitle,
  CanvasPropertyList,
  CanvasDatasetTable,
  CanvasObjectTable,
  CanvasObjectCards,
  CanvasSearch,
  CanvasPivotTable,
  CanvasTimeSeries,
  CanvasEmbeddedModule,
  CanvasLoopSection,
  CanvasChart,
  CanvasMap,
  CanvasMetricCard,
  CanvasActionForm,
};

export const PALETTE: { key: keyof typeof CANVAS_RESOLVER; label: string; hint: string }[] = [
  { key: "CanvasHeader", label: "Header", hint: "A toolbar above every page; one per module" },
  { key: "CanvasPage", label: "Page", hint: "A screen of the app; Tabs move between them" },
  { key: "CanvasSection", label: "Section", hint: "Columns, rows, a flow or a toolbar" },
  { key: "CanvasLoopSection", label: "Loop", hint: "One embedded module per object in a set" },
  { key: "CanvasOverlay", label: "Overlay", hint: "A modal or drawer over the page" },
  { key: "CanvasTabs", label: "Tabs", hint: "One button per page" },
  { key: "CanvasButton", label: "Button", hint: "Runs the events wired to its click" },
  { key: "CanvasContainer", label: "Container", hint: "A box to arrange other widgets in" },
  { key: "CanvasText", label: "Text", hint: "A heading or paragraph" },
  { key: "CanvasFilterList", label: "Filter list", hint: "Property filters over an object set, with counts" },
  { key: "CanvasNumericInput", label: "Numeric input", hint: "A number the viewer types, with units and grouping" },
  { key: "CanvasTextInput", label: "Text input", hint: "A line or a paragraph the viewer types" },
  { key: "CanvasStringSelector", label: "String selector", hint: "Pick one or many from a list of strings" },
  { key: "CanvasDateTimePicker", label: "Date and time", hint: "A single date and time, in a chosen timezone" },
  { key: "CanvasMarkdown", label: "Markdown", hint: "Formatted text, typed or read from a string variable" },
  { key: "CanvasObjectSetTitle", label: "Object set title", hint: "One object's title, or an object type and how many there are" },
  { key: "CanvasPropertyList", label: "Property list", hint: "The properties of one object, in a grid" },
  { key: "CanvasDatasetTable", label: "Dataset table", hint: "Preview rows from a dataset" },
  { key: "CanvasObjectTable", label: "Object table", hint: "Live rows from an ontology object type" },
  { key: "CanvasObjectCards", label: "Card list", hint: "The same objects as cards, one heading each" },
  { key: "CanvasSearch", label: "Search", hint: "Narrow an object set by a property prefix" },
  { key: "CanvasPivotTable", label: "Pivot table", hint: "Counts by two properties at once, over an object set" },
  { key: "CanvasTimeSeries", label: "Time series", hint: "When the objects in a set last changed" },
  { key: "CanvasEmbeddedModule", label: "Embedded module", hint: "Another Workshop module, shown inside this one" },
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
