"use client";

/** Each widget's settings panel, out of `widgets.tsx` (§995).
 *
 * Only an author sees a panel, and the panels are close to half of the
 * widget table's code - so a module's readers, in View, in a published
 * module and in a configured object view, loaded every one of them to draw
 * the widgets beside them. Each widget's `related.settings` loads this file
 * the first time the builder shows one (`settingsPanel` in `widgets.tsx`).
 * What each panel edits, and why, is said beside it and beside its widget. */

import { useNode } from "@craftjs/core";
import { useQueries, useQuery } from "@tanstack/react-query";
import React, { Fragment, useMemo, useState } from "react";
import { actions as actionApi, ApiError, canvas as canvasApi, datasets as dsApi, objects as objApi } from "@/lib/api";
import { variablesOf } from "@/lib/workshop-module";
import { TypePicker } from "@/components/type-picker";
import { WidgetSetup } from "./WidgetSetup";
import { StyleFields } from "./StyleFields";
import { refTo } from "./saved-colours";
import { useSavedColours } from "./use-saved-colours";
import { isSelectable } from "@/lib/render-hints";
import { resolveBackground, textColourChoice, type StyleProps } from "./style";
import { formatOf, MAX_ROWS, MIN_ROWS, rowsOf, settingsOf, TEXT_FORMATS } from "./text-input";
import { canCreate, columnsOf, DISPLAYS, displayOf, displaysFor, LAYOUTS, layoutOf as optionLayoutOf, layoutStyle, MAX_COLUMNS, MIN_COLUMNS, modeOf, outputKind, SELECTIONS, selectionOf as pickModeOf, sourceOf } from "./string-selector";
import { COMMON_ZONES, DATE_FORMATS, DEFAULT_DATE_FORMAT, DEFAULT_PRECISION, PRECISIONS, TIME_FORMATS, ZONE_MODES } from "./date-time";
import { DATE_INPUT_MODES } from "./date-input";
import { ALIGNMENTS, alignmentOf, sourceOf as markdownSourceOf } from "./markdown";
import { UNSUPPORTED_HINT, isUnsupported } from "./unsupported-properties";
import { FORM_FACTORS as OBJECT_FORM_FACTORS, PANEL_BEHAVIORS, formFactorOf, panelBehaviorOf } from "@/lib/object-panels";
import { unionParts } from "./union-set";
import { MAX_LAYERS, layerColorOf, layerOpacityOf, layersOf, withLayerSetting, withNewLayer, withoutLayer, type MapLayer } from "./map-layer";
import { EMPTY_MODES, MAX_LINES, emptyModeOf, fillsCellOf, fitColumnsOf, linesOf, narrowHeadersOf, wrapOf } from "./object-table-display";
import { renderWhenEmptyOf, showIconOf, singleOf } from "./object-set-title";
import { LAYOUTS as PROPERTY_LAYOUTS, MAX_COLUMNS as PROPERTY_MAX_COLUMNS, MIN_COLUMNS as PROPERTY_MIN_COLUMNS, columnsOf as propertyColumnsOf, hideNullOf, layoutOf as propertyLayoutOf } from "./property-list";
import { LINK_MODES, MAX_DEFAULT_EXPAND, chosenOf as linkChosenOf, defaultExpandOf, linkKey, modeOf as linkModeOf, type ChosenLink } from "./links-widget";
import { VIEW_MODES, allowToggleOf, emptyMessageOf as objectViewEmptyMessageOf, hideHeaderOf, viewModeOf } from "./object-view-widget";
import { INVALID_STATES, hideHeaderOf as hideActionHeaderOf, invalidStateOf } from "./action-form";
import { AGGREGATIONS as PIE_AGGREGATIONS, LEGEND_POSITIONS, MAX_INNER_RADIUS, aggregationOf as pieAggregationOf, innerRadiusOf, legendPositionOf, needsProperty as pieNeedsProperty, showLegendOf } from "./pie-chart";
import { AGGREGATIONS as METRIC_AGGREGATIONS, aggregationOf as metricAggregationOf, needsProperty as metricNeedsProperty, propertiesFor as metricPropertiesFor, SPARK_POSITIONS, sparkPositionOf as metricSparkPositionOf, METRIC_SIZES, SPARK_RANGES, metricSizeOf, sparkRangeOf as metricSparkRangeOf, sparkRangeProblem as metricSparkRangeProblem, secondaryLabelOf as metricSecondaryLabelOf, DIRECTIONS as METRIC_DIRECTIONS, LAYOUT_STYLES as METRIC_LAYOUT_STYLES, TEMPLATES as METRIC_TEMPLATES, addMetric, directionOf as metricDirectionOf, extraMetricsOf, layoutSettings as metricLayoutSettings, layoutStyleOf as metricLayoutStyleOf, metricLabelOf, moveMetric, sparkAllowedIn, templateOf as metricTemplateOf, type ExtraMetric, BASELINE_KINDS, BASELINE_SUMMARIES, RELATIVE_UNITS, baselineKindOf } from "./metric-card";
import { ValueFormatEditor } from "@/components/value-format-editor";
import { formatsByColumn, formatSummary, numberFormatOf, type NumberFormat } from "./value-formats";
import { METRIC_SUBJECT, rulesByColumn, rulesOf, SERIES_SUBJECT, subjectProperties } from "./conditional-formats";
import { columnsFor } from "./derived-columns";
import { FunctionLayerEditor } from "./function-column-editor";
import { functionLayerOf } from "./function-layers";
import { FunctionPivotSettings } from "./function-pivot-table";
import { unknownColumns } from "./column-visibility";
import { ConditionalFormatEditor } from "@/components/conditional-format-editor";
import type { ConditionalRule, ObjectTypeProperty } from "@/lib/types";
import { DEFAULT_SORT as DROPDOWN_DEFAULT_SORT, SEARCH_MODES, SORTS as DROPDOWN_SORTS, allowNoSelectionOf, searchModeOf } from "./object-dropdown";
import { ORDERABLE_HINT, orderableProperties, requestSort } from "./property-sort";
import { SELECTION_MODES as USER_SELECTION_MODES, isMultiple as userIsMultiple, modeOf as userModeOf } from "./user-select";
import { MODES as PILL_MODES, canRemove, modeOf as pillModeOf } from "./filter-clause";
import { LINK_SCOPES, PROPERTY_SCOPES, linkScopeOf, propertyScopeOf } from "./search-bar";
import { MAX_TERMS as TERMS_MAX, blankTerm, termsOf } from "./prominent-terms";
import type { Property as SortableProperty } from "./property-sort";
import { STEPPER_TYPES, TEMPLATES as STEPPER_TEMPLATES, activeColourOf, completedColourOf, showsStepNumber, stepsOf, templateOf as stepperTemplateOf, typeOf as stepperTypeOf } from "./stepper";
import { COLOUR_MODES as TIMELINE_COLOUR_MODES, ICON_MODES as TIMELINE_ICON_MODES, ORDERS as TIMELINE_ORDERS, ORIENTATIONS as TIMELINE_ORIENTATIONS, PROPERTY_MODES as TIMELINE_PROPERTY_MODES, TITLE_MODES as TIMELINE_TITLE_MODES, colourModeOf as timelineColourModeOf, iconModeOf as timelineIconModeOf, layersOf as timelineLayersOf, orderOf as timelineOrderOf, orientationOf as timelineOrientationOf, propertyModeOf as timelinePropertyModeOf, titleModeOf as timelineTitleModeOf, newLayerId } from "./timeline";
import { SOURCES as MEDIA_SOURCES, sourceOf as mediaSourceOf } from "./media";
import { youtubeEmbedUrl } from "./frame";
import { bindable, savedDefinition } from "./frame-protocol";
import { customColourOf, intentOf } from "./button-look";
import { addItem, buttonTypeOf, duplicateItem, itemsOf, removeItem, renameItem, setItemIcon } from "./button-items";
import { FILTER_COMPONENT_LABELS, componentOf, componentsFor, filtersOf, layoutOf, newFilterId, linkDisplayOf, LINK_DISPLAYS, type FilterSpec } from "./filter-list";
import { IconChoice } from "@/components/icon";
import { interfaceKey } from "@/lib/object-view-tabs";
import { FIXED_SORTS as TABLE_FIXED_SORTS, MAX_SORTS as TABLE_MAX_SORTS, blankEntry as blankTableSort, labelOf as tableSortLabel, sortsOf as tableSortsOf, withDirection as withSortDirection, withFixed as withSortFixed, withProperty as withSortProperty } from "./table-sorts";
import { DEFAULT_BUTTON_TEXT, automaticMapping, editByDefaultOf, editing, eligibleActions, mappingOf, oneClickOf, variableFeedsOf } from "./inline-edit";
import { staticTypeOf } from "./object-export";
import { ANNOTATION_COLOR_MODES, ANNOTATION_FORMATS, addHoverAction, annotationFormatOf, annotationLayersOf, hoverActionsOf, type AnnotationColorMode } from "./markdown-annotations";
import { SELECTION_BEHAVIORS as REFERENCE_SELECTIONS, referenceTypesOf, selectionBehaviorOf as referenceSelectionOf, COLOR_MODES as REFERENCE_COLOR_MODES, type ColorMode as ReferenceColorMode, newReferenceTypeId } from "./markdown-references";
import { COLUMN_BASELINE_KINDS, baselinesByColumn, withColumnBaseline, type ColumnBaseline } from "./series-baselines";
import { transformsByColumn, withColumnTransforms, TIME_UNITS } from "./series-transforms";
import { SeriesTransformsEditor } from "./SeriesTransformsEditor";
import { MAX_ROOTS as MAX_SERIES_ROOTS, PLOT_LABELS as SERIES_PLOT_LABELS, PLOT_TYPES as SERIES_PLOT_TYPES, MAX_EVENT_SETS as MAX_SERIES_EVENT_SETS, EVENT_SET_TYPES as SERIES_EVENT_SET_TYPES, EVENT_SET_TYPE_LABELS as SERIES_EVENT_SET_TYPE_LABELS, MAX_CANVASES as MAX_SERIES_CANVASES, initialEventSetsOf as seriesInitialEventSetsOf, placementOf as seriesPlacementOf, VIEW_RANGES as SERIES_VIEW_RANGES, MAX_DIGITS as MAX_SERIES_DIGITS, TOOLTIP_VALUES as SERIES_TOOLTIP_VALUES, tooltipOptionsOf as seriesTooltipOptionsOf, MAX_ADD_DATA_SETS as MAX_SERIES_ADD_DATA_SETS } from "./series-analysis";
import { moreActionsOf, withAddedAction, withMoreAction, withoutMoreAction } from "./action-menu";
import { useCanvasEnv, useCanvasVariables } from "./context";
import { holdsClauses } from "./pure";
import { type FilterOperator } from "./filter-sql";
import { MAX_SERIES, axisSides, canSegment, seriesName as seriesNameOf, seriesOf, LAYER_KINDS, type LayerKind } from "./chart-series";
import { SEGMENT_LEGEND_POSITIONS, SEGMENT_MODES, segmentLegendPositionOf, segmentModeOf } from "./chart-segments";
import { HEADER_STYLES, headerCount, headerStyleOf } from "./section-header";
import { INNER_SECTION_STYLES, innerStyleOf, ownLook } from "./inner-section-style";
import { MAX_LOGO_HEIGHT, MIN_LOGO_HEIGHT, imageRefOf, logoHeightOf, logoPositionOf, logoPositionsFor, type ImageRef } from "./header-logo";
import { EDIT_ORDERS, editOrderOf } from "./edit-history";
import { itemsOf as freshnessItemsOf, newItemId as newFreshnessItemId, type FreshnessItem } from "./data-freshness";
import { AREA_OPTIONS, CHART_SORTS, NULL_DISPLAYS, SCALE_TYPES, areaOf, axisProblem, chartSortOf, defaultValueTitle, nullDisplayOf, rightAxisTitle, orientationOf, valueAxisOf } from "./chart-display";
import { MAX_GEOMETRIES, geometriesOf, withGeometryEarlier, withGeometrySetting, withNewGeometry, withoutGeometry, type MapGeometry } from "./map-geometry";
import { shapeOutputOf } from "./map-drawn";
import { perimeterModeOf } from "./map-measure";
// Aliased on §211's rule: `areaOf` is also §537's chart area option.
import { DRAW_TOOLS, DRAW_TOOL_LABELS, drawToolsOf, drawnOpacityOf, singleDrawOf, withDrawTool } from "./map-area";
import {
  CARD_FIELD_CAP,
  PropertyOptions,
  useInheritedSectionStyle,
  useSetProperties,
  registerSettingsPanels,
} from "./widgets";


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

/** p.62's "Inner section style" control, on pages and sections, beside the
 * padding p.62 puts it with. */
function InnerSectionStyleField() {
  const {
    innerSectionStyle,
    actions: { setProp },
  } = useNode((node) => ({ innerSectionStyle: node.data.props.innerSectionStyle }));
  return (
    <label className="field">
      <span className="field-label">Inner section style</span>
      <select
        data-testid="inner-section-style"
        value={innerStyleOf(innerSectionStyle) ? innerSectionStyle : ""}
        onChange={(e) =>
          setProp((p: { innerSectionStyle: string | null }) => (
            p.innerSectionStyle = e.target.value || null))}
      >
        <option value="">None</option>
        {Object.entries(INNER_SECTION_STYLES).map(([key, preset]) => (
          <option key={key} value={key}>{preset.label}</option>
        ))}
      </select>
      <span className="field-hint">
        The header format, border and background of the sections directly
        inside, where they have not set their own
      </span>
    </label>
  );
}

/** What a section's settings say when its parent names a preset: which of
 * its own values are hiding it, and a way to let it through. */
function InheritedSectionStyle() {
  const inherited = useInheritedSectionStyle();
  const {
    own,
    actions: { setProp },
  } = useNode((node) => ({
    own: {
      headerStyle: node.data.props.headerStyle,
      border: node.data.props.border,
      background: node.data.props.background,
    },
  }));
  const preset = innerStyleOf(inherited);
  if (!preset) return null;
  const hiding = ownLook(own, inherited);
  const names = { headerStyle: "header format", border: "border", background: "background" };
  const words = hiding.map((key) => names[key]);
  const listed = words.length > 1
    ? `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}` : words[0];
  return (
    <div className="field" data-testid="inherited-section-style">
      <span className="field-hint">
        {`The parent's inner section style is ${preset.label}.`}
        {hiding.length > 0
          ? ` This section's own ${listed} take${hiding.length === 1 ? "s" : ""} its place.`
          : " This section takes all of it."}
      </span>
      {hiding.length > 0 && (
        <button
          type="button"
          className="btn"
          data-testid="use-inner-section-style"
          onClick={() =>
            setProp((p: Record<string, unknown>) => {
              for (const key of hiding) p[key] = null;
            })
          }
        >
          Use {preset.label}
        </button>
      )}
    </div>
  );
}

