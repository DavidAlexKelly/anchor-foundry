"use client";

/** Canvas widgets - the components a saved app's Craft.js definition is
 * built from. Each reads workspace/project id + edit-vs-run mode from
 * CanvasEnvProvider (never from its own serialised props - the same app
 * renders from more than one route), and reuses the datasets/objects/
 * actions endpoints already built elsewhere; a widget only remembers which
 * dataset/action it's bound to, never a copy of the data itself. */

import { Editor, Frame, useEditor, useNode } from "@craftjs/core";
import dynamic from "next/dynamic";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { actions as actionApi, api, ApiError, canvas as canvasApi, datasets as dsApi, objects as objApi, seriesAnalyses as seriesAnalysisApi, type SeriesAnalysis } from "@/lib/api";
import { eventsOf, variablesOf } from "@/lib/workshop-module";
import { TypePicker } from "@/components/type-picker";
import { VariableBridge } from "./VariableBridge";
import { useSavedColours } from "./use-saved-colours";
import { regexProblem } from "./regex-query";
import { resolveBackground, schemeFor, styleFor, type BorderName, type PaddingName } from "./style";
import { asCollapsed, collapseState } from "./collapse";
import { arrayEntries, pageOf } from "./loop-array";
import { canReset, suffixText as suffixTextOf, toDisplay, toStored, type SuffixKind } from "./number-input";
import { rowsOf, settingsOf, toDisplay as toTextDisplay, toStored as toTextStored } from "./text-input";
import { canCreate, chosenOf, createdOf, displayOf, layoutStyle, modeOf, optionsOf, outputKind, pick, placeholderOf, selectionOf as pickModeOf, sourceOf, withTyped } from "./string-selector";
import { COMMON_ZONES, DEFAULT_PRECISION, PRECISIONS, formatDisplay, fromLocalInput, isZone, toLocalInput, zoneLabel, zoneOf, type Precision } from "./date-time";
import { orderedRange, rangeText, shownDay } from "./date-input";
import { alignmentOf, parse as parseMarkdown, sourceOf as markdownSourceOf, textOf as markdownTextOf } from "./markdown";
import { autoSelectKey, hasSelection, keysOf, selectionClauses, toggle as toggleKey } from "./object-table-selection";
import { UNSUPPORTED_HINT, isUnsupported, omittedOf, valuesForHiding } from "./unsupported-properties";
import { ObjectSetPanel } from "@/components/object-panels";
import { formFactorOf, panelBehaviorOf, panelShows } from "@/lib/object-panels";
import { combinedColumns, isPicked, pickedClauses, pickedIn, pickOf, selectedType, tabIndex, typedSelection, UNION_PAGE_DEPTH, unionParts, unionProperties, type Picked } from "./union-set";
import { layerColorOf, layerOpacityOf, layerPoints, layerVisibleOf, layersOf } from "./map-layer";
import { DEFAULT_LINES, cellStyle, emptyIconOf, emptyMessageOf, fillsCellOf, fitColumnsOf, frozenOf, linesOf, narrowHeadersOf, noValueOf, rowMinHeight, stickyLefts, wrapOf } from "./object-table-display";
import { renderWhenEmptyOf, shouldRender, showIconOf, singleOf, titleFor } from "./object-set-title";
import { columnsOf as propertyColumnsOf, gridStyle as propertyGridStyle, hideNullOf, layoutOf as propertyLayoutOf, visibleProperties } from "./property-list";
import { chosenOf as linkChosenOf, defaultExpandOf, initiallyExpanded, labelFor, linkKey, modeOf as linkModeOf, toggleExpanded, visibleLinks, LINK_PAGE, objectViewHref, previewOf as linkPreviewOf, previewProperties, sortOf as linkSortOf, sortedLinkQuery, titleOf, expandsFurther, type ChosenLink } from "./links-widget";
import { linkSubsetHref } from "@/lib/link-subset";
import { useWorkspaceById } from "@/components/use-workspace";
import { allowToggleOf, emptyMessageOf as objectViewEmptyMessageOf, hideHeaderOf, viewModeOf } from "./object-view-widget";
import { formVisible, headerTitleOf, hideHeaderOf as hideActionHeaderOf, localDefaultsOf } from "./action-form";
import { aggregationOf as pieAggregationOf, aggregationRequest as pieAggregationRequest, innerRadiusOf, legendPositionOf, segmentsOf, showLegendOf, visibleSlices } from "./pie-chart";
import { DEFAULT_SPARK_POSITION, metricRequest, showsSpark as metricShowsSpark, sparkEmptyReason as metricSparkEmptyReason, sparkPositionOf as metricSparkPositionOf, valueLabel as metricValueLabel, baselineOf as metricBaselineOf, descriptionOf as metricDescriptionOf, metricSizeOf, pageNow, sparkRangeTransform as metricSparkRangeTransform, secondaryLabelOf as metricSecondaryLabelOf, directionOf as metricDirectionOf, extraMetricsOf, layoutSettings as metricLayoutSettings, layoutStyleOf as metricLayoutStyleOf, metricLabelOf, sparkAllowedIn, templateOf as metricTemplateOf, type ExtraMetric, baselineKindOf, summarise } from "./metric-card";
import { formatsByColumn, numberFormatOf } from "./value-formats";
import { METRIC_SUBJECT, paintFor, rulesByColumn, rulesOf, SERIES_SUBJECT, strokeFor } from "./conditional-formats";
import { columnsFor, derivedInputs, valueFor, type DerivedColumn, type FunctionColumn } from "./derived-columns";
import { callKey, callValues, cellOf } from "./function-columns";
import { inputValues } from "./function-inputs";
import { functionLayerOf, gridFrom, pointsFrom } from "./function-layers";
import { derivedForExport } from "./derived-export";
import { derivedSortLimit, readUpTo, sortRowsBy, splitSorts } from "./derived-sort";
import { FunctionPivotView, pivotFieldsOf } from "./function-pivot-table";
import { derivedCell } from "@/lib/derived-values";
import { visibleColumns } from "./column-visibility";
import { moved as movedColumn, storageKey as columnsKey, storedChoice, toggled as toggledColumn, viewerColumnsOf } from "./viewer-columns";
import { DerivedValue } from "@/components/derived-value";
import type { ObjectInstance, ObjectTypeDetail, ObjectTypeProperty, TypeLink } from "@/lib/types";
import { latest as latestOf } from "./sparkline";
import { PAGE_LIMIT as DROPDOWN_PAGE_LIMIT, allowNoSelectionOf, labelOf as dropdownLabelOf, matchesQuery, propertyListOf, searchProperties, selectionSummary, sortOf as dropdownSortOf, titleOf as optionTitleOf, truncationNote } from "./object-dropdown";
import { requestSort } from "./property-sort";
import { allowClearOf as userAllowClearOf, groupIdsOf as userGroupIdsOf, isMultiple as userIsMultiple, labelOf as userLabelOf, pickedSingle as userPickedSingle, placeholderOf as userPlaceholderOf, selectedIds as userSelectedIds, shouldAsk as userShouldAsk, summaryOf as userSummaryOf, textOf as userTextOf, toOutput as userToOutput, toggled as userToggled, usersOf } from "./user-select";
import { OPERATOR_LABELS, canAdd, canEdit, canRemove, clausesOf, describe as describeClause, describe as describeFilterClause, editableValue, isEditable, isRemovable, modeOf as pillModeOf, operatorsFor, parseValue, withValue, without } from "./filter-clause";
import { MAX_SUGGESTED, availableLinks, availableProperties, describeLinked, linkMenu, linkScopeOf, placeholderOf as searchPlaceholderOf, propertyScopeOf, searchMenu, suggestionDefinition, suggestionsOf, withLinkedFilter, type LinkEntry, type MenuEntry, type Link as SearchLink } from "./search-bar";
import { nextIndex } from "@/lib/search-keys";
import { hasItems, submittedValues } from "@/lib/array-parameter";
import { countLabel, labelOf as termLabelOf, renderableTerms, selectedValues, termsOf, toClauses, toggled, visibleTerms } from "./prominent-terms";
import type { Property as SortableProperty } from "./property-sort";
import { activeColourOf, activeIndex, completedColourOf, isCompleted, isReachable, showsStepNumber, stateOf, stepsOf, templateOf as stepperTemplateOf } from "./stepper";
import { eventProperties, eventsOf as timelineEventsOf, gapLabel, layerIcon, labelFor as timelineLabelFor, layerColour, layersOf as timelineLayersOf, orientationOf as timelineOrientationOf, showsIcon, sortFor, toggleLayer, visibleEvents, selectionItemOf, type Layer as TimelineLayer } from "./timeline";
import { attachmentOf, resolveMedia, sizeLabel, sourceOf as mediaSourceOf } from "./media";
import { frameRefusal, frameTitle, safeFrameUrl } from "./frame";
import { MESSAGE as FRAME_MESSAGE, VERSION as FRAME_VERSION, acceptWrite, frameOrigin, knownEvent, readMessage, sameDefinition, savedDefinition, valuesOf as frameValuesOf } from "./frame-protocol";
import { buttonLook } from "./button-look";
import { buttonTypeOf, itemsOf, removeItem } from "./button-items";
import { axisEnds, barWidth, bucketLabel, defaultComponentFor, filtersOf, isBucketChosen, isPeriodChosen, periodLabel, periodOf, timelineIntervalOf, withBucket, keywordOf, layoutOf, pillSummary, rangeOf, toggleValue, valuesOf, viewerFilterId, visibleFilters, withKeyword, withRange, withValues, withoutFilter, hasLinkOf, linkedClausesOf, linkedPillLabel, withHasLink, withLinked, groupFilters, linkDisplayOf, type Clause, type DayRange, type FilterSpec } from "./filter-list";
import { keywordQueryProblem } from "./keyword-query";
import { swatch } from "@/lib/object-type-icon";
import { IconOrGlyph, TypeGlyph } from "@/components/icon";
import { MAX_DRAGGED_OBJECTS, OBJECT_MEDIA_TYPE, OBJECT_SET_MEDIA_TYPE, carriesPayload, collectKeys, droppedClauses, objectPayload, objectSetPayload } from "./drag-payload";
import { sortsOf as tableSortsOf, toRequest as tableSortsToRequest } from "./table-sorts";
import { buttonTextOf, canStage, canSubmit, cellValue, editing, eligibleActions, isStaged, limitNotice, mappingOf, oneClickOf, parameterForColumn, rowLimitOf, stage, stagedCount, toEdits, undoRow, type Staged, variableFeedsOf, withVariables } from "./inline-edit";
import { readerLayout } from "./reader-layout";
import { PALETTE as WIDGET_LIST } from "./widget-list";
import { MarkdownReferences, MarkdownRuns, MarkdownView } from "../markdown-view";
import { iconPropertyOf, imageUrlOf } from "@/lib/type-classes";
import { annotationColorOf, annotationFormatOf, annotationLayersOf, annotationsOf, hoverActionsOf, segmentsOf as annotatedPieces, tooltipOf } from "./markdown-annotations";
import { type SelectionEnd, selectedSource, selectionRange } from "./markdown-selection";
import { isLit as isReferenceLit, numberReferences, referenceTypesOf, selectionBehaviorOf as referenceSelectionOf, keysToColor as referenceKeysToColor, referenceColorOf, selectionItemOfType } from "./markdown-references";
import { FORMATS, FORMAT_LABELS, applyFormat, autoRows, type MarkdownFormat } from "./markdown-editor";
import { markdownOf } from "./markdown-dom";
import { SeriesCell } from "./SeriesCell";
import { baselineFor, baselinesByColumn } from "./series-baselines";
import { Sparkline } from "./Sparkline";
import { useSeriesPoints, type SeriesRef } from "./series-points";
import { ChartExport } from "./ChartExport";
import { blankTransform, readableTransforms, transformsProblem as seriesTransformsProblem, transformsText, TIME_UNITS, COMBINE_AGGREGATES, COMBINE_WORDS, FILTER_OPERATORS as SERIES_FILTER_OPERATORS, FILTER_WORDS as SERIES_FILTER_WORDS, WINDOW_AGGREGATES as SERIES_WINDOW_AGGREGATES, type FilterOperator as SeriesFilterOperator, type SeriesTransform, type TimeUnit, type TransformKind } from "./series-transforms";
import { SeriesTransformsEditor } from "./SeriesTransformsEditor";
import { SeriesAnalysisChart } from "./SeriesAnalysisChart";
import { LINE_STYLES as SERIES_LINE_STYLES, MAX_PLOTS as MAX_SERIES_PLOTS, MAX_ROOTS as MAX_SERIES_ROOTS, PLOT_LABELS as SERIES_PLOT_LABELS, PLOT_TYPES as SERIES_PLOT_TYPES, canvasesOf as seriesCanvasesOf, chainOf as seriesChainOf, readingsOf as seriesReadingsOf, rootOf as seriesRootOf, rootPlots as seriesRootPlots, statsOf as seriesStatsOf, withDerived as withSeriesDerived, withPlotSetting as withSeriesPlotSetting, withRoots as withSeriesRoots, withoutPlot as withoutSeriesPlot, DEFAULT_BANDS as DEFAULT_SERIES_BANDS, bandsProblem as seriesBandsProblem, withBands as withSeriesBands, MAX_COMBINED as MAX_SERIES_COMBINED, withCombined as withSeriesCombined, MAX_EVENT_SETS as MAX_SERIES_EVENT_SETS, eventCount as seriesEventCount, eventsOf as seriesEventsOf, liveEventSets as liveSeriesEventSets, withEventSet as withSeriesEventSet, withLinkedEventSet as withSeriesLinkedEventSet, POINT_FILLS as SERIES_POINT_FILLS, POINT_FILL_WORDS as SERIES_POINT_FILL_WORDS, POINT_SHAPES as SERIES_POINT_SHAPES, displayOf as seriesDisplayOf, pointOptions as seriesPointOptions, withDisplay as withSeriesDisplay, type PointFill as SeriesPointFill, type PointShape as SeriesPointShape, AXIS_ALIGNS as SERIES_AXIS_ALIGNS, MAX_UNIT as MAX_SERIES_UNIT, axesOf as seriesAxesOf, axisOf as seriesAxisOf, axisProblem as seriesAxisProblem, axisSettingsOf as seriesAxisSettingsOf, newAxisOf as newSeriesAxisOf, withAxisSetting as withSeriesAxisSetting, type AxisAlign as SeriesAxisAlign, type Axes as SeriesAxes, EXTERNAL_INTERPOLATIONS as SERIES_EXTERNAL_INTERPOLATIONS, INTERNAL_INTERPOLATIONS as SERIES_INTERNAL_INTERPOLATIONS, type ExternalInterpolation as SeriesExternalInterpolation, type InternalInterpolation as SeriesInternalInterpolation, EVENT_SET_TYPES as SERIES_EVENT_SET_TYPES, MAX_INITIAL_EVENTS as MAX_SERIES_INITIAL_EVENTS, canvasFor as seriesCanvasFor, initialEventSetsOf as seriesInitialEventSetsOf, objectEventsOf as seriesObjectEventsOf, placementOf as seriesPlacementOf, defaultRangeOf as seriesDefaultRangeOf, pannedRange as seriesPannedRange, timesOf as seriesTimesOf, zoomedRange as seriesZoomedRange, type ViewRange as SeriesViewRange, tooltipOptionsOf as seriesTooltipOptionsOf, addDataSetsOf as seriesAddDataSetsOf, objectLabelOf as seriesObjectLabelOf, withAddedRoot as withSeriesAddedRoot, openedView as seriesOpenedView, savedViewOf as seriesSavedViewOf, autoloadIdsOf as seriesAutoloadIdsOf, mergedView as seriesMergedView, type EventSet as SeriesEventSet, withEventStatistics as withSeriesEventStatistics, type Bands as SeriesBands, type LineStyle as SeriesLineStyle, type Plot as SeriesPlot } from "./series-analysis";
import { conversionProblem, convertReadings, shownUnit } from "./series-units";
import { outputClauses } from "./action-output";
import { actionItemsOf, activeIndexOf, menuLabelOf } from "./action-menu";
import { collapsedInitially, columnsOf as sectionColumnsOf, conditionKey, formLayout, hasConditions, labelOf as parameterLabel, requiredElsewhere, unreachableNote, type FormParameter, type FormSection } from "@/lib/action-sections";
import { isFilled } from "@/lib/struct-parameter";
import { hasOverrides, overrideKey } from "@/lib/action-overrides";
import { emptyNote as noChoicesNote, labelOf as choiceLabel, offerFor, truncationNote as choicesTruncatedNote, valuesFor } from "@/lib/action-choices";
import { emptyValuesNote, valuesTruncationNote } from "@/lib/action-options";
import { filterKey, isWaiting, waitingNote } from "@/lib/action-filters";
import { interfaceQuery } from "./routing";
import { LayoutTemplatePicker } from "./LayoutTemplatePicker";
import { activeTab, asTabName, tabLabels } from "./tab-selection";
import { CanvasNode, InLoop, OffLayout, holdsKept } from "./SettingsPanel";
import { CanvasHeaderCollapsedContext, CanvasParameterProvider, useCanvasActions, useCanvasEnv, useHeaderCollapsed, useCanvasPage, useCanvasParameter, useCanvasParameters, useCanvasVariable, useCanvasVariables } from "./context";
import { eventsFor, interpolate, run as runEvents, useEventContext } from "./events";
import { invalidateCanvasReads } from "./refresh";
import { ActionTable } from "./ActionTable";
import { describeSet, selectionOf, useOnScreen, useSetPage } from "./object-set";
import { MIN_SHARE, formatWeights, hasValue, parseWeights, pivotClauses, resizeWeights, roundWeight, seedActionForm, seriesLabel, seriesPointLabel, type PivotPick } from "./pure";
import { chartQuery, distinctValuesQuery, filteredQuery, mapQuery, type Aggregate, type ChartKind, type FilterOperator } from "./filter-sql";
import { Chart, MultiLineChart, PALETTE as CHART_PALETTE, PieChart, SegmentedBarChart, toPoints } from "./charts";
import { axisSides, drillClauses, drilledLabel as drilledOn, layerKinds, mergeSeries, mixedKinds, layeredGrid, segmentsLayer, seriesName as seriesNameOf, seriesOf, seriesRequests, seriesSource } from "./chart-series";
import { segmentLegendPositionOf, segmentModeOf, segmentedFrom, sortSegmented } from "./chart-segments";
import { useAttachmentUrl } from "./use-attachment-url";
import { headerCount, headerStyleOf, paddingTarget, styleTarget } from "./section-header";
import { sectionLook } from "./inner-section-style";
import { DEFAULT_LOGO_HEIGHT, headerMark, logoHeightOf, logoPositionOf, type ImageRef } from "./header-logo";
import { chosenProperties as chosenEditProperties, editOrderOf, editSummary } from "./edit-history";
import { freshnessLabel, isStale, itemsOf as freshnessItemsOf, type FreshnessItem } from "./data-freshness";
import { areaOf, axisProblem, axisTitlesOf, categoryText, chartSortOf, defaultValueTitle, missingCount, missingText, nullDisplayOf, rightAxisTitle, orientationOf, sortPoints, valueAxisOf, valueText, withMissing } from "./chart-display";
import { MapCanvas, toLatLon, type MapPoint, type MapShape } from "./map";
import { geometriesOf, geometryShapes, type MapGeometry } from "./map-geometry";
import { extentOf, nextPlayback, pauseCrossed, pausesOf, positionAt, selectedTimeOf, selectedTimeText, timeLabel, timelineControls, timelineSpan, trackShape, windowOf, withinWindow, type TimeFormat } from "./map-tracks";
import { type Line as DrawnLine, lineOfShapes, lineText, selectedIn, selectedText, shapeOutputOf, shapesText, syncShapes, toggledShape } from "./map-drawn";
import { perimeterModeOf } from "./map-measure";
import { hopLabel, locationProperties, pinStart, resultColor, resultLabel, searchAroundLinks, searchAroundOf, searchAroundSet, toolbarStart, type SearchResult, type SearchStart } from "./map-search-around";
// Aliased on §211's rule: `areaOf` is also §537's chart area option.
import { DRAWN_OPACITY, areasOf as mapAreasOf, drawToolsOf, drawnOpacityOf, singleDrawOf, withAreas as withMapAreas, withDrawn } from "./map-area";
import { PropertyInput, PropertyValue } from "@/components/property-value";
import { PropertyInlineEdit } from "@/components/property-inline-edit";
import { constraintNote, fieldChoices, fieldNotes, multipleChoice } from "@/lib/parameter-constraint";
import { conditionalStyle, cssFor } from "@/lib/conditional-format";

/** The widgets' settings panels, by name, once `widget-settings.tsx` has
 * registered them (§995).
 *
 * Only an author sees a panel, and the panels are close to half of this
 * table's code, so a module's readers load the widgets without them. The
 * builder imports `widget-settings.tsx` itself (`workshop-app.tsx`), so there
 * every panel is here before a widget can be selected and draws at once - a
 * panel that arrived a moment after its click would be a race for anything
 * reading it, an author or a test. Anywhere else, a panel that is asked for
 * loads the file then. */
const SETTINGS_PANELS: Record<string, React.ComponentType> = {};

export function registerSettingsPanels(panels: Record<string, React.ComponentType>) {
  Object.assign(SETTINGS_PANELS, panels);
}

function settingsPanel(name: string): React.ComponentType {
  function WidgetSettingsPanel() {
    const [, loaded] = useState(0);
    const Panel = SETTINGS_PANELS[name];
    useEffect(() => {
      if (Panel) return;
      let current = true;
      void import("./widget-settings").then(() => current && loaded((n) => n + 1));
      return () => {
        current = false;
      };
    }, [Panel]);
    return Panel ? <Panel /> : <p className="canvas-settings-loading">Loading settings…</p>;
  }
  WidgetSettingsPanel.displayName = name;
  return WidgetSettingsPanel;
}

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
  const saved = useSavedColours();
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
      data-scheme={schemeFor({ background }, saved)}
      style={{
        ...styleFor({ background, border }, saved),
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

/** The p.62 preset a section's parent names for it (§704), read off the
 * layout tree rather than passed down: "children sections" are the sections
 * whose parent - a page or a section - names one, and the settings panel asks
 * the same question of the same tree, so the two cannot disagree about which
 * sections a preset reaches. */
export function useInheritedSectionStyle(): string | null {
  const { parent } = useNode((node) => ({ parent: node.data.parent }));
  const { inherited } = useEditor((state) => {
    const host = parent ? state.nodes[parent] : undefined;
    const name = host?.data?.name;
    const value = name === "CanvasPage" || name === "CanvasSection"
      ? host?.data?.props?.innerSectionStyle : null;
    return { inherited: typeof value === "string" ? value : null };
  });
  return inherited;
}

CanvasContainer.craft = {
  displayName: "Container",
  props: { background: "", padding: 12, border: null, visibleWhen: null },
  related: { settings: settingsPanel("ContainerSettings") },
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

CanvasText.craft = {
  displayName: "Text",
  props: { text: "Text", tag: "p" },
  related: { settings: settingsPanel("TextSettings") },
};

// ---- Filter List -----------------------------------------------------------
/** The properties a set can be filtered on: its type's, or for a union (§687)
 * p.450's Common and Single properties (`unionProperties`). `typeId` is the
 * set's type, and `null` for a union, which has several. */
export function useSetProperties(workspaceId: string, definition: unknown) {
  const parts = unionParts(definition);
  const typeId = parts ? null
    : (definition as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const ids = parts ? parts.map((p) => p.object_type_id) : typeId ? [typeId] : [];
  const types = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["object-type", id],
      queryFn: () => objApi.getType(workspaceId, id),
    })),
  });
  const loaded = types.map((t) => t.data);
  if (!parts) {
    return { typeId, properties: types[0]?.data?.properties ?? [], union: null, loaded };
  }
  const union = unionProperties(loaded.map((t) =>
    t ? { displayName: t.display_name, properties: t.properties } : undefined));
  return { typeId, properties: [...union.common, ...union.single], union, loaded };
}

/** A property picker's options: flat for one type, and for a union in p.450's
 * two groups. `properties` is what to offer, which may be fewer than the
 * union's (a viewer's Add filter leaves out the ones shown). */
export function PropertyOptions({ properties, union }: {
  properties: readonly { api_name: string; display_name: string }[];
  union: { common: readonly { api_name: string }[]; single: readonly { api_name: string }[] } | null;
}) {
  const option = (p: { api_name: string; display_name: string }) => (
    <option key={p.api_name} value={p.api_name}>{p.display_name || p.api_name}</option>
  );
  if (!union) return <>{properties.map(option)}</>;
  const within = (group: readonly { api_name: string }[]) =>
    properties.filter((p) => group.some((g) => g.api_name === p.api_name));
  return (
    <>
      {within(union.common).length > 0 && (
        <optgroup label="Common properties">{within(union.common).map(option)}</optgroup>
      )}
      {within(union.single).length > 0 && (
        <optgroup label="Single properties">{within(union.single).map(option)}</optgroup>
      )}
    </>
  );
}

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
 *
 * **Each filter is drawn as one of p.449's components** (§463): a histogram,
 * a single- or multi-select dropdown, a keyword or a date range. The clauses
 * each writes are `filter-list.ts`.
 */
export function CanvasFilterList({
  objectSetVariable = null,
  variable = null,
  properties = "",
  filters = null,
  title = "Filters",
  userEditable = false,
  layout = "vertical",
  linkDisplay = "inline",
  collapseLinked = false,
}: {
  /** The set to offer filters over. */
  objectSetVariable?: string | null;
  /** The variable this widget writes its clauses into. A `narrow_set`
   * derivation reads it and the input set, and produces the filtered set
   * every other widget then points at. */
  variable?: string | null;
  /** How a Filter List saved before §463 named its properties:
   * comma-separated api_names, each drawn as a histogram (`filtersOf`). */
  properties?: string;
  /** p.449's filters, each a property and the component it is drawn as. Null
   * rather than `[]` by default: Craft fills a missing prop from here, and an
   * empty list would replace an older document's `properties` with nothing. */
  filters?: FilterSpec[] | null;
  title?: string;
  /** p.449's Allow user to add and remove filters (§464). */
  userEditable?: boolean;
  /** p.449's Vertical or Pills layout (§464). */
  layout?: string;
  /** p.451's display options for linked filters (§546): Inline or Grouped,
   * and whether a group starts collapsed. A Pills layout has a pill per
   * filter, grouped or not. */
  linkDisplay?: string;
  collapseLinked?: boolean;
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

  // A viewer's own filters (p.449): **held here and never saved**, because
  // they change what this reader sees and not what the module is for the next
  // one (decision 0002 §3).
  const [added, setAdded] = useState<FilterSpec[]>([]);
  const [removed, setRemoved] = useState<ReadonlySet<string>>(new Set());
  const [openPill, setOpenPill] = useState<string | null>(null);
  const pillsRef = useRef<HTMLDivElement | null>(null);
  const configured = filtersOf(filters, properties);
  const editable = userEditable === true;
  const specs = editable ? visibleFilters(configured, added, removed) : configured;
  const pills = layoutOf(layout) === "pills";

  // A pill's popover closes as the button menu does (§462): on Escape and on
  // a press anywhere outside the row of pills.
  useEffect(() => {
    if (!openPill) return;
    const outside = (e: MouseEvent) => {
      if (pillsRef.current && !pillsRef.current.contains(e.target as Node)) setOpenPill(null);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenPill(null);
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [openPill]);
  // Read back from the variable this widget writes, so every component shows
  // the document's state rather than a second copy of it held here. **The
  // resolved value until something is written**, because that is where p.449's
  // default lives: a parameter nobody has set is undefined, and building the
  // first write on it would drop the default the reader is looking at.
  // Afterwards the parameter, which is current a round trip before the
  // resolved value is, so a keyword typed quickly does not lose a letter.
  const resolvedClauses = useCanvasVariable(variable);
  const clauses = clausesOf(chosen !== undefined ? chosen : resolvedClauses);
  const { properties: typeProperties, union } = useSetProperties(workspaceId, setDefinition);
  const labelOf = (property: string) =>
    typeProperties.find((p) => p.api_name === property)?.display_name || property;

  const write = (next: Clause[], property: string, value: string, on: boolean) => {
    if (variable) set(variable, next);
    // Every component's change is `change` - Foundry's select and deselect on
    // a dropdown. One trigger with the value and whether it is now on, not a
    // trigger per component every document and panel would have to know about.
    if (mode === "run" && changed.length > 0) {
      runEvents(changed, {
        ...eventContext,
        payload: { value, property, selected: on ? "true" : "" },
      });
    }
  };

  // Removing a filter takes its clauses with it (`withoutFilter`): one that
  // stayed would go on narrowing the set with nothing on screen to undo it.
  const remove = (spec: FilterSpec) => {
    write(withoutFilter(clauses, spec), spec.property, "", false);
    if (added.some((f) => f.id === spec.id)) {
      setAdded(added.filter((f) => f.id !== spec.id));
    } else {
      setRemoved(new Set([...removed, spec.id]));
    }
    if (openPill === spec.id) setOpenPill(null);
  };
  const shown = new Set(specs.map((f) => f.property));
  const addable = typeProperties.filter((p) => !shown.has(p.api_name));
  const addControl = editable ? (
    <select
      aria-label="Add filter"
      className="canvas-filter-add"
      value=""
      onChange={(e) => {
        const property = e.target.value;
        if (!property) return;
        const dataType = typeProperties.find((p) => p.api_name === property)?.data_type;
        setAdded([...added, {
          id: viewerFilterId([...configured, ...added]),
          property,
          component: defaultComponentFor(dataType),
        }]);
      }}
    >
      <option value="">+ Add filter</option>
      <PropertyOptions properties={addable} union={union} />
    </select>
  ) : null;
  const filterOf = (spec: FilterSpec) => spec.link ? (
    <LinkedFilterListFilter
      key={spec.id}
      workspaceId={workspaceId}
      spec={spec}
      clauses={clauses}
      onWrite={(next, value, on) => write(next, spec.property || spec.link!, value, on)}
      onRemove={editable ? () => remove(spec) : undefined}
    />
  ) : (
    <FilterListFilter
      key={spec.id}
      workspaceId={workspaceId}
      definition={setDefinition}
      spec={spec}
      label={labelOf(spec.property)}
      clauses={clauses}
      onWrite={(next, value, on) => write(next, spec.property, value, on)}
      onRemove={editable ? () => remove(spec) : undefined}
    />
  );

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      <p className="field-label">{title}</p>
      {!objectSetVariable || !variable ? (
        <p className="canvas-widget-empty">
          Filter list - point it at an object set and at the variable it writes in Settings
        </p>
      ) : specs.length === 0 && !editable ? (
        <p className="canvas-widget-empty">Add filters in Settings</p>
      ) : pills ? (
        // p.449's Pills layout: "all the filters horizontally within an
        // interactive pill. Once selected, the pill opens a popover with filter
        // configuration UI." Closed, a pill says what it applies.
        <div className="canvas-filter-pills" ref={pillsRef}>
          {specs.map((spec) => {
            // A linked filter's property is the linked type's (§545), so its
            // pill names that type first (§621).
            const label = spec.link
              ? <LinkedPillLabel workspaceId={workspaceId} spec={spec} />
              : labelOf(spec.property);
            const summary = pillSummary(spec, clauses);
            const open = openPill === spec.id;
            return (
              <div key={spec.id} className="canvas-filter-pill-wrap">
                <button
                  type="button"
                  className={`canvas-filter-pill${summary ? " canvas-filter-pill--on" : ""}`}
                  aria-expanded={open}
                  onClick={() => setOpenPill(open ? null : spec.id)}
                >
                  {summary ? <>{label}: {summary}</> : label}
                </button>
                {open && <div className="canvas-filter-popover">{filterOf(spec)}</div>}
              </div>
            );
          })}
          {addControl}
        </div>
      ) : (
        <>
          {groupFilters(specs, linkDisplayOf(linkDisplay)).map((group) => group.link === null
            ? group.specs.map(filterOf)
            : (
              <LinkedFilterGroup
                key={`${group.link}:${group.linkTo}`}
                workspaceId={workspaceId}
                link={group.link}
                linkTo={group.linkTo}
                base={setDefinition}
                collapsed={collapseLinked === true}
              >
                {group.specs.map(filterOf)}
              </LinkedFilterGroup>
            ))}
          {addControl}
        </>
      )}
    </div>
  );
}

/** One of p.449's filter components. The three that pick values read the
 * property's values from `/object-sets/group` against the **unfiltered** input
 * set: counts recomputed against the narrowed set would read 0 for every value
 * but the ones already picked, which says nothing about picking another. */
/**
 * p.452's advanced keyword search in a Filter List (§543): AND, OR, NOT,
 * quotations and brackets over the plain search's prefix terms.
 *
 * **Only a query that parses is applied.** The box keeps what is typed, and
 * a half-typed `(north OR` says what is wrong under it while the last query
 * that parsed stays applied - rather than being sent, refused, and shown as
 * an error by every widget reading the set.
 */
function AdvancedKeyword({ label, applied, onApply, problemOf = keywordQueryProblem,
  testId = "filter-keyword-advanced", placeholder = 'north OR (south AND NOT "south east")' }: {
  label: string;
  applied: string;
  onApply: (text: string) => void;
  /** §728's regular expression box is this one with `regexProblem`: both
   * apply what they hold only once it parses. */
  problemOf?: (text: string) => string | null;
  testId?: string;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(applied);
  const problem = draft.trim() ? problemOf(draft) : null;
  return (
    <>
      <input
        type="search"
        aria-label={label}
        data-testid={testId}
        placeholder={placeholder}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          if (!e.target.value.trim() || problemOf(e.target.value) === null) {
            onApply(e.target.value);
          }
        }}
      />
      {problem && (
        <p className="field-hint" role="status" data-testid="filter-keyword-problem">
          {problem.charAt(0).toUpperCase() + problem.slice(1)}.
          {applied.trim() ? ` Still applied: ${applied}` : ""}
        </p>
      )}
    </>
  );
}

/**
 * p.451's Grouped display (§546): a link's filters in one section, headed by
 * the linked type's icon and name and how many of its objects are linked to
 * the set - the traversal §544 made every count honour. p.451's Collapse by
 * default starts it closed.
 */
/** A linked filter's pill label (§621), read off the linked type the way
 * `LinkedFilterGroup` heads its section, and from the same query. */
function LinkedPillLabel({ workspaceId, spec }: { workspaceId: string; spec: FilterSpec }) {
  const far = useQuery({
    queryKey: ["object-type", spec.linkTo],
    queryFn: () => objApi.getType(workspaceId, spec.linkTo!),
    enabled: !!spec.linkTo,
  });
  const property = far.data?.properties?.find((p) => p.api_name === spec.property);
  return (
    <span data-testid="filter-pill-link-label">
      {linkedPillLabel(spec, far.data?.display_name ?? null, property?.display_name)}
    </span>
  );
}

function LinkedFilterGroup({ workspaceId, link, linkTo, base, collapsed, children }: {
  workspaceId: string;
  link: string;
  linkTo: string | null;
  base: unknown;
  collapsed: boolean;
  children: React.ReactNode;
}) {
  const far = useQuery({
    queryKey: ["object-type", linkTo],
    queryFn: () => objApi.getType(workspaceId, linkTo!),
    enabled: !!linkTo,
  });
  const reached = base && linkTo
    ? { object_type_id: linkTo, filters: [], via: { link_type_id: link, base } }
    : null;
  const count = useQuery({
    queryKey: ["canvas-filter-link-count", JSON.stringify(reached)],
    queryFn: () => objApi.aggregateObjectSet(workspaceId, reached, { aggregation: "count" }),
    enabled: !!reached,
  });
  return (
    <details className="canvas-filter-link-group" data-testid="filter-link-group"
      open={!collapsed}>
      <summary>
        {far.data && (
          <span className="ot-mark" style={{ background: swatch(far.data) }} aria-hidden>
            <TypeGlyph type={far.data} />
          </span>
        )}
        {" "}{far.data?.display_name ?? "Linked objects"}
        {count.data?.value != null && (
          <span className="canvas-filter-count" data-testid="filter-link-count">
            {count.data.value}
          </span>
        )}
      </summary>
      {children}
    </details>
  );
}

/**
 * p.451's filter on a link (§545): p.451's Has link, or one of the linked
 * type's properties drawn as any other filter is - over the linked type's own
 * objects, and writing into its link's `has_link` clause (`withLinked`).
 */
function LinkedFilterListFilter({ workspaceId, spec, clauses, onWrite, onRemove }: {
  workspaceId: string;
  spec: FilterSpec;
  clauses: Clause[];
  onWrite: (next: Clause[], value: string, on: boolean) => void;
  onRemove?: () => void;
}) {
  const link = spec.link!;
  const far = useQuery({
    queryKey: ["object-type", spec.linkTo],
    queryFn: () => objApi.getType(workspaceId, spec.linkTo!),
    enabled: !!spec.linkTo,
  });
  const farName = far.data?.display_name ?? "linked object";
  const propertyLabel = far.data?.properties.find((p) => p.api_name === spec.property)
    ?.display_name || spec.property;
  if (!spec.property) {
    const on = hasLinkOf(clauses, link);
    return (
      <fieldset className="canvas-filter-group" data-testid={`filter-${spec.id}`}>
        <legend>{farName}</legend>
        {onRemove && (
          <button
            type="button"
            className="canvas-filter-remove"
            aria-label={`Remove the ${farName} filter`}
            onClick={onRemove}
          >
            ×
          </button>
        )}
        <label className="canvas-toggle">
          <input
            type="checkbox"
            data-testid={`filter-has-link-${spec.id}`}
            checked={on}
            onChange={(e) =>
              onWrite(withHasLink(clauses, link, e.target.checked), link, e.target.checked)}
          />
          <span>Has a linked {farName}</span>
        </label>
      </fieldset>
    );
  }
  return (
    <FilterListFilter
      workspaceId={workspaceId}
      // The linked type's objects, unfiltered, as a plain filter's values
      // come from the input set before anything narrows it.
      definition={spec.linkTo ? { object_type_id: spec.linkTo, filters: [] } : undefined}
      spec={{ ...spec, link: undefined }}
      label={`${farName} · ${propertyLabel}`}
      clauses={linkedClausesOf(clauses, link)}
      onWrite={(next, value, on) => onWrite(withLinked(clauses, link, next), value, on)}
      onRemove={onRemove}
    />
  );
}

function FilterListFilter({
  workspaceId,
  definition,
  spec,
  label,
  clauses,
  onWrite,
  onRemove,
}: {
  workspaceId: string;
  definition: unknown;
  spec: FilterSpec;
  label: string;
  clauses: Clause[];
  onWrite: (next: Clause[], value: string, on: boolean) => void;
  /** Set when a viewer may remove this filter (p.449). */
  onRemove?: () => void;
}) {
  const { property, component } = spec;
  const picksValues = component === "histogram" || component === "singleSelect"
    || component === "multiSelect";
  const result = useQuery({
    queryKey: ["canvas-filter-list", property, JSON.stringify(definition ?? null)],
    queryFn: () => objApi.groupObjectSet(workspaceId, definition, property),
    enabled: !!definition && picksValues,
  });
  const groups = result.data?.groups ?? [];
  const values = valuesOf(clauses, property);
  // p.449's distribution chart reads ranges rather than values (§465), over
  // the unfiltered input set for the reason the counts above are.
  const distribution = useQuery({
    queryKey: ["canvas-filter-distribution", property, JSON.stringify(definition ?? null)],
    queryFn: () => objApi.distributionObjectSet(workspaceId, definition, property),
    enabled: !!definition && component === "distribution",
  });
  // p.449's timeline (§466): the property's own dates by day, week or month,
  // whichever fits - the server picks, and says which.
  const timeline = useQuery({
    queryKey: ["canvas-filter-timeline", property, JSON.stringify(definition ?? null)],
    queryFn: () => objApi.timeSeriesObjectSet(workspaceId, definition, "auto", property),
    enabled: !!definition && component === "timeline",
  });

  return (
    <fieldset className="canvas-filter-group" data-testid={`filter-${spec.id}`}>
      <legend>{label}</legend>
      {onRemove && (
        <button
          type="button"
          className="canvas-filter-remove"
          aria-label={`Remove the ${label} filter`}
          onClick={onRemove}
        >
          ×
        </button>
      )}
      {picksValues && result.isError && (
        <p className="canvas-widget-empty" data-testid="filter-values-error">
          {/* The server's sentence, as the Pie's: a property that is not
              Selectable (§727) has no values to offer, and says so. */}
          {result.error instanceof ApiError ? result.error.message
            : "Couldn't read this property's values."}
        </p>
      )}
      {picksValues && result.data?.truncated && (
        <p className="canvas-widget-empty">showing the most common values</p>
      )}
      {picksValues && result.data && groups.length === 0 && (
        <p className="canvas-widget-empty">no values</p>
      )}

      {component === "histogram" && (() => {
        const max = Math.max(0, ...groups.map((g) => g.count));
        return groups.map((group) => (
          <label
            key={group.value}
            className="canvas-filter-option canvas-filter-bar"
            // p.446's "visualize the most common property values": the bar is
            // the row's own background, so the value, its count and its share
            // read as one line rather than as a chart beside a list.
            style={{ "--bar": `${barWidth(group.count, max)}%` } as React.CSSProperties}
          >
            <input
              type="checkbox"
              checked={values.includes(group.value)}
              onChange={() => onWrite(
                toggleValue(clauses, property, group.value), group.value,
                !values.includes(group.value))}
            />
            <span>{group.value}</span>
            <span className="canvas-filter-count">{group.count}</span>
          </label>
        ));
      })()}

      {component === "singleSelect" && (
        <select
          aria-label={label}
          value={values[0] ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            onWrite(withValues(clauses, property, v ? [v] : []), v || (values[0] ?? ""), !!v);
          }}
        >
          <option value="">Any</option>
          {/* A value chosen before it fell out of the most common is still
              shown, or the select would read "Any" while filtering on it. */}
          {values[0] && !groups.some((g) => g.value === values[0]) && (
            <option value={values[0]}>{values[0]}</option>
          )}
          {groups.map((g) => (
            <option key={g.value} value={g.value}>{`${g.value} (${g.count})`}</option>
          ))}
        </select>
      )}

      {component === "multiSelect" && (
        <>
          {values.length > 0 && (
            <div className="canvas-filter-chips">
              {values.map((v) => (
                <span key={v} className="canvas-filter-chip">
                  {v}
                  <button
                    type="button"
                    aria-label={`Remove ${v}`}
                    onClick={() => onWrite(
                      withValues(clauses, property, values.filter((x) => x !== v)), v, false)}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <select
            aria-label={`Add to ${label}`}
            value=""
            onChange={(e) => {
              const v = e.target.value;
              if (v) onWrite(withValues(clauses, property, [...values, v]), v, true);
            }}
          >
            <option value="">Add a value…</option>
            {groups.filter((g) => !values.includes(g.value)).map((g) => (
              <option key={g.value} value={g.value}>{`${g.value} (${g.count})`}</option>
            ))}
          </select>
        </>
      )}

      {component === "keyword" && !spec.syntax && (
        <input
          type="search"
          aria-label={label}
          placeholder="Starts with…"
          value={keywordOf(clauses, property)}
          onChange={(e) => onWrite(
            withKeyword(clauses, property, e.target.value), e.target.value,
            !!e.target.value.trim())}
        />
      )}
      {component === "keyword" && spec.syntax === "advanced" && (
        <AdvancedKeyword
          label={label}
          applied={keywordOf(clauses, property)}
          onApply={(text) => onWrite(
            withKeyword(clauses, property, text, true), text, !!text.trim())}
        />
      )}
      {/* `ontology` p.130: "You can search in the Ontology from Workshop
          using the filter list" - a regular expression (§728), the whole
          value, applied once it parses. */}
      {component === "keyword" && spec.syntax === "regex" && (
        <AdvancedKeyword
          label={label}
          applied={keywordOf(clauses, property)}
          problemOf={regexProblem}
          testId="filter-keyword-regex"
          placeholder=".*pump.*"
          onApply={(text) => onWrite(
            withKeyword(clauses, property, text, "regex"), text, !!text.trim())}
        />
      )}

      {component === "distribution" && (() => {
        const bars = distribution.data?.buckets ?? [];
        const integer = distribution.data?.integer ?? false;
        const max = Math.max(0, ...bars.map((b) => b.count));
        return (
          <>
            {distribution.isError && (
              <p className="canvas-widget-empty">Couldn&apos;t read this property&apos;s range.</p>
            )}
            {distribution.data && bars.length === 0 && (
              <p className="canvas-widget-empty">no numbers</p>
            )}
            <div className="canvas-filter-distribution" role="group" aria-label={label}>
              {bars.map((bar) => {
                const name = bucketLabel(bar, integer);
                const chosen = isBucketChosen(clauses, property, bar);
                return (
                  <button
                    key={`${bar.low}-${bar.high}`}
                    type="button"
                    className="canvas-filter-column"
                    aria-pressed={chosen}
                    aria-label={`${name}: ${bar.count}`}
                    title={`${name}: ${bar.count}`}
                    onClick={() => onWrite(
                      withBucket(clauses, property, chosen ? null : bar), name, !chosen)}
                  >
                    <span style={{ height: `${barWidth(bar.count, max)}%` }} />
                  </button>
                );
              })}
            </div>
            {bars.length > 0 && (
              <div className="canvas-filter-axis" aria-hidden>
                {axisEnds(bars, integer).map((end, i) => <span key={i}>{end}</span>)}
              </div>
            )}
            {!!distribution.data?.missing && (
              <p className="canvas-widget-empty">{distribution.data.missing} with no value</p>
            )}
          </>
        );
      })()}

      {component === "timeline" && (() => {
        const periods = timeline.data?.points ?? [];
        const interval = timelineIntervalOf(timeline.data?.interval);
        const max = Math.max(0, ...periods.map((p) => p.count));
        const first = periods[0];
        const last = periods[periods.length - 1];
        return (
          <>
            {timeline.isError && (
              <p className="canvas-widget-empty">Couldn&apos;t read this property&apos;s dates.</p>
            )}
            {timeline.data && periods.length === 0 && (
              <p className="canvas-widget-empty">no dates</p>
            )}
            <div className="canvas-filter-distribution" role="group" aria-label={label}>
              {periods.map((period) => {
                const name = periodLabel(period.start, interval);
                const chosen = isPeriodChosen(clauses, property, period.start, interval);
                return (
                  <button
                    key={period.start}
                    type="button"
                    className="canvas-filter-column"
                    aria-pressed={chosen}
                    aria-label={`${name}: ${period.count}`}
                    title={`${name}: ${period.count}`}
                    // A period is a date range, written as one: both of its
                    // days in, and the same clauses the range picker reads.
                    onClick={() => onWrite(
                      withRange(clauses, property,
                        chosen ? { from: "", to: "" } : periodOf(period.start, interval)),
                      name, !chosen)}
                  >
                    <span style={{ height: `${barWidth(period.count, max)}%` }} />
                  </button>
                );
              })}
            </div>
            {first && last && (
              <div className="canvas-filter-axis" aria-hidden>
                <span>{periodLabel(first.start, interval)}</span>
                <span>{periodLabel(last.start, interval)}</span>
              </div>
            )}
            {!!timeline.data?.missing && (
              <p className="canvas-widget-empty">{timeline.data.missing} with no date</p>
            )}
          </>
        );
      })()}

      {component === "date" && (
        <input
          type="date"
          aria-label={label}
          value={rangeOf(clauses, property).from}
          // One day, both ends in: the range's rule with the same day twice.
          onChange={(e) => onWrite(
            withRange(clauses, property, { from: e.target.value, to: e.target.value }),
            e.target.value, !!e.target.value)}
        />
      )}

      {component === "dateRange" && (() => {
        const range = rangeOf(clauses, property);
        const change = (next: DayRange) => onWrite(
          withRange(clauses, property, next), `${next.from}..${next.to}`,
          !!(next.from || next.to));
        return (
          <div className="canvas-filter-range">
            <input
              type="date"
              aria-label={`${label} from`}
              value={range.from}
              onChange={(e) => change({ ...range, from: e.target.value })}
            />
            <span aria-hidden>–</span>
            <input
              type="date"
              aria-label={`${label} to`}
              value={range.to}
              onChange={(e) => change({ ...range, to: e.target.value })}
            />
          </div>
        );
      })()}
    </fieldset>
  );
}

CanvasFilterList.craft = {
  displayName: "Filter list",
  props: {
    objectSetVariable: null, variable: null, properties: "", filters: null, title: "Filters",
    userEditable: false, layout: "vertical", linkDisplay: "inline", collapseLinked: false,
  },
  related: { settings: settingsPanel("FilterListSettings") },
};

// ---- User Select (parity workshop.md §10; Foundry p.477-478) ---------------
/**
 * p.477: "Use the User Select widget for selection of user(s) through a single
 * or multi-select dropdown menu."
 *
 * **The first widget whose options are people rather than data.** Everything
 * else in this file reads an object set; this reads the organisation's
 * directory, which was already open to every member — `GET /org/members` has
 * been viewer-visible since the org routes were written, on the reasoning that
 * emails within one org are not sensitive to it. So the widget needs no new
 * access boundary and creates none.
 *
 * **The output's *shape* is the setting**, which no other picker here does.
 * p.478 makes Single a `string` variable holding one id and Multiple a
 * `string[]` holding several, so the mode decides what kind of variable an
 * author binds and what every downstream reader sees. The panel offers the
 * matching kind for the mode rather than both, because a widget writing an
 * array into a string variable is refused on save and one writing a string into
 * an array variable looks fine and reads wrong.
 *
 * **p.478's group filter is built rather than refused**: this platform has
 * groups of its own (migration 0001) and the setting's shape carries over
 * exactly. What does not carry over is Foundry's "View group membership"
 * permission note, which is about a boundary this platform does not draw.
 *
 * The widget **does not ask the directory** while a configured group filter
 * names nobody — see `shouldAsk`, and the note on `orgMembers` for why the
 * server cannot make that decision.
 */
export function CanvasUserSelect({
  variable = null,
  groupsVariable = null,
  mode = "single",
  allowClear = false,
  label = "",
  placeholder = "",
}: {
  /** p.478's Output variable — a string, or a string array in Multiple. */
  variable?: string | null;
  /** p.478's "Specify Multipass group IDs": a string-array variable. */
  groupsVariable?: string | null;
  mode?: string;
  /** p.478's Allow clear, Single only. */
  allowClear?: boolean;
  label?: string;
  placeholder?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { mode: runMode } = useCanvasEnv();
  const { set } = useCanvasParameters();
  const chosen = useCanvasParameter(variable);
  const groupIds = userGroupIdsOf(useCanvasVariable(groupsVariable));
  const [open, setOpen] = useState(false);

  const multiple = userIsMultiple(mode);
  const ask = userShouldAsk(!!groupsVariable, groupIds);
  const directory = useQuery({
    // The group ids are part of the key: two filters are two different lists,
    // and an array compares by identity in a query key, so a fresh one each
    // render would refetch every time (§40's lesson on `useSetPage`).
    queryKey: ["org-members", (groupIds ?? []).join(",")],
    queryFn: () => api.orgMembers(groupIds ?? undefined),
    enabled: ask,
  });

  const users = usersOf(directory.data);
  const selected = userSelectedIds(chosen, mode);
  const text = userPlaceholderOf(placeholder, mode);
  const heading = userTextOf(label);
  const live = runMode === "run";

  const write = (ids: string[]) => {
    if (variable) set(variable, userToOutput(ids, mode));
  };

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {heading ? (
        <p className="field-label" data-testid="user-select-label">{heading}</p>
      ) : null}
      {!variable ? (
        <p className="canvas-widget-empty">
          User select — choose the variable it writes in Settings
        </p>
      ) : (
        <div className="canvas-dropdown">
          <button
            type="button"
            className="canvas-dropdown-toggle"
            data-testid="user-select-toggle"
            disabled={!live}
            onClick={() => setOpen((o) => !o)}
          >
            <span data-testid="user-select-value">
              {userSummaryOf(selected, users, text)}
            </span>
          </button>
          {/* p.478's Allow clear, Single only: in Multiple, unticking is how a
              selection goes away, so a second control would be a second answer
              to one question. */}
          {!multiple && userAllowClearOf(allowClear) && selected.length > 0 && live && (
            <button
              type="button"
              className="btn quiet"
              data-testid="user-select-clear"
              onClick={() => write([])}
            >
              Clear
            </button>
          )}
          {open && live && (
            <div className="canvas-dropdown-panel" data-testid="user-select-list">
              {!ask && (
                <p className="canvas-widget-empty" data-testid="user-select-unfiltered">
                  No groups chosen yet — nobody to show.
                </p>
              )}
              {ask && directory.isError && (
                <p className="canvas-widget-empty">Couldn&apos;t read the directory.</p>
              )}
              {ask && directory.data && users.length === 0 && (
                <p className="canvas-widget-empty" data-testid="user-select-none">
                  No users to choose from.
                </p>
              )}
              {users.map((user) => (
                <button
                  type="button"
                  key={user.id}
                  className={`canvas-dropdown-option${multiple ? " canvas-object-tick" : ""}`}
                  data-testid="user-select-option"
                  data-user={user.id}
                  aria-pressed={selected.includes(user.id)}
                  onClick={() => {
                    if (multiple) {
                      write(userToggled(selected, user.id));
                      return;
                    }
                    write(userPickedSingle(user.id));
                    setOpen(false);
                  }}
                >
                  {/* The Object Selector's tick, reused rather than restyled —
                      `canvas-object-tick` carries §211's naming fix and §204's
                      collision with it. The list itself is the Object
                      Dropdown's `canvas-dropdown-panel`, which is absolutely
                      positioned for §195's reason: a list that reflows the page
                      moves the control out from under the pointer that opened
                      it, and the browser never sends the click. */}
                  {multiple && (
                    <input
                      type="checkbox"
                      readOnly
                      checked={selected.includes(user.id)}
                      tabIndex={-1}
                    />
                  )}
                  <span className="canvas-dropdown-title">{userLabelOf(user)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

CanvasUserSelect.craft = {
  displayName: "User select",
  props: {
    variable: null, groupsVariable: null, mode: "single",
    allowClear: false, label: "", placeholder: "",
  },
  related: { settings: settingsPanel("UserSelectSettings") },
};

// ---- Exploration Filter Pills (parity workshop.md §10; Foundry p.470-471) --
/**
 * p.470: "Use the Exploration Filter Pills widget to visualize and apply filters
 * to an object set."
 *
 * **The first widget that reads a set's filters rather than writing them.**
 * Every narrowing widget before it wrote one shape of clause and knew which — a
 * Filter List writes `eq`/`in`, a Search writes `starts_with`, a Prominent Terms
 * widget writes `eq`. This one renders whatever is there, which is why
 * `filter-clause.ts` exists.
 *
 * **The data layer was already built and nobody had used it.** A set variable
 * resolves to a *definition*, and `workshop_variables._narrow_set` returns
 * `{...base, filters: [...base.filters, ...clauses]}` — a flat, effective filter
 * list. So "what filters are on this set" needs no endpoint; it is the resolved
 * variable the widget is already reading. A traversal resets `filters` to `[]`
 * and keeps the base under `via`, which is correct here rather than incidental:
 * p.470 says "an object set containing a single object type", and after a
 * traversal the earlier clauses are about the *other* type.
 *
 * **A pill the widget cannot remove does not offer to be.** The resolved list is
 * the base definition's own filters plus whatever `narrow_set` added, and only
 * the second kind lives in the variable this widget writes. The first is
 * structural — part of what the set *is* — so a remove button on it would write
 * a list that changes nothing while the pill sat there. §214's rule, and the
 * reason `isRemovable` takes the written list as well as the clause.
 *
 * **Divergence, stated rather than approximated: p.470's "Prevent users from
 * changing operators (or, and)" has nothing to prevent.** Every clause the
 * object-set language takes is an `and` — there is no `or` between filters, as
 * the Object Dropdown's search modes already record. A toggle governing a choice
 * nobody can make would be a control with no question behind it, so the panel
 * says so where the toggle would be.
 */
/** The pills themselves (§233), shared by the Filter Pills and p.472's
 * Exploration Search Bar (§577): each clause described, with p.470's edit
 * and remove where the mode allows them and the widget wrote the clause. */
function FilterPillItems({ pills, written, declared, mode, editable, commit, links = [] }: {
  pills: Clause[];
  written: Clause[];
  declared: { api_name: string; display_name?: string | null; data_type?: string | null }[];
  mode: string;
  editable: boolean;
  commit: (next: Clause[]) => void;
  /** The type's links, so a `has_link` pill names its link (§578). */
  links?: SearchLink[];
}) {
  const describeClause = (clause: Clause, props: typeof declared) =>
    describeLinked(clause, links) ?? describeFilterClause(clause, props);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  return (
    <>
      {pills.map((clause, index) => {
        const removable = isRemovable(clause, written);
        const beingEdited = editing === index;
        return (
          <span
            className={`canvas-pill${removable ? "" : " is-fixed"}`}
            key={`${clause.property}:${clause.op}:${index}`}
            data-testid="filter-pill"
            data-removable={removable ? "true" : "false"}
          >
            {beingEdited ? (
              <>
                <span className="canvas-pill-text">
                  {describeClause({ ...clause, value: null }, declared)}
                </span>
                <input
                  type="text"
                  className="canvas-pill-input"
                  value={draft}
                  autoFocus
                  data-testid="filter-pill-input"
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter" && e.key !== "Escape") return;
                    if (e.key === "Enter") {
                      commit(withValue(written, clause, parseValue(clause.op, draft)));
                    }
                    setEditing(null);
                  }}
                  onBlur={() => setEditing(null)}
                />
              </>
            ) : (
              <span className="canvas-pill-text" data-testid="filter-pill-text">
                {describeClause(clause, declared)}
              </span>
            )}
            {/* p.470's Update mode. A pill the widget did not write cannot
                be edited either — the edit goes into the same list the
                removal would. */}
            {canEdit(mode) && editable && removable && isEditable(clause)
              && !beingEdited && (
              <button
                type="button"
                className="canvas-pill-btn"
                data-testid="filter-pill-edit"
                onClick={() => {
                  setDraft(editableValue(clause));
                  setEditing(index);
                }}
              >
                edit
              </button>
            )}
            {canRemove(mode) && editable && removable && (
              <button
                type="button"
                className="canvas-pill-btn"
                aria-label={`Remove ${describeClause(clause, declared)}`}
                data-testid="filter-pill-remove"
                onClick={() => commit(without(written, clause))}
              >
                ✕
              </button>
            )}
          </span>
        );
      })}
    </>
  );
}

export function CanvasFilterPills({
  objectSetVariable = null,
  variable = null,
  mode = "read_only",
  showTypePill = false,
  title = "",
}: {
  /** p.470's specified object set — the one whose filters are drawn. */
  objectSetVariable?: string | null;
  /** p.470's optional output: "an object set filter variable containing the
   * applied filters". Optional in the spec and *required* for the three
   * editable modes here, because without it an edit has nowhere to go. */
  variable?: string | null;
  /** p.470's Mode. */
  mode?: string;
  /** p.471's Display object type pill. */
  showTypePill?: boolean;
  title?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, mode: runMode } = useCanvasEnv();
  const { set } = useCanvasParameters();
  const setDefinition = useCanvasVariable(objectSetVariable);
  // **The *resolved* variable, not the parameter.** `useCanvasParameter` holds
  // only what somebody has set this session, so a variable carrying a default —
  // which is how an app opens with filters already applied — would read as
  // empty, and every pill would look structural and lose its ✕. The resolved
  // value is what `narrow_set` actually consumed, which is the list these pills
  // are describing.
  const written = clausesOf(useCanvasVariable(variable));
  const [adding, setAdding] = useState<{ property: string; op: string; value: string }>(
    { property: "", op: "eq", value: "" },
  );

  const resolved = (setDefinition ?? null) as { object_type_id?: string } | null;
  const typeId = resolved?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const declared = type.data?.properties ?? [];
  const pills = clausesOf((setDefinition as { filters?: unknown })?.filters);

  const live = runMode === "run";
  const editable = live && !!variable;
  const commit = (next: ReturnType<typeof clausesOf>) => {
    if (variable) set(variable, next);
  };

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {title ? <p className="field-label">{title}</p> : null}
      {!objectSetVariable ? (
        <p className="canvas-widget-empty">
          Filter pills — choose the object set whose filters to show, in Settings
        </p>
      ) : (
        <div className="canvas-pills" data-testid="filter-pills">
          {showTypePill && (
            // p.471's Display object type pill. Named from the ontology rather
            // than from the definition, because the definition holds an id.
            <span className="canvas-pill is-type" data-testid="filter-pill-type">
              {type.data?.display_name || type.data?.api_name || "Object type"}
            </span>
          )}
          {pills.length === 0 && (
            <span className="canvas-widget-empty" data-testid="filter-pills-none">
              No filters applied
            </span>
          )}
          <FilterPillItems
            pills={pills} written={written} declared={declared} mode={mode}
            editable={editable} commit={commit}
          />
          {canAdd(mode) && editable && (
            <span className="canvas-pill is-add" data-testid="filter-pill-add">
              <select
                value={adding.property}
                data-testid="filter-add-property"
                onChange={(e) => {
                  const property = e.target.value;
                  const allowed = operatorsFor(
                    declared.find((p) => p.api_name === property)?.data_type,
                  );
                  // The operator is reset when it is no longer offered: a
                  // `gte` left over from a numeric property, applied to a
                  // string, is a 422 the viewer did not ask for.
                  // Back to `eq` rather than to the first of the allowed list:
                  // `eq` is in every list `operatorsFor` returns, so it is the
                  // one fallback that needs no index and cannot be undefined.
                  setAdding((a) => ({
                    property,
                    op: allowed.includes(a.op) ? a.op : "eq",
                    value: a.value,
                  }));
                }}
              >
                <option value="">Add a filter…</option>
                {declared.map((p) => (
                  <option key={p.api_name} value={p.api_name}>
                    {p.display_name || p.api_name}
                  </option>
                ))}
              </select>
              {!!adding.property && (
                <>
                  <select
                    value={adding.op}
                    data-testid="filter-add-op"
                    onChange={(e) => setAdding((a) => ({ ...a, op: e.target.value }))}
                  >
                    {operatorsFor(
                      declared.find((p) => p.api_name === adding.property)?.data_type,
                    ).map((op) => (
                      <option key={op} value={op}>{OPERATOR_LABELS[op]}</option>
                    ))}
                  </select>
                  <input
                    type="text"
                    className="canvas-pill-input"
                    value={adding.value}
                    placeholder={adding.op === "in" ? "a, b, c" : "value"}
                    data-testid="filter-add-value"
                    onChange={(e) => setAdding((a) => ({ ...a, value: e.target.value }))}
                  />
                  <button
                    type="button"
                    className="canvas-pill-btn"
                    data-testid="filter-add-apply"
                    // A blank value is not a filter: `eq ""` matches the rows
                    // whose property is the empty string, which is never what
                    // an unfinished row means.
                    disabled={!adding.value.trim()}
                    onClick={() => {
                      commit([...written, {
                        property: adding.property,
                        op: adding.op,
                        value: parseValue(adding.op, adding.value),
                      }]);
                      setAdding({ property: "", op: "eq", value: "" });
                    }}
                  >
                    Apply
                  </button>
                </>
              )}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

CanvasFilterPills.craft = {
  displayName: "Filter pills",
  props: {
    objectSetVariable: null, variable: null,
    mode: "read_only", showTypePill: false, title: "",
  },
  related: { settings: settingsPanel("FilterPillsSettings") },
};

// ---- Exploration Search Bar (parity workshop.md §10; Foundry p.472-473) -----
/**
 * p.472-473's Exploration Search Bar (§577): the Filter Pills (§233) with a
 * field in front of them. What is typed is offered back as a keyword search
 * in each string property and as the properties whose names hold it
 * (`search-bar.ts`); a property chosen asks for its value, with the values
 * the set holds suggested as the reader types. Every filter goes into the
 * same clause list the pills read, so p.472's four modes mean what they mean
 * there.
 */
export function CanvasSearchBar({
  objectSetVariable = null,
  variable = null,
  mode = "add",
  showTypePill = false,
  placeholder = "",
  showClearButton = true,
  fillWidth = true,
  disableAutocomplete = false,
  disableKeyword = false,
  propertyScope = "visible",
  customProperties = [],
  showHelpIcon = false,
  icon = "",
  linkScope = "all",
  customLinks = [],
}: {
  /** p.472's specified object set. */
  objectSetVariable?: string | null;
  /** p.472's optional output: the filter variable the bar writes. */
  variable?: string | null;
  mode?: string;
  /** p.473's Display object type pill. */
  showTypePill?: boolean;
  placeholder?: string;
  showClearButton?: boolean;
  /** p.473's Fill entire container width. */
  fillWidth?: boolean;
  disableAutocomplete?: boolean;
  disableKeyword?: boolean;
  /** p.473's Property types available, and for Custom the list. */
  propertyScope?: string;
  customProperties?: string[];
  /** p.473's Show search help icon: the query syntax, said in place, since
   * there is no documentation site here to link to. */
  showHelpIcon?: boolean;
  /** p.473's Icon: a name from the icon set or typed characters (§706). */
  icon?: string;
  /** p.473's Link types available (§578), and for Custom list the links. */
  linkScope?: string;
  customLinks?: string[];
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, mode: runMode } = useCanvasEnv();
  const { set } = useCanvasParameters();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const written = clausesOf(useCanvasVariable(variable));
  const typeId = (setDefinition as { object_type_id?: string } | null)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const declared = type.data?.properties ?? [];
  const offered = availableProperties(declared, propertyScopeOf(propertyScope), customProperties ?? []);
  // p.472's "filtering with linked object types and their properties" (§578).
  const typeLinks = useQuery({
    queryKey: ["type-links", typeId],
    queryFn: () => objApi.typeLinks(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const allLinks = typeLinks.data ?? [];
  const links = availableLinks(allLinks, linkScopeOf(linkScope), customLinks ?? []);
  const pills = clausesOf((setDefinition as { filters?: unknown })?.filters);
  const editable = runMode === "run" && !!variable;
  const adds = editable && canAdd(mode);
  const commit = (next: Clause[]) => {
    if (variable) set(variable, next);
  };

  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // Whether the reader has arrowed to a suggested value: Enter takes it then,
  // and what was typed otherwise - a typed "25" is not the first suggestion.
  const [browsed, setBrowsed] = useState(false);
  // A link chosen from the menu (§578), whose objects the next filter is on.
  const [pickedLink, setPickedLink] = useState<(typeof links)[number] | null>(null);
  // A property chosen from the menu, whose value is being typed: the bar's
  // own type's, or the chosen link's far type's.
  const [picked, setPicked] = useState<{ property: string; op: string } | null>(null);
  const [helping, setHelping] = useState(false);
  const farType = useQuery({
    queryKey: ["object-type", pickedLink?.far_type_id],
    queryFn: () => objApi.getType(workspaceId, pickedLink!.far_type_id),
    enabled: !!pickedLink,
  });
  const farProperties = availableProperties(farType.data?.properties ?? [], "visible");
  const pickedProperty = (pickedLink ? farProperties : declared)
    .find((p) => p.api_name === picked?.property);
  const menu = picked || pickedLink ? []
    : searchMenu(text, offered, { keyword: !disableKeyword }, links);
  const linkEntries = pickedLink && !picked ? linkMenu(text, pickedLink, farProperties) : [];
  const suggestBase = pickedLink ? { object_type_id: pickedLink.far_type_id, filters: [] } : setDefinition;
  const suggestFrom = picked ? suggestionDefinition(suggestBase, picked.property, text) : null;
  const suggest = useQuery({
    queryKey: ["search-bar-values", JSON.stringify(suggestFrom), picked?.property],
    queryFn: () => objApi.groupObjectSet(workspaceId, suggestFrom, picked!.property,
      { limit: MAX_SUGGESTED }),
    enabled: !!picked && !disableAutocomplete && !!setDefinition,
    placeholderData: (previous) => previous,
  });
  // With autocomplete off the query never runs, so there is nothing to
  // suggest (a second check here survived the sweep as equivalent).
  const suggestions = picked ? suggestionsOf(suggest.data?.groups ?? [], text) : [];

  const reset = () => {
    setText("");
    setPicked(null);
    setPickedLink(null);
    setActive(0);
    setBrowsed(false);
  };
  const choose = (entry: MenuEntry) => {
    if (entry.kind === "keyword") {
      commit(withKeyword(written, entry.property, text.trim(), true));
      reset();
      setOpen(false);
    } else {
      if (entry.kind === "link") {
        setPickedLink(links.find((l) => l.link_type_id === entry.link) ?? null);
      } else {
        setPicked({ property: entry.property, op: "eq" });
      }
      setText("");
      setActive(0);
      // Arrowing through the menu is not arrowing to a value.
      setBrowsed(false);
    }
  };
  const chooseOnLink = (entry: LinkEntry) => {
    if (!pickedLink) return;
    if (entry.kind === "has_link") {
      commit(withHasLink(written, pickedLink.link_type_id, true));
      reset();
    } else {
      setPicked({ property: entry.property, op: "eq" });
      setText("");
      setActive(0);
    }
  };
  const apply = (value: string) => {
    if (!picked || !value.trim()) return;
    const clause = { property: picked.property, op: picked.op, value: parseValue(picked.op, value) };
    commit(pickedLink ? withLinkedFilter(written, pickedLink.link_type_id, clause) : [...written, clause]);
    reset();
  };

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectSetVariable ? (
        <p className="canvas-widget-empty">
          Search bar — choose the object set to search and filter, in Settings
        </p>
      ) : (
        <div
          className="canvas-search-bar"
          data-testid="search-bar"
          style={{ display: fillWidth ? "flex" : "inline-flex", flexWrap: "wrap", gap: 6,
            alignItems: "center", width: fillWidth ? "100%" : undefined }}
        >
          {icon ? <span aria-hidden="true" data-testid="search-bar-icon"><IconOrGlyph value={icon} /></span> : null}
          {showTypePill && (
            <span className="canvas-pill is-type" data-testid="filter-pill-type">
              {type.data?.display_name || type.data?.api_name || "Object type"}
            </span>
          )}
          <FilterPillItems
            pills={pills} written={written} declared={declared} mode={pillModeOf(mode)}
            editable={editable} commit={commit} links={allLinks}
          />
          {adds && pickedLink && (
            <span className="canvas-pill is-add" data-testid="search-bar-picked-link">
              {pickedLink.side_name}
            </span>
          )}
          {adds && picked && (
            <span className="canvas-pill is-add" data-testid="search-bar-picked">
              {pickedProperty?.display_name || picked.property}
              <select
                value={picked.op}
                aria-label="Operator"
                data-testid="search-bar-op"
                onChange={(e) => setPicked({ ...picked, op: e.target.value })}
              >
                {operatorsFor(pickedProperty?.data_type).map((op) => (
                  <option key={op} value={op}>{OPERATOR_LABELS[op]}</option>
                ))}
              </select>
            </span>
          )}
          {adds && (
            <span style={{ position: "relative", flex: fillWidth ? 1 : undefined, minWidth: 160 }}>
              <input
                type="text"
                className="canvas-pill-input"
                role="combobox"
                aria-expanded={open && (menu.length > 0 || suggestions.length > 0)}
                aria-label="Search"
                data-testid="search-bar-input"
                value={text}
                placeholder={picked ? "value" : searchPlaceholderOf(placeholder, !disableKeyword)}
                style={{ width: "100%" }}
                onFocus={() => setOpen(true)}
                onBlur={() => setOpen(false)}
                onChange={(e) => {
                  setText(e.target.value);
                  setActive(0);
                  setBrowsed(false);
                  setOpen(true);
                }}
                onKeyDown={(e) => {
                  const count = picked ? suggestions.length
                    : pickedLink ? linkEntries.length : menu.length;
                  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                    e.preventDefault();
                    setActive(browsed || !picked ? nextIndex(active, count, e.key) : 0);
                    setBrowsed(true);
                  } else if (e.key === "Enter") {
                    e.preventDefault();
                    if (picked) apply(browsed && suggestions[active] ? suggestions[active]!.value : text);
                    else if (pickedLink) {
                      if (linkEntries[active]) chooseOnLink(linkEntries[active]!);
                    } else if (menu[active]) choose(menu[active]!);
                  } else if (e.key === "Escape") {
                    reset();
                  } else if (e.key === "Backspace" && !text && picked) {
                    setPicked(null);
                  } else if (e.key === "Backspace" && !text && pickedLink) {
                    setPickedLink(null);
                  }
                }}
              />
              {open && (picked ? suggestions.length > 0
                : pickedLink ? linkEntries.length > 0 : menu.length > 0) && (
                <ul
                  role="listbox"
                  className="canvas-menu"
                  data-testid="search-bar-menu"
                  style={{ position: "absolute", zIndex: 5, left: 0, right: 0, margin: 0,
                    padding: 4, listStyle: "none", background: "var(--bg, #fff)",
                    border: "1px solid var(--line, #d0d7de)" }}
                >
                  {(picked
                    ? suggestions.map((g) => ({ key: g.value, label: `${g.value} (${g.count})`,
                        run: () => apply(g.value), kind: "value" }))
                    : pickedLink
                      ? linkEntries.map((m) => ({
                          key: m.kind === "has_link" ? m.kind : `${m.kind}:${m.property}`,
                          label: m.label, run: () => chooseOnLink(m), kind: m.kind }))
                      : menu.map((m) => ({
                          key: `${m.kind}:${m.kind === "link" ? m.link : m.property}`,
                          label: m.label, run: () => choose(m), kind: m.kind }))
                  ).map((item, n) => {
                    const on = picked ? browsed && n === active : n === active;
                    return (
                      <li
                        key={item.key}
                        role="option"
                        aria-selected={on}
                        data-testid="search-bar-option"
                        data-kind={item.kind}
                        style={{ padding: "2px 6px", cursor: "pointer",
                          background: on ? "var(--accent-wash)" : undefined }}
                        // Before the input's blur closes the menu.
                        onMouseDown={(e) => {
                          e.preventDefault();
                          item.run();
                        }}
                      >
                        {item.label}
                      </li>
                    );
                  })}
                </ul>
              )}
            </span>
          )}
          {!adds && pills.length === 0 && (
            <span className="canvas-widget-empty" data-testid="filter-pills-none">
              No filters applied
            </span>
          )}
          {showClearButton && editable && canRemove(mode) && written.length > 0 && (
            <button
              type="button"
              className="btn quiet"
              data-testid="search-bar-clear"
              onClick={() => commit([])}
            >
              Clear
            </button>
          )}
          {showHelpIcon && (
            <button
              type="button"
              className="btn quiet"
              aria-label="Search help"
              aria-expanded={helping}
              data-testid="search-bar-help"
              onClick={() => setHelping(!helping)}
            >
              ?
            </button>
          )}
          {showHelpIcon && helping && (
            <p className="field-hint" data-testid="search-bar-help-text" style={{ flexBasis: "100%" }}>
              Type to search a text property, or pick a property to filter on its value.
              A search matches words that start with what you type; join words with
              AND, OR and NOT, group them with brackets, and quote a phrase.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

CanvasSearchBar.craft = {
  displayName: "Exploration search bar",
  props: {
    objectSetVariable: null, variable: null, mode: "add", showTypePill: false,
    placeholder: "", showClearButton: true, fillWidth: true, disableAutocomplete: false,
    disableKeyword: false, propertyScope: "visible", customProperties: [], showHelpIcon: false,
    icon: "", linkScope: "all", customLinks: [],
  },
  related: { settings: settingsPanel("SearchBarSettings") },
};

// ---- Prominent Terms (parity workshop.md §10; Foundry p.475) ---------------
/**
 * p.475: "define prominently-used terms and phrases to match on within an object
 * set. Showcase the number of matched results, and use the widget as a way to
 * define a custom set of terms for users to apply as filters."
 *
 * **The Filter List with its list turned around.** That widget asks the data
 * what values exist and offers them; this one is handed the values by an author
 * and asks the data how many rows each accounts for. Everything downstream is
 * shared — the clause vocabulary, the `narrow_set` derivation, the read-back of
 * the selection — and the rules that are this widget's own live in
 * `prominent-terms.ts`.
 *
 * **One count per term, and it is not an optimisation waiting to happen.** The
 * Filter List gets every count in a single `/object-sets/group` call, which is
 * capped at `object_sets.MAX_GROUPS` and ordered by count — so a curated term
 * naming a rare value comes back *absent*, and absent would mean either "no
 * rows" or "not in the top twenty". p.475 hangs **Hide empty terms** on exactly
 * that distinction, so a grouped implementation would hide rows for being
 * unfashionable rather than unused, invisibly. `MAX_TERMS` is what keeps the
 * fan-out bounded instead.
 *
 * **A term naming a value no row has is the normal case, not an error.** It is
 * what the Filter List structurally cannot produce and what makes Hide empty
 * terms a setting worth having: an author writes the vocabulary they want the
 * viewer to think in, and the data says which parts of it are populated today.
 *
 * p.475's **Icon** is a name from the icon set or one or two typed characters
 * (§706), as every icon setting in this file is.
 */
export function CanvasProminentTerms({
  objectSetVariable = null,
  variable = null,
  property = "",
  terms = [],
  hideEmpty = false,
  title = "",
}: {
  /** p.475's Base object set. */
  objectSetVariable?: string | null;
  /** p.475's Filter variable — an array of clauses a `narrow_set` reads. */
  variable?: string | null;
  /** p.475's Property, the one every term filters on. */
  property?: string;
  /** p.475's Terms. */
  terms?: unknown[];
  /** p.475's Hide empty terms. */
  hideEmpty?: boolean;
  title?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, mode } = useCanvasEnv();
  const { set } = useCanvasParameters();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const chosen = useCanvasParameter(variable);

  const configured = renderableTerms(termsOf(terms));
  const selected = selectedValues(chosen, property);
  const ready = !!objectSetVariable && !!variable && !!property;

  const counts = useQueries({
    queries: configured.map((term) => ({
      queryKey: ["canvas-prominent-term", property, term.value,
                 JSON.stringify(setDefinition ?? null)],
      queryFn: () => objApi.aggregateObjectSet(
        workspaceId,
        // p.475's exact match, applied *on top of* the base set — a term
        // narrows what the set already says rather than replacing it.
        termClause(setDefinition, property, term.value),
        { aggregation: "count" },
      ),
      enabled: ready && !!setDefinition,
    })),
  });
  const byValue: Record<string, number | undefined> = {};
  configured.forEach((term, n) => {
    const value = counts[n]?.data?.value;
    byValue[term.value] = typeof value === "number" ? value : undefined;
  });
  const shown = visibleTerms(configured, byValue, hideEmpty);

  const pick = (value: string) => {
    if (!variable) return;
    set(variable, [
      // Clauses this widget did not write are kept: several widgets chain
      // through one `narrow_set`, and rewriting the whole variable would
      // silently drop another widget's filter (§40's shape, stated here
      // because this is the second widget to write into a shared list).
      ...(Array.isArray(chosen) ? chosen : []).filter(
        (c) => (c as { property?: unknown })?.property !== property,
      ),
      ...toClauses(property, toggled(selected, value)),
    ]);
  };

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {title ? <p className="field-label">{title}</p> : null}
      {!ready ? (
        <p className="canvas-widget-empty">
          Prominent terms — choose an object set, a property and the variable it
          writes in Settings
        </p>
      ) : configured.length === 0 ? (
        <p className="canvas-widget-empty">Add the terms to match on in Settings</p>
      ) : shown.length === 0 ? (
        // Every term answered zero and the setting hides them. Said rather than
        // rendered as a blank space, which reads as a widget that failed.
        <p className="canvas-widget-empty" data-testid="prominent-terms-all-empty">
          No term matches anything in this set
        </p>
      ) : (
        <ul className="canvas-terms" data-testid="prominent-terms">
          {shown.map((term) => (
            <li key={term.value}>
              <button
                type="button"
                className={`canvas-term${selected.includes(term.value) ? " is-on" : ""}`}
                data-testid="prominent-term"
                data-value={term.value}
                aria-pressed={selected.includes(term.value)}
                // In the builder the rows are shown but inert: clicking one
                // would write a viewer's filter into the document being edited.
                disabled={mode !== "run"}
                onClick={() => pick(term.value)}
              >
                {term.icon ? (
                  <span className="canvas-term-icon" aria-hidden="true"><IconOrGlyph value={term.icon} /></span>
                ) : null}
                <span className="canvas-term-label">{termLabelOf(term)}</span>
                <span className="canvas-term-count" data-testid="prominent-term-count">
                  {countLabel(byValue[term.value])}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The base set with one term's exact-match clause added.
 *
 * Built here rather than in `prominent-terms.ts` because it is about the shape
 * of an object-set *definition*, which every widget in this file shares and no
 * widget's model owns.
 */
function termClause(definition: unknown, property: string, value: string): unknown {
  const base = (definition ?? {}) as { filters?: unknown[] };
  return {
    ...(base as object),
    filters: [...(Array.isArray(base.filters) ? base.filters : []),
              { property, op: "eq", value }],
  };
}

CanvasProminentTerms.craft = {
  displayName: "Prominent terms",
  props: {
    objectSetVariable: null, variable: null, property: "",
    terms: [], hideEmpty: false, title: "",
  },
  related: { settings: settingsPanel("ProminentTermsSettings") },
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
  related: { settings: settingsPanel("ParameterSettings") },
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
              <span className="canvas-number-affix" aria-hidden="true" data-testid="numeric-prefix-shown">
                <IconOrGlyph value={prefix} max={40} />
              </span>
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
              <span className="canvas-number-affix" aria-hidden="true" data-testid="numeric-suffix-shown">
                <IconOrGlyph value={unit} max={40} />
              </span>
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

CanvasNumericInput.craft = {
  displayName: "Numeric input",
  props: {
    name: "", label: "", grouping: false, allowReset: false,
    prefix: "", suffix: "none", suffixText: "",
  },
  related: { settings: settingsPanel("NumericInputSettings") },
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
  autoSize = true,
}: {
  name?: string;
  label?: string;
  placeholder?: string;
  format?: string;
  rows?: number;
  /** p.466's Auto-sizing, for the Markdown format (§582). */
  autoSize?: boolean;
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
        shape.markdown ? (
          <MarkdownTextEditor
            label={label}
            text={text}
            placeholder={placeholder}
            autoSize={autoSize !== false}
            onText={write}
          />
        ) : (
        <label className="field" style={{ maxWidth: 420 }}>
          {label && <span className="field-label">{label}</span>}
          {shape.multiline
            ? <textarea {...shared} rows={rowsOf(rows)} />
            : <input type="text" {...shared} />}
        </label>
        )
      )}
    </div>
  );
}

/** p.466's Markdown editor (§582): the toolbar writes Markdown around the
 * selection (`markdown-editor.ts`), and the rich view is the Markdown widget's
 * own renderer, so it shows exactly what the toolbar wrote.
 *
 * **The rich view is edited in place (§789)**, p.466's "formatted preview
 * with inline editing": the rendering is `contentEditable`, and each edit is
 * read back as Markdown (`markdown-dom.ts`). It is drawn again only when the
 * text changes from elsewhere - the raw view, or the variable - since
 * redrawing under somebody's caret would move it. In the rich view the
 * toolbar is the browser's own editing commands, whose elements the reading
 * back knows. */
const RICH_COMMANDS: Record<MarkdownFormat, [string, string?]> = {
  bold: ["bold"],
  italic: ["italic"],
  strikethrough: ["strikeThrough"],
  code: ["code"],
  heading: ["formatBlock", "H1"],
  bullets: ["insertUnorderedList"],
  numbers: ["insertOrderedList"],
  quote: ["formatBlock", "BLOCKQUOTE"],
  link: ["createLink", "https://"],
};

function MarkdownTextEditor({ label, text, placeholder, autoSize, onText }: {
  label: string;
  text: string;
  placeholder: string;
  autoSize: boolean;
  onText: (next: string) => void;
}) {
  const [rich, setRich] = useState(false);
  const area = React.useRef<HTMLTextAreaElement | null>(null);
  const editable = React.useRef<HTMLDivElement | null>(null);
  // What the rich view last wrote, so its own edit is not drawn again.
  const wrote = React.useRef<string | null>(null);
  const [drawn, setDrawn] = useState({ text, epoch: 0 });
  useEffect(() => {
    if (text !== wrote.current && text !== drawn.text) {
      setDrawn((was) => ({ text, epoch: was.epoch + 1 }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  const readBack = () => {
    if (!editable.current) return;
    const next = markdownOf(editable.current);
    wrote.current = next;
    onText(next);
  };
  const press = (format: MarkdownFormat) => {
    if (rich) {
      const [command, value] = RICH_COMMANDS[format];
      editable.current?.focus();
      if (command === "code") {
        // No command makes code: the selection's text, as one code element.
        const selected = window.getSelection()?.toString() ?? "";
        const code = document.createElement("code");
        code.textContent = selected || "code";
        document.execCommand("insertHTML", false, code.outerHTML);
      } else {
        document.execCommand(command, false, value);
      }
      // The command's own input event reads it back.
      return;
    }
    const el = area.current;
    const out = applyFormat(text, el?.selectionStart ?? text.length,
      el?.selectionEnd ?? text.length, format);
    onText(out.text);
    // The selection is put back once the new text has rendered.
    requestAnimationFrame(() => {
      area.current?.focus();
      area.current?.setSelectionRange(out.start, out.end);
    });
  };
  return (
    <div className="field" data-testid="markdown-editor" style={{ maxWidth: 560 }}>
      {label && <span className="field-label">{label}</span>}
      <div className="row-actions" role="toolbar" aria-label="Formatting" style={{ gap: 4 }}>
        {FORMATS.map((format) => (
          <button
            key={format}
            type="button"
            className="btn quiet"
            data-testid={`md-${format}`}
            aria-label={FORMAT_LABELS[format]}
            title={FORMAT_LABELS[format]}
            // Before the text loses its selection to the button.
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => press(format)}
          >
            {FORMAT_LABELS[format]}
          </button>
        ))}
        <button
          type="button"
          className="btn quiet"
          data-testid="md-view"
          aria-pressed={rich}
          onClick={() => setRich(!rich)}
        >
          {/* p.466's own words for the two views. Not "Preview", which is the
              builder's own button a page already has (§582's first test run
              pressed this one instead). */}
          {rich ? "Markdown" : "Rich text"}
        </button>
      </div>
      {rich ? (
        <div
          key={drawn.epoch}
          ref={editable}
          data-testid="md-rich"
          className="canvas-markdown md-rich-edit"
          role="textbox"
          aria-multiline="true"
          aria-label={label || "Text input"}
          contentEditable
          suppressContentEditableWarning
          data-placeholder={placeholder || "Nothing written yet"}
          onInput={readBack}
        >
          {drawn.text.trim()
            ? <MarkdownView blocks={parseMarkdown(drawn.text, { breaks: true })} align="left" />
            : null}
        </div>
      ) : (
        <textarea
          ref={area}
          aria-label={label || "Text input"}
          data-testid="text-input"
          value={text}
          placeholder={placeholder}
          rows={autoSize ? autoRows(text) : 8}
          onChange={(e) => onText(e.target.value)}
        />
      )}
    </div>
  );
}

CanvasTextInput.craft = {
  displayName: "Text input",
  props: { name: "", label: "", placeholder: "", format: "line", rows: 4, autoSize: true },
  related: { settings: settingsPanel("TextInputSettings") },
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
  allowCreating = false,
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
  /** p.461's "Allow creating new options", for a Multiple dropdown (§579). */
  allowCreating?: boolean;
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

  // **Every write goes through here**, so every one fires `change`. The two
  // dropdowns wrote the variable straight and fired nothing, which left the
  // events panel offering a trigger half this widget's forms never pulled
  // (§579 found it).
  function write(next: string | string[] | null) {
    set(name, next);
    if (mode === "run" && changed.length > 0) {
      runEvents(changed, {
        ...eventContext,
        payload: { value: Array.isArray(next) ? next.join(", ") : next ?? "" },
      });
    }
  }
  function choose(option: string) {
    write(pick(selection, stored, option));
  }
  // p.461's user-created options (§579): they live in the selection itself.
  const creates = canCreate(selection, display, allowCreating);
  const created = creates ? createdOf(options, chosen) : [];
  const [typed, setTyped] = useState("");
  const addTyped = () => {
    if (!typed.trim()) return;
    write(withTyped(stored, typed));
    setTyped("");
  };

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
              onChange={(e) => write(e.target.value || null)}
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
              size={Math.min(6, Math.max(2, options.length + created.length))}
              value={chosen}
              onChange={(e) =>
                write([...e.target.selectedOptions].map((o) => o.value))}
            >
              {options.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
              {/* p.461: "Any user-created options will be italicized." */}
              {created.map((o) => (
                <option key={`created:${o}`} value={o} data-created="true"
                  style={{ fontStyle: "italic" }}>
                  {o}
                </option>
              ))}
            </select>
          )}
          {creates && (
            <span className="row-actions" style={{ gap: 6 }}>
              <input
                type="text"
                aria-label="New option"
                data-testid="selector-create-input"
                placeholder={text}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addTyped();
                  }
                }}
              />
              <button
                type="button"
                className="btn quiet"
                data-testid="selector-create"
                disabled={!typed.trim()}
                onClick={addTyped}
              >
                Add
              </button>
            </span>
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

          {options.length === 0 && !creates && (
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

CanvasStringSelector.craft = {
  displayName: "String selector",
  props: {
    name: "", label: "", selection: "single", display: "dropdown",
    optionSource: "static", options: [], optionsVariable: "",
    placeholder: "", allowClearing: true, layout: "vertical", columns: 3, allowCreating: false,
  },
  related: { settings: settingsPanel("StringSelectorSettings") },
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

CanvasDateTimePicker.craft = {
  displayName: "Date and time",
  props: {
    name: "", label: "", dateFormat: "iso", timeFormat: "h24",
    precision: "minute", zoneMode: "local", timezone: "UTC",
    timezoneVariable: "", zoneEditable: false,
  },
  related: { settings: settingsPanel("DateTimePickerSettings") },
};

// ---- Date Input (p.444) --------------------------------------------------------
/** p.444's Date Input: "Allow the user to enter a single data or date range."
 *
 * A single date writes `name`. A range writes `name` as its start and
 * `endVariable` as its end, **both on every change**, in order (`date-input.ts`),
 * so the pair cannot disagree the way two separate pickers could. */
export function CanvasDateInput({
  name = "",
  endVariable = "",
  label = "",
  mode = "single",
}: {
  name?: string;
  endVariable?: string;
  label?: string;
  mode?: string;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { mode: env } = useCanvasEnv();
  const { values, set } = useCanvasParameters();
  const { events: moduleEvents } = useCanvasVariables();
  const range = mode === "range";
  const start = name ? values[name] : undefined;
  const end = endVariable ? values[endVariable] : undefined;

  const changed = eventsFor(moduleEvents, nodeId, "change");
  const overlayIds = useOverlayIds();
  const eventContext = useEventContext(undefined, overlayIds);

  function announce(value: string) {
    if (env === "run" && changed.length > 0) {
      runEvents(changed, { ...eventContext, payload: { value } });
    }
  }

  function writeSingle(text: string) {
    // A date input gives a whole day or "" for cleared; cleared is unset.
    set(name, text || null);
    announce(text);
  }

  function writeRange(nextStart: string, nextEnd: string) {
    const [s, e] = orderedRange(nextStart, nextEnd);
    set(name, s);
    set(endVariable, e);
    announce(`${s ?? ""}/${e ?? ""}`);
  }

  const unbound = !name || (range && !endVariable);
  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {unbound ? (
        <p className="canvas-widget-empty">
          {range
            ? "Date range - bind a start and an end date variable in Settings"
            : "Date input - bind a date variable in Settings"}
        </p>
      ) : range ? (
        <div className="field canvas-date-range" style={{ maxWidth: 420 }}>
          {label && <span className="field-label">{label}</span>}
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="date"
              aria-label={`${label || "Date range"} from`}
              data-testid="date-range-start"
              value={shownDay(start)}
              onChange={(e) => writeRange(e.target.value, shownDay(end))}
            />
            <input
              type="date"
              aria-label={`${label || "Date range"} to`}
              data-testid="date-range-end"
              value={shownDay(end)}
              onChange={(e) => writeRange(shownDay(start), e.target.value)}
            />
          </div>
          {rangeText(start, end) && (
            <span className="field-hint" data-testid="date-range-text">{rangeText(start, end)}</span>
          )}
        </div>
      ) : (
        <div className="field" style={{ maxWidth: 240 }}>
          {label && <span className="field-label">{label}</span>}
          <input
            type="date"
            aria-label={label || "Date"}
            data-testid="date-input"
            value={shownDay(start)}
            onChange={(e) => writeSingle(e.target.value)}
          />
        </div>
      )}
    </div>
  );
}

CanvasDateInput.craft = {
  displayName: "Date input",
  props: { name: "", endVariable: "", label: "", mode: "single" },
  related: { settings: settingsPanel("DateInputSettings") },
};

// ---- Markdown -------------------------------------------------------------------
export function CanvasMarkdown({
  source = "text",
  text = "",
  textVariable = "",
  monospace = false,
  scrolling = false,
  wordWrap = true,
  breaks = true,
  alignment = "left",
  tagType = "standard",
  selectedVariable = null,
  referenceTypes = [],
  selectionBehavior = "last",
  selectedTextVariable = null,
  selectionStartVariable = null,
  selectionEndVariable = null,
  annotationLayers = [],
  annotationFormat = "highlight",
  selectedAnnotationVariable = null,
  annotationTooltip = "",
  highlightActions = [],
  hoverActions = [],
}: {
  source?: string;
  text?: string;
  textVariable?: string;
  monospace?: boolean;
  scrolling?: boolean;
  wordWrap?: boolean;
  breaks?: boolean;
  alignment?: string;
  /** p.316's Tag type configuration (§632): `standard`, or
   * `inline_reference` for p.319's anchors. */
  tagType?: string;
  /** p.320's Selected object set: the output, as selection clauses. */
  selectedVariable?: string | null;
  /** p.320's Object types, each with its highlight colour. */
  referenceTypes?: unknown;
  /** p.320's Selection behavior. */
  selectionBehavior?: string;
  /** p.317's User text selection (§636): the selected raw Markdown, and its
   * start and end indices in the source. */
  selectedTextVariable?: string | null;
  selectionStartVariable?: string | null;
  selectionEndVariable?: string | null;
  /** p.321-322's annotations (§637), with Tag type `annotation`: the layers,
   * how they are drawn, the selected annotation's output and the properties
   * its tooltip shows (comma-separated). */
  annotationLayers?: unknown;
  annotationFormat?: string;
  selectedAnnotationVariable?: string | null;
  annotationTooltip?: string;
  /** p.322's Create annotations via actions or events (§638): what is offered
   * on highlighted text, each a click the Events panel wires. */
  highlightActions?: unknown;
  /** p.322's On hover interactions (§669): what an annotation's hover card
   * offers, each a click the Events panel wires. */
  hoverActions?: unknown;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { resolved, events: moduleEvents } = useCanvasVariables();
  const { mode } = useCanvasEnv();
  const { values: parameterValues, set: setParameter } = useCanvasParameters();
  const overlayIds = useOverlayIds();
  const eventContext = useEventContext(undefined, overlayIds);
  // p.320's "most recently selected anchor text", by its place in the text.
  const [lastAnchor, setLastAnchor] = useState<number | null>(null);

  const raw = markdownTextOf(
    source, text, textVariable ? resolved[textVariable] : undefined,
  );
  // **`{{v_id}}` is expanded in typed text only.** It is what `CanvasText` does
  // and what an author moving to this widget will expect to keep working. It is
  // deliberately *not* done to text arriving from a variable: that text is data,
  // and data that can name variables is data that reads them.
  const filled = markdownSourceOf(source) === "text" ? interpolate(raw, resolved) : raw;
  const widgetAlign = alignmentOf(alignment);
  const references = tagType === "inline_reference";
  // p.317's outputs need to know where each character came from (§636).
  const offered = itemsOf(highlightActions);
  // The text highlighted now, for p.322's actions on it (§638).
  const [highlighted, setHighlighted] = useState<
    { text: string; start: number; end: number } | null>(null);
  const selecting = !!(selectedTextVariable || selectionStartVariable || selectionEndVariable)
    || offered.length > 0;
  // p.321's annotations (§637): each layer's objects read, and drawn over the
  // runs their indices name.
  const annotating = tagType === "annotation";
  // p.321 names no limit; one read per layer, of as many objects as a read
  // returns. More than that are counted and said, not silently left out.
  const ANNOTATIONS_READ = 200;
  const layers = annotating ? annotationLayersOf(annotationLayers) : [];
  const { workspaceId } = useCanvasEnv();
  const layerReads = useQueries({
    queries: layers.map((layer) => ({
      queryKey: ["canvas-markdown-annotations", layer.objectSetVariable,
        JSON.stringify(layer.objectSetVariable ? resolved[layer.objectSetVariable] ?? null : null)],
      queryFn: () => objApi.evaluateObjectSet(
        workspaceId, resolved[layer.objectSetVariable!], { limit: ANNOTATIONS_READ }),
      enabled: !!layer.objectSetVariable && resolved[layer.objectSetVariable] !== undefined
        && !!layer.startProperty && !!layer.endProperty,
    })),
  });
  const read = layers.map((layer, n) =>
    annotationsOf(n, layer, layerReads[n]?.data?.instances ?? []));
  const annotations = read.flatMap((r) => r.annotations);
  const unreadable = read.reduce((sum, r) => sum + r.unreadable, 0);
  const beyond = layerReads.reduce((sum, r) =>
    sum + Math.max(0, (r.data?.total ?? 0) - (r.data?.instances.length ?? 0)), 0);
  const selectedAnnotations = keysOf(
    selectedAnnotationVariable ? parameterValues[selectedAnnotationVariable] : undefined);
  const tooltipProps = annotationTooltip.split(",").map((p) => p.trim()).filter(Boolean);
  const format = annotationFormatOf(annotationFormat);
  // p.322's On hover interactions (§669): the hovered annotation, and where
  // its card goes, below the words, inside the widget.
  const hovering = annotating ? hoverActionsOf(hoverActions) : [];
  const [hovered, setHovered] = useState<
    { annotation: (typeof annotations)[number]; left: number; top: number } | null>(null);
  const drawRun = (runText: string, runAt: number) => annotatedPieces(runText, runAt, annotations)
    .map((piece) => {
      if (piece.covering.length === 0) {
        return <span key={piece.at} data-at={piece.at}>{piece.text}</span>;
      }
      // The first annotation covering a piece is the one a click selects;
      // the tooltip names every one.
      const top = piece.covering[0]!;
      // p.322's Highlight color, static or by the layer's rules (§669).
      const color = annotationColorOf(layers[top.layer]!, top);
      const on = piece.covering.some((a) => selectedAnnotations.includes(a.key));
      return (
        <mark
          key={piece.at}
          data-at={piece.at}
          data-testid="markdown-annotation"
          data-annotation={piece.covering.map((a) => a.key).join(" ")}
          className={`canvas-markdown-annotation fmt-${format}${on ? " on" : ""}`}
          style={color ? ({ "--annotation-color": color } as React.CSSProperties) : undefined}
          data-color={color ?? undefined}
          // With hover interactions the card is the tooltip, properties and all.
          title={hovering.length > 0 ? undefined
            : piece.covering.map((a) => tooltipOf(a, tooltipProps)).filter(Boolean).join("\n\n") || undefined}
          aria-pressed={on}
          onMouseEnter={hovering.length > 0 ? (e) => {
            const box = containerRef.current?.getBoundingClientRect();
            const mark = e.currentTarget.getBoundingClientRect();
            setHovered({ annotation: top, left: mark.left - (box?.left ?? 0), top: mark.bottom - (box?.top ?? 0) });
          } : undefined}
          onClick={() => {
            if (selectedAnnotationVariable) {
              setParameter(selectedAnnotationVariable, selectionClauses([top.key]));
            }
            if (mode === "run" && onSelect.length > 0) {
              runEvents(onSelect, { ...eventContext, payload: {
                primary_key: top.key, layer: layers[top.layer]?.name ?? "" } });
            }
          }}
        >
          {piece.text}
        </mark>
      );
    });
  const blocks = parseMarkdown(filled, {
    breaks: breaks !== false, references, offsets: selecting || annotating });
  const rawSource = filled.replace(/\r\n?/g, "\n");
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  // A selection's end as a place in the source: the run it is in, and how far
  // into it. An end on an element boundary is the first run after it, or the
  // end of the last run before it.
  const endOf = (node: Node | null, offset: number): SelectionEnd | null => {
    const root = containerRef.current;
    if (!node || !root || !root.contains(node)) return null;
    const runOf = (text: Node): SelectionEnd | null => {
      const holder = text.parentElement;
      const at = holder?.getAttribute("data-at");
      return at === null || at === undefined || holder!.firstChild !== text
        ? null : { at: Number(at), offset: 0 };
    };
    if (node.nodeType === Node.TEXT_NODE) {
      const run = runOf(node);
      return run ? { ...run, offset } : null;
    }
    const texts: Text[] = [];
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) texts.push(t as Text);
    const after = node.childNodes[offset];
    const next = after ? texts.find((t) => after === t || after.contains(t)) : undefined;
    if (next) return runOf(next);
    const last = [...texts].reverse().find((t) => runOf(t));
    return last ? { ...runOf(last)!, offset: last.length } : null;
  };
  const readSelection = () => {
    if (!selecting) return;
    const chosen = window.getSelection();
    if (!chosen || chosen.rangeCount === 0) return;
    const range = selectionRange(
      endOf(chosen.anchorNode, chosen.anchorOffset), endOf(chosen.focusNode, chosen.focusOffset));
    const inside = containerRef.current?.contains(chosen.anchorNode ?? null);
    if (!inside) return;
    setHighlighted(range ? { text: selectedSource(rawSource, range), ...range } : null);
    if (selectedTextVariable) {
      setParameter(selectedTextVariable, range ? selectedSource(rawSource, range) : "");
    }
    if (selectionStartVariable) setParameter(selectionStartVariable, range ? range.start : null);
    if (selectionEndVariable) setParameter(selectionEndVariable, range ? range.end : null);
  };
  if (references) numberReferences(blocks);
  const types = referenceTypesOf(referenceTypes);
  // p.320's Highlight color from a property's formatting or rules (§664):
  // the anchors' objects are read, by type, to be painted.
  const colorKeys = references ? referenceKeysToColor(blocks, types) : new Map<string, string[]>();
  const colored = [...colorKeys.keys()];
  const colorTypeIds = useQueries({
    queries: colored.map((apiName) => ({
      queryKey: ["markdown-ref-type-id", workspaceId, apiName],
      queryFn: async () => (await objApi.listTypes(workspaceId, null, { q: apiName, limit: 50 }))
        .items.find((t) => t.api_name === apiName)?.id ?? null,
    })),
  });
  const colorTypes = useQueries({
    queries: colored.map((_, n) => ({
      queryKey: ["object-type", colorTypeIds[n]?.data ?? null],
      queryFn: () => objApi.getType(workspaceId, colorTypeIds[n]!.data!),
      enabled: !!colorTypeIds[n]?.data,
    })),
  });
  const colorObjects = useQueries({
    queries: colored.map((apiName, n) => ({
      queryKey: ["markdown-ref-objects", colorTypeIds[n]?.data ?? null, JSON.stringify(colorKeys.get(apiName))],
      queryFn: () => objApi.evaluateObjectSet(workspaceId, {
        object_type_id: colorTypeIds[n]!.data!,
        filters: [{ property: "$primary_key", op: "in", value: colorKeys.get(apiName) }],
      }, { limit: 200 }),
      enabled: !!colorTypeIds[n]?.data,
    })),
  });
  const anchorColor = (type: (typeof types)[number], primaryKey: string): string | null => {
    const n = colored.indexOf(type.objectType);
    if (n < 0) return type.color;
    const found = colorObjects[n]?.data?.instances.find((i) => String(i.primary_key) === primaryKey);
    const rules = colorTypes[n]?.data?.properties.find((p) => p.api_name === type.colorProperty)?.conditional_format;
    return referenceColorOf(type, found?.properties, rules);
  };
  const behavior = referenceSelectionOf(selectionBehavior);
  const selectedRaw = selectedVariable ? parameterValues[selectedVariable] : undefined;
  const selectedKeys = keysOf(selectedRaw);
  // **A selection names its type** (§692): p.320 outputs "that object", and
  // two types' objects can share a key, so the key alone could be either.
  // The anchors name types by api name, and a selection by id.
  const typeIds = useQueries({
    queries: types.map((t) => ({
      queryKey: ["markdown-ref-type-id", workspaceId, t.objectType],
      queryFn: async () => (await objApi.listTypes(workspaceId, null, { q: t.objectType, limit: 50 }))
        .items.find((found) => found.api_name === t.objectType)?.id ?? null,
    })),
  });
  const idOfType = (apiName: string) =>
    typeIds[types.findIndex((t) => t.objectType === apiName)]?.data ?? null;
  const pickedType = selectedType(selectedRaw);
  const onSelect = eventsFor(moduleEvents, nodeId, "row_select");
  // p.319-320's anchor. A type the builder did not configure is not an
  // anchor - p.320: "the object reference will not appear" - and its text is
  // kept as text, since dropping it would drop words from a sentence.
  const drawReference = (
    node: { objectType: string; primaryKey: string; index?: number },
    children: React.ReactNode,
  ) => {
    const type = types.find((t) => t.objectType === node.objectType);
    if (!type) return children;
    const index = node.index ?? -1;
    const lit = isReferenceLit(behavior, { index, primaryKey: node.primaryKey },
      lastAnchor,
      pickedType === null || pickedType === idOfType(node.objectType) ? selectedKeys : []);
    const color = anchorColor(type, node.primaryKey);
    return (
      <button
        type="button"
        className={`canvas-markdown-ref${lit ? " on" : ""}`}
        style={color ? ({ "--ref-color": color } as React.CSSProperties) : undefined}
        data-color={color ?? ""}
        data-testid="markdown-ref"
        data-object-type={node.objectType}
        data-primary-key={node.primaryKey}
        aria-pressed={lit}
        onClick={() => {
          setLastAnchor(index);
          // p.320: "that object will be output into this object set variable".
          if (selectedVariable) {
            setParameter(selectedVariable, typedSelection(
              selectionClauses([node.primaryKey]), idOfType(node.objectType)));
          }
          // p.320's Event on selection, in a running module only: a navigate
          // fired while arranging the page would move the builder off it. A
          // type with its own events fires those instead (§665).
          const picked = eventsFor(moduleEvents, nodeId, "row_select", selectionItemOfType(type));
          if (mode === "run" && picked.length > 0) {
            runEvents(picked, { ...eventContext,
              payload: { primary_key: node.primaryKey, object_type: node.objectType } });
          }
        }}
      >
        {children}
      </button>
    );
  };

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
        <div className={classes.join(" ")} data-testid="markdown" ref={containerRef}
             onMouseUp={readSelection} onKeyUp={readSelection}
             onMouseLeave={() => setHovered(null)}>
          <MarkdownReferences.Provider value={references ? drawReference : null}>
            <MarkdownRuns.Provider value={annotating ? drawRun : null}>
              <MarkdownView blocks={blocks} align={widgetAlign} />
            </MarkdownRuns.Provider>
          </MarkdownReferences.Provider>
          {/* p.322: "Configure actions or events to create new annotation
              objects when text is highlighted within the widget" (§638). Each
              runs its events with the highlighted text - p.322's "Highlighted
              text" - as `{{value}}`, and its indices. */}
          {highlighted && offered.length > 0 && (
            <div className="row-actions canvas-markdown-highlight" data-testid="markdown-highlight">
              {offered.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  className="btn quiet"
                  data-testid="markdown-highlight-action"
                  title={`${action.label}: “${highlighted.text}”`}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    if (mode !== "run") return;
                    runEvents(eventsFor(moduleEvents, nodeId, "click", action.id), {
                      ...eventContext,
                      payload: { value: highlighted.text, start: highlighted.start,
                                 end: highlighted.end },
                    });
                  }}
                >
                  {/* p.323: "The title appears on hover over the icon". */}
                  {action.icon ? <IconOrGlyph value={action.icon} /> : action.label || "Action"}
                </button>
              ))}
            </div>
          )}
          {/* p.322's On hover interactions (§669): "displayed in the on-hover
              tooltip of an annotation object", each run with the hovered
              object - p.322's "Hovered object" - as `{{primary_key}}`. */}
          {hovered && hovering.length > 0 && (
            <div className="canvas-markdown-hover" data-testid="markdown-annotation-hover"
                 style={{ left: hovered.left, top: hovered.top }}>
              {tooltipOf(hovered.annotation, tooltipProps) && (
                <div className="canvas-markdown-hover-props">{tooltipOf(hovered.annotation, tooltipProps)}</div>
              )}
              <div className="row-actions">
                {hovering.map((action) => (
                  <button
                    key={action.id}
                    type="button"
                    className="btn quiet"
                    data-testid="markdown-hover-action"
                    title={action.label || "Interaction"}
                    onClick={() => {
                      if (mode !== "run") return;
                      runEvents(eventsFor(moduleEvents, nodeId, "click", action.id), {
                        ...eventContext,
                        payload: { primary_key: hovered.annotation.key,
                                   layer: layers[hovered.annotation.layer]?.name ?? "" },
                      });
                    }}
                  >
                    {/* p.323: the title "appears when hovering over the
                        interaction icon". */}
                    {action.icon ? <IconOrGlyph value={action.icon} /> : action.label || "Interaction"}
                  </button>
                ))}
              </div>
            </div>
          )}
          {unreadable > 0 && (
            // Said, not dropped: an annotation that cannot be placed and one
            // that is not there look the same otherwise.
            <p className="canvas-widget-empty" data-testid="markdown-annotations-unreadable">
              {unreadable} annotation{unreadable === 1 ? "" : "s"} with no usable start and end
            </p>
          )}
          {beyond > 0 && (
            <p className="canvas-widget-empty" data-testid="markdown-annotations-beyond">
              {beyond} more annotation{beyond === 1 ? "" : "s"} than one read draws
            </p>
          )}
        </div>
      )}
    </div>
  );
}

CanvasMarkdown.craft = {
  displayName: "Markdown",
  props: {
    source: "text", text: "", textVariable: "", monospace: false,
    scrolling: false, wordWrap: true, breaks: true, alignment: "left",
  },
  related: { settings: settingsPanel("MarkdownSettings") },
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

CanvasDatasetTable.craft = {
  displayName: "Dataset table",
  props: {
    datasetId: null,
    filterColumn: null,
    filterParameter: null,
    filterOperator: "equals",
  },
  related: { settings: settingsPanel("DatasetTableSettings") },
};

// ---- Object table (ROADMAP Canvas item 3) -----------------------------------
/** p.266 and p.596's reveal (§693): an unsupported property is not loaded
 * with the page, and a reader asks for it - "select Load next to an
 * unsupported property to reveal its value on demand". One object's read,
 * once, shared by every cell asking for the same object. */
function LoadOnDemand({ workspaceId, typeId, instanceId, property, label, emptyText }: {
  workspaceId: string;
  typeId: string | null;
  instanceId: string;
  property: ObjectTypeProperty;
  label: string;
  emptyText?: string;
}) {
  const [asked, setAsked] = useState(false);
  const read = useQuery({
    queryKey: ["instance", workspaceId, typeId, instanceId],
    queryFn: () => objApi.getInstance(workspaceId, typeId!, instanceId),
    enabled: asked && !!typeId,
  });
  if (!asked) {
    return (
      <button
        type="button"
        className="btn quiet canvas-load-property"
        data-testid={`load-${property.api_name}`}
        title={UNSUPPORTED_HINT}
        aria-label={`Load ${property.display_name || property.api_name}`}
        onClick={(e) => {
          // A click in a cell is not a click on its row.
          e.stopPropagation();
          setAsked(true);
        }}
      >
        {label}
      </button>
    );
  }
  if (read.isPending) return <span className="canvas-widget-empty">Loading…</span>;
  if (read.isError) return <span className="canvas-widget-empty">Couldn&apos;t load it.</span>;
  return (
    <PropertyValue
      workspaceId={workspaceId}
      dataType={property.data_type}
      valueFormat={property.value_format}
      structFields={property.struct_fields}
      value={read.data.properties[property.api_name]}
      emptyText={emptyText}
      compact
    />
  );
}

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
  emptyIcon = "",
  emptyMessage = "",
  customNoValue = false,
  noValueText = "",
  fitColumns = true,
  narrowHeaders = false,
  formatFillsCell = false,
  inlineEditAction = null,
  inlineEditMapping = null,
  inlineEditVariables = null,
  columnsVariable = null,
  inlineEditButtonText = "",
  inlineEditByDefault = false,
  inlineEditOneClick = false,
  exportCsv = false,
  exportExcel = false,
  hideColumnConfig = false,
  customMenu = false,
  menuItems = null,
  rightClickedVariable = null,
  seriesFormats = null,
  seriesRules = null,
  seriesTransforms = null,
  seriesBaselines = null,
  combineTypes = false,
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
  /** p.174's value formatting for this module's **time series columns**, keyed
   * by property API name. Read through `formatsByColumn`, which drops anything
   * that would not apply (§212) - see `value-formats.ts` for why the ontology
   * has nothing to inherit from here. */
  seriesFormats?: unknown;
  /** p.175's conditional formatting for this module's **time series columns**,
   * keyed by property API name. §158's rules, comparing the latest value
   * rather than a stored property - see `conditional-formats.ts`. */
  seriesRules?: unknown;
  /** p.583's time series transforms, by column (§555): each row's series read
   * through the column's chain. */
  seriesTransforms?: unknown;
  /** p.592-593's baselines (§563), by series column: static, the row's own
   * numeric property, or the series summarised. `series-baselines.ts`. */
  seriesBaselines?: unknown;
  /** One of the server's `object_sets.SORTS`, **or a property sort** — `name`
   * or `-name` for a property whose declared type has an order both stores
   * agree on (§221's `ORDERABLE_TYPES`), which §231 gave this panel.
   *
   * This said property sorts were "refused there rather than here, because
   * untyped properties would order differently on the two stores". True when
   * written and untrue from §221, which is the same shape of stale claim §406
   * found on the derived-property editor — except this one had already been
   * built, so the comment was describing a refusal the code beside it does not
   * make. `withSortProperty` is imported ten lines up.
   *
   * **p.223's "one or more"**: a list of them, and a plain string for the one
   * every module stored before this. Both read through `table-sorts.ts`, so
   * there is no migration and no moment when a saved table reorders itself. */
  sort?: string | string[];
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
  /** p.224's Custom empty state icon (§719). */
  emptyIcon?: string;
  emptyMessage?: string;
  customNoValue?: boolean;
  noValueText?: string;
  fitColumns?: boolean;
  narrowHeaders?: boolean;
  formatFillsCell?: boolean;
  /** p.240-243's inline edits. The action id is the toggle: p.241 makes
   * enabling the feature and choosing the action one act, because an inline
   * edit *is* an action and a table enabled with none configured would be a
   * mode with nothing in it. Which actions may be named is §238's answer, not
   * this widget's. */
  inlineEditAction?: string | null;
  /** p.241's parameter-to-column mapping, `{parameter: column}`. */
  inlineEditMapping?: Record<string, string> | null;
  /** p.241's variables passed as action parameters (§598),
   * `{parameter: variable id}`. */
  inlineEditVariables?: Record<string, string> | null;
  /** p.225's variable-backed column visibility (§610): a string array
   * variable naming which of the configured columns show, in its order. */
  columnsVariable?: string | null;
  /** p.242's Custom button text, and its two toggles; p.243's One-click. */
  inlineEditButtonText?: string;
  inlineEditByDefault?: boolean;
  inlineEditOneClick?: boolean;
  /** p.223's "Enable export to CSV": from a row's right-click menu (§611). */
  exportCsv?: boolean;
  /** p.223's "Enable export to Excel" (§788), beside it. */
  exportExcel?: boolean;
  /** p.225's "Hide column configuration": no viewer-side Configure columns (§612). */
  hideColumnConfig?: boolean;
  /** p.243's "Customize right-click menu" (§613): the toggle, the menu's items
   * (`button-items.ts`'s shape, so the Events panel names them as it names a
   * menu button's), and the right-clicked object as selection clauses. */
  customMenu?: boolean;
  menuItems?: unknown;
  rightClickedVariable?: string | null;
  /** p.225's "Combine multiple object types" (§689): a union in one table
   * rather than a tab per type. "Not available when Enable inline editing is
   * set to true", so an inline edit action switches it off. */
  combineTypes?: boolean;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId, mode, derivedColumns } = useCanvasEnv();
  const eventContext = useEventContext(undefined, useOverlayIds());
  const filterValue = useCanvasParameter(filterParameter);
  const searchValue = useCanvasParameter(searchParameter);
  // p.450's union (§686): each type in its own tab (p.225), and each tab an
  // ordinary set, so everything below reads the tab's part as it would read
  // a set over one type. Which tab is runtime state, like the page.
  const boundSet = useCanvasVariable(objectSetVariable);
  const parts = unionParts(boundSet);
  // p.225's Combine (§689): the whole union as one page, every type's
  // objects in one order (`union_reads.page`).
  const combined = !!parts && combineTypes === true && !inlineEditAction;
  const [tabRequested, setTab] = useState(0);
  const tab = parts ? tabIndex(tabRequested, parts.length) : 0;
  const setDefinition = combined ? boundSet : parts ? parts[tab] ?? null : boundSet;
  const tabType = parts && !combined ? parts[tab]?.object_type_id ?? null : null;
  const tabTypes = useQueries({
    queries: (parts ?? []).map((part) => ({
      queryKey: ["object-type", part.object_type_id],
      queryFn: () => objApi.getType(workspaceId, part.object_type_id),
    })),
  });
  const {
    pending: variablesPending, events: moduleEvents, declared: moduleVariables,
    resolved: variableValues,
  } = useCanvasVariables();
  const usingSet = !!objectSetVariable;

  // p.224's two outputs. **The variables are the source of truth**, not a copy
  // in component state: a table holding its own set would disagree with the
  // variable the moment anything else wrote to it — an event that clears the
  // selection, a saved state restored on load — and the checkboxes would show
  // one answer while every downstream widget acted on another.
  const { set: setParameter } = useCanvasParameters();
  const activeRaw = useCanvasParameter(activeVariable);
  const selectedRaw = useCanvasParameter(selectedVariable);
  // A union tab reads back only what its own type wrote, and a combined
  // table each object with its type (`union-set.ts`).
  const activePicked = pickedIn(activeRaw, combined, tabType);
  const selectedPicked = pickedIn(selectedRaw, combined, tabType);
  const activeKeys = activePicked.map((p) => p.key);
  const selection = (picked: readonly Picked[]) => pickedClauses(picked, combined, tabType);
  const pick = (row: ObjectInstance) => pickOf(row, combined);
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
  // p.223's Default sort(s), read from whichever shape the document holds and
  // sent as whichever shape the request wants - one ordering still goes as the
  // string the API has always taken.
  // The set's type, from its definition, read before its page (§693).
  const effectiveTypeId = usingSet
    ? (setDefinition as { object_type_id?: string } | undefined)?.object_type_id ?? null
    : objectTypeId;
  // p.173's sort by a derived column (§781): the first sort naming one is
  // ordered here, over the whole set, and the store orders by the rest.
  const sortableDerived = useMemo(
    () => columnsFor(derivedColumns, String(effectiveTypeId ?? "")),
    [derivedColumns, effectiveTypeId],
  );
  const sortSplit = useMemo(
    () => splitSorts(tableSortsOf(sort), sortableDerived.map((c) => c.api_name)),
    [sort, sortableDerived],
  );
  const sortRequest = useMemo(() => tableSortsToRequest(sortSplit.server), [sortSplit]);
  const type = useQuery({
    queryKey: ["object-type", effectiveTypeId],
    queryFn: () => objApi.getType(workspaceId, effectiveTypeId!),
    enabled: !!effectiveTypeId,
  });
  // p.266 and p.596: "Some large properties, such as Geoshape and Vector,
  // are not loaded by default to improve performance", and a cell reveals
  // one on demand. So the page waits for the types that say which (§693).
  const heavy = omittedOf(combined
    ? tabTypes.flatMap((t) => t.data?.properties ?? []) : type.data?.properties ?? []);
  const typesKnown = combined ? tabTypes.every((t) => !!t.data) : !!type.data;
  const setPage = useSetPage(workspaceId, usingSet && typesKnown ? setDefinition : null, {
    pageSize,
    sort: sortRequest,
    variablesPending,
    omit: heavy,
  });
  const { offset, setOffset } = setPage;
  const sortColumn = sortSplit.derived
    ? sortableDerived.find((c) => c.api_name === sortSplit.derived!.property) : undefined;
  const derivedSorted = useQuery({
    queryKey: ["canvas-derived-sort", JSON.stringify(setDefinition ?? null), sortRequest,
               sortSplit.derived?.key ?? null, sortColumn ?? null, variableValues],
    queryFn: async () => {
      const column = sortColumn!;
      const read = await readUpTo(async (at, limit) => {
        const got = await objApi.evaluateObjectSet(workspaceId, setDefinition, {
          limit, offset: at, sort: sortRequest, omit: heavy });
        return { rows: got.instances, total: got.total };
      }, derivedSortLimit(column));
      if ("tooMany" in read) return read;
      const wanted = derivedInputs(
        [column.api_name], type.data?.properties ?? [], sortableDerived);
      const values = await derivedForExport(read.rows, [column], {
        readDerived: wanted.properties.length > 0 || Object.keys(wanted.derivations).length > 0
          ? (keys) => objApi.derivedValues(workspaceId, String(effectiveTypeId), { keys, ...wanted })
          : undefined,
        callFunction: (c, keys) => objApi.executeFunction(
          workspaceId, c.function_id, callValues(c, keys, variableValues), c.version),
      }, wanted.properties);
      return { rows: sortRowsBy(read.rows, values, column.api_name,
                                sortSplit.derived!.descending) };
    },
    enabled: !!sortColumn && usingSet && !combined && typesKnown && !!setDefinition,
  });
  const derivedOrder = derivedSorted.data && "rows" in derivedSorted.data
    ? derivedSorted.data.rows : null;
  // p.222's hubble:icon (§671): the property holding each object's image.
  const iconProperty = iconPropertyOf(type.data?.properties ?? []);

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
        // p.33's "in which Foundry applications" (§320): a widget's reads are
        // Workshop's, which is the answer somebody renaming a property needs.
        application: "workshop",
      }),
    enabled: !!objectTypeId,
  });

  // A combined table's columns are every type's, one per api name and
  // display name (p.225), each saying which types' rows it has values for.
  const loadedTypes = tabTypes.map((t) => t.data);
  const columnsOfUnion = useMemo(
    () => combinedColumns(loadedTypes),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loadedTypes.map((t) => t?.id ?? "").join(",")],
  );
  const all: (ObjectTypeProperty & { covers?: string[] })[] = combined
    ? columnsOfUnion
    : type.data?.properties ?? [];
  // p.174's per-column formatters, read once for the render rather than per
  // cell: this validates every entry, and a twenty-five row page would run it
  // twenty-five times for an answer that cannot differ between rows.
  const columnFormats = useMemo(() => formatsByColumn(seriesFormats), [seriesFormats]);
  const columnRules = useMemo(() => rulesByColumn(seriesRules), [seriesRules]);
  // Configured order wins, and a name that matches nothing is dropped rather
  // than rendered as an empty column: a property can be removed from the type
  // long after a table was pointed at it.
  const configured = String(columns || "")
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
  // p.225's variable-backed column visibility (§610): the variable chooses
  // among the configured columns - every property, when none are configured -
  // and orders them. Empty, it shows them all, so a table whose variable has
  // not been written yet looks the way it was configured to.
  //
  // `null` is "no list, every property"; a list the variable emptied by naming
  // only columns this table does not have is an empty list, and shows none -
  // the variable said which, and none of them is here.
  const listedAll: string[] | null = columnsVariable
    ? visibleColumns(
      configured.length ? configured : all.map((p) => p.api_name),
      variableValues[columnsVariable],
    )
    : configured.length ? configured : null;
  // In a union's tab, columns configured for the other types are not this
  // one's, and a tab with none of its own shows every property rather than
  // rows with no cells (§686).
  const listed = parts && !columnsVariable && listedAll && all.length > 0
    && !listedAll.some((name) => all.some((p) => p.api_name === name))
    ? null : listedAll;
  // p.222's Configure columns (§612): a viewer chooses among what the table
  // offers, and the choice is theirs - kept in their browser per widget and
  // type, never in the shared document. The builder always sees the table as
  // configured, which is what it is building.
  const offeredColumns = listed ?? all.map((p) => p.api_name);
  const viewerConfigures = mode === "run" && !hideColumnConfig;
  const choiceKey = columnsKey(nodeId, effectiveTypeId ? String(effectiveTypeId) : null);
  const [viewerChoice, setViewerChoiceState] = useState<string[] | null>(null);
  useEffect(() => {
    try {
      setViewerChoiceState(storedChoice(window.localStorage.getItem(choiceKey)));
    } catch {
      setViewerChoiceState(null);
    }
  }, [choiceKey]);
  const setViewerChoice = (next: string[] | null) => {
    setViewerChoiceState(next);
    try {
      if (next) window.localStorage.setItem(choiceKey, JSON.stringify(next));
      else window.localStorage.removeItem(choiceKey);
    } catch {
      // Storage refused (a private window): the choice lasts the visit.
    }
  };
  const [configuringColumns, setConfiguringColumns] = useState<{ x: number; y: number } | null>(
    null,
  );
  useEffect(() => {
    if (!configuringColumns) return;
    const close = () => setConfiguringColumns(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [configuringColumns]);
  const shownColumns = viewerConfigures && viewerChoice
    ? viewerColumnsOf(offeredColumns, viewerChoice)
    : listed;
  const properties = shownColumns
    // Every column by that name: a combined table has two under one api name
    // when the types display it differently (p.225).
    ? shownColumns.flatMap((name) => all.filter((p) => p.api_name === name))
    : all;

  // p.170's calculated columns for whichever type this table is showing.
  //
  // **Only when named in `columns`, and never in the "every property" case.**
  // A derived property is the module's, not the ontology's, so a table left
  // on its default of "show everything" is showing everything the *type* has;
  // adding columns a builder never asked this table for would be the module
  // reaching into a widget that never mentioned it.
  const declaredDerived = useMemo(
    () => columnsFor(derivedColumns, String(effectiveTypeId ?? "")),
    [derivedColumns, effectiveTypeId],
  );
  const derived = shownColumns
    ? shownColumns.map((name) => declaredDerived.find((c) => c.api_name === name))
        .filter((c) => !!c)
    : [];

  // p.583's column. **One read for the page**, fired only when a visible
  // column is a time series - a table of ordinary properties must not pay for
  // a feature it is not using.
  //
  // The *first* such column rather than all of them: a second series column
  // would be a second read, and no widget in the corpus has one. When one
  // does, this becomes a loop rather than a different shape.
  const seriesProperty = properties.find((p) => p.data_type === "time_series");
  // p.583's transforms on the column (§555), each row's series on its own.
  const seriesChain = seriesProperty
    ? readableTransforms(seriesTransforms, seriesProperty.api_name) : [];
  const columnBaselines = baselinesByColumn(seriesBaselines);
  const seriesPage = useQuery({
    queryKey: ["canvas-series-points", JSON.stringify(setDefinition ?? null),
               effectiveTypeId, seriesProperty?.api_name, pageSize, offset,
               Array.isArray(sortRequest) ? sortRequest.join(",") : sortRequest ?? null,
               JSON.stringify(seriesChain)],
    queryFn: () => objApi.objectSetSeriesPoints(
      workspaceId,
      // The explore path has no object set of its own, so the type *is* the
      // set. The series read has to describe the same rows the table drew, and
      // an unfiltered type is what that path is showing.
      usingSet ? setDefinition : { object_type_id: effectiveTypeId, filters: [] },
      seriesProperty!.api_name,
      { limit: pageSize, offset, sort: sortRequest, transforms: seriesChain },
    ),
    enabled: !!seriesProperty && !!effectiveTypeId && (!usingSet || !!setDefinition),
    placeholderData: (previous) => previous,
  });
  // Keyed by primary key, which is how the server keys it and the only key
  // that survives two objects sharing a series.
  const seriesByKey = new Map(
    (seriesPage.data?.rows ?? []).map((r) => [r.primary_key, r.points]),
  );

  // One shape for both paths, so everything below reads the same. The set path
  // returns `instances`; the explore path returns `items`.
  // Waiting on the whole set's order rather than drawing the store's first,
  // which would be a page in an order that is about to change under the reader.
  const awaitingOrder = !!sortColumn && derivedSorted.isPending && derivedSorted.fetchStatus !== "idle";
  const rows = derivedOrder
    ? derivedOrder.slice(offset, offset + pageSize)
    : awaitingOrder ? undefined : usingSet ? setPage.rows : page.data?.items;
  const total = derivedOrder ? derivedOrder.length : usingSet ? setPage.total : page.data?.total;
  const active = usingSet
    ? { isError: setPage.isError, isPending: setPage.isPending || awaitingOrder }
    : { isError: page.isError, isPending: page.isPending };
  const setFilters = setPage.filters;

  // p.143's derived properties among the columns (§604), and p.169's linked
  // columns the module declares (§605). A list read carries neither - both
  // are calculated from each object's links - so the page asks for them in
  // one more read, one read per hop for every row at once, and only when a
  // visible column needs one. "Needs" includes a column-math column's inputs:
  // p.170 lets it reference an aggregation, and an expression over a value
  // the table never fetched is a column of blanks.
  const derivedWanted = derivedInputs(
    shownColumns ?? properties.map((p) => p.api_name), all, declaredDerived,
  );
  const needsDerived = derivedWanted.properties.length > 0
    || Object.keys(derivedWanted.derivations).length > 0;
  const pageKeys = (rows ?? []).map((r) => r.primary_key);
  const derivedPage = useQuery({
    queryKey: ["canvas-derived-values", effectiveTypeId, derivedWanted, pageKeys],
    queryFn: () => objApi.derivedValues(workspaceId, String(effectiveTypeId), {
      keys: pageKeys, ...derivedWanted,
    }),
    enabled: needsDerived && pageKeys.length > 0 && !!effectiveTypeId,
  });
  // A row's own values with its derived ones beside them, for column math.
  const derivedByKey = new Map(
    (derivedPage.data?.rows ?? []).map((r) => [r.primary_key, r.values]),
  );

  // p.221's function-backed columns (§770), with the page's keys as the
  // runtime input - "pass only the objects currently displayed in the Object
  // Table". Columns that differ only in their field share a query key, so
  // React Query makes them one call.
  const functionColumns = derived.filter(
    (c): c is FunctionColumn => !!c && c.kind === "function",
  );
  const functionResults = useQueries({
    queries: functionColumns.map((c) => {
      const values = callValues(c, pageKeys, variableValues);
      return {
        queryKey: ["canvas-function-column", c.function_id, c.version, values],
        queryFn: () => objApi.executeFunction(workspaceId, c.function_id, values, c.version),
        enabled: pageKeys.length > 0,
        retry: false,
      };
    }),
  });
  const functionByCall = new Map(
    functionColumns.map((c, i) => [callKey(c), functionResults[i]]),
  );

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

  // p.223's right-click menu (§611): "Enable export to CSV: … export object
  // table data to CSV format from a row's right-click menu." The whole set,
  // not the page - p.223's own limit is 10,000 rows, which is §459's - in the
  // columns this table shows, through §459's export, so the file and what is
  // said about it are the Export widget's. **Only over an object set
  // variable**: the other path is a type narrowed by a search box, which is
  // no set an export can name.
  const { exportObjects } = useCanvasActions();
  // Not from a combined table, which pages to 200 objects (`union_reads`) and
  // so cannot be read to p.223's 10,000; each tab of a union can.
  const offersExport = mode === "run" && (!!exportCsv || !!exportExcel) && usingSet && !combined;
  // p.243's custom items (§613): "run actions or events on an object that is
  // right-clicked from the object table". Each item is a click the Events
  // panel wires, as a menu button's items are, and it fires with the row's
  // object as its selection - the same context a row click gives.
  const rowItems = customMenu ? itemsOf(menuItems) : [];
  const offersItems = mode === "run" && rowItems.length > 0;
  const [rowMenu, setRowMenu] = useState<
    { x: number; y: number; instance: ObjectInstance } | null
  >(null);
  useEffect(() => {
    if (!rowMenu) return;
    const close = () => setRowMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    // A press anywhere else closes it; the menu's own button stops its press.
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [rowMenu]);

  const chooseActive = (row: ObjectInstance) => {
    if (activeVariable) setParameter(activeVariable, selection([pick(row)]));
  };

  // p.224's auto-selection, in an effect because it is a *write* — doing it
  // during render would set a variable while React is drawing the widget that
  // reads it.
  const autoKey = autoSelectKey({
    rows, current: activeKeys, enabled: autoSelect !== false, visible: onScreen,
  });
  useEffect(() => {
    if (!activeVariable) return;
    if (autoKey && rows?.[0]) {
      setParameter(activeVariable, selection([pick(rows[0])]));
      return;
    }
    // p.224's "results in an empty active object at load time", written down
    // rather than left unsaid - see `activeStated` above.
    if (!activeStated) setParameter(activeVariable, selection([]));
    // `setParameter` is stable for the life of the provider; listing it would
    // re-run this on every render of every widget in the module.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoKey, activeVariable, activeStated]);

  useEffect(() => {
    // p.224: the Selected objects variable "will only be in use and populated
    // if the Enable multi-select toggle is set to true" - so an unbound or
    // single-select table leaves it alone entirely.
    if (!multiSelect || !selectedVariable || selectedStated) return;
    setParameter(selectedVariable, selection([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [multiSelect, selectedVariable, selectedStated]);

  // ---- p.240-243's inline edits ------------------------------------------
  // The action is fetched by id rather than taken from the panel's list: the
  // widget runs in a published module where no panel is mounted, and it needs
  // the parameters (to know what a cell writes), the refusals (because the
  // action can have changed since it was configured) and p.242's row cap.
  const editAction = useQuery({
    queryKey: ["action-type", workspaceId, inlineEditAction],
    queryFn: () => actionApi.getType(workspaceId, inlineEditAction!),
    enabled: !!inlineEditAction,
  });
  // **Re-checked here, not trusted from the document.** A builder can point a
  // table at an action and then change the action; §238 refuses the submission
  // either way, and this is what stops the table drawing editors for a
  // submission that is going to be refused.
  const liveAction = eligibleActions(editAction.data ? [editAction.data] : [])[0] ?? null;
  const shownNames = properties.map((p) => p.api_name);
  const editMapping = mappingOf(inlineEditMapping, liveAction, shownNames);
  const editFeeds = variableFeedsOf(
    inlineEditVariables, liveAction, Object.keys(moduleVariables), editMapping,
  );
  const rowLimit = rowLimitOf(liveAction);
  // `null` until somebody presses the button, so p.242's toggle decides the
  // starting state and the button can still close a table configured to open
  // in edit mode - see `editing`.
  const [editOpen, setEditOpen] = useState<boolean | null>(null);
  const [staged, setStaged] = useState<Staged>({});
  const [confirming, setConfirming] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const inEditMode = mode === "run" && !!liveAction
    && Object.keys(editMapping).length > 0 && editing(editOpen, inlineEditByDefault);
  const rowsDrag = mode === "run" && !inEditMode && !!effectiveTypeId;
  const queryClient = useQueryClient();
  const submit = useMutation({
    mutationFn: () =>
      actionApi.executeBatch(
        workspaceId, projectId, liveAction!.id,
        withVariables(toEdits(staged), editFeeds, variableValues),
      ),
    onSuccess: () => {
      setStaged({});
      setConfirming(false);
      setSubmitError(null);
      // The rows on screen are now stale in exactly the cells that were
      // edited, and p.243 says nothing about what a reader sees afterwards -
      // showing them their own edits confirmed is the only answer that does
      // not require a reload.
      //
      // **Both keys, because a table is populated two ways** (p.65's choice):
      // `canvas-object-table` is the explore path and `canvas-object-set` is
      // the bound-set one, which `useSetPage` owns. Invalidating only one
      // leaves every table on the *other* path showing the values the reader
      // has just changed - and it is not this widget's own rows that matter
      // most, it is the ones beside it reading the same set.
      queryClient.invalidateQueries({ queryKey: ["canvas-object-table"] });
      queryClient.invalidateQueries({ queryKey: ["canvas-object-set"] });
    },
    onError: (err: unknown) => {
      setConfirming(false);
      setSubmitError(err instanceof Error ? err.message : "The edits were not saved.");
    },
  });

  const columnCount = properties.length + 1 + (multiSelect && selectedVariable ? 1 : 0)
    + (inEditMode ? 1 : 0);
  const frozen = frozenOf(frozenColumns, columnCount);
  useEffect(() => {
    const head = headRef.current;
    if (!head || frozen === 0) return;
    setWidths(Array.from(head.children, (cellEl) => (cellEl as HTMLElement).offsetWidth));
  }, [frozen, columnCount, rows?.length, rowLines, wrapValues, fitColumns]);
  const lefts = stickyLefts(widths, frozen);
  // **How many columns come before the key**, computed once. Every sticky
  // offset and every `colSpan` below is relative to it, and p.242's undo column
  // is the second thing to change it - the first was p.224's checkbox, and that
  // one was written out at four call sites.
  const leading = (inEditMode ? 1 : 0) + (multiSelect && selectedVariable ? 1 : 0);
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
      {/* p.225: "When disabled, each object type will be displayed within its
          own tab" (§686). The section's tabstrip, roles and keys included. */}
      {parts && parts.length > 0 && !combined && (
        <div className="canvas-tabstrip" role="tablist" aria-label="Object types">
          {parts.map((part, i) => (
            <button
              key={part.object_type_id}
              type="button"
              role="tab"
              aria-selected={i === tab}
              tabIndex={i === tab ? 0 : -1}
              className={`canvas-tabstrip-tab${i === tab ? " on" : ""}`}
              data-testid="object-table-tab"
              onClick={() => setTab(i)}
              onKeyDown={(event) => {
                const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
                if (!step) return;
                event.preventDefault();
                const next = (tab + step + parts.length) % parts.length;
                setTab(next);
                const strip = event.currentTarget.parentElement;
                (strip?.children[next] as HTMLElement | undefined)?.focus();
              }}
            >
              {tabTypes[i]?.data?.display_name ?? "…"}
            </button>
          ))}
        </div>
      )}
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
              {/* p.224: "By Default, the widget will display a generic table
                  icon alongside a 'No objects found' message. To customize
                  the display icon and message, select the Custom option"
                  (§719). */}
              {emptyIconOf(emptyMode, emptyIcon) && (
                <span className="canvas-empty-icon" data-testid="table-empty-icon" aria-hidden="true">
                  <IconOrGlyph value={emptyIconOf(emptyMode, emptyIcon)} size={16} />
                </span>
              )}
              {emptyMessageOf(emptyMode, emptyMessage)}
            </p>
          ) : (
          <p className="canvas-widget-empty">
            {total.toLocaleString()} {type.data?.display_name ?? "object"}
            {total === 1 ? "" : "s"}
            {/* The set says what narrowed it. A table that showed a filtered
                count with no sign it was filtered is the same trap as a
                sampled preview that does not say so. */}
            {/* Each clause in its operator's words: a date range read
                "at = 2024-03-01" here while this printed every clause as `=`. */}
            {usingSet && setFilters.length > 0
              ? ` where ${setFilters
                  .map((f) => describeClause(
                    { property: f.property, op: f.op ?? "eq", value: f.value }, []))
                  .join(" and ")}`
              : ""}
            {!usingSet && useProperty ? ` where ${filterProperty} = ${String(filterValue)}` : ""}
            {!usingSet && !useProperty && searchValue
              ? ` matching “${String(searchValue)}”`
              : ""}
          </p>
          )}
          {/* A derived column the page reached too far to answer, said once
              for the column rather than in every one of its cells. */}
          {Object.entries(derivedPage.data?.errors ?? {}).map(([name, reason]) => (
            <p key={name} className="field-hint" data-testid={`derived-error-${name}`}>
              {properties.find((p) => p.api_name === name)?.display_name
                || declaredDerived.find((c) => c.api_name === name)?.display_name
                || name}: {reason}
            </p>
          ))}
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
                  {/* p.242 draws Undo in "the left-most column of the table",
                      so the header above it is a blank cell rather than a
                      label - there is nothing to call a column of buttons. */}
                  {inEditMode && (
                    <th className="canvas-table-check" style={stick(0)} aria-label="Undo" />
                  )}
                  {multiSelect && selectedVariable && (
                    <th className="canvas-table-check" style={stick(inEditMode ? 1 : 0)}>
                      <input
                        type="checkbox"
                        aria-label="Select all rows on this page"
                        data-testid="table-select-all"
                        checked={rows.length > 0 && rows.every(
                          (r) => isPicked(selectedPicked, r),
                        )}
                        onChange={(e) =>
                          setParameter(selectedVariable, selection(
                            // **This page, not the whole set.** Checking a box
                            // that selects rows nobody has seen is a promise
                            // the widget cannot keep: it only has the page it
                            // fetched, and the set may be a million rows.
                            e.target.checked
                              ? [...selectedPicked,
                                 ...rows.filter((r) => !isPicked(selectedPicked, r)).map(pick)]
                              : selectedPicked.filter(
                                (p) => !rows.some((r) => isPicked([p], r)),
                              ),
                          ))}
                      />
                    </th>
                  )}
                  <th style={stick(leading)}>
                    Key
                    {/* p.222: "selecting Configure columns from the arrow next
                        to a column header". */}
                    {viewerConfigures && (
                      <button
                        type="button"
                        className="canvas-column-menu"
                        data-testid="table-configure-columns"
                        aria-label="Configure columns"
                        title="Configure columns"
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          const box = e.currentTarget.getBoundingClientRect();
                          setConfiguringColumns(
                            configuringColumns ? null : { x: box.left, y: box.bottom + 4 },
                          );
                        }}
                      />
                    )}
                  </th>
                  {properties.map((p, column) => (
                    <th key={`${p.api_name}:${column}`} style={stick(column + 1 + leading)}>
                      {p.display_name || p.api_name}
                    </th>
                  ))}
                  {/* p.170's calculated columns, after the type's own. They
                      are not frozen - `stick` numbers the columns a reader can
                      pin, and a column the ontology does not have is not one
                      of them. */}
                  {derived.map((c) => (
                    <th key={`derived-${c.api_name}`} data-derived={c.api_name}>
                      {c.display_name || c.api_name}
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
                      isPicked(activePicked, instance) ? "row-active" : "",
                    ].filter(Boolean).join(" ") || undefined}
                    // The active row is announced rather than only coloured: a
                    // highlight nobody can hear is not a selection.
                    aria-current={
                      isPicked(activePicked, instance) ? "true" : undefined
                    }
                    // p.570's drag zone: "Cells in an object table can be
                    // dragged onto compatible drop zones", carrying the
                    // row's object. Not while inline editing, where a drag
                    // is somebody selecting the text they are typing.
                    draggable={rowsDrag || undefined}
                    onDragStart={rowsDrag ? (event) => {
                      event.dataTransfer.setData(
                        OBJECT_MEDIA_TYPE, objectPayload(effectiveTypeId!, instance.primary_key),
                      );
                      event.dataTransfer.effectAllowed = "copy";
                    } : undefined}
                    onContextMenu={(offersExport || offersItems) && !inEditMode ? (event) => {
                      event.preventDefault();
                      setRowMenu({ x: event.clientX, y: event.clientY, instance });
                      // p.243's right-clicked object "outputs the currently
                      // right-clicked object": set on the right-click, so an
                      // item's events read a variable already settled.
                      if (rightClickedVariable) {
                        setParameter(rightClickedVariable, selection([pick(instance)]));
                      }
                    } : undefined}
                    onClick={
                      rowsAreClickable
                        ? () => {
                          chooseActive(instance);
                          runEvents(rowEvents, {
                            ...eventContext,
                            ...selectionOf(instance, effectiveTypeId),
                          });
                        }
                        : undefined
                    }
                  >
                    {inEditMode && (
                      <td className="canvas-table-check" style={stick(0)}>
                        {isStaged(staged, instance.id) && (
                          <button
                            type="button"
                            className="btn quiet"
                            data-testid={`undo-${instance.primary_key}`}
                            aria-label={`Undo edits to ${instance.primary_key}`}
                            // Not a row click: undoing an edit is not choosing
                            // an active object, and without this one press
                            // would do both and fire the row's events.
                            onClick={(e) => {
                              e.stopPropagation();
                              setStaged(undoRow(staged, instance.id));
                            }}
                          >
                            Undo
                          </button>
                        )}
                      </td>
                    )}
                    {multiSelect && selectedVariable && (
                      <td className="canvas-table-check" style={stick(inEditMode ? 1 : 0)}>
                        <input
                          type="checkbox"
                          aria-label={`Select ${instance.primary_key}`}
                          checked={isPicked(selectedPicked, instance)}
                          // **Stops the click reaching the row.** Checking a box
                          // is not choosing an active object, and without this
                          // one click would do both — and fire the row's events
                          // as a side effect of ticking a checkbox.
                          onClick={(e) => e.stopPropagation()}
                          onChange={() =>
                            setParameter(selectedVariable, selection(
                              isPicked(selectedPicked, instance)
                                ? selectedPicked.filter((p) => !isPicked([p], instance))
                                : [...selectedPicked, pick(instance)],
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
                        ...stick(leading),
                      }}
                    >
                      {/* **The clamp lives on an inner element**, because
                          `-webkit-box` would stop the `<td>` being a table cell
                          and take the column widths with it. */}
                      <div style={cell}>
                        {/* p.222: "add the type class hubble:icon to display
                            the image instead of the icon" (§671). An object
                            with no usable URL shows its key alone. */}
                        {iconProperty && imageUrlOf(instance.properties[iconProperty]) && (
                          <img data-testid="object-table-icon" alt="" width={18} height={18} loading="lazy"
                            referrerPolicy="no-referrer" src={imageUrlOf(instance.properties[iconProperty])!}
                            style={{ verticalAlign: "middle", marginRight: 6, borderRadius: 3, objectFit: "cover" }} />
                        )}
                        {instance.primary_key}
                      </div>
                    </td>
                    {properties.map((p, column) => {
                      // p.225: a combined column has values for the types it
                      // covers, and is blank for the others' rows.
                      const covered = !("covers" in p) || !p.covers
                        || p.covers.includes(String(instance.object_type_id));
                      const paint = covered
                        ? conditionalStyle(p.conditional_format, instance.properties)
                        : undefined;
                      // p.242: "users can edit any modifiable column mapped to
                      // an action parameter" - so a column with no parameter
                      // pointed at it stays a value, in edit mode or out of it.
                      const parameter = inEditMode
                        ? parameterForColumn(editMapping, p.api_name)
                        : undefined;
                      return (
                        <td
                          key={`${p.api_name}:${column}`}
                          style={{
                            height: minHeight,
                            // p.225's "Conditional formatting colors entire
                            // cell". The rule is evaluated once either way; the
                            // toggle only decides where the colour lands.
                            ...(fillsCell && paint?.background
                              ? { background: paint.background }
                              : {}),
                            ...stick(column + 1 + leading),
                          }}
                        >
                          <div style={cell}>
                            {!covered ? null : parameter ? (
                              <div
                                data-testid={`edit-${instance.primary_key}-${p.api_name}`}
                                // A click in a cell is typing, not choosing a
                                // row - the same reason p.224's checkbox stops
                                // its own click.
                                onClick={(e) => e.stopPropagation()}
                              >
                                {/* **The same control the action form draws**
                                    (§237). A second typed-input renderer is a
                                    second place for `attachment`, `date` and
                                    `boolean` to disagree, which is the mistake
                                    §237 spent a unit deleting.

                                    **And the same way of switching it off.**
                                    p.242's cap is about rows: a row nobody has
                                    touched cannot be started once the batch is
                                    full, and one already in it stays editable.
                                    A `disabled` prop on `PropertyInput` would
                                    have been a second mechanism for what §237's
                                    fieldset already does, and one this suite
                                    cannot reach - the cap is two hundred rows,
                                    which no browser fixture stages. */}
                                <fieldset
                                  className="canvas-action-field"
                                  disabled={!canStage(staged, instance.id, rowLimit)}
                                >
                                  <PropertyInput
                                    workspaceId={workspaceId}
                                    dataType={p.data_type as never}
                                    // The inline-edit grid edits *properties*,
                                    // so the fields are on the property here
                                    // rather than derived from a rule (§450).
                                    structFields={p.struct_fields}
                                    arrayOf={p.array_of}
                                    // p.241: "If a parameter has defined
                                    // enumerated values … those options will
                                    // be … displayed within an in-cell
                                    // dropdown" (§597).
                                    choices={multipleChoice(
                                      liveAction?.parameters?.find(
                                        (a) => a.api_name === parameter,
                                      ) ?? { data_type: "" },
                                    )}
                                    label={p.display_name || p.api_name}
                                    value={cellValue(
                                      staged, instance.id, parameter,
                                      instance.properties[p.api_name] ?? null,
                                    ) as never}
                                    onChange={(next) =>
                                      setStaged(stage(
                                        staged, instance.id, parameter, next, rowLimit,
                                      ))}
                                  />
                                </fieldset>
                              </div>
                            ) : p.data_type === "time_series" ? (
                              // p.583, and the reason it is not `PropertyValue`:
                              // the stored value is the *id* of the readings,
                              // so the ordinary renderer puts an opaque key in
                              // the cell.
                              <SeriesCell
                                points={seriesByKey.get(instance.primary_key)}
                                pending={seriesPage.isPending}
                                // p.174: the module's formatter for this
                                // column, when one was set.
                                format={columnFormats[p.api_name] ?? null}
                                // p.175: one rule paints the number and the
                                // line, so the match happens once here rather
                                // than twice inside the cell.
                                paint={paintFor(
                                  columnRules[p.api_name],
                                  SERIES_SUBJECT,
                                  latestOf(seriesByKey.get(instance.primary_key) ?? []),
                                  { pending: seriesPage.isPending },
                                )}
                                // p.592-593: this row's baseline (§563).
                                baseline={baselineFor(
                                  columnBaselines[p.api_name],
                                  instance.properties,
                                  (seriesByKey.get(instance.primary_key) ?? [])
                                    .map((point) => point.value as number),
                                )}
                              />
                            ) : p.derivation ? (
                              <DerivedValue
                                workspaceId={workspaceId}
                                property={p}
                                cell={derivedCell(
                                  derivedPage.data, instance.primary_key, p.api_name,
                                )}
                                emptyText={emptyText}
                                testId={`derived-${instance.primary_key}-${p.api_name}`}
                              />
                            ) : usingSet && isUnsupported(p) ? (
                              // p.596: "select ... button to reveal its value".
                              <LoadOnDemand
                                workspaceId={workspaceId}
                                typeId={String(instance.object_type_id ?? effectiveTypeId ?? "")}
                                instanceId={instance.id}
                                property={p}
                                label="…"
                                emptyText={emptyText}
                              />
                            ) : (
                              <PropertyValue
                                workspaceId={workspaceId}
                                dataType={p.data_type}
                                valueFormat={p.value_format}
                                structFields={p.struct_fields}
                                style={paint}
                                value={instance.properties[p.api_name]}
                                emptyText={emptyText}
                                compact
                              />
                            )}
                          </div>
                        </td>
                      );
                    })}
                    {derived.map((c) => {
                      if (c.kind === "function") {
                        const call = functionByCall.get(callKey(c));
                        const value = cellOf(call?.data, instance.primary_key, c.field);
                        return (
                          <td key={`derived-${c.api_name}`} data-derived={c.api_name}>
                            <div
                              className="canvas-cell"
                              data-testid={`function-${instance.primary_key}-${c.api_name}`}
                              // The call's own sentence: a column that cannot
                              // be computed is blank with the reason on it,
                              // not an error in every row.
                              title={call?.error instanceof ApiError ? call.error.message : undefined}
                            >
                              {call?.isPending ? (
                                <span className="soft">…</span>
                              ) : value === undefined || value === null ? (
                                <span className="soft">{emptyText}</span>
                              ) : (
                                String(value)
                              )}
                            </div>
                          </td>
                        );
                      }
                      if (c.kind === "linked") {
                        return (
                          <td key={`derived-${c.api_name}`} data-derived={c.api_name}>
                            <div className="canvas-cell">
                              <DerivedValue
                                workspaceId={workspaceId}
                                cell={derivedCell(
                                  derivedPage.data, instance.primary_key, c.api_name,
                                )}
                                emptyText={emptyText}
                                testId={`derived-${instance.primary_key}-${c.api_name}`}
                              />
                            </div>
                          </td>
                        );
                      }
                      // p.171: "computed on the fly", from this row's values
                      // and the derived ones the page read beside them.
                      const value = valueFor(c, {
                        ...instance.properties,
                        ...(derivedByKey.get(instance.primary_key) ?? {}),
                      });
                      return (
                        <td key={`derived-${c.api_name}`} data-derived={c.api_name}>
                          <div className="canvas-cell">
                            {value === null ? (
                              // **Not a zero.** A missing or non-numeric input
                              // makes the whole expression nothing, and the
                              // cell says so the way every other empty one
                              // does rather than reporting a figure.
                              <span className="soft">{emptyText}</span>
                            ) : (
                              value.toLocaleString()
                            )}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {configuringColumns && (
            <div
              className="explore-menu canvas-columns-panel"
              role="dialog"
              aria-label="Configure columns"
              data-testid="table-columns-panel"
              style={{ position: "fixed", left: configuringColumns.x, top: configuringColumns.y }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              {(() => {
                const current = viewerColumnsOf(offeredColumns, viewerChoice);
                const rest = offeredColumns.filter((name) => !current.includes(name));
                const labelOf = (name: string) =>
                  all.find((p) => p.api_name === name)?.display_name
                  || declaredDerived.find((c) => c.api_name === name)?.display_name
                  || name;
                return [...current, ...rest].map((name) => {
                  const on = current.includes(name);
                  return (
                    <div key={name} className="canvas-columns-row"
                      data-testid={`table-column-${name}`}>
                      <label className="field-check">
                        <input
                          type="checkbox"
                          checked={on}
                          // The last column stays: a table of keys alone is
                          // one a viewer cannot find their way back from.
                          disabled={on && current.length === 1}
                          onChange={() =>
                            setViewerChoice(toggledColumn(offeredColumns, viewerChoice, name))}
                        />
                        <span>{labelOf(name)}</span>
                      </label>
                      {on && (
                        <span className="row-actions">
                          <button type="button" className="btn quiet"
                            aria-label={`Move ${labelOf(name)} left`}
                            data-testid={`table-column-${name}-up`}
                            onClick={() => setViewerChoice(
                              movedColumn(offeredColumns, viewerChoice, name, -1))}>
                            ↑
                          </button>
                          <button type="button" className="btn quiet"
                            aria-label={`Move ${labelOf(name)} right`}
                            data-testid={`table-column-${name}-down`}
                            onClick={() => setViewerChoice(
                              movedColumn(offeredColumns, viewerChoice, name, 1))}>
                            ↓
                          </button>
                        </span>
                      )}
                    </div>
                  );
                });
              })()}
              <button
                type="button"
                className="btn quiet"
                data-testid="table-columns-reset"
                disabled={!viewerChoice}
                onClick={() => setViewerChoice(null)}
              >
                Reset to the table&rsquo;s columns
              </button>
            </div>
          )}
          {rowMenu && (
            <div
              className="explore-menu canvas-row-menu"
              role="menu"
              data-testid="table-row-menu"
              style={{ position: "fixed", left: rowMenu.x, top: rowMenu.y }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              {/* No `offersItems &&`: the menu opens only in run mode,
                  where having items is offering them (§613's sweep). */}
              {rowItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="menuitem"
                  className="btn quiet"
                  data-testid={`table-row-item-${item.id}`}
                  onClick={() => {
                    setRowMenu(null);
                    runEvents(eventsFor(moduleEvents, nodeId, "click", item.id), {
                      ...eventContext,
                      ...selectionOf(rowMenu.instance, effectiveTypeId),
                    });
                  }}
                >
                  {item.label}
                </button>
              ))}
              {offersExport && exportExcel && (<button
                type="button"
                role="menuitem"
                className="btn quiet"
                data-testid="table-export-excel"
                onClick={() => {
                  setRowMenu(null);
                  // p.223's "Enable export to Excel" (§788): the table's
                  // property columns. Its derived ones go in the CSV, which
                  // p.223 says carries them, as p.489's Excel does not.
                  exportObjects({
                    variable: objectSetVariable!,
                    definition: setDefinition,
                    format: "excel",
                    fileName: null,
                    properties: shownColumns
                      ? [...new Set(shownColumns.filter((n) =>
                          all.some((p) => p.api_name === n)))]
                      : properties.map((p) => p.api_name),
                  });
                }}
              >
                Export to Excel
              </button>)}
              {offersExport && exportCsv && (<button
                type="button"
                role="menuitem"
                className="btn quiet"
                data-testid="table-export-csv"
                onClick={() => {
                  setRowMenu(null);
                  const shownDerived = derived as DerivedColumn[];
                  exportObjects({
                    variable: objectSetVariable!,
                    definition: setDefinition,
                    format: "csv",
                    fileName: null,
                    // p.223: "supports exporting function-backed columns and
                    // linked object properties" (§778) - the columns this
                    // table shows, its derived ones in their places.
                    properties: shownColumns
                      ? [...new Set(shownColumns.filter((n) =>
                          all.some((p) => p.api_name === n)
                          || shownDerived.some((c) => c.api_name === n)))]
                      : properties.map((p) => p.api_name),
                    headers: Object.fromEntries(
                      shownDerived.map((c) => [c.api_name, c.display_name || c.api_name])),
                    derive: (exported) => derivedForExport(exported, shownDerived, {
                      readDerived: needsDerived
                        ? (keys) => objApi.derivedValues(
                            workspaceId, String(effectiveTypeId), { keys, ...derivedWanted })
                        : undefined,
                      callFunction: (c, keys) => objApi.executeFunction(
                        workspaceId, c.function_id, callValues(c, keys, variableValues), c.version),
                    }, derivedWanted.properties),
                  });
                }}
              >
                Export to CSV
              </button>)}
            </div>
          )}
          {derivedSorted.data && "tooMany" in derivedSorted.data && (
            // p.173's limit, said where the order would have been.
            <p className="canvas-widget-empty" data-testid="table-derived-sort-limit">
              Sorting by {sortColumn?.display_name || sortColumn?.api_name} reads at most{" "}
              {derivedSortLimit(sortColumn!).toLocaleString()} objects (Workshop p.173), and
              this set holds {derivedSorted.data.tooMany.toLocaleString()} - so the rows are
              not in that order.
            </p>
          )}
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
                disabled={offset + rows.length >= total
                  || (combined && offset + pageSize >= UNION_PAGE_DEPTH)}
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
          {combined && total > UNION_PAGE_DEPTH && (
            <p className="canvas-widget-empty" data-testid="table-combined-depth">
              A combined table shows the first {UNION_PAGE_DEPTH} of these; narrow it, or turn
              off Combine to page each type in its own tab.
            </p>
          )}
          {/* p.242: the button lives "in the table footer", and p.243 puts
              Submit "in the bottom right corner of the table". */}
          {mode === "run" && !!liveAction && Object.keys(editMapping).length > 0 && (
            <div className="canvas-table-edit" data-testid="inline-edit-footer">
              <button
                type="button"
                className="btn quiet"
                data-testid="inline-edit-toggle"
                onClick={() => {
                  const next = !inEditMode;
                  setEditOpen(next);
                  // **Leaving edit mode discards what was staged**, and says so
                  // on the button below. Keeping it would leave edits pending
                  // behind a closed table, where the only sign of them is a
                  // Submit nobody can see.
                  if (!next) {
                    setStaged({});
                    setSubmitError(null);
                  }
                }}
              >
                {inEditMode ? "Done" : buttonTextOf(inlineEditButtonText)}
              </button>
              {inEditMode && (
                <>
                  <span className="canvas-widget-empty" data-testid="inline-edit-count">
                    {stagedCount(staged) === 1
                      ? "1 row edited"
                      : `${stagedCount(staged)} rows edited`}
                  </span>
                  <button
                    type="button"
                    className="btn"
                    data-testid="inline-edit-submit"
                    disabled={!canSubmit(staged, liveAction) || submit.isPending}
                    onClick={() =>
                      // p.243's dialog is the default and the toggle is the way
                      // past it - the safer direction for a control that writes
                      // to every staged row at once.
                      oneClickOf(inlineEditOneClick) ? submit.mutate() : setConfirming(true)
                    }
                  >
                    {submit.isPending ? "Submitting…" : "Submit"}
                  </button>
                </>
              )}
              {limitNotice(staged, rowLimit) && (
                <span className="form-error" data-testid="inline-edit-limit">
                  {limitNotice(staged, rowLimit)}
                </span>
              )}
              {submitError && (
                <span className="form-error" data-testid="inline-edit-error">
                  {submitError}
                </span>
              )}
            </div>
          )}
          {confirming && (
            /* p.243: "A confirmation dialog will appear where you will again
               press Submit to submit your changes." */
            <div className="canvas-confirm" role="dialog" aria-modal="true"
              aria-label="Submit these edits" data-testid="inline-edit-confirm">
              <p>
                Submit {stagedCount(staged) === 1
                  ? "1 edited row" : `${stagedCount(staged)} edited rows`}?
                {" "}They are written together, or not at all.
              </p>
              <div className="canvas-table-edit">
                <button type="button" className="btn quiet"
                  onClick={() => setConfirming(false)}>
                  Cancel
                </button>
                <button type="button" className="btn"
                  data-testid="inline-edit-confirm-submit"
                  onClick={() => submit.mutate()}>
                  Submit
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** The Loop's p.132 sort as `useSetPage` wants it.
 *
 * `undefined` means "the set's own order", which is what an unconfigured loop
 * has always had and must keep — so the fallback is the empty string rather than
 * one of the four fixed sorts, and an empty string is no `sort` key at all. The
 * Object Dropdown's fallback is `key` for the opposite reason: a picker with no
 * predictable order is a worse picker, while a looped layout with no configured
 * order is simply the set.
 */
function sortOfLoop(
  raw: unknown,
  declared: readonly SortableProperty[] | undefined,
): string | undefined {
  return requestSort(raw, declared, "") || undefined;
}

CanvasObjectTable.craft = {
  displayName: "Object table",
  props: {
    objectTypeId: null, filterProperty: null, filterParameter: null,
    searchParameter: null, pageSize: 25, columns: "", sort: "recent",
    activeVariable: null, autoSelect: true, multiSelect: false,
    selectedVariable: null, lines: DEFAULT_LINES, valueWrap: false,
    frozenColumns: 0, emptyMode: "default", emptyMessage: "", emptyIcon: "",
    customNoValue: false, noValueText: "", fitColumns: true,
    narrowHeaders: false, formatFillsCell: false,
    inlineEditAction: null, inlineEditMapping: null, inlineEditVariables: null,
    inlineEditButtonText: "",
    inlineEditByDefault: false, inlineEditOneClick: false,
    seriesFormats: null, seriesRules: null, seriesTransforms: null, seriesBaselines: null,
    columnsVariable: null, exportCsv: false, exportExcel: false, hideColumnConfig: false,
    combineTypes: false,
    customMenu: false, menuItems: null, rightClickedVariable: null,
  },
  related: { settings: settingsPanel("ObjectTableSettings") },
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
  enableDrag = false,
}: {
  /** p.274's Enable drag: "Enables dragging the objects within the object set
   * to an accepting drop zone. Must … have fewer than 500 objects within the
   * object set." p.274's other condition, a data bank service, is Foundry's
   * transport for the drag and has no counterpart to install here. */
  enableDrag?: boolean;
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

  // p.274's drag. The keys are fetched ahead of the drag, because `dragstart`
  // is synchronous and a drag that had to wait for a request would carry
  // nothing. Sorted by key so the pages cannot shift under the walk.
  const total = setPage.total ?? 0;
  const dragWanted = enableDrag && mode === "run" && !showingPlaceholder && !!setPage.typeId;
  const tooMany = total > MAX_DRAGGED_OBJECTS;
  const dragKeys = useQuery({
    queryKey: ["set-title-drag", workspaceId, JSON.stringify(setDefinition ?? null), total],
    queryFn: () => collectKeys(
      async (offset, limit) =>
        (await objApi.evaluateObjectSet(workspaceId, setDefinition, {
          limit, offset, sort: "key",
        })).instances,
      total,
    ),
    enabled: dragWanted && total > 0 && !tooMany,
  });
  const dragPayload = dragWanted && dragKeys.data && setPage.typeId
    ? objectSetPayload(setPage.typeId, dragKeys.data)
    : null;

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
        <h3
          className="canvas-set-title"
          data-testid="set-title"
          data-drag={dragWanted ? (dragPayload ? "ready" : tooMany ? "refused" : "pending") : undefined}
          draggable={!!dragPayload || undefined}
          style={dragPayload ? { cursor: "grab" } : undefined}
          // Said rather than silently inert: a title that will not drag looks
          // exactly like one whose drag is broken.
          title={dragWanted && tooMany
            ? "Too many objects to drag: an object set can be dragged while it has fewer than 500"
            : undefined}
          onDragStart={dragPayload ? (event) => {
            event.dataTransfer.setData(OBJECT_SET_MEDIA_TYPE, dragPayload);
            event.dataTransfer.effectAllowed = "copy";
          } : undefined}
        >
          {showIconOf(showIcon) && (
            // The type's mark (§705): its named icon, or the glyph it falls
            // back to, on its colour - what the Explorer and the object view
            // draw. The icon's name travels as the accessible label.
            <span
              className="canvas-set-title-icon"
              data-testid="set-title-icon"
              role="img"
              aria-label={type.data?.icon || "object type"}
              style={{ background: type.data?.colour || "var(--accent)" }}
            >
              {type.data && <TypeGlyph type={type.data} size={11} />}
            </span>
          )}
          <span>{title}</span>
        </h3>
      )}
    </div>
  );
}

CanvasObjectSetTitle.craft = {
  displayName: "Object set title",
  props: {
    objectSetVariable: null, single: false, showIcon: false,
    titleOverride: "", renderWhenEmpty: false, placeholderTypeId: null, enableDrag: false,
  },
  related: { settings: settingsPanel("ObjectSetTitleSettings") },
};

// ---- Property list (p.265-266) --------------------------------------------------
/** p.265-266's Property List: "a list of properties from a single provided object".
 *
 * Which properties and how they are arranged is `property-list.ts`. What is here
 * is the fetch — one object out of a set, plus the type that says what its
 * properties are called and how to draw each one.
 *
 * **p.266's inline editing** (§594): a property whose inline action is set in
 * the Ontology Manager, and which that action still backs, can be edited in
 * place in a running module - one submission of the action for one object,
 * whose other parameters keep the object's values (`action-types` p.135).
 *
 * **Not built, and named rather than approximated**: p.265's "Load data from
 * scenario" (there are no Scenarios here) and p.266's security markings (no
 * markings).
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
  const { workspaceId, projectId, mode } = useCanvasEnv();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();

  // The type first: p.266's unsupported properties "are not loaded by
  // default", so the page leaves them out and a reader loads each (§693).
  const typeId = (setDefinition as { object_type_id?: string } | undefined)?.object_type_id
    ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const heavy = omittedOf(type.data?.properties ?? []);
  // p.265: "If the object set contains more than one object, only the first
  // object will be displayed within the widget." One row is all it ever needs.
  const setPage = useSetPage(workspaceId, !typeId || type.data ? setDefinition : null, {
    pageSize: 1, variablesPending, omit: heavy,
  });

  // `[0]` and `[length - 1]` are the same expression here, because the fetch
  // above asks for one row: p.265's "only the first object will be displayed"
  // is kept by the *page size*, not by the index.
  const instance = setPage.rows?.[0];
  const shown = visibleProperties({
    all: type.data?.properties ?? [],
    chosen: properties,
    // Not hidden as null before it is loaded.
    values: valuesForHiding(instance?.properties, heavy),
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
                {isUnsupported(p) ? (
                  // p.266: "select Load next to an unsupported property".
                  <LoadOnDemand
                    workspaceId={workspaceId}
                    typeId={setPage.typeId}
                    instanceId={instance.id}
                    property={p}
                    label="Load"
                  />
                ) : (
                  <PropertyValue
                    workspaceId={workspaceId}
                    dataType={p.data_type}
                    valueFormat={p.value_format}
                    structFields={p.struct_fields}
                    style={conditionalStyle(p.conditional_format, instance.properties)}
                    value={instance.properties[p.api_name]}
                  />
                )}
                {mode === "run" && p.inline_action_type_id && (
                  <PropertyInlineEdit
                    workspaceId={workspaceId}
                    projectId={projectId}
                    property={p}
                    instanceId={instance.id}
                    value={instance.properties[p.api_name] ?? null}
                    // Every reader of the object in the module, as the
                    // Object Table's save refreshes.
                    refreshKeys={[["canvas-object-table"], ["canvas-object-set"]]}
                  />
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

CanvasPropertyList.craft = {
  displayName: "Property list",
  props: {
    objectSetVariable: null, layout: "adjacent", properties: "",
    columns: 1, hideNull: false,
  },
  related: { settings: settingsPanel("PropertyListSettings") },
};

// ---- Links (p.268-272) ------------------------------------------------------
/** p.268-272's Links widget: "the links relationship between objects and
 * provide exploration into those paths".
 *
 * Which rows are drawn, what they are called and which of them open on load is
 * `links-widget.ts`. What is here is the fetch - one object out of the bound
 * set, then every mapped link from it in a single request, which is what
 * `instance_links` exists to answer.
 *
 * **Not built, and named rather than approximated**: p.270's "Load data from
 * scenario" (there are no Scenarios here); p.271's "Enable exploration on link
 * types" and "Enable open object view on linked objects", which need the
 * Object View widget that `workshop.md`'s build order still has ahead of this;
 * p.271-272's hover preview and the properties shown in it, which is the same
 * dependency seen from the other side; and p.272's "Sort linked object by",
 * because the traversal endpoint returns one page per link in the store's own
 * order and a control that reordered *that page* would claim to sort the link
 * while only shuffling the first ten of it.
 */
export function CanvasLinksWidget({
  objectSetVariable = null,
  linkMode = "all",
  links = [],
  defaultExpand = 0,
  exploreLinks = false,
  openObjects = false,
  previewOnHover = false,
}: {
  objectSetVariable?: string | null;
  /** p.270's "Link types to display": all of them, or the configured list. */
  linkMode?: string;
  /** p.272's per-link configuration, keyed on `${link_type_id}:${direction}`. */
  links?: ChosenLink[];
  /** p.271's "Default link expand". */
  defaultExpand?: number;
  /** p.271's linked objects configuration (§547): a button to view a link's
   * objects in the Object Explorer, one to open a linked object's Object
   * View there, and a preview of its prominent properties on hover. */
  exploreLinks?: boolean;
  openObjects?: boolean;
  previewOnHover?: boolean;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  // The Explorer's address is by slug, and a module is addressed by id.
  const slug = useWorkspaceById(workspaceId).workspace?.slug ?? null;
  const [previewing, setPreviewing] = useState<string | null>(null);
  // p.268's further exploration (§712): which linked objects are open.
  const [expandedObjects, setExpandedObjects] = useState<string[]>([]);
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();

  // One row: p.268's widget explores the links of *an* object, and a page of
  // twenty-five would be twenty-four objects fetched to be thrown away.
  const setPage = useSetPage(workspaceId, setDefinition, {
    pageSize: 1, variablesPending,
  });
  const instance = setPage.rows?.[0];
  // The same query key the Object Explorer's traversal dialog uses, so a
  // reader who opens both pays for one request.
  // p.268's "input object set which may contain one or more object types"
  // (§712): the object's own type, which a union's rows carry (§688) and a
  // one-type set's rows may not, where the set's is the same answer.
  const objectTypeId = instance?.object_type_id ?? setPage.typeId;
  // The object the links are followed from, for a link the Explorer opens as
  // a traversal (§793).
  const near = objectTypeId && instance
    ? { typeId: String(objectTypeId), key: String(instance.primary_key) } : null;
  const linkQuery = useQuery({
    queryKey: ["instance-links", workspaceId, objectTypeId, instance?.id],
    queryFn: () => objApi.instanceLinks(workspaceId, objectTypeId!, instance!.id, "workshop"),
    enabled: !!objectTypeId && !!instance,
  });

  const chosen = linkChosenOf(links);
  const visible = visibleLinks(linkQuery.data ?? [], linkMode, chosen);
  const expand = defaultExpandOf(defaultExpand);
  // The linked types, for each object's title and p.271's prominent
  // properties.
  const farIds = [...new Set(visible.map((g) => g.far_type_id))];
  const farTypes = useQueries({
    queries: farIds.map((id) => ({
      queryKey: ["object-type", id],
      queryFn: () => objApi.getType(workspaceId, id),
    })),
  });
  const farType = (id: string) => farTypes[farIds.indexOf(id)]?.data;
  // p.272's Sort linked object by (§548): a sorted link's first page, asked
  // for again in its order (`sortedLinkQuery`).
  // A sort is part of a *specified* link (p.272), so in "all links" mode
  // there is none to ask for, whatever an older configuration left behind.
  const specifying = linkModeOf(linkMode) === "specify";
  const sortedAsks = visible.map((g) =>
    specifying ? sortedLinkQuery(g, linkSortOf(chosen, linkKey(g)), objectTypeId ?? undefined)
      : null);
  const sortedPages = useQueries({
    queries: sortedAsks.map((ask) => ({
      queryKey: ["canvas-links-sorted", JSON.stringify(ask)],
      queryFn: () => objApi.evaluateObjectSet(workspaceId, ask!.definition,
        { limit: LINK_PAGE, sort: ask!.sort }),
      enabled: !!ask,
    })),
  });

  // p.271's default expansion is a *starting* state, so it is seeded rather
  // than computed: once somebody has folded a section away, re-deriving it
  // every render would open it again on the next fetch. Re-seeded when the
  // object, the configuration or the count changes, because each of those
  // makes the previous answer about a different widget.
  const [open, setOpen] = useState<string[]>([]);
  const seed = `${instance?.id ?? ""}|${visible.map(linkKey).join(",")}|${expand}`;
  const [seeded, setSeeded] = useState<string | null>(null);
  if (linkQuery.data && seed !== seeded) {
    setSeeded(seed);
    setOpen(initiallyExpanded(visible, expand));
  }

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectSetVariable ? (
        <p className="canvas-widget-empty">Links - bind an object set in Settings</p>
      ) : setPage.unresolved ? (
        <p className="canvas-widget-empty">Resolving the object set…</p>
      ) : !instance ? (
        <p className="canvas-widget-empty" data-testid="links-no-object">No object to show</p>
      ) : linkQuery.isPending ? (
        <p className="canvas-widget-empty">Following links…</p>
      ) : visible.length === 0 ? (
        // Distinct from "no object": the object is there and has no link this
        // widget was asked to draw, which is a different thing to fix.
        <p className="canvas-widget-empty" data-testid="links-none">No links to show</p>
      ) : (
        <ul className="canvas-links" data-testid="links">
          {visible.map((group, index) => {
            const key = linkKey(group);
            const isOpen = open.includes(key);
            const sorted = sortedAsks[index] ? sortedPages[index] : null;
            const items = sorted ? sorted.data?.instances ?? null : group.items;
            return (
              <li className="canvas-link-group" key={key} data-testid="link-group">
                <button
                  type="button"
                  className="canvas-link-header"
                  aria-expanded={isOpen}
                  data-testid={`link-toggle-${key}`}
                  onClick={() => setOpen(toggleExpanded(open, key))}
                >
                  <span className="canvas-link-caret" aria-hidden>{isOpen ? "▾" : "▸"}</span>
                  <span className="canvas-link-label" data-testid="link-label">
                    {labelFor(group, chosen)}
                  </span>
                  <span className="canvas-link-count">
                    {group.total} {group.far_type_display_name}
                  </span>
                </button>
                {exploreLinks === true && slug && linkSubsetHref(slug, group, near) && (
                  <a
                    className="canvas-link-explore"
                    data-testid={`link-explore-${key}`}
                    href={linkSubsetHref(slug, group, near)!}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Explore
                  </a>
                )}
                {isOpen && (
                  items === null ? (
                    // Not the store's page while the sorted one comes: a list
                    // that reorders itself under the reader is worse than none.
                    <p className="canvas-link-empty">Sorting…</p>
                  ) : items.length === 0 ? (
                    <p className="canvas-link-empty" data-testid="link-empty">
                      Nothing on the other side of this link
                    </p>
                  ) : (
                    <ul className="canvas-link-objects">
                      {items.map((i) => {
                        const far = farType(group.far_type_id);
                        const title = titleOf(i, far?.properties
                          .find((p) => p.id === far.title_property_id)?.api_name);
                        // Only ever set by the hover handlers, which exist only
                        // when the preview is on.
                        const shown = previewing === `${key}/${i.id}`;
                        return (
                          <li key={i.id} data-testid="link-object"
                            onMouseEnter={previewOnHover === true
                              ? () => setPreviewing(`${key}/${i.id}`) : undefined}
                            onMouseLeave={previewOnHover === true
                              ? () => setPreviewing(null) : undefined}
                          >
                            <LinkObjectExpand
                              depth={1}
                              open={expandedObjects.includes(`${key}/${i.id}`)}
                              title={title}
                              onToggle={() => setExpandedObjects(
                                toggleExpanded(expandedObjects, `${key}/${i.id}`))}
                            />
                            <span data-testid="link-object-title">{title}</span>
                            {openObjects === true && slug && (
                              <a
                                className="canvas-link-open"
                                data-testid="link-object-open"
                                href={objectViewHref(slug, group.far_type_id, i.id)}
                                target="_blank"
                                rel="noreferrer"
                                aria-label={`Open ${title}`}
                              >
                                Open
                              </a>
                            )}
                            {shown && far && (
                              <dl className="canvas-link-preview" data-testid="link-object-preview">
                                {previewProperties(far.properties,
                                  specifying ? linkPreviewOf(chosen, key) : undefined).map((p) => (
                                  <Fragment key={p.api_name}>
                                    <dt>{p.display_name || p.api_name}</dt>
                                    <dd>{String(i.properties[p.api_name] ?? "—")}</dd>
                                  </Fragment>
                                ))}
                              </dl>
                            )}
                            {expandedObjects.includes(`${key}/${i.id}`) && (
                              <NestedLinks
                                workspaceId={workspaceId}
                                typeId={group.far_type_id}
                                instanceId={i.id}
                                depth={1}
                                slug={slug}
                                openObjects={openObjects === true}
                              />
                            )}
                          </li>
                        );
                      })}
                      {group.total > items.length && (
                        // The traversal returns a first page, not the far side.
                        <li className="canvas-link-more">
                          Showing {items.length} of {group.total}
                        </li>
                      )}
                    </ul>
                  )
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** p.268's further exploration (§712): one linked object's own links, below
 * it, each opening to its objects and each of those to *its* links, to
 * `MAX_LINK_DEPTH`. p.272's specified-link configuration is about the
 * starting set's links, so a level below shows all of an object's links,
 * folded until asked for, in the store's order. */
function NestedLinks({ workspaceId, typeId, instanceId, depth, slug, openObjects }: {
  workspaceId: string;
  typeId: string;
  instanceId: string;
  /** The level of the object these are the links *of*: 1 for a linked object. */
  depth: number;
  slug: string | null;
  openObjects: boolean;
}) {
  const links = useQuery({
    queryKey: ["instance-links", workspaceId, typeId, instanceId],
    queryFn: () => objApi.instanceLinks(workspaceId, typeId, instanceId, "workshop"),
  });
  const groups = links.data ?? [];
  const farIds = [...new Set(groups.map((g) => g.far_type_id))];
  const farTypes = useQueries({
    queries: farIds.map((id) => ({
      queryKey: ["object-type", id],
      queryFn: () => objApi.getType(workspaceId, id),
    })),
  });
  const farType = (id: string) => farTypes[farIds.indexOf(id)]?.data;
  const [open, setOpen] = useState<string[]>([]);
  const [expanded, setExpanded] = useState<string[]>([]);
  if (links.isPending) return <p className="canvas-link-empty">Following links…</p>;
  if (groups.length === 0) {
    return <p className="canvas-link-empty" data-testid="link-nested-none">No links</p>;
  }
  return (
    <ul className="canvas-links canvas-links--nested" data-testid="links-nested" data-depth={depth}>
      {groups.map((group) => {
        const key = linkKey(group);
        const isOpen = open.includes(key);
        return (
          <li className="canvas-link-group" key={key} data-testid="link-group">
            <button
              type="button"
              className="canvas-link-header"
              aria-expanded={isOpen}
              data-testid={`link-toggle-${key}`}
              onClick={() => setOpen(toggleExpanded(open, key))}
            >
              <span className="canvas-link-caret" aria-hidden>{isOpen ? "▾" : "▸"}</span>
              <span className="canvas-link-label" data-testid="link-label">{group.side_name}</span>
              <span className="canvas-link-count">
                {group.total} {group.far_type_display_name}
              </span>
            </button>
            {isOpen && (group.items.length === 0 ? (
              <p className="canvas-link-empty" data-testid="link-empty">
                Nothing on the other side of this link
              </p>
            ) : (
              <ul className="canvas-link-objects">
                {group.items.map((i) => {
                  const far = farType(group.far_type_id);
                  const title = titleOf(i, far?.properties
                    .find((p) => p.id === far.title_property_id)?.api_name);
                  const row = `${key}/${i.id}`;
                  return (
                    <li key={i.id} data-testid="link-object">
                      <LinkObjectExpand
                        depth={depth + 1}
                        open={expanded.includes(row)}
                        title={title}
                        onToggle={() => setExpanded(toggleExpanded(expanded, row))}
                      />
                      <span data-testid="link-object-title">{title}</span>
                      {openObjects && slug && (
                        <a
                          className="canvas-link-open"
                          data-testid="link-object-open"
                          href={objectViewHref(slug, group.far_type_id, i.id)}
                          target="_blank"
                          rel="noreferrer"
                          aria-label={`Open ${title}`}
                        >
                          Open
                        </a>
                      )}
                      {expanded.includes(row) && (
                        <NestedLinks
                          workspaceId={workspaceId}
                          typeId={group.far_type_id}
                          instanceId={i.id}
                          depth={depth + 1}
                          slug={slug}
                          openObjects={openObjects}
                        />
                      )}
                    </li>
                  );
                })}
                {group.total > group.items.length && (
                  <li className="canvas-link-more">
                    Showing {group.items.length} of {group.total}
                  </li>
                )}
              </ul>
            ))}
          </li>
        );
      })}
    </ul>
  );
}

/** The control that opens a linked object to its own links (§712), absent
 * at the depth bound. */
function LinkObjectExpand({ depth, open, title, onToggle }: {
  depth: number;
  open: boolean;
  title: string;
  onToggle: () => void;
}) {
  if (!expandsFurther(depth)) return null;
  return (
    <button
      type="button"
      className="canvas-link-expand"
      aria-expanded={open}
      aria-label={`${open ? "Hide" : "Show"} the links of ${title}`}
      data-testid="link-object-expand"
      onClick={onToggle}
    >
      {open ? "▾" : "▸"}
    </button>
  );
}

CanvasLinksWidget.craft = {
  displayName: "Links",
  props: {
    objectSetVariable: null, linkMode: "all", links: [], defaultExpand: 0,
    exploreLinks: false, openObjects: false, previewOnHover: false,
  },
  related: { settings: settingsPanel("LinksWidgetSettings") },
};

// ---- Object View (p.259-263) ------------------------------------------------
/** **Loaded dynamically to break a real import cycle.**
 *
 * `object-view.tsx` imports `CANVAS_RESOLVER` from this file, because a
 * configured object view *is* a module and rendering one needs the widget
 * table. Importing it back statically would close the loop, and which half
 * ends up `undefined` then depends on which module the bundler reaches first —
 * a failure that appears as a blank widget with no error. The dynamic import
 * defers the edge to render time, which is when both halves exist. It is the
 * same instrument `repository-app.tsx` uses on Monaco, for a different reason.
 */
const EmbeddedObjectView = dynamic(
  () => import("@/components/object-view").then((m) => m.ObjectView),
  { loading: () => <p className="canvas-widget-empty">Loading this object&apos;s view…</p> },
);

/** p.41's configured object set panel (§744), dynamically for
 * `EmbeddedObjectView`'s reason: `configured-object-view.tsx` renders a
 * module, so it imports this file. */
const ConfiguredSetPanel = dynamic(
  () => import("@/components/configured-object-view").then((m) => m.ConfiguredSetPanel),
  { loading: () => <p className="canvas-widget-empty">Loading this panel…</p> },
);

/** p.259-263's Object View widget: "detailed information about a single object
 * by displaying an embedded object view within a Workshop module".
 *
 * Which view opens and whether the reader may switch is
 * `object-view-widget.ts`. What is here is the fetch and the composition —
 * and the composition is the point: this renders **the same `ObjectView` the
 * Object Explorer and the traversal dialog render**, rather than a Workshop
 * copy of it. A second renderer of an object view would be a second place for
 * a configured view, a prominent geopoint's map and a derived property to
 * drift, which is the mistake `object-properties.ts` exists to record.
 *
 * p.261's **panel form factor** and p.263's panel behaviours are §694's: an
 * object instance panel is the type's configured panel view or `object-views`
 * p.41's default, and an object set panel is p.41's Charts and List
 * (`object-panels.tsx`).
 *
 * p.262-263's **Hide tabs**, **Go to initial tab on object switch** and
 * **Initial object view tab ID** are §695's, over `object-views` p.35's tabs.
 *
 * p.263's **Interface configuration** is §710's (`viewInterface`) and p.262's
 * Empty state **icon** §709's. p.263's **Revert to legacy widget** has no
 * legacy widget here to revert to.
 */
export function CanvasObjectViewWidget({
  objectSetVariable = null,
  viewMode = "configured",
  allowToggle = true,
  hideHeader = false,
  emptyMessage = "",
  emptyIcon = "",
  viewInterface = {},
  formFactor = "full",
  panelBehavior = "instance",
  hideTabs = false,
  goToInitialTab = false,
  initialTabId = "",
}: {
  /** p.262's Empty state icon (§709): "Builders can select an icon and
   * configure a custom message to display." */
  emptyIcon?: string;
  /** p.263's Interface configuration (§710): this module's variables passed
   * into the view's tabs, `{"<tab id>:<external id>": variable id}`. */
  viewInterface?: Record<string, string>;
  /** p.262's Hide tabs (§695). */
  hideTabs?: boolean;
  /** p.262's Go to initial tab on object switch (§695). */
  goToInitialTab?: boolean;
  /** p.263's Initial object view tab ID (§695); blank is the first tab. */
  initialTabId?: string;
  /** p.261's Form factor (§694). */
  formFactor?: string;
  /** p.263's Panel behavior (§694). */
  panelBehavior?: string;
  objectSetVariable?: string | null;
  /** p.261's Object View Mode. */
  viewMode?: string;
  /** p.261's "with an option to toggle between them". */
  allowToggle?: boolean;
  /** p.262's Hide header. */
  hideHeader?: boolean;
  /** p.262's Empty state message. */
  emptyMessage?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, mode } = useCanvasEnv();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending, resolved: hostValues } = useCanvasVariables();
  const { set: setHostVariable } = useCanvasParameters();

  // p.261: "only the first object will be shown if the object set contains
  // multiple objects."
  const setPage = useSetPage(workspaceId, setDefinition, {
    pageSize: 1, variablesPending,
  });
  const instance = setPage.rows?.[0];
  // p.35's tab the reader picked (§695), held here rather than in the view:
  // the view is unmounted while the set resolves, and p.262's "Go to initial
  // tab on object switch" is this widget's setting about its own object.
  const [pickedTab, setPickedTab] = useState<string | null>(null);
  const [tabObject, setTabObject] = useState<string | null>(null);
  if (instance && instance.id !== tabObject) {
    setTabObject(instance.id);
    if (goToInitialTab === true) setPickedTab(null);
  }
  const panel = formFactorOf(formFactor) === "panel";
  // p.263: which of the two panels, by the set's size.
  const shows = panel ? panelShows(panelBehaviorOf(panelBehavior), setPage.total ?? 0) : "instance";
  // p.41's configured object set panel (§744), asked only when the set panel
  // is what this widget is showing.
  const setPanelView = useQuery({
    queryKey: ["object-view", workspaceId, setPage.typeId, "panel_set"],
    queryFn: () => objApi.getView(workspaceId, setPage.typeId!, "panel_set"),
    enabled: shows === "set" && !!setPage.typeId,
  });
  // The wrapper below carries no class of its own. The first version gave it
  // `min-width: 0; overflow-x: auto` for §208's reason, and the harness said
  // nothing could tell: `.canvas-frame-area` already carries `min-width: 0` and
  // a wide grid already scrolls inside itself, so it was a third copy of a rule
  // two other places enforce - deleted for the same reason the `hasConfigured`
  // guard was.
  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectSetVariable ? (
        <p className="canvas-widget-empty">Object view - bind an object set in Settings</p>
      ) : setPage.unresolved ? (
        <p className="canvas-widget-empty">Resolving the object set…</p>
      ) : shows === "set" && setPage.typeId ? (
        <div data-testid="object-view-widget" data-panel="set">
          {/* p.41's configured object set panel when the type has one (§744),
              p.41's default otherwise. */}
          {setPanelView.data ? (
            <ConfiguredSetPanel
              key={`${setPanelView.data.canvas_app_id}:${JSON.stringify(setDefinition)}`}
              workspaceId={workspaceId}
              appId={setPanelView.data.canvas_app_id}
              subjectVariable={setPanelView.data.subject_variable}
              definition={setDefinition}
              fallback={<ObjectSetPanel workspaceId={workspaceId} definition={setDefinition}
                typeId={setPage.typeId} />}
            />
          ) : setPanelView.isPending ? (
            <p className="canvas-widget-empty">Loading…</p>
          ) : (
            <ObjectSetPanel
              workspaceId={workspaceId}
              definition={setDefinition}
              typeId={setPage.typeId}
            />
          )}
        </div>
      ) : !instance || !setPage.typeId ? (
        <p className="canvas-widget-empty" data-testid="object-view-empty">
          {emptyIcon.trim() && (
            <span className="canvas-empty-icon" data-testid="object-view-empty-icon" aria-hidden="true">
              <IconOrGlyph value={emptyIcon} size={16} />
            </span>
          )}
          {objectViewEmptyMessageOf(emptyMessage)}
        </p>
      ) : (
        <div data-testid="object-view-widget" data-panel={panel ? "instance" : undefined}>
          <EmbeddedObjectView
            workspaceId={workspaceId}
            typeId={setPage.typeId}
            instance={instance}
            // **Neither of these asks whether the type has a configured
            // view**, and it used to. `ObjectView` opens the standard one when
            // there is none and withholds a switch that leads nowhere; a
            // harness run replacing this widget's answer with a constant
            // changed nothing on screen, which is what a second copy of a
            // guard looks like from outside.
            initialStandard={viewModeOf(viewMode) === "standard"}
            allowToggle={allowToggleOf(allowToggle)}
            hideHeader={hideHeaderOf(hideHeader)}
            // p.570: in a running module the header's icon is a drag zone.
            dragIcon={mode === "run"}
            // §595, `action-types` p.135's "native Object View widgets": a
            // property with an inline action is edited in place, in a running
            // module only. Who may write is the server's to refuse.
            canEdit={mode === "run"}
            formFactor={panel ? "panel" : "full"}
            hideTabs={hideTabs === true}
            initialTabId={initialTabId || null}
            pickedTab={pickedTab}
            onPickTab={setPickedTab}
            // p.263's Interface configuration (§710), both ways as p.127's is.
            interfaceLink={{ mapping: viewInterface, values: hostValues, set: setHostVariable }}
          />
        </div>
      )}
    </div>
  );
}

CanvasObjectViewWidget.craft = {
  displayName: "Object view",
  props: {
    objectSetVariable: null, viewMode: "configured", allowToggle: true,
    hideHeader: false, emptyMessage: "", emptyIcon: "", viewInterface: {}, formFactor: "full",
    panelBehavior: "instance",
    hideTabs: false, goToInitialTab: false, initialTabId: "",
  },
  related: { settings: settingsPanel("ObjectViewWidgetSettings") },
};

// ---- Pie chart (p.309-310) --------------------------------------------------
/** p.309-310's Pie Chart: objects grouped by a property into proportional
 * slices.
 *
 * The slice arithmetic, the document reads and the SVG geometry are
 * `pie-chart.ts`, and **Chart XY's pie renders through the same functions** —
 * one pie, two widgets. What is here is the fetch: `/object-sets/group`, which
 * has answered grouped counts over an object set since roadmap 1.5 and is
 * exactly what p.310's "each property type value will be represented by a
 * slice" asks for.
 *
 * **Five of p.310's six aggregations landed in §227 and §228**, and this
 * paragraph used to list them as not built "because instance properties are
 * stored untyped and the two stores would disagree about a sum (decision
 * 0006)". `/object-sets/group` takes an aggregation and a property now.
 * The sixth, `count_distinct`, followed in §615 once the grouped endpoint
 * answered it per bucket.
 *
 * p.309's **export as PNG / copy to clipboard** (§529) is `ChartExport`,
 * shown on hover in view mode.
 */
export function CanvasPieChart({
  objectSetVariable = null,
  groupBy = "",
  aggregation = "count",
  aggregationProperty = "",
  inner = 0,
  legend = "right",
  showLegend = true,
  segments = [],
  ontologyColors = false,
  filterVariable = null,
}: {
  objectSetVariable?: string | null;
  /** p.310's Group by. */
  groupBy?: string;
  /** p.310's **Aggregation**: what sizes a slice. `count` until §227, which
   * shipped the four numeric ones per bucket on both stores. */
  aggregation?: string;
  /** The property a numeric aggregation runs over — a *second* property,
   * distinct from the one being grouped by. */
  aggregationProperty?: string;
  /** p.310's Radius, as a fraction of the outer radius. */
  inner?: number;
  legend?: string;
  showLegend?: boolean;
  /** p.310's Segment display overrides. */
  segments?: unknown;
  /** p.310's "Enable ontology colors". */
  ontologyColors?: boolean;
  /** p.310's "Selection as filter". */
  filterVariable?: string | null;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, mode } = useCanvasEnv();
  // What p.309's export draws: the chart's own SVG, found inside this.
  const pieRef = React.useRef<HTMLDivElement | null>(null);
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();
  const { set: setParameter } = useCanvasParameters();
  const filterRaw = useCanvasParameter(filterVariable);

  // `null` while p.310's Aggregation is unfinished — a `sum` with no property
  // yet — so the widget does not send a request the server refuses with a
  // sentence about property types for what is a half-filled panel.
  const ask = pieAggregationRequest(aggregation, aggregationProperty);
  const grouped = useQuery({
    queryKey: ["object-set-group", JSON.stringify(setDefinition ?? null), groupBy,
               ask?.aggregation ?? null, ask?.aggregation_property ?? null],
    queryFn: () => objApi.groupObjectSet(workspaceId, setDefinition, groupBy, ask ?? {}),
    enabled: !!setDefinition && !!groupBy && !!ask && !variablesPending,
  });
  const typeId = (setDefinition as { object_type_id?: string } | undefined)?.object_type_id
    ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    // Only for p.310's ontology colours: the rules live on the property, and
    // asking for the type when nobody wants them is a round trip for nothing.
    enabled: !!typeId && ontologyColors === true,
  });

  const chosen = segmentsOf(segments);
  const slices = visibleSlices(grouped.data?.groups ?? [], chosen);
  // p.310's "Enable ontology colors": the conditional formatting rules set for
  // *that property* in the Ontology, evaluated against a row whose only
  // property is the one being grouped — which is all a rule about it can read.
  const property = (type.data?.properties ?? []).find((p) => p.api_name === groupBy);
  const colors: Record<string, string | null> = {};
  for (const slice of slices) {
    const override = chosen.find((s) => s.value === slice.value)?.color ?? null;
    const fromOntology = ontologyColors && property
      ? conditionalStyle(property.conditional_format, { [groupBy]: slice.value })?.background
        ?? null
      : null;
    // A per-segment colour beats the ontology's: p.310 offers both, and the
    // one written on this widget is the more specific statement.
    colors[slice.label] = override ?? fromOntology;
  }

  // p.310's "Selection as filter", as the clauses every other narrowing widget
  // writes — so a pie, a table and a filter list compose instead of competing.
  let selected: string | null = null;
  for (const clause of Array.isArray(filterRaw) ? filterRaw : []) {
    const c = clause as { property?: string; op?: string; value?: unknown };
    if (c.property === groupBy && c.op === "eq") selected = String(c.value ?? "");
  }

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectSetVariable || !groupBy ? (
        <p className="canvas-widget-empty">
          Pie chart - bind an object set and a property in Settings
        </p>
      ) : grouped.isPending ? (
        <p className="canvas-widget-empty">Counting…</p>
      ) : grouped.isError ? (
        <p className="canvas-widget-empty" data-testid="pie-error">
          {/* The server's sentence when it has one - a property that is not
              Selectable (§727) is refused by name, and "couldn't" would hide
              the one thing somebody can fix. */}
          {grouped.error instanceof ApiError ? grouped.error.message : "Couldn't group this object set."}
        </p>
      ) : (
        <div data-testid="pie-chart" ref={pieRef} className="chart-exportable">
          {/* p.309: "Export and copy to clipboard options appear on hover of
              the widget", in View mode. */}
          {mode === "run" && (
            <ChartExport target={pieRef} title={groupBy ? `${aggregation} by ${groupBy}` : "pie chart"} />
          )}
          <PieChart
            // **`size`, not `count`** — what p.310's Aggregation made the two
            // different numbers. `PieChart` takes a series of values and knows
            // nothing about aggregations, so this is the one line where a pie
            // sized by a sum becomes a pie sized by how many objects are in
            // each slice, and every assertion downstream still passes.
            points={slices.map((s) => ({ label: s.label, value: s.size }))}
            // Passed only where it is a *second* number: a count pie's slices
            // have one, and a title repeating it would say "3 (75.0%) — 3
            // objects".
            counts={Object.fromEntries(slices.map((s) => [s.label, s.count]))}
            inner={innerRadiusOf(inner)}
            legend={legendPositionOf(legend)}
            showLegend={showLegendOf(showLegend)}
            colors={colors}
            drill={filterVariable
              ? {
                selected,
                onSelect: (label: string) => {
                  const slice = slices.find((s) => s.label === label);
                  const value = slice ? slice.value : label;
                  setParameter(filterVariable, selected === value
                    ? []
                    : [{ property: groupBy, op: "eq", value }]);
                },
              }
              : undefined}
          />
          {grouped.data?.truncated && (
            // Said rather than hidden: a pie missing slices is not a smaller
            // pie, it is the wrong proportions — §214's rule about a search
            // over part of a set, where the cost of silence is higher.
            <p className="canvas-widget-empty" data-testid="pie-truncated">
              Showing {slices.length} of {grouped.data.distinct_total} values
            </p>
          )}
        </div>
      )}
    </div>
  );
}

CanvasPieChart.craft = {
  displayName: "Pie chart",
  props: {
    objectSetVariable: null, groupBy: "", aggregation: "count",
    aggregationProperty: "", inner: 0, legend: "right",
    showLegend: true, segments: [], ontologyColors: false, filterVariable: null,
  },
  related: { settings: settingsPanel("PieChartSettings") },
};

// ---- Stepper (p.312-313) ----------------------------------------------------
/** p.312-313's Stepper: "navigate the user through a multi-step workflow,
 * displaying and tracking progress as they walk through a sequence of steps".
 *
 * The rules are `stepper.ts`. What is here is the wiring: each step's
 * completion is read from **a boolean variable the module owns**, so this
 * widget stores no progress of its own and cannot disagree with the module
 * about how far somebody has got.
 *
 * **The first widget whose bindings are not top-level props**, which is the
 * larger part of this unit: a step's completion variable lives inside the
 * `steps` array, where `REFERENCE_PROPS` cannot see it. Left that way the
 * variable would report zero usages and be deletable out from under the
 * stepper - §185 and §190's failure by a route their guards cannot reach - so
 * `NESTED_REFERENCE_PROPS` is what usage scanning, dangling-reference
 * refusal, the lineage graph, paste remapping and page bindings all now walk.
 *
 * p.313's **Icon** is a name from decision 0019's icon set or typed
 * characters (§707), drawn in the icon template's marks, with the name as the
 * mark's accessible label. Until §707 there was no set, and the mark carried
 * only the label.
 */
export function CanvasStepper({
  steps = [],
  stepperType = "linear",
  template = "text",
  showStepNumber = false,
  completedColour = "",
  activeColour = "",
}: {
  /** p.313's Steps. */
  steps?: unknown;
  /** p.312's Type. */
  stepperType?: string;
  /** p.313's Template. */
  template?: string;
  /** p.313's Show step number. */
  showStepNumber?: boolean;
  /** p.313's Completed color. */
  completedColour?: string;
  /** p.313's Active color. */
  activeColour?: string;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const saved = useSavedColours();
  const { events: moduleEvents, resolved } = useCanvasVariables();
  const eventContext = useEventContext(undefined, useOverlayIds());

  const drawn = stepsOf(steps);
  // p.313: completion is "a boolean variable … to determine when a step has
  // been completed", so it is read every render rather than held here.
  //
  // **`resolved`, not the parameter store.** The store holds what a *viewer*
  // has set; `resolved` is the whole variable graph, so a completion variable
  // with a default is true from the first render and a **derived** one - "is
  // this approved?", the natural way to write a real workflow's step - can be
  // read at all. Reading the store made both of those permanently incomplete,
  // which every colour and state assertion in `test_stepper.py` caught at once.
  const completed = drawn.map((step) =>
    isCompleted(step.completedVariable ? resolved[step.completedVariable] : undefined));
  const active = activeIndex(completed);
  const numbered = showsStepNumber({ template, type: stepperType, show: showStepNumber });
  const useIcons = stepperTemplateOf(template) === "icons";

  const clicked = eventsFor(moduleEvents, nodeId, "click");

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {drawn.length === 0 ? (
        <p className="canvas-widget-empty">Stepper - add steps in Settings</p>
      ) : (
        <ol className="canvas-stepper" data-testid="stepper">
          {drawn.map((step, index) => {
            const state = stateOf(index, completed, active);
            const reachable = isReachable({ index, completed, type: stepperType });
            const colour = state === "completed"
              ? completedColourOf(completedColour, saved)
              : state === "active" ? activeColourOf(activeColour, saved) : undefined;
            return (
              <li
                className="canvas-step"
                key={`${index}:${step.label}`}
                data-testid="step"
                data-state={state}
                data-reachable={reachable ? "yes" : "no"}
              >
                <button
                  type="button"
                  className="canvas-step-button"
                  data-testid={`step-${index}`}
                  // p.312's Linear: a step whose predecessors are unfinished is
                  // *shown* - a workflow with invisible later stages tells a
                  // viewer nothing about how much is left - and is not
                  // clickable, which is what "required to complete in order"
                  // constrains.
                  disabled={!reachable || mode !== "run"}
                  aria-current={state === "active" ? "step" : undefined}
                  onClick={() => {
                    if (clicked.length > 0) {
                      runEvents(clicked, {
                        ...eventContext,
                        payload: { step: String(index + 1), label: step.label },
                      });
                    }
                  }}
                >
                  <span
                    className={`canvas-step-mark${
                      useIcons && numbered && step.icon ? " canvas-step-mark--both" : ""}`}
                    data-testid="step-mark"
                    style={colour ? { background: colour, borderColor: colour } : undefined}
                    // p.313's Icon (§707), its name also the accessible label.
                    aria-label={useIcons ? (step.icon || "step") : undefined}
                  >
                    {useIcons && step.icon && <IconOrGlyph value={step.icon} size={12} />}
                    {!useIcons || numbered ? index + 1 : null}
                  </span>
                  <span className="canvas-step-label">{step.label}</span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

CanvasStepper.craft = {
  displayName: "Stepper",
  props: {
    steps: [], stepperType: "linear", template: "text", showStepNumber: false,
    completedColour: "", activeColour: "",
  },
  related: { settings: settingsPanel("StepperSettings") },
};

// ---- Timeline (p.347-349) ---------------------------------------------------
/** p.347-349's Timeline: "visualize temporal data, rendering objects as events
 * in a chronologically ordered timeline".
 *
 * The rules are `timeline.ts`. What is here is the wiring, and two parts of it
 * are worth naming.
 *
 * **One query for every layer, not one per layer.** A layer is an entry in an
 * array, so a hook per layer is not a thing React allows - and the alternative
 * of a fixed number of hooks would cap p.348's "multiple timeline layers" at
 * whatever number somebody guessed. `Promise.all` inside one query is the shape
 * that has no cap.
 *
 * **The server orders each layer and this merges them.** p.348's date property
 * is "visualizing *and ordering*", which is the sort decision 0006 refused
 * until §221 - so each layer is fetched already ordered, and `eventsOf` does
 * the interleave that no single query can.
 *
 * **Not built, and named rather than approximated**:
 *
 * - p.348's **Load data from scenario**. This platform has no scenarios - there
 *   is nothing to point the setting at, and a control that listed nothing would
 *   be worse than its absence.
 * - p.349's per-layer **Override selection event**. An event trigger is
 *   `{node, on}`, so a per-layer override needs a trigger addressed at
 *   something finer than a node. That is a change to the event system rather
 *   than to this widget, and inventing `select:0` here would make one widget's
 *   private vocabulary out of something four other widgets share.
 * - p.349's **Icon override** draws its icon in the mark (§707): the object
 *   type's own by default, the layer's chosen one when Custom, none when None.
 */
export function CanvasTimeline({
  layers = [],
  orientation = "vertical",
  order = "newest_first",
  showLegend = true,
  showGaps = false,
  activeVariable = null,
  highlightSelection = true,
  pageSize = 50,
}: {
  /** p.348's timeline layers. */
  layers?: unknown;
  /** p.349's Timeline orientation. */
  orientation?: string;
  /** p.349's Timeline events order. */
  order?: string;
  /** p.349's Show legend. */
  showLegend?: boolean;
  /** p.349's Show time between events in tooltip on hover. */
  showGaps?: boolean;
  /** p.349's Active object. */
  activeVariable?: string | null;
  /** p.349's Enable highlight of event on selection. */
  highlightSelection?: boolean;
  pageSize?: number;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, mode } = useCanvasEnv();
  const { resolved, events: moduleEvents } = useCanvasVariables();
  const { values, set } = useCanvasParameters();
  const eventContext = useEventContext(undefined, useOverlayIds());

  const drawn = useMemo(() => timelineLayersOf(layers), [layers]);
  const [hidden, setHidden] = useState<ReadonlySet<number>>(() => new Set<number>());

  // Each layer's set definition and the sort its date property asks for. Kept
  // together so the query key is exactly what the request depends on.
  const asked = useMemo(
    () => drawn.map((layer) => ({
      definition: resolved[layer.objectSetVariable],
      sort: sortFor(order, layer.dateProperty),
    })),
    [drawn, resolved, order],
  );

  const page = useQuery({
    queryKey: ["canvas-timeline", workspaceId, JSON.stringify(asked), pageSize],
    // Each layer's page **and its object type**, because p.348's prominent
    // properties are the ontology's answer rather than this widget's - so the
    // declaration has to be in hand before an event can say what it shows.
    queryFn: () => Promise.all(asked.map(async (ask) => {
      if (!ask.definition || !ask.sort) {
        return {
          instances: [],
          properties: [] as { api_name: string; visibility?: string; id?: string }[],
          titleProperty: null as string | null,
          typeIcon: null as string | null,
          typeColour: null as string | null,
        };
      }
      const typeId = (ask.definition as { object_type_id?: string }).object_type_id;
      const [rows, type] = await Promise.all([
        objApi.evaluateObjectSet(workspaceId, ask.definition, {
          limit: pageSize, sort: ask.sort,
        }),
        typeId ? objApi.getType(workspaceId, typeId) : Promise.resolve(null),
      ]);
      const declared = type?.properties ?? [];
      return {
        instances: rows.instances ?? [],
        // The layer's type, which its selection names (§692).
        typeId: typeId ?? null,
        properties: declared,
        // p.348's **Object title** is the ontology's title property, not the
        // primary key. An object set page carries neither, so the type is what
        // says which property to read - and without this every event would be
        // labelled with its key, which is a title only a database has.
        titleProperty:
          declared.find((p) => p.id === type?.title_property_id)?.api_name ?? null,
        // p.348-349's Default colour and icon are "set in the ontology for
        // the object" (§707, §713): the type's own.
        typeIcon: type?.icon ?? null,
        typeColour: type?.colour ?? null,
      };
    })),
    enabled: drawn.length > 0 && asked.some((a) => !!a.definition && !!a.sort),
    placeholderData: (previous) => previous,
  });

  const rows = useMemo(
    () => (page.data ?? []).map((answer) => answer.instances.map((row) => {
      const properties = (row.properties ?? {}) as Record<string, unknown>;
      const named = answer.titleProperty ? properties[answer.titleProperty] : undefined;
      return {
        key: String(row.primary_key),
        title: named === null || named === undefined ? undefined : String(named),
        primaryKey: String(row.primary_key),
        properties,
      };
    })),
    [page.data],
  );
  const declaredByLayer = useMemo(
    () => (page.data ?? []).map((answer) => answer.properties),
    [page.data],
  );

  const events = useMemo(
    () => visibleEvents(timelineEventsOf(drawn, rows, order), hidden),
    [drawn, rows, order, hidden],
  );

  // p.349's Active object is "an object set of the currently selected
  // object", and layers are "across multiple object types" (p.348): a key
  // alone could be two layers' objects, so the selection names its type
  // (§692), and an event is chosen when both match.
  const activeRaw = activeVariable ? values[activeVariable] : undefined;
  const chosen = keysOf(activeRaw)[0] ?? null;
  const chosenType = selectedType(activeRaw);
  const typeOfLayer = (layer: number) => page.data?.[layer]?.typeId ?? null;
  const isChosen = (key: string, layer: number) => chosen === key
    && (chosenType === null || chosenType === typeOfLayer(layer));

  const pick = (key: string, layer: number) => {
    if (mode !== "run") return;
    if (activeVariable) {
      set(activeVariable, typedSelection(selectionClauses([key]), typeOfLayer(layer)));
    }
    // p.349's Override selection event (§616): a layer with its own events
    // fires those *instead of* the widget's, which is the page's "override".
    // The active object is set either way - it is an output, not an event.
    const own = selectionItemOf(drawn[layer]!);
    const selected = eventsFor(moduleEvents, nodeId, "row_select", own);
    if (selected.length > 0) {
      runEvents(selected, { ...eventContext, payload: { key } });
    }
  };

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {drawn.length === 0 ? (
        <p className="canvas-widget-empty">Timeline - add a layer in Settings</p>
      ) : (
        <div
          className="canvas-timeline"
          data-testid="timeline"
          data-orientation={timelineOrientationOf(orientation)}
        >
          {showLegend && (
            <ul className="canvas-timeline-legend" data-testid="timeline-legend">
              {drawn.map((layer, index) => (
                <li key={index}>
                  <button
                    type="button"
                    data-testid={`timeline-legend-${index}`}
                    data-hidden={hidden.has(index) ? "yes" : "no"}
                    // p.349: the legend is "interactive… to show or hide
                    // selected timeline layers", so it is a control in run mode
                    // and a label in the builder, where a click selects the
                    // widget instead.
                    disabled={mode !== "run"}
                    onClick={() => setHidden((was) => toggleLayer(was, index))}
                  >
                    <span
                      className="canvas-timeline-swatch"
                      style={{
                        background: layerColour(layer, index, page.data?.[index]?.typeColour)
                          ?? undefined,
                      }}
                    />
                    {timelineLabelFor(layer, index)}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {page.isPending ? (
            <p className="canvas-widget-empty">Loading events…</p>
          ) : events.length === 0 ? (
            <p className="canvas-widget-empty" data-testid="timeline-empty">
              No events to show
            </p>
          ) : (
            <ol className="canvas-timeline-track">
              {events.map((event, index) => {
                const layer = drawn[event.layer] as TimelineLayer;
                const colour = layerColour(layer, event.layer, page.data?.[event.layer]?.typeColour);
                const icon = layerIcon(layer, page.data?.[event.layer]?.typeIcon);
                const previous = events[index - 1];
                return (
                  <li
                    className="canvas-timeline-event"
                    key={`${event.layer}:${event.key}`}
                    data-testid="timeline-event"
                    data-layer={String(event.layer)}
                    data-selected={
                      highlightSelection && isChosen(event.key, event.layer) ? "yes" : "no"
                    }
                  >
                    {showGaps && previous && (
                      // p.349's tooltip, drawn as a rung between the two events
                      // it measures rather than as a hover-only string: a
                      // tooltip nobody hovers is a fact nobody reads, and the
                      // gap between two events is most of what a timeline is
                      // for.
                      <span className="canvas-timeline-gap" data-testid="timeline-gap">
                        {gapLabel(previous.at, event.at)}
                      </span>
                    )}
                    <button
                      type="button"
                      className="canvas-timeline-mark"
                      data-testid={`timeline-mark-${event.key}`}
                      style={colour ? { background: colour, borderColor: colour, color: "#fff" } : undefined}
                      aria-label={
                        showsIcon(layer) ? (layer.icon || timelineLabelFor(layer, event.layer))
                          : undefined
                      }
                      disabled={mode !== "run"}
                      onClick={() => pick(event.key, event.layer)}
                    >
                      {icon && <IconOrGlyph value={icon} size={11} />}
                    </button>
                    <div className="canvas-timeline-body">
                      <span className="canvas-timeline-when" data-testid="timeline-when">
                        {new Date(event.at).toISOString().slice(0, 10)}
                      </span>
                      <button
                        type="button"
                        className="canvas-timeline-title"
                        data-testid={`timeline-title-${event.key}`}
                        style={colour ? { color: colour } : undefined}
                        disabled={mode !== "run"}
                        onClick={() => pick(event.key, event.layer)}
                      >
                        {event.title}
                      </button>
                      <TimelineProperties
                        layer={layer}
                        declared={declaredByLayer[event.layer] ?? []}
                        properties={event.properties}
                      />
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

/** p.348's Event properties, for one event.
 *
 * `eventProperties` decides *which*; this drops the ones the object has no
 * value for, which p.348 does not mention and every other property display in
 * this codebase does - an event card listing three empty rows says less than
 * one listing none.
 */
function TimelineProperties({ layer, declared, properties }: {
  layer: TimelineLayer;
  declared: readonly { api_name: string; visibility?: string }[];
  properties: Record<string, unknown>;
}) {
  const names = eventProperties(layer, declared);
  const shown = names.filter((name) => {
    const value = properties[name];
    return value !== null && value !== undefined && String(value) !== "";
  });
  if (shown.length === 0) return null;
  return (
    <dl className="canvas-timeline-props" data-testid="timeline-props">
      {shown.map((name) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{String(properties[name])}</dd>
        </div>
      ))}
    </dl>
  );
}

CanvasTimeline.craft = {
  displayName: "Timeline",
  props: {
    layers: [], orientation: "vertical", order: "newest_first",
    showLegend: true, showGaps: false, activeVariable: null,
    highlightSelection: true, pageSize: 50,
  },
  related: { settings: settingsPanel("TimelineSettings") },
};

// ---- Media Preview (p.363-364) ----------------------------------------------
/** p.363-364's Media Preview: "display image, audio, video, and document media,
 * given a supported media source".
 *
 * The rules are `media.ts`, and the one worth naming here is that **what a
 * media string may be is a security rule**: an app author types it and every
 * viewer's browser follows it, so `resolveMedia` refuses `javascript:` and a
 * `data:` URL for anything this platform does not already render inline. This
 * component never sees a URL that rule rejected.
 *
 * **p.363's attachment source is a `single_object` variable**, which is this
 * platform's spelling of "an object set with a single object": the viewer picks
 * one, the variable holds its properties, and the named `attachment` property
 * is the file. No fetch of its own — the object is already resolved.
 *
 * **Not built, and named rather than approximated**:
 *
 * - p.363's **Blobster RID** and **media-set URL** formats. Both are Foundry
 *   resource identifiers with a Foundry service behind them; there is nothing
 *   here to resolve them against, and accepting the string would draw a broken
 *   image rather than say so.
 * - p.363's **media reference property**, for the same reason: it is a media
 *   set by another name.
 * - p.363's "document media" reaches a viewer as a **link**. A PDF can run
 *   script, and serving one inline from the app's own origin is the stored-XSS
 *   shape `download_attachment` exists to describe — so the allowlist excludes
 *   it on both sides, and widening it is the PDF Viewer's decision to make
 *   deliberately rather than this widget's to make in passing.
 */
export function CanvasMediaPreview({
  source = "string",
  url = "",
  textVariable = null,
  subjectVariable = null,
  property = "",
  label = "",
  maxHeight = 320,
}: {
  /** p.363's media source. */
  source?: string;
  /** p.363's Media string, written by the author. */
  url?: string;
  /** …or read from a string variable, the shape §209's Markdown already takes. */
  textVariable?: string | null;
  /** p.363's "object set with a single object". */
  subjectVariable?: string | null;
  /** p.363's attachment typed property. */
  property?: string;
  label?: string;
  maxHeight?: number;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const { resolved } = useCanvasVariables();

  const subject = subjectVariable
    ? (resolved[subjectVariable] as { properties?: Record<string, unknown> } | undefined)
    : undefined;
  const fromVariable = textVariable ? resolved[textVariable] : undefined;

  // An attachment is fetched rather than pointed at (`useAttachmentUrl` says
  // why). A *media string* needs none of this: it points at somewhere else, or
  // carries its own bytes.
  const wanted = attachmentOf((subject?.properties ?? {})[property]);
  const key = mediaSourceOf(source) === "attachment" ? wanted?.key : undefined;
  const objectUrl = useAttachmentUrl(workspaceId, key, wanted?.contentType ?? "");

  const media = resolveMedia({
    source,
    // The variable wins when one is bound, the same precedence §209's Markdown
    // uses: an author who has bound a variable has said the text is not theirs
    // to write, and reading the literal instead would show a value nothing on
    // screen can change.
    url: textVariable ? fromVariable : url,
    attachment: (subject?.properties ?? {})[property],
    label,
    // The blob's own URL, once it has arrived. `""` while it is in flight,
    // which `resolveMedia` reads as nothing to draw yet rather than as an
    // error - the difference a viewer sees between "loading" and "broken".
    attachmentHref: () => objectUrl ?? "",
  });

  const style = { maxHeight: `${Math.max(80, Math.min(Number(maxHeight) || 320, 1200))}px` };

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      <figure className="canvas-media" data-testid="media" data-kind={media.kind}>
        {media.problem ? (
          <p className="canvas-widget-empty" data-testid="media-problem">{media.problem}</p>
        ) : !media.url ? (
          <p className="canvas-widget-empty" data-testid="media-loading">Loading…</p>
        ) : media.kind === "image" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={media.url ?? ""}
            alt={media.label}
            style={style}
            data-testid="media-image"
          />
        ) : media.kind === "video" ? (
          <video src={media.url ?? ""} controls style={style} data-testid="media-video">
            <track kind="captions" />
          </video>
        ) : media.kind === "audio" ? (
          <audio src={media.url ?? ""} controls data-testid="media-audio" />
        ) : (
          // **A link, which is the one answer that is never wrong.** An `<img>`
          // pointed at a PDF is a broken image and an `<audio>` pointed at one
          // is a player that will never play; a link says what it is and lets
          // the browser decide.
          <a
            className="canvas-media-link"
            href={media.url ?? "#"}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="media-link"
          >
            {media.label}
            {sizeLabel(media.size) && (
              <span className="canvas-media-size"> ({sizeLabel(media.size)})</span>
            )}
          </a>
        )}
        {label && !media.problem && (
          <figcaption className="canvas-media-caption" data-testid="media-caption">
            {label}
          </figcaption>
        )}
      </figure>
    </div>
  );
}

CanvasMediaPreview.craft = {
  displayName: "Media preview",
  props: {
    source: "string", url: "", textVariable: null, subjectVariable: null,
    property: "", label: "", maxHeight: 320,
  },
  related: { settings: settingsPanel("MediaPreviewSettings") },
};

// ---- Iframe (p.545-547) -----------------------------------------------------
/** p.545's Iframe widget: "embedding of external, full-page applications
 * within Workshop, providing builders with a way to add custom views to their
 * modules" (§455).
 *
 * p.546's URL, "as a static string or a string variable", with the variable
 * winning when one is bound — the precedence §209's Markdown and the Media
 * Preview already use, for their reason: an author who bound a variable has
 * said the URL is not theirs to write.
 *
 * **The refusals are `frame.ts`'s**, and a refused URL says *why* rather than
 * drawing an empty box (§214): a frame showing nothing looks exactly like a
 * page that failed to load, and the two have different fixes.
 *
 * **Sandboxed**, with the four permissions a full-page application actually
 * needs and none of the top-level ones: a framed page may not navigate this
 * module away from under the viewer. `no-referrer`, because the module's URL
 * names the workspace and the app, and neither is the framed site's business.
 *
 * **Inert in the builder.** An iframe captures every click on it, so a builder
 * could not select the widget they had just dropped; `pointer-events: none`
 * in edit mode is what makes the frame a widget rather than a hole in the
 * canvas.
 *
 * Not built, and named rather than approximated: p.548-552's **Slate** source,
 * which embeds an application this platform does not have; and p.552-553's
 * **Bidirectional** mode, which is a contract with an npm package
 * (`@osdk/workshop-iframe-custom-widget`) the framed application has to
 * install — a protocol to design, not a widget setting.
 */
export function CanvasIframe({
  url = "",
  textVariable = null,
  title = "",
  height = 480,
  frameMode = "url",
  frameDefinition = null,
  frameBindings = {},
}: {
  /** p.546's URL, as a static string. */
  url?: string;
  /** …or as a string variable. */
  textVariable?: string | null;
  /** The frame's accessible name. */
  title?: string;
  height?: number;
  /** p.552's Bidirectional option (§756; decision 0023): the framed
   * application reads and writes variables and fires events. */
  frameMode?: "url" | "bidirectional";
  /** The fields and events the application last asked for, saved so the
   * bindings mean something before it answers again (decision 0023 §4). */
  frameDefinition?: unknown;
  /** Field id -> the variable it is bound to. */
  frameBindings?: Record<string, string>;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
    actions: { setProp },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { resolved, declared, pending, events: moduleEvents } = useCanvasVariables();
  const { set } = useCanvasParameters();
  const raw = textVariable ? resolved[textVariable] : url;
  const target = safeFrameUrl(raw);
  const refusal = frameRefusal(raw);
  const px = Math.max(120, Math.min(Number(height) || 480, 2000));

  // p.552-553's Bidirectional mode: one listener and one sender, each
  // checking that the other end is this frame's window at its URL's origin
  // (decision 0023 §2).
  const bidirectional = frameMode === "bidirectional";
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const origin = bidirectional && typeof window !== "undefined"
    ? frameOrigin(target, window.location.href) : null;
  const definition = savedDefinition(frameDefinition);
  const bindings = frameBindings && typeof frameBindings === "object" ? frameBindings : {};
  const overlayIds = useOverlayIds();
  const eventContext = useEventContext(undefined, overlayIds);
  const sent = frameValuesOf(definition, bindings, resolved, pending);
  const sentKey = JSON.stringify(sent);
  // The listener reads the latest of these through a ref, so it is attached
  // once per frame rather than once per render.
  const live = useRef({ definition, bindings, declared, moduleEvents, eventContext, mode, sent });
  live.current = { definition, bindings, declared, moduleEvents, eventContext, mode, sent };

  function post(body: Record<string, unknown>) {
    const win = frameRef.current?.contentWindow;
    if (!win || !origin) return;
    // Until its URL loads, a frame is `about:blank` on this page's origin. A
    // window whose origin can be read and is not the frame's is that one, and
    // a message to it would be refused; one that cannot be read is the
    // framed page on another origin, which is who it is for.
    let current: string | null = null;
    try {
      current = win.location.origin;
    } catch {
      current = null;
    }
    if (current !== null && current !== origin) return;
    win.postMessage({ version: FRAME_VERSION, ...body }, origin);
  }

  useEffect(() => {
    if (!bidirectional || !origin) return;
    function onMessage(e: MessageEvent) {
      if (e.source !== frameRef.current?.contentWindow || e.origin !== origin) return;
      const message = readMessage(e.data);
      if (!message) return;
      const now = live.current;
      if (message.type === "definition") {
        // p.553: the panel learns what to offer from this. Saved in the
        // builder only - a viewer's frame cannot rewrite the module.
        if (now.mode === "edit" && !sameDefinition(message.definition, now.definition)) {
          setProp((p: { frameDefinition: unknown }) => (p.frameDefinition = message.definition));
        }
        // And what it is bound to, at once, so it does not wait for a change.
        post({ type: FRAME_MESSAGE.values, values: now.sent });
        return;
      }
      if (now.mode !== "run") return;
      if (message.type === "set-value") {
        const verdict = acceptWrite(
          now.definition, now.bindings, now.declared, message.fieldId, message.value);
        if (!verdict.ok) {
          console.warn(`Iframe: ignored a write - ${verdict.reason}`);
          return;
        }
        set(verdict.variable, verdict.value);
        return;
      }
      if (!knownEvent(now.definition, message.eventId)) {
        console.warn(`Iframe: ignored an event the module did not ask for - "${message.eventId}"`);
        return;
      }
      const wired = eventsFor(now.moduleEvents, nodeId, "click", message.eventId);
      if (wired.length > 0) {
        runEvents(wired, { ...now.eventContext, payload: { event: message.eventId } });
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [bidirectional, origin, nodeId, set, setProp]);

  // Asked again when the builder opens for editing: a frame that loaded
  // before then sent its definition to a viewer, which saves nothing.
  useEffect(() => {
    if (bidirectional && mode === "edit") post({ type: FRAME_MESSAGE.requestDefinition });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bidirectional, origin, mode]);

  // p.553: "sent to the custom application each time the value or loading
  // state of the variable changes".
  useEffect(() => {
    if (!bidirectional) return;
    post({ type: FRAME_MESSAGE.values, values: live.current.sent });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bidirectional, origin, sentKey]);

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {refusal ? (
        <p className="canvas-widget-empty" data-testid="iframe-refused">{refusal}</p>
      ) : !target ? (
        <p className="canvas-widget-empty" data-testid="iframe-empty">
          {textVariable ? "The variable holds no URL yet" : "No URL set"}
        </p>
      ) : (
        <iframe
          ref={frameRef}
          src={target}
          title={frameTitle(title, target)}
          data-testid="iframe"
          onLoad={() => {
            // Asked once the frame is up, so a definition sent before this
            // listened is sent again (decision 0023 §1).
            if (bidirectional) post({ type: FRAME_MESSAGE.requestDefinition });
          }}
          className="canvas-iframe"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          referrerPolicy="no-referrer"
          loading="lazy"
          style={{
            height: `${px}px`,
            pointerEvents: mode === "edit" ? "none" : undefined,
          }}
        />
      )}
    </div>
  );
}

CanvasIframe.craft = {
  displayName: "Iframe",
  props: {
    url: "", textVariable: null, title: "", height: 480,
    frameMode: "url", frameDefinition: null, frameBindings: {},
  },
  related: { settings: settingsPanel("IframeSettings") },
};

// ---- Object dropdown (p.455-458) --------------------------------------------
/** The list a dropdown or a selector picks from (§688, §690): the set's page
 * in the order p.458's sort asks for, and how to draw each row.
 *
 * Over a union of sets (§686) the page is every type's objects in one order,
 * each row naming its type and drawn by that type's title and properties;
 * p.458's "only shared properties can be sorted on" makes the union's common
 * properties the ones it sorts and searches by.
 *
 * **Not read until the types are**, because the sort is theirs to decide: a
 * page asked for sooner comes back in another order, and p.457's
 * auto-selection takes its first object and keeps it once the right order
 * arrives. The set reads as resolving until then. */
function usePickerList(
  workspaceId: string, setDefinition: unknown, sortProperty: string, variablesPending: boolean,
) {
  const { union, loaded, properties: offered } = useSetProperties(workspaceId, setDefinition);
  const types = loaded.flatMap((t) => (t ? [t] : []));
  const ready = loaded.length > 0 && loaded.every((t) => !!t);
  const declared = union ? union.common : offered;
  const typeOf = (row: ObjectInstance) =>
    union ? types.find((t) => t.id === row.object_type_id) : types[0];
  const titleOf = (type: ObjectTypeDetail | undefined) =>
    type?.properties.find((p) => p.id === type.title_property_id)?.api_name ?? null;
  const setPage = useSetPage(workspaceId, ready ? setDefinition : null, {
    pageSize: DROPDOWN_PAGE_LIMIT,
    sort: dropdownSortOf(sortProperty, declared),
    variablesPending,
  });
  return { union, types, declared, typeOf, titleOf, setPage };
}

/** p.455-458's Object Dropdown: "used to select a single object from a list of
 * objects".
 *
 * p.458's search rules are `object-dropdown.ts`. The **output** is the Object
 * Table's — `selectionClauses`, one key — and p.457's "Allow no selection" is
 * p.224's auto-selection with the sign flipped, so it is `autoSelectKey` with
 * `enabled: !allowNone`. Two settings on two pages of two different widgets
 * turn out to be the same question about the same variable shape, and writing
 * a second answer to it would have been a second thing to keep in step.
 *
 * p.455's "data on one or multiple object types" is §688's: over a union of
 * sets (§686) the list is every type's objects in one order, and p.458's "only
 * shared properties can be sorted on" is the union's common properties. p.455's
 * conditional and numerical formatting *configured in the Ontology Manager* is
 * drawn by `PropertyValue`.
 */
export function CanvasObjectDropdown({
  objectSetVariable = null,
  selectedVariable = null,
  label = "",
  properties = "",
  hideNull = false,
  sortProperty = "",
  searchMode = "on_screen",
  searchPropertyNames = "",
  allowNoSelection = false,
}: {
  objectSetVariable?: string | null;
  /** p.457's Selected object — the output, as selection clauses. */
  selectedVariable?: string | null;
  label?: string;
  /** p.457's "Add property": what is drawn beneath each object's title. */
  properties?: string;
  /** p.458's Hide null properties, per object. */
  hideNull?: boolean;
  /** p.458's Sort items by, as far as `object_sets` can express it. */
  sortProperty?: string;
  /** p.458's Search items by. */
  searchMode?: string;
  /** p.458's "the specified string properties". */
  searchPropertyNames?: string;
  /** p.457's Allow no selection. */
  allowNoSelection?: boolean;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();
  const { set: setParameter } = useCanvasParameters();
  const selectedRaw = useCanvasParameter(selectedVariable);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [screenRef, onScreen] = useOnScreen();

  // **The type is resolved from the set definition, not from the page**, so a
  // p.458 property sort can be checked before the first fetch rather than after
  // it. `useSetPage` reads `object_type_id` off the same definition — it never
  // needed the response for it — so this costs no request the panel and the
  // other widgets over this set are not already sharing by query key.
  //
  // p.455's "one or multiple object types" (§688): over a union the page is
  // every type's objects in one order, each row naming its type, and each is
  // drawn by its own type's title and properties. p.458: "If multiple object
  // types exist in the object set, only shared properties can be sorted on",
  // so a union sorts and searches by its common properties.
  const { union, types, declared, typeOf, titleOf, setPage } =
    usePickerList(workspaceId, setDefinition, sortProperty, variablesPending);
  const shownNames = propertyListOf(properties);
  const searchable = searchProperties({
    mode: searchMode,
    all: declared,
    // The title is on screen too, and p.458 says search runs on what is
    // displayed — a picker whose search ignored the words it is showing would
    // be the most surprising thing on the page. Every type's, over a union.
    shown: [...types.flatMap((t) => titleOf(t) ?? []), ...shownNames],
    specific: searchPropertyNames,
  });

  const rows = setPage.rows ?? [];
  const options = rows.filter((row) => matchesQuery(row.properties, query, searchable));
  const keys = keysOf(selectedRaw);
  const chosenKey = keys[0] ?? null;
  // Over a union a key is one type's, and the selection says which.
  const chosenType = union ? selectedType(selectedRaw) : null;
  const chosen = rows.find((row) => row.primary_key === chosenKey
    && (!union || row.object_type_id === chosenType));
  const selectionOf = (row: ObjectInstance | undefined) => typedSelection(
    selectionClauses(row ? [row.primary_key] : []),
    union && row ? String(row.object_type_id ?? "") : null);
  const allowNone = allowNoSelectionOf(allowNoSelection);

  // p.457's Allow no selection, off, is p.224's auto-selection: pick the first
  // object so downstream widgets have something to read. In an effect because
  // it is a *write*, and only when the widget is on screen for p.224's reason.
  const autoKey = autoSelectKey({
    rows, current: keys, enabled: !allowNone, visible: onScreen,
  });
  const stated = hasSelection(selectedRaw);
  useEffect(() => {
    if (!selectedVariable) return;
    if (autoKey) {
      setParameter(selectedVariable, selectionOf(rows[0]));
      return;
    }
    if (!stated) setParameter(selectedVariable, selectionClauses([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoKey, selectedVariable, stated]);

  const pick = (row: ObjectInstance | null) => {
    setOpen(false);
    setQuery("");
    if (selectedVariable) setParameter(selectedVariable, selectionOf(row ?? undefined));
  };

  const note = truncationNote(setPage.total, rows.length);
  const heading = dropdownLabelOf(label);

  return (
    <div
      ref={(ref) => {
        connectDragDrop(ref, connect, drag);
        screenRef(ref);
      }}
      className="canvas-block"
    >
      {!objectSetVariable ? (
        <p className="canvas-widget-empty">Object dropdown - bind an object set in Settings</p>
      ) : (
        <div className="canvas-dropdown" data-testid="object-dropdown">
          {heading && <span className="field-label" data-testid="dropdown-label">{heading}</span>}
          <button
            type="button"
            className="canvas-dropdown-toggle"
            aria-expanded={open}
            aria-haspopup="listbox"
            data-testid="dropdown-toggle"
            onClick={() => setOpen(!open)}
          >
            <span data-testid="dropdown-value">
              {setPage.unresolved
                ? "Resolving the object set…"
                : chosen
                  ? optionTitleOf(chosen.properties, titleOf(typeOf(chosen)), chosen.primary_key)
                  : "Select an object..."}
            </span>
            <span className="canvas-dropdown-caret" aria-hidden>▾</span>
          </button>
          {open && (
            <div className="canvas-dropdown-panel" role="listbox">
              <input
                type="search"
                className="canvas-dropdown-search"
                placeholder="Search…"
                value={query}
                data-testid="dropdown-search"
                onChange={(e) => setQuery(e.target.value)}
              />
              {/* p.457's Allow no selection, as a control rather than only as a
                  permission: a viewer who may have no selection needs a way
                  back to having none. */}
              {allowNone && (
                <button
                  type="button"
                  className="canvas-dropdown-option"
                  data-testid="dropdown-clear"
                  onClick={() => pick(null)}
                >
                  No selection
                </button>
              )}
              {options.length === 0 ? (
                <p className="canvas-widget-empty" data-testid="dropdown-no-matches">
                  Nothing matches
                </p>
              ) : (
                options.map((row) => (
                  <button
                    type="button"
                    key={row.id}
                    role="option"
                    aria-selected={row === chosen}
                    className="canvas-dropdown-option"
                    data-testid="dropdown-option"
                    onClick={() => pick(row)}
                  >
                    <span className="canvas-dropdown-title">
                      {optionTitleOf(row.properties, titleOf(typeOf(row)), row.primary_key)}
                    </span>
                    {union && (
                      <span className="canvas-dropdown-detail" data-testid="dropdown-type">
                        {typeOf(row)?.display_name}
                      </span>
                    )}
                    {visibleProperties({
                      all: typeOf(row)?.properties ?? [], chosen: properties,
                      values: row.properties, hideNull: hideNullOf(hideNull),
                    }).map((p) => (
                      <span className="canvas-dropdown-detail" key={p.api_name}
                            data-testid="dropdown-detail">
                        <PropertyValue
                          workspaceId={workspaceId}
                          dataType={p.data_type}
                          valueFormat={p.value_format}
                          structFields={p.struct_fields}
                          style={conditionalStyle(p.conditional_format, row.properties)}
                          value={row.properties[p.api_name]}
                        />
                      </span>
                    ))}
                  </button>
                ))
              )}
              {note && (
                <p className="canvas-widget-empty" data-testid="dropdown-truncated">{note}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

CanvasObjectDropdown.craft = {
  displayName: "Object dropdown",
  props: {
    objectSetVariable: null, selectedVariable: null, label: "", properties: "",
    hideNull: false, sortProperty: "key", searchMode: "on_screen",
    searchPropertyNames: "", allowNoSelection: false,
  },
  related: { settings: settingsPanel("ObjectDropdownSettings") },
};

// ---- Object selector (p.444) ------------------------------------------------
/** p.444's Object Selector: "Allow the user to select multiple objects from a
 * list of objects".
 *
 * **One line is its whole specification** — unlike every other filtering
 * widget it has no page of its own — so it is the Object Dropdown with a
 * different selection, and it is built that way on purpose: same model, same
 * search rules, same property lines, same clause output with several keys
 * instead of one. Inventing settings Foundry does not document for it would be
 * building our design and calling it parity.
 *
 * Three things differ, and each follows from "multiple" rather than from a
 * guess:
 *
 * * **No auto-selection.** p.457's Allow no selection exists because a single
 *   dropdown with nothing chosen leaves downstream widgets with nothing; a
 *   multiple selection's honest resting state is none, and pre-ticking one row
 *   of many would be a filter nobody applied.
 * * **The list stays open while ticking**, since the whole point is choosing
 *   several and a panel that closed on each click would make that four clicks
 *   instead of one.
 * * **The empty selection is still *stated*** — `in []` on load — for §207's
 *   reason: a variable nothing has written means "no narrowing", so every
 *   downstream widget would receive the whole set rather than none of it.
 *
 * Over a union of sets it lists every type as the dropdown does (§690), and
 * a selection of several types' objects is §689's `[type, key]` pairs.
 */
export function CanvasObjectSelector({
  objectSetVariable = null,
  selectedVariable = null,
  label = "",
  properties = "",
  hideNull = false,
  sortProperty = "key",
  searchMode = "on_screen",
  searchPropertyNames = "",
}: {
  objectSetVariable?: string | null;
  /** p.444's output: the selected objects, as selection clauses. */
  selectedVariable?: string | null;
  label?: string;
  properties?: string;
  hideNull?: boolean;
  sortProperty?: string;
  searchMode?: string;
  searchPropertyNames?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();
  const { set: setParameter } = useCanvasParameters();
  const selectedRaw = useCanvasParameter(selectedVariable);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  // The Object Dropdown's list (§688), over a union too (§690).
  const { union, types, declared, typeOf, titleOf, setPage } =
    usePickerList(workspaceId, setDefinition, sortProperty, variablesPending);
  const searchable = searchProperties({
    mode: searchMode,
    all: declared,
    shown: [...types.flatMap((t) => titleOf(t) ?? []), ...propertyListOf(properties)],
    specific: searchPropertyNames,
  });

  const rows = setPage.rows ?? [];
  const options = rows.filter((row) => matchesQuery(row.properties, query, searchable));
  // Over a union each object with its type, since a key alone could be two
  // (§689's pairs); over one set, the keys.
  const picked = pickedIn(selectedRaw, !!union, null);
  const stated = hasSelection(selectedRaw);

  // §207's rule: state the empty selection rather than leaving the variable
  // alone, or `narrow_set` hands downstream the whole set instead of none.
  useEffect(() => {
    if (!selectedVariable || stated) return;
    setParameter(selectedVariable, selectionClauses([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedVariable, stated]);

  const toggleRow = (row: ObjectInstance) => {
    if (!selectedVariable) return;
    const next = isPicked(picked, row)
      ? picked.filter((p) => !isPicked([p], row))
      : [...picked, pickOf(row, !!union)];
    setParameter(selectedVariable, pickedClauses(next, !!union, null));
  };

  const onlyRow = picked.length === 1
    ? rows.find((row) => isPicked(picked, row))
    : undefined;
  const summary = selectionSummary(
    picked.length,
    onlyRow ? optionTitleOf(onlyRow.properties, titleOf(typeOf(onlyRow)), onlyRow.primary_key)
      : null,
  );
  const note = truncationNote(setPage.total, rows.length);
  const heading = dropdownLabelOf(label);

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectSetVariable ? (
        <p className="canvas-widget-empty">Object selector - bind an object set in Settings</p>
      ) : (
        <div className="canvas-dropdown" data-testid="object-selector">
          {heading && <span className="field-label" data-testid="selector-label">{heading}</span>}
          <button
            type="button"
            className="canvas-dropdown-toggle"
            aria-expanded={open}
            data-testid="selector-toggle"
            onClick={() => setOpen(!open)}
          >
            <span data-testid="selector-value">
              {setPage.unresolved ? "Resolving the object set…" : summary}
            </span>
            <span className="canvas-dropdown-caret" aria-hidden>▾</span>
          </button>
          {open && (
            <div className="canvas-dropdown-panel">
              <input
                type="search"
                className="canvas-dropdown-search"
                placeholder="Search…"
                value={query}
                data-testid="selector-search"
                onChange={(e) => setQuery(e.target.value)}
              />
              {picked.length > 0 && (
                <button
                  type="button"
                  className="canvas-dropdown-option"
                  data-testid="selector-clear"
                  onClick={() => {
                    if (selectedVariable) {
                      setParameter(selectedVariable, selectionClauses([]));
                    }
                  }}
                >
                  Clear selection
                </button>
              )}
              {options.length === 0 ? (
                <p className="canvas-widget-empty" data-testid="selector-no-matches">
                  Nothing matches
                </p>
              ) : (
                options.map((row) => (
                  <label
                    className="canvas-dropdown-option canvas-object-tick"
                    key={row.id}
                    data-testid="selector-option"
                  >
                    <input
                      type="checkbox"
                      checked={isPicked(picked, row)}
                      data-testid={`selector-tick-${row.primary_key}`}
                      onChange={() => toggleRow(row)}
                    />
                    <span>
                      <span className="canvas-dropdown-title">
                        {optionTitleOf(row.properties, titleOf(typeOf(row)), row.primary_key)}
                      </span>
                      {union && (
                        <span className="canvas-dropdown-detail" data-testid="selector-type">
                          {typeOf(row)?.display_name}
                        </span>
                      )}
                      {visibleProperties({
                        all: typeOf(row)?.properties ?? [], chosen: properties,
                        values: row.properties, hideNull: hideNullOf(hideNull),
                      }).map((p) => (
                        <span className="canvas-dropdown-detail" key={p.api_name}
                              data-testid="selector-detail">
                          <PropertyValue
                            workspaceId={workspaceId}
                            dataType={p.data_type}
                            valueFormat={p.value_format}
                            structFields={p.struct_fields}
                            style={conditionalStyle(p.conditional_format, row.properties)}
                            value={row.properties[p.api_name]}
                          />
                        </span>
                      ))}
                    </span>
                  </label>
                ))
              )}
              {note && (
                <p className="canvas-widget-empty" data-testid="selector-truncated">{note}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

CanvasObjectSelector.craft = {
  displayName: "Object selector",
  props: {
    objectSetVariable: null, selectedVariable: null, label: "", properties: "",
    hideNull: false, sortProperty: "key", searchMode: "on_screen",
    searchPropertyNames: "",
  },
  related: { settings: settingsPanel("ObjectSelectorSettings") },
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

CanvasSearch.craft = {
  displayName: "Search",
  props: { objectSetVariable: null, variable: null, property: null, label: "Search" },
  related: { settings: settingsPanel("SearchSettings") },
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
export const CARD_FIELD_CAP = 6;

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
  // The type first, so p.595's unsupported properties are left out of the
  // page and loaded on demand (§693).
  const typeId = (definition as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const heavy = omittedOf(type.data?.properties ?? []);
  const page = useSetPage(
    workspaceId, objectSetVariable && (!typeId || type.data) ? definition : null,
    { pageSize, sort, variablesPending, omit: heavy },
  );
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
                          {isUnsupported(p) ? (
                            // p.596: "select Load to reveal its value".
                            <LoadOnDemand
                              workspaceId={workspaceId}
                              typeId={page.typeId}
                              instanceId={instance.id}
                              property={p}
                              label="Load"
                            />
                          ) : (
                            <PropertyValue
                              workspaceId={workspaceId}
                              dataType={p.data_type}
                              valueFormat={p.value_format}
                              structFields={p.struct_fields}
                              style={conditionalStyle(p.conditional_format, instance.properties)}
                              value={instance.properties[p.api_name]}
                              compact
                            />
                          )}
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

CanvasObjectCards.craft = {
  displayName: "Card list",
  props: { objectSetVariable: null, fields: "", pageSize: 12, sort: "recent" },
  related: { settings: settingsPanel("ObjectCardsSettings") },
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
 * **Counts only, and this is now a gap rather than a refusal.** The paragraph
 * here used to say a cross-tab of sums "would mean one thing on Postgres and
 * nothing at all on OpenSearch" — decision 0006's reason, correct until §226
 * built numeric aggregations on both stores. Nothing blocks a summed pivot; it
 * is a *second* aggregation argument on `/object-sets/cross-tab` and the
 * margins have to agree with the cells, which is real work nobody has done.
 * Recorded on the parity row as ○ rather than fixed in passing.
 *
 * Clicking a cell narrows, by the same mechanism the chart's drill-down uses:
 * it writes equality *clauses* into a variable a `narrow_set` derivation
 * reads. Two clauses rather than one is the only difference — a cell is the
 * intersection of a row and a column, which is exactly what it looks like.
 */
export function CanvasPivotTable(props: Parameters<typeof ObjectSetPivotTable>[0] & {
  /** p.335's function-backed pivot (§774): the function, its version and
   * inputs. Null reads the object set. */
  fn?: unknown;
  fnRows?: string;
  /** p.340's expandable rows, outermost first (§782). */
  fnExpand?: string;
  fnColumn?: string;
  fnValues?: string;
}) {
  const { connectors: { connect, drag } } = useNode();
  const fn = functionLayerOf(props.fn);
  if (!fn) return <ObjectSetPivotTable {...props} />;
  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      <FunctionPivotView
        fn={fn}
        fields={pivotFieldsOf(props.fnRows ?? "", props.fnColumn ?? "", props.fnValues ?? "",
                              props.fnExpand ?? "")}
        title={props.title ?? ""}
      />
    </div>
  );
}

function ObjectSetPivotTable({
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

CanvasPivotTable.craft = {
  displayName: "Pivot table",
  props: {
    objectSetVariable: null, rowProperty: null, columnProperty: null,
    drilldownVariable: null, title: "",
    fn: null, fnRows: "", fnExpand: "", fnColumn: "", fnValues: "",
  },
  related: { settings: settingsPanel("PivotTableSettings") },
};

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

CanvasTimeSeries.craft = {
  displayName: "Time series",
  props: { objectSetVariable: null, interval: "day", title: "" },
  related: { settings: settingsPanel("TimeSeriesSettings") },
};

// ---- Time Series Analysis (§647) -------------------------------------------
/**
 * `workshop` p.392's *Time Series Analysis*: "enables users to independently investigate time
 * series data … derive new plots by selecting New Plot. Plots can be
 * organized across multiple canvases within the same analysis."
 *
 * The plots come from p.396's *Control series with object sets*: an object set and a
 * time series property, one root plot per object, which the reader cannot
 * delete or re-point but can move and restyle. A **New plot** is derived from
 * any plot by p.583-586's transforms, and is read as its root's series through
 * the whole chain (`series-analysis.ts`), so the server's transform machinery
 * does the arithmetic and a plot derived from a derived plot costs nothing
 * new. The analysis lives in the viewer's session: p.397's *Enable analysis
 * saving* is ○.
 */
export function CanvasSeriesAnalysis({
  objectSetVariable = null,
  property = null,
  labelProperty = null,
  limit = 5,
  title = "",
  plotTypes = null,
  eventSetTypes = null,
  newPlotCanvas = "input",
  eventSets: initialEventSets = null,
  viewRange = "full",
  windowStartVariable = null,
  windowEndVariable = null,
  relativeAmount = 2,
  relativeUnit = "week",
  syncXAxes = false,
  utc = false,
  overlayYAxes = false,
  collapseYAxes = false,
  collapsedBoundaries = false,
  tooltip = null,
  addData = false,
  addDataSets = null,
  saving = false,
  saveProjectVariable = null,
  fixedSaveLocation = false,
  outputVariable = null,
  autoloadVariable = null,
  keepOnLoad = false,
}: {
  objectSetVariable?: string | null;
  property?: string | null;
  labelProperty?: string | null;
  limit?: number;
  title?: string;
  /** p.396's *Customize available plot types*: those offered by New plot, in
   * order; null offers them all. */
  plotTypes?: string[] | null;
  /** p.396's *Customize available event set types* (§658); null offers both. */
  eventSetTypes?: string[] | null;
  /** p.396's *New plot placement* (§658): "input", "new" or a canvas number. */
  newPlotCanvas?: string | number;
  /** p.396's *Add initial event sets* (§658). */
  eventSets?: unknown;
  /** p.396's *Default view range* (§659): "full", "fixed" between two date
   * or timestamp variables, or "relative", this long before the page loaded. */
  viewRange?: string;
  windowStartVariable?: string | null;
  windowEndVariable?: string | null;
  relativeAmount?: number;
  relativeUnit?: string;
  /** p.396's *Sync X-axes across canvases* (§659). */
  syncXAxes?: boolean;
  /** p.396's *Enable UTC time format* (§659). */
  utc?: boolean;
  /** p.396's Y-axis chart options (§660). */
  overlayYAxes?: boolean;
  collapseYAxes?: boolean;
  collapsedBoundaries?: boolean;
  /** p.396's *Tooltip options* (§660). */
  tooltip?: unknown;
  /** p.392's *+ Add Data* and p.396's *Add data options* (§661): whether the
   * reader may add any object's series, and the object sets that narrow it. */
  addData?: boolean;
  addDataSets?: unknown;
  /** p.397's *Enable analysis saving* (§662), and where an analysis is saved:
   * the project a string variable names, or the module's own; with
   * *Don't allow users to choose save location*, there alone. */
  saving?: boolean;
  saveProjectVariable?: string | null;
  fixedSaveLocation?: boolean;
  /** p.397's *Output analysis RID* (§663): the string variable the open
   * analysis's RID is written to. */
  outputVariable?: string | null;
  /** p.397's *Autoload analyses* (§663): a variable naming the analyses to
   * load, and *Don't clear on load*. */
  autoloadVariable?: string | null;
  keepOnLoad?: boolean;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const definition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();
  const typeId = (definition as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const roots = Math.max(1, Math.min(MAX_SERIES_ROOTS, Number(limit) || 5));
  const set = useQuery({
    queryKey: ["canvas-series-analysis-set", JSON.stringify(definition ?? null), roots],
    queryFn: () => objApi.evaluateObjectSet(workspaceId, definition, { limit: roots }),
    enabled: !!objectSetVariable && !!definition && !!property,
  });
  const objects = (set.data?.instances ?? []).map((i) => {
    const raw = labelProperty ? i.properties[labelProperty] : null;
    return { id: i.id, label: raw === null || raw === undefined ? String(i.primary_key) : String(raw) };
  });
  const rootsKey = JSON.stringify([typeId, property, objects]);
  const [plots, setPlots] = useState<SeriesPlot[]>([]);
  const [addedCanvases, setAddedCanvases] = useState(0);
  React.useEffect(() => {
    if (!typeId || !property) return;
    setPlots((previous) => withSeriesRoots(previous, seriesRootPlots(objects, typeId, property)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rootsKey]);
  const readingsFor = useQueries({
    queries: plots.map((plot) => {
      const root = seriesRootOf(plots, plot.id)?.root ?? null;
      const chain = seriesChainOf(plots, plot.id);
      return {
        queryKey: ["canvas-series-analysis-plot", root?.objectId, root?.property, JSON.stringify(chain)],
        queryFn: () => objApi.seriesPoints(workspaceId, root!.typeId, root!.objectId, root!.property,
          { transforms: chain }),
        enabled: !!root && !seriesTransformsProblem(chain),
      };
    }),
  });
  // p.394-395's axes (§656), by canvas and axis - above the readings,
  // which are converted by them (§733).
  const [axes, setAxes] = useState<SeriesAxes>({});
  // p.394's unit conversion (§733): each plot's readings as its axis shows
  // them, so the line, its scale, the tooltip and the statistics all read
  // the converted values.
  const readings = plots.map((plot, n) => {
    const a = seriesAxisSettingsOf(axes, plot.canvas, seriesAxisOf(plot));
    return convertReadings(seriesReadingsOf(readingsFor[n]?.data?.points ?? []), a.unit, a.display);
  });
  const colorOf = (n: number) => CHART_PALETTE[n % CHART_PALETTE.length]!;
  const offered = SERIES_PLOT_TYPES.filter((k) => !plotTypes || plotTypes.includes(k));
  const setTypes = SERIES_EVENT_SET_TYPES.filter((k) => !eventSetTypes || eventSetTypes.includes(k));
  const placement = seriesPlacementOf(newPlotCanvas);
  // p.396's initial event sets (§658): the builder's, read from object sets,
  // shaded on every canvas; the reader may hide one but not change it.
  const { resolved: resolvedVariables, declared: declaredVariables } = useCanvasVariables();
  const initial = seriesInitialEventSetsOf(initialEventSets);
  const initialRead = useQueries({
    queries: initial.map((set) => {
      const definition = resolvedVariables[set.objectSetVariable];
      return {
        queryKey: ["canvas-series-analysis-initial-events", set.objectSetVariable,
          JSON.stringify(definition ?? null)],
        queryFn: () => objApi.evaluateObjectSet(workspaceId, definition, { limit: MAX_SERIES_INITIAL_EVENTS }),
        enabled: !!definition,
      };
    }),
  });
  const initialEvents = initial.map((set, n) =>
    seriesObjectEventsOf(initialRead[n]?.data?.instances ?? [], set.start, set.end));
  const [initialHidden, setInitialHidden] = useState<number[]>([]);
  const initialColor = (n: number) => CHART_PALETTE[(CHART_PALETTE.length - 1 - n) % CHART_PALETTE.length]!;
  const [draft, setDraft] = useState<{
    parent: string; transforms: SeriesTransform[]; bands?: SeriesBands;
    combine?: { kind: "combine" | "linear_aggregate"; others: string[]; aggregate: "avg" | "min" | "max" | "sum" };
    eventStats?: { set: string; aggregate: "sum" | "avg" | "min" | "max" | "count" | "stddev" };
  } | null>(null);
  const canvases = seriesCanvasesOf(plots, addedCanvases);
  // p.396's view range (§659): each canvas's, or one for them all when the
  // X-axes are synced; a canvas the reader has not moved shows the default.
  const [loaded] = useState(() => Date.now());
  const windowStartWritten = useCanvasParameter(windowStartVariable);
  const windowStartResolved = useCanvasVariable(windowStartVariable);
  const windowEndWritten = useCanvasParameter(windowEndVariable);
  const windowEndResolved = useCanvasVariable(windowEndVariable);
  const defaultView = seriesDefaultRangeOf(viewRange, windowOf(
    windowStartWritten !== undefined ? windowStartWritten : windowStartResolved,
    windowEndWritten !== undefined ? windowEndWritten : windowEndResolved,
  ), relativeAmount, relativeUnit, loaded);
  const [views, setViews] = useState<Record<string, SeriesViewRange | null>>({});
  // p.396's Collapse Y-axes by default (§660): the reader expands a canvas's.
  const [collapsedAxes, setCollapsedAxes] = useState<Record<number, boolean>>({});
  const collapsedOf = (canvas: number) => collapsedAxes[canvas] ?? !!collapseYAxes;
  const tooltipOptions = seriesTooltipOptionsOf(tooltip);
  // p.392's + Add Data (§661): a source - one of the builder's object sets,
  // or with none any object type - then an object, then its series.
  const dataSets = seriesAddDataSetsOf(addDataSets);
  const [dataDraft, setDataDraft] = useState<{ source: string; object: string; property: string; search: string } | null>(null);
  const dataSetDefinition = dataDraft && dataSets.length ? resolvedVariables[dataDraft.source] : undefined;
  const dataTypeId = !dataDraft?.source ? null : dataSets.length
    ? (dataSetDefinition as { object_type_id?: string } | undefined)?.object_type_id ?? null : dataDraft.source;
  const dataType = useQuery({
    queryKey: ["object-type", dataTypeId],
    queryFn: () => objApi.getType(workspaceId, dataTypeId!),
    enabled: !!dataTypeId,
  });
  const dataObjects = useQuery({
    queryKey: ["canvas-series-analysis-add-objects", dataDraft?.source, JSON.stringify(dataSetDefinition ?? null)],
    queryFn: async () => (dataSets.length
      ? (await objApi.evaluateObjectSet(workspaceId, dataSetDefinition, { limit: 200 })).instances
      : (await objApi.listInstances(workspaceId, dataTypeId!, 200)).items),
    enabled: !!dataTypeId && (dataSets.length === 0 || !!dataSetDefinition),
  });
  const dataTitle = dataType.data?.properties.find((p) => p.id === dataType.data?.title_property_id)?.api_name;
  const dataOffered = (dataObjects.data ?? [])
    .map((o) => ({ id: o.id, label: seriesObjectLabelOf(o, dataTitle) }))
    .filter((o) => !dataDraft?.search.trim()
      || o.label.toLowerCase().includes(dataDraft.search.trim().toLowerCase()));
  const dataSeries = (dataType.data?.properties ?? []).filter((p) => p.data_type === "time_series");
  // p.397's analysis saving (§662): the analysis open now, if one is, and
  // where the next is saved.
  const [currentAnalysis, setCurrentAnalysis] = useState<(SeriesAnalysis & { project: string }) | null>(null);
  const [saveError, setSaveError] = useState("");
  const saveWritten = useCanvasParameter(saveProjectVariable);
  const saveResolved = useCanvasVariable(saveProjectVariable);
  const namedProject = saveWritten !== undefined ? saveWritten : saveResolved;
  const defaultLocation = typeof namedProject === "string" && namedProject ? namedProject : projectId;
  const [saveDraft, setSaveDraft] = useState<{ name: string; visibility: string; location: string } | null>(null);
  const [openFrom, setOpenFrom] = useState<string | null>(null);
  // Searched, a page at a time (§828): every project in the workspace was an
  // <option>, and a workspace can hold ten thousand. A project once offered
  // keeps its name when a later search no longer lists it.
  const [locationSearch, setLocationSearch] = useState("");
  const locations = useQuery({
    queryKey: ["canvas-series-analysis-locations", workspaceId, locationSearch],
    queryFn: () => api.projectPage(workspaceId, locationSearch, 0),
    enabled: !!saveDraft && !fixedSaveLocation,
    placeholderData: (previous) => previous,
  });
  const locationNames = React.useRef(new Map<string, string>());
  for (const p of locations.data?.items ?? []) locationNames.current.set(p.id, p.name);
  const openable = useQuery({
    queryKey: ["canvas-series-analyses", workspaceId, openFrom],
    queryFn: () => seriesAnalysisApi.list(workspaceId, openFrom!),
    enabled: !!openFrom,
  });
  const viewNow = () => seriesSavedViewOf(plots, addedCanvases, eventSets, axes);
  const saveAnalysis = async (over: boolean) => {
    try {
      const saved = over && currentAnalysis
        ? await seriesAnalysisApi.replace(workspaceId, currentAnalysis.project, currentAnalysis.id,
          { visibility: currentAnalysis.visibility, state: viewNow() })
        : await seriesAnalysisApi.save(workspaceId, saveDraft!.location,
          { name: saveDraft!.name.trim(), visibility: saveDraft!.visibility, state: viewNow() });
      setCurrentAnalysis({ ...saved, project: over && currentAnalysis ? currentAnalysis.project : saveDraft!.location });
      // Only a save from the draft closes it. Saving over opened none, and
      // clearing one here threw away a "Save as new analysis" somebody had
      // opened while that request was in flight - a CI run caught the Save
      // button detaching under the click.
      if (!over) setSaveDraft(null);
      setSaveError("");
    } catch (error) {
      setSaveError(error instanceof ApiError ? error.message : "Couldn't save this analysis.");
    }
  };
  // p.397's Output analysis RID (§663): the open analysis's, once there is one.
  const { set: setOutput } = useCanvasParameters();
  React.useEffect(() => {
    if (outputVariable && currentAnalysis) setOutput(outputVariable, currentAnalysis.id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outputVariable, currentAnalysis?.id]);
  // p.397's Autoload analyses (§663): read by RID once the set's roots are
  // known. A change of RIDs starts again from the set's roots, or with Don't
  // clear on load adds the analyses not loaded yet to what is there.
  const autoloadWritten = useCanvasParameter(autoloadVariable);
  const autoloadResolved = useCanvasVariable(autoloadVariable);
  const autoloadIds = seriesAutoloadIdsOf(autoloadWritten !== undefined ? autoloadWritten : autoloadResolved);
  const autoloads = useQueries({
    queries: autoloadIds.map((id) => ({
      queryKey: ["canvas-series-analysis-rid", workspaceId, id],
      queryFn: () => seriesAnalysisApi.byRid(workspaceId, id),
      retry: false,
    })),
  });
  const [autoloaded, setAutoloaded] = useState<string[] | null>(null);
  const autoloadsSettled = autoloads.every((q) => !q.isPending);
  React.useEffect(() => {
    if (!typeId || !property || !set.data || !autoloadsSettled) return;
    if (autoloaded && JSON.stringify(autoloaded) === JSON.stringify(autoloadIds)) return;
    const rootsNow = seriesRootPlots(objects, typeId, property);
    const fresh = keepOnLoad && autoloaded ? autoloadIds.filter((id) => !autoloaded.includes(id)) : autoloadIds;
    let view = keepOnLoad && autoloaded
      ? seriesSavedViewOf(plots, addedCanvases, eventSetsRaw, axes)
      : seriesSavedViewOf(rootsNow, 0, [], {});
    let last: SeriesAnalysis | null = null;
    for (const id of fresh) {
      const found = autoloads[autoloadIds.indexOf(id)]?.data;
      if (!found) continue;
      view = seriesMergedView(view, seriesOpenedView(found.state, rootsNow));
      last = found;
    }
    setAutoloaded(autoloadIds);
    if (!last && !(autoloaded && !keepOnLoad)) return;
    setPlots(view.plots);
    setAddedCanvases(view.canvases);
    setEventSets(view.eventSets);
    setAxes(view.axes);
    if (last) setCurrentAnalysis({ ...last, project: last.project_id });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(autoloadIds), autoloadsSettled, set.data, typeId, property]);
  const openAnalysis = (analysis: SeriesAnalysis, project: string) => {
    const view = seriesOpenedView(analysis.state,
      typeId && property ? seriesRootPlots(objects, typeId, property) : []);
    setPlots(view.plots);
    setAddedCanvases(view.canvases);
    setEventSets(view.eventSets);
    setAxes(view.axes);
    setCurrentAnalysis({ ...analysis, project });
    setOpenFrom(null);
  };
  const viewKey = (canvas: number) => (syncXAxes ? "all" : String(canvas));
  const viewOf = (canvas: number) => (viewKey(canvas) in views ? views[viewKey(canvas)]! : defaultView);
  const fullOf = (canvas: number) => seriesTimesOf(plots.flatMap((p, n) => (p.canvas === canvas || syncXAxes
    ? [readings[n] ?? []] : [])));
  const setView = (canvas: number, next: SeriesViewRange | null | undefined) => {
    const { [viewKey(canvas)]: _was, ...rest } = views;
    setViews(next === undefined ? rest : { ...rest, [viewKey(canvas)]: next });
  };
  // p.392's Time series search (§651): event sets over the plots, each
  // searched by the server over the plot's whole chain.
  const [eventSetsRaw, setEventSets] = useState<SeriesEventSet[]>([]);
  const eventSets = liveSeriesEventSets(eventSetsRaw, plots);
  const [eventDraft, setEventDraft] = useState<{ plot: string; op: SeriesFilterOperator; value: string } | null>(null);
  // p.393's Linked event set (§654): a link from a plot's root object, and
  // the linked type's timestamp or date properties for the two ends.
  const [linkedDraft, setLinkedDraft] = useState<{ plot: string; link: string; start: string; end: string } | null>(null);
  const linkedRoot = linkedDraft ? seriesRootOf(plots, linkedDraft.plot)?.root ?? null : null;
  const linkedLinks = useQuery({
    queryKey: ["canvas-series-analysis-links", linkedRoot?.typeId],
    queryFn: () => objApi.typeLinks(workspaceId, linkedRoot!.typeId),
    enabled: !!linkedRoot,
  });
  const linkedChosen = (linkedLinks.data ?? []).find(
    (l) => `${l.link_type_id}:${l.direction}` === linkedDraft?.link) ?? null;
  const linkedType = useQuery({
    queryKey: ["canvas-series-analysis-linked-type", linkedChosen?.far_type_id],
    queryFn: () => objApi.getType(workspaceId, linkedChosen!.far_type_id),
    enabled: !!linkedChosen,
  });
  const linkedMoments = (linkedType.data?.properties ?? [])
    .filter((p) => p.data_type === "timestamp" || p.data_type === "date");
  const eventsFor = useQueries({
    queries: eventSets.map((set) => {
      const root = seriesRootOf(plots, set.plot)?.root ?? null;
      if (set.linked) {
        return {
          queryKey: ["canvas-series-analysis-linked-events", root?.objectId, JSON.stringify(set.linked)],
          queryFn: () => objApi.linkedEvents(workspaceId, root!.typeId, root!.objectId, set.linked),
          enabled: !!root,
        };
      }
      const chain = seriesChainOf(plots, set.plot);
      return {
        queryKey: ["canvas-series-analysis-events", root?.objectId, root?.property,
          JSON.stringify(chain), set.op, set.value],
        queryFn: () => objApi.seriesEvents(workspaceId, root!.typeId, root!.objectId, root!.property,
          { op: set.op, value: set.value, transforms: chain }),
        enabled: !!root,
      };
    }),
  });
  // Event statistics reads a search's events in the query; a linked set's
  // are objects (§654).
  const searchSets = eventSets.filter((set) => !set.linked);
  const eventsOfSet = eventSets.map((_, n) => seriesEventsOf(eventsFor[n]?.data?.events ?? []));

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block"
         data-testid="series-analysis">
      {title && <h3 style={{ fontSize: 14, margin: "0 0 6px" }}>{title}</h3>}
      {(!objectSetVariable || !property) && (
        <p className="canvas-widget-empty">
          Time series analysis - choose an object set and its time series property in Settings
        </p>
      )}
      {objectSetVariable && property && (variablesPending || set.isPending) && (
        <p className="canvas-widget-empty">Loading…</p>
      )}
      {set.isError && (
        <p className="canvas-widget-empty">
          {set.error instanceof ApiError ? set.error.message : "Couldn't read this object set."}
        </p>
      )}
      {set.data && plots.length === 0 && (
        <p className="canvas-widget-empty">Nothing in this set.</p>
      )}
      {plots.length > 0 && (
        <>
          {canvases.map((canvas) => (
            <React.Fragment key={canvas}>
            <div className="row-actions" data-testid={`series-view-${canvas}`} style={{ gap: 4 }}>
              {([["zoom in", "Zoom in"], ["zoom out", "Zoom out"], ["earlier", "◀"], ["later", "▶"]] as const)
                .map(([what, text]) => (
                  <button key={what} type="button" className="btn quiet" aria-label={`Canvas ${canvas} ${what}`}
                          disabled={!fullOf(canvas)}
                          onClick={() => {
                            const full = fullOf(canvas)!;
                            setView(canvas, what === "zoom in" ? seriesZoomedRange(viewOf(canvas), full, 0.5)
                              : what === "zoom out" ? seriesZoomedRange(viewOf(canvas), full, 2)
                              : seriesPannedRange(viewOf(canvas), full, what === "earlier" ? -0.5 : 0.5));
                          }}>
                    {text}
                  </button>
                ))}
              <button type="button" className="btn quiet" aria-label={`Canvas ${canvas} reset view`}
                      onClick={() => setView(canvas, undefined)}>
                Reset view
              </button>
              <button type="button" className="btn quiet"
                      aria-label={`Canvas ${canvas} ${collapsedOf(canvas) ? "expand" : "collapse"} axes`}
                      onClick={() => setCollapsedAxes({ ...collapsedAxes, [canvas]: !collapsedOf(canvas) })}>
                {collapsedOf(canvas) ? "Expand axes" : "Collapse axes"}
              </button>
            </div>
            <SeriesAnalysisChart canvas={canvas} view={viewOf(canvas)} utc={utc}
              overlay={!!overlayYAxes} collapsed={collapsedOf(canvas)} boundaries={!!collapsedBoundaries}
              tooltip={tooltipOptions}
              axes={seriesAxesOf(plots, canvas).map((axis) => {
                const s = seriesAxisSettingsOf(axes, canvas, axis);
                // Labelled with the unit shown, which is the converted one.
                return { axis, settings: { ...s, unit: shownUnit(s.unit, s.display) } };
              })}
              events={[...initial.flatMap((_, n) => initialHidden.includes(n) ? []
                : [{ id: `initial-${n + 1}`, color: initialColor(n), events: initialEvents[n] ?? [] }]),
              ...eventSets.flatMap((set, n) => {
                const at = plots.findIndex((p) => p.id === set.plot);
                return set.highlight && plots[at]?.canvas === canvas
                  ? [{ id: set.id, color: colorOf(at), events: eventsOfSet[n] ?? [] }] : [];
              })]}
              plots={plots
              .map((p, n) => ({ plot: p, n }))
              .filter(({ plot }) => plot.canvas === canvas)
              .map(({ plot, n }) => ({ id: plot.id, label: plot.label, color: colorOf(n),
                dashed: plot.style === "dashed", display: seriesDisplayOf(plot), axis: seriesAxisOf(plot),
                readings: readings[n] ?? [] }))} />
            </React.Fragment>
          ))}
          {/* The Plots panel: each plot's display, place and statistics. */}
          <table className="data-grid" data-testid="series-plots">
            <thead>
              <tr>
                <th>Plot</th><th>Canvas</th><th>Axis</th><th>Line</th><th>Width</th><th>Gradient</th><th>Points</th>
                <th>Interpolation</th>
                <th>Min</th><th>Max</th><th>Mean</th><th />
              </tr>
            </thead>
            <tbody>
              {plots.map((plot, n) => {
                // p.395: "within the current view range".
                const stats = seriesStatsOf(readings[n] ?? [], viewOf(plot.canvas));
                const failed = readingsFor[n]?.error;
                const display = seriesDisplayOf(plot);
                const options = seriesPointOptions(display);
                return (
                  <tr key={plot.id} data-plot={plot.id} data-label={plot.label}>
                    <td>
                      <span style={{ color: colorOf(n) }}>■</span> {plot.label}
                      {failed && (
                        <div className="field-hint">
                          {failed instanceof ApiError ? failed.message : "Couldn't read this plot."}
                        </div>
                      )}
                    </td>
                    <td>
                      <select aria-label={`${plot.label} canvas`} value={plot.canvas}
                              onChange={(e) => setPlots(withSeriesPlotSetting(plots, plot.id, "canvas",
                                Number(e.target.value)))}>
                        {canvases.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </td>
                    <td>
                      <select aria-label={`${plot.label} axis`} value={seriesAxisOf(plot)}
                              onChange={(e) => setPlots(withSeriesPlotSetting(plots, plot.id, "axis",
                                e.target.value === "new" ? newSeriesAxisOf(plots, plot.canvas)!
                                  : Number(e.target.value)))}>
                        {seriesAxesOf(plots, plot.canvas).map((a) => <option key={a} value={a}>{`Axis ${a}`}</option>)}
                        {newSeriesAxisOf(plots, plot.canvas) !== null && <option value="new">New axis</option>}
                      </select>
                    </td>
                    <td>
                      <select aria-label={`${plot.label} line`} value={plot.style}
                              onChange={(e) => setPlots(withSeriesPlotSetting(plots, plot.id, "style",
                                e.target.value as SeriesLineStyle))}>
                        {SERIES_LINE_STYLES.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </td>
                    <td>
                      <input type="number" min={0.5} max={8} step={0.5} style={{ width: 56 }}
                             aria-label={`${plot.label} line width`} value={display.width}
                             onChange={(e) => setPlots(withSeriesDisplay(plots, plot.id, "width",
                               e.target.value === "" ? Number.NaN : Number(e.target.value)))} />
                    </td>
                    <td>
                      <input type="checkbox" aria-label={`${plot.label} gradient`} checked={display.gradient}
                             onChange={(e) => setPlots(withSeriesDisplay(plots, plot.id, "gradient",
                               e.target.checked))} />
                    </td>
                    <td>
                      <span className="row-actions" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <select aria-label={`${plot.label} point shape`} value={display.shape}
                                onChange={(e) => setPlots(withSeriesDisplay(plots, plot.id, "shape",
                                  e.target.value as SeriesPointShape))}>
                          {SERIES_POINT_SHAPES.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                        <input type="number" min={2} max={16} style={{ width: 48 }}
                               aria-label={`${plot.label} point size`} value={display.size}
                               disabled={!options.size}
                               onChange={(e) => setPlots(withSeriesDisplay(plots, plot.id, "size",
                                 e.target.value === "" ? Number.NaN : Number(e.target.value)))} />
                        <select aria-label={`${plot.label} point fill`} value={display.fill}
                                disabled={!options.fill}
                                onChange={(e) => setPlots(withSeriesDisplay(plots, plot.id, "fill",
                                  e.target.value as SeriesPointFill))}>
                          {SERIES_POINT_FILLS.map((f) => <option key={f} value={f}>{SERIES_POINT_FILL_WORDS[f]}</option>)}
                        </select>
                        <input type="number" min={0.5} max={4} step={0.5} style={{ width: 48 }}
                               aria-label={`${plot.label} point outline`} value={display.outline}
                               disabled={!options.outline}
                               onChange={(e) => setPlots(withSeriesDisplay(plots, plot.id, "outline",
                                 e.target.value === "" ? Number.NaN : Number(e.target.value)))} />
                      </span>
                    </td>
                    <td>
                      <span className="row-actions" style={{ gap: 4, flexWrap: "nowrap" }}>
                        <select aria-label={`${plot.label} internal interpolation`} value={display.internal}
                                onChange={(e) => setPlots(withSeriesDisplay(plots, plot.id, "internal",
                                  e.target.value as SeriesInternalInterpolation))}>
                          {SERIES_INTERNAL_INTERPOLATIONS.map((i) => <option key={i} value={i}>{i}</option>)}
                        </select>
                        <select aria-label={`${plot.label} external interpolation`} value={display.external}
                                onChange={(e) => setPlots(withSeriesDisplay(plots, plot.id, "external",
                                  e.target.value as SeriesExternalInterpolation))}>
                          {SERIES_EXTERNAL_INTERPOLATIONS.map((i) => <option key={i} value={i}>{i}</option>)}
                        </select>
                      </span>
                    </td>
                    <td data-stat="min">{stats ? Number(stats.min.toFixed(3)) : "—"}</td>
                    <td data-stat="max">{stats ? Number(stats.max.toFixed(3)) : "—"}</td>
                    <td data-stat="mean">{stats ? Number(stats.mean.toFixed(3)) : "—"}</td>
                    <td>
                      {(!plot.root || plot.added) && (
                        <button type="button" className="btn quiet"
                                aria-label={`Remove ${plot.label}`}
                                onClick={() => setPlots(withoutSeriesPlot(plots, plot.id))}>
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <table className="data-grid" data-testid="series-axes" style={{ marginTop: 6 }}>
            <thead>
              <tr>
                <th>Axis</th><th>Unit</th><th>Display as</th><th>Auto scale</th><th>Min</th><th>Max</th><th>Log</th>
                <th>Invert</th><th>Align</th>
              </tr>
            </thead>
            <tbody>
              {canvases.flatMap((c) => seriesAxesOf(plots, c).map((axis) => {
                const a = seriesAxisSettingsOf(axes, c, axis);
                const name = `Canvas ${c} axis ${axis}`;
                const set = <K extends keyof typeof a>(key: K, value: (typeof a)[K]) =>
                  setAxes(withSeriesAxisSetting(axes, c, axis, key, value));
                const problem = seriesAxisProblem(a);
                return (
                  <tr key={`${c}:${axis}`} data-axis={`${c}:${axis}`}>
                    <td>
                      {name}
                      {problem && <div className="field-hint" data-testid="series-axis-problem">{problem}</div>}
                    </td>
                    <td>
                      <input aria-label={`${name} unit`} value={a.unit} maxLength={MAX_SERIES_UNIT}
                             style={{ width: 64 }} onChange={(e) => set("unit", e.target.value)} />
                    </td>
                    <td>
                      {/* p.394: "Allows unit conversion (for example, meters
                          to kilometers)" (§733) - into a unit of the same
                          kind as the Unit beside it. */}
                      <input aria-label={`${name} display as`} value={a.display} maxLength={MAX_SERIES_UNIT}
                             placeholder="km" style={{ width: 64 }}
                             onChange={(e) => set("display", e.target.value)} />
                      {conversionProblem(a.unit, a.display) && (
                        <div className="field-hint" data-testid="series-unit-problem">
                          {conversionProblem(a.unit, a.display)}
                        </div>
                      )}
                    </td>
                    <td>
                      <input type="checkbox" aria-label={`${name} auto scale`} checked={a.auto}
                             onChange={(e) => set("auto", e.target.checked)} />
                    </td>
                    <td>
                      <input type="number" aria-label={`${name} min`} value={a.min ?? ""} disabled={a.auto}
                             style={{ width: 72 }}
                             onChange={(e) => set("min", e.target.value === "" ? null : Number(e.target.value))} />
                    </td>
                    <td>
                      <input type="number" aria-label={`${name} max`} value={a.max ?? ""} disabled={a.auto}
                             style={{ width: 72 }}
                             onChange={(e) => set("max", e.target.value === "" ? null : Number(e.target.value))} />
                    </td>
                    <td>
                      <input type="checkbox" aria-label={`${name} log scale`} checked={a.log}
                             onChange={(e) => set("log", e.target.checked)} />
                    </td>
                    <td>
                      <input type="checkbox" aria-label={`${name} invert`} checked={a.invert}
                             onChange={(e) => set("invert", e.target.checked)} />
                    </td>
                    <td>
                      <select aria-label={`${name} align`} value={a.align}
                              onChange={(e) => set("align", e.target.value as SeriesAxisAlign)}>
                        {SERIES_AXIS_ALIGNS.map((x) => <option key={x} value={x}>{x}</option>)}
                      </select>
                    </td>
                  </tr>
                );
              }))}
            </tbody>
          </table>
          <div className="row-actions" style={{ marginTop: 6 }}>
            {offered.length > 0 && plots.length < MAX_SERIES_PLOTS && (
              <select aria-label="New plot" value=""
                      onChange={(e) => {
                        if (!e.target.value) return;
                        // p.393's Bollinger bands are three plots, set up by
                        // their own three numbers (§649).
                        // Combine picks other plots as its inputs (§650), as
                        // a linear aggregation does (§653).
                        setDraft(e.target.value === "bollinger"
                          ? { parent: plots[0]!.id, transforms: [], bands: DEFAULT_SERIES_BANDS }
                          : e.target.value === "combine" || e.target.value === "linear_aggregate"
                            ? { parent: plots[0]!.id, transforms: [],
                                combine: { kind: e.target.value, others: [], aggregate: "avg" } }
                          : e.target.value === "event_statistics"
                            ? { parent: plots[0]!.id, transforms: [],
                                eventStats: { set: searchSets[0]?.id ?? "", aggregate: "avg" } }
                            : { parent: plots[0]!.id,
                                transforms: [blankTransform(e.target.value as TransformKind)] });
                      }}>
                <option value="">New plot…</option>
                {offered.map((k) => <option key={k} value={k}>{SERIES_PLOT_LABELS[k]}</option>)}
              </select>
            )}
            <button type="button" className="btn quiet"
                    onClick={() => setAddedCanvases(Math.max(addedCanvases, ...canvases) + 1)}>
              New canvas
            </button>
            {addData && plots.length < MAX_SERIES_PLOTS && (
              <button type="button" className="btn quiet"
                      onClick={() => setDataDraft({ source: dataSets[0] ?? "", object: "", property: "", search: "" })}>
                Add data
              </button>
            )}
            {saving && currentAnalysis?.mine && (
              <button type="button" className="btn quiet" onClick={() => void saveAnalysis(true)}>
                Save analysis
              </button>
            )}
            {saving && (
              <button type="button" className="btn quiet"
                      onClick={() => {
                        setSaveError("");
                        setSaveDraft({ name: currentAnalysis ? `${currentAnalysis.name} copy` : "",
                          visibility: currentAnalysis?.visibility ?? "private", location: defaultLocation });
                      }}>
                Save as new analysis
              </button>
            )}
            {saving && (
              <button type="button" className="btn quiet" onClick={() => setOpenFrom(defaultLocation)}>
                Open analysis
              </button>
            )}
            {saving && currentAnalysis && (
              <span className="field-hint" data-testid="series-analysis-open">
                {`${currentAnalysis.name} (${currentAnalysis.visibility}${currentAnalysis.mine ? "" : `, by ${currentAnalysis.created_by_name ?? "another reader"}`})`}
              </span>
            )}
            {setTypes.includes("search") && eventSets.length < MAX_SERIES_EVENT_SETS && (
              <button type="button" className="btn quiet"
                      onClick={() => setEventDraft({ plot: plots[0]!.id, op: "gt", value: "" })}>
                New event set
              </button>
            )}
            {setTypes.includes("linked") && eventSets.length < MAX_SERIES_EVENT_SETS && (
              <button type="button" className="btn quiet"
                      onClick={() => setLinkedDraft({ plot: plots[0]!.id, link: "", start: "", end: "" })}>
                New linked event set
              </button>
            )}
          </div>
          {eventDraft && (
            <div className="row-actions" data-testid="series-new-events" style={{ marginTop: 6 }}>
              <select aria-label="Event plot" value={eventDraft.plot}
                      onChange={(e) => setEventDraft({ ...eventDraft, plot: e.target.value })}>
                {plots.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
              <select aria-label="Event comparison" value={eventDraft.op}
                      onChange={(e) => setEventDraft({ ...eventDraft, op: e.target.value as SeriesFilterOperator })}>
                {SERIES_FILTER_OPERATORS.map((o) => <option key={o} value={o}>{SERIES_FILTER_WORDS[o]}</option>)}
              </select>
              <input type="number" aria-label="Event threshold" value={eventDraft.value}
                     onChange={(e) => setEventDraft({ ...eventDraft, value: e.target.value })} />
              <button type="button" className="btn"
                      disabled={eventDraft.value.trim() === "" || !Number.isFinite(Number(eventDraft.value))}
                      onClick={() => {
                        setEventSets(withSeriesEventSet(eventSets, plots, eventDraft.plot, eventDraft.op,
                          Number(eventDraft.value)));
                        setEventDraft(null);
                      }}>
                Add event set
              </button>
              <button type="button" className="btn quiet" onClick={() => setEventDraft(null)}>Cancel</button>
            </div>
          )}
          {saveError && !saveDraft && <p className="field-hint" role="alert">{saveError}</p>}
          {saveDraft && (
            <div className="row-actions" data-testid="series-save-analysis" style={{ marginTop: 6, flexWrap: "wrap", gap: 4 }}>
              <input aria-label="Analysis name" placeholder="Name" value={saveDraft.name} maxLength={200}
                     onChange={(e) => setSaveDraft({ ...saveDraft, name: e.target.value })} />
              <select aria-label="Analysis visibility" value={saveDraft.visibility}
                      onChange={(e) => setSaveDraft({ ...saveDraft, visibility: e.target.value })}>
                <option value="private">Private</option>
                <option value="public">Public</option>
              </select>
              {!fixedSaveLocation && (
                <input type="search" aria-label="Find a project to save in" placeholder="Find a project"
                       value={locationSearch} onChange={(e) => setLocationSearch(e.target.value)} />
              )}
              {!fixedSaveLocation && (
                <select aria-label="Save location" value={saveDraft.location}
                        onChange={(e) => setSaveDraft({ ...saveDraft, location: e.target.value })}>
                  {!(locations.data?.items ?? []).some((p) => p.id === saveDraft.location) && (
                    <option value={saveDraft.location}>
                      {locationNames.current.get(saveDraft.location) ?? "This project"}
                    </option>
                  )}
                  {(locations.data?.items ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              )}
              <button type="button" className="btn" disabled={!saveDraft.name.trim()}
                      onClick={() => void saveAnalysis(false)}>
                Save
              </button>
              <button type="button" className="btn quiet" onClick={() => setSaveDraft(null)}>Cancel</button>
              {saveError && <span className="field-hint" role="alert">{saveError}</span>}
            </div>
          )}
          {openFrom && (
            <div data-testid="series-open-analysis" style={{ marginTop: 6 }}>
              {openable.isPending && <p className="field-hint">Loading…</p>}
              {openable.data && openable.data.length === 0 && (
                <p className="field-hint">No saved analyses here yet.</p>
              )}
              {openable.data && openable.data.length > 0 && (
                <table className="data-grid">
                  <thead><tr><th>Analysis</th><th>By</th><th>Shared</th><th /></tr></thead>
                  <tbody>
                    {openable.data.map((a) => (
                      <tr key={a.id} data-label={a.name}>
                        <td>{a.name}</td>
                        <td>{a.mine ? "You" : a.created_by_name ?? "Another reader"}</td>
                        <td>{a.visibility}</td>
                        <td>
                          <button type="button" className="btn quiet" aria-label={`Open ${a.name}`}
                                  onClick={() => openAnalysis(a, openFrom)}>
                            Open
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <button type="button" className="btn quiet" onClick={() => setOpenFrom(null)}>Close</button>
            </div>
          )}
          {dataDraft && (
            <div className="row-actions" data-testid="series-add-data" style={{ marginTop: 6, flexWrap: "wrap", gap: 4 }}>
              {dataSets.length ? (
                <select aria-label="Data source" value={dataDraft.source}
                        onChange={(e) => setDataDraft({ ...dataDraft, source: e.target.value, object: "", property: "" })}>
                  {dataSets.map((id) => <option key={id} value={id}>{declaredVariables[id]?.label ?? id}</option>)}
                </select>
              ) : (
                // **The ontology, searched, not its first 200 types (§893).**
                // A plain list of one page offered a reader of a larger
                // workspace none of the rest, and said nothing.
                <TypePicker workspaceId={workspaceId} label="Data source" placeholder="Object type…"
                            testId="series-data-source" value={dataDraft.source}
                            onChange={(id) => setDataDraft({ ...dataDraft, source: id, object: "", property: "" })} />
              )}
              <input aria-label="Find an object" placeholder="Find an object" value={dataDraft.search}
                     onChange={(e) => setDataDraft({ ...dataDraft, search: e.target.value })} />
              <select aria-label="Data object" value={dataDraft.object} disabled={!dataTypeId}
                      onChange={(e) => setDataDraft({ ...dataDraft, object: e.target.value })}>
                <option value="">Object…</option>
                {dataOffered.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
              <select aria-label="Data series" value={dataDraft.property} disabled={!dataTypeId}
                      onChange={(e) => setDataDraft({ ...dataDraft, property: e.target.value })}>
                <option value="">Time series…</option>
                {dataSeries.map((p) => <option key={p.api_name} value={p.api_name}>{p.display_name}</option>)}
              </select>
              {dataType.data && dataSeries.length === 0 && (
                <span className="field-hint">{`${dataType.data.display_name} has no time series property.`}</span>
              )}
              <button type="button" className="btn"
                      disabled={!dataTypeId || !dataDraft.object || !dataDraft.property}
                      onClick={() => {
                        const picked = dataOffered.find((o) => o.id === dataDraft.object)
                          ?? { id: dataDraft.object, label: dataDraft.object };
                        setPlots(withSeriesAddedRoot(plots, { objectId: picked.id, typeId: dataTypeId!,
                          property: dataDraft.property, objectLabel: picked.label },
                        seriesCanvasFor(placement, 1, canvases)));
                        setDataDraft(null);
                      }}>
                Add series
              </button>
              <button type="button" className="btn quiet" onClick={() => setDataDraft(null)}>Cancel</button>
            </div>
          )}
          {linkedDraft && (
            <div className="row-actions" data-testid="series-new-linked-events"
                 style={{ marginTop: 6, flexWrap: "wrap" }}>
              <select aria-label="Linked from plot" value={linkedDraft.plot}
                      onChange={(e) => setLinkedDraft({ plot: e.target.value, link: "", start: "", end: "" })}>
                {plots.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
              <select aria-label="Event link" value={linkedDraft.link}
                      onChange={(e) => setLinkedDraft({ ...linkedDraft, link: e.target.value, start: "", end: "" })}>
                <option value="">Choose a link…</option>
                {(linkedLinks.data ?? []).map((l) => (
                  <option key={`${l.link_type_id}:${l.direction}`} value={`${l.link_type_id}:${l.direction}`}>
                    {`${l.side_name} (${l.far_type_display_name})`}
                  </option>
                ))}
              </select>
              <select aria-label="Event start" value={linkedDraft.start} disabled={!linkedChosen}
                      onChange={(e) => setLinkedDraft({ ...linkedDraft, start: e.target.value })}>
                <option value="">Start property…</option>
                {linkedMoments.map((p) => <option key={p.api_name} value={p.api_name}>{p.display_name}</option>)}
              </select>
              <select aria-label="Event end" value={linkedDraft.end} disabled={!linkedChosen}
                      onChange={(e) => setLinkedDraft({ ...linkedDraft, end: e.target.value })}>
                <option value="">No end (a moment)</option>
                {linkedMoments.map((p) => <option key={p.api_name} value={p.api_name}>{p.display_name}</option>)}
              </select>
              {linkedChosen && linkedType.data && linkedMoments.length === 0 && (
                <span className="field-hint">{`${linkedChosen.far_type_display_name} has no timestamp or date property.`}</span>
              )}
              <button type="button" className="btn"
                      disabled={!linkedChosen || !linkedDraft.start}
                      onClick={() => {
                        setEventSets(withSeriesLinkedEventSet(eventSets, plots, linkedDraft.plot, {
                          link: linkedChosen!.link_type_id, direction: linkedChosen!.direction,
                          start: linkedDraft.start, end: linkedDraft.end || null,
                        }, linkedChosen!.side_name));
                        setLinkedDraft(null);
                      }}>
                Add linked event set
              </button>
              <button type="button" className="btn quiet" onClick={() => setLinkedDraft(null)}>Cancel</button>
            </div>
          )}
          {(eventSets.length > 0 || initial.length > 0) && (
            <table className="data-grid" data-testid="series-event-sets" style={{ marginTop: 6 }}>
              <thead><tr><th>Event set</th><th>Events</th><th>Highlight</th><th /></tr></thead>
              <tbody>
                {initial.map((set, n) => {
                  const read = initialRead[n]?.data;
                  return (
                    <tr key={`initial-${n}`} data-label={set.label} data-initial="">
                      <td>{set.label}</td>
                      <td data-stat="events">
                        {read ? `${seriesEventCount(initialEvents[n] ?? [], viewOf(1))}${read.total > read.instances.length ? "+" : ""}` : "…"}
                      </td>
                      <td>
                        <input type="checkbox" aria-label={`Highlight ${set.label}`} checked={!initialHidden.includes(n)}
                               onChange={(e) => setInitialHidden(e.target.checked
                                 ? initialHidden.filter((x) => x !== n) : [...initialHidden, n])} />
                      </td>
                      <td />
                    </tr>
                  );
                })}
                {eventSets.map((set, n) => (
                  <tr key={set.id} data-label={set.label}>
                    <td>{set.label}</td>
                    <td data-stat="events">
                      {eventsFor[n]?.data
                        ? `${seriesEventCount(eventsOfSet[n] ?? [], viewOf(plots.find((p) => p.id === set.plot)?.canvas ?? 1))}${eventsFor[n]!.data!.truncated ? "+" : ""}`
                        : "…"}
                    </td>
                    <td>
                      <input type="checkbox" aria-label={`Highlight ${set.label}`} checked={set.highlight}
                             onChange={(e) => setEventSets(eventSets.map((x) => x.id === set.id
                               ? { ...x, highlight: e.target.checked } : x))} />
                    </td>
                    <td>
                      <button type="button" className="btn quiet" aria-label={`Remove ${set.label}`}
                              onClick={() => setEventSets(eventSets.filter((x) => x.id !== set.id))}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {draft && (
            <div className="card" data-testid="series-new-plot" style={{ marginTop: 6, padding: 8 }}>
              <label className="field">
                <span className="field-label">Input plot</span>
                <select aria-label="Input plot" value={draft.parent}
                        onChange={(e) => setDraft({ ...draft, parent: e.target.value })}>
                  {plots.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </label>
              {draft.eventStats ? (
                <div className="row-actions" data-testid="series-event-statistics">
                  {searchSets.length === 0 ? (
                    <span className="field-hint">Add an event set first: its events are what this aggregates over.</span>
                  ) : (
                    <>
                      <select aria-label="Statistic" value={draft.eventStats.aggregate}
                              onChange={(e) => setDraft({ ...draft, eventStats: { ...draft.eventStats!,
                                aggregate: e.target.value as "sum" | "avg" | "min" | "max" | "count" | "stddev" } })}>
                        {SERIES_WINDOW_AGGREGATES.map((a) => <option key={a} value={a}>{a}</option>)}
                      </select>
                      <span className="field-hint">per event of</span>
                      <select aria-label="Event set" value={draft.eventStats.set}
                              onChange={(e) => setDraft({ ...draft, eventStats: { ...draft.eventStats!,
                                set: e.target.value } })}>
                        {searchSets.map((set) => <option key={set.id} value={set.id}>{set.label}</option>)}
                      </select>
                    </>
                  )}
                </div>
              ) : draft.combine ? (
                <div className="row-actions" data-testid="series-combine" style={{ flexWrap: "wrap" }}>
                  <select aria-label="Combine by" value={draft.combine.aggregate}
                          onChange={(e) => setDraft({ ...draft, combine: { ...draft.combine!,
                            aggregate: e.target.value as "avg" | "min" | "max" | "sum" } })}>
                    {COMBINE_AGGREGATES.map((a) => (
                      <option key={a} value={a}>
                        {draft.combine!.kind === "combine" ? `${COMBINE_WORDS[a]} where they meet` : COMBINE_WORDS[a]}
                      </option>
                    ))}
                  </select>
                  {plots.filter((p) => p.id !== draft.parent).map((p) => (
                    <label key={p.id} className="field canvas-toggle">
                      <input type="checkbox" aria-label={`Combine with ${p.label}`}
                             checked={draft.combine!.others.includes(p.id)}
                             disabled={!draft.combine!.others.includes(p.id)
                               && draft.combine!.others.length >= MAX_SERIES_COMBINED}
                             onChange={(e) => setDraft({ ...draft, combine: { ...draft.combine!,
                               others: e.target.checked
                                 ? [...draft.combine!.others, p.id]
                                 : draft.combine!.others.filter((o) => o !== p.id) } })} />
                      <span className="field-label">{p.label}</span>
                    </label>
                  ))}
                </div>
              ) : draft.bands ? (
                <div className="row-actions" data-testid="series-bands">
                  <input type="number" min={1} aria-label="Bands window" value={draft.bands.window}
                         onChange={(e) => setDraft({ ...draft,
                           bands: { ...draft.bands!, window: Number(e.target.value) } })} />
                  <select aria-label="Bands unit" value={draft.bands.unit}
                          onChange={(e) => setDraft({ ...draft,
                            bands: { ...draft.bands!, unit: e.target.value as TimeUnit } })}>
                    {TIME_UNITS.map((u) => <option key={u} value={u}>{`${u}s`}</option>)}
                  </select>
                  <input type="number" min={0.1} step={0.5} aria-label="Bands deviations"
                         value={draft.bands.deviations}
                         onChange={(e) => setDraft({ ...draft,
                           bands: { ...draft.bands!, deviations: Number(e.target.value) } })} />
                  <span className="field-hint">standard deviations either side</span>
                  {seriesBandsProblem(draft.bands) && (
                    <span className="field-hint">{seriesBandsProblem(draft.bands)}</span>
                  )}
                </div>
              ) : (
                <SeriesTransformsEditor transforms={draft.transforms} readOnly={false}
                  onChange={(next) => setDraft({ ...draft, transforms: next })} />
              )}
              <div className="row-actions">
                <button type="button" className="btn"
                        disabled={draft.eventStats ? !searchSets.some((x) => x.id === draft.eventStats!.set)
                          : draft.combine ? draft.combine.others.length === 0
                          : draft.bands ? !!seriesBandsProblem(draft.bands)
                          : draft.transforms.length === 0 || !!seriesTransformsProblem(draft.transforms)}
                        onClick={() => {
                          const parent = plots.find((p) => p.id === draft.parent);
                          const canvas = seriesCanvasFor(placement, parent?.canvas ?? 1, canvases);
                          setPlots(draft.eventStats
                            ? withSeriesEventStatistics(plots, draft.parent,
                              searchSets.find((x) => x.id === draft.eventStats!.set),
                              draft.eventStats.aggregate, canvas)
                            : draft.combine
                            ? withSeriesCombined(plots, draft.parent, draft.combine.others,
                              draft.combine.aggregate, canvas, draft.combine.kind)
                            : draft.bands
                            ? withSeriesBands(plots, draft.parent, draft.bands, canvas)
                            : withSeriesDerived(plots, draft.parent, draft.transforms,
                              canvas));
                          setDraft(null);
                        }}>
                  Add plot
                </button>
                <button type="button" className="btn quiet" onClick={() => setDraft(null)}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

CanvasSeriesAnalysis.craft = {
  displayName: "Time series analysis",
  props: { objectSetVariable: null, property: null, labelProperty: null, limit: 5, title: "",
    plotTypes: null, eventSetTypes: null, newPlotCanvas: "input", eventSets: null, viewRange: "full",
    windowStartVariable: null, windowEndVariable: null, relativeAmount: 2, relativeUnit: "week",
    syncXAxes: false, utc: false, overlayYAxes: false, collapseYAxes: false, collapsedBoundaries: false,
    tooltip: null, addData: false, addDataSets: null, saving: false, saveProjectVariable: null,
    fixedSaveLocation: false, outputVariable: null, autoloadVariable: null, keepOnLoad: false },
  related: { settings: settingsPanel("SeriesAnalysisSettings") },
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
  const { workspaceId, projectId, mode } = useCanvasEnv();
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
  // An embedded module is a module, and p.207 says nothing about which door
  // a reader came through. Its *own* table, not the host's: the two are
  // separate documents translated by separate people.
  const layout = definition ? readerLayout(definition) : null;
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

  // p.165's second paragraph:
  //
  // > "In edit mode, when you open a module from a module reference (for
  // > example, opening an embedded child module in its own editor), the module
  // > opens with the current values of any module interface variables that were
  // > passed from the source module. This allows you to debug the opened module
  // > using the same state that was present where it was referenced."
  //
  // **The same query §242's event builds**, from the same function - which is
  // the whole reason this row is a link rather than a feature. `mapping` is
  // already keyed the way `interfaceQuery` wants (child external ID -> host
  // variable id), and the values are the host's, laid over the same way the
  // event lays them: what is on screen now, not what the server last resolved.
  //
  // **Edit mode only**, because p.165 says so and because it is a debugging
  // affordance: a viewer has no editor to be sent to, and a link into one from
  // a published module would be an invitation to a page they cannot open.
  const debugQuery = interfaceQuery(mapping, {
    ...host.resolved, ...hostParams.values,
  });
  const debugSearch = new URLSearchParams(debugQuery).toString();
  const childResource = embedded.data?.resource_id ?? null;

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
      {mode === "edit" && childResource && (
        // Below the title and above the module, where it reads as being about
        // the embed rather than about anything inside it.
        <a
          className="slug"
          data-testid="embed-open-child"
          href={`/r/${childResource}${debugSearch ? `?${debugSearch}` : ""}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open {embedded.data?.name ?? "this module"} in its own editor
          {debugSearch ? " with these values" : ""}
        </a>
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
              // p.75's last sentence (§393): "This behavior is the same for
              // non-visible variables used in embedded modules." The child is
              // a module with its own pages, its own current page and its own
              // bridge, so the rule is the same rule over the child's own
              // document rather than a second one.
              layout={layout}
              // Run mode only, and for the host's reason rather than by
              // analogy with it: the child inherits the host's mode, and in
              // edit mode `CanvasPage` renders every page - so inside the
              // host's editor every page of the child is on screen too.
              lazy={mode === "run"}
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

CanvasEmbeddedModule.craft = {
  displayName: "Embedded module",
  props: { moduleId: null, title: "", interface: {} },
  related: { settings: settingsPanel("EmbeddedModuleSettings") },
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
 * **p.132's property sorts are offered as of §231.** This paragraph used to say
 * they were not, "and that is decision 0006 rather than an omission" — which was
 * true when it was written and false from §221, one of the six copies of that
 * refusal `STATUS.md` §230 found still standing. p.132's other sentence still
 * holds and now matters more: Foundry "applies a primary key sort behind any
 * user configured sorts to ensure a consistent ordering", which is exactly what
 * §225 appends in `_order_by`, so a loop ordered by a property with five
 * distinct values still pages without repeating or skipping an object.
 *
 * **Only the object-set arm.** p.133 orders the array arm "by the entry's
 * position in the array", which is the array's own order — there is nothing to
 * sort by and no request to put a sort on.
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
  sort = "",
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
  /** p.132's property sorts. Blank is the set's own order, which is what every
   * module saved before §231 has and must keep having. */
  sort?: string;
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
  // p.133's array arm. Its entries are already resolved and in memory, so
  // paging is a slice - see `loop-array.ts` for why position is the key.
  const overArray = source === "array";
  // p.132's property sort needs the looped type's declared properties before it
  // can be sent, for the reason `requestSort` gives; the type comes off the set
  // definition, so no page has to come back first.
  const loopTypeId =
    (definition as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const loopType = useQuery({
    queryKey: ["object-type", loopTypeId],
    queryFn: () => objApi.getType(workspaceId, loopTypeId!),
    enabled: !!loopTypeId && !overArray,
  });
  const page = useSetPage(workspaceId, definition, {
    pageSize: size,
    // **No sort at all when nothing is configured**, which is what every module
    // saved before §231 gets: the fallback is `""`, so `requestSort` returns it
    // and `useSetPage` sends no `sort` key. A default of `recent` here would
    // reorder existing looped layouts on deploy.
    //
    // p.132: "a primary key sort will be applied behind any user configured
    // sorts to ensure a consistent ordering of objects" — which is what §225
    // built into `_order_by`, so this sends the one sort and the server appends
    // the tie-break that makes the page stable.
    sort: sortOfLoop(sort, loopType.data ? (loopType.data.properties ?? []) : undefined),
    variablesPending: host.pending,
  });

  const [arrayPage, setArrayPage] = useState(0);
  const entries = arrayEntries(overArray ? host.resolved[arrayVariable ?? ""] : undefined);
  const arraySlice = pageOf(entries, { paging, maxItems, pageSize, page: arrayPage });

  const layout = child.data?.definition ? readerLayout(child.data.definition) : null;
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
                  // p.75's other remaining clause (§393): "non-visible pages
                  // of a looped layout". A Loop is one embedded module per
                  // row (p.129), each with its own variable scope and layout
                  // state, so a row's non-visible pages are an embedded
                  // module's non-visible pages and the same wiring answers
                  // both. A row the loop is not showing is not mounted at all,
                  // so it never had a bridge to be lazy about.
                  layout={layout}
                  lazy={mode === "run"}
                >
                  {/* p.181 (§679): display optimization is not supported in a
                      loop layout, so the repeated module's widgets take the
                      defaults. */}
                  <InLoop.Provider value={true}>
                    <Editor resolver={CANVAS_RESOLVER} enabled={false} onRender={CanvasNode}>
                      <Frame data={JSON.stringify(layout)} />
                    </Editor>
                  </InLoop.Provider>
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

CanvasLoopSection.craft = {
  displayName: "Loop",
  props: {
    source: "object_set", arrayVariable: null,
    objectSetVariable: null, moduleId: null, itemVariable: null, interface: {},
    paging: "limit", maxItems: 12, pageSize: 12,
    display: "list", maxColumns: 3, minCardWidth: 220,
    // Blank, not `recent`: a new Loop and every Loop saved before §231 both mean
    // "the set's own order", and a default here would be a setting nobody chose.
    sort: "",
  },
  related: { settings: settingsPanel("LoopSectionSettings") },
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
  areaVariable = null,
  trackProperty = null,
  enableTimeline = false,
  selectedTimeVariable = null,
  windowStartVariable = null,
  windowEndVariable = null,
  timeZone = "utc",
  timeFormat = "local",
  allowTimeChange = true,
  liveModeToggle = true,
  openTimelineByDefault = true,
  playingVariable = null,
  playbackPositionVariable = null,
  autoPauseVariable = null,
  layerLabel = "",
  selectedVariable = null,
  layerVisible = true,
  layerVisibleVariable = null,
  lockLayer = false,
  layerColor = null,
  layerOpacity = 1,
  drawOptions = null,
  drawnShapeColor = null,
  drawnShapeOpacity = DRAWN_OPACITY,
  singleDrawMode,
  drawnShapesVariable = null,
  selectedShapesVariable = null,
  shapeOutputType = "features",
  enableMeasurements = false,
  measurePerimeter = true,
  perimeterMode = "total",
  measureArea = true,
  measureLine = true,
  lineMode = "total",
  showLegend = false,
  legendCollapsed = false,
  legendSize = "full",
  showSelectionPanel = false,
  autoZoom = "default",
  autoZoomSetVariable = null,
  autoZoomOutsideOnly = false,
  boundsVariable = null,
  followSetVariable = null,
  layers = null,
  geometries = null,
  layerInLegend = true,
  enableSearchAround = false,
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
  /** p.302's shape-based selection (§550): the array a drawn area is written
   * into as a `within_box` on the location property (a `within_polygon` or a
   * `within_distance` for §571's shape and §572's circle), for a `narrow_set`
   * to read (`map-area.ts`). */
  areaVariable?: string | null;
  /** p.301's Draw options, Drawn shape colors and Drawn shape opacity
   * (§573): the drawing tools offered (null for all three), and the colour
   * and fill opacity of what is drawn. */
  drawOptions?: string[] | null;
  drawnShapeColor?: string | null;
  drawnShapeOpacity?: number;
  /** p.301's Enable single draw mode (§640): one shape at a time, "removing
   * the previous shape when a new one is drawn". On unless set false, which
   * is how a map saved before the choice behaved; off, the shapes drawn
   * select the objects inside any of them (§639's `within_any`). */
  singleDrawMode?: boolean;
  /** p.301's Drawn shapes and Shape output type (§574): a string variable
   * the drawn shape is read from and written to as GeoJSON, as features or
   * as geometries (`map-drawn.ts`). */
  drawnShapesVariable?: string | null;
  /** p.301's Selected shapes (§641): a string variable the drawn shapes
   * clicked are written to as GeoJSON, in the same output type, and read
   * back from. */
  selectedShapesVariable?: string | null;
  shapeOutputType?: string;
  /** p.302's Enable measurements, Enable polygon perimeter (by segment or in
   * total) and Enable polygon area (§575, `map-measure.ts`). */
  enableMeasurements?: boolean;
  measurePerimeter?: boolean;
  perimeterMode?: string;
  measureArea?: boolean;
  /** p.302's Enable line measurements (§634): segments or the total. */
  measureLine?: boolean;
  lineMode?: string;
  /** A `geotemporal_series` property (§557): each object's track drawn as a
   * line, and the object at its position at the selected time. */
  trackProperty?: string | null;
  /** p.303's Enable timeline. */
  enableTimeline?: boolean;
  /** p.303's Selected time: a timestamp or date variable, read and written. */
  selectedTimeVariable?: string | null;
  /** p.303's Time window, as two timestamp or date variables (§558). */
  windowStartVariable?: string | null;
  windowEndVariable?: string | null;
  /** p.303's Time zone, and for Local its Time format. */
  timeZone?: string;
  timeFormat?: string;
  /** p.303's Allow user to change selected time, Enable user facing live
   * mode toggle and Open timeline by default (§576). */
  allowTimeChange?: boolean;
  liveModeToggle?: boolean;
  openTimelineByDefault?: boolean;
  /** p.303's Playback state (a boolean variable), Playback position (a
   * number variable written with the time in milliseconds) and Auto pause at
   * (a timestamp array variable). */
  playingVariable?: string | null;
  playbackPositionVariable?: string | null;
  autoPauseVariable?: string | null;
  /** p.300's layer settings (§559, `map-layer.ts`): its Label; its Selected
   * objects, an array variable of clauses, read and written; its Layer
   * visibility, static or from a boolean variable; Lock layer; and Style's
   * colour and opacity. */
  layerLabel?: string;
  selectedVariable?: string | null;
  layerVisible?: boolean;
  layerVisibleVariable?: string | null;
  lockLayer?: boolean;
  layerColor?: string | null;
  layerOpacity?: number;
  /** p.304's interface options (§560, `map-view.ts`): the Legend panel, its
   * starting state and size; the Selection panel; Viewport auto zoom (all
   * objects, or an object set's, optionally only when they are out of view);
   * Viewport bounds, a GeoJSON string variable read and written; and
   * Viewport follow object set. */
  showLegend?: boolean;
  legendCollapsed?: boolean;
  legendSize?: string;
  showSelectionPanel?: boolean;
  autoZoom?: string;
  autoZoomSetVariable?: string | null;
  autoZoomOutsideOnly?: boolean;
  boundsVariable?: string | null;
  followSetVariable?: string | null;
  /** p.300's Add object layer (§642, `map-layer.ts`): the layers after the
   * map's own, each with its own object set and settings. */
  layers?: unknown;
  /** p.300's Geometry (§670, `map-geometry.ts`): the map's own layer's
   * geoshape properties, drawn as shapes. */
  geometries?: unknown;
  /** p.300's Legend visibility for the map's own layer. */
  layerInLegend?: boolean;
  /** p.303's Enable search around (§734, `map-search-around.ts`): from the
   * toolbar and a pin's context menu, each result a layer of its own. */
  enableSearchAround?: boolean;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const { set: setParameter, values: parameterValues } = useCanvasParameters();
  // Read back from the variable it writes, as a Filter List's clauses are:
  // the area on the map is the one the document holds.
  const areaWritten = useCanvasParameter(areaVariable);
  const areaResolved = useCanvasVariable(areaVariable);
  const areaClauses = clausesOf(areaWritten !== undefined ? areaWritten : areaResolved);
  const selectsArea = source === "objects" && !!objectSetVariable && !!areaVariable
    && !!locationProperty;
  const mapAreas = selectsArea ? mapAreasOf(areaClauses, locationProperty!) : [];
  const single = singleDrawOf(singleDrawMode);
  // p.301's Drawn shapes (§574): the area as GeoJSON, read and written, and
  // whichever of the two moved since the map last looked wins.
  const shapesWritten = useCanvasParameter(drawnShapesVariable);
  const shapesResolved = useCanvasVariable(drawnShapesVariable);
  const shapesNow = String((shapesWritten !== undefined ? shapesWritten : shapesResolved) ?? "");
  const shapeOutput = shapeOutputOf(shapeOutputType);
  const shapesSeen = React.useRef<{ area: string; shapes: string } | null>(null);
  // p.301's drawn line (§634): in the Drawn shapes text where there is one,
  // and held here where there is not.
  const [localLine, setLocalLine] = useState<DrawnLine | null>(null);
  const drawnLine = drawnShapesVariable ? lineOfShapes(shapesNow) : localLine;
  // p.301's Selected shapes (§641): read back from the variable each render,
  // so text written there selects the drawn shapes it names.
  const shapesPicked = useCanvasParameter(selectedShapesVariable);
  const shapesPickedResolved = useCanvasVariable(selectedShapesVariable);
  const selectedAreas = selectedShapesVariable
    ? selectedIn(mapAreas, shapesPicked !== undefined ? shapesPicked : shapesPickedResolved,
      shapeOutput)
    : [];
  React.useEffect(() => {
    if (!selectsArea || !drawnShapesVariable) {
      shapesSeen.current = null;
      return;
    }
    const sync = syncShapes(shapesSeen.current, { areas: mapAreas, shapes: shapesNow }, shapeOutput,
      single);
    shapesSeen.current = { area: shapesText(mapAreas, shapeOutput), shapes: shapesNow };
    if (sync?.write === "area") {
      setParameter(areaVariable!, withMapAreas(areaClauses, locationProperty!, sync.areas));
    } else if (sync?.write === "shapes") {
      setParameter(drawnShapesVariable, sync.text);
    }
  });
  const searchValue = useCanvasParameter(searchParameter);
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending, events: moduleEvents, resolved: resolvedVariables } =
    useCanvasVariables();
  const eventContext = useEventContext(undefined, useOverlayIds());
  const usingSet = source === "objects" && !!objectSetVariable;

  const setPage = useQuery({
    queryKey: ["canvas-map-set", objectSetVariable, JSON.stringify(setDefinition ?? null), limit],
    queryFn: () =>
      objApi.evaluateObjectSet(workspaceId, setDefinition, { limit: Math.min(limit, 200) }),
    enabled: usingSet && !!setDefinition,
  });
  // p.303's timeline over tracks (§557): the same page of objects' tracks in
  // one read, and the time they are shown at - a variable's when one is
  // bound, the viewer's own otherwise, and none ("View latest") to start.
  const tracking = usingSet && !!trackProperty;
  const tracksPage = useQuery({
    queryKey: ["canvas-map-tracks", JSON.stringify(setDefinition ?? null), trackProperty, limit],
    queryFn: () => objApi.objectSetTracks(workspaceId, setDefinition, trackProperty!,
      { limit: Math.min(limit, 200) }),
    enabled: tracking && !!setDefinition,
  });
  // p.303's Time window (§558): the tracks as they were inside it.
  const windowStartWritten = useCanvasParameter(windowStartVariable);
  const windowStartResolved = useCanvasVariable(windowStartVariable);
  const windowEndWritten = useCanvasParameter(windowEndVariable);
  const windowEndResolved = useCanvasVariable(windowEndVariable);
  const timeWindow = windowOf(
    windowStartWritten !== undefined ? windowStartWritten : windowStartResolved,
    windowEndWritten !== undefined ? windowEndWritten : windowEndResolved,
  );
  const tracksByKey = React.useMemo(() => new Map(
    (tracksPage.data?.rows ?? []).map((row) => [row.primary_key, withinWindow(row.points, timeWindow)])),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [tracksPage.data, timeWindow.start, timeWindow.end]);
  const writtenTime = useCanvasParameter(selectedTimeVariable);
  const resolvedTime = useCanvasVariable(selectedTimeVariable);
  const [ownTime, setOwnTime] = useState<number | null>(null);
  const selectedTime = selectedTimeVariable
    ? selectedTimeOf(writtenTime !== undefined ? writtenTime : resolvedTime)
    : ownTime;
  const selectTime = (ms: number | null) => {
    if (selectedTimeVariable) setParameter(selectedTimeVariable, ms === null ? null : selectedTimeText(ms));
    else setOwnTime(ms);
    // p.303's Playback position: "the current playback time (in
    // milliseconds) as a numeric variable".
    if (playbackPositionVariable && ms !== null) setParameter(playbackPositionVariable, ms);
  };
  // p.303's Playback state: a boolean variable's when one is bound.
  const playingWritten = useCanvasParameter(playingVariable);
  const playingResolved = useCanvasVariable(playingVariable);
  const [ownPlaying, setOwnPlaying] = useState(false);
  // p.303's timeline open button (§576): open to start unless the map says.
  const [timelineOpen, setTimelineOpen] = useState(openTimelineByDefault !== false);
  const playing = playingVariable
    ? (playingWritten !== undefined ? playingWritten : playingResolved) === true
    : ownPlaying;
  const setPlaying = (next: boolean) => {
    if (playingVariable) setParameter(playingVariable, next);
    else setOwnPlaying(next);
  };
  const pauseWritten = useCanvasParameter(autoPauseVariable);
  const pauseResolved = useCanvasVariable(autoPauseVariable);
  const pauses = pausesOf(pauseWritten !== undefined ? pauseWritten : pauseResolved);
  // p.300's Selected objects (§559): the clause list in its variable is the
  // selection, as for the Object Table - "bidirectional", so anything that
  // writes it moves the selection here.
  const selectedWritten = useCanvasParameter(selectedVariable);
  const selectedResolved = useCanvasVariable(selectedVariable);
  const selectedClauses = selectedWritten !== undefined ? selectedWritten : selectedResolved;
  const selectedKeys = new Set(keysOf(selectedClauses));
  const visibleWritten = useCanvasParameter(layerVisibleVariable);
  const visibleResolved = useCanvasVariable(layerVisibleVariable);
  const layerShown = layerVisibleOf(layerVisible,
    visibleWritten !== undefined ? visibleWritten : visibleResolved, !!layerVisibleVariable);
  // Written as "none selected" once, so a set narrowed by it is empty rather
  // than everything until somebody clicks - the Object Table's rule (§207).
  // Only once the variable has resolved: a default the document gives it is
  // a selection already, and written over before it arrived it would be lost.
  const selectionStated = hasSelection(selectedWritten) || hasSelection(selectedResolved);
  React.useEffect(() => {
    if (selectedVariable && !variablesPending && selectedResolved !== undefined
        && !selectionStated) {
      setParameter(selectedVariable, selectionClauses([]));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedVariable, variablesPending, selectedResolved === undefined, selectionStated]);

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
        // Workshop's, like the other widget read above (§320).
        application: "workshop",
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

  const { points, unplaceable, notYet } = React.useMemo(() => {
    const collected: MapPoint[] = [];
    let bad = 0;
    let later = 0;
    if (source === "objects") {
      for (const instance of (usingSet ? setPage.data?.instances : objectPage.data?.items) ?? []) {
        // A tracked object stands where its track puts it at the selected
        // time; one with no fix by then is not on the map yet (§557).
        const track = tracking ? tracksByKey.get(String(instance.primary_key)) : undefined;
        const fix = track ? positionAt(track, selectedTime) : null;
        if (track && !fix) {
          later += 1;
          continue;
        }
        const at = fix ? { lat: fix.lat, lon: fix.lon }
          : locationProperty ? toLatLon(instance.properties[locationProperty]) : null;
        if (!at) {
          // A layer of shapes alone (§670) has no pins, rather than every
          // object counted as one with nowhere to stand.
          if (locationProperty) bad += 1;
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
    return { points: collected, unplaceable: bad, notYet: later };
  }, [source, usingSet, setPage.data, objectPage.data, datasetRows.data,
      locationProperty, labelProperty, tracking, tracksByKey, selectedTime]);
  // p.300's added layers (§642): each reads its own set, the way the map's
  // own layer does, and its pins carry its style and selection.
  const addedLayers = usingSet ? layersOf(layers) : [];
  const valueOf = (id: string | null) => !id ? undefined
    : parameterValues[id] !== undefined ? parameterValues[id] : resolvedVariables[id];
  const layerSets = useQueries({
    queries: addedLayers.map((layer) => {
      const definition = layer.objectSetVariable ? resolvedVariables[layer.objectSetVariable] : undefined;
      return {
        queryKey: ["canvas-map-layer", layer.objectSetVariable, JSON.stringify(definition ?? null), limit],
        queryFn: () =>
          objApi.evaluateObjectSet(workspaceId, definition, { limit: Math.min(limit, 200) }),
        enabled: !!definition && (!!layer.locationProperty || layer.geometries.some((g) => !!g.property)),
      };
    }),
  });
  const layerData = addedLayers.map((layer, n) => {
    const keys = new Set(keysOf(valueOf(layer.selectedVariable)));
    const placed = layerPoints(layer, layerSets[n]?.data?.instances ?? [], toLatLon,
      (instance, at, label): MapPoint => ({
        id: `${layer.id}:${instance.id}`, label, instance: instance as MapPoint["instance"], ...at,
        layer: { id: layer.id, color: layer.color, opacity: layer.opacity,
          selected: keys.has(String(instance.primary_key)), locked: layer.locked },
      }));
    // p.300's geometries (§670): each a geoshape property drawn as shapes.
    const shapes = layer.geometries.map((geometry) => ({
      geometry,
      shapes: geometryShapes(layer.id, geometry, layerSets[n]?.data?.instances ?? [], layer.labelProperty,
        layer.color),
    }));
    return {
      layer, keys, ...placed, shapes,
      shown: layerVisibleOf(layer.visible, valueOf(layer.visibleVariable), !!layer.visibleVariable),
    };
  });
  const layerPins = layerData.flatMap((d) => (d.shown ? d.points : []));
  const layerShapes = layerData.flatMap((d) => (d.shown ? d.shapes.flatMap((s) => s.shapes) : []));
  // The map's own layer's geometries (§670).
  const ownGeometries = usingSet ? geometriesOf(geometries).map((geometry) => ({
    geometry,
    shapes: geometryShapes("layer-1", geometry, setPage.data?.instances ?? [], labelProperty,
      layerColorOf(layerColor)),
  })) : [];
  const ownShapes = ownGeometries.flatMap((g) => g.shapes);
  // Each layer's Selected objects written as "none selected" once, for the
  // map's own layer's reason below.
  const unstatedLayers = addedLayers.filter((l) => l.selectedVariable
    && resolvedVariables[l.selectedVariable] !== undefined
    && !hasSelection(parameterValues[l.selectedVariable])
    && !hasSelection(resolvedVariables[l.selectedVariable]))
    .map((l) => l.selectedVariable!).join("\n");
  React.useEffect(() => {
    if (variablesPending || !unstatedLayers) return;
    for (const id of unstatedLayers.split("\n")) setParameter(id, selectionClauses([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variablesPending, unstatedLayers]);
  const selectLayerPin = (point: MapPoint) => {
    const found = layerData.find((d) => d.layer.id === point.layer?.id);
    // A locked layer's pins are not clickable at all (`MapCanvas`), so the
    // lock needs no check here (one survived the sweep as equivalent).
    if (!found || !found.layer.selectedVariable || !point.instance) return;
    setParameter(found.layer.selectedVariable,
      selectionClauses(toggleKey([...found.keys], String(point.instance.primary_key))));
  };
  // p.303's search around (§734, `map-search-around.ts`): from the toolbar or
  // a pin's context menu, each result drawn as a layer of its own until it is
  // removed. Held by the widget, as a viewer's own exploration is: p.303
  // gives it no variable to write.
  const searchAround = usingSet && searchAroundOf(enableSearchAround);
  const [searchStart, setSearchStart] = useState<SearchStart | null>(null);
  const [pinMenu, setPinMenu] = useState<{ x: number; y: number; start: SearchStart } | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const searchSerial = React.useRef(0);
  const resultSets = useQueries({
    queries: searchResults.map((result) => ({
      queryKey: ["canvas-map-search-around", JSON.stringify(result.definition), limit],
      queryFn: () => objApi.evaluateObjectSet(workspaceId, result.definition,
        { limit: Math.min(limit, 200) }),
      // A refusal (a traversal past the server's depth) is an answer, not a
      // blip to retry.
      retry: false,
    })),
  });
  const resultData = searchResults.map((result, n) => {
    const read = resultSets[n];
    const pins: MapPoint[] = [];
    let unplaced = 0;
    for (const instance of read?.data?.instances ?? []) {
      const at = toLatLon(instance.properties[result.locationProperty]);
      if (!at) {
        unplaced += 1;
        continue;
      }
      const label = result.labelProperty ? instance.properties[result.labelProperty] : null;
      pins.push({
        id: `${result.id}:${instance.id}`,
        label: label === null || label === undefined ? String(instance.primary_key) : String(label),
        instance: instance as MapPoint["instance"],
        ...at,
        // Locked: a result has no Selected objects to write a click into.
        layer: { id: result.id, color: result.color, opacity: 1, selected: false, locked: true },
      });
    }
    return { result, pins, unplaced, total: read?.data?.total, error: read?.error ?? null,
      pending: !!read?.isPending };
  });
  const resultPins = resultData.flatMap((d) => d.pins);
  // A pin's type, for its context menu: the map's own layer's, an added
  // layer's set's, or the type a search around arrived at.
  const typeOfPin = (point: MapPoint): string | null => {
    if (!point.layer) {
      return typeof (setDefinition as { object_type_id?: unknown } | undefined)?.object_type_id === "string"
        ? (setDefinition as { object_type_id: string }).object_type_id : null;
    }
    const result = searchResults.find((r) => r.id === point.layer!.id);
    if (result) return result.typeId;
    const layer = addedLayers.find((l) => l.id === point.layer!.id);
    const definition = layer?.objectSetVariable ? resolvedVariables[layer.objectSetVariable] : undefined;
    const typeId = (definition as { object_type_id?: unknown } | undefined)?.object_type_id;
    return typeof typeId === "string" ? typeId : null;
  };
  const ownStart = searchAround
    ? toolbarStart(setDefinition, selectedVariable ? [...selectedKeys] : [], layerLabel ?? "")
    : null;
  React.useEffect(() => {
    if (!pinMenu) return;
    const close = () => setPinMenu(null);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", onKey);
    };
  }, [pinMenu]);
  // p.302's "map breadcrumbs": each track as a line under the pins.
  const trackShapes: MapShape[] = tracking
    ? (setPage.data?.instances ?? []).flatMap((instance) => {
        const line = trackShape(tracksByKey.get(String(instance.primary_key)) ?? []);
        const label = labelProperty ? instance.properties[labelProperty] : null;
        return line ? [{
          id: `track-${instance.id}`,
          label: label === null || label === undefined ? String(instance.primary_key) : String(label),
          value: line,
        }] : [];
      })
    : [];
  const timeSpan = tracking ? timelineSpan(extentOf([...tracksByKey.values()]), timeWindow) : null;
  // p.304's viewport (§560). The objects to fit: an object set followed, or
  // the auto-zoom target - all the objects, or an object set's - each as the
  // pins it has on this map.
  const targetSetVariable = followSetVariable
    ?? (autoZoom === "set" ? autoZoomSetVariable : null);
  const targetDefinition = useCanvasVariable(targetSetVariable);
  const targetSet = useQuery({
    queryKey: ["canvas-map-target", JSON.stringify(targetDefinition ?? null)],
    queryFn: () => objApi.evaluateObjectSet(workspaceId, targetDefinition, { limit: 200 }),
    enabled: !!targetSetVariable && !!targetDefinition,
  });
  const targetKeys = targetSetVariable
    ? new Set((targetSet.data?.instances ?? []).map((i) => String(i.primary_key)))
    : null;
  const targetPoints = targetKeys
    ? points.filter((p) => targetKeys.has(String(p.instance?.primary_key)))
    : autoZoom === "all" ? points : [];
  const focus = targetPoints.length
    ? {
        key: JSON.stringify(targetPoints.map((p) => [p.id, p.lat, p.lon])),
        points: targetPoints,
        outsideOnly: !followSetVariable && !!autoZoomOutsideOnly,
      }
    : null;
  const boundsWritten = useCanvasParameter(boundsVariable);
  const boundsResolved = useCanvasVariable(boundsVariable);
  // The set's type, for the Selection panel's details: each property by its
  // own name and drawn as its own type.
  const setTypeId = (setDefinition as { object_type_id?: string } | undefined)?.object_type_id;
  const setType = useQuery({
    queryKey: ["object-type", setTypeId],
    queryFn: () => objApi.getType(workspaceId, setTypeId!),
    enabled: showSelectionPanel && !!setTypeId,
  });
  // Playback: a step a tenth of a second, stopping at the end or at the
  // first auto-pause time it crosses. The latest values are read through a
  // ref, so the timer is not restarted on every step it causes.
  const playback = React.useRef({ selectedTime, timeSpan, pauses, selectTime, setPlaying });
  playback.current = { selectedTime, timeSpan, pauses, selectTime, setPlaying };
  React.useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      const now = playback.current;
      if (!now.timeSpan) return;
      const next = nextPlayback(now.selectedTime, now.timeSpan);
      const pause = pauseCrossed(now.selectedTime, next.time, now.pauses);
      now.selectTime(pause ?? next.time);
      if (pause !== null || next.done) now.setPlaying(false);
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing]);

  const needs =
    source === "objects"
      ? usingSet
        ? !locationProperty && !trackProperty && !geometriesOf(geometries).some((g) => g.property)
          ? "pick the geopoint property to plot, or add a geometry" : null
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
  // p.301's On drawn shape (§574): `change`, worded "Shape drawn" on a map.
  const drawEvents = eventsFor(moduleEvents, nodeId, "change");

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
          points={[...(layerShown ? points : []), ...layerPins, ...resultPins]}
          shapes={[...(layerShown ? [...ownShapes, ...trackShapes] : []), ...layerShapes]}
          color={layerColorOf(layerColor)}
          opacity={layerOpacityOf(layerOpacity)}
          selectedKeys={selectedVariable ? selectedKeys : undefined}
          layerLabel={layerLabel}
          focus={focus}
          bounds={boundsVariable
            ? (boundsWritten !== undefined ? boundsWritten : boundsResolved) : undefined}
          onBounds={boundsVariable
            ? (text) => setParameter(boundsVariable, text) : undefined}
          legend={showLegend ? {
            collapsed: !!legendCollapsed,
            compact: legendSize === "compact",
            entries: [
              // p.300's Legend visibility (§670): a layer, or one geometry,
              // left out of the legend is still drawn.
              ...(layerShown && layerInLegend !== false ? [
                ...(locationProperty || tracking ? [{ label: layerLabel || "Objects", kind: "points" as const,
                  color: layerColorOf(layerColor) ?? "var(--accent, #14646e)",
                  count: points.length }] : []),
                ...(trackShapes.length ? [{ label: `${layerLabel || "Objects"} tracks`,
                  kind: "track" as const, color: layerColorOf(layerColor) ?? "var(--accent, #14646e)",
                  count: trackShapes.length }] : []),
                ...geometryLegend(layerLabel || "Objects", ownGeometries, layerColorOf(layerColor)),
              ] : []),
              ...layerData.filter((d) => d.shown && d.layer.inLegend).flatMap((d) => [
                ...(d.layer.locationProperty ? [{
                  label: d.layer.label || "Objects", kind: "points" as const,
                  color: d.layer.color ?? "var(--accent, #14646e)", count: d.points.length }] : []),
                ...geometryLegend(d.layer.label || "Objects", d.shapes, d.layer.color),
              ]),
              ...resultData.map((d) => ({ label: d.result.label, kind: "points" as const,
                color: d.result.color, count: d.pins.length })),
            ],
          } : null}
          areas={mapAreas}
          selectedAreas={selectedAreas}
          onSelectArea={selectsArea && selectedShapesVariable
            ? (at) => setParameter(selectedShapesVariable,
              selectedText(mapAreas, toggledShape(selectedAreas, at), shapeOutput))
            : undefined}
          drawTools={drawToolsOf(drawOptions)}
          drawnColor={layerColorOf(drawnShapeColor)}
          drawnOpacity={drawnOpacityOf(drawnShapeOpacity)}
          measure={enableMeasurements ? {
            perimeter: measurePerimeter ? perimeterModeOf(perimeterMode) : null,
            line: measureLine !== false ? perimeterModeOf(lineMode) : null,
            area: !!measureArea,
          } : null}
          line={drawnLine}
          onLine={selectsArea || drawnShapesVariable
            ? (line) => {
                // A line replaces the areas, which a line cannot be one of:
                // the Drawn shapes text holds areas or a line, not both.
                if (selectsArea && mapAreas.length > 0) {
                  setParameter(areaVariable!, withMapAreas(areaClauses, locationProperty!, []));
                }
                const text = lineText(line, shapeOutput);
                if (drawnShapesVariable) setParameter(drawnShapesVariable, text);
                else setLocalLine(line);
                if (line && drawEvents.length > 0) {
                  runEvents(drawEvents, { ...eventContext, payload: { value: text } });
                }
              }
            : undefined}
          onArea={selectsArea
            ? (area) => {
                setLocalLine(null);
                // p.301's single draw mode (§640): the new shape replaces the
                // last, or out of it joins the rest. Clearing clears them all.
                const next = area ? withDrawn(mapAreas, area, single) : [];
                // A selected shape that is no longer drawn is no longer
                // selected: cleared, or replaced in single draw mode.
                if (selectedShapesVariable && selectedAreas.length > 0) {
                  const kept = selectedAreas.map((at) => mapAreas[at]!).filter((a) => next.includes(a));
                  setParameter(selectedShapesVariable, shapesText(kept, shapeOutput));
                }
                // The Drawn shapes text follows by the sync above, the area
                // having moved (writing it here too survived the sweep as
                // equivalent).
                setParameter(areaVariable!, withMapAreas(areaClauses, locationProperty!, next));
                // Drawn, not cleared: `{{value}}` is the drawn shape's GeoJSON.
                if (area && drawEvents.length > 0) {
                  runEvents(drawEvents, { ...eventContext, payload: { value: shapesText(area, shapeOutput) } });
                }
              }
            : undefined}
          unplaceable={unplaceable + layerData.reduce((n, d) => n + (d.shown ? d.unplaceable : 0), 0)
            + resultData.reduce((n, d) => n + d.unplaced, 0)}
          onPinMenu={searchAround ? (point, at) => {
            const typeId = typeOfPin(point);
            if (!typeId || !point.instance) return;
            setPinMenu({ ...at, start: pinStart(typeId, String(point.instance.primary_key), point.label) });
          } : undefined}
          tools={searchAround ? (
            <button
              type="button"
              data-testid="map-search-around"
              disabled={!ownStart}
              aria-expanded={searchStart !== null}
              title={ownStart
                ? `Follow a link from ${ownStart.label === (layerLabel?.trim() || "Objects")
                  ? "every object on the layer" : `the ${ownStart.label}`}`
                : "The map's object set is not over one object type"}
              onClick={() => setSearchStart(searchStart ? null : ownStart)}
            >
              Search around
            </button>
          ) : null}
          notYet={notYet}
          total={
            source === "objects"
              ? (usingSet ? setPage.data?.total : objectPage.data?.total)
              : undefined
          }
          atLimit={
            source === "dataset" && (datasetRows.data?.rows.length ?? 0) >= (limit ?? 500)
          }
          onSelect={
            // p.300: "Objects in locked layers cannot be selected by users".
            // An added layer's pin selects into its own layer (§642).
            (lockLayer || !(selectedVariable || pinEvents.length > 0))
              && !addedLayers.some((l) => !l.locked && l.selectedVariable) ? undefined
              : (point) => {
                  if (point.layer) {
                    selectLayerPin(point);
                    return;
                  }
                  if (lockLayer) return;
                  if (selectedVariable && point.instance) {
                    setParameter(selectedVariable, selectionClauses(
                      toggleKey([...selectedKeys], String(point.instance.primary_key))));
                  }
                  if (pinEvents.length > 0) {
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
                  });
                  }
                }
          }
        />
      )}
      {searchAround && pinMenu && (
        <div
          role="menu"
          className="card"
          data-testid="map-pin-menu"
          style={{ position: "fixed", left: pinMenu.x, top: pinMenu.y, zIndex: 50, padding: 4 }}
        >
          <button
            type="button"
            role="menuitem"
            className="btn quiet"
            data-testid="map-pin-menu-search-around"
            // The menu closes by the document's click listener above, which
            // this click reaches too (closing it here as well survived the
            // sweep as equivalent).
            onClick={() => setSearchStart(pinMenu.start)}
          >
            Search around {pinMenu.start.label}…
          </button>
        </div>
      )}
      {searchAround && searchStart && (
        <MapSearchAroundPanel
          key={JSON.stringify(searchStart.base)}
          workspaceId={workspaceId}
          start={searchStart}
          onCancel={() => setSearchStart(null)}
          onAdd={(link, locationProperty, labelProperty) => {
            const n = searchSerial.current++;
            setSearchResults((now) => [...now, {
              id: `search-${n}`,
              label: resultLabel(searchStart, link),
              typeId: link.far_type_id,
              definition: searchAroundSet(searchStart, link),
              locationProperty,
              labelProperty,
              color: resultColor(n),
            }]);
            setSearchStart(null);
          }}
        />
      )}
      {searchAround && resultData.length > 0 && (
        <ul className="card" data-testid="map-search-results"
          style={{ listStyle: "none", margin: "6px 0 0", padding: "6px 10px" }}>
          {resultData.map((d) => (
            <li key={d.result.id} className="row-actions" style={{ gap: 6 }}
              data-testid="map-search-result">
              <svg width={10} height={10} aria-hidden="true">
                <circle cx={5} cy={5} r={4} fill={d.result.color} />
              </svg>
              <span>{d.result.label}</span>
              <span className="slug" data-testid="map-search-result-count">
                {d.error
                  ? d.error instanceof ApiError ? d.error.message : "Couldn't follow this link."
                  : d.pending ? "Loading…"
                  : `${d.pins.length.toLocaleString()} placed${
                    d.unplaced > 0 ? `, ${d.unplaced.toLocaleString()} without a usable location` : ""}${
                    d.total !== undefined && d.total > d.pins.length + d.unplaced
                      ? `, of ${d.total.toLocaleString()}` : ""}`}
              </span>
              <button
                type="button"
                className="btn quiet"
                data-testid="map-search-result-remove"
                aria-label={`Remove ${d.result.label}`}
                onClick={() => setSearchResults((now) => now.filter((r) => r.id !== d.result.id))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {/* p.304's Selection panel (§560): the selected objects, or the one
          selected object's details. */}
      {!needs && query.data && showSelectionPanel && selectedVariable && (() => {
        const chosen = (setPage.data?.instances ?? [])
          .filter((i) => selectedKeys.has(String(i.primary_key)));
        const nameOf = (i: { primary_key: unknown; properties: Record<string, unknown> }) => {
          const label = labelProperty ? i.properties[labelProperty] : null;
          return label === null || label === undefined ? String(i.primary_key) : String(label);
        };
        return (
          <div className="card" data-testid="map-selection-panel" style={{ marginTop: 6, padding: "6px 10px" }}>
            {chosen.length === 0 ? (
              <span className="canvas-widget-empty">No objects selected</span>
            ) : chosen.length === 1 ? (
              <dl data-testid="map-selection-details" style={{ margin: 0 }}>
                <dt><strong>{nameOf(chosen[0]!)}</strong></dt>
                {(setType.data?.properties ?? []).map((p) => (
                  <dd key={p.api_name} style={{ margin: 0 }} data-testid="map-selection-property">
                    {p.display_name || p.api_name}:{" "}
                    <PropertyValue
                      workspaceId={workspaceId}
                      dataType={p.data_type}
                      valueFormat={p.value_format}
                      structFields={p.struct_fields}
                      value={chosen[0]!.properties[p.api_name]}
                    />
                  </dd>
                ))}
              </dl>
            ) : (
              <ul data-testid="map-selection-list" style={{ margin: 0, paddingLeft: 18 }}>
                {chosen.map((i) => <li key={String(i.primary_key)}>{nameOf(i)}</li>)}
              </ul>
            )}
          </div>
        );
      })()}
      {!needs && query.data && tracking && enableTimeline && timeSpan && (
        <button
          type="button"
          className="btn quiet"
          data-testid="map-timeline-toggle"
          aria-expanded={timelineOpen}
          onClick={() => setTimelineOpen(!timelineOpen)}
          style={{ marginTop: 6 }}
        >
          {timelineOpen ? "Hide timeline" : "Timeline"}
        </button>
      )}
      {!needs && query.data && tracking && enableTimeline && timeSpan && timelineOpen && (
        <MapTimeline
          controls={timelineControls(allowTimeChange, liveModeToggle)}
          start={timeSpan.start}
          end={timeSpan.end}
          selected={selectedTime}
          onSelect={selectTime}
          playing={playing}
          onPlaying={setPlaying}
          label={(ms) => timeLabel(ms, timeZone === "local" ? "local" : "utc",
            (["12", "24"].includes(timeFormat) ? timeFormat : "local") as TimeFormat)}
        />
      )}
    </div>
  );
}

/** p.303's search around, once started (§734): which link to follow from
 * the start's type, and - when the type arrived at has several - which
 * geopoint its objects stand at. */
function MapSearchAroundPanel({ workspaceId, start, onAdd, onCancel }: {
  workspaceId: string;
  start: SearchStart;
  onAdd: (link: TypeLink, locationProperty: string, labelProperty: string | null) => void;
  onCancel: () => void;
}) {
  const links = useQuery({
    queryKey: ["object-type-links", start.typeId],
    queryFn: () => objApi.typeLinks(workspaceId, start.typeId),
  });
  const offered = searchAroundLinks(links.data ?? [], start.typeId);
  const keyOf = (l: TypeLink) => `${l.link_type_id}:${l.direction}`;
  const [linkKey, setLinkKey] = useState("");
  const chosen = offered.find((l) => keyOf(l) === linkKey) ?? offered[0];
  const far = useQuery({
    queryKey: ["object-type", chosen?.far_type_id],
    queryFn: () => objApi.getType(workspaceId, chosen!.far_type_id),
    enabled: !!chosen,
  });
  const locations = locationProperties(far.data?.properties ?? []);
  const [location, setLocation] = useState("");
  const at = locations.includes(location) ? location : locations[0];
  const title = far.data?.properties?.find((p) => p.id === far.data?.title_property_id)?.api_name ?? null;
  return (
    <div className="card" data-testid="map-search-around-panel" style={{ marginTop: 6, padding: "6px 10px" }}>
      <strong>Search around {start.label}</strong>
      {links.isPending ? (
        <p className="canvas-widget-empty">Loading…</p>
      ) : offered.length === 0 ? (
        <p className="canvas-widget-empty" data-testid="map-search-around-no-links">
          No link types to follow from here.
        </p>
      ) : (
        <>
          <label className="field">
            <span className="field-label">Follow</span>
            <select
              data-testid="map-search-around-link"
              value={chosen ? keyOf(chosen) : ""}
              onChange={(e) => setLinkKey(e.target.value)}
            >
              {offered.map((l) => (
                <option key={keyOf(l)} value={keyOf(l)}>{hopLabel(l)}</option>
              ))}
            </select>
          </label>
          {far.data && locations.length === 0 && (
            <p className="canvas-widget-empty" data-testid="map-search-around-nowhere">
              {far.data.display_name} has no geopoint property, so its objects have nowhere to stand on
              this map.
            </p>
          )}
          {locations.length > 1 && (
            <label className="field">
              <span className="field-label">Place by</span>
              <select
                data-testid="map-search-around-location"
                value={at}
                onChange={(e) => setLocation(e.target.value)}
              >
                {locations.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
          )}
        </>
      )}
      <div className="row-actions" style={{ gap: 6 }}>
        <button
          type="button"
          className="btn"
          data-testid="map-search-around-add"
          disabled={!chosen || !at}
          onClick={() => chosen && at && onAdd(chosen, at, title)}
        >
          Add to map
        </button>
        <button type="button" className="btn quiet" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

/** p.303's timeline panel under the map (§557): a cursor over the tracks'
 * span, and p.303's "View latest" to let it go. */
function MapTimeline({ controls, start, end, selected, onSelect, playing, onPlaying, label }: {
  controls: { cursor: boolean; latest: boolean };
  start: number; end: number; selected: number | null; onSelect: (ms: number | null) => void;
  playing: boolean; onPlaying: (next: boolean) => void; label: (ms: number) => string;
}) {
  return (
    <div className="row-actions" data-testid="map-timeline" style={{ gap: 8, marginTop: 6 }}>
      <button
        type="button"
        className="btn quiet"
        data-testid="map-timeline-play"
        aria-pressed={playing}
        onClick={() => onPlaying(!playing)}
      >
        {playing ? "Pause" : "Play"}
      </button>
      <input
        type="range"
        aria-label="Selected time"
        data-testid="map-timeline-slider"
        min={start}
        max={end}
        step={1000}
        value={selected ?? end}
        disabled={!controls.cursor}
        onChange={(e) => onSelect(Number(e.target.value))}
        style={{ flex: 1 }}
      />
      <span className="slug" data-testid="map-timeline-time">
        {selected === null ? "Latest" : label(selected)}
      </span>
      {controls.latest && (
        <button
          type="button"
          className="btn quiet"
          data-testid="map-timeline-latest"
          disabled={selected === null}
          onClick={() => onSelect(null)}
        >
          View latest
        </button>
      )}
    </div>
  );
}

/** One added layer's settings (§642): p.300's Input and Style for it, the
 * same as the map's own layer has, with its object set and the property its
 * objects stand at. */
/** A layer's geometries as legend entries (§670): each named by its layer
 * and property, and counted, unless p.300's Legend visibility leaves it out. */
function geometryLegend(
  layerLabel: string, geometries: { geometry: MapGeometry; shapes: MapShape[] }[], color: string | null,
) {
  return geometries.filter(({ geometry }) => geometry.legend && geometry.property).map(({ geometry, shapes }) => ({
    label: `${layerLabel} · ${geometry.property}`, kind: "shape" as const,
    color: geometry.color ?? color ?? "var(--accent, #14646e)", count: shapes.length,
  }));
}

CanvasMap.craft = {
  displayName: "Map",
  props: {
    source: "objects",
    objectSetVariable: null, objectTypeId: null, locationProperty: null, labelProperty: null,
    datasetId: null, locationColumn: null, latColumn: null, lonColumn: null, labelColumn: null,
    filterProperty: null, filterColumn: null, filterOperator: "equals",
    filterParameter: null, searchParameter: null, limit: 500, areaVariable: null,
    trackProperty: null, enableTimeline: false, selectedTimeVariable: null,
    windowStartVariable: null, windowEndVariable: null, timeZone: "utc", timeFormat: "local",
    allowTimeChange: true, liveModeToggle: true, openTimelineByDefault: true,
    playingVariable: null, playbackPositionVariable: null, autoPauseVariable: null,
    layerLabel: "", selectedVariable: null, layerVisible: true, layerVisibleVariable: null,
    lockLayer: false, layerColor: null, layerOpacity: 1,
    drawOptions: null, drawnShapeColor: null, drawnShapeOpacity: DRAWN_OPACITY,
    drawnShapesVariable: null, selectedShapesVariable: null, shapeOutputType: "features",
    enableMeasurements: false, measurePerimeter: true, perimeterMode: "total", measureArea: true,
    showLegend: false, legendCollapsed: false, legendSize: "full", showSelectionPanel: false,
    autoZoom: "default", autoZoomSetVariable: null, autoZoomOutsideOnly: false,
    boundsVariable: null, followSetVariable: null, enableSearchAround: false,
  },
  related: { settings: settingsPanel("MapSettings") },
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
  segmentBy = null,
  segmentMode = "stacked",
  showLegend = true,
  sort = "source",
  orientation = "vertical",
  valueLabels = false,
  scaleType = "linear",
  minBound = null,
  maxBound = null,
  showCategoryTitle = false,
  categoryTitle = "",
  showValueTitle = false,
  valueTitle = "",
  lineArea = "line",
  nullDisplay = "ignored",
  valueFormat = null,
  categoryFormat = null,
  legendPosition = "bottom",
  segmentNames = {},
  series = [],
  seriesName = "",
  multipleAxes = false,
  showRightTitle = false,
  rightTitle = "",
  rightScaleType = "linear",
  rightMinBound = null,
  rightMaxBound = null,
  rightValueFormat = null,
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
   * p.281's **Series aggregation** is `aggregate` over `measure` (§467): a
   * count, or a sum, average, minimum or maximum of a declared number, which
   * `/object-sets/group` has answered since §227. This comment used to say
   * grouped counts only, from before typed properties, and the chart drew a
   * count whatever the panel's Measure said. */
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
  /** p.281's **Segment by**: a second property each bar is split by (§467).
   * Counts only, because the split comes from `/object-sets/cross-tab`, which
   * counts; a segmented sum would need a metric per cell that no endpoint
   * returns yet. */
  segmentBy?: string | null;
  /** p.282's **Segment overrides**: stacked, percentage or grouped. */
  segmentMode?: string;
  /** p.284's **Show legend**, for the segments. */
  showLegend?: boolean;
  /** p.283's **Sort by** (§468), `chart-display.ts`. The data's own order
   * unless set, which is what every chart saved before it draws. */
  sort?: string;
  /** p.284's bar **orientation**; a line or scatter is vertical whatever this
   * says. */
  orientation?: string;
  /** p.281's **Labels**: each value written on its bar or point. */
  valueLabels?: boolean;
  /** p.283's value axis **Scale type** and **bounds** (§536,
   * `chart-display.valueScale`): calculated from the values unless fixed. */
  scaleType?: string;
  minBound?: number | null;
  maxBound?: number | null;
  /** p.283's axis **titles**, each off unless shown, and its default unless
   * overridden (`chart-display.axisTitlesOf`). */
  showCategoryTitle?: boolean;
  categoryTitle?: string;
  showValueTitle?: boolean;
  valueTitle?: string;
  /** p.281's **Area options** for a line: Line, or Area shaded beneath it
   * (§537). Stacked needs lines per segment, which a line chart has not. */
  lineArea?: string;
  /** p.282's **Display of null/missing values** on a line: Ignored, Gap or
   * Zeroes (`chart-display.withMissing`). */
  nullDisplay?: string;
  /** p.283's **numerical formatting** of the value and categorical axes
   * (§538): a property formatter (p.97–98), or null for none. */
  valueFormat?: unknown;
  categoryFormat?: unknown;
  /** p.284's legend **Positioning options** for the segments (§539). */
  legendPosition?: string;
  /** p.282's **Display override**: a segment's name in the legend, by its
   * value (`chart-segments.segmentName`). */
  segmentNames?: unknown;
  /** p.281's **multiple series** (§541): the series after the Measure's, each
   * an aggregation over the set grouped by the same X axis property
   * (`chart-series.ts`). A set-backed bar or line chart's, and not a
   * segmented one's. */
  series?: unknown;
  /** p.282's display override for the Measure's own series, in the legend a
   * chart with several series draws. */
  seriesName?: string;
  /** p.283's **Use multiple value axes** (§542): a second axis on the right
   * for the series that say so (`chart-series.axisSides`). */
  multipleAxes?: boolean;
  /** p.283's value axes "configured on a per series basis" (§691): the right
   * axis's own title, scale, bounds and number format. */
  showRightTitle?: boolean;
  rightTitle?: string;
  rightScaleType?: string;
  rightMinBound?: number | null;
  rightMaxBound?: number | null;
  rightValueFormat?: unknown;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending, resolved, declared } = useCanvasVariables();
  const { set: setParameter, values: parameterValues } = useCanvasParameters();
  const drilled = useCanvasParameter(drilldownVariable);
  // A time series set beats an object set beats a dataset. One order, stated
  // once, rather than three sources that can all be half-configured and a
  // reader left to guess which won.
  const seriesRef = useCanvasVariable(seriesVariable) as SeriesRef | null;
  const usingSeries = !!seriesVariable;
  const usingSet = !usingSeries && !!objectSetVariable;
  // p.282: segments are a bar chart's and, since §601, a line chart's -
  // p.281's Stacked area "stacks segmented chart values" - and they count
  // (see `segmentBy`).
  const segmenting = usingSet && !!segmentBy
    && ((kind ?? "bar") === "bar" || kind === "line")
    && pieAggregationOf(aggregate) === "count";

  // Drill-down needs a set to narrow and a property to narrow it on, so it is
  // offered only where both exist. A dataset-backed chart has no set: there is
  // nothing for a clause to mean, and inventing a second mechanism for it
  // would be two answers to one question.
  const canDrill = usingSet && !!drilldownVariable && !!dimension;
  // What is currently drilled into, read back out of the variable the chart
  // writes rather than held here as a second copy - so the chart reflects the
  // document's state, including a clause something else set.
  const drilledLabel = drilledOn(drilled, dimension ?? null);

  const sql = chartQuery({
    kind, dimension, measure, aggregate,
    filterColumn, filterOperator, filterValue,
  });

  const datasetResult = useQuery({
    queryKey: ["canvas-chart", datasetId, sql],
    queryFn: () => dsApi.query(workspaceId, projectId, datasetId!, sql!),
    enabled: !usingSet && !usingSeries && !!datasetId && sql !== null,
  });
  // p.281's Series aggregation. `null` while a numeric one has no property
  // yet, so an unfinished panel sends nothing rather than a refused request.
  const ask = pieAggregationRequest(aggregate, measure);
  const setResult = useQuery({
    queryKey: [
      "canvas-chart-set", objectSetVariable,
      JSON.stringify(setDefinition ?? null), dimension,
      ask?.aggregation ?? null, ask?.aggregation_property ?? null,
    ],
    queryFn: () => objApi.groupObjectSet(workspaceId, setDefinition, dimension!, ask ?? {}),
    enabled: usingSet && !!setDefinition && !!dimension && !!ask && !segmenting,
  });
  const crossTab = useQuery({
    queryKey: [
      "canvas-chart-segments", JSON.stringify(setDefinition ?? null), dimension, segmentBy,
    ],
    queryFn: () => objApi.crossTabObjectSet(workspaceId, setDefinition, dimension!, segmentBy!),
    enabled: segmenting && !!setDefinition && !!dimension,
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
        { interval: seriesRef!.interval, aggregate: seriesRef!.aggregate,
          transforms: seriesRef!.transforms },
      ),
    enabled: usingSeries && !!seriesRef,
  });

  // A reading with no value is a *gap*, and `Number(null)` is 0 - a finite
  // number that plots as a real measurement of zero (the bug §149 caught in
  // `plot`). It is kept as missing, NaN, and p.282's null display decides
  // whether it is skipped, left as a gap or drawn as zero (§537); the count
  // is said below.
  const reading = (value: unknown) =>
    value !== null && value !== "" && Number.isFinite(Number(value)) ? Number(value) : NaN;

  const result = usingSeries ? seriesResult
    : segmenting ? crossTab : usingSet ? setResult : datasetResult;
  const unsorted = usingSeries
    ? seriesResult.data
      ? seriesResult.data.points.map((p) => ({
          label: seriesPointLabel(p.at, seriesRef!.interval),
          value: reading(p.value),
        }))
      : null
    : usingSet
    ? (setResult.data?.groups ?? []).map((g) => ({
        label: g.value,
        // The metric when there is one: a bar of total capacity is its sum,
        // not how many sites made it.
        value: ask && ask.aggregation !== "count" ? Number(g.metric ?? 0) : g.count,
      }))
    : datasetResult.data
      ? toPoints(datasetResult.data.rows)
      : null;
  // p.283's Sort by, for categories. A series is a timeline and stays in time
  // order: a sorted one would be a line zig-zagging back through the weeks.
  const sorted = unsorted && !usingSeries ? sortPoints(unsorted, chartSortOf(sort)) : unsorted;
  // p.282's null display, which is a line chart's; any other leaves a missing
  // value out (`chart-display.withMissing`).
  const drawnKind = usingSeries ? "line" : (kind ?? "bar");
  const nulls = nullDisplayOf(nullDisplay);
  const missing = sorted ? missingCount(sorted) : 0;
  const points = sorted ? withMissing(sorted, drawnKind, nulls) : sorted;

  // One drill-down for every way the chart can be drawn: a click on a
  // category narrows to it, whichever series or segment it was on.
  const chartDrill = canDrill
    ? {
        selected: drilledLabel,
        // Clicking what is already drilled into clears it. Without that there
        // is no way back out from inside the chart, and a filter you cannot
        // remove is a filter you have to remember you applied.
        onSelect: (label: string) =>
          setParameter(drilldownVariable!, drillClauses(dimension!, label, drilledLabel)),
      }
    : undefined;

  // p.281's multiple series: the rest of the chart's series, each with its own
  // aggregation - and, as p.280's layers (§625), its own set grouped by its
  // own property when it names one. A series still being filled in asks
  // nothing and is left out.
  // A segmented bar chart keeps its layers since §678: each stands beside the
  // chart's own, split by its own Segment by where it has one. A segmented
  // line chart is one layer, a line per segment (§601).
  const extras = usingSet && (drawnKind === "bar" || (!segmenting && drawnKind === "line"))
    ? seriesOf(series) : [];
  const extraSegmented = extras.map((spec) =>
    segmentsLayer(spec, drawnKind === "line" ? "line" : "bar"));
  const extraAsks = seriesRequests(extras);
  const extraSources = extras.map((spec) => seriesSource(
    spec, { objectSetVariable: objectSetVariable ?? null, dimension: dimension ?? null },
    resolved));
  const extraResults = useQueries({
    queries: extras.map((spec, i) => ({
      queryKey: [
        "canvas-chart-set", extraSources[i]?.key ?? null,
        JSON.stringify(extraSources[i]?.definition ?? null), extraSources[i]?.dimension ?? null,
        extraAsks[i]?.aggregation ?? null, extraAsks[i]?.aggregation_property ?? null,
      ],
      queryFn: () => objApi.groupObjectSet(
        workspaceId, extraSources[i]!.definition, extraSources[i]!.dimension, extraAsks[i]!),
      enabled: !!extraSources[i] && !!extraAsks[i] && !extraSegmented[i] && !spec.fn,
    })),
  });
  // p.280's Function aggregation (§771): a layer that is a function's
  // buckets, called with its inputs as they stand.
  const layerFunctions = useQueries({
    queries: extras.map((spec) => {
      const values = spec.fn ? inputValues(spec.fn.inputs, resolved) : {};
      return {
        queryKey: ["canvas-chart-function", spec.fn?.function_id ?? null,
                   spec.fn?.version ?? null, values],
        queryFn: () => objApi.executeFunction(
          workspaceId, spec.fn!.function_id, values, spec.fn!.version),
        enabled: !!spec.fn?.function_id,
        retry: false,
      };
    }),
  });
  const functionNames = useQuery({
    queryKey: ["functions", workspaceId],
    queryFn: () => objApi.listFunctions(workspaceId),
    enabled: extras.some((spec) => !!spec.fn),
  });
  // p.282's Segment by on a layer (§678): its categories by its segments.
  const extraGrids = useQueries({
    queries: extras.map((spec, i) => ({
      queryKey: [
        "canvas-chart-segments", JSON.stringify(extraSources[i]?.definition ?? null),
        extraSources[i]?.dimension ?? null, spec.segmentBy,
      ],
      queryFn: () => objApi.crossTabObjectSet(
        workspaceId, extraSources[i]!.definition, extraSources[i]!.dimension, spec.segmentBy!),
      enabled: !!extraSources[i] && !!extraSegmented[i] && !spec.fn,
    })),
  });
  const drawnExtras = extras.flatMap((spec, i) => {
    if (spec.fn) {
      const answer = layerFunctions[i]?.data;
      const fnPoints = pointsFrom(answer);
      const fnGrid = gridFrom(answer);
      if (!fnPoints && !fnGrid) return [];
      const label = functionNames.data?.find((f) => f.id === spec.fn!.function_id)?.api_name;
      return [{
        spec,
        // A function layer has no set and no property: a click on its marks
        // filters as the chart's do.
        source: { key: `fn:${spec.fn.function_id}`, definition: null, dimension: "" },
        name: spec.name.trim() || spec.title.trim() || label || "Function",
        points: fnPoints ?? [],
        grid: fnGrid ?? undefined,
      }];
    }
    const data = extraResults[i]?.data;
    const grid = extraGrids[i]?.data;
    const request = extraAsks[i];
    const source = extraSources[i];
    if (!request || !source || (extraSegmented[i] ? !grid : !data)) return [];
    return [{
      spec,
      source,
      name: seriesNameOf(spec, source.key !== objectSetVariable
        ? declared[source.key]?.label ?? source.key : undefined),
      points: (data?.groups ?? []).map((g) => ({
        label: g.value,
        value: request.aggregation !== "count" ? Number(g.metric ?? 0) : g.count,
      })),
      grid: extraSegmented[i] && grid ? segmentedFrom(grid) : undefined,
    }];
  });
  const firstName = (typeof seriesName === "string" ? seriesName.trim() : "")
    || defaultValueTitle(kind ?? "bar", aggregate, measure);
  // §678: layers side by side, each segmented one stacked by its segments -
  // the chart's own, when it segments, and any layer with its own Segment by.
  const firstGrid = segmenting && crossTab.data && crossTab.data.rows.length > 0
    ? sortSegmented(segmentedFrom(crossTab.data), chartSortOf(sort)) : null;
  const layered = drawnExtras.length > 0 && (segmenting ? !!firstGrid : points !== null)
    && (segmenting || drawnExtras.some((e) => e.grid))
    ? layeredGrid([
        firstGrid ? { name: firstName, grid: firstGrid, segmentNames } : { name: firstName, points: points! },
        ...drawnExtras.map((e) => (e.grid ? { name: e.name, grid: e.grid } : { name: e.name, points: e.points })),
      ])
    : null;
  const multi = !layered && drawnExtras.length > 0 && points !== null
    ? mergeSeries(points, drawnExtras.map((e) => e.points),
      [firstName, ...drawnExtras.map((e) => e.name)])
    : null;
  // Only a series that asked is waited for: a disabled query stays pending.
  // p.282's Selection as filter per layer (§628): a series naming its own
  // variable narrows it on its own property; the rest narrow the chart's.
  const layerDrills = multi || layered ? [chartDrill, ...drawnExtras.map(({ spec, source }) => {
    const variable = spec.drilldownVariable;
    if (!variable || spec.fn) return chartDrill;
    const selected = drilledOn(parameterValues[variable], source.dimension);
    return {
      selected,
      onSelect: (label: string) =>
        setParameter(variable, drillClauses(source.dimension, label, selected)),
    };
  })] : undefined;
  // A layered chart's columns are its layers' segments: each takes its layer's.
  const drills = layered ? layered.stacks.map((layer) => layerDrills![layer]) : layerDrills;
  // p.280's Layer type (§626): a chart whose series are drawn as both bars
  // and lines is drawn as bars with the lines across them.
  const kinds = layerKinds(drawnKind === "line" ? "line" : "bar",
    drawnExtras.map((e) => e.spec));
  const mixed = mixedKinds(kinds);
  const extrasPending = extras.some((spec, i) => (spec.fn
    ? !!spec.fn.function_id && layerFunctions[i]?.isPending
    : !!extraAsks[i] && !!extraSources[i]
      && (extraSegmented[i] ? extraGrids[i]?.isPending : extraResults[i]?.isPending)));
  const sides = axisSides(drawnExtras.map((e) => e.spec), multipleAxes === true);
  const columnKinds = layered ? layered.stacks.map((layer) => kinds[layer]!) : kinds;
  const columnSides = layered ? layered.stacks.map((layer) => sides[layer]!) : sides;

  // p.283's value axis and titles. A problem with the bounds is said and the
  // chart drawn on calculated ones, rather than on an axis running backwards.
  const axis = valueAxisOf({ scaleType, minBound, maxBound });
  const axisTrouble = axisProblem(axis);
  // The right axis's, when there is one (§691). A problem with its bounds is
  // said, and `valueScale` draws it on calculated ones, as it does the left.
  const rightAxis = valueAxisOf({
    scaleType: rightScaleType, minBound: rightMinBound, maxBound: rightMaxBound });
  const rightTrouble = sides.includes("right") ? axisProblem(rightAxis) : null;
  const rightText = valueText(rightValueFormat) ?? undefined;
  const titles = axisTitlesOf(
    { showCategoryTitle, categoryTitle, showValueTitle, valueTitle, showRightTitle, rightTitle },
    usingSeries
      // p.281: a series chart has "the time range on the X axis".
      ? { category: "Time", value: defaultValueTitle("line", seriesRef?.aggregate, seriesRef?.property) }
      // p.283: "the aggregation type(s) used within the chart's series".
      : { category: dimension,
          value: multi ? multi.segments.join(", ")
            : layered ? [firstName, ...drawnExtras.map((e) => e.name)].join(", ")
            : defaultValueTitle(kind ?? "bar", aggregate, measure),
          right: rightAxisTitle(drawnExtras.map((e) => e.spec), sides, kind ?? "bar") },
  );

  const needs = usingSeries
    ? (!seriesRef ? "nothing picked yet" : null)
    : usingSet
    ? (!dimension ? "pick a property to group by"
      : !ask ? `pick a property to ${pieAggregationOf(aggregate)}` : null)
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
      {segmenting && crossTab.data && !layered && (
        crossTab.data.rows.length === 0
          ? <p className="canvas-widget-empty">No rows match — nothing to chart.</p>
          : kind === "line" ? (
            // A line per segment value (§601), shaded or stacked as p.281's
            // Area options say.
            <MultiLineChart
              data={sortSegmented(segmentedFrom(crossTab.data), chartSortOf(sort))}
              fill={areaOf(lineArea)}
              axis={axis}
              showLegend={showLegend !== false}
              titles={titles}
              legend={segmentLegendPositionOf(legendPosition)}
              valueText={valueText(valueFormat) ?? undefined}
              categoryText={categoryText(categoryFormat) ?? undefined}
              drill={chartDrill}
            />
          ) : (
            <SegmentedBarChart
              data={sortSegmented(segmentedFrom(crossTab.data), chartSortOf(sort))}
              mode={segmentModeOf(segmentMode)}
              showLegend={showLegend !== false}
              titles={titles}
              legend={segmentLegendPositionOf(legendPosition)}
              names={segmentNames}
              valueText={valueText(valueFormat) ?? undefined}
              categoryText={categoryText(categoryFormat) ?? undefined}
              drill={chartDrill}
            />
          )
      )}
      {/* Said, not hidden, as the grouped chart's truncation is below. */}
      {segmenting && (crossTab.data?.rows_truncated || crossTab.data?.columns_truncated) && (
        <p className="canvas-widget-empty" data-testid="chart-segments-truncated">
          Showing the largest {crossTab.data.rows.length} of{" "}
          {crossTab.data.row_distinct_total} {dimension} values and{" "}
          {crossTab.data.columns.length} of {crossTab.data.column_distinct_total} {segmentBy}{" "}
          values.
        </p>
      )}
      {multi && (drawnKind === "bar" || mixed) && (
        <SegmentedBarChart
          // Side by side, a colour per series. A series with no value for a
          // category has no bar there, which a zero draws as - and a line
          // layer's missing value is left missing, for the chart to join over.
          data={mixed ? multi : { ...multi, values: multi.values.map((row) =>
            row.map((v) => (Number.isNaN(v) ? 0 : v))) }}
          mode="grouped"
          kinds={mixed ? kinds : undefined}
          drills={drills}
          sides={sides}
          rightText={rightText}
          showLegend={showLegend !== false}
          titles={titles}
          legend={segmentLegendPositionOf(legendPosition)}
          valueText={valueText(valueFormat) ?? undefined}
          categoryText={categoryText(categoryFormat) ?? undefined}
          drill={chartDrill}
        />
      )}
      {layered && (
        <SegmentedBarChart
          // §678: each layer a group in the category's slot, a segmented one
          // stacked by its segments. A line layer runs across them.
          data={mixed ? layered.data : { ...layered.data, values: layered.data.values.map((row) =>
            row.map((v) => (Number.isNaN(v) ? 0 : v))) }}
          mode="grouped"
          stacks={layered.stacks}
          kinds={mixed ? columnKinds : undefined}
          drills={drills}
          sides={columnSides}
          rightText={rightText}
          showLegend={showLegend !== false}
          titles={titles}
          legend={segmentLegendPositionOf(legendPosition)}
          valueText={valueText(valueFormat) ?? undefined}
          categoryText={categoryText(categoryFormat) ?? undefined}
          drill={chartDrill}
        />
      )}
      {multi && drawnKind === "line" && !mixed && (
        <MultiLineChart
          data={multi}
          drills={drills}
          sides={sides}
          rightText={rightText}
          rightAxis={rightAxis}
          axis={axis}
          nulls={nulls}
          showLegend={showLegend !== false}
          titles={titles}
          legend={segmentLegendPositionOf(legendPosition)}
          valueText={valueText(valueFormat) ?? undefined}
          categoryText={categoryText(categoryFormat) ?? undefined}
          drill={chartDrill}
        />
      )}
      {extrasPending && <p className="canvas-widget-empty">Loading the other series…</p>}
      {!multi && !layered && !segmenting && points && !(usingSeries && points.length === 0) && (
        <Chart
          /* p.281: "If the data input is a time series set, only the Line
             Chart option is supported." */
          kind={usingSeries ? "line" : kind}
          points={points}
          display={{
            horizontal: orientationOf(orientation, usingSeries ? "line" : (kind ?? "bar"))
              === "horizontal",
            labels: valueLabels === true,
            axis,
            titles,
            // One line has nothing to stack, so Stacked shades it as Area does.
            shaded: drawnKind === "line" && areaOf(lineArea) !== "line",
            valueText: valueText(valueFormat) ?? undefined,
            categoryText: categoryText(categoryFormat) ?? undefined,
          }}
          drill={chartDrill}
        />
      )}
      {!segmenting && !usingSeries && missingText(missing, drawnKind, nulls) && (
        <p className="canvas-widget-empty" data-testid="chart-missing">
          {missingText(missing, drawnKind, nulls)}
        </p>
      )}
      {rightTrouble && (
        <p className="canvas-widget-empty" data-testid="chart-right-axis-problem">
          The right axis: {rightTrouble} It is calculated from the values instead.
        </p>
      )}
      {!segmenting && points && points.length > 0 && axisTrouble && (kind ?? "bar") !== "pie" && (
        <p className="canvas-widget-empty" data-testid="chart-axis-problem">
          {axisTrouble} The axis is calculated from the values instead.
        </p>
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
          {/* §524: what the server did to it, in order. */}
          {transformsText(seriesRef!.transforms) && `, ${transformsText(seriesRef!.transforms)}`}
          , in UTC. {sorted!.length - missing} point{sorted!.length - missing === 1 ? "" : "s"}
          {/* Said, not hidden - the same rule as the truncation notice below.
              A gap dropped in silence is a chart that looks complete. */}
          {missing > 0 && `, ${missing} with no reading ${
            nulls === "gap" ? "left as gaps" : nulls === "zeroes" ? "drawn as zero" : "skipped"}`}
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

CanvasChart.craft = {
  displayName: "Chart",
  props: {
    datasetId: null, kind: "bar", dimension: null, measure: null,
    aggregate: "count", title: "", filterColumn: null,
    filterParameter: null, filterOperator: "equals",
    objectSetVariable: null, seriesVariable: null, drilldownVariable: null,
    segmentBy: null, segmentMode: "stacked", showLegend: true,
    sort: "source", orientation: "vertical", valueLabels: false,
    scaleType: "linear", minBound: null, maxBound: null,
    showCategoryTitle: false, categoryTitle: "", showValueTitle: false, valueTitle: "",
    lineArea: "line", nullDisplay: "ignored", valueFormat: null, categoryFormat: null,
    legendPosition: "bottom", segmentNames: {}, series: [], seriesName: "",
    multipleAxes: false, showRightTitle: false, rightTitle: "", rightScaleType: "linear",
    rightMinBound: null, rightMaxBound: null, rightValueFormat: null,
  },
  related: { settings: settingsPanel("ChartSettings") },
};

// ---- Action form (write-back) --------------------------------------------------
/** One of p.122-124's sections, drawn around the parameters inside it.
 *
 * Its own component because folding is a fact about *a reader in a moment*: the
 * database stores whether a section `collapsible` and whether it starts
 * `collapsed`, and nothing else, so one person opening a section does not open
 * it for everybody. A `useState` per section needs a component per section.
 */
function ActionFormSection({
  section, children,
}: { section: FormSection; children: React.ReactNode }) {
  const [folded, setFolded] = useState(collapsedInitially(section));
  const columns = sectionColumnsOf(section);
  return (
    <section
      className="canvas-action-section"
      data-testid="action-form-section"
      data-section={section.title}
      data-columns={columns}
    >
      {section.collapsible ? (
        <button
          type="button"
          className="btn quiet"
          aria-expanded={!folded}
          data-testid="action-form-section-toggle"
          onClick={() => setFolded(!folded)}
        >
          {folded ? "▸" : "▾"} {section.title}
        </button>
      ) : (
        <h4 className="field-label" style={{ marginBottom: 4 }}>{section.title}</h4>
      )}
      {/* p.123: the description "is not stylized and, unlike parameter
          descriptions, will always be shown in the section itself, not in a
          tooltip" — so it is drawn beside the title rather than folded away
          with the fields, which is what "always" leaves room for. */}
      {section.description && (
        <p className="field-hint" data-testid="action-form-section-description">
          {section.description}
        </p>
      )}
      {!folded && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: columns === 2 ? "1fr 1fr" : "1fr",
            gap: 12,
          }}
        >
          {children}
        </div>
      )}
    </section>
  );
}

export function CanvasActionForm({
  actionTypeId: firstActionTypeId = null,
  subjectVariable = null,
  title: firstTitle = "",
  hideHeader = false,
  parameterDefaults: firstDefaults = {},
  invalidState = "disabled",
  outputVariable = null,
  actions: moreActions = [],
  layout: defaultLayout = "form",
  layoutSwitch = false,
  prefillVariable = null,
}: {
  actionTypeId?: string | null;
  /** p.512's "Select default layout: Choose between Action Table and Action
   * Form" (§702). */
  layout?: string;
  /** p.512's end-user "layout switching": readers may flip between the two. */
  layoutSwitch?: boolean;
  /** p.512's "Pre-fill with variable (table only)": an object set variable
   * whose objects become the table's rows (§703). */
  prefillVariable?: string | null;
  /** p.512's "Add item": the further actions, each with its own action,
   * title and defaults (§556, `action-menu.ts`). With any, the form has a
   * selection menu upfront. */
  actions?: unknown;
  /** p.512's "Set custom Action title". */
  title?: string;
  /** p.513's Hide header. */
  hideHeader?: boolean;
  /** p.512's local parameter defaults, keyed by parameter api_name. */
  parameterDefaults?: Record<string, unknown>;
  /** p.513's "form state if invalid". */
  invalidState?: string;
  /** p.513's **Output object set**: an `array` variable holding the clauses
   * that name what this submission created or modified.
   *
   * **An array, not an object set** - the same split p.224's Object Table
   * outputs use (§207). What the widget writes is a clause list; a `narrow_set`
   * derivation over a base set of the type turns it into the set. Offering an
   * object-set variable here would invite binding the *derived* one and
   * overwriting the thing that derives it. */
  outputVariable?: string | null;
  /** A `single_object` variable naming what to edit (roadmap 1.5, the inline
   * action form). Bound, the form edits the object somebody picked and the
   * record dropdown disappears — which is the difference between a form beside
   * an app and a form *in* one. Unbound, it keeps the dropdown, so the apps
   * built before this still work. */
  subjectVariable?: string | null;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId, mode } = useCanvasEnv();
  const queryClient = useQueryClient();
  const {
    events: moduleEvents, declared: moduleVariables,
    pending: variablesPending,
  } = useCanvasVariables();
  const eventContext = useEventContext(undefined, useOverlayIds());
  const subject = useCanvasVariable(subjectVariable) as
    | { id?: string; primary_key?: unknown; properties?: Record<string, unknown> }
    | undefined;
  const { set: setParameter } = useCanvasParameters();

  // p.512's selection menu (§556): the item showing decides the action, its
  // title and its defaults; everything else below is the one form it was.
  const items = actionItemsOf(
    { actionTypeId: firstActionTypeId, title: firstTitle, parameterDefaults: firstDefaults },
    moreActions,
  );
  const [activeItem, setActiveItem] = useState(0);
  const item = items[activeIndexOf(activeItem, items.length)];
  const actionTypeId = item?.actionTypeId ?? null;
  const title = item?.title ?? "";
  const parameterDefaults = item?.parameterDefaults ?? {};

  const actionTypesQ = useQuery({
    queryKey: ["action-types", workspaceId],
    queryFn: () => actionApi.listTypes(workspaceId),
  });
  const actionType = actionTypesQ.data?.find((a) => a.id === actionTypeId) ?? null;
  // p.511's two layouts (§702). What the builder chose, until a reader flips
  // it where p.512's layout switching is on. A table only for an action it can
  // draw - p.511: "some Actions … are not yet usable in the Table" - which the
  // server says rather than this widget guessing.
  const [readerLayout, setReaderLayout] = useState<string | null>(null);
  const chosenLayout = layoutSwitch && readerLayout ? readerLayout : defaultLayout;
  const tableRefusals = actionType?.table_refusals ?? [];
  const prefillSet = useCanvasVariable(prefillVariable);
  const asTable = chosenLayout === "table" && tableRefusals.length === 0;

  // **The objects this action can be run against** — and for an interface
  // action that is every object of every implementing type, which is
  // `action-types` p.62's interface reference parameter: it "shows objects of
  // any type that implements the interface" (§451).
  //
  // Two queries rather than one with a branch inside it, because they have
  // different keys and only one of them ever runs: a shared key would let a
  // cached page of one type answer for the other.
  const instancesQ = useQuery({
    queryKey: ["canvas-widget-instances", actionType?.object_type_id],
    queryFn: () => objApi.listInstances(workspaceId, actionType!.object_type_id!, 25, 0),
    // A table's rows pick their objects from this list even when the form
    // would edit a bound one (§702).
    enabled: !!actionType?.object_type_id && (!subjectVariable || asTable),
  });
  // p.60's list of object types to pick from — the interface's
  // implementations, which the detail read carries (§453). Its own query
  // rather than a field on the action type: which types implement an interface
  // changes without the action changing, and a copy on the action would be
  // free to go stale (§191).
  const interfaceQ = useQuery({
    queryKey: ["interface", actionType?.interface_id],
    queryFn: () => objApi.getInterface(workspaceId, actionType!.interface_id!),
    enabled: !!actionType?.interface_id,
  });
  const membersQ = useQuery({
    queryKey: ["canvas-widget-interface-members", actionType?.interface_id],
    queryFn: () =>
      objApi.evaluateInterfaceSet(workspaceId, actionType!.interface_id!, { limit: 25 }),
    // **`!!actionType?.interface_id` is load-bearing and cannot be asserted**,
    // which is worth saying rather than leaving as an untested line (§213,
    // §223). Without it the query runs before `actionType` has loaded, the
    // `!` assertions read through `null`, and React Query *swallows* the
    // TypeError into an error state nothing renders — no request is made, the
    // dropdown still fills from the other read, and the page looks identical.
    // So a mutant removing it survives every check a browser can make, and the
    // guard stays on the strength of what it prevents rather than of a test.
    enabled: !!actionType?.interface_id && !subjectVariable,
  });
  // One list, because the dropdown is one control. An interface page calls its
  // rows `instances` and a type's page calls them `items`; both rows carry an
  // id, a primary key and the properties p.25's seeding reads — the last of
  // which is why this is the *interface's* vocabulary on that side, which is
  // also the vocabulary the action's parameters are named in (p.59).
  const choosable: {
    id: string; primary_key: unknown; properties?: Record<string, unknown>;
  }[] = actionType?.interface_id
    ? (membersQ.data?.instances ?? [])
    : (instancesQ.data?.items ?? []);

  const [picked, setPicked] = useState("");
  // **`unknown`, not `string`, as of §237.** An attachment parameter's value is
  // the reference object `POST /attachments` returned and a boolean's is a
  // boolean — the map was typed `string` because the old field could only ever
  // produce one, which is the type recording a limitation rather than a rule.
  // The server coerces each value against the parameter's declared type.
  const [values, setValues] = useState<Record<string, unknown>>({});
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
    : choosable.find((i) => i.id === picked);
  // With the action: another item is another form, so switching re-seeds it
  // even on the same object (§556).
  const chosenKey = `${actionTypeId ?? ""}:${String(chosen?.id ?? "")}`;
  const [seeded, setSeeded] = useState<string | null>(null);
  // Which fields the reader has actually typed in. **The only thing that keeps
  // p.45's overridden default from overwriting somebody's work** (§329): an
  // override can change a parameter's default as another value changes, so the
  // form has to be able to tell "this box still holds what we put in it" from
  // "this box holds what somebody meant".
  const [typed, setTyped] = useState<Record<string, true>>({});
  if (chosenKey !== seeded) {
    setSeeded(chosenKey);
    // A different object is a different form. Anything typed against the last
    // one is not an answer about this one.
    setTyped({});
    setValues(seedActionForm(
      actionType?.parameters ?? [], chosen?.properties ?? {},
      localDefaultsOf(parameterDefaults),
    ));
  }

  // p.513's output, **stated rather than merely empty**, and §207's rule
  // arrived at from the other side. A variable nothing has written holds no
  // clauses, and no clauses means *no narrowing* - so a module showing "what
  // this submission changed" would show the whole table until the first
  // submit. `hasSelection` is how the widget knows it still has to say so, and
  // is what keeps a state restored on load (§153) from being wiped.
  const outputRaw = useCanvasParameter(outputVariable);
  // **A declared default counts as stated, and the browser cannot see it in
  // `values`.** The server resolves an unbound variable as
  // `values.get(vid, variable.default)`, so a default never reaches the local
  // map - and writing the empty set here would *replace* it, destroying a
  // starting selection the builder declared on purpose.
  //
  // Not the question p.224's Object Table asks with `activeStated`: p.224 says
  // in as many words that the table "results in an empty active object at load
  // time", so there the empty write is the requirement. p.513 says nothing of
  // the sort about an output set.
  const outputStated = hasSelection(outputRaw) || hasSelection(
    outputVariable
      ? (moduleVariables[outputVariable] as { default?: unknown } | undefined)?.default
      : undefined,
  );
  useEffect(() => {
    // **Nothing is written while the variables are still resolving**
    // (§210's rule: unresolved is not empty). `declared` is `{}` on the
    // first render, so a default would read as absent and the empty set
    // would be written over it before the module had finished loading -
    // which is exactly what the browser test saw.
    // **`pending` alone is not enough**, and this is the bug the preset test
    // found. The default `VariableContext` is `{declared: {}, pending: false}`,
    // so on any render before the provider is in place the guard above passes,
    // the declared default reads as absent, and the empty set is written over
    // it - after which nothing puts it back. A module that binds an output
    // variable necessarily declares variables, so an empty map means "not
    // loaded yet", never "none".
    if (variablesPending || Object.keys(moduleVariables).length === 0) return;
    if (!outputVariable || outputStated) return;
    setParameter(outputVariable, selectionClauses([]));
    // `setParameter` is stable for the life of the provider; listing it would
    // re-run this on every render of every widget in the module.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outputVariable, outputStated, variablesPending, moduleVariables]);

  const execute = useMutation({
    // An array's blank rows are dropped here, as it is sent (§580).
    mutationFn: () => actionApi.execute(workspaceId, projectId, actionType!.id, instanceId,
      submittedValues(values, actionType!.parameters)),
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
      // p.513's **Output object set**, written before the event below fires -
      // an event that navigates or opens an overlay would otherwise act on the
      // previous submission's objects. **Written even when this action touched
      // nothing of its own type**, as the empty set: leaving it alone would
      // leave the last submission's rows on screen for a reader to act on.
      if (outputVariable) {
        setParameter(outputVariable, outputClauses(
          result.touched, actionType?.object_type_id ?? null,
        ));
      }
      // p.513's "On successful action submit". **On success only**, which is
      // what p.513 says and what makes it usable: an event that also fired on
      // a refusal would navigate away from the message explaining why.
      const submitted = eventsFor(moduleEvents, nodeId, "submit");
      if (submitted.length > 0) {
        runEvents(submitted, {
          ...eventContext,
          payload: { ...values, primary_key: String(subject?.primary_key ?? "") },
        });
      }
    },
  });

  const live = mode === "run";
  // p.513's "form state if invalid", asked of the server rather than decided
  // here.
  //
  // **On the seeded values, keyed on the object — not on what is typed.** The
  // question is whether this action is available for *this object*, which is
  // p.513's own example (a ticket that is not open). The first version keyed
  // this on the current values and broke §130's test: typing a value a
  // criterion refuses disabled the button, so the submission never happened
  // and the criterion's own message (p.56) never appeared. A live check does
  // not *add* to that message, it **replaces it with silence** — and it asks
  // the server once per keystroke to do it.
  const seedForCheck = seedActionForm(
    actionType?.parameters ?? [], chosen?.properties ?? {},
    localDefaultsOf(parameterDefaults),
  );
  const criteriaCheck = useQuery({
    queryKey: ["action-check", actionTypeId, chosenKey],
    queryFn: () => actionApi.check(workspaceId, projectId, actionTypeId!, seedForCheck),
    // Only where a builder asked for it, and only when there is something to
    // check: an action with no criteria can never be refused by one, so asking
    // would be a round trip whose answer is known.
    enabled: live && !!actionTypeId && !!instanceId
      && (actionType?.criteria ?? []).length > 0,
  });
  const valid = criteriaCheck.data ? criteriaCheck.data.ok : undefined;
  const visibleForm = formVisible({ invalidState, valid });

  // §328: p.122-124's sections, which arrange this form and change nothing
  // about what it submits. Their own read rather than a field on the action
  // type, because every other reader of an action's parameters would otherwise
  // pay for a layout it is not going to draw.
  const sectionsQ = useQuery({
    queryKey: ["action-sections", actionTypeId],
    queryFn: () => actionApi.sections(workspaceId, actionTypeId!),
    enabled: !!actionTypeId,
  });
  const sections: FormSection[] = sectionsQ.data ?? [];
  // p.123's conditional override, **asked of the server**. The same argument
  // the criteria check above makes: decision 0007's conditions are one grammar,
  // and a form evaluating `{left, operator, right}` in TypeScript would be a
  // second reading of the document the definition editor writes.
  //
  // Keyed on only the values some section's condition actually names, so typing
  // in an ordinary field is not a round trip — and **asked at all only when a
  // section carries a condition**, which is a different question from whether
  // any condition names a parameter. p.50's other template ("based on current
  // user") reads nothing out of the form, so keying the `enabled` flag on the
  // values made a section shown to one person undrawable for everybody. A
  // mutation sweep found it.
  const watching = conditionKey(sections, values);
  const shownQ = useQuery({
    queryKey: ["action-visible-sections", actionTypeId, watching],
    queryFn: () => actionApi.visibleSections(workspaceId, actionTypeId!, values),
    enabled: !!actionTypeId && hasConditions(sections),
  });
  // **`undefined` until the server answers**, which `drawnSections` reads as
  // p.123's "hidden at first" for a conditional section and as nothing at all
  // for one without a condition. There is deliberately no "substitute the
  // empty list when nothing is conditional" here: it was in the first draft
  // and a sweep showed it could not matter, because a form with no conditional
  // section has no section whose drawing depends on the answer.
  const shown = shownQ.data;

  // §329: p.43-46's overrides, which change what this form *asks for* rather
  // than how it looks — a parameter can be required for one person and optional
  // for another. **Asked of the server**, like the sections above and for a
  // stronger reason: the same resolution decides whether the submission is
  // refused, so a browser-side copy could ask for the wrong things and then
  // refuse what somebody sent.
  //
  // Gated on `hasOverrides` rather than on "does a condition name a
  // parameter", because p.43's own example asks who is submitting and names
  // nothing — which is the defect §328 shipped and had to come back for.
  // §330: what each object parameter may be set to. An `object` parameter has
  // been a text box since db 0044 — it asks whoever submits to know a uuid —
  // and this is the list p.33-37 assumes. Absent for a parameter whose type
  // nobody declared, which keeps its text box: a *guessed* list would be worse
  // than none, because a reader cannot tell a wrong list from a short one.
  // p.36's filters may read what has been filled in so far (§331), so this is
  // keyed on **only those values**: a form whose object parameters carry no
  // parameter-reading filters asks once when it opens, and typing in a box no
  // filter mentions is not a round trip.
  const watchingFilters = filterKey(
    (actionType?.parameters ?? []) as never, values,
  );
  const offersQ = useQuery({
    queryKey: ["action-parameter-choices", actionTypeId, watchingFilters],
    queryFn: () => actionApi.parameterChoices(workspaceId, actionTypeId!, values),
    enabled: !!actionTypeId,
    // **The last list stays while the next one loads** (§331). Without this the
    // data is `undefined` for the width of a round trip whenever a watched
    // value changes, `offerFor` returns nothing, and the control flips from a
    // dropdown to a text box and back on every keystroke in the box above it —
    // which is worse than a stale list, because a text box will accept an id
    // the filter excludes.
    placeholderData: (previous) => previous,
  });
  const stored = (actionType?.parameters ?? []) as FormParameter[];
  const overridden = hasOverrides(actionType?.parameters ?? []);
  const watchingValues = overrideKey(actionType?.parameters ?? [], values);
  const effectiveQ = useQuery({
    queryKey: ["action-effective-parameters", actionTypeId, watchingValues],
    queryFn: () => actionApi.effectiveParameters(workspaceId, actionTypeId!, values),
    enabled: !!actionTypeId && overridden,
  });
  // **The stored parameters until the server answers**, rather than nothing. A
  // form that drew no fields while the question was in flight would blank
  // itself on every keystroke in a watched value; the stored row is what the
  // parameter says when no block holds, which is the honest starting point and
  // the one every form had before §329.
  const declared = (
    overridden && effectiveQ.data ? effectiveQ.data : stored
  ) as FormParameter[];
  const layout = formLayout(declared, sections, shown);
  const visible = [
    ...layout.loose,
    ...layout.sections.flatMap((drawn) => drawn.parameters),
  ];
  // p.45 lists default values among what an override may change, and the
  // server honours one for a parameter the caller does not supply. **This form
  // always supplies every parameter it drew**, so without this the overridden
  // default could never apply through a form — the seed would win every time
  // and the rule would be true only of submissions made without a screen.
  //
  // Only fields nobody has typed in, which is what makes this safe to run on
  // every resolution: a default that changed while somebody was writing would
  // otherwise take the sentence out from under them.
  useEffect(() => {
    if (!overridden || !effectiveQ.data) return;
    const fill: Record<string, unknown> = {};
    for (const parameter of effectiveQ.data) {
      if (typed[parameter.api_name]) continue;
      if (parameter.default_value === null || parameter.default_value === undefined) continue;
      fill[parameter.api_name] = parameter.default_value;
    }
    if (Object.keys(fill).length === 0) return;
    setValues((was) => {
      const next = { ...was, ...fill };
      // Compared before writing, because this effect runs on every resolution
      // and an unconditional `setValues` would re-render forever.
      return Object.keys(fill).every((k) => was[k] === next[k]) ? was : next;
    });
    // `typed` is read rather than depended on: a keystroke marks a field typed
    // and the very next run would otherwise undo nothing but re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveQ.data, overridden]);
  // p.33: "If only one linked object is available in the resulting object set
  // and the parameter is required, the parameter dropdown will automatically
  // prefill with the corresponding property value" (§335).
  //
  // The same shape as the effect above and for the same reasons: the condition
  // is decided by the server, because it is about the object *set* and this
  // form is only ever shown what the set left; and only untyped fields are
  // filled, so a value that appeared while somebody was choosing does not take
  // the choice out from under them.
  //
  // **`seeded` is in the dependencies and the browser test is why.** Choosing
  // a subject re-seeds the whole form — "a different object is a different
  // form" — and the offers have not changed, so an effect watching only them
  // fills the box once, has it wiped a moment later, and never puts it back.
  // p.33's prefill belongs to the form rather than to the response, so it is
  // reapplied whenever the form is.
  useEffect(() => {
    const fill: Record<string, unknown> = {};
    for (const offer of offersQ.data ?? []) {
      if (offer.kind !== "values" || !offer.prefill) continue;
      // **`typed` and only `typed`** (§213). There used to be a
      // `hasValue(values[...])` beside this, and a sweep could delete it with
      // nothing failing — for a reason worth writing down rather than a gap in
      // the tests. The prefill fires only when the set left exactly one allowed
      // value, so anything already in the box that is *not* that value is not a
      // choice: it is the subject's own property read at seed time, and the
      // submission would refuse it (§214's check on the submit path). Filling
      // over it is p.33's sentence doing its job. What must not be overwritten
      // is what somebody actually did, which is what `typed` records — clearing
      // a required box and having it refill itself is a control arguing with
      // the person using it.
      if (typed[offer.parameter]) continue;
      fill[offer.parameter] = offer.prefill;
    }
    if (Object.keys(fill).length === 0) return;
    setValues((was) => {
      const next = { ...was, ...fill };
      return Object.keys(fill).every((k) => was[k] === next[k]) ? was : next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offersQ.data, seeded]);

  // p.66's struct is filled in field by field, and what the form holds after
  // somebody clears the last field is `{}` — which `hasValue` calls a value.
  // That is the right answer for the attachment reference it was written for
  // and the wrong one here, so the struct case is named rather than folded
  // into `hasValue`. **An array is the third question, decided by §580**: it
  // is answered by a row with something in it, since blank rows are dropped
  // when the form is sent and p.116 says a required array has an item.
  const supplied = (p: FormParameter, value: unknown) =>
    p.data_type === "struct" ? isFilled(value)
    : p.data_type === "array" ? hasItems(value)
    : hasValue(value);
  const missingRequired = visible.filter(
    (p) => p.required && !supplied(p, values[p.api_name]),
  );
  // A required parameter inside a section this form is not showing. The server
  // still requires it, so the submission would be refused — and saying
  // "Priority is required" beside no Priority box is §214's shape, a control
  // that looks like it works.
  const unreachable = unreachableNote(requiredElsewhere(declared, sections, shown));
  const field = (parameter: FormParameter) => {
    const offer = offerFor(parameter.api_name, offersQ.data);
    // p.33's *other* shape (§335): a parameter that is not an object, whose
    // allowed values are what one property holds across a set. Its own lookup
    // rather than a `kind` check here, because the two are read by different
    // controls and `offerFor` returning either would put the choosing in this
    // component.
    const choice = valuesFor(parameter.api_name, offersQ.data);
    return (
    <label className="field" key={parameter.api_name} data-parameter={parameter.api_name}>
      <span className="field-label">
        {parameterLabel(parameter)}
        {parameter.required && <span aria-hidden> *</span>}
      </span>
      {/* **`PropertyInput`, not a local `<input>`** (§237). That component's
          own docstring says it is "the input for one editable property in an
          action form", and this form — the other action form — had its own
          field instead. The two disagreed about `attachment`, where a text box
          could never produce the reference `POST /attachments` returns, and
          about `boolean`, which now gets a three-state select. `disabled` stays
          here because it is about the *builder*, not the type. */}
      <fieldset disabled={!live} className="canvas-action-field">
        {/* p.33-37's dropdown, where the action says what the parameter holds
            (§330). Drawn here rather than inside `PropertyInput` because that
            component is about a *property's* type and these choices are about
            an *action's* parameter — the inline-edit path shares it and has no
            action to ask. **The refusal is the server's either way** (p.34's
            second sentence), so this is a convenience over a rule rather than
            the rule itself. */}
        {parameter.data_type === "object_type" ? (
          /* `action-types` p.60's Object type parameter (§453): "the user will
             be prompted to pick an object type from a list". **The list is the
             interface's implementations**, because those are the only types a
             rule written in the interface's vocabulary can produce — the
             server refuses any other, and offering one would be a control
             whose only outcome is that refusal (§214).

             Its own branch rather than a kind of `offer`: an offer is p.33's
             narrowed set of *objects*, resolved per submission against the
             other values, and this is a fixed list that depends on nothing. */
          <select
            aria-label={parameterLabel(parameter)}
            required={parameter.required}
            data-testid="object-type-parameter"
            value={values[parameter.api_name] === null
              || values[parameter.api_name] === undefined
              ? "" : String(values[parameter.api_name])}
            onChange={(e) => {
              setTyped((was) => ({ ...was, [parameter.api_name]: true }));
              setValues({
                ...values,
                [parameter.api_name]: e.target.value === "" ? null : e.target.value,
              });
            }}
          >
            <option value="">Choose an object type…</option>
            {(interfaceQ.data?.implementations ?? []).map((implementor) => (
              <option
                key={implementor.object_type_id}
                value={implementor.object_type_id}
              >
                {implementor.display_name}
              </option>
            ))}
          </select>
        ) : offer && parameter.data_type === "array" ? (
          /* p.36's ObjectReference list (§581): several of the offered objects
             at once. A native `<select multiple>`, for the String Selector's
             reason - the control a browser already gives keyboard and screen
             reader support for. */
          <select
            multiple
            aria-label={parameterLabel(parameter)}
            data-testid="object-list-parameter"
            size={Math.min(6, Math.max(2, offer.items.length))}
            value={Array.isArray(values[parameter.api_name])
              ? (values[parameter.api_name] as unknown[]).map(String) : []}
            onChange={(e) => {
              setTyped((was) => ({ ...was, [parameter.api_name]: true }));
              setValues({
                ...values,
                [parameter.api_name]: [...e.target.selectedOptions].map((o) => o.value),
              });
            }}
          >
            {offer.items.map((choice) => (
              <option key={choice.id} value={choice.id}>{choiceLabel(choice)}</option>
            ))}
          </select>
        ) : offer ? (
          <select
            aria-label={parameterLabel(parameter)}
            required={parameter.required}
            value={values[parameter.api_name] === null
              || values[parameter.api_name] === undefined
              ? "" : String(values[parameter.api_name])}
            onChange={(e) => {
              setTyped((was) => ({ ...was, [parameter.api_name]: true }));
              setValues({
                ...values,
                [parameter.api_name]: e.target.value === "" ? null : e.target.value,
              });
            }}
          >
            <option value="">Choose a {offer.object_type_name}…</option>
            {offer.items.map((choice) => (
              <option key={choice.id} value={choice.id}>{choiceLabel(choice)}</option>
            ))}
          </select>
        ) : choice ? (
          /* p.33's multiple choice. A plain `<select>` of values rather than
             `PropertyInput`, because the point of the control is that the
             options are derived — a typed value would be refused by the same
             rule that produced them (§214, and the check on the submit path). */
          <select
            aria-label={parameterLabel(parameter)}
            required={parameter.required}
            data-testid="values-select"
            value={values[parameter.api_name] === null
              || values[parameter.api_name] === undefined
              ? "" : String(values[parameter.api_name])}
            onChange={(e) => {
              setTyped((was) => ({ ...was, [parameter.api_name]: true }));
              setValues({
                ...values,
                [parameter.api_name]: e.target.value === "" ? null : e.target.value,
              });
            }}
          >
            <option value="">Choose…</option>
            {(choice.values ?? []).map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        ) : (
        <PropertyInput
          workspaceId={workspaceId}
          dataType={parameter.data_type as never}
          // p.66's nested fields, sent down with the parameter (§450). The
          // server derives them from the property the rule writes, so this
          // form has nothing that could disagree with the ontology.
          structFields={parameter.struct_fields}
          // db 0118's element type, for an array parameter's rows (§580).
          arrayOf={parameter.array_of}
          // p.8's multiple choice (§584), a dropdown of its options.
          choices={multipleChoice(parameter)}
          // p.71-72's per-field multiple choice on a struct (§585).
          fieldChoices={fieldChoices(parameter)}
          value={values[parameter.api_name] ?? null}
          onChange={(next) => {
            setTyped((was) => ({ ...was, [parameter.api_name]: true }));
            setValues({ ...values, [parameter.api_name]: next });
          }}
          label={parameterLabel(parameter)}
          required={parameter.required}
        />
        )}
        {/* p.8 and p.71's constraint, said beside the box in the words the
            server's refusal uses (§584). */}
        {constraintNote(parameter) && (
          <span className="field-hint" data-testid="constraint-note">
            {constraintNote(parameter)}
          </span>
        )}
        {fieldNotes(parameter).map((note) => (
          <span key={note} className="field-hint" data-testid="field-constraint-note">
            {note}
          </span>
        ))}
        {/* p.36's filter can read a box nobody has filled in, and then the
            list is empty for a reason worth saying: "there are no Teams" is
            false and unhelpful when the truth is "you have not said which
            region". §331. */}
        {offer && isWaiting(offer) && (
          <span className="field-hint" data-testid="choices-waiting">
            {waitingNote(offer, Object.fromEntries(declared.map(
              (p) => [p.api_name, parameterLabel(p)],
            )))}
          </span>
        )}
        {offer && !isWaiting(offer) && noChoicesNote(offer) && (
          <span className="field-hint" data-testid="choices-empty">
            {noChoicesNote(offer)}
          </span>
        )}
        {offer && choicesTruncatedNote(offer) && (
          <span className="field-hint" data-testid="choices-truncated">
            {choicesTruncatedNote(offer)}
          </span>
        )}
        {/* p.33's two states a derived list of values has and a text box does
            not (§335). Their own notes rather than the object ones above:
            "there are no Teams" and "no object has a value for that property"
            are different things to be told, and the second is the one an
            editor can act on. */}
        {/* p.33's list can be narrowed by a filter reading another box
            (§336), so it has the same waiting state an object dropdown has —
            and `emptyValuesNote` must stand down for it, because "no object
            has a value for that property" is false when the truth is "you
            have not said which region". */}
        {choice && isWaiting(choice) && (
          <span className="field-hint" data-testid="values-waiting">
            {waitingNote(choice, Object.fromEntries(declared.map(
              (p) => [p.api_name, parameterLabel(p)],
            )))}
          </span>
        )}
        {choice && !isWaiting(choice) && emptyValuesNote(choice) && (
          <span className="field-hint" data-testid="values-empty">
            {emptyValuesNote(choice)}
          </span>
        )}
        {valuesTruncationNote(choice) && (
          <span className="field-hint" data-testid="values-truncated">
            {valuesTruncationNote(choice)}
          </span>
        )}
      </fieldset>
    </label>
    );
  };

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {items.length > 1 && (
        // p.512: "users will see a selection menu upfront".
        <label className="field">
          <span className="field-label">Action</span>
          <select
            aria-label="Choose an action"
            data-testid="action-form-menu"
            value={activeIndexOf(activeItem, items.length)}
            onChange={(e) => setActiveItem(Number(e.target.value))}
          >
            {items.map((it, i) => (
              <option key={`${it.actionTypeId}-${i}`} value={i}>
                {menuLabelOf(it, actionTypesQ.data ?? [])}
              </option>
            ))}
          </select>
        </label>
      )}
      {!actionType && <p className="canvas-widget-empty">Action form - pick an action in Settings</p>}
      {actionType && !visibleForm && (
        // p.513's `hidden`. Said rather than drawn as nothing, because a
        // builder arranging the page needs to know the widget is there — the
        // same argument §210 makes for a title widget that renders nothing.
        mode === "run" ? null : (
          <p className="canvas-widget-empty" data-testid="action-form-hidden">
            Hidden: this action cannot be submitted
          </p>
        )
      )}
      {actionType && layoutSwitch && (
        // p.512's "layout switching", for readers.
        <div className="row-actions" role="group" aria-label="Layout"
             data-testid="action-layout-switch">
          {(["form", "table"] as const).map((name) => (
            <button
              key={name}
              type="button"
              className={chosenLayout === name ? "btn" : "btn quiet"}
              aria-pressed={chosenLayout === name}
              onClick={() => setReaderLayout(name)}
            >
              {name === "form" ? "Form" : "Table"}
            </button>
          ))}
        </div>
      )}
      {actionType && chosenLayout === "table" && tableRefusals.length > 0 && (
        // Said, and the form drawn instead: an action the table cannot hold
        // is still an action somebody can submit.
        <p className="canvas-widget-empty" data-testid="action-table-refused">
          This action is only available as a form: {tableRefusals.join("; ")}.
        </p>
      )}
      {actionType && visibleForm && asTable && (
        <div className="card">
          {!hideActionHeaderOf(hideHeader) && (
            <h3 style={{ marginTop: 0 }} data-testid="action-form-title">
              {headerTitleOf(title, actionType.display_name)}
            </h3>
          )}
          <ActionTable
            key={actionType.id}
            workspaceId={workspaceId}
            projectId={projectId}
            actionType={actionType}
            subjects={choosable}
            localDefaults={localDefaultsOf(parameterDefaults)}
            live={live}
            prefill={prefillVariable && prefillSet ? { definition: prefillSet } : null}
            onSubmitted={(touched, rows) => {
              // p.513's output and its event, once every row went through -
              // the table's "successful action submit".
              if (outputVariable) {
                setParameter(outputVariable, outputClauses(
                  touched, actionType.object_type_id ?? null,
                ));
              }
              const submitted = eventsFor(moduleEvents, nodeId, "submit");
              if (submitted.length > 0) {
                runEvents(submitted, { ...eventContext, payload: { rows: rows.length } });
              }
            }}
          />
        </div>
      )}
      {actionType && visibleForm && !asTable && (
        <form
          className="card"
          onSubmit={(e) => {
            e.preventDefault();
            if (live) execute.mutate();
          }}
        >
          {!hideActionHeaderOf(hideHeader) && (
            <h3 style={{ marginTop: 0 }} data-testid="action-form-title">
              {headerTitleOf(title, actionType.display_name)}
            </h3>
          )}
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
                {choosable.map((i) => (
                  <option key={i.id} value={i.id}>
                    {String(i.primary_key)}
                  </option>
                ))}
              </select>
            </label>
          )}
          {/* p.124: "Parameters and sections display in the form based on
              their order in this Form Content section" - the parameters no
              section holds and p.122's groupings, in one order (§589). */}
          {layout.blocks.map((block) => block.kind === "parameter"
            ? field(block.parameter)
            : (
              <ActionFormSection key={block.drawn.section.id} section={block.drawn.section}>
                {block.drawn.parameters.map(field)}
              </ActionFormSection>
            ))}
          <button
            type="submit"
            className="btn"
            disabled={!live || !instanceId || execute.isPending
              || missingRequired.length > 0 || !!unreachable || valid === false}
          >
            {execute.isPending ? "Submitting…" : "Submit"}
          </button>
          {valid === false && live && (
            // The criterion's own message (p.56), from the server that would
            // refuse it — not a sentence this widget invented about a rule it
            // does not implement.
            <p className="canvas-widget-empty" data-testid="action-form-invalid">
              {criteriaCheck.data?.error}
            </p>
          )}
          {missingRequired.length > 0 && live && (
            <p className="canvas-widget-empty" data-testid="action-form-missing">
              {missingRequired.map(parameterLabel).join(", ")} is required.
            </p>
          )}
          {/* And the one nobody can act on from here, said to whoever can
              (§328). A required parameter inside a section this form does not
              show leaves the button disabled for a reason no box on screen
              explains — which is the shape §214 refuses. */}
          {unreachable && live && (
            <p className="canvas-widget-empty" data-testid="action-form-unreachable">
              {unreachable}
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

CanvasActionForm.craft = {
  displayName: "Action form",
  props: {
    actionTypeId: null, subjectVariable: null, title: "", hideHeader: false,
    parameterDefaults: {}, invalidState: "disabled", outputVariable: null, actions: [],
    layout: "form", layoutSwitch: false, prefillVariable: null,
  },
  related: { settings: settingsPanel("ActionFormSettings") },
};

/** A Metric Card: one number over an object set (roadmap 1.5).
 *
 * The widget Workshop apps lead with, and the one that makes an object set
 * worth having as a shared thing: the card, the table and the chart all read
 * *the same* variable, so "127 sites" and the rows under it cannot disagree.
 *
 * All six of `object_sets`' aggregations. Only `count` and `count_distinct`
 * were offered until §229, because those are the two the stores answered
 * identically over *untyped* properties - and §220 typed them, §226 shipped the
 * other four. The rules are `metric-card.ts`, including the divergence from
 * p.328 that shapes this widget: p.328's card reads a *variable* and something
 * else computes the number.
 */
export function CanvasMetricCard({
  objectSetVariable = null,
  aggregation = "count",
  property = null,
  label = "",
  showVisualization = false,
  visualizationPosition = DEFAULT_SPARK_POSITION,
  seriesVariable = null,
  valueFormat = null,
  valueRules = null,
  size = "regular",
  description = "",
  sparkRange = "all",
  sparkStart = null,
  sparkEnd = null,
  baseline = null,
  showSecondary = false,
  secondaryLabel = "",
  secondaryAggregation = "count",
  secondaryProperty = null,
  secondaryFormat = null,
  metrics = [],
  sparkAgo = null,
  sparkAgoUnit = "week",
  sparkAhead = null,
  sparkAheadUnit = "day",
  baselineKind = null,
  baselineProperty = null,
  baselineSummary = "last",
  layoutStyle = "card",
  direction = "horizontal",
  template = "stacked",
}: {
  objectSetVariable?: string | null;
  /** p.591's relative range (§534): so many units ago, to so many ahead. */
  sparkAgo?: unknown;
  sparkAgoUnit?: string;
  sparkAhead?: unknown;
  sparkAheadUnit?: string;
  /** p.592's baseline type (§534), and the summary a series baseline takes. */
  baselineKind?: string | null;
  baselineSummary?: string;
  /** p.593's Numeric property baseline (§563): a property of the series'
   * own object. */
  baselineProperty?: string | null;
  /** p.325's group (§533): the metrics after this card's own first one. */
  metrics?: unknown;
  /** p.326's layout style, and its direction and template. */
  layoutStyle?: string;
  direction?: string;
  template?: string;
  /** p.329's secondary metric (§528): a second aggregation of the same set,
   * configured as the primary is. */
  showSecondary?: boolean;
  secondaryLabel?: string;
  secondaryAggregation?: string;
  secondaryProperty?: string | null;
  secondaryFormat?: unknown;
  /** p.326's metric size (§526). */
  size?: string;
  /** p.328's description, shown on the "i tooltip" (§526). */
  description?: string;
  /** p.330's sparkline time range, and a custom range's ends (§526). */
  sparkRange?: string;
  sparkStart?: string | null;
  sparkEnd?: string | null;
  /** p.330's baseline, p.592's Static kind (§526). */
  baseline?: unknown;
  /** p.310's six, as `metric-card.ts` lists them. */
  aggregation?: string;
  property?: string | null;
  label?: string;
  /** p.329's "Show visualization?" - a sparkline of a time series beside the
   * number - and its two settings. */
  showVisualization?: boolean;
  visualizationPosition?: string;
  seriesVariable?: string | null;
  /** p.328's "Numeric formatting", which is p.174's module-local value
   * formatting. Read through `numberFormatOf` rather than used as given,
   * because a layout document holds whatever was put there (§212). */
  valueFormat?: unknown;
  /** p.329's **Conditional formatting**: "apply rule-based formatting to the
   * metric value displayed, as in the example below that displays the metric
   * in red if its value is less than or equal to zero, and in green
   * otherwise." p.175 is the page it points at. */
  valueRules?: unknown;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, mode } = useCanvasEnv();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending, events: moduleEvents } = useCanvasVariables();
  // p.330's **Interactive metric**: "An optional configuration to trigger a
  // command, action, or event upon card selection. Defaults to No
  // interaction." Wired in the Events panel as the card's `click` (§527); a
  // card with nothing wired is not a control, which is p.330's default.
  const eventContext = useEventContext(undefined, useOverlayIds());
  const selected = eventsFor(moduleEvents, nodeId, "click");
  const interactive = mode === "run" && selected.length > 0;
  const select = () => {
    if (interactive) runEvents(selected, eventContext);
  };
  // p.329's sparkline: the same read the Chart makes of a time series set
  // variable, through the hook they share (§292).
  // p.326: "time series visualizations are only supported in this layout
  // style" (Card), so a Tag or List group draws no line.
  const style = metricLayoutStyleOf(layoutStyle);
  const drawsSpark = metricShowsSpark(showVisualization, seriesVariable) && sparkAllowedIn(style);
  const extras = extraMetricsOf(metrics);
  const arrangement = metricLayoutSettings(style);
  const groupDirection = arrangement.direction ? metricDirectionOf(direction) : "vertical";
  const groupTemplate = arrangement.template ? metricTemplateOf(template) : "side_by_side";
  // p.175's rules, matched against the number this card is showing. One match
  // for both marks, the same as the table's column.
  const cardRules = useMemo(() => rulesOf(valueRules), [valueRules]);
  // p.330's time range, as a range transform after the variable's own. The
  // widget's, not the variable's: two cards can show one series over two
  // ranges. `pageNow` is p.591's "current time … when it is first needed".
  const rangeTransform = useMemo(
    () => metricSparkRangeTransform(sparkRange, sparkStart, sparkEnd, pageNow(), {
      ago: sparkAgo, agoUnit: sparkAgoUnit, ahead: sparkAhead, aheadUnit: sparkAheadUnit,
    }),
    [sparkRange, sparkStart, sparkEnd, sparkAgo, sparkAgoUnit, sparkAhead, sparkAheadUnit],
  );
  const spark = useSeriesPoints(
    workspaceId, drawsSpark ? seriesVariable : null, rangeTransform ? [rangeTransform] : [],
  );
  const info = metricDescriptionOf(description);
  // p.592's baseline: a typed value, or the series' own summary (§534).
  const kindOfBaseline = baselineKindOf(baselineKind, baseline);
  // §563: p.593's numeric property, read off the object the series is of -
  // "the object type feeding the widget", for a card whose line is one
  // object's series.
  const baselineObject = useQuery({
    queryKey: ["metric-baseline-object", spark.ref?.object_type_id, spark.ref?.instance_id],
    queryFn: () => objApi.getInstance(workspaceId, spark.ref!.object_type_id, spark.ref!.instance_id),
    enabled: kindOfBaseline === "property" && !!baselineProperty && !!spark.ref,
  });
  const baselineValue = kindOfBaseline === "static"
    ? metricBaselineOf(baseline)
    : kindOfBaseline === "series"
      ? summarise((spark.points ?? []).map((p) => p.value as number), baselineSummary)
      : kindOfBaseline === "property"
        ? baselineFor({ kind: "property", property: String(baselineProperty ?? "") },
            baselineObject.data?.properties ?? {}, [])
        : null;
  const sparkMissing = metricSparkEmptyReason(showVisualization, seriesVariable);

  // `null` while the setting is unfinished - an aggregation whose property has
  // not been chosen yet. The server answers that with a sentence about property
  // types, and showing it here would report a half-filled panel as a failure of
  // the data (§223, §228).
  const ask = metricRequest(aggregation, property);
  const metric = useQuery({
    queryKey: [
      "canvas-metric", objectSetVariable, JSON.stringify(setDefinition ?? null),
      ask?.aggregation ?? null, ask?.property ?? null,
    ],
    queryFn: () => objApi.aggregateObjectSet(workspaceId, setDefinition, ask ?? {}),
    enabled: !!objectSetVariable && !!setDefinition && !!ask,
  });

  // p.329's secondary metric, asked of the same set. `null` while its
  // property is unchosen, for the primary's reason above.
  const secondAsk = showSecondary === true ? metricRequest(secondaryAggregation, secondaryProperty) : null;
  const second = useQuery({
    queryKey: [
      "canvas-metric", objectSetVariable, JSON.stringify(setDefinition ?? null),
      secondAsk?.aggregation ?? null, secondAsk?.property ?? null,
    ],
    queryFn: () => objApi.aggregateObjectSet(workspaceId, setDefinition, secondAsk ?? {}),
    enabled: !!objectSetVariable && !!setDefinition && !!secondAsk,
  });

  // **Matched against the aggregate, not against the series.** p.329's example
  // is about "its value" - the metric - and the sparkline beside it is the
  // history of a different number entirely. A rule reading the line's latest
  // point would colour the metric by something the metric does not show.
  const cardPaint = paintFor(
    cardRules,
    METRIC_SUBJECT,
    typeof metric.data?.value === "number" ? metric.data.value : null,
    { pending: metric.isPending },
  );

  const spine = (
    <>
        {!objectSetVariable ? (
          <p className="canvas-widget-empty">Pick an object set variable in Settings</p>
        ) : variablesPending || metric.isPending ? (
          // Not "0". A card that showed a number it did not have would be
          // believed, and nobody re-reads a figure that looked fine.
          <span className="metric-value soft" data-testid="metric-pending">…</span>
        ) : metric.isError ? (
          <p className="canvas-widget-empty" data-testid="metric-error">
            {(metric.error as Error).message}
          </p>
        ) : (
          // **Not `.toLocaleString()` on the value directly.** §226 made an
          // aggregation over an empty set answer `null`, and a card is one
          // large number somebody reads at a glance - so it says there is
          // nothing rather than throwing, or worse, showing a zero.
          <span
            className="metric-value"
            data-testid="metric-value"
            style={cssFor(cardPaint)}
          >
            {metricValueLabel(metric.data?.value, numberFormatOf(valueFormat))}
          </span>
        )}
    </>
  );

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {/* p.325-326's group and its layout (§533). A Tag's template and a
          List's direction are not settings p.326 gives them, so each takes
          the arrangement its style implies. */}
      <div className={`metric-group metric-group--${style} metric-group--${groupDirection} metric-group--${groupTemplate}`}
           data-testid="metric-group" data-layout={style} data-direction={groupDirection}
           data-template={groupTemplate}>
      <div className={`metric-card metric-item metric-card--${metricSizeOf(size)}${interactive ? " metric-card--interactive" : ""}`}
           data-testid="metric-card"
           data-size={metricSizeOf(size)}
           // A control only when something is wired to it: role and focus
           // on a card that does nothing would be a button that does nothing.
           {...(interactive ? {
             role: "button", tabIndex: 0, "aria-label": label || "Metric",
             onClick: select,
             onKeyDown: (e: React.KeyboardEvent) => {
               if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
             },
           } : {})}>
        <span className="metric-label">
          {label || "Metric"}
          {info && (
            <span className="metric-info" title={info} aria-label={info} role="img"
                  data-testid="metric-description">
              i
            </span>
          )}
        </span>
        {/* p.329's Position: "Side-by-side (alongside) or Stacked (under)
            with the metric value". The number and the line are one block
            either way - the setting chooses the direction, so there is one
            arrangement rather than two layouts to keep in step. */}
        <div
          className={`metric-body metric-body--${metricSparkPositionOf(visualizationPosition)}`}
          data-testid="metric-body"
          data-position={metricSparkPositionOf(visualizationPosition)}
        >
          {spine}
          {drawsSpark && (
            <span className="metric-spark" data-testid="metric-spark">
              {/* `unresolved` is not "no readings": the variable points at an
                  object nobody has picked yet, so nothing has been asked. A
                  line here would be a reading the widget never took. */}
              {spark.unresolved ? (
                <span className="soft canvas-series-empty" data-testid="metric-spark-unpicked">
                  Nothing picked yet
                </span>
              ) : (
                <Sparkline
                  points={spark.points}
                  pending={spark.isPending}
                  testId="metric-spark-line"
                  colour={strokeFor(cardPaint)}
                  baseline={baselineValue}
                />
              )}
            </span>
          )}
        </div>
        {/* p.329: "under the primary metric". */}
        {showSecondary === true && objectSetVariable && (
          <span className="metric-secondary" data-testid="metric-secondary">
            <span className="metric-secondary-label">
              {metricSecondaryLabelOf(secondaryLabel, secondaryAggregation)}
            </span>{" "}
            <span className="metric-secondary-value" data-testid="metric-secondary-value">
              {second.isError
                ? (second.error as Error).message
                : variablesPending || second.isPending
                  ? "…"
                  : metricValueLabel(second.data?.value, numberFormatOf(secondaryFormat))}
            </span>
          </span>
        )}
        {/* A toggle switched on with nothing chosen. Said in edit mode only:
            a builder needs to know what is missing, and a reader would see an
            unexplained gap where a chart was promised. */}
        {sparkMissing && mode === "edit" && (
          <p className="canvas-widget-empty" data-testid="metric-spark-missing">
            {sparkMissing}
          </p>
        )}
      </div>
      {objectSetVariable && extras.map((extra) => (
        <ExtraMetricItem
          key={extra.id}
          metric={extra}
          size={metricSizeOf(size)}
          workspaceId={workspaceId}
          objectSetVariable={objectSetVariable}
          setDefinition={setDefinition}
          variablesPending={variablesPending}
        />
      ))}
      </div>
    </div>
  );
}

/** One metric of p.325's group after the first (§533): its own aggregation
 * of the card's set, labelled and formatted. */
function ExtraMetricItem({
  metric, size, workspaceId, objectSetVariable, setDefinition, variablesPending,
}: {
  metric: ExtraMetric;
  size: string;
  workspaceId: string;
  objectSetVariable: string;
  setDefinition: unknown;
  variablesPending: boolean;
}) {
  const ask = metricRequest(metric.aggregation, metric.property);
  const answer = useQuery({
    queryKey: [
      "canvas-metric", objectSetVariable, JSON.stringify(setDefinition ?? null),
      ask?.aggregation ?? null, ask?.property ?? null,
    ],
    queryFn: () => objApi.aggregateObjectSet(workspaceId, setDefinition, ask ?? {}),
    enabled: !!setDefinition && !!ask,
  });
  return (
    <div className={`metric-card metric-item metric-card--${size}`} data-testid="metric-extra"
         data-metric={metric.id}>
      <span className="metric-label">{metricLabelOf(metric)}</span>
      <span className="metric-value" data-testid="metric-extra-value">
        {answer.isError
          ? (answer.error as Error).message
          : variablesPending || answer.isPending
            ? "…"
            : metricValueLabel(answer.data?.value, numberFormatOf(metric.valueFormat))}
      </span>
    </div>
  );
}

CanvasMetricCard.craft = {
  displayName: "Metric card",
  props: {
    objectSetVariable: null, aggregation: "count", property: null, label: "",
    valueFormat: null, valueRules: null,
    showVisualization: false, visualizationPosition: DEFAULT_SPARK_POSITION,
    seriesVariable: null,
    size: "regular", description: "", sparkRange: "all", sparkStart: null, sparkEnd: null,
    baseline: null,
    showSecondary: false, secondaryLabel: "", secondaryAggregation: "count",
    secondaryProperty: null, secondaryFormat: null,
    metrics: [], layoutStyle: "card", direction: "horizontal", template: "stacked",
    sparkAgo: null, sparkAgoUnit: "week", sparkAhead: null, sparkAheadUnit: "day",
    baselineKind: null, baselineSummary: "last", baselineProperty: null,
  },
  related: { settings: settingsPanel("MetricCardSettings") },
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
  dropHandling = false,
  dropLabel = "",
  dropIcon = "",
  dropVariable = null,
  showHeader = false,
  headerIcon = "",
  description = "",
  headerStyle = null,
  headerWidgets = 0,
  children,
}: {
  /** p.62's Inner section style (§704) for the sections directly inside -
   * read by them off the layout tree (`useInheritedSectionStyle`), so this
   * section does nothing with it itself. */
  innerSectionStyle?: string | null;
  /** p.13's "toggle on the options for Section Header" (§473): a header
   * with the `title`, an icon and a description, drawn whether or not the
   * section collapses. A collapsible section has always drawn a header of its
   * own; this is the same header for one that does not. */
  showHeader?: boolean;
  /** p.15's section icon, typed as every icon here is. */
  headerIcon?: string;
  /** p.28's "subheadings to provide context for section headers as a
   * rendered Description". */
  description?: string;
  /** p.58's Block, Contained or Floating (`section-header.ts`). Unset is
   * Block, or the parent's p.62 preset's format (§704). */
  headerStyle?: string | null;
  /** p.14's (+) "on the right" of a section header (§680): how many of the
   * first children sit in the header rather than the body
   * (`section-header.headerCount`). */
  headerWidgets?: number;
  /** p.564-568's **Drop Handling**: this section becomes a drop zone for
   * objects dragged from a table cell, an Object View's icon or an Object Set
   * Title (p.569-570). Off by default, because a section that swallowed every
   * drag on the page would be a surprise. */
  dropHandling?: boolean;
  /** p.566's Drop label and Drop icon: what the zone shows while something
   * droppable is over it. The icon is a name from the set or up to four typed
   * characters (§706). */
  dropLabel?: string;
  dropIcon?: string;
  /** p.568's Output object set: where the dropped objects are written, as the
   * clause list a `narrow_set` reads (`drag-payload.ts`). */
  dropVariable?: string | null;
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
  const saved = useSavedColours();
  // Whether this section is on a closed page or in a closed tab, so a tab of
  // its own stays closed inside one (§711).
  const offLayout = React.useContext(OffLayout);
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
  // p.14's header widgets come off the front, so everything below - tabs,
  // proportions, handles - counts only what is in the body.
  const all = childList(children);
  const inHeader = headerCount(headerWidgets, all.length, showHeader === true);
  const headerParts = all.slice(0, inHeader);
  const parts = all.slice(inHeader);

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

  // p.564-568's drop zone. The hooks run whether or not drop handling is on,
  // for the reason the collapse block gives: a hook that depends on a toggle
  // is a hook-order bug waiting for the first author who flips it.
  const { events: moduleEvents } = useCanvasVariables();
  const dropEvents = eventsFor(moduleEvents, nodeId, "drop");
  const dropContext = useEventContext(undefined, useOverlayIds());
  const [dragOver, setDragOver] = React.useState(false);
  const [dropRefused, setDropRefused] = React.useState(false);
  // **Run mode only.** In the builder a drag is the builder moving widgets
  // around, and a section that caught it would be a section nobody could drop
  // a widget into.
  const dropZone = dropHandling && mode === "run";
  // `dragenter` as well as `dragover`: the first is what lights the zone the
  // moment a payload arrives, and the second - repeated while it stays - is
  // what a browser needs cancelled before it will let anything be dropped.
  const acceptDrag = (event: React.DragEvent) => {
    // Only a drag carrying one of the two types p.568 names. Anything else
    // - a file, a link, some text - passes over as though nothing were here.
    if (!carriesPayload(Array.from(event.dataTransfer.types))) return;
    event.preventDefault();
    // The innermost zone takes it, so a drop zone inside another one is
    // not also a drop on the outer.
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
    setDragOver(true);
    setDropRefused(false);
  };
  const dropHandlers = dropZone ? {
    onDragEnter: acceptDrag,
    onDragOver: acceptDrag,
    onDragLeave: (event: React.DragEvent) => {
      // `dragleave` fires on every child the pointer crosses, so it only
      // counts once the pointer has left the section itself. **By position,
      // not by `relatedTarget`**: Chromium sends a drag's leave with no
      // related target, so "is it still inside?" asked that way always
      // answers no, and the overlay went out at the first child boundary.
      const box = event.currentTarget.getBoundingClientRect();
      const inside = event.clientX > box.left && event.clientX < box.right
        && event.clientY > box.top && event.clientY < box.bottom;
      if (!inside) setDragOver(false);
    },
    onDrop: (event: React.DragEvent) => {
      if (!carriesPayload(Array.from(event.dataTransfer.types))) return;
      event.preventDefault();
      event.stopPropagation();
      setDragOver(false);
      const clauses = droppedClauses((type) => event.dataTransfer.getData(type));
      // Said, rather than ignored: a drop that did nothing looks exactly like
      // a drop zone that is broken.
      setDropRefused(clauses === null);
      if (clauses === null) return;
      if (dropVariable) setVariable(dropVariable, clauses);
      if (dropEvents.length > 0) {
        const keys = clauses[1]?.value;
        runEvents(dropEvents, {
          ...dropContext,
          payload: { count: Array.isArray(keys) ? keys.length : 0 },
        });
      }
    },
  } : {};

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

  // p.62's Inner section style (§704): the parent's preset, under whatever
  // of these three this section set itself.
  const look = sectionLook({ headerStyle, border, background }, useInheritedSectionStyle());
  // p.58's header formats. A floating header moves the section's box to the
  // body (`section-header.styleTarget`), so the header sits on the parent.
  const withHeader = showHeader === true;
  const formatted = headerStyleOf(look.headerStyle);
  const { padding: boxPadding, ...boxStyle } = styleFor(
    { background: look.background, padding, customPadding, border: look.border }, saved,
  ) as React.CSSProperties;
  const bodyBackground = resolveBackground(look.body, saved);
  const boxOnBody = styleTarget(withHeader, formatted) === "body";
  const paddingOnBody = paddingTarget(withHeader, formatted) === "body";
  const toggle = collapsible ? (
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
  ) : null;

  if (hidden) return null;
  return (
    <div
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-section canvas-section--${direction}${
        withHeader ? ` canvas-section--header-${formatted}` : ""}`}
      // p.59-60: "widgets within that section automatically switch between
      // light and dark mode based on the brightness of the background".
      data-scheme={schemeFor({ background: look.background }, saved)}
      style={{
        ...(boxOnBody ? {} : boxStyle),
        ...(paddingOnBody ? {} : { padding: boxPadding }),
      }}
      data-drop-zone={dropZone ? (dragOver ? "over" : "ready") : undefined}
      data-testid={dropZone ? `drop-zone-${nodeId}` : undefined}
      {...dropHandlers}
    >
      {marker && <p className="canvas-hidden-marker">{marker}</p>}
      {dropZone && dragOver && (
        // p.566: "the text and icon that will appear on the drop zone" while a
        // payload is over it. Drawn over the section's contents rather than in
        // place of them, so what is being dropped onto stays visible.
        <div className="canvas-drop-overlay" data-testid={`drop-overlay-${nodeId}`}>
          {dropIcon.trim() && <span aria-hidden="true"><IconOrGlyph value={dropIcon} max={4} /></span>}
          <span>{dropLabel.trim() || "Drop here"}</span>
        </div>
      )}
      {dropZone && dropRefused && (
        <p className="state error" role="status" data-testid={`drop-refused-${nodeId}`}>
          That drag did not carry objects this zone can take.
        </p>
      )}
      {withHeader ? (
        <div
          className={`canvas-section-header canvas-section-header--${formatted}`}
          data-testid={`section-header-${nodeId}`}
        >
          {headerIcon.trim() && (
            <span className="canvas-section-header-icon" aria-hidden="true">
              <IconOrGlyph value={headerIcon} />
            </span>
          )}
          <div className="canvas-section-header-text">
            {/* p.28: section headers are "the second largest text", under the
                page header - so a heading, and the collapse control is that
                heading when the section collapses. */}
            {toggle ?? <h3 className="canvas-section-title">{title || "Section"}</h3>}
            {description.trim() && (
              <p className="canvas-section-description">{description}</p>
            )}
          </div>
          {headerParts.length > 0 && (
            // p.14: "the plus sign (+) on the right" - the header's widgets
            // sit after its title, at the far end of the bar.
            <div
              className="canvas-section-header-widgets"
              data-testid={`section-header-widgets-${nodeId}`}
            >
              {headerParts}
            </div>
          )}
        </div>
      ) : toggle}
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
          {dropHandling ? " · drop zone" : ""}
        </p>
      )}
      <div
        className="canvas-section-parts"
        // `hidden` rather than not rendering: a collapsed section keeps its
        // children mounted, so a table inside one does not refetch every time
        // somebody opens it - and a widget that was mid-edit is still there.
        hidden={shut}
        style={{
          ...(boxOnBody ? boxStyle : {}),
          ...(bodyBackground ? { background: bodyBackground } : {}),
          ...(paddingOnBody ? { padding: boxPadding } : {}),
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
                  // The panel stays, `hidden`; what is *in* it is closed as a
                  // closed page's is (§711, below), so a widget remounts when
                  // its tab comes back - p.182's Default - unless it is set
                  // to Never unmount, which is the setting for a table that
                  // should not refetch.
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
              {tabbed ? (
                // p.182's Default unmount (§711): a widget "unmounts when its
                // containing layout is no longer rendered; for example, when
                // the user switches to another tab or page". A tab not showing
                // is closed as a closed page is, so its widgets are not
                // mounted unless one is set to Eagerly mount or Never unmount
                // - and inside a closed page it stays closed. Run mode only,
                // which `CanvasNode` already asks: the builder draws every tab.
                <OffLayout.Provider value={offLayout || labels[index] !== showing}>
                  {child}
                </OffLayout.Provider>
              ) : child}
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

CanvasSection.craft = {
  displayName: "Section",
  props: {
    direction: "columns", weights: "", gap: 12, minHeight: 0, visibleWhen: null, scroll: false,
    background: null, padding: null, customPadding: null, border: null,
    collapsible: false, collapsedByDefault: false, collapsedWhen: null, title: "",
    tabs: "", tabVariable: null,
    dropHandling: false, dropLabel: "", dropIcon: "", dropVariable: null,
    // `headerStyle` unset rather than "block", which draws the same: a stored
    // "block" is a choice, and would keep a parent's p.62 preset (§704) from
    // giving this section its header format.
    showHeader: false, headerIcon: "", description: "", headerStyle: null, headerWidgets: 0,
    innerSectionStyle: null,
  },
  isCanvas: true,
  related: { settings: settingsPanel("SectionSettings") },
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
  background = null,
  titleColour = null,
  icon = "",
  iconColour = null,
  logoImage = null,
  logoHeight = DEFAULT_LOGO_HEIGHT,
  logoPosition = null,
  collapsedImage = null,
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
  /** p.47: "Select a background color for the header."
   *
   * The style block's own prop and resolver (§184, §414), so a header takes a
   * preset, a typed hex or a saved colour by the same rules a section does —
   * and p.59-60's brightness rule comes with it, which matters more here than
   * anywhere: the buttons and tabs a header holds are the module's navigation,
   * and dark navigation on a dark header is a module nobody can steer. */
  background?: string | null;
  /** p.47: "Choose a custom color for the title text."
   *
   * Null is the theme's ink rather than a colour of its own: a default written
   * into every document is a value that stops following the theme the moment
   * the theme changes. */
  titleColour?: string | null;
  /** p.47's application logo: *"Enable an application logo by choosing an icon
   * or uploading an image. **Icon:** Choose an icon and an icon color."*
   *
   * **An icon from the set, or one or two typed characters** (§445, §706):
   * §445 built the glyph when this platform had no icon set, and §706 lets
   * p.47's "Choose an icon" choose from the one decision 0019 added. An emoji
   * or an initial still works, since it is a mark somebody recognises.
   *
   * p.47's **Image** half is `logoImage` (§472). */
  icon?: string;
  /** p.47: *"Choose an icon and an icon color."* Null is the theme's ink, for
   *  `titleColour`'s reason — a default written into every document stops
   *  following the theme the moment the theme changes. */
  iconColour?: string | null;
  /** p.47's "Image: … upload one from your computer" (§472): an attachment
   * reference, shown in place of the icon (`header-logo.ts`). */
  logoImage?: ImageRef | null;
  /** p.47's "Customize the image height", in pixels. */
  logoHeight?: number;
  /** p.47's "left, center, or right for horizontal headers; … top or bottom
   * for vertical headers". Null is the first of those. */
  logoPosition?: string | null;
  /** p.48's "custom image for the collapsed state", shown only beside a
   * header image, as p.49 says. */
  collapsedImage?: ImageRef | null;
  children?: React.ReactNode;
}) {
  const {
    connectors: { connect, drag },
    childIds,
  } = useNode((node) => ({ childIds: node.data.nodes ?? [] }));
  const { query } = useEditor();
  const saved = useSavedColours();
  // `{{v_id}}` like every other text, so a header can name what the viewer is
  // looking at rather than only what the app is called.
  const { resolved } = useCanvasVariables();
  const vertical = orientation === "vertical";
  const [collapsed, setCollapsed] = useState(collapsible && collapsedByDefault);
  // Collapsing is a vertical-header affordance (p.48); a horizontal header that
  // had been collapsed and then switched would otherwise stay hidden with no
  // control left to undo it.
  const isCollapsed = vertical && collapsible && collapsed;
  // p.47-49's logo: an image over an icon, and the collapsed image when
  // collapsed (`header-logo.ts`).
  const { workspaceId } = useCanvasEnv();
  const mark = headerMark({ icon, image: logoImage, collapsedImage, collapsed: !!isCollapsed });
  const logoUrl = useAttachmentUrl(
    workspaceId, mark?.kind === "image" ? mark.image.key : null,
    mark?.kind === "image" ? mark.image.content_type : "",
  );
  const position = logoPositionOf(logoPosition, orientation);

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
        // p.59-60 one level up, exactly as a section does it: the stylesheet
        // redefines the ink and line tokens beneath this attribute, so the
        // buttons and tabs inside stay legible without knowing the header has
        // a colour at all.
        data-scheme={schemeFor({ background }, saved)}
        // **Says a colour was chosen, not which one.** The header has no
        // horizontal padding by default - it sits flush with the page it
        // titles - and a coloured band flush to the edge reads as a rendering
        // fault rather than as a choice. The padding belongs with the colour,
        // and CSS is where it can be added without the untinted header moving.
        data-tinted={resolveBackground(background, saved) ? "true" : undefined}
        style={{
          ...styleFor({ background }, saved),
          ...(vertical
            ? { width: isCollapsed ? 56 : width, flex: `0 0 ${isCollapsed ? 56 : width}px` }
            : height > 0
              ? { minHeight: height }
              : {}),
        }}
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
        {/* p.47's logo. **It survives the collapsed state, where the title
            does not**, and the two are different things rather than an
            inconsistency: p.49 drops *labels*, and a logo is a mark rather
            than a word — a collapsed header with nothing at the top of it is
            one nobody can tell from a blank rail. */}
        {mark?.kind === "icon" && (
          <span
            className={`canvas-header-logo canvas-header-logo--${position}`}
            data-testid="header-logo"
            style={{ color: resolveBackground(iconColour, saved) ?? undefined }}
          >
            <IconOrGlyph value={mark.text} size={18} />
          </span>
        )}
        {mark?.kind === "image" && (
          <span
            className={`canvas-header-logo canvas-header-logo--${position}`}
            data-testid="header-logo-image"
            data-position={position}
          >
            {logoUrl && (
              <img
                src={logoUrl}
                alt={title.trim() ? `${interpolate(title, resolved)} logo` : "Logo"}
                data-filename={mark.image.filename}
                // Collapsed, the rail is 56px wide, so the image fits it
                // rather than holding the height it has when open.
                style={isCollapsed
                  ? { maxWidth: 40, maxHeight: 40 }
                  : { height: logoHeightOf(logoHeight), maxWidth: "100%" }}
              />
            )}
          </span>
        )}
        {/* The title goes with the text: p.49 drops labels in the collapsed
            state, and a title is nothing but a label. */}
        {!isCollapsed && title.trim() && (
          <p
            className="canvas-header-title"
            style={{ color: resolveBackground(titleColour, saved) ?? undefined }}
          >
            {interpolate(title, resolved)}
          </p>
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
 * Foundry drops the label and shows the configured icon (a name from the set
 * or typed characters, §706). An unset icon falls back to the label's first
 * character rather than to nothing - a collapsed header of blank buttons is
 * worse than an approximate glyph, because there is no way to tell which one
 * is which. */
function glyphFor(icon: string | undefined, label: string | undefined): string {
  const chosen = (icon ?? "").trim();
  if (chosen) return chosen;
  return (label ?? "").trim().charAt(0).toUpperCase() || "•";
}

CanvasHeader.craft = {
  displayName: "Header",
  props: {
    title: "", sticky: true, orientation: "horizontal",
    height: 0, width: 220, collapsible: false, collapsedByDefault: false,
    background: null, titleColour: null,
    // p.47's application logo (§445). Empty is no logo, which is what a
    // header has had until now.
    icon: "", iconColour: null,
    // p.47's image half and p.48's collapsed image (§472). Null is none, and
    // null position is the first for the orientation - the icon's old place.
    logoImage: null, logoHeight: DEFAULT_LOGO_HEIGHT, logoPosition: null, collapsedImage: null,
    // p.47's favourite toggle. **Written into new documents as `true` and
    // read as "not false" everywhere else** (`module-header.ts`): a default
    // in `craft.props` reaches the document somebody is editing now and no
    // document written before it existed, so the reader cannot rely on the
    // key being there and the two have to agree on what absent means.
    allowFavourite: true,
  },
  isCanvas: true,
  related: { settings: settingsPanel("HeaderSettings") },
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
  /** p.62's Inner section style (§704), for the sections directly on the
   * page; they read it off the layout tree. */
  innerSectionStyle?: string | null;
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
  const saved = useSavedColours();
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

  // p.182's Eagerly mount and Never unmount (§609): a closed page renders
  // hidden rather than not at all when something on it may stay mounted, and
  // tells what it holds that it is closed, so everything else on it is not
  // mounted - as a closed page's widgets never were. A page holding none of
  // them is `null`, as it always was.
  if (mode === "run" && !active && !holdsKept(query, nodeId)) return null;

  return (
    <section
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-page${active ? " on" : ""}`}
      data-scheme={schemeFor({ background }, saved)}
      // Inline rather than the `hidden` attribute, which any `display` rule on
      // `.canvas-page` would override - a closed page drawn over the open one.
      style={{
        ...styleFor({ background, padding, customPadding }, saved),
        ...(mode === "run" && !active ? { display: "none" } : {}),
      }}
      data-closed={mode === "run" && !active ? "yes" : undefined}
    >
      {mode === "edit" && (
        <p className="canvas-page-label">
          {title}
          {active ? " · shown first" : ""}
        </p>
      )}
      <OffLayout.Provider value={mode === "run" && !active}>{children}</OffLayout.Provider>
      {/* p.52's picker, "at the bottom of the page" and only while editing:
          it is an authoring control, and a reader has no layout to choose. */}
      {mode === "edit" && <LayoutTemplatePicker pageId={nodeId} />}
    </section>
  );
}

CanvasPage.craft = {
  displayName: "Page",
  props: {
    title: "Page", icon: "", pageId: "",
    background: null, padding: null, customPadding: null, innerSectionStyle: null,
  },
  isCanvas: true,
  related: { settings: settingsPanel("PageSettings") },
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

CanvasOverlay.craft = {
  displayName: "Overlay",
  props: { title: "Overlay", variant: "modal" },
  isCanvas: true,
  related: { settings: settingsPanel("OverlaySettings") },
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
          {collapsed ? <IconOrGlyph value={glyphFor(page.icon, page.title)} /> : page.title}
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
  intent = null,
  customColour = null,
  leftIcon = "",
  rightIcon = "",
  description = "",
  hideWhenFalse = false,
  minimal = false,
  tag = false,
  large = false,
  fill = false,
  buttonType = "inline",
  items = [],
}: {
  /** p.483's Button type: one button, a button that opens a menu of items, or
   * a main button with a menu beside it (§462). */
  buttonType?: string;
  /** The items of a Menu or Two-part button, each firing its own click
   * events - addressed by id, see `button-items.ts`. */
  items?: unknown;
  /** p.486's Button color: an intent, or `custom` with `customColour`. Unset
   * on a button saved before §461, which `button-look.ts` reads from `style`. */
  intent?: string | null;
  customColour?: string | null;
  /** p.486's Left icon and Right icon, as typed glyphs: this platform has no
   * icon set, the same divergence as `icon` below. */
  leftIcon?: string;
  rightIcon?: string;
  /** p.486's Description: "a tooltip when hovering over the button". */
  description?: string;
  /** p.486's "State if false": hidden rather than disabled while the
   * variable is false. */
  hideWhenFalse?: boolean;
  /** p.486's Display & formatting. */
  minimal?: boolean;
  tag?: boolean;
  large?: boolean;
  fill?: boolean;
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
  const gateFalse = !!enabledVariable && gate !== undefined && !gate;
  const disabled = mode === "edit" || gateFalse;
  const look = buttonLook({ intent, style, customColour, minimal, tag, large, fill });
  const text = interpolate(label ?? "", resolved);
  // p.483's Menu and Two-part types (§462). The menu's open state and its
  // outside-click close are hooks, so they run before the hidden check below
  // for the hook-order reason every widget here gives.
  const kind = buttonTypeOf(buttonType);
  const menuItems = kind === "inline" ? [] : itemsOf(items);
  const [menuOpen, setMenuOpen] = React.useState(false);
  const wrapRef = React.useRef<HTMLSpanElement | null>(null);
  React.useEffect(() => {
    if (!menuOpen) return;
    const away = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [menuOpen]);
  const fireItem = (item: string) => {
    setMenuOpen(false);
    if (mode === "edit") return;
    const itemEvents = eventsFor(moduleEvents, nodeId, "click", item);
    if (itemEvents.length > 0) runEvents(itemEvents, eventContext);
  };
  const anyItemWired = menuItems.some((i) => eventsFor(moduleEvents, nodeId, "click", i.id).length > 0);

  // p.486's "State if false: … disabled or hidden". Hidden only for a reader:
  // a builder who could not see the button could not select it to change the
  // setting back.
  if (hideWhenFalse && gateFalse && mode === "run") return null;

  const menu = menuOpen && (
    <div className="canvas-button-menu" role="menu" aria-label={text}>
      {menuItems.map((item) => (
        <button
          key={item.id}
          type="button"
          role="menuitem"
          className="canvas-button-menu-item"
          title={item.description?.trim() || undefined}
          onClick={() => fireItem(item.id)}
        >
          {item.leftIcon?.trim() && (
            <span className="btn-icon btn-icon--left" aria-hidden="true"><IconOrGlyph value={item.leftIcon} /></span>
          )}
          {interpolate(item.label, resolved)}
        </button>
      ))}
    </div>
  );

  if (kind !== "inline" && !collapsed) {
    // A Menu button *is* its toggle; a Two-part button is its main button with
    // a toggle beside it (p.483).
    const toggle = (
      <button
        type="button"
        className={`${look.className}${kind === "twoPart" ? " btn-split-toggle" : ""}`}
        style={look.style}
        disabled={disabled || menuItems.length === 0}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        aria-label={kind === "twoPart" ? `More options for ${text}` : undefined}
        title={kind === "menu" ? description.trim() || undefined : undefined}
        onClick={() => setMenuOpen((open) => !open)}
      >
        {kind === "menu" && (
          <>
            {leftIcon.trim() && (
              <span className="btn-icon btn-icon--left" aria-hidden="true"><IconOrGlyph value={leftIcon} /></span>
            )}
            {text}{" "}
          </>
        )}
        <span aria-hidden="true">▾</span>
      </button>
    );
    return (
      <span
        ref={(ref) => { wrapRef.current = ref; connectDragDrop(ref, connect, drag); }}
        className={`canvas-button-wrap canvas-button-wrap--menu${fill ? " canvas-button-wrap--fill" : ""}`}
      >
        {kind === "twoPart" ? (
          <span className="btn-split">
            <button
              type="button"
              className={`${look.className} btn-split-main`}
              style={look.style}
              disabled={disabled}
              title={description.trim() || undefined}
              onClick={() => {
                if (mode === "edit") return;
                if (wired.length > 0) runEvents(wired, eventContext);
              }}
            >
              {leftIcon.trim() && (
                <span className="btn-icon btn-icon--left" aria-hidden="true"><IconOrGlyph value={leftIcon} /></span>
              )}
              {text}
            </button>
            {toggle}
          </span>
        ) : toggle}
        {menu}
        {mode === "edit" && menuItems.length === 0 && (
          <span className="canvas-widget-empty"> add items in Settings</span>
        )}
        {mode === "edit" && menuItems.length > 0 && !anyItemWired && (
          <span className="canvas-widget-empty"> no item is wired yet</span>
        )}
      </span>
    );
  }

  return (
    <span
      ref={(ref) => connectDragDrop(ref, connect, drag)}
      className={`canvas-button-wrap${fill ? " canvas-button-wrap--fill" : ""}`}
    >
      <button
        type="button"
        className={`${look.className}${collapsed ? " btn-collapsed" : ""}`}
        style={look.style}
        disabled={disabled}
        // p.486's Description is the tooltip. The label becomes the accessible
        // name when the text is dropped, so a collapsed header is still
        // navigable by anything that is not eyes.
        title={description.trim() || (collapsed ? text : undefined)}
        aria-label={collapsed ? text : undefined}
        onClick={() => {
          if (mode === "edit") return;
          if (wired.length > 0) runEvents(wired, eventContext);
        }}
      >
        {collapsed ? <IconOrGlyph value={glyphFor(icon || leftIcon, label)} /> : (
          <>
            {leftIcon.trim() && (
              <span className="btn-icon btn-icon--left" aria-hidden="true"><IconOrGlyph value={leftIcon} /></span>
            )}
            {text}
            {rightIcon.trim() && (
              <span className="btn-icon btn-icon--right" aria-hidden="true"><IconOrGlyph value={rightIcon} /></span>
            )}
          </>
        )}
      </button>
      {mode === "edit" && !collapsed && wired.length === 0 && (
        <span className="canvas-widget-empty"> nothing wired to this click yet</span>
      )}
    </span>
  );
}

CanvasButton.craft = {
  displayName: "Button",
  props: {
    label: "Button", icon: "", style: "primary", enabledVariable: null,
    // `intent` is null, not "primary": Craft fills a saved node's missing
    // props from these, so a default here would override the `style` of every
    // button saved before §461 - an old danger button turned primary.
    intent: null, customColour: null, leftIcon: "", rightIcon: "", description: "",
    hideWhenFalse: false, minimal: false, tag: false, large: false, fill: false,
    buttonType: "inline", items: [],
  },
  related: { settings: settingsPanel("ButtonSettings") },
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

// ---- Edit History (parity workshop.md §10; Foundry p.402-403; §471) ---------
/**
 * p.402: "The Edit History widget displays the list of user edits made to an
 * object's properties after Track user edit history has been enabled for the
 * object type within Ontology Manager."
 *
 * **One object, the set's first** (p.403's "If the object set contains more
 * than one object, only the first object will be displayed"), read as the
 * Property List reads it. Its edits come from §470's log, keyed `canvas-` so
 * an action run in this module refreshes the history it just added to.
 *
 * **Untracked is said, not shown as empty.** A type whose history is off has
 * no edits because nothing records them, which is a different fact from an
 * object nobody has changed, and only the first is something an author can
 * act on.
 */
export function CanvasEditHistory({
  objectSetVariable = null,
  order = "newest",
  properties = "",
}: {
  objectSetVariable?: string | null;
  /** p.403's Edits sort order. */
  order?: string;
  /** p.403's Property configuration: comma-separated api_names, blank for all. */
  properties?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const setDefinition = useCanvasVariable(objectSetVariable);
  const { pending: variablesPending } = useCanvasVariables();
  const setPage = useSetPage(workspaceId, setDefinition, { pageSize: 1, variablesPending });
  const instance = setPage.rows?.[0];
  const type = useQuery({
    queryKey: ["object-type", setPage.typeId],
    queryFn: () => objApi.getType(workspaceId, setPage.typeId!),
    enabled: !!setPage.typeId,
  });
  const chosen = chosenEditProperties(properties);
  const history = useQuery({
    queryKey: ["canvas-edit-history", setPage.typeId, instance?.primary_key ?? null,
               editOrderOf(order), (chosen ?? []).join(",")],
    queryFn: () => objApi.objectEdits(workspaceId, {
      object_type_id: setPage.typeId!,
      primary_key: String(instance!.primary_key),
      order: editOrderOf(order),
      properties: chosen,
    }),
    enabled: !!setPage.typeId && !!instance,
  });
  const labelOf = (property: string) =>
    (type.data?.properties ?? []).find((p) => p.api_name === property)?.display_name || property;
  const edits = history.data?.edits ?? [];

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {!objectSetVariable ? (
        <p className="canvas-widget-empty">Edit history - bind an object set in Settings</p>
      ) : setPage.unresolved ? (
        <p className="canvas-widget-empty">Resolving the object set…</p>
      ) : !instance ? (
        <p className="canvas-widget-empty">No object to show</p>
      ) : history.data && !history.data.tracking_since && edits.length === 0 ? (
        <p className="canvas-widget-empty" data-testid="edit-history-untracked">
          Edit history is not tracked for this object type - switch on Track user edit
          history in its settings
        </p>
      ) : history.data && edits.length === 0 ? (
        <p className="canvas-widget-empty" data-testid="edit-history-empty">
          No edits since tracking began
        </p>
      ) : (
        <ol className="canvas-edit-history" data-testid="edit-history">
          {edits.map((edit) => (
            <li key={edit.id} data-testid="edit-history-entry" data-kind={edit.kind}>
              <span className="canvas-edit-summary">{editSummary(edit, labelOf)}</span>
              <span className="canvas-edit-meta">
                {edit.editor} · {new Date(edit.edited_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ol>
      )}
      {history.data?.truncated && (
        <p className="canvas-widget-empty">Showing the {edits.length} {editOrderOf(order)} edits</p>
      )}
    </div>
  );
}

CanvasEditHistory.craft = {
  displayName: "Edit history",
  props: { objectSetVariable: null, order: "newest", properties: "" },
  related: { settings: settingsPanel("EditHistorySettings") },
};

// ---- Data Freshness (parity workshop.md §10; Foundry p.399-401; §469) --------
/**
 * p.399: "The Data Freshness widget enables users to track data freshness
 * directly within their application by displaying the Last Updated timestamp
 * corresponding to the most recent index time for configured object types and
 * datasources."
 *
 * **Out of scope until the platform recorded index times, and it now does.**
 * An object type's is §408's watermark, the newest `updated_at` among its
 * instances; a datasource's is its last sync into the type
 * (`object_type_sources.last_synced_at`). Both come from one call,
 * `/object-types/freshness`, which auto-refresh already polls.
 *
 * p.400's format is `data-freshness.ts`: relative within a day, absolute past
 * it, and a source that has never synced says so in words. The relative ones
 * tick over without a reload, and the answer is re-read every minute, because
 * a freshness widget that is itself stale reports the wrong thing about the
 * one thing it is for.
 */
export function CanvasDataFreshness({
  items = [],
  title = "Data freshness",
}: {
  /** p.401's items: an object type each, with the sources shown under it. */
  items?: FreshnessItem[];
  title?: string;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId } = useCanvasEnv();
  const configured = freshnessItemsOf(items);
  const ids = configured.map((i) => i.objectTypeId);
  const fresh = useQuery({
    // `canvas-`, so an action run in this module refreshes it too.
    queryKey: ["canvas-data-freshness", ids.join(",")],
    queryFn: () => objApi.objectTypeFreshness(workspaceId, ids),
    enabled: ids.length > 0,
    refetchInterval: 60_000,
  });
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(tick);
  }, []);
  const byType = new Map((fresh.data?.types ?? []).map((t) => [t.object_type_id, t]));

  return (
    <div ref={(ref) => connectDragDrop(ref, connect, drag)} className="canvas-block">
      {title && <p className="field-label">{title}</p>}
      {configured.length === 0 ? (
        <p className="canvas-widget-empty">Data freshness - add an object type in Settings</p>
      ) : (
        <ul className="canvas-freshness" data-testid="data-freshness">
          {configured.map((item) => {
            const type = byType.get(item.objectTypeId);
            return (
              <li key={item.id} data-testid={`freshness-${item.id}`}>
                <div className="canvas-freshness-row">
                  <span className="canvas-freshness-name">
                    {type?.display_name ?? (fresh.isPending ? "…" : "An object type you cannot see")}
                  </span>
                  {type && (
                    <FreshnessStamp iso={type.updated_at} now={now} />
                  )}
                </div>
                {item.sources.map((source) => {
                  const known = type?.sources.find((s) => s.dataset_id === source.datasetId);
                  return (
                    <div
                      key={source.datasetId}
                      className="canvas-freshness-row canvas-freshness-source"
                      data-testid={`freshness-source-${source.datasetId}`}
                    >
                      <span className="canvas-freshness-name">
                        {source.name ?? known?.dataset_name ?? "A datasource"}
                      </span>
                      {known ? (
                        <FreshnessStamp iso={known.last_synced_at} now={now} />
                      ) : type ? (
                        // Configured, and no longer one of the type's sources
                        // (or not one this reader can see): said, rather than
                        // dated with something that is not its index time.
                        <span className="canvas-freshness-time">Not a source of this type</span>
                      ) : null}
                    </div>
                  );
                })}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function FreshnessStamp({ iso, now }: { iso: string | null; now: number }) {
  const stale = isStale(iso, now);
  return (
    <span
      className={`canvas-freshness-time${stale ? " canvas-freshness-time--stale" : ""}`}
      title={iso ?? undefined}
    >
      {freshnessLabel(iso, now)}
    </span>
  );
}

CanvasDataFreshness.craft = {
  displayName: "Data freshness",
  props: { items: [], title: "Data freshness" },
  related: { settings: settingsPanel("DataFreshnessSettings") },
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
  CanvasFilterPills,
  CanvasSearchBar,
  CanvasUserSelect,
  CanvasProminentTerms,
  CanvasParameterControl,
  CanvasNumericInput,
  CanvasTextInput,
  CanvasStringSelector,
  CanvasDateTimePicker,
  CanvasDateInput,
  CanvasMarkdown,
  CanvasObjectSetTitle,
  CanvasPropertyList,
  CanvasLinksWidget,
  CanvasObjectViewWidget,
  CanvasObjectDropdown,
  CanvasObjectSelector,
  CanvasPieChart,
  CanvasStepper,
  CanvasTimeline,
  CanvasMediaPreview,
  CanvasIframe,
  CanvasDataFreshness,
  CanvasEditHistory,
  CanvasDatasetTable,
  CanvasObjectTable,
  CanvasObjectCards,
  CanvasSearch,
  CanvasPivotTable,
  CanvasTimeSeries,
  CanvasSeriesAnalysis,
  CanvasEmbeddedModule,
  CanvasLoopSection,
  CanvasChart,
  CanvasMap,
  CanvasMetricCard,
  CanvasActionForm,
};

// The list itself is `widget-list.ts`, so a test can read it (§447).
// Re-exported here because every caller has imported it from this module
// since the builder was written — **and narrowed to the resolver's keys on the
// way through**, which is the one thing the data file cannot do for itself: it
// must not import `widgets.tsx` back. The cast is checked by
// `widget-palette.test.ts`, which asserts the two lists hold the same keys.
export const PALETTE = WIDGET_LIST as {
  key: keyof typeof CANVAS_RESOLVER; label: string; hint: string;
}[];

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