export function ContainerSettings() {
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

export function TextSettings() {
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

export function FilterListSettings() {
  const {
    objectSetVariable,
    variable,
    properties,
    filters,
    title,
    userEditable,
    layout,
    linkDisplay,
    collapseLinked,
    actions: { setProp },
  } = useNode((node) => ({
    linkDisplay: node.data.props.linkDisplay,
    collapseLinked: node.data.props.collapseLinked,
    objectSetVariable: node.data.props.objectSetVariable,
    variable: node.data.props.variable,
    properties: node.data.props.properties,
    filters: node.data.props.filters,
    title: node.data.props.title,
    userEditable: node.data.props.userEditable,
    layout: node.data.props.layout,
  }));
  const { workspaceId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const sets = Object.values(declared).filter((v) => v.kind === "object_set");
  const arrays = Object.values(declared).filter((v) => holdsClauses(v));
  const bound = objectSetVariable ? resolved[objectSetVariable] : undefined;
  const { typeId, properties: typeProperties, union } = useSetProperties(workspaceId, bound);
  const specs = filtersOf(filters, properties);
  // Written as a list from the first edit on, which is when an older
  // document's `properties` stops being read.
  const writeFilters = (next: FilterSpec[]) =>
    setProp((p: { filters: FilterSpec[] | null }) => (p.filters = next));
  const dataTypeOf = (property: string) =>
    typeProperties.find((p) => p.api_name === property)?.data_type;
  // p.451's "Filter on a link section of the Add filter... dropdown" (§545):
  // each link this set's type is an end of, once per end, as a traversal
  // offers them - a self-link can be followed either way.
  const linkTypes = useQuery({
    queryKey: ["link-types", workspaceId],
    queryFn: () => objApi.listLinkTypes(workspaceId),
  });
  const hops = (linkTypes.data ?? []).flatMap((link) => {
    const out: { key: string; id: string; toType: string; label: string }[] = [];
    if (link.from_object_type_id === typeId) {
      out.push({ key: `${link.id}:to`, id: link.id, toType: link.to_object_type_id,
        label: `${link.to_side_name || link.display_name} → ${link.to_display_name}` });
    }
    if (link.to_object_type_id === typeId) {
      out.push({ key: `${link.id}:from`, id: link.id, toType: link.from_object_type_id,
        label: `${link.from_side_name || link.display_name} → ${link.from_display_name}` });
    }
    return out;
  });
  // The linked types' properties, for a linked filter's property picker.
  const farTypes = [...new Set(specs.map((f) => f.linkTo).filter((t): t is string => !!t))];
  const farResults = useQueries({
    queries: farTypes.map((id) => ({
      queryKey: ["object-type", id],
      queryFn: () => objApi.getType(workspaceId, id),
    })),
  });
  const farProperties = (id: string | undefined) =>
    farResults[farTypes.indexOf(id ?? "")]?.data?.properties ?? [];

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
      <fieldset className="field" data-testid="filter-list-filters">
        <legend className="field-label">Filters</legend>
        {specs.map((spec) => {
          if (spec.link) {
            const props = farProperties(spec.linkTo);
            const farType = (p: string) => props.find((x) => x.api_name === p)?.data_type;
            const allowedHere = componentsFor(farType(spec.property));
            return (
              <div key={spec.id} className="row-actions" style={{ marginBottom: 6 }}>
                <span className="field-hint">
                  {hops.find((h) => h.id === spec.link && h.toType === spec.linkTo)?.label
                    ?? "Link"}
                </span>
                <select
                  aria-label="Linked property"
                  data-testid={`filter-linked-property-${spec.id}`}
                  value={spec.property}
                  onChange={(e) => {
                    const property = e.target.value;
                    const component = componentsFor(farType(property)).includes(spec.component)
                      ? spec.component : "histogram";
                    writeFilters(specs.map((f) => f.id === spec.id
                      ? { ...f, property, component } : f));
                  }}
                >
                  <option value="">Has link</option>
                  {props.map((p) => (
                    <option key={p.api_name} value={p.api_name}>
                      {p.display_name || p.api_name}
                    </option>
                  ))}
                </select>
                {spec.property && (
                  <select
                    aria-label="Filter component"
                    data-testid={`filter-component-${spec.id}`}
                    value={spec.component}
                    onChange={(e) => writeFilters(specs.map((f) => f.id === spec.id
                      ? { ...f, component: componentOf(e.target.value) } : f))}
                  >
                    {allowedHere.map((c) => (
                      <option key={c} value={c}>{FILTER_COMPONENT_LABELS[c]}</option>
                    ))}
                  </select>
                )}
                <button
                  type="button"
                  className="btn quiet"
                  aria-label="Remove the linked filter"
                  onClick={() => writeFilters(specs.filter((f) => f.id !== spec.id))}
                >
                  ×
                </button>
              </div>
            );
          }
          const allowed = componentsFor(dataTypeOf(spec.property));
          return (
            <div key={spec.id} className="row-actions" style={{ marginBottom: 6 }}>
              <select
                aria-label="Property"
                data-testid={`filter-property-${spec.id}`}
                value={spec.property}
                onChange={(e) => {
                  const property = e.target.value;
                  // A date range on a property that is not a date would write
                  // a comparison the server refuses; fall back rather than keep it.
                  const component = componentsFor(dataTypeOf(property)).includes(spec.component)
                    ? spec.component : "histogram";
                  writeFilters(specs.map((f) => f.id === spec.id ? { ...f, property, component } : f));
                }}
              >
                {!typeProperties.some((p) => p.api_name === spec.property) && (
                  <option value={spec.property}>{spec.property}</option>
                )}
                <PropertyOptions properties={typeProperties} union={union} />
              </select>
              <select
                aria-label="Filter component"
                data-testid={`filter-component-${spec.id}`}
                value={spec.component}
                onChange={(e) => writeFilters(specs.map((f) => f.id === spec.id
                  ? { ...f, component: componentOf(e.target.value) } : f))}
              >
                {allowed.map((c) => (
                  <option key={c} value={c}>{FILTER_COMPONENT_LABELS[c]}</option>
                ))}
              </select>
              {/* p.452: "any keyword search filter component will have the
                  advanced syntax as an option in the dropdown UI". */}
              {spec.component === "keyword" && (
                <select
                  aria-label="Search type"
                  data-testid={`filter-syntax-${spec.id}`}
                  value={spec.syntax ?? "simple"}
                  onChange={(e) => writeFilters(specs.map((f) => {
                    if (f.id !== spec.id) return f;
                    const { syntax: _old, ...rest } = f;
                    return e.target.value === "advanced" || e.target.value === "regex"
                      ? { ...rest, syntax: e.target.value } : rest;
                  }))}
                >
                  <option value="simple">Starts with</option>
                  <option value="advanced">Advanced syntax</option>
                  {/* p.130: "the property must be indexed for regex search" -
                      its Enable regex queries render hint (§728). Offered only
                      then, or kept when already chosen. */}
                  {(spec.syntax === "regex" || typeProperties.find(
                    (p) => p.api_name === spec.property)?.render_hints?.includes("regex")) && (
                    <option value="regex">Regular expression</option>
                  )}
                </select>
              )}
              <button
                type="button"
                className="btn quiet"
                aria-label={`Remove the ${spec.property} filter`}
                onClick={() => writeFilters(specs.filter((f) => f.id !== spec.id))}
              >
                ×
              </button>
            </div>
          );
        })}
        {/* p.449's Add filter: "Selecting a property here will result in that
            property being displayed within the Filter List". */}
        <select
          aria-label="Add filter"
          data-testid="filter-add"
          value=""
          onChange={(e) => {
            if (!e.target.value) return;
            const hop = hops.find((h) => `link:${h.key}` === e.target.value);
            // A link starts as p.451's Has link; a property of the linked
            // type is picked on its row.
            writeFilters([...specs, hop
              ? { id: newFilterId(specs), property: "", component: "histogram",
                  link: hop.id, linkTo: hop.toType }
              : { id: newFilterId(specs), property: e.target.value, component: "histogram" }]);
          }}
        >
          <option value="">Add filter…</option>
          <PropertyOptions properties={typeProperties} union={union} />
          {hops.length > 0 && (
            <optgroup label="Filter on a link">
              {hops.map((h) => (
                <option key={h.key} value={`link:${h.key}`}>{h.label}</option>
              ))}
            </optgroup>
          )}
        </select>
      </fieldset>
      <label className="field">
        <span className="field-label">Layout</span>
        <select
          data-testid="filter-layout"
          value={layoutOf(layout)}
          onChange={(e) => setProp((p: { layout: string }) => (p.layout = layoutOf(e.target.value)))}
        >
          <option value="vertical">Vertical</option>
          <option value="pills">Pills</option>
        </select>
      </label>
      {/* p.451's display options, once there is a linked filter to display. */}
      {specs.some((f) => f.link) && layoutOf(layout) !== "pills" && (
        <>
          <label className="field">
            <span className="field-label">Linked filters</span>
            <select
              data-testid="filter-link-display"
              value={linkDisplayOf(linkDisplay)}
              onChange={(e) =>
                setProp((p: { linkDisplay: string }) => (p.linkDisplay = e.target.value))}
            >
              {Object.entries(LINK_DISPLAYS).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </label>
          {linkDisplayOf(linkDisplay) === "grouped" && (
            <label className="field canvas-toggle">
              <input
                type="checkbox"
                data-testid="filter-collapse-linked"
                checked={collapseLinked === true}
                onChange={(e) => setProp((p: { collapseLinked: boolean }) =>
                  (p.collapseLinked = e.target.checked))}
              />
              <span className="field-label">Collapse by default</span>
            </label>
          )}
        </>
      )}
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          data-testid="filter-user-editable"
          checked={userEditable === true}
          onChange={(e) =>
            setProp((p: { userEditable: boolean }) => (p.userEditable = e.target.checked))}
        />
        <span className="field-label">Allow users to add and remove filters</span>
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
          An object set filter variable (or an array). Point a narrow_set variable at it and the set to get the
          filtered set other widgets read.
        </span>
      </label>
      </>}
    />
  );
}

export function UserSelectSettings() {
  const {
    variable, groupsVariable, mode, allowClear, label, placeholder,
    actions: { setProp },
  } = useNode((node) => ({
    variable: node.data.props.variable,
    groupsVariable: node.data.props.groupsVariable,
    mode: node.data.props.mode,
    allowClear: node.data.props.allowClear,
    label: node.data.props.label,
    placeholder: node.data.props.placeholder,
  }));
  const { declared } = useCanvasVariables();
  const multiple = userIsMultiple(mode);
  // **The kind offered follows the mode**, per p.478: a string for Single, a
  // string array for Multiple. Offering both would invite the binding the
  // server refuses on save.
  const outputs = Object.values(declared).filter(
    (v) => v.kind === (multiple ? "array" : "string"),
  );
  const groupVars = Object.values(declared).filter((v) => v.kind === "array");

  return (
    <WidgetSetup
      bindings={{ variable }}
      // **Nothing is required, and §180 wrote the reason at the Parameter
      // control**: "a rule that made configuration wait for an input would
      // leave it permanently unconfigurable". It is sharper here. This widget
      // has no input at all — p.478's group filter is optional — and the
      // *mode* decides which kind of variable the output picker offers, so
      // waiting for the output would hide the control that decides what can be
      // bound. The first version of this panel did exactly that.
      labels={{ variable: "where to put the selection" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Multipass group IDs</span>
        <select
          value={groupsVariable ?? ""}
          data-testid="user-groups-variable"
          onChange={(e) =>
            setProp((p: { groupsVariable: string | null }) =>
              (p.groupsVariable = e.target.value || null))}
        >
          <option value="">Every user in the organisation</option>
          {groupVars.map((v) => <option key={v.id} value={v.id}>{v.label || v.id}</option>)}
        </select>
        <span className="field-hint">
          A string array of group ids. The dropdown shows only their members —
          and shows nobody until the variable names at least one group, because
          &ldquo;no groups&rdquo; and &ldquo;no filter&rdquo; are the same request.
        </span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          type="text"
          value={label ?? ""}
          data-testid="user-select-label-field"
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Placeholder</span>
        <input
          type="text"
          value={placeholder ?? ""}
          data-testid="user-select-placeholder"
          onChange={(e) =>
            setProp((p: { placeholder: string }) => (p.placeholder = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Selection</span>
        <select
          value={userModeOf(mode)}
          data-testid="user-select-mode"
          onChange={(e) =>
            // **The output is cleared with the mode**, because the two modes
            // hold different kinds of variable: a `string` binding left behind
            // by Single is not a legal Multiple output, and leaving it would
            // put a refusal on the next save rather than on this change.
            setProp((p: { mode: string; variable: string | null }) => {
              p.mode = e.target.value;
              p.variable = null;
            })}
        >
          {Object.entries(USER_SELECTION_MODES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
        <span className="field-hint">
          Single writes one user id into a string variable; Multiple writes
          several into a string array. Changing this clears the output binding.
        </span>
      </label>
      {!multiple && (
        <label className="field checkbox">
          <input
            type="checkbox"
            checked={allowClear === true}
            data-testid="user-select-allow-clear"
            onChange={(e) =>
              setProp((p: { allowClear: boolean }) => (p.allowClear = e.target.checked))}
          />
          <span className="field-label">Allow clear</span>
        </label>
      )}
      </>}
      outputs={<>
      <label className="field">
        <span className="field-label">Selected user{multiple ? "s" : ""}</span>
        <select
          value={variable ?? ""}
          data-testid="user-select-variable"
          onChange={(e) =>
            setProp((p: { variable: string | null }) =>
              (p.variable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {outputs.map((v) => <option key={v.id} value={v.id}>{v.label || v.id}</option>)}
        </select>
        <span className="field-hint">
          {multiple
            ? "A string array variable — the ids of the selected users."
            : "A string variable — the id of the selected user."}
        </span>
      </label>
      </>}
    />
  );
}

export function FilterPillsSettings() {
  const {
    objectSetVariable, variable, mode, showTypePill, title,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    variable: node.data.props.variable,
    mode: node.data.props.mode,
    showTypePill: node.data.props.showTypePill,
    title: node.data.props.title,
  }));
  const { declared } = useCanvasVariables();
  const sets = Object.values(declared).filter((v) => v.kind === "object_set");
  const arrays = Object.values(declared).filter((v) => holdsClauses(v));
  const needsOutput = canRemove(mode);

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
          data-testid="pills-set"
          onChange={(e) =>
            setProp((p: { objectSetVariable: string | null }) =>
              (p.objectSetVariable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {sets.map((v) => <option key={v.id} value={v.id}>{v.label || v.id}</option>)}
        </select>
        <span className="field-hint">The set whose filters are drawn as pills</span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          type="text"
          value={title ?? ""}
          data-testid="pills-title"
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Mode</span>
        <select
          value={pillModeOf(mode)}
          data-testid="pills-mode"
          onChange={(e) => setProp((p: { mode: string }) => (p.mode = e.target.value))}
        >
          {Object.entries(PILL_MODES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
        {needsOutput && !variable && (
          <span className="field-hint" data-testid="pills-needs-output">
            This mode changes filters, so it needs the output variable below —
            without one there is nowhere for an edit to go, and the pills stay
            read-only.
          </span>
        )}
      </label>
      <label className="field checkbox">
        <input
          type="checkbox"
          checked={showTypePill === true}
          data-testid="pills-type-pill"
          onChange={(e) =>
            setProp((p: { showTypePill: boolean }) => (p.showTypePill = e.target.checked))}
        />
        <span className="field-label">Display object type pill</span>
      </label>
      {/* p.470's fourth toggle. Said rather than offered: the object-set clause
          language has no `or` between filters, so there is no operator for a
          viewer to change and nothing for a toggle to prevent. */}
      <p className="field-hint" data-testid="pills-no-operator-toggle">
        p.470&apos;s &ldquo;Prevent users from changing operators&rdquo; is not
        offered: every clause an object set takes is an <code>and</code>, so
        there is no or/and for a viewer to change.
      </p>
      </>}
      outputs={<>
      <label className="field">
        <span className="field-label">Filter variable</span>
        <select
          value={variable ?? ""}
          data-testid="pills-variable"
          onChange={(e) =>
            setProp((p: { variable: string | null }) =>
              (p.variable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {arrays.map((v) => <option key={v.id} value={v.id}>{v.label || v.id}</option>)}
        </select>
        <span className="field-hint">
          An array variable holding clauses — the same one a narrow_set uses to
          make the set these pills describe. Optional for Read only.
        </span>
      </label>
      </>}
    />
  );
}

export function SearchBarSettings() {
  const {
    objectSetVariable, variable, mode, showTypePill, placeholder, showClearButton, fillWidth,
    disableAutocomplete, disableKeyword, propertyScope, customProperties, showHelpIcon, icon,
    linkScope, customLinks,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    variable: node.data.props.variable,
    mode: node.data.props.mode,
    showTypePill: node.data.props.showTypePill,
    placeholder: node.data.props.placeholder,
    showClearButton: node.data.props.showClearButton,
    fillWidth: node.data.props.fillWidth,
    disableAutocomplete: node.data.props.disableAutocomplete,
    disableKeyword: node.data.props.disableKeyword,
    propertyScope: node.data.props.propertyScope,
    customProperties: node.data.props.customProperties,
    showHelpIcon: node.data.props.showHelpIcon,
    icon: node.data.props.icon,
    linkScope: node.data.props.linkScope,
    customLinks: node.data.props.customLinks,
  }));
  const { workspaceId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const sets = Object.values(declared).filter((v) => v.kind === "object_set");
  const arrays = Object.values(declared).filter((v) => holdsClauses(v));
  const typeId = (objectSetVariable
    ? (resolved[objectSetVariable] as { object_type_id?: string } | undefined)?.object_type_id
    : undefined) ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const scope = propertyScopeOf(propertyScope);
  const links = useQuery({
    queryKey: ["type-links", typeId],
    queryFn: () => objApi.typeLinks(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const toggles = [
    ["showClearButton", "Show clear button", showClearButton !== false],
    ["fillWidth", "Fill entire container width", fillWidth !== false],
    ["showTypePill", "Display object type pill", showTypePill === true],
    ["disableAutocomplete", "Disable property value autocomplete", disableAutocomplete === true],
    ["disableKeyword", "Disable keyword filtering", disableKeyword === true],
    ["showHelpIcon", "Show search help icon", showHelpIcon === true],
  ] as const;

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
          data-testid="search-bar-set"
          onChange={(e) => setProp((p: { objectSetVariable: string | null }) =>
            (p.objectSetVariable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {sets.map((v) => <option key={v.id} value={v.id}>{v.label || v.id}</option>)}
        </select>
        <span className="field-hint">The set whose filters the bar shows and adds to</span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Mode</span>
        <select
          value={pillModeOf(mode ?? "add")}
          data-testid="search-bar-mode"
          onChange={(e) => setProp((p: { mode: string }) => (p.mode = e.target.value))}
        >
          {Object.entries(PILL_MODES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Property types available</span>
        <select
          value={scope}
          data-testid="search-bar-scope"
          onChange={(e) => setProp((p: { propertyScope: string }) => (p.propertyScope = e.target.value))}
        >
          {Object.entries(PROPERTY_SCOPES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      {scope === "custom" && (
        <div className="field" data-testid="search-bar-custom">
          {(type.data?.properties ?? []).map((p) => (
            <label key={p.api_name} className="field checkbox">
              <input
                type="checkbox"
                data-testid={`search-bar-custom-${p.api_name}`}
                checked={(customProperties ?? []).includes(p.api_name)}
                onChange={(e) => setProp((props: { customProperties: string[] }) => {
                  const now = props.customProperties ?? [];
                  props.customProperties = e.target.checked
                    ? [...now.filter((n) => n !== p.api_name), p.api_name]
                    : now.filter((n) => n !== p.api_name);
                })}
              />
              <span className="field-label">{p.display_name || p.api_name}</span>
            </label>
          ))}
        </div>
      )}
      <label className="field">
        <span className="field-label">Link types available</span>
        <select
          value={linkScopeOf(linkScope)}
          data-testid="search-bar-link-scope"
          onChange={(e) => setProp((p: { linkScope: string }) => (p.linkScope = e.target.value))}
        >
          {Object.entries(LINK_SCOPES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
        <span className="field-hint">
          p.473&apos;s Prominent and Visible are not offered: a link type has no visibility here
        </span>
      </label>
      {linkScopeOf(linkScope) === "custom" && (
        <div className="field" data-testid="search-bar-custom-links">
          {(links.data ?? []).map((l) => (
            <label key={`${l.link_type_id}:${l.direction}`} className="field checkbox">
              <input
                type="checkbox"
                data-testid={`search-bar-custom-link-${l.api_name}`}
                checked={(customLinks ?? []).includes(l.link_type_id)}
                onChange={(e) => setProp((props: { customLinks: string[] }) => {
                  const now = props.customLinks ?? [];
                  props.customLinks = e.target.checked
                    ? [...now.filter((n) => n !== l.link_type_id), l.link_type_id]
                    : now.filter((n) => n !== l.link_type_id);
                })}
              />
              <span className="field-label">{l.side_name} ({l.far_type_display_name})</span>
            </label>
          ))}
        </div>
      )}
      <label className="field">
        <span className="field-label">Placeholder</span>
        <input
          type="text"
          value={placeholder ?? ""}
          data-testid="search-bar-placeholder"
          onChange={(e) => setProp((p: { placeholder: string }) => (p.placeholder = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Icon</span>
        <IconChoice
          value={icon}
          testId="search-bar-icon-input"
          onChange={(next) => setProp((p: { icon: string }) => (p.icon = next))}
        />
      </label>
      {toggles.map(([key, label, checked]) => (
        <label key={key} className="field checkbox">
          <input
            type="checkbox"
            checked={checked}
            data-testid={`search-bar-${key}`}
            onChange={(e) => setProp((p: Record<string, boolean>) => (p[key] = e.target.checked))}
          />
          <span className="field-label">{label}</span>
        </label>
      ))}
      <p className="field-hint">
        p.473&apos;s &ldquo;Prevent users from changing operators&rdquo; is not offered, for the
        Filter Pills&apos; reason: every clause an object set takes is an <code>and</code>.
      </p>
      </>}
      outputs={<>
      <label className="field">
        <span className="field-label">Filter variable</span>
        <select
          value={variable ?? ""}
          data-testid="search-bar-variable"
          onChange={(e) => setProp((p: { variable: string | null }) =>
            (p.variable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {arrays.map((v) => <option key={v.id} value={v.id}>{v.label || v.id}</option>)}
        </select>
        <span className="field-hint">
          The array a narrow_set reads to make the set the bar filters
        </span>
      </label>
      </>}
    />
  );
}

export function ProminentTermsSettings() {
  const {
    objectSetVariable, variable, property, terms, hideEmpty, title,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    variable: node.data.props.variable,
    property: node.data.props.property,
    terms: node.data.props.terms,
    hideEmpty: node.data.props.hideEmpty,
    title: node.data.props.title,
  }));
  const { workspaceId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const sets = Object.values(declared).filter((v) => v.kind === "object_set");
  const arrays = Object.values(declared).filter((v) => holdsClauses(v));
  const typeId = objectSetVariable
    ? ((resolved[objectSetVariable] as { object_type_id?: string } | undefined)
        ?.object_type_id ?? null)
    : null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });

  const rows = termsOf(terms);
  const write = (next: ReturnType<typeof termsOf>) =>
    setProp((p: { terms: unknown[] }) => (p.terms = next));
  const edit = (index: number, patch: Partial<ReturnType<typeof blankTerm>>) =>
    write(rows.map((t, n) => (n === index ? { ...t, ...patch } : t)));

  return (
    <WidgetSetup
      bindings={{ objectSetVariable, variable }}
      requires={["objectSetVariable"]}
      labels={{
        objectSetVariable: "an object set",
        variable: "where to put the filter",
      }}
      inputs={<>
      <label className="field">
        <span className="field-label">Base object set</span>
        <select
          value={objectSetVariable ?? ""}
          data-testid="terms-set"
          onChange={(e) =>
            setProp((p: { objectSetVariable: string | null }) =>
              (p.objectSetVariable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {sets.map((v) => <option key={v.id} value={v.id}>{v.label || v.id}</option>)}
        </select>
        <span className="field-hint">The set the counts are measured against</span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          type="text"
          value={title ?? ""}
          data-testid="terms-title"
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Property</span>
        <select
          value={property || ""}
          data-testid="terms-property"
          onChange={(e) =>
            setProp((p: { property: string }) => (p.property = e.target.value))}
        >
          <option value="">Choose…</option>
          {(type.data?.properties ?? []).map((p) => (
            <option key={p.api_name} value={p.api_name}>
              {p.display_name || p.api_name}
            </option>
          ))}
        </select>
        <span className="field-hint">
          Every term filters on this one property, matched exactly (p.475)
        </span>
      </label>
      <label className="field checkbox">
        <input
          type="checkbox"
          checked={hideEmpty === true}
          data-testid="terms-hide-empty"
          onChange={(e) =>
            setProp((p: { hideEmpty: boolean }) => (p.hideEmpty = e.target.checked))}
        />
        <span className="field-label">Hide empty terms</span>
      </label>
      <div className="field" data-testid="terms-rows">
        <span className="field-label">Terms</span>
        {rows.length === 0 && (
          <p className="field-hint" data-testid="terms-empty">
            No terms yet — the widget shows nothing until there is one.
          </p>
        )}
        {rows.map((term, index) => (
          <div className="canvas-sort-row" key={index}>
            <input
              type="text"
              value={term.value}
              placeholder="value to match"
              data-testid={`term-value-${index}`}
              onChange={(e) => edit(index, { value: e.target.value })}
            />
            <input
              type="text"
              value={term.label}
              placeholder="display name"
              data-testid={`term-label-${index}`}
              onChange={(e) => edit(index, { label: e.target.value })}
            />
            <IconChoice
              value={term.icon}
              placeholder="icon"
              testId={`term-icon-${index}`}
              onChange={(next) => edit(index, { icon: next })}
            />
            <button
              type="button"
              className="btn quiet"
              data-testid={`term-remove-${index}`}
              onClick={() => write(rows.filter((_, n) => n !== index))}
            >
              Remove
            </button>
          </div>
        ))}
        {rows.length < TERMS_MAX && (
          <button
            type="button"
            className="btn quiet"
            data-testid="term-add"
            onClick={() => write([...rows, blankTerm()])}
          >
            Add a term
          </button>
        )}
        <span className="field-hint">
          {`The value is matched exactly, so it is not trimmed. At most ${TERMS_MAX}: `
           + "each term is its own count, and a long list belongs in a Filter List."}
        </span>
      </div>
      </>}
      outputs={<>
      <label className="field">
        <span className="field-label">Filter variable</span>
        <select
          value={variable ?? ""}
          data-testid="terms-variable"
          onChange={(e) =>
            setProp((p: { variable: string | null }) =>
              (p.variable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {arrays.map((v) => <option key={v.id} value={v.id}>{v.label || v.id}</option>)}
        </select>
        <span className="field-hint">
          An array variable holding clauses. Point a narrow_set variable at it and
          the base set to get the filtered set other widgets read.
        </span>
      </label>
      </>}
    />
  );
}

export function ParameterSettings() {
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

export function NumericInputSettings() {
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
        {/* p.468: "read-only text or icon of choice" (§719). */}
        <IconChoice
          value={prefix}
          placeholder="$"
          max={40}
          testId="numeric-prefix"
          onChange={(next) => setProp((p: { prefix: string }) => (p.prefix = next))}
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
          <option value="text">Text or icon</option>
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
          <span className="field-label">Suffix text or icon</span>
          {/* p.468: "The suffix can be text, an icon of choice, or a percent
              sign" (§719). */}
          <IconChoice
            value={suffixLabel}
            placeholder="kg"
            max={40}
            testId="numeric-suffix-text"
            onChange={(next) => setProp((p: { suffixText: string }) => (p.suffixText = next))}
          />
        </label>
      )}
      </>}
    />
  );
}

export function TextInputSettings() {
  const {
    name, label, placeholder, format, rows, autoSize,
    actions: { setProp },
  } = useNode((node) => ({
    name: node.data.props.name,
    label: node.data.props.label,
    placeholder: node.data.props.placeholder,
    format: node.data.props.format,
    rows: node.data.props.rows,
    autoSize: node.data.props.autoSize,
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
      {shape.markdown && (
        <label className="field checkbox">
          <input
            type="checkbox"
            checked={autoSize !== false}
            data-testid="text-auto-size"
            onChange={(e) => setProp((p: { autoSize: boolean }) => (p.autoSize = e.target.checked))}
          />
          <span className="field-label">Auto-sizing</span>
        </label>
      )}
      </>}
    />
  );
}

export function StringSelectorSettings() {
  const {
    name, label, selection, display, optionSource, options, optionsVariable,
    placeholder, allowClearing, layout, columns, allowCreating,
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
    allowCreating: node.data.props.allowCreating,
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
      {canCreate(selection, display, true) && (
        <label className="field canvas-toggle">
          <input
            type="checkbox"
            checked={allowCreating === true}
            data-testid="selector-allow-creating"
            onChange={(e) =>
              setProp((p: { allowCreating: boolean }) => (p.allowCreating = e.target.checked))}
          />
          <span className="field-label">Allow creating new options</span>
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

export function DateTimePickerSettings() {
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

export function DateInputSettings() {
  const {
    name, endVariable, label, mode,
    actions: { setProp },
  } = useNode((node) => ({
    name: node.data.props.name,
    endVariable: node.data.props.endVariable,
    label: node.data.props.label,
    mode: node.data.props.mode,
  }));
  const { declared } = useCanvasVariables();
  const dates = Object.values(declared).filter((v) => v.kind === "date");
  const range = mode === "range";
  const hint = dates.length === 0 ? "Declare a date variable in the Variables panel first" : "";

  return (
    <WidgetSetup
      outputs={<>
      <label className="field">
        <span className="field-label">{range ? "Start date" : "Selected date"}</span>
        <select
          value={name || ""}
          data-testid="date-input-variable"
          onChange={(e) => setProp((p: { name: string }) => (p.name = e.target.value))}
        >
          <option value="">Choose…</option>
          {dates.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        {hint && <span className="field-hint">{hint}</span>}
      </label>
      {range && (
        <label className="field">
          <span className="field-label">End date</span>
          <select
            value={endVariable || ""}
            data-testid="date-input-end-variable"
            onChange={(e) => setProp((p: { endVariable: string }) => (p.endVariable = e.target.value))}
          >
            <option value="">Choose…</option>
            {dates.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
          <span className="field-hint">Written with the start, so the end is never before it</span>
        </label>
      )}
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
          value={mode || "single"}
          data-testid="date-input-mode"
          onChange={(e) => setProp((p: { mode: string }) => (p.mode = e.target.value))}
        >
          {Object.entries(DATE_INPUT_MODES).map(([key, l]) => (
            <option key={key} value={key}>{l}</option>
          ))}
        </select>
      </label>
      </>}
    />
  );
}

export function MarkdownSettings() {
  const {
    source, text, textVariable, monospace, scrolling, wordWrap, breaks, alignment,
    tagType, selectedVariable, referenceTypes, selectionBehavior,
    selectedTextVariable, selectionStartVariable, selectionEndVariable,
    annotationLayers, annotationFormat, selectedAnnotationVariable, annotationTooltip,
    highlightActions, hoverActions,
    actions: { setProp },
  } = useNode((node) => ({
    highlightActions: node.data.props.highlightActions,
    hoverActions: node.data.props.hoverActions,
    annotationLayers: node.data.props.annotationLayers,
    annotationFormat: node.data.props.annotationFormat,
    selectedAnnotationVariable: node.data.props.selectedAnnotationVariable,
    annotationTooltip: node.data.props.annotationTooltip,
    selectedTextVariable: node.data.props.selectedTextVariable,
    selectionStartVariable: node.data.props.selectionStartVariable,
    selectionEndVariable: node.data.props.selectionEndVariable,
    tagType: node.data.props.tagType,
    selectedVariable: node.data.props.selectedVariable,
    referenceTypes: node.data.props.referenceTypes,
    selectionBehavior: node.data.props.selectionBehavior,
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
  // p.320's Selected object set: written as selection clauses, the shape
  // every selecting widget here writes, into an array a derivation narrows by.
  const clauseVariables = Object.values(declared).filter(
    (v) => holdsClauses(v) && !v.derivation);
  const types = referenceTypesOf(referenceTypes);
  // p.317's outputs (§636): the text into a string, the indices into numbers.
  const writable = (kind: string) =>
    Object.values(declared).filter((v) => v.kind === kind && !v.derivation);
  const selectionOutputs: { prop: string; label: string; kind: string; value: unknown }[] = [
    { prop: "selectedTextVariable", label: "Selected text", kind: "string",
      value: selectedTextVariable },
    { prop: "selectionStartVariable", label: "Selection start index", kind: "number",
      value: selectionStartVariable },
    { prop: "selectionEndVariable", label: "Selection end index", kind: "number",
      value: selectionEndVariable },
  ];
  const writeTypes = (next: ReturnType<typeof referenceTypesOf>) =>
    setProp((p: { referenceTypes: unknown }) => (p.referenceTypes = next));

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
      {/* p.316's Tag type configuration and p.320's reference options (§632). */}
      <label className="field">
        <span className="field-label">Tag type</span>
        <select
          value={tagType === "inline_reference" || tagType === "annotation" ? tagType : "standard"}
          data-testid="markdown-tag-type"
          onChange={(e) => setProp((p: { tagType: string }) => (p.tagType = e.target.value))}
        >
          <option value="standard">Standard</option>
          <option value="inline_reference">Inline reference</option>
          <option value="annotation">Annotation</option>
        </select>
        {tagType === "inline_reference" && (
          <span className="field-hint">
            {":objectreference[text]{objectType=\"api_name\" primaryKey=\"key\"}"}
          </span>
        )}
      </label>
      {tagType === "inline_reference" && (
        <>
          <label className="field">
            <span className="field-label">Selected object set</span>
            <select
              value={selectedVariable || ""}
              data-testid="markdown-ref-selected"
              onChange={(e) => setProp((p: { selectedVariable: string | null }) =>
                (p.selectedVariable = e.target.value || null))}
            >
              <option value="">None</option>
              {clauseVariables.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
            <span className="field-hint">
              The selected reference, as a filter on its key; derive a set from it
            </span>
          </label>
          <div className="field" data-testid="markdown-ref-types">
            <span className="field-label">Object types</span>
            {types.map((type, i) => (
              <MarkdownReferenceTypeRow key={i} index={i} type={type} newId={newReferenceTypeId(types)}
                onChange={(next) => writeTypes(types.map((t, j) => (j === i ? next : t)))}
                onRemove={() => writeTypes(types.filter((_, j) => j !== i))} />
            ))}
            <div className="field-inline">
              <input
                type="text"
                data-testid="markdown-ref-new-type"
                placeholder="api_name"
                onKeyDown={(e) => {
                  const value = e.currentTarget.value.trim();
                  if (e.key !== "Enter" || !value) return;
                  e.preventDefault();
                  writeTypes([...types, { objectType: value, color: null, colorMode: "static",
                    colorProperty: null, colorRules: null, overrideSelection: false, id: null }]);
                  e.currentTarget.value = "";
                }}
              />
            </div>
            <span className="field-hint">
              A reference to a type not listed here is shown as plain text (p.320)
            </span>
          </div>
          <label className="field">
            <span className="field-label">Selection behavior</span>
            <select
              value={referenceSelectionOf(selectionBehavior)}
              data-testid="markdown-ref-behavior"
              onChange={(e) => setProp((p: { selectionBehavior: string }) =>
                (p.selectionBehavior = e.target.value))}
            >
              {Object.entries(REFERENCE_SELECTIONS).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </label>
        </>
      )}
      {/* p.321-322's annotations (§637). */}
      {tagType === "annotation" && (() => {
        const layers = annotationLayersOf(annotationLayers);
        const sets = Object.values(declared).filter((v) => v.kind === "object_set");
        const write = (next: typeof layers) =>
          setProp((p: { annotationLayers: unknown }) => (p.annotationLayers = next));
        const change = (i: number, patch: Partial<(typeof layers)[number]>) =>
          write(layers.map((l, j) => (j === i ? { ...l, ...patch } : l)));
        return (
          <div className="field" data-testid="markdown-annotation-settings">
            <span className="field-label">Annotation layers</span>
            {layers.map((layer, i) => (
              <div key={i} className="field" data-testid="markdown-annotation-layer">
                <input type="text" aria-label={`Layer ${i + 1} name`} value={layer.name}
                  placeholder="Name" onChange={(e) => change(i, { name: e.target.value })} />
                <select aria-label={`Layer ${i + 1} object set`}
                  data-testid="markdown-annotation-set"
                  value={layer.objectSetVariable ?? ""}
                  onChange={(e) => change(i, { objectSetVariable: e.target.value || null })}>
                  <option value="">Choose an object set…</option>
                  {sets.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                </select>
                <input type="text" aria-label={`Layer ${i + 1} start index property`}
                  data-testid="markdown-annotation-start" placeholder="Start index property"
                  value={layer.startProperty}
                  onChange={(e) => change(i, { startProperty: e.target.value })} />
                <input type="text" aria-label={`Layer ${i + 1} end index property`}
                  data-testid="markdown-annotation-end" placeholder="End index property"
                  value={layer.endProperty}
                  onChange={(e) => change(i, { endProperty: e.target.value })} />
                <input type="color" aria-label={`Layer ${i + 1} highlight colour`}
                  value={layer.color ?? "#2563eb"}
                  onChange={(e) => change(i, { color: e.target.value })} />
                <AnnotationLayerRules index={i} layer={layer} onChange={(patch) => change(i, patch)} />
                <button type="button" className="btn quiet" aria-label={`Remove layer ${i + 1}`}
                  onClick={() => write(layers.filter((_, j) => j !== i))}>×</button>
              </div>
            ))}
            <button type="button" className="btn" data-testid="markdown-annotation-add"
              onClick={() => write([...layers, { name: "", objectSetVariable: null,
                startProperty: "", endProperty: "", color: null, colorMode: "static", colorRules: null }])}>
              Add a layer
            </button>
            <label className="field">
              <span className="field-label">Annotation formatting</span>
              <select data-testid="markdown-annotation-format"
                value={annotationFormatOf(annotationFormat)}
                onChange={(e) => setProp((p: { annotationFormat: string }) =>
                  (p.annotationFormat = e.target.value))}>
                {Object.entries(ANNOTATION_FORMATS).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Selected annotation</span>
              <select data-testid="markdown-annotation-selected"
                value={selectedAnnotationVariable || ""}
                onChange={(e) => setProp((p: { selectedAnnotationVariable: string | null }) =>
                  (p.selectedAnnotationVariable = e.target.value || null))}>
                <option value="">None</option>
                {clauseVariables.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Properties to display in tooltip</span>
              <input type="text" data-testid="markdown-annotation-tooltip"
                value={annotationTooltip || ""} placeholder="author, note"
                onChange={(e) => setProp((p: { annotationTooltip: string }) =>
                  (p.annotationTooltip = e.target.value))} />
            </label>
            {/* p.322's On hover interactions (§669). */}
            <div className="field" data-testid="markdown-hover-settings">
              <span className="field-label">On hover interactions</span>
              {hoverActionsOf(hoverActions).map((action, i) => (
                <div key={action.id} className="field-inline">
                  <input type="text" aria-label={`Hover interaction ${i + 1} title`}
                    value={action.label}
                    onChange={(e) => setProp((p: { hoverActions: unknown }) =>
                      (p.hoverActions = renameItem(hoverActionsOf(p.hoverActions), action.id, e.target.value)))} />
                  <IconChoice
                    value={action.icon}
                    testId={`markdown-hover-icon-${i}`}
                    onChange={(next) => setProp((p: { hoverActions: unknown }) =>
                      (p.hoverActions = setItemIcon(hoverActionsOf(p.hoverActions), action.id, next)))}
                  />
                  <button type="button" className="btn quiet" aria-label={`Remove hover interaction ${i + 1}`}
                    onClick={() => setProp((p: { hoverActions: unknown }) =>
                      (p.hoverActions = removeItem(hoverActionsOf(p.hoverActions), action.id)))}>
                    ×
                  </button>
                </div>
              ))}
              <button type="button" className="btn" data-testid="markdown-hover-add"
                onClick={() => setProp((p: { hoverActions: unknown }) =>
                  (p.hoverActions = addHoverAction(hoverActionsOf(p.hoverActions))))}>
                Add an interaction
              </button>
              <span className="field-hint">
                Offered on an annotation&apos;s hover card; wire each in Events, where {"{{primary_key}}"} is the
                hovered annotation
              </span>
            </div>
            <span className="field-hint">
              Indices are into this Markdown: zero-based, start inclusive, end exclusive —
              what User text selection writes
            </span>
          </div>
        );
      })()}
      {/* p.322's Create annotations via actions or events (§638). */}
      <div className="field" data-testid="markdown-highlight-settings">
        <span className="field-label">Actions on highlighted text</span>
        {itemsOf(highlightActions).map((action, i) => (
          <div key={action.id} className="field-inline">
            <input
              type="text"
              aria-label={`Highlight action ${i + 1} title`}
              data-testid="markdown-highlight-title"
              value={action.label}
              onChange={(e) => setProp((p: { highlightActions: unknown }) =>
                (p.highlightActions = renameItem(itemsOf(p.highlightActions), action.id,
                  e.target.value)))}
            />
            <IconChoice
              value={action.icon}
              testId={`markdown-highlight-icon-${i}`}
              onChange={(next) => setProp((p: { highlightActions: unknown }) =>
                (p.highlightActions = setItemIcon(itemsOf(p.highlightActions), action.id, next)))}
            />
            <button
              type="button"
              className="btn quiet"
              aria-label={`Remove highlight action ${i + 1}`}
              onClick={() => setProp((p: { highlightActions: unknown }) =>
                (p.highlightActions = removeItem(itemsOf(p.highlightActions), action.id)))}
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn"
          data-testid="markdown-highlight-add"
          onClick={() => setProp((p: { highlightActions: unknown }) =>
            (p.highlightActions = addItem(itemsOf(p.highlightActions))))}
        >
          Add an action
        </button>
        <span className="field-hint">
          Offered on highlighted text; wire each in Events, where {"{{value}}"} is the text
        </span>
      </div>
      {/* p.317's User text selection (§636). */}
      <div className="field" data-testid="markdown-selection-outputs">
        <span className="field-label">User text selection</span>
        {selectionOutputs.map((output) => (
          <label key={output.prop} className="field">
            <span className="field-label">{output.label}</span>
            <select
              value={typeof output.value === "string" ? output.value : ""}
              data-testid={`markdown-${output.prop}`}
              onChange={(e) => setProp((p: Record<string, unknown>) =>
                (p[output.prop] = e.target.value || null))}
            >
              <option value="">Not output</option>
              {writable(output.kind).map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
          </label>
        ))}
        <span className="field-hint">
          The raw Markdown selected, and where it starts and ends in the text
        </span>
      </div>
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

export function DatasetTableSettings() {
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

/** p.266's "During configuration, unsupported properties are indicated with a
 * warning icon and tooltip", beside a widget's choice of properties. */
function UnsupportedNote({ properties, testId }: {
  properties: readonly ObjectTypeProperty[];
  testId: string;
}) {
  const heavy = properties.filter(isUnsupported);
  if (heavy.length === 0) return null;
  return (
    <span className="field-hint" data-testid={testId}>
      {heavy.map((p) => (
        <span key={p.api_name} title={UNSUPPORTED_HINT} className="canvas-unsupported">
          ⚠ {p.display_name || p.api_name}{" "}
        </span>
      ))}
      {heavy.length === 1 ? "is" : "are"} loaded on demand: a reader selects Load to see
      {heavy.length === 1 ? " it" : " them"}.
    </span>
  );
}

/** **One** page ordering, chosen from the four fixed sorts and the object
 * type's orderable properties — p.458's "Sort items by" for the Object Dropdown
 * and Object Selector, and p.132's property sorts for the Loop layout.
 *
 * **One control for three widgets, which is the whole argument of §231.** All
 * three carried a hint saying the platform could not sort by a property, all
 * three were wrong from §221, and the reason none of them noticed is that each
 * had typed the constraint out privately. The types come from
 * `property-sort.ts` and the sentence beneath comes from `ORDERABLE_HINT`, so
 * there is nothing here for a fourth widget to disagree with.
 *
 * **A select rather than the Object Table's three controls.** p.223's setting is
 * a *list* whose order is itself the setting, so it needs a row with a kind, a
 * property and a direction. This is one ordering, and 4 + 2n options in a single
 * select is the shape a person can read in one glance — the direction is part of
 * the option because "capacity, high to low" is how somebody says it.
 *
 * The list is empty until the ontology resolves, and the stored value is shown
 * meanwhile: a select that fell back to the default while loading would rewrite
 * the author's setting on the next keystroke somewhere else in the panel.
 */
function PropertySortField({ value, properties, onChange, testId, label }: {
  value: unknown;
  properties: readonly SortableProperty[];
  onChange: (sort: string) => void;
  testId: string;
  label: string;
}) {
  const sortable = orderableProperties(properties);
  const stored = typeof value === "string" && value ? value : DROPDOWN_DEFAULT_SORT;
  // What is *shown* is the stored value whenever the ontology has not ruled it
  // out — `requestSort` only overrides once there is a property list to check
  // against, which is what stops a half-loaded panel from looking like a reset.
  const shown = sortable.length > 0
    ? requestSort(stored, sortable, DROPDOWN_DEFAULT_SORT) ?? DROPDOWN_DEFAULT_SORT
    : stored;
  const known = Object.hasOwn(DROPDOWN_SORTS, shown)
    || sortable.some((p) => p.api_name === shown.replace(/^-/, ""));

  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select
        value={shown}
        data-testid={testId}
        onChange={(e) => onChange(e.target.value)}
      >
        {/* A stored sort the type no longer offers is shown as its own option
            rather than silently swapped: the author has to be able to see what
            the document says before deciding to change it. The widget sends the
            fallback regardless — `requestSort` is what makes that safe. */}
        {!known && <option value={shown}>{shown} — no longer sortable</option>}
        {Object.entries(DROPDOWN_SORTS).map(([key, name]) => (
          <option key={key} value={key}>{name}</option>
        ))}
        {sortable.map((p) => (
          <Fragment key={p.api_name}>
            <option value={p.api_name}>
              {`${p.display_name || p.api_name} — low to high`}
            </option>
            <option value={`-${p.api_name}`}>
              {`${p.display_name || p.api_name} — high to low`}
            </option>
          </Fragment>
        ))}
      </select>
      <span className="field-hint" data-testid={`${testId}-hint`}>
        {sortable.length > 0
          ? ORDERABLE_HINT
          : `This object type declares no property both stores can order. ${ORDERABLE_HINT}`}
      </span>
    </label>
  );
}

/** p.223's **Default sort(s)**: "one or more default sorts to be applied to the
 * table".
 *
 * A list of rows rather than one select, because p.223's setting is a list and
 * the *order* of it is the setting. Each row is one of the four fixed sorts or
 * a property with a direction — the rules are in `table-sorts.ts`, so what
 * this component holds is the editing and nothing else.
 *
 * **The property is picked as of §231**, and this paragraph used to explain why
 * it was typed: "a picker over the ontology's orderable properties is one
 * decision for every widget that wants one — the Timeline, the Object Dropdown's
 * p.458 sort, this — and building it three times privately is how three widgets
 * end up disagreeing about which properties are offered." That is what
 * `property-sort.ts` is, and this field is one of its four callers. The text box
 * survives as the fallback for the case that made §225 leave it: this widget can
 * be configured from p.65's object-type half before any type is chosen, and the
 * panel has no property list then.
 *
 * p.223 asks for something a column list cannot give — "module builders can sort
 * on **hidden property types not displayed**" — and the picker satisfies it,
 * because it lists what the *type* declares rather than what the table shows.
 */
function TableSortsField({ sort, properties, derived = [], setProp }: {
  sort: unknown;
  /** Every property the type declares. Empty while the ontology resolves, and
   * empty is why the text box is still here rather than deleted. */
  properties: readonly SortableProperty[];
  /** The module's derived columns for this type, sortable over p.173's
   * limits (§781). */
  derived?: readonly { api_name: string; display_name?: string }[];
  setProp: (cb: (props: { sort: string | string[] }) => void) => void;
}) {
  const sortable = [
    ...orderableProperties(properties),
    ...derived.map((c) => ({ api_name: c.api_name,
                             display_name: `${c.display_name || c.api_name} (derived)` })),
  ];
  const entries = tableSortsOf(sort);
  const write = (next: ReturnType<typeof tableSortsOf>) => {
    const keys = next.map((e) => e.key);
    // **A row still being typed is kept, not dropped**, so the author can
    // finish it — `toRequest` is what refuses to send it. Written back as a
    // string when there is one, so a table with a single ordering keeps the
    // document shape every module before p.223 had.
    const only = keys.length === 1 ? keys[0] : "";
    setProp((p) => (p.sort = only ? only : keys));
  };
  const edit = (index: number, entry: ReturnType<typeof blankTableSort>) =>
    write(entries.map((e, n) => (n === index ? entry : e)));

  return (
    <div className="field" data-testid="table-sorts">
      <span className="field-label">Default sort(s)</span>
      {entries.length === 0 && (
        <p className="field-hint" data-testid="table-sorts-empty">
          No sort set — rows come back newest-changed first.
        </p>
      )}
      {entries.map((entry, index) => (
        <div className="canvas-sort-row" key={index}>
          <select
            value={entry.fixed ? entry.key : ""}
            data-testid={`table-sort-kind-${index}`}
            onChange={(e) => edit(index, withSortFixed(entry, e.target.value))}
          >
            <option value="">A property…</option>
            {Object.entries(TABLE_FIXED_SORTS).map(([key, name]) => (
              <option key={key} value={key}>{name}</option>
            ))}
          </select>
          {!entry.fixed && (
            <>
              {/* **A picker when the ontology is there, a text box when it is
                  not.** §225 shipped the text box because this panel had no
                  property list; §231 gave it one, and a picker is strictly
                  better — it cannot name a property that does not exist, and it
                  cannot offer a `string` the server refuses. The text box stays
                  as the fallback rather than as an alternative: this widget can
                  be configured before an object type is chosen (p.65's choice),
                  and a control that vanished then would look broken. p.223's
                  "hidden property types not displayed" is satisfied either way,
                  because the list is the *type's* properties and not the
                  table's columns. */}
              {sortable.length > 0 ? (
                <select
                  value={entry.property}
                  data-testid={`table-sort-property-${index}`}
                  onChange={(e) => edit(index, withSortProperty(entry, e.target.value))}
                >
                  <option value="">Choose a property…</option>
                  {!!entry.property
                    && !sortable.some((p) => p.api_name === entry.property) && (
                    <option value={entry.property}>
                      {`${entry.property} — no longer sortable`}
                    </option>
                  )}
                  {sortable.map((p) => (
                    <option key={p.api_name} value={p.api_name}>
                      {p.display_name || p.api_name}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={entry.property}
                  placeholder="property api name"
                  data-testid={`table-sort-property-${index}`}
                  onChange={(e) => edit(index, withSortProperty(entry, e.target.value))}
                />
              )}
              <select
                value={entry.descending ? "desc" : "asc"}
                data-testid={`table-sort-direction-${index}`}
                onChange={(e) =>
                  edit(index, withSortDirection(entry, e.target.value === "desc"))}
              >
                <option value="asc">Low to high</option>
                <option value="desc">High to low</option>
              </select>
            </>
          )}
          <button
            type="button"
            className="btn quiet"
            data-testid={`table-sort-remove-${index}`}
            onClick={() => write(entries.filter((_, n) => n !== index))}
          >
            Remove
          </button>
        </div>
      ))}
      {entries.length < TABLE_MAX_SORTS && (
        <button
          type="button"
          className="btn quiet"
          data-testid="table-sort-add"
          onClick={() => write([...entries, blankTableSort()])}
        >
          Add a sort
        </button>
      )}
      {entries.length > 1 && (
        <span className="field-hint" data-testid="table-sorts-summary">
          {entries.map(tableSortLabel).join(", then ")}
        </span>
      )}
      {/* Not a click on a column header, deliberately. A header that sometimes
          422s — on a property whose declared type has no order both stores
          agree on — would be worse than one that never invited the click. See
          `object_sets.PROPERTY_SORT_HINT`. */}
      <span className="field-hint">{ORDERABLE_HINT}</span>
    </div>
  );
}

/** p.241's inline-edit block, which p.241 places "within the Column
 * configuration section below the Columns list" - so that is where it is.
 *
 * **The picker offers only what the executor will accept.** `eligibleActions`
 * reads §238's `inline_edit_refusals`, computed on the server, rather than
 * deciding here: p.240's criteria govern writes, and a panel that judged them
 * in another language would be free to disagree with the endpoint that runs
 * them. When nothing on this object type qualifies the block says so and names
 * why for the nearest miss, because "no actions" and "none that can do this"
 * send a builder to two different places.
 */
/** Variable kinds that hold no value a parameter could take (§598). */
const FEEDLESS_KINDS: readonly string[] = [
  "object_set", "object_set_filter", "time_series_set",
];

function InlineEditField({ actions, columns, inlineEdit, mapping, feeds, variables, setProp }: {
  actions: readonly import("@/lib/types").ActionType[] | undefined;
  /** The columns the table is currently displaying, which p.241 makes the
   * only things a parameter may be mapped onto. */
  columns: readonly string[];
  inlineEdit: unknown;
  mapping: unknown;
  /** p.241's variables passed as action parameters (§598). */
  feeds: unknown;
  variables: readonly import("@/lib/types").WorkshopVariable[];
  setProp: (cb: (props: Record<string, unknown>) => void) => void;
}) {
  const eligible = eligibleActions(actions);
  const chosen = eligible.find((a) => a.id === inlineEdit) ?? null;
  const current = mappingOf(mapping, chosen, columns);
  const fed = variableFeedsOf(feeds, chosen, variables.map((v) => v.id), current);
  // A value a parameter can take: not a set, a filter or a series.
  const feedable = variables.filter((v) => !FEEDLESS_KINDS.includes(v.kind));
  const refusedExample = (actions ?? []).find(
    (a) => (a.inline_edit_refusals?.length ?? 0) > 0,
  );

  return (
    <div className="field" data-testid="inline-edit">
      <span className="field-label">Enable inline editing</span>
      <select
        value={typeof inlineEdit === "string" ? inlineEdit : ""}
        data-testid="inline-edit-action"
        onChange={(e) =>
          setProp((p) => {
            p.inlineEditAction = e.target.value || null;
            // **Seeded on the way in, not derived on every render** (p.241's
            // "automatic mapping"). Derived, a builder could never unmap a
            // matching column - the mapping would come straight back. Seeded,
            // it is a starting point they own.
            p.inlineEditMapping = e.target.value
              ? automaticMapping(eligible.find((a) => a.id === e.target.value), columns)
              : {};
          })
        }
      >
        <option value="">Off</option>
        {eligible.map((a) => (
          <option key={a.id} value={a.id}>{a.display_name || a.api_name}</option>
        ))}
      </select>
      {eligible.length === 0 && (
        <span className="field-hint" data-testid="inline-edit-none">
          {refusedExample
            ? `No action on this object type can back a cell edit. ${
              refusedExample.display_name || refusedExample.api_name}: ${
              refusedExample.inline_edit_refusals?.[0]}`
            : "No actions on this object type yet — create one in the Ontology Manager"}
        </span>
      )}
      {chosen && (
        <div data-testid="inline-edit-mapping">
          {(chosen.parameters ?? []).map((parameter) => (
            <label className="field" key={parameter.api_name}>
              <span className="field-label">
                {parameter.display_name || parameter.api_name}
              </span>
              <select
                value={current[parameter.api_name] ?? ""}
                data-parameter={parameter.api_name}
                onChange={(e) =>
                  setProp((p) => {
                    const next = { ...current };
                    if (e.target.value) next[parameter.api_name] = e.target.value;
                    else delete next[parameter.api_name];
                    p.inlineEditMapping = next;
                    // A column and a variable are one or the other (§598).
                    if (e.target.value) {
                      const { [parameter.api_name]: _dropped, ...rest } = fed;
                      p.inlineEditVariables = rest;
                    }
                  })
                }
              >
                <option value="">Not editable</option>
                {columns.map((column) => (
                  <option key={column} value={column}>{column}</option>
                ))}
              </select>
              {/* p.241: "You can also pass variables as action parameters
                  that will get passed into the action automatically without
                  the user needing to edit the field in the table" (§598). */}
              <select
                value={fed[parameter.api_name] ?? ""}
                aria-label={`${parameter.display_name || parameter.api_name} from a variable`}
                data-testid={`inline-edit-variable-${parameter.api_name}`}
                onChange={(e) =>
                  setProp((p) => {
                    const next = { ...fed };
                    if (e.target.value) next[parameter.api_name] = e.target.value;
                    else delete next[parameter.api_name];
                    p.inlineEditVariables = next;
                    if (e.target.value) {
                      const { [parameter.api_name]: _dropped, ...rest } = current;
                      p.inlineEditMapping = rest;
                    }
                  })
                }
              >
                <option value="">Or from a variable…</option>
                {feedable.map((v) => (
                  <option key={v.id} value={v.id}>{v.label}</option>
                ))}
              </select>
            </label>
          ))}
          <span className="field-hint">
            {/* p.135: an unmapped parameter is not a gap. The batch seeds every
                untouched parameter from the object, so a parameter left "Not
                editable" keeps its value rather than clearing it. */}
            A parameter left unmapped keeps whatever the object already holds. One
            from a variable takes the variable&apos;s value, for every row submitted.
          </span>
        </div>
      )}
    </div>
  );
}

export function ObjectTableSettings() {
  const { workspaceId, derivedColumns } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    objectTypeId, filterProperty, filterParameter, searchParameter,
    objectSetVariable, pageSize, columns, sort,
    activeVariable, autoSelect, multiSelect, selectedVariable,
    lines, valueWrap, frozenColumns, emptyMode, emptyMessage, emptyIcon,
    customNoValue, noValueText, fitColumns, narrowHeaders, formatFillsCell,
    inlineEditAction, inlineEditMapping, inlineEditVariables, inlineEditButtonText,
    inlineEditByDefault, inlineEditOneClick, seriesFormats, seriesRules, seriesTransforms, seriesBaselines,
    columnsVariable, exportCsv, exportExcel, hideColumnConfig, customMenu, menuItems,
    rightClickedVariable, combineTypes,
    actions: { setProp },
  } = useNode((node) => ({
    combineTypes: node.data.props.combineTypes,
    customMenu: node.data.props.customMenu,
    menuItems: node.data.props.menuItems,
    rightClickedVariable: node.data.props.rightClickedVariable,
    hideColumnConfig: node.data.props.hideColumnConfig,
    columnsVariable: node.data.props.columnsVariable,
    exportCsv: node.data.props.exportCsv,
    exportExcel: node.data.props.exportExcel,
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
    emptyIcon: node.data.props.emptyIcon,
    emptyMode: node.data.props.emptyMode,
    emptyMessage: node.data.props.emptyMessage,
    customNoValue: node.data.props.customNoValue,
    noValueText: node.data.props.noValueText,
    fitColumns: node.data.props.fitColumns,
    narrowHeaders: node.data.props.narrowHeaders,
    formatFillsCell: node.data.props.formatFillsCell,
    inlineEditAction: node.data.props.inlineEditAction,
    inlineEditMapping: node.data.props.inlineEditMapping,
    inlineEditVariables: node.data.props.inlineEditVariables,
    inlineEditButtonText: node.data.props.inlineEditButtonText,
    inlineEditByDefault: node.data.props.inlineEditByDefault,
    inlineEditOneClick: node.data.props.inlineEditOneClick,
    seriesFormats: node.data.props.seriesFormats,
    seriesRules: node.data.props.seriesRules,
    seriesTransforms: node.data.props.seriesTransforms,
    seriesBaselines: node.data.props.seriesBaselines,
  }));
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  // **`array`, not `object_set`.** p.224 calls these outputs object sets and
  // they end up as ones, but what the widget *writes* is the clause list a
  // `narrow_set` derivation reads - so the variable to bind here is the array
  // in the middle. Offering object-set variables would invite binding the
  // derived one and overwriting the thing that derives it.
  const clauseVariables = Object.values(declared).filter((v) => holdsClauses(v));
  // `TypePicker` owns the object type read now (§256): the listing is a page,
  // so a control over it has to be able to search the ontology rather than the
  // rows it happened to receive.
  // **Either half of p.65's choice**, because p.223's sort picker needs the
  // declared properties whichever way this widget was populated: a directly
  // picked object type, or the one behind a bound object set. Before §231 the
  // sort's property was typed by hand, so it needed neither.
  const sortTypeId = objectTypeId
    ?? (objectSetVariable
      ? ((resolved[objectSetVariable] as { object_type_id?: string } | undefined)
          ?.object_type_id ?? null)
      : null);
  const detail = useQuery({
    queryKey: ["object-type", sortTypeId],
    queryFn: () => objApi.getType(workspaceId, sortTypeId!),
    enabled: !!sortTypeId,
  });
  // p.241's action picker. Asked of the *object type* rather than of the bound
  // set, for the reason §212's link endpoint exists: a builder configures a
  // widget before there is data, and answering from today's rows would make the
  // set of configurable actions depend on whether the table happened to be
  // empty.
  const tableActions = useQuery({
    queryKey: ["action-types", workspaceId, sortTypeId],
    queryFn: () => actionApi.listTypes(workspaceId, sortTypeId!),
    enabled: !!sortTypeId,
  });
  // The columns p.241 lets a parameter be mapped onto: what the table displays,
  // which is the configured list when there is one and every property when
  // there is not - the same rule the widget itself renders by.
  const shownColumns = useMemo(() => {
    const wanted = String(columns || "").split(",").map((c) => c.trim()).filter(Boolean);
    const all = (detail.data?.properties ?? []).map((p) => p.api_name);
    return wanted.length ? wanted.filter((c) => all.includes(c)) : all;
  }, [columns, detail.data]);
  // p.174 scopes Workshop value formatting to *time series* columns, so the
  // controls are offered for those and nothing else. Every other column is
  // written by the ontology's formatter (§157) and an override here would be
  // the second place to set the same thing.
  // §610: names the column visibility variable holds that are not columns of
  // this table - said here, where somebody can act on them. Only once the
  // type has been read, for `seriesColumns`' reason below.
  const configuredColumns = String(columns || "").split(",").map((c) => c.trim())
    .filter(Boolean);
  const strayColumns = columnsVariable && detail.data
    ? unknownColumns(
      configuredColumns.length
        ? configuredColumns
        : detail.data.properties.map((p) => p.api_name),
      resolved[columnsVariable],
    )
    : [];
  const seriesColumns = useMemo(() => {
    const types = new Map(
      (detail.data?.properties ?? []).map((prop) => [prop.api_name, prop.data_type]),
    );
    return shownColumns.filter((name) => types.get(name) === "time_series");
  }, [shownColumns, detail.data]);
  const savedFormats = useMemo(() => formatsByColumn(seriesFormats), [seriesFormats]);
  const savedRules = useMemo(() => rulesByColumn(seriesRules), [seriesRules]);

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
        {/* §256: the listing behind this is a page, so the control searches
            the ontology rather than the fifty rows it happened to receive. */}
        <TypePicker
          workspaceId={workspaceId}
          value={objectTypeId || ""}
          disabled={!!objectSetVariable}
          placeholder="Choose…"
          onChange={(id) =>
            setProp((p: Record<string, unknown>) => {
              p.objectTypeId = id || null;
              p.filterProperty = null;  // property names are per-type
            })
          }
        />
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
        <UnsupportedNote properties={detail.data?.properties ?? []} testId="table-unsupported" />
      </label>
      {/* p.225's "Variable-backed column visibility" (§610). String arrays
          only - an array of numbers names no column - and an untyped one,
          which may hold names. */}
      <label className="field">
        <span className="field-label">Column visibility variable</span>
        <select
          value={columnsVariable ?? ""}
          data-testid="table-columns-variable"
          onChange={(e) => setProp((p: { columnsVariable: string | null }) =>
            (p.columnsVariable = e.target.value || null))}
        >
          <option value="">None — show the columns above</option>
          {Object.values(declared)
            .filter((v) => v.kind === "array" && (!v.element || v.element === "string"))
            .map((v) => (
              <option key={v.id} value={v.id}>{v.label || v.id}</option>
            ))}
        </select>
        <span className="field-hint">
          p.225: a string array of the column names to show, in its order. Empty shows
          all the columns above.
        </span>
        {strayColumns.length > 0 && (
          <span className="field-hint" data-testid="table-columns-variable-unknown">
            Not columns of this table, so not shown: {strayColumns.join(", ")}
          </span>
        )}
      </label>
      {/* p.174's value formatting, one control per time series column shown.
          **Only when the type has been read**: before that `seriesColumns` is
          empty for want of the property list rather than because there are no
          series columns, and an absent section says that more honestly than a
          "no time series columns" sentence that would be wrong for a moment. */}
      {seriesColumns.map((name) => (
        <ValueFormatField
          key={name}
          label={`Format ${name}`}
          testId={`series-format-${name}`}
          value={savedFormats[name] ?? null}
          hint="The latest value of this series. Local to this module (p.174)."
          onChange={(next) =>
            setProp((p: { seriesFormats: Record<string, NumberFormat> | null }) => {
              // A rebuilt map rather than a mutated one, and the cleared entry
              // *deleted* rather than set to null: `formatsByColumn` would drop
              // a null anyway, but a document full of tombstones is a document
              // where "has this column been formatted" has two answers.
              const next_ = { ...savedFormats };
              if (next) next_[name] = next;
              else delete next_[name];
              p.seriesFormats = Object.keys(next_).length ? next_ : null;
            })
          }
        />
      ))}
      {/* p.175's rules, beside p.174's formatter and on the same columns -
          the two pages name the same pair of surfaces. */}
      {seriesColumns.map((name) => (
        <ConditionalFormatField
          key={`rules-${name}`}
          subject={SERIES_SUBJECT}
          testId={`series-rules-${name}`}
          value={savedRules[name] ?? null}
          hint={`Paints ${name}'s value and its sparkline (p.175).`}
          onChange={(next) =>
            setProp((p: { seriesRules: Record<string, ConditionalRule[]> | null }) => {
              // Same rebuild-and-delete as the formatter map above, for the
              // same reason: a tombstone makes "has this column got rules"
              // two questions instead of one.
              const built = { ...savedRules };
              if (next) built[name] = next;
              else delete built[name];
              p.seriesRules = Object.keys(built).length ? built : null;
            })
          }
        />
      ))}
      {/* p.583's transforms (§555), per series column: "different time series
          transforms are applied … to generate new time series". */}
      {seriesColumns.map((name) => (
        <div key={`transforms-${name}`} className="field" data-testid={`series-chain-${name}`}>
          <span className="field-label">Series {name}</span>
          <SeriesTransformsEditor
            transforms={transformsByColumn(seriesTransforms)[name] ?? []}
            readOnly={false}
            onChange={(next) => setProp((p: { seriesTransforms: unknown }) => {
              p.seriesTransforms = withColumnTransforms(p.seriesTransforms, name, next);
            })}
          />
        </div>
      ))}
      {/* p.592-593's baselines (§563), per series column. */}
      {seriesColumns.map((name) => {
        const current = baselinesByColumn(seriesBaselines)[name] ?? null;
        const set = (next: ColumnBaseline | null) =>
          setProp((p: { seriesBaselines: unknown }) => {
            p.seriesBaselines = withColumnBaseline(p.seriesBaselines, name, next);
          });
        const numeric = (detail.data?.properties ?? [])
          .filter((prop) => prop.data_type === "integer" || prop.data_type === "float");
        return (
          <div key={`baseline-${name}`} className="field" data-testid={`series-baseline-${name}`}>
            <span className="field-label">Baseline for {name}</span>
            <select
              aria-label={`Baseline for ${name}`}
              value={current?.kind ?? "none"}
              onChange={(e) => set(
                e.target.value === "static" ? { kind: "static", value: 0 }
                  : e.target.value === "property" && numeric[0]
                    ? { kind: "property", property: numeric[0].api_name }
                    : e.target.value === "series" ? { kind: "series", summary: "last" }
                      : null)}
            >
              {Object.entries(COLUMN_BASELINE_KINDS).map(([kind, label]) => (
                <option key={kind} value={kind} disabled={kind === "property" && !numeric.length}>
                  {label}
                </option>
              ))}
            </select>
            {current?.kind === "static" && (
              <input
                type="number"
                aria-label={`Baseline value for ${name}`}
                value={current.value}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  if (e.target.value !== "" && Number.isFinite(value)) set({ kind: "static", value });
                }}
              />
            )}
            {current?.kind === "property" && (
              <select
                aria-label={`Baseline property for ${name}`}
                value={current.property}
                onChange={(e) => set({ kind: "property", property: e.target.value })}
              >
                {numeric.map((prop) => (
                  <option key={prop.api_name} value={prop.api_name}>
                    {prop.display_name || prop.api_name}
                  </option>
                ))}
              </select>
            )}
            {current?.kind === "series" && (
              <select
                aria-label={`Baseline summary for ${name}`}
                value={current.summary}
                onChange={(e) => set({ kind: "series", summary: e.target.value })}
              >
                {Object.entries(BASELINE_SUMMARIES).map(([how, label]) => (
                  <option key={how} value={how}>{label}</option>
                ))}
              </select>
            )}
          </div>
        );
      })}
      {/* p.241: "the toggle to Enable inline editing will appear within the
          Column configuration section below the Columns list". */}
      <InlineEditField
        actions={tableActions.data}
        columns={shownColumns}
        inlineEdit={inlineEditAction}
        mapping={inlineEditMapping}
        feeds={inlineEditVariables}
        variables={Object.values(declared)}
        setProp={setProp}
      />
      {inlineEditAction && (
        <>
          <label className="field">
            <span className="field-label">Custom button text</span>
            <input
              type="text"
              value={typeof inlineEditButtonText === "string" ? inlineEditButtonText : ""}
              placeholder={DEFAULT_BUTTON_TEXT}
              onChange={(e) =>
                setProp((p: { inlineEditButtonText: string }) =>
                  (p.inlineEditButtonText = e.target.value))
              }
            />
          </label>
          <label className="field-check">
            <input
              type="checkbox"
              checked={editByDefaultOf(inlineEditByDefault)}
              onChange={(e) =>
                setProp((p: { inlineEditByDefault: boolean }) =>
                  (p.inlineEditByDefault = e.target.checked))
              }
            />
            <span>Enable edit mode by default</span>
          </label>
          <label className="field-check">
            <input
              type="checkbox"
              checked={oneClickOf(inlineEditOneClick)}
              onChange={(e) =>
                setProp((p: { inlineEditOneClick: boolean }) =>
                  (p.inlineEditOneClick = e.target.checked))
              }
            />
            <span>One-click submit</span>
          </label>
          <span className="field-hint">
            {/* p.243 makes the dialog the default and the toggle the way past
                it, which is the safer direction for a control that writes to
                every staged row at once. */}
            Without this, Submit asks for confirmation before writing.
          </span>
        </>
      )}
      {/* p.225's Combine multiple object types (§689): offered over a union,
          and "not available when Enable inline editing is set to true". */}
      {unionParts(objectSetVariable ? resolved[objectSetVariable] : undefined) && (
        <>
          <label className="field-check">
            <input
              type="checkbox"
              data-testid="table-combine-types"
              checked={!!combineTypes && !inlineEditAction}
              disabled={!!inlineEditAction}
              onChange={(e) =>
                setProp((p: { combineTypes: boolean }) => (p.combineTypes = e.target.checked))}
            />
            <span>Combine multiple object types</span>
          </label>
          <span className="field-hint">
            {inlineEditAction
              ? "Not available while inline editing is on (p.225)."
              : "One table rather than a tab per type. Columns with the same name and ID are one column; a combined table pages to 200 objects."}
          </span>
        </>
      )}
      {/* p.225's Hide column configuration (§612). */}
      <label className="field-check">
        <input
          type="checkbox"
          data-testid="table-hide-column-config"
          checked={!!hideColumnConfig}
          onChange={(e) =>
            setProp((p: { hideColumnConfig: boolean }) => (p.hideColumnConfig = e.target.checked))}
        />
        <span>Hide column configuration</span>
      </label>
      <span className="field-hint">
        p.222: without this, a reader can choose which of the table&rsquo;s columns to see and
        in what order, from the arrow beside the Key header. Their choice stays in their browser.
      </span>
      {/* p.223's Right-click menu (§611). */}
      <label className="field-check">
        <input
          type="checkbox"
          data-testid="table-export-csv-toggle"
          checked={!!exportCsv}
          onChange={(e) => setProp((p: { exportCsv: boolean }) => (p.exportCsv = e.target.checked))}
        />
        <span>Enable export to CSV</span>
      </label>
      <span className="field-hint" data-testid="table-export-csv-hint">
        {objectSetVariable
          ? "A reader right-clicks a row to download every object in the set (up to 10,000), "
            + "in the columns shown."
          : "Offered when the table reads an object set variable: a table narrowed by a "
            + "search box is not a set an export can name."}
      </span>
      <label className="field-check">
        <input
          type="checkbox"
          data-testid="table-export-excel-toggle"
          checked={!!exportExcel}
          onChange={(e) =>
            setProp((p: { exportExcel: boolean }) => (p.exportExcel = e.target.checked))}
        />
        <span>Enable export to Excel</span>
      </label>
      <span className="field-hint">
        The same rows as an Excel workbook, in the property columns shown; derived
        columns go in the CSV. Up to 10,000 objects, not p.223&apos;s 200,000: the
        store reads a set a page at a time, and stops at ten thousand.
      </span>
      {/* p.243's Customize right-click menu (§613). */}
      <label className="field-check">
        <input
          type="checkbox"
          data-testid="table-custom-menu-toggle"
          checked={!!customMenu}
          onChange={(e) =>
            setProp((p: { customMenu: boolean; menuItems: unknown }) => {
              p.customMenu = e.target.checked;
              // A menu with nothing in it opens nothing, so the first switch
              // on starts it with an item to rename - the menu button's rule.
              if (e.target.checked && itemsOf(p.menuItems).length === 0) {
                p.menuItems = addItem([]);
              }
            })}
        />
        <span>Customize right-click menu</span>
      </label>
      {customMenu && (
        <>
          <label className="field">
            <span className="field-label">Right-clicked object</span>
            <select
              value={rightClickedVariable || ""}
              data-testid="table-right-clicked-variable"
              onChange={(e) =>
                setProp((p: { rightClickedVariable: string | null }) =>
                  (p.rightClickedVariable = e.target.value || null))}
            >
              <option value="">None</option>
              {clauseVariables.map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
            <span className="field-hint">
              Holds the clauses that pick the row a reader right-clicked, as the active object does
            </span>
          </label>
          <fieldset className="field" data-testid="table-menu-items">
            <legend className="field-label">Menu items</legend>
            {itemsOf(menuItems).map((item) => (
              <div key={item.id} className="row-actions">
                <input
                  value={item.label}
                  aria-label={`Label of ${item.label || item.id}`}
                  data-testid={`table-menu-item-${item.id}`}
                  onChange={(e) =>
                    setProp((p: { menuItems: unknown }) =>
                      (p.menuItems = renameItem(itemsOf(p.menuItems), item.id, e.target.value)))}
                />
                <button
                  type="button"
                  className="btn quiet"
                  aria-label={`Remove ${item.label || item.id}`}
                  onClick={() =>
                    setProp((p: { menuItems: unknown }) =>
                      (p.menuItems = removeItem(itemsOf(p.menuItems), item.id)))}
                >
                  ×
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn quiet"
              data-testid="table-menu-add-item"
              onClick={() =>
                setProp((p: { menuItems: unknown }) => (p.menuItems = addItem(itemsOf(p.menuItems))))}
            >
              Add item
            </button>
            <span className="field-hint">
              Each item fires its own events, with the right-clicked row as the selection: wire
              them in the Events panel under Right-click menu item
            </span>
          </fieldset>
        </>
      )}
      <TableSortsField
        sort={sort}
        properties={detail.data?.properties ?? []}
        derived={columnsFor(derivedColumns, String(detail.data?.id ?? ""))}
        setProp={setProp}
      />
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
          <span className="field-hint">Blank falls back to “No objects found”</span>
        </label>
      )}
      {emptyModeOf(emptyMode) === "custom" && (
        <label className="field">
          <span className="field-label">Icon</span>
          {/* p.224's Custom "display icon" (§719); none draws the message alone. */}
          <IconChoice
            value={emptyIcon}
            testId="table-empty-icon-input"
            onChange={(next) => setProp((p: { emptyIcon: string }) => (p.emptyIcon = next))}
          />
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

export function ObjectSetTitleSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, single, showIcon, titleOverride, renderWhenEmpty,
    placeholderTypeId, enableDrag,
    actions: { setProp },
  } = useNode((node) => ({
    enableDrag: node.data.props.enableDrag,
    objectSetVariable: node.data.props.objectSetVariable,
    single: node.data.props.single,
    showIcon: node.data.props.showIcon,
    titleOverride: node.data.props.titleOverride,
    renderWhenEmpty: node.data.props.renderWhenEmpty,
    placeholderTypeId: node.data.props.placeholderTypeId,
  }));
  const { declared } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  // `TypePicker` owns the object type read now (§256): the listing is a page,
  // so a control over it has to be able to search the ontology rather than the
  // rows it happened to receive.

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
      {/* p.274's order: Enable drag comes after Show icon. */}
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={!!enableDrag}
          data-testid="set-title-enable-drag"
          onChange={(e) => setProp((p: { enableDrag: boolean }) => (p.enableDrag = e.target.checked))}
        />
        <span className="field-label">Enable drag</span>
        <span className="field-hint">
          Onto a section with Drop Handling. Only while the set has fewer than 500 objects
        </span>
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
          <TypePicker
            workspaceId={workspaceId}
            testId="set-title-placeholder"
            value={placeholderTypeId || ""}
            placeholder="None"
            onChange={(id) =>
              setProp((p: { placeholderTypeId: string | null }) =>
                (p.placeholderTypeId = id || null))}
          />
          <span className="field-hint">
            Named so an empty widget still says what it would have shown
          </span>
        </label>
      )}
      </>}
    />
  );
}

export function PropertyListSettings() {
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
        <UnsupportedNote properties={type.data?.properties ?? []} testId="property-list-unsupported" />
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

/** p.272's Display properties in object preview for one chosen link
 * (§549): none ticked is the prominent ones, as p.271 has it. */
function LinkPreviewField({ workspaceId, farTypeId, testid, value, onChange }: {
  workspaceId: string;
  farTypeId: string;
  testid: string;
  value: string[];
  onChange: (preview: string[]) => void;
}) {
  const far = useQuery({
    queryKey: ["object-type", farTypeId],
    queryFn: () => objApi.getType(workspaceId, farTypeId),
  });
  return (
    <fieldset className="field" data-testid={testid}>
      <legend className="field-label">Preview shows</legend>
      {(far.data?.properties ?? []).map((p) => (
        <label className="canvas-toggle" key={p.api_name}>
          <input
            type="checkbox"
            data-testid={`${testid}-${p.api_name}`}
            checked={value.includes(p.api_name)}
            onChange={(e) => onChange(e.target.checked
              ? [...value, p.api_name] : value.filter((x) => x !== p.api_name))}
          />
          <span>{p.display_name || p.api_name}</span>
        </label>
      ))}
      <span className="field-hint">None ticked shows the prominent properties</span>
    </fieldset>
  );
}

/** p.272's Sort linked object by for one chosen link (§548): the linked
 * type's properties that have an order both stores agree on, and a
 * direction. Text is not offered, as the server would refuse it. */
function LinkSortField({ workspaceId, farTypeId, testid, value, onChange }: {
  workspaceId: string;
  farTypeId: string;
  testid: string;
  value: string | undefined;
  onChange: (sort: string | undefined) => void;
}) {
  const far = useQuery({
    queryKey: ["object-type", farTypeId],
    queryFn: () => objApi.getType(workspaceId, farTypeId),
  });
  const descending = !!value?.startsWith("-");
  const property = value?.replace(/^-/, "") ?? "";
  return (
    <span className="row-actions">
      <select
        aria-label="Sort linked objects by"
        data-testid={testid}
        value={property}
        onChange={(e) => onChange(e.target.value
          ? `${descending ? "-" : ""}${e.target.value}` : undefined)}
      >
        <option value="">The store&apos;s order</option>
        {orderableProperties(far.data?.properties ?? []).map((p) => (
          <option key={p.api_name} value={p.api_name}>{p.display_name || p.api_name}</option>
        ))}
      </select>
      {property && (
        <select
          aria-label="Sort direction"
          data-testid={`${testid}-direction`}
          value={descending ? "desc" : "asc"}
          onChange={(e) => onChange(`${e.target.value === "desc" ? "-" : ""}${property}`)}
        >
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
      )}
    </span>
  );
}

export function LinksWidgetSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, linkMode, links, defaultExpand, exploreLinks, openObjects, previewOnHover,
    actions: { setProp },
  } = useNode((node) => ({
    exploreLinks: node.data.props.exploreLinks,
    openObjects: node.data.props.openObjects,
    previewOnHover: node.data.props.previewOnHover,
    objectSetVariable: node.data.props.objectSetVariable,
    linkMode: node.data.props.linkMode,
    links: node.data.props.links,
    defaultExpand: node.data.props.defaultExpand,
  }));
  const { declared, resolved } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const bound = objectSetVariable ? resolved[objectSetVariable] : undefined;
  const typeId = (bound as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  // **The type's links, not the bound object's.** p.272 says the dropdown
  // follows from choosing a starting object set, and which links exist is a
  // fact about the object type - asking the traversal endpoint would make the
  // configurable set depend on whether today's set happens to be empty.
  const available = useQuery({
    queryKey: ["type-links", workspaceId, typeId],
    queryFn: () => objApi.typeLinks(workspaceId, typeId!),
    enabled: !!typeId,
  });

  const chosen = linkChosenOf(links);
  const write = (next: ChosenLink[]) =>
    setProp((p: { links: ChosenLink[] }) => (p.links = next));

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
          data-testid="links-variable"
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
          The links of the first object in the set, which is what p.268 explores
        </span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Link types to display</span>
        <select
          value={linkModeOf(linkMode)}
          data-testid="links-mode"
          onChange={(e) => setProp((p: { linkMode: string }) => (p.linkMode = e.target.value))}
        >
          {Object.entries(LINK_MODES).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </label>
      {linkModeOf(linkMode) === "specify" && (
        <div className="field">
          <span className="field-label">Link types</span>
          {!typeId ? (
            <span className="field-hint">Bind an object set first</span>
          ) : available.data && available.data.length === 0 ? (
            <span className="field-hint">
              This object type has no mapped links. A link also needs to say which
              properties join before anything can be traversed.
            </span>
          ) : (
            <div className="canvas-link-picker" data-testid="links-picker">
              {(available.data ?? []).map((link) => {
                const key = linkKey(link);
                const picked = chosen.find((c) => c.key === key);
                return (
                  <div className="canvas-link-choice" key={key}>
                    <label className="canvas-toggle">
                      <input
                        type="checkbox"
                        checked={!!picked}
                        data-testid={`links-pick-${key}`}
                        onChange={() =>
                          write(picked
                            ? chosen.filter((c) => c.key !== key)
                            : [...chosen, { key }])}
                      />
                      <span className="field-label">
                        {link.side_name} → {link.far_type_display_name}
                      </span>
                    </label>
                    {picked && (
                      <input
                        type="text"
                        placeholder={link.side_name}
                        value={picked.label ?? ""}
                        data-testid={`links-label-${key}`}
                        onChange={(e) =>
                          write(chosen.map((c) => {
                            if (c.key !== key) return c;
                            const { label: _old, ...rest } = c;
                            return e.target.value ? { ...rest, label: e.target.value } : rest;
                          }))}
                      />
                    )}
                    {/* p.272's Sort linked object by (§548): a property of the
                        linked type that has an order, and a direction. */}
                    {picked && (
                      <LinkSortField
                        workspaceId={workspaceId}
                        farTypeId={link.far_type_id}
                        testid={`links-sort-${key}`}
                        value={picked.sort}
                        onChange={(sort) => write(chosen.map((c) => {
                          if (c.key !== key) return c;
                          const { sort: _old, ...rest } = c;
                          return sort ? { ...rest, sort } : rest;
                        }))}
                      />
                    )}
                    {/* p.272: "If "Enable object preview on hover" is enabled,
                        the specified link type's linked objects can be
                        configured to show … specified properties" (§549). */}
                    {picked && previewOnHover === true && (
                      <LinkPreviewField
                        workspaceId={workspaceId}
                        farTypeId={link.far_type_id}
                        testid={`links-preview-${key}`}
                        value={picked.preview ?? []}
                        onChange={(preview) => write(chosen.map((c) => {
                          if (c.key !== key) return c;
                          const { preview: _old, ...rest } = c;
                          return preview.length ? { ...rest, preview } : rest;
                        }))}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          )}
          <span className="field-hint">
            Ticked links are drawn in the order they were ticked. A self-link
            appears twice, once per direction — they are different questions.
          </span>
        </div>
      )}
      <label className="field">
        <span className="field-label">Default link expand</span>
        <input
          type="number"
          min={0}
          max={MAX_DEFAULT_EXPAND}
          value={defaultExpandOf(defaultExpand)}
          data-testid="links-default-expand"
          onChange={(e) =>
            setProp((p: { defaultExpand: number }) =>
              (p.defaultExpand = Number(e.target.value)))}
        />
        <span className="field-hint">
          How many of the sections shown open on load (p.271)
        </span>
      </label>
      {/* p.271's linked objects configuration (§547). */}
      {([
        ["exploreLinks", "links-explore", "Enable exploration on link types",
          "A button on each link to see its objects in the Object Explorer"],
        ["openObjects", "links-open", "Enable open object view on linked objects",
          "A button on each object to open its Object View in the Object Explorer"],
        ["previewOnHover", "links-preview", "Enable object preview on hover",
          "Hovering an object shows its type's prominent properties"],
      ] as const).map(([prop, testid, label, hint]) => (
        <label className="field canvas-toggle" key={prop}>
          <input
            type="checkbox"
            data-testid={testid}
            checked={{ exploreLinks, openObjects, previewOnHover }[prop] === true}
            onChange={(e) =>
              setProp((p: Record<string, boolean>) => (p[prop] = e.target.checked))}
          />
          <span className="field-label">{label}</span>
          <span className="field-hint">{hint}</span>
        </label>
      ))}
      </>}
    />
  );
}

/** p.263's **Interface configuration** (§710): "Defines a mapping from the
 * current module's variables to an object view tab's module interface …
 * select a tab that has a module interface defined and populate the
 * interface." Each tab of the bound set's type's view, with the variables its
 * module publishes; the view's subject is the object itself, so it is not
 * offered. The type is the one the widget's set names - p.263's "adding an
 * object type to the mapping" is that choice, made by the set. */
function ViewInterfaceFields({ typeId, formFactor }: { typeId: string; formFactor: string }) {
  const { workspaceId } = useCanvasEnv();
  const {
    mapping,
    actions: { setProp },
  } = useNode((node) => ({ mapping: (node.data.props.viewInterface ?? {}) as Record<string, string> }));
  const hostVariables = useCanvasVariables().declared;
  const view = useQuery({
    queryKey: ["object-view", workspaceId, typeId, formFactor],
    queryFn: () => objApi.getView(workspaceId, typeId, formFactor),
  });
  const tabs = view.data?.tabs ?? [];
  const modules = useQueries({
    queries: tabs.map((tab) => ({
      queryKey: ["published-canvas-app", tab.canvas_app_id],
      queryFn: () => canvasApi.getPublished(workspaceId, tab.canvas_app_id),
    })),
  });
  if (view.isPending) return null;
  if (!view.data) {
    return (
      <p className="field-hint" data-testid="object-view-interface-none">
        This object type has no configured view, so there is no interface to pass into.
      </p>
    );
  }
  return (
    <div className="field" data-testid="object-view-interface">
      <span className="field-label">Interface configuration</span>
      {tabs.map((tab, index) => {
        const definition = modules[index]?.data?.definition;
        const published = Object.values(definition ? variablesOf(definition) : {})
          .filter((v) => v.interface && v.external_id && v.id !== tab.subject_variable);
        return (
          <div key={tab.id} className="field">
            <span className="field-hint">{tab.title || tab.canvas_app_name}</span>
            {definition && published.length === 0 && (
              <span className="field-hint">This tab&apos;s module publishes no interface.</span>
            )}
            {published.map((variable) => {
              const key = interfaceKey(tab.id, variable.external_id!);
              const compatible = Object.values(hostVariables).filter((h) => h.kind === variable.kind);
              return (
                <label key={key} className="field">
                  <span className="field-label">
                    {variable.interface?.display_name || variable.label}
                  </span>
                  <select
                    value={mapping[key] ?? ""}
                    data-testid={`object-view-map-${variable.external_id}`}
                    onChange={(e) =>
                      setProp((p: { viewInterface?: Record<string, string> }) => {
                        const next = { ...(p.viewInterface ?? {}) };
                        if (e.target.value) next[key] = e.target.value;
                        else delete next[key];
                        p.viewInterface = next;
                      })
                    }
                  >
                    <option value="">Not passed — it uses its own definition</option>
                    {compatible.map((h) => (
                      <option key={h.id} value={h.id}>{h.label}</option>
                    ))}
                  </select>
                </label>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

export function ObjectViewWidgetSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, viewMode, allowToggle, hideHeader, emptyMessage, emptyIcon, formFactor, panelBehavior,
    hideTabs, goToInitialTab, initialTabId,
    actions: { setProp },
  } = useNode((node) => ({
    hideTabs: node.data.props.hideTabs,
    goToInitialTab: node.data.props.goToInitialTab,
    initialTabId: node.data.props.initialTabId,
    formFactor: node.data.props.formFactor,
    panelBehavior: node.data.props.panelBehavior,
    objectSetVariable: node.data.props.objectSetVariable,
    viewMode: node.data.props.viewMode,
    allowToggle: node.data.props.allowToggle,
    hideHeader: node.data.props.hideHeader,
    emptyMessage: node.data.props.emptyMessage,
    emptyIcon: node.data.props.emptyIcon,
  }));
  const { declared, resolved } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const bound = objectSetVariable ? resolved[objectSetVariable] : undefined;
  const typeId = (bound as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  // So the panel can say whether the mode above is going to mean anything.
  const view = useQuery({
    queryKey: ["object-view", workspaceId, typeId],
    queryFn: () => objApi.getView(workspaceId, typeId!),
    enabled: !!typeId,
  });

  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Object to display</span>
        <select
          value={objectSetVariable || ""}
          data-testid="object-view-variable"
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
          Only the first object is shown, which is what p.261 says a set of several does
        </span>
      </label>
      </>}
      configuration={<>
      {/* p.261's Form factor and p.263's Panel behavior (§694). */}
      <label className="field">
        <span className="field-label">Form factor</span>
        <select
          value={formFactorOf(formFactor)}
          data-testid="object-view-form-factor"
          onChange={(e) => setProp((p: { formFactor: string }) => (p.formFactor = e.target.value))}
        >
          {Object.entries(OBJECT_FORM_FACTORS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </label>
      {formFactorOf(formFactor) === "panel" && (
        <label className="field">
          <span className="field-label">Panel behavior</span>
          <select
            value={panelBehaviorOf(panelBehavior)}
            data-testid="object-view-panel-behavior"
            onChange={(e) =>
              setProp((p: { panelBehavior: string }) => (p.panelBehavior = e.target.value))}
          >
            {Object.entries(PANEL_BEHAVIORS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
          <span className="field-hint">
            {panelBehaviorOf(panelBehavior) === "adaptive"
              ? "One object shows its panel; none or several show the set's."
              : panelBehaviorOf(panelBehavior) === "set"
                ? "The set's panel: its charts and a list, whatever it holds."
                : "The first object's panel, whatever the set holds."}
          </span>
        </label>
      )}
      <label className="field">
        <span className="field-label">Object view mode</span>
        <select
          value={viewModeOf(viewMode)}
          data-testid="object-view-mode"
          onChange={(e) => setProp((p: { viewMode: string }) => (p.viewMode = e.target.value))}
        >
          {Object.entries(VIEW_MODES).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
        <span className="field-hint" data-testid="object-view-configured-hint">
          {!typeId
            ? "Bind an object set first"
            : view.data
              ? `This type has a configured view: ${view.data.canvas_app_name}`
              : "This type has no configured view, so the standard one is shown either way"}
        </span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={allowToggleOf(allowToggle)}
          data-testid="object-view-allow-toggle"
          onChange={(e) =>
            setProp((p: { allowToggle: boolean }) => (p.allowToggle = e.target.checked))}
        />
        <span className="field-label">Let the reader switch views</span>
        <span className="field-hint">
          On by default: the standard view stays reachable unless you say otherwise
        </span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={hideHeaderOf(hideHeader)}
          data-testid="object-view-hide-header"
          onChange={(e) =>
            setProp((p: { hideHeader: boolean }) => (p.hideHeader = e.target.checked))}
        />
        <span className="field-label">Hide header</span>
        <span className="field-hint">
          The type name and object title above the standard view
        </span>
      </label>
      {/* p.262-263's tab settings (§695), for a full view of several tabs:
          "this is only applicable to object views with multiple tabs". */}
      {formFactorOf(formFactor) === "full" && (view.data?.tabs.length ?? 0) > 1 && (
        <>
          <label className="field">
            <span className="field-label">Initial object view tab</span>
            <select
              value={initialTabId ?? ""}
              data-testid="object-view-initial-tab"
              onChange={(e) =>
                setProp((p: { initialTabId: string }) => (p.initialTabId = e.target.value))}
            >
              <option value="">The first tab</option>
              {view.data!.tabs.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
          </label>
          <label className="field canvas-toggle">
            <input
              type="checkbox"
              checked={hideTabs === true}
              data-testid="object-view-hide-tabs"
              onChange={(e) =>
                setProp((p: { hideTabs: boolean }) => (p.hideTabs = e.target.checked))}
            />
            <span className="field-label">Hide tabs</span>
            <span className="field-hint">The reader sees the initial tab only</span>
          </label>
          <label className="field canvas-toggle">
            <input
              type="checkbox"
              checked={goToInitialTab === true}
              data-testid="object-view-initial-on-switch"
              onChange={(e) =>
                setProp((p: { goToInitialTab: boolean }) => (p.goToInitialTab = e.target.checked))}
            />
            <span className="field-label">Go to initial tab on object switch</span>
          </label>
        </>
      )}
      <label className="field">
        <span className="field-label">Empty state message</span>
        <input
          type="text"
          value={emptyMessage ?? ""}
          placeholder={objectViewEmptyMessageOf("")}
          data-testid="object-view-empty-message"
          onChange={(e) =>
            setProp((p: { emptyMessage: string }) => (p.emptyMessage = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Empty state icon</span>
        <IconChoice
          value={emptyIcon}
          testId="object-view-empty-icon-input"
          onChange={(next) => setProp((p: { emptyIcon: string }) => (p.emptyIcon = next))}
        />
      </label>
      {typeId && <ViewInterfaceFields typeId={typeId} formFactor={formFactorOf(formFactor)} />}
      </>}
    />
  );
}

export function PieChartSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, groupBy, aggregation, aggregationProperty, inner, legend,
    showLegend, ontologyColors, filterVariable,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    groupBy: node.data.props.groupBy,
    aggregation: node.data.props.aggregation,
    aggregationProperty: node.data.props.aggregationProperty,
    inner: node.data.props.inner,
    legend: node.data.props.legend,
    showLegend: node.data.props.showLegend,
    ontologyColors: node.data.props.ontologyColors,
    filterVariable: node.data.props.filterVariable,
  }));
  const { declared, resolved } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const arrays = Object.values(declared).filter((v) => holdsClauses(v));
  const bound = objectSetVariable ? resolved[objectSetVariable] : undefined;
  const typeId = (bound as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });

  return (
    <WidgetSetup
      bindings={{ objectSetVariable, groupBy }}
      requires={["objectSetVariable", "groupBy"]}
      labels={{ objectSetVariable: "an object set", groupBy: "a property to group by" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Input object set</span>
        <select
          value={objectSetVariable || ""}
          data-testid="pie-variable"
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
      <label className="field">
        <span className="field-label">Group by</span>
        <select
          value={groupBy || ""}
          data-testid="pie-group-by"
          onChange={(e) => setProp((p: { groupBy: string }) => (p.groupBy = e.target.value))}
        >
          <option value="">Choose…</option>
          {/* p.250's Selectable (§727): only what may be grouped by - and
              the current choice, whatever it is, so it is not silently
              replaced by "Choose…". */}
          {(type.data?.properties ?? []).filter((p) => isSelectable(p) || p.api_name === groupBy)
            .map((p) => (
              <option key={p.api_name} value={p.api_name}>{p.display_name || p.api_name}</option>
            ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Aggregation</span>
        <select
          value={pieAggregationOf(aggregation)}
          data-testid="pie-aggregation"
          onChange={(e) =>
            setProp((p: { aggregation: string }) => (p.aggregation = e.target.value))}
        >
          {Object.entries(PIE_AGGREGATIONS).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
        <span className="field-hint">What sizes a slice</span>
      </label>
      {pieNeedsProperty(aggregation) && (
        <label className="field">
          <span className="field-label">Aggregate over</span>
          <select
            value={aggregationProperty || ""}
            data-testid="pie-aggregation-property"
            onChange={(e) =>
              setProp((p: { aggregationProperty: string }) =>
                (p.aggregationProperty = e.target.value))}
          >
            <option value="">Choose…</option>
            {/* **Only the properties the server will aggregate**: every one
                for a distinct count (§615), which asks about identity, and
                integer and float for arithmetic, since `object_sets` refuses
                the rest and a picker that offered a date would produce a
                sentence about arithmetic in place of a chart. The Metric
                Card's rule, read rather than repeated. */}
            {metricPropertiesFor(aggregation, type.data?.properties ?? []).map((p) => (
              <option key={p.api_name} value={p.api_name}>
                {p.display_name || p.api_name}
              </option>
            ))}
          </select>
          <span className="field-hint" data-testid="pie-aggregation-property-hint">
            {pieAggregationOf(aggregation) === "count_distinct"
              ? "How many different values it has in each slice"
              : "Integer and float properties only — the two the stores order and add "
                + "identically (decision 0006)"}
          </span>
        </label>
      )}
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Inner radius</span>
        <input
          type="number"
          min={0}
          max={MAX_INNER_RADIUS}
          step={0.1}
          value={innerRadiusOf(inner)}
          data-testid="pie-inner"
          onChange={(e) => setProp((p: { inner: number }) => (p.inner = Number(e.target.value)))}
        />
        <span className="field-hint">Zero is a pie; anything above it is a donut</span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={showLegendOf(showLegend)}
          data-testid="pie-show-legend"
          onChange={(e) =>
            setProp((p: { showLegend: boolean }) => (p.showLegend = e.target.checked))}
        />
        <span className="field-label">Show legend</span>
      </label>
      <label className="field">
        <span className="field-label">Legend position</span>
        <select
          value={legendPositionOf(legend)}
          data-testid="pie-legend-position"
          onChange={(e) => setProp((p: { legend: string }) => (p.legend = e.target.value))}
        >
          {Object.entries(LEGEND_POSITIONS).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={ontologyColors === true}
          data-testid="pie-ontology-colors"
          onChange={(e) =>
            setProp((p: { ontologyColors: boolean }) => (p.ontologyColors = e.target.checked))}
        />
        <span className="field-label">Enable ontology colors</span>
        <span className="field-hint">
          The conditional formatting rules set for this property in the Ontology
        </span>
      </label>
      <label className="field">
        <span className="field-label">Selection as filter</span>
        <select
          value={filterVariable || ""}
          data-testid="pie-filter-variable"
          onChange={(e) =>
            setProp((p: { filterVariable: string | null }) =>
              (p.filterVariable = e.target.value || null))}
        >
          <option value="">Clicking a slice does nothing</option>
          {arrays.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          An array variable holding clauses, which a narrow_set derivation reads
        </span>
      </label>
      </>}
    />
  );
}

export function StepperSettings() {
  const {
    steps, stepperType, template, showStepNumber, completedColour, activeColour,
    actions: { setProp },
  } = useNode((node) => ({
    steps: node.data.props.steps,
    stepperType: node.data.props.stepperType,
    template: node.data.props.template,
    showStepNumber: node.data.props.showStepNumber,
    completedColour: node.data.props.completedColour,
    activeColour: node.data.props.activeColour,
  }));
  const { declared } = useCanvasVariables();
  const booleans = Object.values(declared).filter((v) => v.kind === "boolean");
  const drawn = stepsOf(steps);
  const write = (next: unknown[]) => setProp((p: { steps: unknown[] }) => (p.steps = next));

  return (
    <WidgetSetup
      inputs={<>
      <div className="field">
        <span className="field-label">Steps</span>
        <div className="canvas-step-editor" data-testid="stepper-steps">
          {drawn.map((step, index) => (
            <div className="canvas-step-row" key={index}>
              <input
                type="text"
                value={step.label}
                data-testid={`stepper-label-${index}`}
                onChange={(e) =>
                  write(drawn.map((s, i) =>
                    i === index ? { ...s, label: e.target.value } : s))}
              />
              <select
                value={step.completedVariable ?? ""}
                data-testid={`stepper-done-${index}`}
                onChange={(e) =>
                  write(drawn.map((s, i) =>
                    i === index ? { ...s, completedVariable: e.target.value } : s))}
              >
                <option value="">Never completed</option>
                {booleans.map((v) => (
                  <option key={v.id} value={v.id}>{v.label}</option>
                ))}
              </select>
              {/* p.313's Icon, drawn by the icon template (§707). */}
              <IconChoice
                value={step.icon}
                testId={`stepper-icon-${index}`}
                onChange={(next) =>
                  write(drawn.map((s, i) => (i === index ? { ...s, icon: next } : s)))}
              />
              <button
                type="button"
                className="btn quiet"
                data-testid={`stepper-remove-${index}`}
                onClick={() => write(drawn.filter((_, i) => i !== index))}
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn quiet"
            data-testid="stepper-add"
            onClick={() => write([...drawn, { label: `Step ${drawn.length + 1}` }])}
          >
            Add step
          </button>
        </div>
        <span className="field-hint">
          Completion is a boolean variable the module writes, so the stepper holds no progress
          of its own
        </span>
      </div>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Type</span>
        <select
          value={stepperTypeOf(stepperType)}
          data-testid="stepper-type"
          onChange={(e) =>
            setProp((p: { stepperType: string }) => (p.stepperType = e.target.value))}
        >
          {Object.entries(STEPPER_TYPES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Template</span>
        <select
          value={stepperTemplateOf(template)}
          data-testid="stepper-template"
          onChange={(e) => setProp((p: { template: string }) => (p.template = e.target.value))}
        >
          {Object.entries(STEPPER_TEMPLATES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={showStepNumber === true}
          data-testid="stepper-show-number"
          onChange={(e) =>
            setProp((p: { showStepNumber: boolean }) => (p.showStepNumber = e.target.checked))}
        />
        <span className="field-label">Show step number</span>
        <span className="field-hint">
          {showsStepNumber({ template, type: stepperType, show: true })
            ? "Numbers appear beside the icons"
            : "p.313 applies this to a linear stepper using icons; the text template is already numbered"}
        </span>
      </label>
      <label className="field">
        <span className="field-label">Completed colour</span>
        <input
          type="text"
          value={completedColour ?? ""}
          placeholder={completedColourOf("")}
          data-testid="stepper-completed-colour"
          onChange={(e) =>
            setProp((p: { completedColour: string }) => (p.completedColour = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Active colour</span>
        <input
          type="text"
          value={activeColour ?? ""}
          placeholder={activeColourOf("")}
          data-testid="stepper-active-colour"
          onChange={(e) =>
            setProp((p: { activeColour: string }) => (p.activeColour = e.target.value))}
        />
      </label>
      </>}
    />
  );
}

export function TimelineSettings() {
  const {
    layers, orientation, order, showLegend, showGaps, activeVariable,
    highlightSelection,
    actions: { setProp },
  } = useNode((node) => ({
    layers: node.data.props.layers,
    orientation: node.data.props.orientation,
    order: node.data.props.order,
    showLegend: node.data.props.showLegend,
    showGaps: node.data.props.showGaps,
    activeVariable: node.data.props.activeVariable,
    highlightSelection: node.data.props.highlightSelection,
  }));
  const { declared } = useCanvasVariables();
  const sets = Object.values(declared).filter((v) => v.kind === "object_set");
  const arrays = Object.values(declared).filter((v) => holdsClauses(v));
  const drawn = timelineLayersOf(layers);
  const raw: Record<string, unknown>[] = Array.isArray(layers)
    ? (layers as Record<string, unknown>[])
    : [];
  // **Edited against the raw list, drawn against the parsed one.** A layer
  // missing its set or its date property is dropped by `layersOf` - correctly,
  // for the canvas - and editing through that list would make such a layer
  // impossible to finish: the row would vanish the moment it was added.
  const write = (next: unknown[]) =>
    setProp((p: { layers: unknown[] }) => (p.layers = next));
  const edit = (index: number, patch: Record<string, unknown>) =>
    write(raw.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)));

  return (
    <WidgetSetup
      inputs={<>
      <div className="field">
        <span className="field-label">Layers</span>
        <div className="canvas-layer-editor" data-testid="timeline-layers">
          {raw.map((entry, index) => (
            <div className="canvas-layer-row" key={index}>
              <input
                type="text"
                value={String(entry.label ?? "")}
                placeholder={`Layer ${index + 1}`}
                data-testid={`timeline-label-${index}`}
                onChange={(e) => edit(index, { label: e.target.value })}
              />
              <select
                value={String(entry.objectSetVariable ?? "")}
                data-testid={`timeline-set-${index}`}
                onChange={(e) => edit(index, { objectSetVariable: e.target.value })}
              >
                <option value="">Pick an object set…</option>
                {sets.map((v) => (
                  <option key={v.id} value={v.id}>{v.label}</option>
                ))}
              </select>
              <input
                type="text"
                value={String(entry.dateProperty ?? "")}
                placeholder="Date property"
                data-testid={`timeline-date-${index}`}
                onChange={(e) => edit(index, { dateProperty: e.target.value })}
              />
              <select
                value={timelineTitleModeOf(entry.titleMode)}
                data-testid={`timeline-title-mode-${index}`}
                onChange={(e) => edit(index, { titleMode: e.target.value })}
              >
                {Object.entries(TIMELINE_TITLE_MODES).map(([key, name]) => (
                  <option key={key} value={key}>{name}</option>
                ))}
              </select>
              {timelineTitleModeOf(entry.titleMode) !== "object" && (
                <input
                  type="text"
                  value={String(entry.titleValue ?? "")}
                  placeholder={
                    timelineTitleModeOf(entry.titleMode) === "custom"
                      ? "Title text" : "Property api name"
                  }
                  data-testid={`timeline-title-value-${index}`}
                  onChange={(e) => edit(index, { titleValue: e.target.value })}
                />
              )}
              <select
                value={timelinePropertyModeOf(entry.propertyMode)}
                data-testid={`timeline-props-mode-${index}`}
                onChange={(e) => edit(index, { propertyMode: e.target.value })}
              >
                {Object.entries(TIMELINE_PROPERTY_MODES).map(([key, name]) => (
                  <option key={key} value={key}>{name}</option>
                ))}
              </select>
              {timelinePropertyModeOf(entry.propertyMode) === "specific" && (
                <input
                  type="text"
                  value={String(entry.properties ?? "")}
                  placeholder="api names, comma separated"
                  data-testid={`timeline-props-${index}`}
                  onChange={(e) => edit(index, { properties: e.target.value })}
                />
              )}
              <select
                value={timelineColourModeOf(entry.colourMode)}
                data-testid={`timeline-colour-mode-${index}`}
                onChange={(e) => edit(index, { colourMode: e.target.value })}
              >
                {Object.entries(TIMELINE_COLOUR_MODES).map(([key, name]) => (
                  <option key={key} value={key}>{name}</option>
                ))}
              </select>
              {timelineColourModeOf(entry.colourMode) === "static" && (
                <input
                  type="text"
                  value={String(entry.colour ?? "")}
                  placeholder="#14646e"
                  data-testid={`timeline-colour-${index}`}
                  onChange={(e) => edit(index, { colour: e.target.value })}
                />
              )}
              <select
                value={timelineIconModeOf(entry.iconMode)}
                data-testid={`timeline-icon-mode-${index}`}
                onChange={(e) => edit(index, { iconMode: e.target.value })}
              >
                {Object.entries(TIMELINE_ICON_MODES).map(([key, name]) => (
                  <option key={key} value={key}>{name}</option>
                ))}
              </select>
              {timelineIconModeOf(entry.iconMode) === "custom" && (
                // p.349's Custom: "manually override and set the icon" (§707).
                <IconChoice
                  value={String(entry.icon ?? "")}
                  testId={`timeline-icon-${index}`}
                  onChange={(next) => edit(index, { icon: next })}
                />
              )}
              {/* p.349's Selection event override (§616). Switching it on
                  gives the layer an id if it has none, in the same act, so
                  there is never an overriding layer an event cannot name. */}
              <label className="field-check">
                <input
                  type="checkbox"
                  data-testid={`timeline-override-${index}`}
                  checked={entry.overrideSelection === true}
                  onChange={(e) => edit(index, {
                    overrideSelection: e.target.checked,
                    ...(e.target.checked && !entry.id ? { id: newLayerId(raw) } : {}),
                  })}
                />
                <span>Override selection event</span>
              </label>
              <button
                type="button"
                className="btn quiet"
                data-testid={`timeline-remove-${index}`}
                onClick={() => write(raw.filter((_, i) => i !== index))}
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn quiet"
            data-testid="timeline-add"
            onClick={() => write([...raw, { label: "", objectSetVariable: "", dateProperty: "" }])}
          >
            Add layer
          </button>
        </div>
        <span className="field-hint">
          {drawn.length} of {raw.length} layer{raw.length === 1 ? "" : "s"} will draw —
          a layer needs both an object set and a date property
        </span>
      </div>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Orientation</span>
        <select
          value={timelineOrientationOf(orientation)}
          data-testid="timeline-orientation"
          onChange={(e) => setProp((p: { orientation: string }) => (p.orientation = e.target.value))}
        >
          {Object.entries(TIMELINE_ORIENTATIONS).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Events order</span>
        <select
          value={timelineOrderOf(order)}
          data-testid="timeline-order"
          onChange={(e) => setProp((p: { order: string }) => (p.order = e.target.value))}
        >
          {Object.entries(TIMELINE_ORDERS).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={showLegend !== false}
          data-testid="timeline-show-legend"
          onChange={(e) => setProp((p: { showLegend: boolean }) => (p.showLegend = e.target.checked))}
        />
        <span className="field-label">Show legend</span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={showGaps === true}
          data-testid="timeline-show-gaps"
          onChange={(e) => setProp((p: { showGaps: boolean }) => (p.showGaps = e.target.checked))}
        />
        <span className="field-label">Show time between events</span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={highlightSelection !== false}
          data-testid="timeline-highlight"
          onChange={(e) =>
            setProp((p: { highlightSelection: boolean }) => (p.highlightSelection = e.target.checked))}
        />
        <span className="field-label">Highlight the selected event</span>
      </label>
      </>}
      outputs={
        <label className="field">
          <span className="field-label">Active object</span>
          <select
            value={activeVariable ?? ""}
            data-testid="timeline-active"
            onChange={(e) =>
              setProp((p: { activeVariable: string | null }) =>
                (p.activeVariable = e.target.value || null))}
          >
            <option value="">Nothing</option>
            {arrays.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
          <span className="field-hint">
            p.349&apos;s Active object: the selected event&apos;s key, as filter clauses a
            narrowed set can read
          </span>
        </label>
      }
    />
  );
}

export function MediaPreviewSettings() {
  const {
    source, url, textVariable, subjectVariable, property, label, maxHeight,
    actions: { setProp },
  } = useNode((node) => ({
    source: node.data.props.source,
    url: node.data.props.url,
    textVariable: node.data.props.textVariable,
    subjectVariable: node.data.props.subjectVariable,
    property: node.data.props.property,
    label: node.data.props.label,
    maxHeight: node.data.props.maxHeight,
  }));
  const { declared } = useCanvasVariables();
  const strings = Object.values(declared).filter((v) => v.kind === "string");
  const objects = Object.values(declared).filter((v) => v.kind === "single_object");
  const chosen = mediaSourceOf(source);

  return (
    <WidgetSetup
      inputs={<>
      <label className="field">
        <span className="field-label">Media source</span>
        <select
          value={chosen}
          data-testid="media-source"
          onChange={(e) => setProp((p: { source: string }) => (p.source = e.target.value))}
        >
          {Object.entries(MEDIA_SOURCES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      {chosen === "string" ? (
        <>
          <label className="field">
            <span className="field-label">Media string</span>
            <input
              type="text"
              value={url ?? ""}
              placeholder="https://… or data:image/png;base64,…"
              disabled={!!textVariable}
              data-testid="media-url"
              onChange={(e) => setProp((p: { url: string }) => (p.url = e.target.value))}
            />
            <span className="field-hint">
              A URL or a data URL. p.363&apos;s Blobster RIDs and media-set URLs need a
              Foundry service to resolve them, so this platform will not follow one
            </span>
          </label>
          <label className="field">
            <span className="field-label">…or from a variable</span>
            <select
              value={textVariable ?? ""}
              data-testid="media-variable"
              onChange={(e) =>
                setProp((p: { textVariable: string | null }) =>
                  (p.textVariable = e.target.value || null))}
            >
              <option value="">Use the string above</option>
              {strings.map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
          </label>
        </>
      ) : (
        <>
          <label className="field">
            <span className="field-label">Object</span>
            <select
              value={subjectVariable ?? ""}
              data-testid="media-subject"
              onChange={(e) =>
                setProp((p: { subjectVariable: string | null }) =>
                  (p.subjectVariable = e.target.value || null))}
            >
              <option value="">Pick an object variable…</option>
              {objects.map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
            <span className="field-hint">
              p.363&apos;s &ldquo;object set with a single object&rdquo;, which is a single-object
              variable here
            </span>
          </label>
          <label className="field">
            <span className="field-label">Attachment property</span>
            <input
              type="text"
              value={property ?? ""}
              placeholder="api name"
              data-testid="media-property"
              onChange={(e) => setProp((p: { property: string }) => (p.property = e.target.value))}
            />
          </label>
        </>
      )}
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Caption</span>
        <input
          type="text"
          value={label ?? ""}
          data-testid="media-label"
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
        <span className="field-hint">
          Also the accessible name. Without one the filename is used, because a
          preview with no name is invisible to a screen reader
        </span>
      </label>
      <label className="field">
        <span className="field-label">Maximum height</span>
        <input
          type="number"
          min={80}
          max={1200}
          value={Number(maxHeight) || 320}
          data-testid="media-height"
          onChange={(e) =>
            setProp((p: { maxHeight: number }) => (p.maxHeight = Number(e.target.value)))}
        />
      </label>
      </>}
    />
  );
}

export function IframeSettings() {
  const {
    url, textVariable, title, height, frameMode, frameDefinition, frameBindings,
    actions: { setProp },
  } = useNode((node) => ({
    url: node.data.props.url,
    textVariable: node.data.props.textVariable,
    title: node.data.props.title,
    height: node.data.props.height,
    frameMode: node.data.props.frameMode,
    frameDefinition: node.data.props.frameDefinition,
    frameBindings: node.data.props.frameBindings,
  }));
  const { declared } = useCanvasVariables();
  const strings = Object.values(declared).filter((v) => v.kind === "string");
  const definition = savedDefinition(frameDefinition);
  const bindings: Record<string, string> =
    frameBindings && typeof frameBindings === "object" ? frameBindings : {};
  // p.547's one-click conversion, offered only while it would change something.
  const embed = textVariable ? null : youtubeEmbedUrl(url);

  return (
    <WidgetSetup
      inputs={<>
      <label className="field">
        <span className="field-label">URL</span>
        <input
          type="text"
          value={url ?? ""}
          placeholder="https://… or a path on this platform"
          disabled={!!textVariable}
          data-testid="iframe-url"
          onChange={(e) => setProp((p: { url: string }) => (p.url = e.target.value))}
        />
        <span className="field-hint">
          To frame one of this platform&apos;s own pages without its top bar, add
          <code> ?embedded=true</code> (p.547)
        </span>
      </label>
      {embed && (
        <button
          type="button"
          className="btn quiet"
          data-testid="iframe-youtube"
          onClick={() => setProp((p: { url: string }) => (p.url = embed))}
        >
          Convert to YouTube&apos;s embed URL
        </button>
      )}
      <label className="field">
        <span className="field-label">…or from a variable</span>
        <select
          value={textVariable ?? ""}
          data-testid="iframe-variable"
          onChange={(e) =>
            setProp((p: { textVariable: string | null }) =>
              (p.textVariable = e.target.value || null))}
        >
          <option value="">Use the URL above</option>
          {strings.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
      </label>
      {/* p.552-553's Bidirectional option (§756; decision 0023). */}
      <label className="field">
        <span className="field-label">Mode</span>
        <select
          value={frameMode === "bidirectional" ? "bidirectional" : "url"}
          data-testid="iframe-mode"
          onChange={(e) =>
            setProp((p: { frameMode: string }) => (p.frameMode = e.target.value))}
        >
          <option value="url">URL - show the page</option>
          <option value="bidirectional">Bidirectional - the page reads and writes variables</option>
        </select>
      </label>
      {frameMode === "bidirectional" && !definition && (
        // p.553: "a loading state while waiting to receive the definition of
        // variables and events required by the embedded application".
        <p className="field-hint" data-testid="iframe-waiting">
          Waiting for the application to say which variables and events it needs. It sends
          an <code>anchor-widget//definition</code> message once it loads.
        </p>
      )}
      {frameMode === "bidirectional" && definition && (
        <div data-testid="iframe-fields">
          {definition.fields.length === 0 && (
            <p className="field-hint">The application asks for no variables.</p>
          )}
          {definition.fields.map((field) => {
            const options = bindable(field, Object.values(declared));
            return (
              <label className="field" key={field.id}>
                <span className="field-label">
                  {field.label} ({field.type}
                  {field.access === "read" ? ", read only" : field.access === "write" ? ", written only" : ""})
                </span>
                <select
                  value={bindings[field.id] ?? ""}
                  data-testid={`iframe-bind-${field.id}`}
                  onChange={(e) =>
                    setProp((p: { frameBindings: Record<string, string> }) => {
                      const next = { ...(p.frameBindings ?? {}) };
                      if (e.target.value) next[field.id] = e.target.value;
                      else delete next[field.id];
                      p.frameBindings = next;
                    })}
                >
                  <option value="">Not bound</option>
                  {options.map((v) => (
                    <option key={v.id} value={v.id}>{v.label}</option>
                  ))}
                </select>
                {options.length === 0 && (
                  <span className="field-hint">
                    Declare a {field.type} variable in the Variables panel first
                  </span>
                )}
              </label>
            );
          })}
          {definition.events.length > 0 && (
            <p className="field-hint" data-testid="iframe-events">
              It can fire {definition.events.map((e) => e.label).join(", ")}. Wire each in the
              Events panel, as this widget&apos;s items.
            </p>
          )}
        </div>
      )}
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          type="text"
          value={title ?? ""}
          data-testid="iframe-title"
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
        <span className="field-hint">
          What a screen reader calls the frame. Without one it is named after the
          site it shows
        </span>
      </label>
      <label className="field">
        <span className="field-label">Height</span>
        <input
          type="number"
          min={120}
          max={2000}
          value={Number(height) || 480}
          data-testid="iframe-height"
          onChange={(e) =>
            setProp((p: { height: number }) => (p.height = Number(e.target.value)))}
        />
        <span className="field-hint">
          p.545 advises against more than one iframe on screen at once: each is a
          whole page, with the memory of one
        </span>
      </label>
      </>}
    />
  );
}

export function ObjectDropdownSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, selectedVariable, label, properties, hideNull,
    sortProperty, searchMode, searchPropertyNames, allowNoSelection,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    selectedVariable: node.data.props.selectedVariable,
    label: node.data.props.label,
    properties: node.data.props.properties,
    hideNull: node.data.props.hideNull,
    sortProperty: node.data.props.sortProperty,
    searchMode: node.data.props.searchMode,
    searchPropertyNames: node.data.props.searchPropertyNames,
    allowNoSelection: node.data.props.allowNoSelection,
  }));
  const { declared, resolved } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const bound = objectSetVariable ? resolved[objectSetVariable] : undefined;
  // A union's properties are p.450's common and single ones, and it sorts by
  // the common alone (p.458, §688).
  const { properties: offered, union } = useSetProperties(workspaceId, bound);
  const names = offered.map((p) => p.api_name).join(", ");

  return (
    <WidgetSetup
      bindings={{ objectSetVariable, selectedVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set", selectedVariable: "where to put the selection" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Input object set</span>
        <select
          value={objectSetVariable || ""}
          data-testid="dropdown-variable"
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
      <label className="field">
        <span className="field-label">Selected object</span>
        <select
          value={selectedVariable || ""}
          data-testid="dropdown-selected-variable"
          onChange={(e) =>
            setProp((p: { selectedVariable: string | null }) =>
              (p.selectedVariable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          An object set of the one selected object, which is what p.457 says it holds
        </span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={allowNoSelectionOf(allowNoSelection)}
          data-testid="dropdown-allow-none"
          onChange={(e) =>
            setProp((p: { allowNoSelection: boolean }) =>
              (p.allowNoSelection = e.target.checked))}
        />
        <span className="field-label">Allow no selection</span>
        <span className="field-hint">
          Off means the first object is selected on load, so downstream widgets have one
        </span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          type="text"
          value={label ?? ""}
          placeholder="none"
          data-testid="dropdown-label-input"
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Properties</span>
        <input
          type="text"
          value={properties ?? ""}
          placeholder="the title only"
          data-testid="dropdown-properties"
          onChange={(e) =>
            setProp((p: { properties: string }) => (p.properties = e.target.value))}
        />
        <span className="field-hint">
          {names ? `Shown beneath each title. Available: ${names}` : "Shown beneath each title"}
        </span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={hideNullOf(hideNull)}
          data-testid="dropdown-hide-null"
          onChange={(e) => setProp((p: { hideNull: boolean }) => (p.hideNull = e.target.checked))}
        />
        <span className="field-label">Hide null properties</span>
      </label>
      <PropertySortField
        label="Sort items by"
        testId="dropdown-sort"
        value={sortProperty}
        properties={union ? union.common : offered}
        onChange={(sort) =>
          setProp((p: { sortProperty: string }) => (p.sortProperty = sort))}
      />
      <label className="field">
        <span className="field-label">Search items by</span>
        <select
          value={searchModeOf(searchMode)}
          data-testid="dropdown-search-mode"
          onChange={(e) =>
            setProp((p: { searchMode: string }) => (p.searchMode = e.target.value))}
        >
          {Object.entries(SEARCH_MODES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      {searchModeOf(searchMode) === "specific" && (
        <label className="field">
          <span className="field-label">Search properties</span>
          <input
            type="text"
            value={searchPropertyNames ?? ""}
            data-testid="dropdown-search-properties"
            onChange={(e) =>
              setProp((p: { searchPropertyNames: string }) =>
                (p.searchPropertyNames = e.target.value))}
          />
          <span className="field-hint">String properties only, which is what p.458 says</span>
        </label>
      )}
      </>}
    />
  );
}

export function ObjectSelectorSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, selectedVariable, label, properties, hideNull,
    sortProperty, searchMode, searchPropertyNames,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    selectedVariable: node.data.props.selectedVariable,
    label: node.data.props.label,
    properties: node.data.props.properties,
    hideNull: node.data.props.hideNull,
    sortProperty: node.data.props.sortProperty,
    searchMode: node.data.props.searchMode,
    searchPropertyNames: node.data.props.searchPropertyNames,
  }));
  const { declared, resolved } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const bound = objectSetVariable ? resolved[objectSetVariable] : undefined;
  // As the Object Dropdown's panel (§688): a union sorts by its common
  // properties (p.458).
  const { properties: offered, union } = useSetProperties(workspaceId, bound);
  const names = offered.map((p) => p.api_name).join(", ");

  return (
    <WidgetSetup
      bindings={{ objectSetVariable, selectedVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set", selectedVariable: "where to put the selection" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Input object set</span>
        <select
          value={objectSetVariable || ""}
          data-testid="selector-variable"
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
      <label className="field">
        <span className="field-label">Selected objects</span>
        <select
          value={selectedVariable || ""}
          data-testid="selector-selected-variable"
          onChange={(e) =>
            setProp((p: { selectedVariable: string | null }) =>
              (p.selectedVariable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          An object set of everything ticked. Nothing ticked is the empty set, not the whole one
        </span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Label</span>
        <input
          type="text"
          value={label ?? ""}
          placeholder="none"
          data-testid="selector-label-input"
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Properties</span>
        <input
          type="text"
          value={properties ?? ""}
          placeholder="the title only"
          data-testid="selector-properties"
          onChange={(e) =>
            setProp((p: { properties: string }) => (p.properties = e.target.value))}
        />
        <span className="field-hint">
          {names ? `Shown beneath each title. Available: ${names}` : "Shown beneath each title"}
        </span>
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={hideNullOf(hideNull)}
          data-testid="selector-hide-null"
          onChange={(e) => setProp((p: { hideNull: boolean }) => (p.hideNull = e.target.checked))}
        />
        <span className="field-label">Hide null properties</span>
      </label>
      <PropertySortField
        label="Sort items by"
        testId="selector-sort"
        value={sortProperty}
        properties={union ? union.common : offered}
        onChange={(sort) =>
          setProp((p: { sortProperty: string }) => (p.sortProperty = sort))}
      />
      <label className="field">
        <span className="field-label">Search items by</span>
        <select
          value={searchModeOf(searchMode)}
          data-testid="selector-search-mode"
          onChange={(e) =>
            setProp((p: { searchMode: string }) => (p.searchMode = e.target.value))}
        >
          {Object.entries(SEARCH_MODES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      {searchModeOf(searchMode) === "specific" && (
        <label className="field">
          <span className="field-label">Search properties</span>
          <input
            type="text"
            value={searchPropertyNames ?? ""}
            data-testid="selector-search-properties"
            onChange={(e) =>
              setProp((p: { searchPropertyNames: string }) =>
                (p.searchPropertyNames = e.target.value))}
          />
        </label>
      )}
      </>}
    />
  );
}

export function SearchSettings() {
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
    (v) => holdsClauses(v) && !v.derivation,
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

export function ObjectCardsSettings() {
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
        <UnsupportedNote properties={type.data?.properties ?? []} testId="cards-unsupported" />
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

export function PivotTableSettings() {
  const {
    fn, fnRows, fnExpand, fnColumn, fnValues, title, actions: { setProp },
  } = useNode((node) => ({
    fn: node.data.props.fn, fnRows: node.data.props.fnRows, fnExpand: node.data.props.fnExpand,
    fnColumn: node.data.props.fnColumn, fnValues: node.data.props.fnValues,
    title: node.data.props.title,
  }));
  const layer = functionLayerOf(fn);
  // p.335: the data is an object set's, or a function's.
  const source = (
    <label className="field">
      <span className="field-label">Data from</span>
      <select
        aria-label="Pivot data from"
        value={layer ? "function" : "set"}
        onChange={(e) => setProp((p: Record<string, unknown>) => {
          p.fn = e.target.value === "function"
            ? { function_id: "", version: null, inputs: {} } : null;
        })}
      >
        <option value="set">An object set</option>
        <option value="function">A function</option>
      </select>
    </label>
  );
  if (!layer) return <ObjectSetPivotSettings source={source} />;
  return (
    <WidgetSetup
      inputs={<>
        {source}
        <FunctionPivotSettings
          fn={layer}
          rows={fnRows ?? ""}
          expand={fnExpand ?? ""}
          column={fnColumn ?? ""}
          values={fnValues ?? ""}
          onChange={(next) => setProp((p: Record<string, unknown>) => {
            for (const [k, v] of Object.entries(next)) p[k] = v;
          })}
        />
      </>}
      configuration={
        <label className="field">
          <span className="field-label">Title</span>
          <input
            type="text"
            value={title || ""}
            onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
          />
        </label>
      }
    />
  );
}

function ObjectSetPivotSettings({ source }: { source: React.ReactNode }) {
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
    (v) => holdsClauses(v) && !v.derivation,
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
      {source}
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
          {/* Each axis is a group, so p.250's Selectable (§727). */}
          {properties.filter((prop) => isSelectable(prop) || prop.api_name === rowProperty)
            .map((prop) => (
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
          {properties.filter((prop) => prop.api_name !== rowProperty
            && (isSelectable(prop) || prop.api_name === columnProperty)).map((prop) => (
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
 * A date *property* is the other question, and as of §220 it is **unbuilt
 * rather than blocked**. This said bucketing one "means guessing whether
 * '03/04' is March or April, and the two stores would guess differently" —
 * decision 0006's reason, and §220 removed it: a `date` property is mapped
 * `date` in the index and stored typed, so both stores read the same instant.
 * What is missing is a date histogram on `/object-sets/group`, which today
 * buckets by term. §222's Timeline already orders by a declared date property,
 * so the ontology half is proven.
 *
 * **No drill-down, deliberately, and this reason did not expire.** Every
 * narrowing widget writes property equality clauses; a time bucket is a *range*
 * over a system field. §221 built the ordered operators, so a range clause is
 * now expressible — over a *property*. `updated_at` is not one; it is a column
 * the set language has no name for, which is a different gap and the same
 * answer. Inventing a second narrowing mechanism for one widget would be two
 * answers to one question — the same reason the scatter chart takes no drill.
 *
 * The line itself is the existing `Chart`, not a second renderer: gaps are
 * already filled by the server, so a plain line over the points is correct.
 */
const SERIES_INTERVALS = ["day", "week", "month"] as const;

export function TimeSeriesSettings() {
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
            explaining or it reads as an oversight. **The explanation changed in
            §231**: it used to name decision 0006, which §220 closed. */}
        <span className="field-hint">
          Plots when each object last changed. Bucketing by a date property needs
          a date histogram on the grouping endpoint, which buckets by term — not
          built yet.
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

/** One of p.320's object types on the Markdown widget: its api name and its
 * Highlight color - static, from a property's Ontology formatting, or the
 * builder's own rules (§664). The type is read by its api name so its
 * properties can be offered. */
/** p.322's Highlight color for an annotation layer (§669): static, or §158's
 * rules over the layer's objects' properties. The properties are the layer's
 * set's type's, where the document can say which type that is. */
function AnnotationLayerRules({ index, layer, onChange }: {
  index: number;
  layer: ReturnType<typeof annotationLayersOf>[number];
  onChange: (patch: Partial<ReturnType<typeof annotationLayersOf>[number]>) => void;
}) {
  const { workspaceId } = useCanvasEnv();
  const { declared } = useCanvasVariables();
  const [editing, setEditing] = useState(false);
  const typeId = layer.objectSetVariable ? staticTypeOf(layer.objectSetVariable, declared) : null;
  const detail = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: layer.colorMode === "rules" && !!typeId,
  });
  const properties = detail.data?.properties ?? [];
  const n = index + 1;
  return (
    <>
      <select aria-label={`Layer ${n} colour from`} value={layer.colorMode}
              onChange={(e) => onChange({ colorMode: e.target.value as AnnotationColorMode })}>
        {Object.entries(ANNOTATION_COLOR_MODES).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
      </select>
      {layer.colorMode === "rules" && (
        <button type="button" className="btn quiet" disabled={properties.length === 0}
                data-testid="markdown-annotation-rules" onClick={() => setEditing(true)}>
          {layer.colorRules?.length
            ? `Edit ${layer.colorRules.length} rule${layer.colorRules.length === 1 ? "" : "s"}` : "Add rules"}
        </button>
      )}
      {editing && (
        <ConditionalFormatEditor open onClose={() => setEditing(false)}
          propertyName={properties[0]?.api_name ?? "value"} properties={properties} value={layer.colorRules}
          onSave={(next) => { onChange({ colorRules: next }); setEditing(false); }} />
      )}
    </>
  );
}

function MarkdownReferenceTypeRow({ index, type, newId, onChange, onRemove }: {
  index: number;
  /** The id the type takes if its override goes on without one (§665). */
  newId: string;
  type: ReturnType<typeof referenceTypesOf>[number];
  onChange: (next: ReturnType<typeof referenceTypesOf>[number]) => void;
  onRemove: () => void;
}) {
  const { workspaceId } = useCanvasEnv();
  const [editing, setEditing] = useState(false);
  const typeId = useQuery({
    queryKey: ["markdown-ref-type-id", workspaceId, type.objectType],
    queryFn: async () => (await objApi.listTypes(workspaceId, null, { q: type.objectType, limit: 50 }))
      .items.find((t) => t.api_name === type.objectType)?.id ?? null,
    enabled: type.colorMode !== "static" && !!type.objectType,
  });
  const detail = useQuery({
    queryKey: ["object-type", typeId.data ?? null],
    queryFn: () => objApi.getType(workspaceId, typeId.data!),
    enabled: !!typeId.data,
  });
  const properties = detail.data?.properties ?? [];
  const n = index + 1;
  return (
    <div className="field" data-testid="markdown-ref-type">
      <div className="field-inline">
        <input type="text" aria-label={`Object type ${n}`} data-testid="markdown-ref-type-name"
               value={type.objectType} onChange={(e) => onChange({ ...type, objectType: e.target.value })} />
        <input type="color" aria-label={`Object type ${n} highlight colour`} data-testid="markdown-ref-type-color"
               value={type.color ?? "#2563eb"} onChange={(e) => onChange({ ...type, color: e.target.value })} />
        <button type="button" className="btn quiet" aria-label={`Remove object type ${n}`} onClick={onRemove}>
          ×
        </button>
      </div>
      <div className="field-inline">
        <select aria-label={`Object type ${n} colour from`} value={type.colorMode}
                onChange={(e) => onChange({ ...type, colorMode: e.target.value as ReferenceColorMode })}>
          {Object.entries(REFERENCE_COLOR_MODES).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        {type.colorMode === "property" && (
          <select aria-label={`Object type ${n} colour property`} value={type.colorProperty ?? ""}
                  onChange={(e) => onChange({ ...type, colorProperty: e.target.value || null })}>
            <option value="">Property…</option>
            {properties.map((p) => (
              <option key={p.api_name} value={p.api_name}>
                {p.conditional_format?.length ? p.display_name : `${p.display_name} (no formatting)`}
              </option>
            ))}
          </select>
        )}
        {type.colorMode === "rules" && (
          <button type="button" className="btn quiet" disabled={properties.length === 0}
                  onClick={() => setEditing(true)}>
            {type.colorRules?.length ? `Edit ${type.colorRules.length} rule${type.colorRules.length === 1 ? "" : "s"}` : "Add rules"}
          </button>
        )}
      </div>
      {/* p.320's Override event on selection (§665): its own events in the
          Events panel, instead of the widget's. */}
      <label className="field canvas-toggle">
        <input type="checkbox" aria-label={`Object type ${n} override event on selection`}
               checked={type.overrideSelection}
               onChange={(e) => onChange({ ...type, overrideSelection: e.target.checked,
                 id: type.id ?? (e.target.checked ? newId : null) })} />
        <span className="field-label">Its own event on selection</span>
      </label>
      {type.colorMode !== "static" && typeId.data === null && (
        <span className="field-hint">{`No object type is called ${type.objectType}.`}</span>
      )}
      {type.colorMode !== "static" && (
        <span className="field-hint">The colour above is used where nothing else paints the reference</span>
      )}
      {editing && (
        <ConditionalFormatEditor open onClose={() => setEditing(false)}
          propertyName={properties[0]?.api_name ?? "value"} properties={properties} value={type.colorRules}
          onSave={(next) => { onChange({ ...type, colorRules: next }); setEditing(false); }} />
      )}
    </div>
  );
}

export function SeriesAnalysisSettings() {
  const { workspaceId } = useCanvasEnv();
  const { declared } = useCanvasVariables();
  const {
    objectSetVariable, property, labelProperty, limit, title, plotTypes, eventSetTypes, newPlotCanvas,
    eventSets, viewRange, windowStartVariable, windowEndVariable, relativeAmount, relativeUnit, syncXAxes, utc,
    overlayYAxes, collapseYAxes, collapsedBoundaries, tooltip, addData, addDataSets, saving,
    saveProjectVariable, fixedSaveLocation, outputVariable, autoloadVariable, keepOnLoad,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    property: node.data.props.property,
    labelProperty: node.data.props.labelProperty,
    limit: node.data.props.limit,
    title: node.data.props.title,
    plotTypes: node.data.props.plotTypes,
    eventSetTypes: node.data.props.eventSetTypes,
    newPlotCanvas: node.data.props.newPlotCanvas,
    eventSets: node.data.props.eventSets,
    viewRange: node.data.props.viewRange,
    windowStartVariable: node.data.props.windowStartVariable,
    windowEndVariable: node.data.props.windowEndVariable,
    relativeAmount: node.data.props.relativeAmount,
    relativeUnit: node.data.props.relativeUnit,
    syncXAxes: node.data.props.syncXAxes,
    utc: node.data.props.utc,
    overlayYAxes: node.data.props.overlayYAxes,
    collapseYAxes: node.data.props.collapseYAxes,
    collapsedBoundaries: node.data.props.collapsedBoundaries,
    tooltip: node.data.props.tooltip,
    addData: node.data.props.addData,
    addDataSets: node.data.props.addDataSets,
    saving: node.data.props.saving,
    saveProjectVariable: node.data.props.saveProjectVariable,
    fixedSaveLocation: node.data.props.fixedSaveLocation,
    outputVariable: node.data.props.outputVariable,
    autoloadVariable: node.data.props.autoloadVariable,
    keepOnLoad: node.data.props.keepOnLoad,
  }));
  const ridHolders = Object.values(declared).filter((v) => v.kind === "string" || v.kind === "array");
  const strings = Object.values(declared).filter((v) => v.kind === "string");
  const rawDataSets: Record<string, unknown>[] = Array.isArray(addDataSets) ? addDataSets : [];
  const tips = seriesTooltipOptionsOf(tooltip);
  const setTip = (key: string, value: unknown) => setProp((p: { tooltip: unknown }) => {
    p.tooltip = { ...seriesTooltipOptionsOf(p.tooltip), [key]: value };
  });
  const moments = Object.values(declared).filter((v) => v.kind === "timestamp" || v.kind === "date");
  const setTypes = SERIES_EVENT_SET_TYPES.filter((k) => !eventSetTypes || eventSetTypes.includes(k));
  const initial = seriesInitialEventSetsOf(eventSets);
  const rawInitial: Record<string, unknown>[] = Array.isArray(eventSets) ? eventSets : [];
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  const typeId = (declared[objectSetVariable ?? ""]?.object_set as { object_type_id?: string } | undefined)
    ?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const properties = type.data?.properties ?? [];
  const offered = SERIES_PLOT_TYPES.filter((k) => !plotTypes || plotTypes.includes(k));
  return (
    <WidgetSetup
      bindings={{ objectSetVariable }}
      requires={["objectSetVariable"]}
      labels={{ objectSetVariable: "an object set" }}
      inputs={<>
      <label className="field">
        <span className="field-label">Object set</span>
        <select aria-label="Series object set" value={objectSetVariable || ""}
                onChange={(e) => setProp((p: { objectSetVariable: string | null }) =>
                  (p.objectSetVariable = e.target.value || null))}>
          <option value="">Choose…</option>
          {setVariables.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Time series property</span>
        <select aria-label="Series property" value={property || ""} disabled={!typeId}
                onChange={(e) => setProp((p: { property: string | null }) =>
                  (p.property = e.target.value || null))}>
          <option value="">Choose…</option>
          {properties.filter((p) => p.data_type === "time_series")
            .map((p) => <option key={p.api_name} value={p.api_name}>{p.api_name}</option>)}
        </select>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Plot label</span>
        <select aria-label="Series label property" value={labelProperty || ""} disabled={!typeId}
                onChange={(e) => setProp((p: { labelProperty: string | null }) =>
                  (p.labelProperty = e.target.value || null))}>
          <option value="">Primary key</option>
          {properties.map((p) => <option key={p.api_name} value={p.api_name}>{p.api_name}</option>)}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Objects plotted</span>
        <input type="number" aria-label="Series objects plotted" min={1} max={MAX_SERIES_ROOTS}
               value={Number(limit) || 5}
               onChange={(e) => setProp((p: { limit: number }) =>
                 (p.limit = Math.max(1, Math.min(MAX_SERIES_ROOTS, Number(e.target.value) || 1))))} />
        <span className="field-hint">The first {MAX_SERIES_ROOTS} at most, one plot each</span>
      </label>
      <div className="field" data-testid="series-plot-types">
        <span className="field-label">Plot types offered</span>
        {SERIES_PLOT_TYPES.map((k) => (
          <label key={k} className="field canvas-toggle">
            <input type="checkbox" data-testid={`series-plot-type-${k}`} checked={offered.includes(k)}
                   onChange={(e) => setProp((p: { plotTypes: string[] | null }) => {
                     const now = SERIES_PLOT_TYPES.filter((t) => !p.plotTypes || p.plotTypes.includes(t));
                     p.plotTypes = SERIES_PLOT_TYPES.filter((t) => (t === k ? e.target.checked : now.includes(t)));
                   })} />
            <span className="field-label">{SERIES_PLOT_LABELS[k]}</span>
          </label>
        ))}
      </div>
      <div className="field" data-testid="series-add-data-options">
        <label className="field canvas-toggle">
          <input type="checkbox" aria-label="Enable add data" checked={!!addData}
                 onChange={(e) => setProp((p: { addData: boolean }) => (p.addData = e.target.checked))} />
          <span className="field-label">Let readers add series from the Ontology</span>
        </label>
        {!!addData && rawDataSets.map((raw, n) => (
          <span key={n} className="row-actions" style={{ gap: 4 }}>
            <select aria-label={`Add data set ${n + 1}`}
                    value={typeof raw.objectSetVariable === "string" ? raw.objectSetVariable : ""}
                    onChange={(e) => setProp((p: { addDataSets: unknown }) => {
                      const all = Array.isArray(p.addDataSets) ? [...p.addDataSets] : [];
                      all[n] = { objectSetVariable: e.target.value };
                      p.addDataSets = all;
                    })}>
              <option value="">Object set…</option>
              {setVariables.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
            </select>
            <button type="button" className="btn quiet" aria-label={`Remove add data set ${n + 1}`}
                    onClick={() => setProp((p: { addDataSets: unknown }) => {
                      const all = Array.isArray(p.addDataSets) ? [...p.addDataSets] : [];
                      all.splice(n, 1);
                      p.addDataSets = all;
                    })}>×</button>
          </span>
        ))}
        {!!addData && rawDataSets.length < MAX_SERIES_ADD_DATA_SETS && (
          <button type="button" className="btn quiet"
                  onClick={() => setProp((p: { addDataSets: unknown }) => {
                    p.addDataSets = [...(Array.isArray(p.addDataSets) ? p.addDataSets : []), { objectSetVariable: "" }];
                  })}>
            Restrict to an object set
          </button>
        )}
        {!!addData && (
          <span className="field-hint">
            {rawDataSets.length ? "Readers pick from these sets' objects." : "Readers pick from any object type."}
          </span>
        )}
      </div>
      <div className="field" data-testid="series-saving-options">
        <label className="field canvas-toggle">
          <input type="checkbox" aria-label="Enable analysis saving" checked={!!saving}
                 onChange={(e) => setProp((p: { saving: boolean }) => (p.saving = e.target.checked))} />
          <span className="field-label">Let readers save and open analyses</span>
        </label>
        {!!saving && (
          <>
            <select aria-label="Default save location variable" value={saveProjectVariable || ""}
                    onChange={(e) => setProp((p: { saveProjectVariable: string | null }) =>
                      (p.saveProjectVariable = e.target.value || null))}>
              <option value="">This module's project</option>
              {strings.map((v) => <option key={v.id} value={v.id}>{`The project ${v.label} names`}</option>)}
            </select>
            <label className="field canvas-toggle">
              <input type="checkbox" aria-label="Don't allow users to choose save location"
                     checked={!!fixedSaveLocation}
                     onChange={(e) => setProp((p: { fixedSaveLocation: boolean }) =>
                       (p.fixedSaveLocation = e.target.checked))} />
              <span className="field-label">Don't allow users to choose save location</span>
            </label>
          </>
        )}
        <label className="field">
          <span className="field-label">Output analysis RID</span>
          <select aria-label="Output analysis RID variable" value={outputVariable || ""}
                  onChange={(e) => setProp((p: { outputVariable: string | null }) =>
                    (p.outputVariable = e.target.value || null))}>
            <option value="">None</option>
            {strings.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Autoload analyses</span>
          <select aria-label="Autoload analyses variable" value={autoloadVariable || ""}
                  onChange={(e) => setProp((p: { autoloadVariable: string | null }) =>
                    (p.autoloadVariable = e.target.value || null))}>
            <option value="">None</option>
            {ridHolders.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
          <span className="field-hint">A string variable naming one analysis's RID, or an array naming several</span>
        </label>
        {!!autoloadVariable && (
          <label className="field canvas-toggle">
            <input type="checkbox" aria-label="Don't clear on load" checked={!!keepOnLoad}
                   onChange={(e) => setProp((p: { keepOnLoad: boolean }) => (p.keepOnLoad = e.target.checked))} />
            <span className="field-label">Don't clear on load</span>
          </label>
        )}
      </div>
      <label className="field">
        <span className="field-label">New plot placement</span>
        <select aria-label="New plot placement" value={String(seriesPlacementOf(newPlotCanvas))}
                onChange={(e) => setProp((p: { newPlotCanvas: string | number }) =>
                  (p.newPlotCanvas = /^\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value))}>
          <option value="input">Its input plot's canvas</option>
          <option value="new">A new canvas</option>
          {Array.from({ length: MAX_SERIES_CANVASES }, (_, n) => (
            <option key={n + 1} value={n + 1}>{`Canvas ${n + 1}`}</option>
          ))}
        </select>
      </label>
      <div className="field" data-testid="series-event-set-types">
        <span className="field-label">Event set types offered</span>
        {SERIES_EVENT_SET_TYPES.map((k) => (
          <label key={k} className="field canvas-toggle">
            <input type="checkbox" aria-label={`Offer ${SERIES_EVENT_SET_TYPE_LABELS[k]}`} checked={setTypes.includes(k)}
                   onChange={(e) => setProp((p: { eventSetTypes: string[] | null }) => {
                     const now = SERIES_EVENT_SET_TYPES.filter((t) => !p.eventSetTypes || p.eventSetTypes.includes(t));
                     p.eventSetTypes = SERIES_EVENT_SET_TYPES.filter((t) => (t === k ? e.target.checked : now.includes(t)));
                   })} />
            <span className="field-label">{SERIES_EVENT_SET_TYPE_LABELS[k]}</span>
          </label>
        ))}
      </div>
      <div className="field" data-testid="series-initial-event-sets">
        <span className="field-label">Initial event sets</span>
        {rawInitial.map((raw, n) => (
          <SeriesInitialEventSetRow key={n} index={n} raw={raw} sets={setVariables}
            onChange={(next) => setProp((p: { eventSets: unknown }) => {
              const all = Array.isArray(p.eventSets) ? [...p.eventSets] : [];
              if (next === null) all.splice(n, 1); else all[n] = next;
              p.eventSets = all;
            })} />
        ))}
        {rawInitial.length < MAX_SERIES_EVENT_SETS && (
          <button type="button" className="btn quiet"
                  onClick={() => setProp((p: { eventSets: unknown }) => {
                    p.eventSets = [...(Array.isArray(p.eventSets) ? p.eventSets : []),
                      { objectSetVariable: "", start: "", end: "", label: "" }];
                  })}>
            Add initial event set
          </button>
        )}
        {rawInitial.length > initial.length && (
          <span className="field-hint">An event set needs an object set and a start property to be shown.</span>
        )}
      </div>
      <label className="field">
        <span className="field-label">Default view range</span>
        <select aria-label="Default view range" value={viewRange || "full"}
                onChange={(e) => setProp((p: { viewRange: string }) => (p.viewRange = e.target.value))}>
          {SERIES_VIEW_RANGES.map((k) => (
            <option key={k} value={k}>
              {k === "full" ? "Full data range" : k === "fixed" ? "Fixed date range" : "Relative date range"}
            </option>
          ))}
        </select>
      </label>
      {viewRange === "fixed" && (["windowStartVariable", "windowEndVariable"] as const).map((key) => (
        <label key={key} className="field">
          <span className="field-label">{key === "windowStartVariable" ? "View from" : "View to"}</span>
          <select aria-label={key === "windowStartVariable" ? "View from variable" : "View to variable"}
                  value={(key === "windowStartVariable" ? windowStartVariable : windowEndVariable) || ""}
                  onChange={(e) => setProp((p: Record<string, string | null>) => (p[key] = e.target.value || null))}>
            <option value="">Choose…</option>
            {moments.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
        </label>
      ))}
      {viewRange === "relative" && (
        <div className="row-actions" style={{ gap: 4 }}>
          <input type="number" min={1} aria-label="View range length" value={Number(relativeAmount) || ""}
                 style={{ width: 64 }}
                 onChange={(e) => setProp((p: { relativeAmount: number }) => (p.relativeAmount = Number(e.target.value)))} />
          <select aria-label="View range unit" value={relativeUnit || "week"}
                  onChange={(e) => setProp((p: { relativeUnit: string }) => (p.relativeUnit = e.target.value))}>
            {TIME_UNITS.map((u) => <option key={u} value={u}>{`${u}s`}</option>)}
          </select>
          <span className="field-hint">before the page loaded, to then</span>
        </div>
      )}
      <label className="field canvas-toggle">
        <input type="checkbox" aria-label="Sync X-axes across canvases" checked={!!syncXAxes}
               onChange={(e) => setProp((p: { syncXAxes: boolean }) => (p.syncXAxes = e.target.checked))} />
        <span className="field-label">Sync X-axes across canvases</span>
      </label>
      <label className="field canvas-toggle">
        <input type="checkbox" aria-label="Enable UTC time format" checked={!!utc}
               onChange={(e) => setProp((p: { utc: boolean }) => (p.utc = e.target.checked))} />
        <span className="field-label">Enable UTC time format</span>
      </label>
      {([["overlayYAxes", "Overlay Y-axes", overlayYAxes], ["collapseYAxes", "Collapse Y-axes by default", collapseYAxes],
        ["collapsedBoundaries", "Display Y-axes boundaries when collapsed", collapsedBoundaries]] as const)
        .map(([key, label, on]) => (
          <label key={key} className="field canvas-toggle">
            <input type="checkbox" aria-label={label} checked={!!on}
                   disabled={key === "collapsedBoundaries" && !collapseYAxes}
                   onChange={(e) => setProp((p: Record<string, boolean>) => (p[key] = e.target.checked))} />
            <span className="field-label">{label}</span>
          </label>
        ))}
      <div className="field" data-testid="series-tooltip-options">
        <span className="field-label">Tooltip</span>
        <label className="field canvas-toggle">
          <input type="checkbox" aria-label="Show tooltip" checked={tips.show}
                 onChange={(e) => setTip("show", e.target.checked)} />
          <span className="field-label">Show a tooltip</span>
        </label>
        <select aria-label="Tooltip values" value={tips.values} disabled={!tips.show}
                onChange={(e) => setTip("values", e.target.value)}>
          {SERIES_TOOLTIP_VALUES.map((v) => (
            <option key={v} value={v}>{v === "all" ? "Every plot's value" : "The hovered plot's value"}</option>
          ))}
        </select>
        <label className="field canvas-toggle">
          <input type="checkbox" aria-label="Tooltip time" checked={tips.time} disabled={!tips.show}
                 onChange={(e) => setTip("time", e.target.checked)} />
          <span className="field-label">Show the time</span>
        </label>
        <label className="field canvas-toggle">
          <input type="checkbox" aria-label="Tooltip wrap" checked={tips.wrap} disabled={!tips.show}
                 onChange={(e) => setTip("wrap", e.target.checked)} />
          <span className="field-label">Wrap text</span>
        </label>
        <label className="field">
          <span className="field-label">Significant digits</span>
          <input type="number" min={1} max={MAX_SERIES_DIGITS} aria-label="Tooltip significant digits"
                 value={tips.digits} disabled={!tips.show}
                 onChange={(e) => setTip("digits", Number(e.target.value))} />
        </label>
      </div>
      <label className="field">
        <span className="field-label">Title</span>
        <input type="text" value={title || ""}
               onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))} />
      </label>
      </>}
    />
  );
}

/** One of p.396's initial event sets in the settings panel (§658): its object
 * set, the start and end properties of the set's type, and its name. */
function SeriesInitialEventSetRow({ index, raw, sets, onChange }: {
  index: number;
  raw: Record<string, unknown>;
  sets: { id: string; label: string; object_set?: unknown }[];
  onChange: (next: Record<string, unknown> | null) => void;
}) {
  const { workspaceId } = useCanvasEnv();
  const variable = typeof raw.objectSetVariable === "string" ? raw.objectSetVariable : "";
  const typeId = (sets.find((v) => v.id === variable)?.object_set as { object_type_id?: string } | undefined)
    ?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const moments = (type.data?.properties ?? []).filter((p) => p.data_type === "timestamp" || p.data_type === "date");
  const name = `Initial event set ${index + 1}`;
  const text = (key: string) => (typeof raw[key] === "string" ? raw[key] as string : "");
  return (
    <div className="row-actions" data-testid={`series-initial-event-set-${index + 1}`} style={{ flexWrap: "wrap", gap: 4 }}>
      <select aria-label={`${name} object set`} value={variable}
              onChange={(e) => onChange({ ...raw, objectSetVariable: e.target.value, start: "", end: "" })}>
        <option value="">Object set…</option>
        {sets.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
      </select>
      <select aria-label={`${name} start`} value={text("start")} disabled={!typeId}
              onChange={(e) => onChange({ ...raw, start: e.target.value })}>
        <option value="">Start property…</option>
        {moments.map((p) => <option key={p.api_name} value={p.api_name}>{p.display_name}</option>)}
      </select>
      <select aria-label={`${name} end`} value={text("end")} disabled={!typeId}
              onChange={(e) => onChange({ ...raw, end: e.target.value })}>
        <option value="">No end (a moment)</option>
        {moments.map((p) => <option key={p.api_name} value={p.api_name}>{p.display_name}</option>)}
      </select>
      <input aria-label={`${name} label`} value={text("label")} placeholder="Name"
             onChange={(e) => onChange({ ...raw, label: e.target.value })} />
      <button type="button" className="btn quiet" aria-label={`Remove ${name.toLowerCase()}`}
              onClick={() => onChange(null)}>×</button>
    </div>
  );
}

export function EmbeddedModuleSettings() {
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

export function LoopSectionSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    source, arrayVariable,
    objectSetVariable, moduleId, itemVariable, mapping,
    paging, maxItems, pageSize, display, maxColumns, minCardWidth, sort,
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
    sort: node.data.props.sort,
  }));
  const { declared, resolved } = useCanvasVariables();
  // p.132's property sorts need the looped type's properties, resolved the same
  // way the Object Selector's panel resolves them.
  const loopTypeId = objectSetVariable
    ? ((resolved[objectSetVariable] as { object_type_id?: string } | undefined)
        ?.object_type_id ?? null)
    : null;
  const loopType = useQuery({
    queryKey: ["object-type", loopTypeId],
    queryFn: () => objApi.getType(workspaceId, loopTypeId!),
    enabled: !!loopTypeId,
  });
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

      {/* p.132: "Property sorts may be applied to the object set being looped
          through to determine the order in which the objects will be
          displayed." Offered rather than said, as of §231 — this was a refusal
          citing decision 0006, correct when written and untrue from §221.
          Only on the object-set arm: p.133's array entries are "ordered by the
          entry's position in the array", which is the array's own order and not
          a sort anybody applies. */}
      {!overArray && (
        <PropertySortField
          label="Sort objects by"
          testId="loop-sort"
          value={sort}
          properties={loopType.data?.properties ?? []}
          onChange={(next) => setProp((p: { sort: string }) => (p.sort = next))}
        />
      )}
      </>}
    />
  );
}

/** p.300's Geometry and Legend visibility for one layer (§670): its geoshape
 * properties, each with its colour and whether the legend lists it, in the
 * order they are drawn. */
function MapGeometrySettings({ tag, value, properties, inLegend, onChange, onInLegend }: {
  tag: string;
  value: unknown;
  properties: { api_name: string; data_type: string }[];
  inLegend: boolean;
  onChange: (next: MapGeometry[]) => void;
  onInLegend: (on: boolean) => void;
}) {
  const geometries = geometriesOf(value);
  const shapes = properties.filter((p) => p.data_type === "geoshape");
  return (
    <div className="field" data-testid={`${tag}-geometries`}>
      <span className="field-label">Geometry</span>
      {geometries.map((g, n) => (
        <div key={g.id} className="field-inline" data-testid={`${tag}-geometry`}>
          <select aria-label={`Geometry ${n + 1} property`} value={g.property ?? ""}
            onChange={(e) => onChange(withGeometrySetting(value, g.id, "property", e.target.value || null))}>
            <option value="">Geoshape property…</option>
            {shapes.map((p) => <option key={p.api_name} value={p.api_name}>{p.api_name}</option>)}
          </select>
          <input type="color" aria-label={`Geometry ${n + 1} colour`} value={g.color ?? "#14646e"}
            onChange={(e) => onChange(withGeometrySetting(value, g.id, "color", e.target.value))} />
          <label className="canvas-toggle">
            <input type="checkbox" aria-label={`Geometry ${n + 1} in the legend`} checked={g.legend}
              onChange={(e) => onChange(withGeometrySetting(value, g.id, "legend", e.target.checked))} />
            <span>Legend</span>
          </label>
          <button type="button" className="btn quiet" aria-label={`Move geometry ${n + 1} earlier`}
            disabled={n === 0} onClick={() => onChange(withGeometryEarlier(value, g.id))}>↑</button>
          <button type="button" className="btn quiet" aria-label={`Remove geometry ${n + 1}`}
            onClick={() => onChange(withoutGeometry(value, g.id))}>×</button>
        </div>
      ))}
      <button type="button" className="btn quiet" data-testid={`${tag}-add-geometry`}
        disabled={geometries.length >= MAX_GEOMETRIES} onClick={() => onChange(withNewGeometry(value))}>
        Add geometry
      </button>
      {shapes.length === 0 && properties.length > 0 && (
        <span className="field-hint">This type has no geoshape property to draw.</span>
      )}
      <label className="field canvas-toggle">
        <input type="checkbox" data-testid={`${tag}-in-legend`} checked={inLegend}
          onChange={(e) => onInLegend(e.target.checked)} />
        <span className="field-label">Layer in the legend</span>
      </label>
    </div>
  );
}

function MapLayerSettings({ layer, onSet, onRemove }: {
  layer: MapLayer;
  onSet: <K extends keyof MapLayer>(key: K, value: MapLayer[K]) => void;
  onRemove: () => void;
}) {
  const { workspaceId } = useCanvasEnv();
  const { declared } = useCanvasVariables();
  const typeId = (declared[layer.objectSetVariable ?? ""]?.object_set as
    { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const properties = type.data?.properties ?? [];
  const tag = `map-added-layer-${layer.id}`;
  return (
    <div className="field" data-testid={tag} style={{ borderTop: "1px solid var(--border)", paddingTop: 6 }}>
      <input type="text" aria-label="Layer label" data-testid={`${tag}-label`} value={layer.label}
        placeholder="Label" onChange={(e) => onSet("label", e.target.value)} />
      <select aria-label="Layer object set" data-testid={`${tag}-set`}
        value={layer.objectSetVariable ?? ""}
        onChange={(e) => onSet("objectSetVariable", e.target.value || null)}>
        <option value="">Object set: choose…</option>
        {Object.values(declared).filter((v) => v.kind === "object_set")
          .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
      </select>
      <select aria-label="Layer location property" data-testid={`${tag}-location`}
        value={layer.locationProperty ?? ""} disabled={!typeId}
        onChange={(e) => onSet("locationProperty", e.target.value || null)}>
        <option value="">Location: choose…</option>
        {properties.filter((p) => p.data_type === "geopoint")
          .map((p) => <option key={p.api_name} value={p.api_name}>{p.api_name}</option>)}
      </select>
      <select aria-label="Layer label property" data-testid={`${tag}-label-property`}
        value={layer.labelProperty ?? ""} disabled={!typeId}
        onChange={(e) => onSet("labelProperty", e.target.value || null)}>
        <option value="">Pin label: primary key</option>
        {properties.map((p) => <option key={p.api_name} value={p.api_name}>{p.api_name}</option>)}
      </select>
      <select aria-label="Layer selected objects" data-testid={`${tag}-selected`}
        value={layer.selectedVariable ?? ""}
        onChange={(e) => onSet("selectedVariable", e.target.value || null)}>
        <option value="">No selected objects</option>
        {Object.values(declared).filter((v) => holdsClauses(v) && !v.derivation)
          .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
      </select>
      <label className="field canvas-toggle">
        <input type="checkbox" data-testid={`${tag}-visible`} checked={layer.visible}
          onChange={(e) => onSet("visible", e.target.checked)} />
        <span className="field-label">Layer visible</span>
      </label>
      <select aria-label="Layer visibility variable" data-testid={`${tag}-visible-variable`}
        value={layer.visibleVariable ?? ""}
        onChange={(e) => onSet("visibleVariable", e.target.value || null)}>
        <option value="">Visibility: the setting above</option>
        {Object.values(declared).filter((v) => v.kind === "boolean")
          .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
      </select>
      <label className="field canvas-toggle">
        <input type="checkbox" data-testid={`${tag}-lock`} checked={layer.locked}
          onChange={(e) => onSet("locked", e.target.checked)} />
        <span className="field-label">Lock layer</span>
      </label>
      <input type="color" aria-label="Layer colour" data-testid={`${tag}-color`}
        value={layer.color ?? "#14646e"} onChange={(e) => onSet("color", e.target.value)} />
      <input type="number" aria-label="Layer opacity" data-testid={`${tag}-opacity`}
        min={0.1} max={1} step={0.1} value={layer.opacity}
        onChange={(e) => onSet("opacity", layerOpacityOf(e.target.value))} />
      <MapGeometrySettings tag={tag} value={layer.geometries} properties={properties}
        inLegend={layer.inLegend} onChange={(next) => onSet("geometries", next)}
        onInLegend={(on) => onSet("inLegend", on)} />
      <button type="button" className="btn quiet" data-testid={`${tag}-remove`} onClick={onRemove}>
        Remove layer
      </button>
    </div>
  );
}

export function MapSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const {
    source, objectTypeId, locationProperty, labelProperty, datasetId,
    locationColumn, latColumn, lonColumn, labelColumn,
    filterProperty, filterColumn, filterOperator, filterParameter, searchParameter,
    objectSetVariable, areaVariable, trackProperty, enableTimeline, selectedTimeVariable,
    windowStartVariable, windowEndVariable, timeZone, timeFormat, playingVariable,
    allowTimeChange, liveModeToggle, openTimelineByDefault,
    playbackPositionVariable, autoPauseVariable, layerLabel, selectedVariable, layerVisible,
    layerVisibleVariable, lockLayer, layerColor, layerOpacity,
    drawOptions, drawnShapeColor, drawnShapeOpacity, singleDrawMode, drawnShapesVariable,
    selectedShapesVariable, shapeOutputType, enableMeasurements, measurePerimeter, perimeterMode, measureArea, measureLine, lineMode,
    showLegend, legendCollapsed, legendSize, showSelectionPanel, autoZoom, autoZoomSetVariable,
    autoZoomOutsideOnly, boundsVariable, followSetVariable, layers, geometries, layerInLegend,
    enableSearchAround,
    actions: { setProp },
  } = useNode((node) => ({
    enableSearchAround: node.data.props.enableSearchAround,
    layers: node.data.props.layers,
    geometries: node.data.props.geometries,
    layerInLegend: node.data.props.layerInLegend,
    showLegend: node.data.props.showLegend,
    legendCollapsed: node.data.props.legendCollapsed,
    legendSize: node.data.props.legendSize,
    showSelectionPanel: node.data.props.showSelectionPanel,
    autoZoom: node.data.props.autoZoom,
    autoZoomSetVariable: node.data.props.autoZoomSetVariable,
    autoZoomOutsideOnly: node.data.props.autoZoomOutsideOnly,
    boundsVariable: node.data.props.boundsVariable,
    followSetVariable: node.data.props.followSetVariable,
    layerLabel: node.data.props.layerLabel,
    selectedVariable: node.data.props.selectedVariable,
    layerVisible: node.data.props.layerVisible,
    layerVisibleVariable: node.data.props.layerVisibleVariable,
    lockLayer: node.data.props.lockLayer,
    layerColor: node.data.props.layerColor,
    layerOpacity: node.data.props.layerOpacity,
    drawOptions: node.data.props.drawOptions,
    drawnShapeColor: node.data.props.drawnShapeColor,
    drawnShapeOpacity: node.data.props.drawnShapeOpacity,
    singleDrawMode: node.data.props.singleDrawMode,
    drawnShapesVariable: node.data.props.drawnShapesVariable,
    selectedShapesVariable: node.data.props.selectedShapesVariable,
    shapeOutputType: node.data.props.shapeOutputType,
    enableMeasurements: node.data.props.enableMeasurements,
    measurePerimeter: node.data.props.measurePerimeter,
    perimeterMode: node.data.props.perimeterMode,
    measureArea: node.data.props.measureArea,
    measureLine: node.data.props.measureLine,
    lineMode: node.data.props.lineMode,
    windowStartVariable: node.data.props.windowStartVariable,
    windowEndVariable: node.data.props.windowEndVariable,
    timeZone: node.data.props.timeZone,
    timeFormat: node.data.props.timeFormat,
    allowTimeChange: node.data.props.allowTimeChange,
    liveModeToggle: node.data.props.liveModeToggle,
    openTimelineByDefault: node.data.props.openTimelineByDefault,
    playingVariable: node.data.props.playingVariable,
    playbackPositionVariable: node.data.props.playbackPositionVariable,
    autoPauseVariable: node.data.props.autoPauseVariable,
    areaVariable: node.data.props.areaVariable,
    trackProperty: node.data.props.trackProperty,
    enableTimeline: node.data.props.enableTimeline,
    selectedTimeVariable: node.data.props.selectedTimeVariable,
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
  // `TypePicker` owns the object type read now (§256): the listing is a page,
  // so a control over it has to be able to search the ontology rather than the
  // rows it happened to receive.
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
            <TypePicker
              workspaceId={workspaceId}
              value={objectTypeId || ""}
              placeholder="Choose…"
              onChange={(id) =>
                setProp((p: Record<string, unknown>) => {
                  p.objectTypeId = id || null;
                  p.locationProperty = null;
                  p.labelProperty = null;
                  p.filterProperty = null;
                })
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
          {/* p.302's shape-based selection (§550): where a drawn area goes,
              for a narrowed set to read - offered over an object set, whose
              objects are what an area can select. */}
          {objectSetVariable && (
            <label className="field">
              <span className="field-label">Area selection writes to</span>
              <select
                data-testid="map-area-variable"
                value={areaVariable || ""}
                onChange={(e) => setProp((p: { areaVariable: string | null }) =>
                  (p.areaVariable = e.target.value || null))}
              >
                <option value="">No area selection</option>
                {Object.values(declared).filter((v) => holdsClauses(v) && !v.derivation)
                  .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </select>
              <span className="field-hint">
                An array a narrowed set reads: an area, shape or circle drawn on the map
                selects the objects in it
              </span>
            </label>
          )}
          {/* p.301's Draw options and drawn shape style (§573). */}
          {objectSetVariable && areaVariable && (
            <div className="field" data-testid="map-draw-settings">
              <span className="field-label">Draw options</span>
              {DRAW_TOOLS.map((tool) => (
                <label key={tool} className="field canvas-toggle">
                  <input
                    type="checkbox"
                    data-testid={`map-draw-option-${tool}`}
                    checked={drawToolsOf(drawOptions).includes(tool)}
                    onChange={(e) => setProp((p: { drawOptions: string[] | null }) =>
                      (p.drawOptions = withDrawTool(p.drawOptions, tool, e.target.checked)))}
                  />
                  <span className="field-label">{DRAW_TOOL_LABELS[tool]}</span>
                </label>
              ))}
              <input
                type="color"
                aria-label="Drawn shape colour"
                data-testid="map-drawn-color"
                value={layerColorOf(drawnShapeColor) ?? "#14646e"}
                onChange={(e) => setProp((p: { drawnShapeColor: string | null }) =>
                  (p.drawnShapeColor = e.target.value))}
              />
              <input
                type="number"
                aria-label="Drawn shape opacity"
                data-testid="map-drawn-opacity"
                min={0}
                max={1}
                step={0.05}
                value={drawnOpacityOf(drawnShapeOpacity)}
                onChange={(e) => setProp((p: { drawnShapeOpacity: number }) =>
                  (p.drawnShapeOpacity = drawnOpacityOf(e.target.value)))}
              />
              {/* p.301's Enable single draw mode (§640). */}
              <label className="field canvas-toggle">
                <input
                  type="checkbox"
                  data-testid="map-single-draw"
                  checked={singleDrawOf(singleDrawMode)}
                  onChange={(e) => setProp((p: { singleDrawMode: boolean }) =>
                    (p.singleDrawMode = e.target.checked))}
                />
                <span className="field-label">Enable single draw mode</span>
                <span className="field-hint">
                  Off, each shape drawn joins the others, and the objects inside any of them
                  are selected
                </span>
              </label>
              {/* p.301's Drawn shapes and Shape output type (§574). */}
              <select
                aria-label="Drawn shapes"
                data-testid="map-drawn-shapes-variable"
                value={drawnShapesVariable || ""}
                onChange={(e) => setProp((p: { drawnShapesVariable: string | null }) =>
                  (p.drawnShapesVariable = e.target.value || null))}
              >
                <option value="">Drawn shapes: not written</option>
                {Object.values(declared).filter((v) => v.kind === "string" && !v.derivation)
                  .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </select>
              {/* p.301's Selected shapes (§641). */}
              <select
                aria-label="Selected shapes"
                data-testid="map-selected-shapes-variable"
                value={selectedShapesVariable || ""}
                onChange={(e) => setProp((p: { selectedShapesVariable: string | null }) =>
                  (p.selectedShapesVariable = e.target.value || null))}
              >
                <option value="">Selected shapes: not written</option>
                {Object.values(declared).filter((v) => v.kind === "string" && !v.derivation)
                  .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </select>
              <select
                aria-label="Shape output type"
                data-testid="map-shape-output"
                value={shapeOutputOf(shapeOutputType)}
                onChange={(e) => setProp((p: { shapeOutputType: string }) =>
                  (p.shapeOutputType = e.target.value))}
              >
                <option value="features">As a feature collection</option>
                <option value="geometries">As a geometry collection</option>
              </select>
              {/* p.302's measurements (§575). */}
              <label className="field canvas-toggle">
                <input
                  type="checkbox"
                  data-testid="map-measure-enabled"
                  checked={!!enableMeasurements}
                  onChange={(e) => setProp((p: { enableMeasurements: boolean }) =>
                    (p.enableMeasurements = e.target.checked))}
                />
                <span className="field-label">Measurements</span>
              </label>
              {enableMeasurements && (
                <>
                  <label className="field canvas-toggle">
                    <input
                      type="checkbox"
                      data-testid="map-measure-perimeter"
                      checked={measurePerimeter !== false}
                      onChange={(e) => setProp((p: { measurePerimeter: boolean }) =>
                        (p.measurePerimeter = e.target.checked))}
                    />
                    <span className="field-label">Perimeter</span>
                  </label>
                  <select
                    aria-label="Perimeter as"
                    data-testid="map-measure-perimeter-mode"
                    value={perimeterModeOf(perimeterMode)}
                    disabled={measurePerimeter === false}
                    onChange={(e) => setProp((p: { perimeterMode: string }) =>
                      (p.perimeterMode = e.target.value))}
                  >
                    <option value="total">The total</option>
                    <option value="segments">Each segment</option>
                  </select>
                  <label className="field canvas-toggle">
                    <input
                      type="checkbox"
                      data-testid="map-measure-area"
                      checked={measureArea !== false}
                      onChange={(e) => setProp((p: { measureArea: boolean }) =>
                        (p.measureArea = e.target.checked))}
                    />
                    <span className="field-label">Area</span>
                  </label>
                  {/* p.302's line measurements (§634). */}
                  <label className="field canvas-toggle">
                    <input
                      type="checkbox"
                      data-testid="map-measure-line"
                      checked={measureLine !== false}
                      onChange={(e) => setProp((p: { measureLine: boolean }) =>
                        (p.measureLine = e.target.checked))}
                    />
                    <span className="field-label">Line length</span>
                  </label>
                  <select
                    aria-label="Line length as"
                    data-testid="map-measure-line-mode"
                    value={perimeterModeOf(lineMode)}
                    disabled={measureLine === false}
                    onChange={(e) => setProp((p: { lineMode: string }) =>
                      (p.lineMode = e.target.value))}
                  >
                    <option value="total">The total</option>
                    <option value="segments">Each segment</option>
                  </select>
                </>
              )}
            </div>
          )}
          {/* p.300's layer settings (§559), for the map's one object layer. */}
          {objectSetVariable && (
            <div className="field" data-testid="map-layer-settings">
              <span className="field-label">Layer</span>
              <input
                type="text"
                aria-label="Layer label"
                data-testid="map-layer-label"
                value={layerLabel ?? ""}
                placeholder="Label"
                onChange={(e) => setProp((p: { layerLabel: string }) => (p.layerLabel = e.target.value))}
              />
              <select
                aria-label="Selected objects"
                data-testid="map-selected-variable"
                value={selectedVariable || ""}
                onChange={(e) => setProp((p: { selectedVariable: string | null }) =>
                  (p.selectedVariable = e.target.value || null))}
              >
                <option value="">No selected objects</option>
                {Object.values(declared).filter((v) => holdsClauses(v) && !v.derivation)
                  .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </select>
              <label className="field canvas-toggle">
                <input
                  type="checkbox"
                  data-testid="map-layer-visible"
                  checked={layerVisible !== false}
                  onChange={(e) => setProp((p: { layerVisible: boolean }) =>
                    (p.layerVisible = e.target.checked))}
                />
                <span className="field-label">Layer visible</span>
              </label>
              <select
                aria-label="Layer visibility variable"
                data-testid="map-layer-visible-variable"
                value={layerVisibleVariable || ""}
                onChange={(e) => setProp((p: { layerVisibleVariable: string | null }) =>
                  (p.layerVisibleVariable = e.target.value || null))}
              >
                <option value="">Visibility: the setting above</option>
                {Object.values(declared).filter((v) => v.kind === "boolean")
                  .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
              </select>
              <label className="field canvas-toggle">
                <input
                  type="checkbox"
                  data-testid="map-lock-layer"
                  checked={!!lockLayer}
                  onChange={(e) => setProp((p: { lockLayer: boolean }) =>
                    (p.lockLayer = e.target.checked))}
                />
                <span className="field-label">Lock layer</span>
              </label>
              <input
                type="color"
                aria-label="Layer colour"
                data-testid="map-layer-color"
                value={layerColorOf(layerColor) ?? "#14646e"}
                onChange={(e) => setProp((p: { layerColor: string | null }) =>
                  (p.layerColor = e.target.value))}
              />
              <input
                type="number"
                aria-label="Layer opacity"
                data-testid="map-layer-opacity"
                min={0.1}
                max={1}
                step={0.1}
                value={layerOpacityOf(layerOpacity)}
                onChange={(e) => setProp((p: { layerOpacity: number }) =>
                  (p.layerOpacity = layerOpacityOf(e.target.value)))}
              />
              <MapGeometrySettings tag="map-layer" value={geometries} properties={detail.data?.properties ?? []}
                inLegend={layerInLegend !== false}
                onChange={(next) => setProp((p: { geometries: unknown }) => (p.geometries = next))}
                onInLegend={(on) => setProp((p: { layerInLegend: boolean }) => (p.layerInLegend = on))} />
            </div>
          )}
          {/* p.300's Add object layer (§642): layers after the map's own. */}
          {objectSetVariable && (
            <div className="field" data-testid="map-added-layers">
              {layersOf(layers).map((layer) => (
                <MapLayerSettings
                  key={layer.id}
                  layer={layer}
                  onSet={(key, value) => setProp((p: { layers: unknown }) =>
                    (p.layers = withLayerSetting(p.layers, layer.id, key, value)))}
                  onRemove={() => setProp((p: { layers: unknown }) =>
                    (p.layers = withoutLayer(p.layers, layer.id)))}
                />
              ))}
              <button
                type="button"
                className="btn quiet"
                data-testid="map-add-layer"
                disabled={layersOf(layers).length >= MAX_LAYERS}
                onClick={() => setProp((p: { layers: unknown }) => (p.layers = withNewLayer(p.layers)))}
              >
                Add object layer
              </button>
            </div>
          )}
          {/* p.304's interface options (§560). */}
          {objectSetVariable && (
            <div className="field" data-testid="map-interface-settings">
              <span className="field-label">Interface</span>
              {([
                ["showLegend", "Legend", showLegend],
                ["legendCollapsed", "Collapse legend panel", legendCollapsed],
                ["showSelectionPanel", "Show selection panel", showSelectionPanel],
                // p.303's Enable search around (§734).
                ["enableSearchAround", "Enable search around", enableSearchAround],
                ["autoZoomOutsideOnly", "Auto zoom only if outside the viewport", autoZoomOutsideOnly],
              ] as const).map(([prop, label, value]) => (
                <label key={prop} className="field canvas-toggle">
                  <input
                    type="checkbox"
                    data-testid={`map-${prop}`}
                    checked={!!value}
                    onChange={(e) => setProp((p: Record<string, unknown>) => {
                      p[prop] = e.target.checked;
                    })}
                  />
                  <span className="field-label">{label}</span>
                </label>
              ))}
              <select
                aria-label="Legend panel size"
                data-testid="map-legendSize"
                value={legendSize === "compact" ? "compact" : "full"}
                onChange={(e) => setProp((p: { legendSize: string }) => (p.legendSize = e.target.value))}
              >
                <option value="full">Legend: full size</option>
                <option value="compact">Legend: compact</option>
              </select>
              <select
                aria-label="Viewport auto zoom"
                data-testid="map-autoZoom"
                value={autoZoom === "all" || autoZoom === "set" ? autoZoom : "default"}
                onChange={(e) => setProp((p: { autoZoom: string }) => (p.autoZoom = e.target.value))}
              >
                <option value="default">Auto zoom: fit once, then the reader&apos;s</option>
                <option value="all">Auto zoom: all objects</option>
                <option value="set">Auto zoom: an object set</option>
              </select>
              {([
                ["autoZoomSetVariable", "Auto zoom object set", autoZoomSetVariable, "object_set"],
                ["followSetVariable", "Viewport follow object set", followSetVariable, "object_set"],
                ["boundsVariable", "Viewport bounds", boundsVariable, "string"],
              ] as const).map(([prop, label, value, kind]) => (
                <select
                  key={prop}
                  aria-label={label}
                  data-testid={`map-${prop}`}
                  value={value || ""}
                  onChange={(e) => setProp((p: Record<string, unknown>) => {
                    p[prop] = e.target.value || null;
                  })}
                >
                  <option value="">{label}: none</option>
                  {Object.values(declared).filter((v) => v.kind === kind)
                    .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                </select>
              ))}
            </div>
          )}
          {/* §557: tracks and p.303's timeline, over an object set. */}
          {objectSetVariable && (
            <>
              <label className="field">
                <span className="field-label">Track</span>
                <select
                  data-testid="map-track-property"
                  value={trackProperty || ""}
                  onChange={(e) => setProp((p: { trackProperty: string | null }) =>
                    (p.trackProperty = e.target.value || null))}
                >
                  <option value="">No tracks</option>
                  {(detail.data?.properties ?? [])
                    .filter((p) => p.data_type === "geotemporal_series")
                    .map((p) => (
                      <option key={p.api_name} value={p.api_name}>{p.display_name || p.api_name}</option>
                    ))}
                </select>
                <span className="field-hint">
                  A geotemporal series: each object&apos;s path, and where it was at the selected time
                </span>
              </label>
              {trackProperty && (
                <>
                  <label className="field canvas-toggle">
                    <input
                      type="checkbox"
                      data-testid="map-enable-timeline"
                      checked={!!enableTimeline}
                      onChange={(e) => setProp((p: { enableTimeline: boolean }) =>
                        (p.enableTimeline = e.target.checked))}
                    />
                    <span className="field-label">Enable timeline</span>
                  </label>
                  <label className="field">
                    <span className="field-label">Selected time</span>
                    <select
                      data-testid="map-selected-time"
                      value={selectedTimeVariable || ""}
                      onChange={(e) => setProp((p: { selectedTimeVariable: string | null }) =>
                        (p.selectedTimeVariable = e.target.value || null))}
                    >
                      <option value="">The viewer&apos;s own</option>
                      {Object.values(declared)
                        .filter((v) => (v.kind === "timestamp" || v.kind === "date") && !v.derivation)
                        .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                    </select>
                  </label>
                  {/* p.303's user controls and the open button (§576). */}
                  {([
                    ["allowTimeChange", "Allow user to change selected time", allowTimeChange],
                    ["liveModeToggle", "View latest option", liveModeToggle],
                    ["openTimelineByDefault", "Open timeline by default", openTimelineByDefault],
                  ] as const).map(([key, label, value]) => (
                    <label key={key} className="field canvas-toggle">
                      <input
                        type="checkbox"
                        data-testid={`map-${key}`}
                        checked={value !== false}
                        disabled={key === "liveModeToggle" && allowTimeChange === false}
                        onChange={(e) => setProp((p: Record<string, boolean>) =>
                          (p[key] = e.target.checked))}
                      />
                      <span className="field-label">{label}</span>
                    </label>
                  ))}
                  {/* The rest of p.303's time configuration (§558). */}
                  {([
                    ["windowStartVariable", "Time window from", windowStartVariable, ["timestamp", "date"]],
                    ["windowEndVariable", "Time window to", windowEndVariable, ["timestamp", "date"]],
                    ["playingVariable", "Playback state", playingVariable, ["boolean"]],
                    ["playbackPositionVariable", "Playback position", playbackPositionVariable, ["number"]],
                    ["autoPauseVariable", "Auto pause at", autoPauseVariable, ["array"]],
                  ] as const).map(([prop, label, value, kinds]) => (
                    <label key={prop} className="field">
                      <span className="field-label">{label}</span>
                      <select
                        data-testid={`map-${prop}`}
                        value={value || ""}
                        onChange={(e) => setProp((p: Record<string, unknown>) => {
                          p[prop] = e.target.value || null;
                        })}
                      >
                        <option value="">Not bound</option>
                        {Object.values(declared)
                          .filter((v) => (kinds as readonly string[]).includes(v.kind) && !v.derivation)
                          .map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                      </select>
                    </label>
                  ))}
                  <label className="field">
                    <span className="field-label">Time zone</span>
                    <select
                      data-testid="map-time-zone"
                      value={timeZone === "local" ? "local" : "utc"}
                      onChange={(e) => setProp((p: { timeZone: string }) => (p.timeZone = e.target.value))}
                    >
                      <option value="utc">UTC</option>
                      <option value="local">Local</option>
                    </select>
                  </label>
                  {timeZone === "local" && (
                    <label className="field">
                      <span className="field-label">Time format</span>
                      <select
                        data-testid="map-time-format"
                        value={timeFormat || "local"}
                        onChange={(e) => setProp((p: { timeFormat: string }) => (p.timeFormat = e.target.value))}
                      >
                        <option value="local">Local</option>
                        <option value="12">12-hour</option>
                        <option value="24">24-hour</option>
                      </select>
                    </label>
                  )}
                </>
              )}
            </>
          )}
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

export function ChartSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    datasetId, kind, dimension, measure, aggregate, title,
    filterColumn, filterParameter, filterOperator, objectSetVariable, seriesVariable,
    drilldownVariable, segmentBy, segmentMode, showLegend, sort, orientation, valueLabels,
    scaleType, minBound, maxBound, showCategoryTitle, categoryTitle, showValueTitle, valueTitle,
    lineArea, nullDisplay, valueFormat, categoryFormat, legendPosition, segmentNames,
    series, seriesName, multipleAxes,
    showRightTitle, rightTitle, rightScaleType, rightMinBound, rightMaxBound, rightValueFormat,
    actions: { setProp },
  } = useNode((node) => ({
    multipleAxes: node.data.props.multipleAxes,
    showRightTitle: node.data.props.showRightTitle,
    rightTitle: node.data.props.rightTitle,
    rightScaleType: node.data.props.rightScaleType,
    rightMinBound: node.data.props.rightMinBound,
    rightMaxBound: node.data.props.rightMaxBound,
    rightValueFormat: node.data.props.rightValueFormat,
    series: node.data.props.series,
    seriesName: node.data.props.seriesName,
    legendPosition: node.data.props.legendPosition,
    segmentNames: node.data.props.segmentNames,
    valueFormat: node.data.props.valueFormat,
    categoryFormat: node.data.props.categoryFormat,
    lineArea: node.data.props.lineArea,
    nullDisplay: node.data.props.nullDisplay,
    scaleType: node.data.props.scaleType,
    minBound: node.data.props.minBound,
    maxBound: node.data.props.maxBound,
    showCategoryTitle: node.data.props.showCategoryTitle,
    categoryTitle: node.data.props.categoryTitle,
    showValueTitle: node.data.props.showValueTitle,
    valueTitle: node.data.props.valueTitle,
    sort: node.data.props.sort,
    orientation: node.data.props.orientation,
    valueLabels: node.data.props.valueLabels,
    segmentBy: node.data.props.segmentBy,
    segmentMode: node.data.props.segmentMode,
    showLegend: node.data.props.showLegend,
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
    (v) => holdsClauses(v) && !v.derivation,
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
          <span className="field-hint">Groups objects by the Category, measured below</span>
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
      {(kind || "bar") !== "pie" && !scatter && (
        <label className="field">
          <span className="field-label">Sort by</span>
          <select
            data-testid="chart-sort"
            value={chartSortOf(sort)}
            onChange={(e) => setProp((p: { sort: string }) => (p.sort = e.target.value))}
          >
            {Object.entries(CHART_SORTS).map(([key, name]) => (
              <option key={key} value={key}>{name}</option>
            ))}
          </select>
        </label>
      )}
      {(kind || "bar") === "bar" && (
        <label className="field">
          <span className="field-label">Orientation</span>
          <select
            data-testid="chart-orientation"
            value={orientationOf(orientation, "bar")}
            onChange={(e) =>
              setProp((p: { orientation: string }) => (p.orientation = e.target.value))}
          >
            <option value="vertical">Vertical</option>
            <option value="horizontal">Horizontal</option>
          </select>
        </label>
      )}
      {((kind || "bar") === "bar" || kind === "line") && (
        <label className="field canvas-toggle">
          <input
            type="checkbox"
            data-testid="chart-value-labels"
            checked={valueLabels === true}
            onChange={(e) =>
              setProp((p: { valueLabels: boolean }) => (p.valueLabels = e.target.checked))}
          />
          <span className="field-label">Value labels</span>
        </label>
      )}
      {(kind === "line" || !!seriesVariable) && (
        <>
          <label className="field">
            <span className="field-label">Area</span>
            <select
              data-testid="chart-line-area"
              value={areaOf(lineArea)}
              onChange={(e) => setProp((p: { lineArea: string }) => (p.lineArea = e.target.value))}
            >
              {Object.entries(AREA_OPTIONS).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
            {areaOf(lineArea) === "stacked" && !segmentBy && (
              <span className="field-hint" data-testid="chart-stacked-hint">
                Stacked piles segments on each other - choose Segment by
              </span>
            )}
          </label>
          <label className="field">
            <span className="field-label">Missing values</span>
            <select
              data-testid="chart-null-display"
              value={nullDisplayOf(nullDisplay)}
              onChange={(e) =>
                setProp((p: { nullDisplay: string }) => (p.nullDisplay = e.target.value))}
            >
              {Object.entries(NULL_DISPLAYS).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
            <span className="field-hint">
              {nullDisplayOf(nullDisplay) === "gap" ? "A gap in the line where a value is missing"
                : nullDisplayOf(nullDisplay) === "zeroes" ? "A missing value is drawn as 0"
                : "The line joins the values either side of a missing one"}
            </span>
          </label>
        </>
      )}
      {(kind || "bar") !== "pie" && (
        <ChartAxisFields
          segmented={!!objectSetVariable && !!segmentBy && (kind || "bar") === "bar"
            && (aggregate || "count") === "count"}
          axis={{ scaleType, minBound, maxBound }}
          titles={{ showCategoryTitle, categoryTitle, showValueTitle, valueTitle }}
          formats={{ value: valueFormat, category: categoryFormat, keyed: !seriesVariable }}
          defaults={seriesVariable
            ? { category: "Time", value: "The series' property" }
            : { category: dimension || "The category property",
                value: defaultValueTitle(kind || "bar", aggregate, measure) }}
          setProp={setProp as (fn: (p: Record<string, unknown>) => void) => void}
        />
      )}
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
            data-testid="chart-aggregate"
            onChange={(e) => setProp((p: { aggregate: string }) => (p.aggregate = e.target.value))}
          >
            <option value="count">Count of rows</option>
            {/* p.282's "Approximate Unique Count" (§615). */}
            <option value="count_distinct">Unique count of…</option>
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
            data-testid="chart-measure"
            onChange={(e) => setProp((p: { measure: string | null }) => (p.measure = e.target.value || null))}
          >
            <option value="">Choose…</option>
            {/* Over a set, p.281's arithmetic runs over a declared number:
                the server refuses anything else, so it is not offered. A
                unique count is of any column (§615). */}
            {(objectSetVariable && aggregate !== "count_distinct"
              ? columns.filter((c) => c.data_type === "integer" || c.data_type === "float")
              : columns
            ).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
        </label>
      )}
      {objectSetVariable && !seriesVariable && ((kind || "bar") === "bar" || kind === "line") && (
        <ChartSeriesFields
          // §678: a segmented *bar* chart keeps its series, each beside it; a
          // segmented line chart is one layer, a line per segment.
          segmented={!!segmentBy && kind === "line"}
          chartKind={kind === "line" ? "line" : "bar"}
          series={series}
          firstName={typeof seriesName === "string" ? seriesName : ""}
          firstDefault={defaultValueTitle(kind || "bar", aggregate, measure)}
          rightAxis={{ showRightTitle, rightTitle, rightScaleType, rightMinBound, rightMaxBound,
                       rightValueFormat }}
          numbers={columns.filter((c) => c.data_type === "integer" || c.data_type === "float")
            .map((c) => c.name)}
          names={columns.map((c) => c.name)}
          showLegend={showLegend !== false}
          legend={legendPosition}
          twoAxes={multipleAxes === true}
          sets={setVariables.map((v) => ({ id: v.id, label: v.label }))}
          chartSet={objectSetVariable}
          clauses={clauseVariables.map((v) => ({ id: v.id, label: v.label }))}
          setProp={setProp as (fn: (p: Record<string, unknown>) => void) => void}
        />
      )}
      {objectSetVariable && ((kind || "bar") === "bar" || kind === "line") && (
        <>
          <label className="field">
            <span className="field-label">Segment by</span>
            <select
              value={segmentBy || ""}
              data-testid="chart-segment-by"
              // §678: a bar chart may segment and keep its series; a line
              // chart's segments are its lines, so it has one series or the
              // other.
              disabled={(aggregate || "count") !== "count" || (kind === "line" && seriesOf(series).length > 0)}
              onChange={(e) =>
                setProp((p: { segmentBy: string | null }) => (p.segmentBy = e.target.value || null))}
            >
              <option value="">No segments</option>
              {columns.filter((c) => c.name !== dimension).map((c) => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
            {(aggregate || "count") !== "count" && (
              <span className="field-hint">Segments count objects - set Measure to a count</span>
            )}
            {kind === "line" && seriesOf(series).length > 0 && (
              <span className="field-hint">A line chart with several series is not segmented</span>
            )}
          </label>
          {segmentBy && (
            <>
              {(kind || "bar") === "bar" && (
              <label className="field">
                <span className="field-label">Segment display</span>
                <select
                  value={segmentModeOf(segmentMode)}
                  data-testid="chart-segment-mode"
                  onChange={(e) =>
                    setProp((p: { segmentMode: string }) => (p.segmentMode = e.target.value))}
                >
                  {Object.entries(SEGMENT_MODES).map(([key, name]) => (
                    <option key={key} value={key}>{name}</option>
                  ))}
                </select>
              </label>
              )}
              <label className="field canvas-toggle">
                <input
                  type="checkbox"
                  data-testid="chart-show-legend"
                  checked={showLegend !== false}
                  onChange={(e) =>
                    setProp((p: { showLegend: boolean }) => (p.showLegend = e.target.checked))}
                />
                <span className="field-label">Show legend</span>
              </label>
              {showLegend !== false && (
                <SegmentLegendFields
                  set={resolved[objectSetVariable as string]}
                  segmentBy={segmentBy}
                  legend={legendPosition}
                  names={segmentNames}
                  setProp={setProp as (fn: (p: Record<string, unknown>) => void) => void}
                />
              )}
            </>
          )}
        </>
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

/** p.281's multiple series and p.282's name for each (§541), in the Chart's
 * panel. The Measure above is the first series; these are the rest. */
/** The layer Data input that is a function rather than a set (§771). */
const FUNCTION_INPUT = "__function";

function ChartSeriesFields({
  segmented, series, firstName, firstDefault, numbers, names, showLegend, legend, twoAxes,
  sets, chartSet, clauses, setProp, chartKind = "bar", rightAxis,
}: {
  /** p.283's per-series value axes (§691): the right axis's settings. */
  rightAxis: {
    showRightTitle?: unknown; rightTitle?: unknown; rightScaleType?: unknown;
    rightMinBound?: unknown; rightMaxBound?: unknown; rightValueFormat?: unknown;
  };
  /** The chart's own type, which a series naming none is drawn as (§626). */
  chartKind?: "bar" | "line";
  /** p.282's Selection as filter per layer (§628): the array variables a
   * series may write its selection into. */
  clauses: { id: string; label: string }[];
  /** p.283's Use multiple value axes (§542). */
  twoAxes: boolean;
  /** p.280's layer Data input (§625): the object set variables a series may
   * read instead of the chart's, `chartSet`. */
  sets: { id: string; label: string }[];
  chartSet: string;
  segmented: boolean;
  series: unknown;
  firstName: string;
  firstDefault: string;
  numbers: string[];
  /** Every property, for a unique count (§615). */
  names: string[];
  showLegend: boolean;
  legend: unknown;
  setProp: (fn: (p: Record<string, unknown>) => void) => void;
}) {
  const specs = seriesOf(series);
  const write = (next: typeof specs) => setProp((p) => (p.series = next));
  // A series reading a set of its own (§625) is offered that set's
  // properties, which are another type's: each such type is read once.
  const { workspaceId } = useCanvasEnv();
  const { resolved } = useCanvasVariables();
  const ownSet = (spec: (typeof specs)[number]) =>
    spec.objectSetVariable !== null && spec.objectSetVariable !== chartSet
      ? spec.objectSetVariable : null;
  const typeOf = (variable: string) =>
    (resolved[variable] as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const typeIds = [...new Set(specs.flatMap((spec) => {
    const own = ownSet(spec);
    const type = own ? typeOf(own) : null;
    return type ? [type] : [];
  }))];
  const types = useQueries({
    queries: typeIds.map((id) => ({
      queryKey: ["object-type", id],
      queryFn: () => objApi.getType(workspaceId, id),
    })),
  });
  const propertiesOf = (spec: (typeof specs)[number]) => {
    const own = ownSet(spec);
    if (!own) return null;
    const type = typeOf(own);
    const found = types[typeIds.indexOf(type ?? "")]?.data;
    return (found?.properties ?? []).map((prop) => ({ name: prop.api_name, type: prop.data_type }));
  };
  if (segmented) {
    return (
      <p className="field-hint" data-testid="chart-series-segmented">
        A segmented line chart has one series: its segments are what the legend names.
      </p>
    );
  }
  return (
    <div className="field" data-testid="chart-series">
      <span className="field-label">More series</span>
      {specs.map((spec, i) => {
        const own = propertiesOf(spec);
        const seriesNumbers = own
          ? own.filter((p) => p.type === "integer" || p.type === "float").map((p) => p.name)
          : numbers;
        const seriesNames = own ? own.map((p) => p.name) : names;
        return (
        <div key={i} className="field-inline" data-testid="chart-series-row">
          {/* p.280's layer Title (§757): for the builder; nothing draws it. */}
          <input
            type="text"
            aria-label={`Series ${i + 2} title`}
            data-testid="chart-series-title"
            placeholder={`Series ${i + 2}`}
            value={spec.title}
            maxLength={100}
            onChange={(e) => write(specs.map((s, j) => (j === i ? { ...s, title: e.target.value } : s)))}
          />
          <select
            aria-label={`Series ${i + 2} object set`}
            data-testid="chart-series-set"
            value={spec.fn ? FUNCTION_INPUT : ownSet(spec) ?? ""}
            onChange={(e) => write(specs.map((s, j) =>
              // Another set's properties are another type's: what was picked
              // for the old one is let go. p.280's Function aggregation
              // (§771) replaces the set altogether.
              (j === i ? { ...s,
                objectSetVariable: e.target.value && e.target.value !== FUNCTION_INPUT
                  ? e.target.value : null,
                dimension: null, measure: null, segmentBy: null,
                fn: e.target.value === FUNCTION_INPUT
                  ? { function_id: "", version: null, inputs: {} } : null } : s)))}
          >
            <option value="">The chart&apos;s set</option>
            {sets.filter((v) => v.id !== chartSet).map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
            <option value={FUNCTION_INPUT}>A function</option>
          </select>
          {spec.fn && (
            <FunctionLayerEditor
              label={`Series ${i + 2}`}
              layer={spec.fn}
              onChange={(fn) => write(specs.map((s, j) => (j === i ? { ...s, fn } : s)))}
            />
          )}
          {own && !spec.fn && (
            <select
              aria-label={`Series ${i + 2} X axis property`}
              data-testid="chart-series-dimension"
              value={spec.dimension ?? ""}
              onChange={(e) => write(specs.map((s, j) =>
                (j === i ? { ...s, dimension: e.target.value || null } : s)))}
            >
              <option value="">Group by…</option>
              {seriesNames.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          )}
          <select
            aria-label={`Series ${i + 2} type`}
            data-testid="chart-series-kind"
            value={spec.kind ?? ""}
            onChange={(e) => write(specs.map((s, j) => (j === i
              ? { ...s, kind: (LAYER_KINDS as readonly string[]).includes(e.target.value)
                  ? e.target.value as LayerKind : null }
              : s)))}
          >
            <option value="">As the chart</option>
            <option value="bar">Bar</option>
            <option value="line">Line</option>
            <option value="scatter">Scatter</option>
          </select>
          {!spec.fn && (<>
          <select
            aria-label={`Series ${i + 2} aggregation`}
            data-testid="chart-series-aggregate"
            value={spec.aggregate}
            onChange={(e) => write(specs.map((s, j) =>
              (j === i ? { ...s, aggregate: e.target.value } : s)))}
          >
            {Object.entries(PIE_AGGREGATIONS).map(([key, name]) => (
              <option key={key} value={key}>{name}</option>
            ))}
          </select>
          {spec.aggregate !== "count" && (
            <select
              aria-label={`Series ${i + 2} property`}
              data-testid="chart-series-measure"
              value={spec.measure ?? ""}
              onChange={(e) => write(specs.map((s, j) =>
                (j === i ? { ...s, measure: e.target.value || null } : s)))}
            >
              <option value="">Choose…</option>
              {(spec.aggregate === "count_distinct" ? seriesNames : seriesNumbers)
                .map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          )}
          </>)}
          {twoAxes && (
            <select
              aria-label={`Series ${i + 2} axis`}
              data-testid="chart-series-axis"
              value={spec.axis}
              onChange={(e) => write(specs.map((s, j) =>
                (j === i ? { ...s, axis: e.target.value === "left" ? "left" : "right" } : s)))}
            >
              <option value="left">Left axis</option>
              <option value="right">Right axis</option>
            </select>
          )}
          {/* p.282's Segment by on a layer (§678): a bar series that counts,
              which is what a segment is. */}
          {!spec.fn && (<>
          {canSegment(spec, chartKind) && (
            <select
              aria-label={`Series ${i + 2} segment by`}
              data-testid="chart-series-segment"
              value={spec.segmentBy ?? ""}
              onChange={(e) => write(specs.map((s, j) =>
                (j === i ? { ...s, segmentBy: e.target.value || null } : s)))}
            >
              <option value="">No segments</option>
              {seriesNames.map((n) => <option key={n} value={n}>Segment by {n}</option>)}
            </select>
          )}
          <select
            aria-label={`Series ${i + 2} selection filter`}
            data-testid="chart-series-drill"
            value={spec.drilldownVariable ?? ""}
            onChange={(e) => write(specs.map((s, j) =>
              (j === i ? { ...s, drilldownVariable: e.target.value || null } : s)))}
          >
            <option value="">Filters as the chart does</option>
            {clauses.map((v) => <option key={v.id} value={v.id}>Writes {v.label}</option>)}
          </select>
          </>)}
          <input
            type="text"
            aria-label={`Series ${i + 2} name`}
            data-testid="chart-series-name"
            placeholder={seriesNameOf({ ...spec, name: "" },
              sets.find((v) => v.id === ownSet(spec))?.label)}
            value={spec.name}
            onChange={(e) => write(specs.map((s, j) =>
              (j === i ? { ...s, name: e.target.value } : s)))}
          />
          <button
            type="button"
            className="btn quiet"
            data-testid="chart-series-remove"
            aria-label={`Remove series ${i + 2}`}
            onClick={() => write(specs.filter((_, j) => j !== i))}
          >
            ×
          </button>
        </div>
        );
      })}
      <button
        type="button"
        className="btn"
        data-testid="chart-add-series"
        disabled={specs.length >= MAX_SERIES - 1}
        onClick={() =>
          write([...specs, { title: "", aggregate: "count", measure: null, name: "", axis: "right",
                             objectSetVariable: null, dimension: null, kind: null,
                             drilldownVariable: null, segmentBy: null, fn: null }])}
      >
        Add a series
      </button>
      {specs.length > 0 && (
        <>
          <label className="field">
            <span className="field-label">First series name</span>
            <input
              type="text"
              data-testid="chart-series-first-name"
              placeholder={firstDefault}
              value={firstName}
              onChange={(e) => setProp((p) => (p.seriesName = e.target.value))}
            />
          </label>
          <label className="field canvas-toggle">
            <input
              type="checkbox"
              data-testid="chart-multiple-axes"
              checked={twoAxes}
              onChange={(e) => setProp((p) => (p.multipleAxes = e.target.checked))}
            />
            <span className="field-label">Use multiple value axes</span>
          </label>
          {twoAxes && (
            <ChartRightAxisFields
              values={rightAxis}
              fallback={rightAxisTitle(specs, axisSides(specs, true), chartKind)}
              setProp={setProp}
            />
          )}
          <label className="field canvas-toggle">
            <input
              type="checkbox"
              data-testid="chart-series-legend"
              checked={showLegend}
              onChange={(e) => setProp((p) => (p.showLegend = e.target.checked))}
            />
            <span className="field-label">Show legend</span>
          </label>
          {showLegend && (
            <label className="field">
              <span className="field-label">Legend position</span>
              <select
                data-testid="chart-series-legend-position"
                value={segmentLegendPositionOf(legend)}
                onChange={(e) => setProp((p) => (p.legendPosition = e.target.value))}
              >
                {Object.entries(SEGMENT_LEGEND_POSITIONS).map(([key, name]) => (
                  <option key={key} value={key}>{name}</option>
                ))}
              </select>
            </label>
          )}
        </>
      )}
    </div>
  );
}

/** p.284's legend position and p.282's display overrides for a segmented
 * chart (§539). The segments offered are the set's own values of the Segment
 * by property, most common first, as the cross-tab keeps them: a name typed
 * for a value that is not there would rename nothing. */
function SegmentLegendFields({ set, segmentBy, legend, names, setProp }: {
  set: unknown;
  segmentBy: string;
  legend: unknown;
  names: unknown;
  setProp: (fn: (p: Record<string, unknown>) => void) => void;
}) {
  const { workspaceId } = useCanvasEnv();
  const values = useQuery({
    queryKey: ["chart-segment-values", JSON.stringify(set ?? null), segmentBy],
    queryFn: () => objApi.groupObjectSet(workspaceId, set, segmentBy, {}),
    enabled: !!set,
  });
  const own = typeof names === "object" && names !== null && !Array.isArray(names)
    ? (names as Record<string, unknown>) : {};
  return (
    <>
      <label className="field">
        <span className="field-label">Legend position</span>
        <select
          data-testid="chart-legend-position"
          value={segmentLegendPositionOf(legend)}
          onChange={(e) => setProp((p) => (p.legendPosition = e.target.value))}
        >
          {Object.entries(SEGMENT_LEGEND_POSITIONS).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <div className="field">
        <span className="field-label">Segment names</span>
        {(values.data?.groups ?? []).slice(0, 12).map((g) => (
          <input
            key={g.value}
            type="text"
            data-testid="chart-segment-name"
            data-segment={g.value}
            aria-label={`Legend name for ${g.value}`}
            placeholder={g.value}
            value={typeof own[g.value] === "string" ? (own[g.value] as string) : ""}
            onChange={(e) => {
              const next = { ...own };
              if (e.target.value === "") delete next[g.value];
              else next[g.value] = e.target.value;
              setProp((p) => (p.segmentNames = next));
            }}
          />
        ))}
        <span className="field-hint">Blank keeps the value as its name</span>
      </div>
    </>
  );
}

/** p.283's "Use multiple value axes … allows value axes to be configured on
 * a per series basis" (§691): the right axis's own title, number format,
 * scale and bounds, as the left's are set in `ChartAxisFields`. */
function ChartRightAxisFields({ values, fallback, setProp }: {
  values: {
    showRightTitle?: unknown; rightTitle?: unknown; rightScaleType?: unknown;
    rightMinBound?: unknown; rightMaxBound?: unknown; rightValueFormat?: unknown;
  };
  fallback: string;
  setProp: (fn: (p: Record<string, unknown>) => void) => void;
}) {
  const read = valueAxisOf({
    scaleType: values.rightScaleType, minBound: values.rightMinBound,
    maxBound: values.rightMaxBound });
  const trouble = axisProblem(read);
  const bound = (key: "rightMinBound" | "rightMaxBound") =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setProp((p) => (p[key] = e.target.value === "" ? null : Number(e.target.value)));
  return (
    <fieldset className="field" data-testid="chart-right-axis">
      <legend className="field-label">Right value axis</legend>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          data-testid="chart-show-right-title"
          checked={values.showRightTitle === true}
          onChange={(e) => setProp((p) => (p.showRightTitle = e.target.checked))}
        />
        <span className="field-label">Show right axis title</span>
      </label>
      {values.showRightTitle === true && (
        <label className="field">
          <span className="field-label">Right axis title</span>
          <input
            type="text"
            data-testid="chart-right-title-input"
            value={typeof values.rightTitle === "string" ? values.rightTitle : ""}
            placeholder={fallback}
            onChange={(e) => setProp((p) => (p.rightTitle = e.target.value))}
          />
        </label>
      )}
      <ValueFormatField
        label="Right axis number format"
        testId="chart-right-format"
        value={values.rightValueFormat}
        hint="The right axis's ticks"
        onChange={(next) => setProp((p) => (p.rightValueFormat = next))}
      />
      <label className="field">
        <span className="field-label">Right axis scale</span>
        <select
          data-testid="chart-right-scale-type"
          value={read.scale}
          onChange={(e) => setProp((p) => (p.rightScaleType = e.target.value))}
        >
          {Object.entries(SCALE_TYPES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Right axis minimum bound</span>
        <input
          type="number"
          data-testid="chart-right-min-bound"
          value={read.min ?? ""}
          placeholder="Calculated from the values"
          onChange={bound("rightMinBound")}
        />
      </label>
      <label className="field">
        <span className="field-label">Right axis maximum bound</span>
        <input
          type="number"
          data-testid="chart-right-max-bound"
          value={read.max ?? ""}
          placeholder="Calculated from the values"
          onChange={bound("rightMaxBound")}
        />
        <span className="field-hint">
          {trouble ?? "For lines: bars on two axes start at zero on calculated axes."}
        </span>
      </label>
    </fieldset>
  );
}

/** p.283's value axis and axis titles in the Chart's panel (§536). */
function ChartAxisFields({ segmented, axis, titles, formats, defaults, setProp }: {
  segmented: boolean;
  axis: { scaleType?: unknown; minBound?: unknown; maxBound?: unknown };
  titles: {
    showCategoryTitle?: unknown; categoryTitle?: unknown;
    showValueTitle?: unknown; valueTitle?: unknown;
  };
  /** `keyed` is false where the categories are not a property's values: a
   * time series' instants, which have no number format to take. */
  formats: { value: unknown; category: unknown; keyed: boolean };
  defaults: { category: string; value: string };
  setProp: (fn: (p: Record<string, unknown>) => void) => void;
}) {
  const read = valueAxisOf(axis);
  const trouble = axisProblem(read);
  // An emptied number box is no bound: calculated. A half-typed "-" also
  // reads as "", and anything else that is not a number is read back as no
  // bound by `valueAxisOf`.
  const bound = (key: "minBound" | "maxBound") => (e: React.ChangeEvent<HTMLInputElement>) =>
    setProp((p) => (p[key] = e.target.value === "" ? null : Number(e.target.value)));
  const title = (show: "showCategoryTitle" | "showValueTitle", text: "categoryTitle" | "valueTitle",
    label: string, fallback: string, testid: string) => (
    <>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          data-testid={`chart-show-${testid}-title`}
          checked={titles[show] === true}
          onChange={(e) => setProp((p) => (p[show] = e.target.checked))}
        />
        <span className="field-label">Show {label} axis title</span>
      </label>
      {titles[show] === true && (
        <label className="field">
          <span className="field-label">{label.charAt(0).toUpperCase() + label.slice(1)} axis title</span>
          <input
            type="text"
            data-testid={`chart-${testid}-title-input`}
            value={typeof titles[text] === "string" ? (titles[text] as string) : ""}
            placeholder={fallback}
            onChange={(e) => setProp((p) => (p[text] = e.target.value))}
          />
        </label>
      )}
    </>
  );
  return (
    <>
      {title("showCategoryTitle", "categoryTitle", "category", defaults.category, "category")}
      {formats.keyed && (
        <ValueFormatField
          label="Category axis number format"
          testId="chart-category-format"
          value={formats.category}
          hint="Applies to category keys that are numbers"
          onChange={(next) => setProp((p) => (p.categoryFormat = next))}
        />
      )}
      {title("showValueTitle", "valueTitle", "value", defaults.value, "value")}
      <ValueFormatField
        label="Value axis number format"
        testId="chart-value-format"
        value={formats.value}
        hint="The axis's ticks and the value labels"
        onChange={(next) => setProp((p) => (p.valueFormat = next))}
      />
      {segmented ? (
        <p className="field-hint" data-testid="chart-axis-segmented">
          A segmented chart&apos;s value axis is calculated: a stack&apos;s height is the sum of
          its segments, which a logarithmic scale would not show.
        </p>
      ) : (
        <>
          <label className="field">
            <span className="field-label">Value axis scale</span>
            <select
              data-testid="chart-scale-type"
              value={read.scale}
              onChange={(e) => setProp((p) => (p.scaleType = e.target.value))}
            >
              {Object.entries(SCALE_TYPES).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Minimum bound</span>
            <input
              type="number"
              data-testid="chart-min-bound"
              value={read.min ?? ""}
              placeholder="Calculated from the values"
              onChange={bound("minBound")}
            />
          </label>
          <label className="field">
            <span className="field-label">Maximum bound</span>
            <input
              type="number"
              data-testid="chart-max-bound"
              value={read.max ?? ""}
              placeholder="Calculated from the values"
              onChange={bound("maxBound")}
            />
            {trouble && (
              <span className="field-hint" data-testid="chart-axis-problem-hint">{trouble}</span>
            )}
          </label>
        </>
      )}
    </>
  );
}

export function ActionFormSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    actionTypeId,
    subjectVariable,
    title,
    hideHeader,
    invalidState,
    outputVariable,
    moreActions,
    layout,
    layoutSwitch,
    prefillVariable,
    actions: { setProp },
  } = useNode((node) => ({
    actionTypeId: node.data.props.actionTypeId,
    moreActions: node.data.props.actions,
    subjectVariable: node.data.props.subjectVariable,
    title: node.data.props.title,
    hideHeader: node.data.props.hideHeader,
    invalidState: node.data.props.invalidState,
    outputVariable: node.data.props.outputVariable,
    layout: node.data.props.layout,
    layoutSwitch: node.data.props.layoutSwitch,
    prefillVariable: node.data.props.prefillVariable,
  }));
  const { declared } = useCanvasVariables();
  const objects = Object.values(declared).filter((v) => v.kind === "single_object");
  // **`array`, not `object_set`** — p.224's Object Table outputs took the same
  // decision for the same reason (§207): what this widget writes is the clause
  // list a `narrow_set` derivation reads, so the variable to bind is the array
  // in the middle. Offering the derived set would invite binding the thing that
  // is computed *from* this one and overwriting it on every submit.
  const clauseVariables = Object.values(declared).filter((v) => holdsClauses(v));
  const list = useQuery({
    queryKey: ["action-types", workspaceId],
    queryFn: () => actionApi.listTypes(workspaceId),
  });
  // So the panel can say whether the setting below is going to mean anything —
  // an action with no criteria can never be invalid, and a control that is
  // permanently inert should say so rather than look configurable.
  const chosenAction = list.data?.find((a) => a.id === actionTypeId) ?? null;
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
      {/* p.512's "Select Add item to include multiple actions, each requiring
          individual configuration" (§556). With any, the form opens on a
          selection menu. */}
      {moreActionsOf(moreActions).map((more, index) => (
        <div key={index} className="field" data-testid={`action-form-more-${index}`}>
          <span className="field-label">Action {index + 2}</span>
          <select
            aria-label={`Action ${index + 2}`}
            value={more.actionTypeId ?? ""}
            onChange={(e) => setProp((p: { actions: unknown }) => {
              p.actions = withMoreAction(p.actions, index, { actionTypeId: e.target.value || null });
            })}
          >
            <option value="">Choose…</option>
            {list.data?.map((a) => (
              <option key={a.id} value={a.id}>{a.display_name}</option>
            ))}
          </select>
          <input
            type="text"
            aria-label={`Action ${index + 2} title`}
            value={more.title}
            placeholder="the action's own name"
            onChange={(e) => setProp((p: { actions: unknown }) => {
              p.actions = withMoreAction(p.actions, index, { title: e.target.value });
            })}
          />
          <button
            type="button"
            className="btn quiet"
            aria-label={`Remove action ${index + 2}`}
            onClick={() => setProp((p: { actions: unknown }) => {
              p.actions = withoutMoreAction(p.actions, index);
            })}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn quiet"
        data-testid="action-form-add-item"
        onClick={() => setProp((p: { actions: unknown }) => {
          p.actions = withAddedAction(p.actions);
        })}
      >
        Add item
      </button>
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
      <label className="field">
        <span className="field-label">Action title</span>
        <input
          type="text"
          value={title ?? ""}
          placeholder="the action's own name"
          data-testid="action-form-title-input"
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      <label className="field canvas-toggle">
        <input
          type="checkbox"
          checked={hideActionHeaderOf(hideHeader)}
          data-testid="action-form-hide-header"
          onChange={(e) =>
            setProp((p: { hideHeader: boolean }) => (p.hideHeader = e.target.checked))}
        />
        <span className="field-label">Hide header</span>
      </label>
      <label className="field">
        <span className="field-label">Default layout</span>
        <select
          value={layout === "table" ? "table" : "form"}
          data-testid="action-form-layout"
          onChange={(e) => setProp((p: { layout: string }) => (p.layout = e.target.value))}
        >
          <option value="form">Action form</option>
          <option value="table">Action table</option>
        </select>
        <span className="field-hint">
          {(chosenAction?.table_refusals ?? []).length > 0
            ? `Only as a form: ${(chosenAction?.table_refusals ?? []).join("; ")}`
            : "A table submits a row per object, after checking every row"}
        </span>
      </label>
      <label className="field" style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
        <input
          type="checkbox"
          checked={!!layoutSwitch}
          data-testid="action-form-layout-switch"
          onChange={(e) =>
            setProp((p: { layoutSwitch: boolean }) => (p.layoutSwitch = e.target.checked))}
        />
        <span className="field-label">Let readers switch layout</span>
      </label>
      <label className="field">
        <span className="field-label">Pre-fill rows from</span>
        <select
          value={prefillVariable ?? ""}
          data-testid="action-form-prefill"
          onChange={(e) => setProp((p: { prefillVariable: string | null }) =>
            (p.prefillVariable = e.target.value || null))}
        >
          <option value="">Nothing - rows are added by hand</option>
          {Object.values(declared).filter((v) => v.kind === "object_set").map((v) => (
            <option key={v.id} value={v.id}>{v.label || v.id}</option>
          ))}
        </select>
        <span className="field-hint">
          Table only (p.512): each object in the set becomes a row. Its object type must
          be this action's.
        </span>
      </label>
      <label className="field">
        <span className="field-label">Form state if invalid</span>
        <select
          value={invalidStateOf(invalidState)}
          data-testid="action-form-invalid-state"
          onChange={(e) =>
            setProp((p: { invalidState: string }) => (p.invalidState = e.target.value))}
        >
          {Object.entries(INVALID_STATES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
        <span className="field-hint">
          {(chosenAction?.criteria ?? []).length > 0
            ? "Checked against this action's submission criteria before anything is written"
            : "This action has no submission criteria, so it is never invalid"}
        </span>
      </label>
      </>}
      outputs={<>
      <label className="field">
        <span className="field-label">Output object set</span>
        <select
          value={outputVariable || ""}
          data-testid="action-form-output"
          onChange={(e) =>
            setProp((p: { outputVariable: string | null }) =>
              (p.outputVariable = e.target.value || null))}
        >
          <option value="">Not bound</option>
          {clauseVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">
          {clauseVariables.length === 0
            ? "Declare an array variable, and derive a narrowed set from it"
            : "The objects each submission creates or modifies, as clauses to narrow a set with"}
        </span>
      </label>
      </>}
    />
  );
}

/**
 * p.174's value formatting as one settings control: a button showing what the
 * formatter does to a number, and §157's dialog behind it.
 *
 * **§157's editor, not a second one** (§191). It already carries p.97-98's
 * whole option list and p.96's live preview, and a Workshop copy would be a
 * second place for "max fraction digits" to mean something slightly different.
 * `dataType` is `float` because both of p.174's surfaces are numbers: that is
 * the editor's switch between p.97's numeric options and p.99's temporal ones,
 * and a datetime formatter on either surface would format nothing.
 *
 * **Mounted only while open**, because the dialog seeds its draft from `value`
 * once at mount. Kept mounted, a formatter cancelled and reopened would still
 * show the abandoned draft.
 *
 * The button's face is the formatter's *effect* rather than its fields, on
 * p.329's own example - "setting the maximum fraction digits to 2 displays
 * 3.14159 as 3.14". Nobody reads "maximumFractionDigits: 2" and pictures that.
 */
function ValueFormatField({
  label,
  testId,
  value,
  onChange,
  hint,
}: {
  label: string;
  testId: string;
  value: unknown;
  onChange: (next: NumberFormat | null) => void;
  hint?: string;
}) {
  const [open, setOpen] = useState(false);
  const format = numberFormatOf(value);
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <button
        type="button"
        className="btn"
        data-testid={testId}
        onClick={() => setOpen(true)}
      >
        {formatSummary(format)}
      </button>
      {hint && <span className="field-hint">{hint}</span>}
      {open && (
        <ValueFormatEditor
          open
          onClose={() => setOpen(false)}
          propertyName={label}
          dataType="float"
          value={format}
          onSave={(next) => onChange(next as NumberFormat | null)}
        />
      )}
    </div>
  );
}

/**
 * p.175's conditional formatting as one settings control, the way
 * `ValueFormatField` is p.174's: a button saying how many rules there are, and
 * §158's dialog behind it.
 *
 * **§158's editor, not a Workshop one** (§191, §292). It carries p.105's whole
 * rule grammar, the ordering controls that make the Always-true fallback mean
 * anything, and p.106's preview — and a second copy would be a second place
 * for "first match wins" to be implemented.
 *
 * `properties` is one entry rather than a type's whole property list, because
 * a rule here has exactly one thing it can read: the number the widget is
 * showing. Offering more would be offering a comparison against a property the
 * evaluator is never given.
 */
function ConditionalFormatField({
  subject,
  testId,
  value,
  onChange,
  hint,
}: {
  subject: string;
  testId: string;
  value: unknown;
  onChange: (next: ConditionalRule[] | null) => void;
  hint?: string;
}) {
  const [open, setOpen] = useState(false);
  const rules = rulesOf(value);
  return (
    <div className="field">
      <span className="field-label">Conditional formatting</span>
      <button
        type="button"
        className="btn"
        data-testid={testId}
        onClick={() => setOpen(true)}
      >
        {/* The count rather than "Configured": the list is ordered and
            first-match-wins, so how many there are is the thing an author is
            actually keeping track of. */}
        {rules ? `${rules.length} rule${rules.length === 1 ? "" : "s"}` : "No rules"}
      </button>
      {hint && <span className="field-hint">{hint}</span>}
      {open && (
        <ConditionalFormatEditor
          open
          onClose={() => setOpen(false)}
          propertyName={subject}
          properties={subjectProperties(subject)}
          value={rules}
          onSave={onChange}
        />
      )}
    </div>
  );
}

export function MetricCardSettings() {
  const { workspaceId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    objectSetVariable, aggregation, property, label,
    showVisualization, visualizationPosition, seriesVariable, valueFormat,
    valueRules, size, description, sparkRange, sparkStart, sparkEnd, baseline,
    showSecondary, secondaryLabel, secondaryAggregation, secondaryProperty, secondaryFormat,
    metrics, layoutStyle, direction, template,
    sparkAgo, sparkAgoUnit, sparkAhead, sparkAheadUnit, baselineKind, baselineSummary, baselineProperty,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    aggregation: node.data.props.aggregation,
    property: node.data.props.property,
    label: node.data.props.label,
    valueFormat: node.data.props.valueFormat,
    valueRules: node.data.props.valueRules,
    showVisualization: node.data.props.showVisualization,
    visualizationPosition: node.data.props.visualizationPosition,
    seriesVariable: node.data.props.seriesVariable,
    size: node.data.props.size,
    description: node.data.props.description,
    sparkRange: node.data.props.sparkRange,
    sparkStart: node.data.props.sparkStart,
    sparkEnd: node.data.props.sparkEnd,
    baseline: node.data.props.baseline,
    showSecondary: node.data.props.showSecondary,
    secondaryLabel: node.data.props.secondaryLabel,
    secondaryAggregation: node.data.props.secondaryAggregation,
    secondaryProperty: node.data.props.secondaryProperty,
    secondaryFormat: node.data.props.secondaryFormat,
    metrics: node.data.props.metrics,
    layoutStyle: node.data.props.layoutStyle,
    direction: node.data.props.direction,
    template: node.data.props.template,
    sparkAgo: node.data.props.sparkAgo,
    sparkAgoUnit: node.data.props.sparkAgoUnit,
    sparkAhead: node.data.props.sparkAhead,
    sparkAheadUnit: node.data.props.sparkAheadUnit,
    baselineKind: node.data.props.baselineKind,
    baselineSummary: node.data.props.baselineSummary,
    baselineProperty: node.data.props.baselineProperty,
  }));
  const kindOfBaseline = baselineKindOf(baselineKind, baseline);
  const extras = extraMetricsOf(metrics);
  const setExtras = (next: ExtraMetric[]) => setProp((p: { metrics: ExtraMetric[] }) => (p.metrics = next));
  const arrangement = metricLayoutSettings(layoutStyle);
  const rangeProblem = metricSparkRangeProblem(sparkRange, sparkStart, sparkEnd);
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
  // p.329: "Time series set: The time series that is to be visualized. This is
  // specified using a Time series set variable". Only those - offering the
  // rest would be a choice that fails at read time.
  const seriesVariables = Object.values(declared).filter(
    (v) => v.kind === "time_series_set",
  );
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
      {/* p.328: "Sets optional description text for the metric. This
          description text is displayed as a tooltip". */}
      <label className="field">
        <span className="field-label">Description</span>
        <input
          value={(description as string) ?? ""}
          data-testid="metric-description-input"
          onChange={(e) => setProp((p: { description: string }) => (p.description = e.target.value))}
        />
      </label>
      {/* p.326: "Sets the display size for every metric in the widget." */}
      <label className="field">
        <span className="field-label">Size</span>
        <select
          value={metricSizeOf(size)}
          data-testid="metric-size"
          onChange={(e) => setProp((p: { size: string }) => (p.size = e.target.value))}
        >
          {Object.entries(METRIC_SIZES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Shows</span>
        <select
          value={metricAggregationOf(aggregation)}
          data-testid="metric-aggregation"
          onChange={(e) =>
            setProp((p: { aggregation: string }) => (p.aggregation = e.target.value))
          }
        >
          {Object.entries(METRIC_AGGREGATIONS).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      {metricNeedsProperty(aggregation) && (
        <label className="field">
          <span className="field-label">Of property</span>
          <select
            value={property || ""}
            data-testid="metric-property"
            onChange={(e) =>
              setProp((p: { property: string | null }) => (p.property = e.target.value || null))
            }
          >
            <option value="">Choose…</option>
            {/* **Two different lists.** A distinct count is a text-identity
                question and works on any property; the four numeric ones are
                arithmetic and the server takes only an integer or a float. */}
            {metricPropertiesFor(aggregation, detail.data?.properties ?? []).map((prop) => (
              <option key={prop.api_name} value={prop.api_name}>{prop.api_name}</option>
            ))}
          </select>
        </label>
      )}
      {/* p.328's **Numeric formatting**: "This optional configuration is only
          available for the Number value type… specify a value formatting
          scheme to display the numeric value", and it points at p.174. In
          p.328's own order, directly under the value it formats. */}
      <ValueFormatField
        label="Numeric formatting"
        testId="metric-value-format"
        value={valueFormat}
        hint="Local to this module — the ontology is unchanged (p.174)."
        onChange={(next) =>
          setProp((p: { valueFormat: NumberFormat | null }) => (p.valueFormat = next))
        }
      />
      {/* p.329's **Conditional formatting**, in p.328-329's own order: under
          Numeric formatting, above Show secondary metric. */}
      <ConditionalFormatField
        subject={METRIC_SUBJECT}
        testId="metric-value-rules"
        value={valueRules}
        hint="Paints the number, and the sparkline with it (p.175)."
        onChange={(next) =>
          setProp((p: { valueRules: ConditionalRule[] | null }) => (p.valueRules = next))
        }
      />
      {/* p.326's layout style, and the arrangement each style has (§533). */}
      <label className="field">
        <span className="field-label">Layout</span>
        <select
          value={metricLayoutStyleOf(layoutStyle)}
          data-testid="metric-layout"
          onChange={(e) => setProp((p: { layoutStyle: string }) => (p.layoutStyle = e.target.value))}
        >
          {Object.entries(METRIC_LAYOUT_STYLES).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
        {!sparkAllowedIn(layoutStyle) && showVisualization === true && (
          <span className="field-hint" data-testid="metric-layout-no-spark">
            Sparklines show only in the Card layout (p.326).
          </span>
        )}
      </label>
      {arrangement.direction && (
        <label className="field">
          <span className="field-label">Direction</span>
          <select
            value={metricDirectionOf(direction)}
            data-testid="metric-direction"
            onChange={(e) => setProp((p: { direction: string }) => (p.direction = e.target.value))}
          >
            {Object.entries(METRIC_DIRECTIONS).map(([key, name]) => (
              <option key={key} value={key}>{name}</option>
            ))}
          </select>
        </label>
      )}
      {arrangement.template && (
        <label className="field">
          <span className="field-label">Template</span>
          <select
            value={metricTemplateOf(template)}
            data-testid="metric-template"
            onChange={(e) => setProp((p: { template: string }) => (p.template = e.target.value))}
          >
            {Object.entries(METRIC_TEMPLATES).map(([key, name]) => (
              <option key={key} value={key}>{name}</option>
            ))}
          </select>
        </label>
      )}
      {/* p.325's Metrics: "The Add Metric button adds a new metric … The Up
          and Down direction arrows on the metrics in the list change the
          order". The card's own metric is the first; these follow it. */}
      <div className="field" data-testid="metric-extras">
        <span className="field-label">More metrics</span>
        {extras.map((extra, index) => (
          <div key={extra.id} className="card" data-testid="metric-extra-settings"
               style={{ padding: 6, margin: "4px 0" }}>
            <input
              aria-label={`Metric ${index + 2} label`}
              placeholder={metricLabelOf({ label: "", aggregation: extra.aggregation })}
              value={extra.label}
              onChange={(e) => setExtras(extras.map((m, i) => (i === index ? { ...m, label: e.target.value } : m)))}
            />
            <select
              aria-label={`Metric ${index + 2} shows`}
              value={extra.aggregation}
              onChange={(e) => setExtras(extras.map((m, i) => (i === index ? { ...m, aggregation: e.target.value } : m)))}
            >
              {Object.entries(METRIC_AGGREGATIONS).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
            {metricNeedsProperty(extra.aggregation) && (
              <select
                aria-label={`Metric ${index + 2} property`}
                value={extra.property ?? ""}
                onChange={(e) => setExtras(extras.map((m, i) => (
                  i === index ? { ...m, property: e.target.value || null } : m)))}
              >
                <option value="">Choose…</option>
                {metricPropertiesFor(extra.aggregation, detail.data?.properties ?? []).map((prop) => (
                  <option key={prop.api_name} value={prop.api_name}>{prop.api_name}</option>
                ))}
              </select>
            )}
            <span className="row-actions" style={{ gap: 4 }}>
              <button type="button" className="btn quiet" aria-label={`Move metric ${index + 2} up`}
                      disabled={index === 0} onClick={() => setExtras(moveMetric(extras, index, -1))}>
                ↑
              </button>
              <button type="button" className="btn quiet" aria-label={`Move metric ${index + 2} down`}
                      disabled={index === extras.length - 1}
                      onClick={() => setExtras(moveMetric(extras, index, 1))}>
                ↓
              </button>
              <button type="button" className="btn quiet" aria-label={`Remove metric ${index + 2}`}
                      onClick={() => setExtras(extras.filter((_, i) => i !== index))}>
                Remove
              </button>
            </span>
          </div>
        ))}
        <button type="button" className="btn quiet" data-testid="metric-add"
                onClick={() => setExtras(addMetric(extras))}>
          Add metric
        </button>
      </div>
      {/* p.329's "Show secondary metric?", in p.329's order: above Show
          visualization. Its configuration "mimics the configuration for the
          primary metric" (§528). */}
      <label className="vars-toggle">
        <input
          type="checkbox"
          checked={showSecondary === true}
          data-testid="metric-show-secondary"
          onChange={(e) =>
            setProp((p: { showSecondary: boolean }) => (p.showSecondary = e.target.checked))
          }
        />
        Show a secondary metric
      </label>
      {showSecondary === true && (
        <>
          <label className="field">
            <span className="field-label">Secondary label</span>
            <input
              value={(secondaryLabel as string) ?? ""}
              data-testid="metric-secondary-label"
              placeholder={metricSecondaryLabelOf("", secondaryAggregation)}
              onChange={(e) =>
                setProp((p: { secondaryLabel: string }) => (p.secondaryLabel = e.target.value))
              }
            />
          </label>
          <label className="field">
            <span className="field-label">Secondary shows</span>
            <select
              value={metricAggregationOf(secondaryAggregation)}
              data-testid="metric-secondary-aggregation"
              onChange={(e) =>
                setProp((p: { secondaryAggregation: string }) => (p.secondaryAggregation = e.target.value))
              }
            >
              {Object.entries(METRIC_AGGREGATIONS).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </label>
          {metricNeedsProperty(secondaryAggregation) && (
            <label className="field">
              <span className="field-label">Of property</span>
              <select
                value={(secondaryProperty as string) || ""}
                data-testid="metric-secondary-property"
                onChange={(e) =>
                  setProp((p: { secondaryProperty: string | null }) =>
                    (p.secondaryProperty = e.target.value || null))
                }
              >
                <option value="">Choose…</option>
                {metricPropertiesFor(secondaryAggregation, detail.data?.properties ?? []).map((prop) => (
                  <option key={prop.api_name} value={prop.api_name}>{prop.api_name}</option>
                ))}
              </select>
            </label>
          )}
          <ValueFormatField
            label="Secondary formatting"
            testId="metric-secondary-format"
            value={secondaryFormat}
            hint="Local to this module — the ontology is unchanged (p.174)."
            onChange={(next) =>
              setProp((p: { secondaryFormat: NumberFormat | null }) => (p.secondaryFormat = next))
            }
          />
        </>
      )}
      {/* p.329's "Show visualization?" - "An optional configuration to display
          a sparkline depicting the history of a time series with the metric.
          Setting this toggle to Yes opens a configuration screen with the
          following options". The two options appear only once it is on, which
          is what "opens a configuration screen" describes. */}
      <label className="vars-toggle">
        <input
          type="checkbox"
          checked={showVisualization === true}
          data-testid="metric-show-visualization"
          onChange={(e) =>
            setProp((p: { showVisualization: boolean }) =>
              (p.showVisualization = e.target.checked))
          }
        />
        Show a sparkline
      </label>
      {showVisualization === true && (
        <>
          <label className="field">
            <span className="field-label">Time series set</span>
            <select
              value={(seriesVariable as string) || ""}
              data-testid="metric-series-variable"
              onChange={(e) =>
                setProp((p: { seriesVariable: string | null }) =>
                  (p.seriesVariable = e.target.value || null))
              }
            >
              <option value="">Choose…</option>
              {seriesVariables.map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
            {seriesVariables.length === 0 && (
              // Named rather than left as an empty dropdown: the variable this
              // needs is a kind somebody has to declare first, and an empty
              // list looks like a bug rather than a missing step.
              <span className="field-hint">
                This module has no time series set variables yet.
              </span>
            )}
          </label>
          <label className="field">
            <span className="field-label">Position</span>
            <select
              value={metricSparkPositionOf(visualizationPosition)}
              data-testid="metric-spark-position"
              onChange={(e) =>
                setProp((p: { visualizationPosition: string }) =>
                  (p.visualizationPosition = e.target.value))
              }
            >
              {Object.entries(SPARK_POSITIONS).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </label>
          {/* p.330: "Time range: Specifies the time range for which data should
              be displayed." Last hour, day and week count back from when the
              page first needed the time (p.591). */}
          <label className="field">
            <span className="field-label">Time range</span>
            <select
              value={metricSparkRangeOf(sparkRange)}
              data-testid="metric-spark-range"
              onChange={(e) => setProp((p: { sparkRange: string }) => (p.sparkRange = e.target.value))}
            >
              {Object.entries(SPARK_RANGES).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </label>
          {metricSparkRangeOf(sparkRange) === "custom" && (
            <>
              <label className="field">
                <span className="field-label">From (UTC)</span>
                <input
                  type="datetime-local"
                  data-testid="metric-spark-start"
                  value={(sparkStart as string) ?? ""}
                  onChange={(e) => setProp((p: { sparkStart: string | null }) =>
                    (p.sparkStart = e.target.value || null))}
                />
              </label>
              <label className="field">
                <span className="field-label">To (UTC)</span>
                <input
                  type="datetime-local"
                  data-testid="metric-spark-end"
                  value={(sparkEnd as string) ?? ""}
                  onChange={(e) => setProp((p: { sparkEnd: string | null }) =>
                    (p.sparkEnd = e.target.value || null))}
                />
              </label>
              {rangeProblem && (
                <span className="field-hint" data-testid="metric-spark-range-problem">{rangeProblem}</span>
              )}
            </>
          )}
          {metricSparkRangeOf(sparkRange) === "relative" && (
            /* p.591: "The relative option specifies the start and end of a
               window relative to the current time." */
            <>
              <label className="field">
                <span className="field-label">From</span>
                <span className="row-actions" style={{ gap: 4 }}>
                  <input type="number" min={0} data-testid="metric-spark-ago"
                         value={sparkAgo === null || sparkAgo === undefined ? "" : String(sparkAgo)}
                         onChange={(e) => setProp((p: { sparkAgo: number | null }) =>
                           (p.sparkAgo = e.target.value === "" ? null : Number(e.target.value)))} />
                  <select data-testid="metric-spark-ago-unit" value={(sparkAgoUnit as string) ?? "week"}
                          onChange={(e) => setProp((p: { sparkAgoUnit: string }) => (p.sparkAgoUnit = e.target.value))}>
                    {Object.keys(RELATIVE_UNITS).map((u) => <option key={u} value={u}>{u}s ago</option>)}
                  </select>
                </span>
              </label>
              <label className="field">
                <span className="field-label">To</span>
                <span className="row-actions" style={{ gap: 4 }}>
                  <input type="number" min={0} data-testid="metric-spark-ahead"
                         value={sparkAhead === null || sparkAhead === undefined ? "" : String(sparkAhead)}
                         onChange={(e) => setProp((p: { sparkAhead: number | null }) =>
                           (p.sparkAhead = e.target.value === "" ? null : Number(e.target.value)))} />
                  <select data-testid="metric-spark-ahead-unit" value={(sparkAheadUnit as string) ?? "day"}
                          onChange={(e) => setProp((p: { sparkAheadUnit: string }) => (p.sparkAheadUnit = e.target.value))}>
                    {Object.keys(RELATIVE_UNITS).map((u) => <option key={u} value={u}>{u}s from now</option>)}
                  </select>
                </span>
                <span className="field-hint">Empty is no end. Counted from when the page opened (p.591).</span>
              </label>
            </>
          )}
          {/* p.330's Baseline, with p.592's Static and Time series types
              (§526, §534). Numeric property is ○: the card does not read the
              object's own properties. */}
          <label className="field">
            <span className="field-label">Baseline</span>
            <select
              data-testid="metric-spark-baseline-kind"
              value={kindOfBaseline}
              onChange={(e) => setProp((p: { baselineKind: string }) => (p.baselineKind = e.target.value))}
            >
              {Object.entries(BASELINE_KINDS).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </label>
          {kindOfBaseline === "static" && (
            <label className="field">
              <span className="field-label">Baseline value</span>
              <input
                type="number"
                data-testid="metric-spark-baseline"
                value={baseline === null || baseline === undefined ? "" : String(baseline)}
                onChange={(e) => setProp((p: { baseline: number | null }) =>
                  (p.baseline = e.target.value === "" ? null : Number(e.target.value)))}
              />
              <span className="field-hint">A dotted line at this value, beside the sparkline.</span>
            </label>
          )}
          {kindOfBaseline === "series" && (
            <label className="field">
              <span className="field-label">Baseline is the series&apos;</span>
              <select
                data-testid="metric-spark-baseline-summary"
                value={(baselineSummary as string) ?? "last"}
                onChange={(e) => setProp((p: { baselineSummary: string }) => (p.baselineSummary = e.target.value))}
              >
                {Object.entries(BASELINE_SUMMARIES).map(([key, name]) => (
                  <option key={key} value={key}>{name}</option>
                ))}
              </select>
              <span className="field-hint">p.592: e.g. &quot;the most recent observation in the time series&quot;.</span>
            </label>
          )}
          {kindOfBaseline === "property" && (
            <label className="field">
              <span className="field-label">Baseline property</span>
              <input
                data-testid="metric-spark-baseline-property"
                value={(baselineProperty as string | null) ?? ""}
                placeholder="e.g. capacity"
                onChange={(e) => setProp((p: { baselineProperty: string | null }) =>
                  (p.baselineProperty = e.target.value || null))}
              />
              <span className="field-hint">
                p.593: a numeric property of the object the series is of. Typed, since which
                type that is depends on the variable&apos;s object.
              </span>
            </label>
          )}
        </>
      )}
      </>}
    />
  );
}

export function SectionSettings() {
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
    dropHandling,
    dropLabel,
    dropIcon,
    dropVariable,
    showHeader,
    headerIcon,
    description,
    headerStyle,
    headerWidgets,
    childCount,
    actions: { setProp },
  } = useNode((node) => ({
    headerWidgets: node.data.props.headerWidgets,
    childCount: (node.data.nodes ?? []).length,
    showHeader: node.data.props.showHeader,
    headerIcon: node.data.props.headerIcon,
    description: node.data.props.description,
    headerStyle: node.data.props.headerStyle,
    dropHandling: node.data.props.dropHandling,
    dropLabel: node.data.props.dropLabel,
    dropIcon: node.data.props.dropIcon,
    dropVariable: node.data.props.dropVariable,
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
      {/* p.13's Section Header (§473), before Collapsible because p.13
          toggles them in that order and a collapsible section's control is
          its header. */}
      <label className="vars-toggle field">
        <input
          type="checkbox"
          checked={showHeader === true}
          data-testid="section-show-header"
          onChange={(e) => setProp((p: { showHeader: boolean }) => (p.showHeader = e.target.checked))}
        />
        Section header
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
      {(collapsible || showHeader === true) && (
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
      )}
      {showHeader === true && (
        <>
          <label className="field">
            <span className="field-label">Header icon</span>
            <IconChoice
              value={headerIcon}
              placeholder="◎"
              testId="section-header-icon"
              onChange={(next) => setProp((p: { headerIcon: string }) => (p.headerIcon = next))}
            />
          </label>
          <label className="field">
            <span className="field-label">Description</span>
            <input
              value={description ?? ""}
              data-testid="section-description"
              onChange={(e) => setProp((p: { description: string }) => (p.description = e.target.value))}
            />
            <span className="field-hint">A subheading under the title (p.28)</span>
          </label>
          <label className="field">
            <span className="field-label">Header format</span>
            <select
              value={headerStyleOf(headerStyle)}
              data-testid="section-header-style"
              onChange={(e) => setProp((p: { headerStyle: string }) => (p.headerStyle = e.target.value))}
            >
              {Object.entries(HEADER_STYLES).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Widgets in the header</span>
            <input
              type="number"
              min={0}
              max={childCount}
              value={headerCount(headerWidgets, childCount, true)}
              data-testid="section-header-widgets"
              onChange={(e) => {
                const next = Number(e.target.value);
                setProp((p: { headerWidgets: number }) => (p.headerWidgets = next));
              }}
            />
            <span className="field-hint">
              The first widgets in this section, in layer order, sit on the
              right of its header - a Button Group or a count (p.14, p.44)
            </span>
          </label>
        </>
      )}
      {collapsible && (
        <>
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
      {/* p.564-568, in p.565-568's order: the toggle, then how the zone looks
          while something is over it, then where the dropped data goes. */}
      <label className="vars-toggle field">
        <input
          type="checkbox"
          checked={!!dropHandling}
          data-testid="section-drop-handling"
          onChange={(e) =>
            setProp((p: { dropHandling: boolean }) => (p.dropHandling = e.target.checked))}
        />
        Drop Handling
      </label>
      {dropHandling && (
        <>
          <label className="field">
            <span className="field-label">Drop label</span>
            <input
              value={dropLabel ?? ""}
              placeholder="Drop here"
              data-testid="section-drop-label"
              onChange={(e) => setProp((p: { dropLabel: string }) => (p.dropLabel = e.target.value))}
            />
          </label>
          <label className="field">
            <span className="field-label">Drop icon</span>
            <IconChoice
              value={dropIcon}
              placeholder="+"
              max={4}
              testId="section-drop-icon"
              onChange={(next) => setProp((p: { dropIcon: string }) => (p.dropIcon = next))}
            />
          </label>
          <label className="field">
            <span className="field-label">Output object set</span>
            <select
              value={dropVariable ?? ""}
              data-testid="section-drop-variable"
              onChange={(e) =>
                setProp((p: { dropVariable: string | null }) =>
                  (p.dropVariable = e.target.value || null))}
            >
              <option value="">None — only fire the On drop event</option>
              {Object.values(declared)
                .filter((v) => holdsClauses(v))
                .map((v) => (
                  <option key={v.id} value={v.id}>{v.label || v.id}</option>
                ))}
            </select>
            {/* The same currency as the Object Table's outputs, and the same
                instruction for turning it into a set. */}
            <span className="field-hint">
              Holds the dropped objects as clauses; derive an object set from it
              with narrow set. Objects of another type narrow it to nothing.
              Add an On drop event in the Events panel.
            </span>
          </label>
        </>
      )}
      <NodeStyleFields padding border />
      <InheritedSectionStyle />
      <InnerSectionStyleField />
    </>
  );
}

/** p.47's "upload one from your computer", as an attachment (§39): the same
 * upload an object's attachment property uses, so the header holds a storage
 * key and the download route's permission check stands between it and the
 * bytes. */
function HeaderImageField({ label, testId, value, onChange }: {
  label: string;
  testId: string;
  value: ImageRef | null;
  onChange: (next: ImageRef | null) => void;
}) {
  const { workspaceId } = useCanvasEnv();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      {value ? (
        <div className="row-actions">
          <span className="slug" data-testid={`${testId}-name`}>{value.filename || "image"}</span>
          <button type="button" className="btn quiet" onClick={() => onChange(null)}>
            Remove
          </button>
        </div>
      ) : (
        <input
          type="file"
          accept="image/*"
          data-testid={testId}
          disabled={busy}
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setBusy(true);
            setError(null);
            try {
              const uploaded = imageRefOf(await objApi.uploadAttachment(workspaceId, file));
              // Checked on the way back as well as by `accept`, which a file
              // dialog lets anybody override.
              if (!uploaded) setError("That is not an image.");
              else onChange(uploaded);
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Couldn't upload the image.");
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
      {error && <span className="field-hint" role="alert">{error}</span>}
    </div>
  );
}

export function HeaderSettings() {
  const {
    title, sticky, orientation, height, width, collapsible, collapsedByDefault,
    titleColour, allowFavourite, icon, iconColour,
    logoImage, logoHeight, logoPosition, collapsedImage,
    actions: { setProp },
  } = useNode((node) => ({
    logoImage: node.data.props.logoImage,
    logoHeight: node.data.props.logoHeight,
    logoPosition: node.data.props.logoPosition,
    collapsedImage: node.data.props.collapsedImage,
    title: node.data.props.title,
    sticky: node.data.props.sticky,
    orientation: node.data.props.orientation,
    height: node.data.props.height,
    width: node.data.props.width,
    collapsible: node.data.props.collapsible,
    collapsedByDefault: node.data.props.collapsedByDefault,
    titleColour: node.data.props.titleColour,
    allowFavourite: node.data.props.allowFavourite,
    icon: node.data.props.icon,
    iconColour: node.data.props.iconColour,
  }));
  const vertical = orientation === "vertical";
  const { palette, scheme } = useSavedColours();
  const titleChoice = textColourChoice(titleColour, palette);
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
      {/* p.47's application logo, above the title because that is the order
          it appears in. **One or two characters**, which is the divergence
          this platform already takes for a Button and a Page — and the hint
          says so, because somebody expecting a picker should find out here
          rather than by typing a word and watching it cut in half (§337). */}
      <label className="field">
        <span className="field-label">Logo</span>
        <IconChoice
          value={icon}
          placeholder="◎"
          testId="header-icon"
          onChange={(next) => setProp((p: { icon: string }) => (p.icon = next))}
        />
        <span className="field-hint">
          An icon, or one or two characters — an emoji or an initial. It stays
          visible when a vertical header is collapsed.
        </span>
      </label>
      {icon?.trim() && (
        <label className="field">
          <span className="field-label">Logo colour</span>
          <select
            data-testid="header-icon-colour"
            value={textColourChoice(iconColour, palette)}
            onChange={(e) =>
              setProp((p: { iconColour: string | null }) => {
                p.iconColour =
                  e.target.value === "default"
                    ? null
                    : e.target.value === "custom"
                      ? resolveBackground(iconColour, { palette, scheme }) ?? "#16232f"
                      : e.target.value;
              })
            }
          >
            <option value="default">Default — follows the theme</option>
            {palette.length > 0 && (
              <optgroup label="Saved colours">
                {palette.map((colour) => (
                  <option key={colour.id} value={refTo(colour.id)}>{colour.name}</option>
                ))}
              </optgroup>
            )}
            <option value="custom">Custom…</option>
          </select>
        </label>
      )}
      {textColourChoice(iconColour, palette) === "custom" && (
        <label className="field">
          <span className="field-label">Logo colour (hex)</span>
          <input
            type="text"
            data-testid="header-icon-colour-hex"
            value={iconColour ?? ""}
            placeholder="#16232f"
            onChange={(e) =>
              setProp((p: { iconColour: string }) => (p.iconColour = e.target.value))}
          />
        </label>
      )}
      {/* p.47's Image, beside the icon it replaces. */}
      <HeaderImageField
        label="Logo image"
        testId="header-logo-upload"
        value={imageRefOf(logoImage)}
        onChange={(next) => setProp((p: { logoImage: ImageRef | null }) => (p.logoImage = next))}
      />
      {imageRefOf(logoImage) && (
        <>
          <label className="field">
            <span className="field-label">Image height (px)</span>
            <input
              type="number"
              min={MIN_LOGO_HEIGHT}
              max={MAX_LOGO_HEIGHT}
              data-testid="header-logo-height"
              value={logoHeightOf(logoHeight)}
              onChange={(e) => setProp((p: { logoHeight: number }) =>
                (p.logoHeight = logoHeightOf(e.target.value)))}
            />
          </label>
          <label className="field">
            <span className="field-label">Image position</span>
            <select
              data-testid="header-logo-position"
              value={logoPositionOf(logoPosition, orientation)}
              onChange={(e) => setProp((p: { logoPosition: string }) =>
                (p.logoPosition = e.target.value))}
            >
              {logoPositionsFor(orientation).map((where) => (
                <option key={where} value={where}>
                  {where.charAt(0).toUpperCase() + where.slice(1)}
                </option>
              ))}
            </select>
          </label>
          {/* p.48's collapsed image, and p.49's condition on it: a header
              image first. */}
          {vertical && collapsible && (
            <HeaderImageField
              label="Collapsed image"
              testId="header-collapsed-upload"
              value={imageRefOf(collapsedImage)}
              onChange={(next) => setProp((p: { collapsedImage: ImageRef | null }) =>
                (p.collapsedImage = next))}
            />
          )}
        </>
      )}
      {/* p.47: "Choose a custom color for the title text." Directly under the
          title it colours rather than in a style section further down: the two
          are one decision, and a colour control separated from the thing it
          colours is one people set on the wrong node. */}
      <label className="field">
        <span className="field-label">Title colour</span>
        <select
          data-testid="header-title-colour"
          value={titleChoice}
          onChange={(e) =>
            setProp((p: { titleColour: string | null }) => {
              p.titleColour =
                e.target.value === "default"
                  ? null
                  : e.target.value === "custom"
                    // Seeded with what is showing, the way the background
                    // control is (p.59): reaching for a shade of the colour
                    // already there should not start by losing it.
                    ? resolveBackground(titleColour, { palette, scheme }) ?? "#16232f"
                    : e.target.value;
            })
          }
        >
          <option value="default">Default — follows the theme</option>
          {palette.length > 0 && (
            <optgroup label="Saved colours">
              {palette.map((colour) => (
                <option key={colour.id} value={refTo(colour.id)}>{colour.name}</option>
              ))}
            </optgroup>
          )}
          <option value="custom">Custom…</option>
        </select>
      </label>
      {titleChoice === "custom" && (
        <label className="field">
          <span className="field-label">Title colour (hex)</span>
          <input
            type="text"
            data-testid="header-title-colour-hex"
            value={titleColour ?? ""}
            placeholder="#16232f"
            onChange={(e) =>
              setProp((p: { titleColour: string }) => (p.titleColour = e.target.value))}
          />
        </label>
      )}
      {/* p.47: "Select a background color for the header." The style block's
          own control, flagless: p.60 puts borders on "sections and widgets"
          and p.62 puts padding on "pages and sections", and a header is
          neither — so it gets the one setting p.47 names and no more. */}
      <NodeStyleFields />
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
      {/* p.47: "Toggle the ability for users to favorite the module in view
          mode." A module-wide setting rather than a style, so it sits with the
          other one rather than in the style block. */}
      <label className="vars-toggle field">
        <input
          type="checkbox"
          checked={allowFavourite !== false}
          data-testid="header-allow-favourite"
          onChange={(e) =>
            setProp((p: { allowFavourite: boolean }) => (p.allowFavourite = e.target.checked))
          }
        />
        Viewers may favourite this module
      </label>
      {/* **Names the surface, because this control has no effect on the one
          the builder is looking at** (§337). A module opened for editing is a
          resource like any other and keeps the star in its application header;
          p.47's toggle is about view mode, and a builder who unticked it and
          saw their own star still there would reasonably conclude it was
          broken. */}
      <p className="field-hint">
        Unticking it removes the star from the published module. Your own,
        in the header above, is the one every resource has.
      </p>
    </>
  );
}

export function PageSettings() {
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
        <IconChoice
          value={icon}
          testId="page-icon"
          placeholder={(title ?? "P").charAt(0).toUpperCase()}
          onChange={(next) => setProp((p: { icon: string }) => (p.icon = next))}
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
      <InnerSectionStyleField />
    </>
  );
}

export function OverlaySettings() {
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

export function ButtonSettings() {
  const {
    label,
    icon,
    style,
    enabledVariable,
    intent,
    customColour,
    leftIcon,
    rightIcon,
    description,
    hideWhenFalse,
    minimal,
    tag,
    large,
    fill,
    buttonType,
    items,
    actions: { setProp },
  } = useNode((node) => ({
    buttonType: node.data.props.buttonType,
    items: node.data.props.items,
    label: node.data.props.label,
    icon: node.data.props.icon,
    style: node.data.props.style,
    enabledVariable: node.data.props.enabledVariable,
    intent: node.data.props.intent,
    customColour: node.data.props.customColour,
    leftIcon: node.data.props.leftIcon,
    rightIcon: node.data.props.rightIcon,
    description: node.data.props.description,
    hideWhenFalse: node.data.props.hideWhenFalse,
    minimal: node.data.props.minimal,
    tag: node.data.props.tag,
    large: node.data.props.large,
    fill: node.data.props.fill,
  }));
  // What the button is showing now, including a pre-§461 button's `style`.
  const shownIntent = intentOf({ intent, style, customColour });
  const toggle = (key: "minimal" | "tag" | "large" | "fill", label: string, hint: string) => (
    <label className="field canvas-toggle">
      <input
        type="checkbox"
        checked={!!({ minimal, tag, large, fill }[key])}
        data-testid={`button-${key}`}
        onChange={(e) =>
          setProp((p: Record<string, unknown>) => (p[key] = e.target.checked))}
      />
      <span className="field-label">{label}</span>
      <span className="field-hint">{hint}</span>
    </label>
  );
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
      {/* p.486's "State if false", which only means something once there is
          a variable to be false. */}
      {enabledVariable && (
        <label className="field">
          <span className="field-label">When false</span>
          <select
            value={hideWhenFalse ? "hidden" : "disabled"}
            data-testid="button-state-if-false"
            onChange={(e) =>
              setProp((p: { hideWhenFalse: boolean }) =>
                (p.hideWhenFalse = e.target.value === "hidden"))}
          >
            <option value="disabled">Disabled</option>
            <option value="hidden">Hidden</option>
          </select>
          <span className="field-hint">Hidden applies to readers; the builder always shows it</span>
        </label>
      )}
      </>}
      configuration={<>
      {/* p.483's three types, first because it decides what the rest mean. */}
      <label className="field">
        <span className="field-label">Button type</span>
        <select
          value={buttonTypeOf(buttonType)}
          data-testid="button-type"
          onChange={(e) =>
            setProp((p: { buttonType: string; items: unknown }) => {
              p.buttonType = e.target.value;
              // A menu with nothing in it is a button that opens nothing, so
              // the first switch to one starts it with an item to rename.
              if (e.target.value !== "inline" && itemsOf(p.items).length === 0) {
                p.items = addItem([]);
              }
            })}
        >
          <option value="inline">Inline: a single option</option>
          <option value="menu">Menu: multiple options</option>
          <option value="twoPart">Two-part: a main button and a menu</option>
        </select>
      </label>
      {buttonTypeOf(buttonType) !== "inline" && (
        <fieldset className="field" data-testid="button-items">
          <legend className="field-label">Menu items</legend>
          {itemsOf(items).map((item) => (
            <div key={item.id} className="row-actions">
              <input
                value={item.label}
                aria-label={`Label of ${item.label || item.id}`}
                data-testid={`button-item-${item.id}`}
                onChange={(e) =>
                  setProp((p: { items: unknown }) =>
                    (p.items = renameItem(itemsOf(p.items), item.id, e.target.value)))}
              />
              <button
                type="button"
                className="btn quiet"
                aria-label={`Duplicate ${item.label || item.id}`}
                onClick={() =>
                  setProp((p: { items: unknown }) =>
                    (p.items = duplicateItem(itemsOf(p.items), item.id)))}
              >
                ⧉
              </button>
              <button
                type="button"
                className="btn quiet"
                aria-label={`Remove ${item.label || item.id}`}
                onClick={() =>
                  setProp((p: { items: unknown }) =>
                    (p.items = removeItem(itemsOf(p.items), item.id)))}
              >
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn quiet"
            data-testid="button-add-item"
            onClick={() =>
              setProp((p: { items: unknown }) => (p.items = addItem(itemsOf(p.items))))}
          >
            Add item
          </button>
          <span className="field-hint">
            Each item fires its own events: wire them in the Events panel
          </span>
        </fieldset>
      )}
      <label className="field">
        <span className="field-label">Label</span>
        <input
          value={label ?? ""}
          data-testid="button-label"
          onChange={(e) => setProp((p: { label: string }) => (p.label = e.target.value))}
        />
        <span className="field-hint">{"{{v_id}}"} shows a variable&apos;s current value</span>
      </label>
      <label className="field">
        <span className="field-label">Icon</span>
        <IconChoice
          value={icon}
          testId="button-icon"
          placeholder={(label ?? "B").charAt(0).toUpperCase()}
          onChange={(next) => setProp((p: { icon: string }) => (p.icon = next))}
        />
        <span className="field-hint">
          Shown instead of the label in a collapsed header. Blank uses the first letter.
        </span>
      </label>
      <label className="field">
        <span className="field-label">Left icon</span>
        <IconChoice
          value={leftIcon}
          testId="button-left-icon"
          onChange={(next) => setProp((p: { leftIcon: string }) => (p.leftIcon = next))}
        />
      </label>
      <label className="field">
        <span className="field-label">Right icon</span>
        <IconChoice
          value={rightIcon}
          testId="button-right-icon"
          onChange={(next) => setProp((p: { rightIcon: string }) => (p.rightIcon = next))}
        />
        <span className="field-hint">An icon or a character either side of the label</span>
      </label>
      <label className="field">
        <span className="field-label">Description</span>
        <input
          value={description ?? ""}
          data-testid="button-description"
          onChange={(e) =>
            setProp((p: { description: string }) => (p.description = e.target.value))}
        />
        <span className="field-hint">Shown as a tooltip when a reader hovers the button</span>
      </label>
      {/* p.486's Button color: five intents, or a custom colour. */}
      <label className="field">
        <span className="field-label">Colour</span>
        <select
          value={intent === "custom" ? "custom" : shownIntent}
          data-testid="button-intent"
          onChange={(e) =>
            setProp((p: { intent: string }) => (p.intent = e.target.value))}
        >
          <option value="none">None</option>
          <option value="primary">Primary</option>
          <option value="success">Success</option>
          <option value="warning">Warning</option>
          <option value="danger">Danger</option>
          <option value="custom">Custom</option>
        </select>
      </label>
      {intent === "custom" && (
        <label className="field">
          <span className="field-label">Custom colour</span>
          <input
            value={customColour ?? ""}
            placeholder="#14646e"
            data-testid="button-custom-colour"
            onChange={(e) =>
              setProp((p: { customColour: string | null }) =>
                (p.customColour = e.target.value || null))}
          />
          <span className="field-hint">
            {customColour && !customColourOf(customColour)
              ? "Not a colour yet: use #rgb or #rrggbb"
              : "A hex colour, #rgb or #rrggbb"}
          </span>
        </label>
      )}
      {toggle("minimal", "Minimal style", "No border; the colour moves to the text")}
      {toggle("tag", "Tag style", "A narrower, rounded button")}
      {toggle("large", "Large style", "A bigger button")}
      {toggle("fill", "Fill available space", "As wide as the section it is in")}
      </>}
    />
  );
}

export function EditHistorySettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, order, properties,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    order: node.data.props.order,
    properties: node.data.props.properties,
  }));
  const { declared, resolved } = useCanvasVariables();
  const setVariables = Object.values(declared).filter((v) => v.kind === "object_set");
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
        <span className="field-label">Object set</span>
        <select
          value={objectSetVariable || ""}
          data-testid="edit-history-variable"
          onChange={(e) =>
            setProp((p: { objectSetVariable: string | null }) =>
              (p.objectSetVariable = e.target.value || null))}
        >
          <option value="">Choose…</option>
          {setVariables.map((v) => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
        <span className="field-hint">Only the first object's edits are shown (p.403)</span>
      </label>
      </>}
      configuration={<>
      <label className="field">
        <span className="field-label">Edits sort order</span>
        <select
          value={editOrderOf(order)}
          data-testid="edit-history-order"
          onChange={(e) => setProp((p: { order: string }) => (p.order = e.target.value))}
        >
          {Object.entries(EDIT_ORDERS).map(([key, name]) => (
            <option key={key} value={key}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Properties</span>
        <input
          type="text"
          value={properties ?? ""}
          placeholder="every property"
          data-testid="edit-history-properties"
          onChange={(e) =>
            setProp((p: { properties: string }) => (p.properties = e.target.value))}
        />
        <span className="field-hint">
          {type.data
            ? `Comma-separated. Available: ${
              (type.data.properties ?? []).map((p) => p.api_name).join(", ")}`
            : "Comma-separated. Blank shows edits to every property."}
        </span>
      </label>
      </>}
    />
  );
}

export function DataFreshnessSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    items,
    title,
    actions: { setProp },
  } = useNode((node) => ({ items: node.data.props.items, title: node.data.props.title }));
  const configured = freshnessItemsOf(items);
  const write = (next: FreshnessItem[]) =>
    setProp((p: { items: FreshnessItem[] }) => (p.items = next));
  const ids = configured.map((i) => i.objectTypeId);
  // The sources each chosen type has, from the same answer the widget reads,
  // so the panel offers exactly what the widget can report on.
  const fresh = useQuery({
    queryKey: ["data-freshness", ids.join(",")],
    queryFn: () => objApi.objectTypeFreshness(workspaceId, ids),
    enabled: ids.length > 0,
  });
  const sourcesOf = (typeId: string) =>
    fresh.data?.types.find((t) => t.object_type_id === typeId)?.sources ?? [];

  return (
    <>
      <label className="field">
        <span className="field-label">Title</span>
        <input
          value={title ?? ""}
          onChange={(e) => setProp((p: { title: string }) => (p.title = e.target.value))}
        />
      </label>
      {configured.map((item) => (
        <fieldset key={item.id} className="field" data-testid={`freshness-item-${item.id}`}>
          <legend className="field-label">Object type</legend>
          <TypePicker
            workspaceId={workspaceId}
            value={item.objectTypeId}
            testId={`freshness-type-${item.id}`}
            onChange={(typeId) => write(configured.map((i) => i.id === item.id
              // A new type has other sources: the old ones would name
              // datasets that are not this type's.
              ? { ...i, objectTypeId: typeId, sources: [] } : i))}
          />
          {sourcesOf(item.objectTypeId).map((source) => {
            const chosen = item.sources.find((s) => s.datasetId === source.dataset_id);
            return (
              <div key={source.dataset_id} className="row-actions" style={{ marginTop: 4 }}>
                <label className="canvas-toggle">
                  <input
                    type="checkbox"
                    data-testid={`freshness-source-toggle-${source.dataset_id}`}
                    checked={!!chosen}
                    onChange={(e) => write(configured.map((i) => i.id !== item.id ? i : {
                      ...i,
                      sources: e.target.checked
                        ? [...i.sources, { datasetId: source.dataset_id }]
                        : i.sources.filter((s) => s.datasetId !== source.dataset_id),
                    }))}
                  />
                  {" "}{source.dataset_name}
                </label>
                {chosen && (
                  // p.401's Override resource name.
                  <input
                    aria-label={`Name shown for ${source.dataset_name}`}
                    data-testid={`freshness-source-name-${source.dataset_id}`}
                    placeholder={source.dataset_name}
                    value={chosen.name ?? ""}
                    onChange={(e) => write(configured.map((i) => i.id !== item.id ? i : {
                      ...i,
                      sources: i.sources.map((s) => s.datasetId !== source.dataset_id ? s
                        : { datasetId: s.datasetId, ...(e.target.value ? { name: e.target.value } : {}) }),
                    }))}
                  />
                )}
              </div>
            );
          })}
          <button
            type="button"
            className="btn quiet"
            aria-label="Remove this object type"
            onClick={() => write(configured.filter((i) => i.id !== item.id))}
          >
            Remove
          </button>
        </fieldset>
      ))}
      {/* p.401's Add item: an object type first, since its sources depend on it. */}
      <div className="field">
        <span className="field-label">Add item</span>
        <TypePicker
          workspaceId={workspaceId}
          value={null}
          testId="freshness-add-type"
          placeholder="Choose an object type…"
          onChange={(typeId) => write([
            ...configured, { id: newFreshnessItemId(configured), objectTypeId: typeId, sources: [] },
          ])}
        />
      </div>
    </>
  );
}

registerSettingsPanels({
  ActionFormSettings,
  ButtonSettings,
  ChartSettings,
  ContainerSettings,
  DataFreshnessSettings,
  DatasetTableSettings,
  DateInputSettings,
  DateTimePickerSettings,
  EditHistorySettings,
  EmbeddedModuleSettings,
  FilterListSettings,
  FilterPillsSettings,
  HeaderSettings,
  IframeSettings,
  LinksWidgetSettings,
  LoopSectionSettings,
  MapSettings,
  MarkdownSettings,
  MediaPreviewSettings,
  MetricCardSettings,
  NumericInputSettings,
  ObjectCardsSettings,
  ObjectDropdownSettings,
  ObjectSelectorSettings,
  ObjectSetTitleSettings,
  ObjectTableSettings,
  ObjectViewWidgetSettings,
  OverlaySettings,
  PageSettings,
  ParameterSettings,
  PieChartSettings,
  PivotTableSettings,
  ProminentTermsSettings,
  PropertyListSettings,
  SearchBarSettings,
  SearchSettings,
  SectionSettings,
  SeriesAnalysisSettings,
  StepperSettings,
  StringSelectorSettings,
  TextInputSettings,
  TextSettings,
  TimeSeriesSettings,
  TimelineSettings,
  UserSelectSettings,
});
