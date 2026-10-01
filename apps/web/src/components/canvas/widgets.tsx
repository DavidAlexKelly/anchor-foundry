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
import {
  actions as actionApi, api, ApiError, canvas as canvasApi, datasets as dsApi,
  objects as objApi,
} from "@/lib/api";
import { eventsOf, variablesOf } from "@/lib/workshop-module";
import { TypePicker } from "@/components/type-picker";
import { VariableBridge } from "./VariableBridge";
import { WidgetSetup } from "./WidgetSetup";
import { StyleFields } from "./StyleFields";
import { refTo } from "./saved-colours";
import { useSavedColours } from "./use-saved-colours";
import {
  resolveBackground, schemeFor, styleFor, textColourChoice,
  type BorderName, type PaddingName, type StyleProps,
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
  canCreate, chosenOf, columnsOf, createdOf, DISPLAYS, displayOf, displaysFor, LAYOUTS,
  layoutOf as optionLayoutOf, layoutStyle, MAX_COLUMNS, MIN_COLUMNS, modeOf,
  optionsOf, outputKind, pick, placeholderOf, SELECTIONS,
  selectionOf as pickModeOf, sourceOf, withTyped,
} from "./string-selector";
import {
  COMMON_ZONES, DATE_FORMATS, DEFAULT_DATE_FORMAT, DEFAULT_PRECISION,
  PRECISIONS, TIME_FORMATS, ZONE_MODES, formatDisplay, fromLocalInput, isZone,
  toLocalInput, zoneLabel, zoneOf, type Precision,
} from "./date-time";
import { DATE_INPUT_MODES, orderedRange, rangeText, shownDay } from "./date-input";
import {
  ALIGNMENTS, alignmentOf, blockAlignment, columnAlignment, parse as parseMarkdown,
  sourceOf as markdownSourceOf, textOf as markdownTextOf,
  type Align, type Block, type Inline,
} from "./markdown";
import {
  autoSelectKey, hasSelection, keysOf, selectionClauses, toggle as toggleKey,
} from "./object-table-selection";
import { layerColorOf, layerOpacityOf, layerVisibleOf } from "./map-layer";
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
import {
  // Aliased for §211's reason: `modeOf` and `chosenOf` already mean the String
  // Selector's in this file, and both of these take different arguments and
  // return different things. Left unaliased they would typecheck at neither
  // call site or - worse - at one of them.
  LINK_MODES, MAX_DEFAULT_EXPAND,
  chosenOf as linkChosenOf, defaultExpandOf, initiallyExpanded, labelFor,
  linkKey, modeOf as linkModeOf, toggleExpanded, visibleLinks,
  LINK_PAGE, objectViewHref, previewOf as linkPreviewOf, previewProperties,
  sortOf as linkSortOf, sortedLinkQuery, titleOf,
  type ChosenLink,
} from "./links-widget";
import { linkSubsetHref } from "@/lib/link-subset";
import { useWorkspaceById } from "@/components/use-workspace";
import {
  // Aliased for §211's reason, and this time the compiler said so rather than
  // letting it through: `emptyMessageOf` already means the Object Table's,
  // which takes two arguments. The two survived the same collision differently
  // only because that one's arity differs — the rule is the same either way.
  VIEW_MODES, allowToggleOf, emptyMessageOf as objectViewEmptyMessageOf,
  hideHeaderOf, viewModeOf,
} from "./object-view-widget";
import {
  // Aliased on §211's rule: `hideHeaderOf` already means the Object View
  // widget's, and the two answer the same question about different widgets —
  // exactly the pair that resolves silently to the wrong one.
  INVALID_STATES, formVisible, headerTitleOf,
  hideHeaderOf as hideActionHeaderOf, invalidStateOf, localDefaultsOf,
} from "./action-form";
import {
  // Aliased on §211's rule: `AGGREGATIONS` and `segmentsOf` are generic enough
  // to collide, and `visibleSlices` sits beside two other `visible*` reads.
  AGGREGATIONS as PIE_AGGREGATIONS, LEGEND_POSITIONS, MAX_INNER_RADIUS,
  aggregationOf as pieAggregationOf,
  aggregationRequest as pieAggregationRequest, innerRadiusOf, legendPositionOf,
  needsProperty as pieNeedsProperty, segmentsOf, showLegendOf, visibleSlices,
} from "./pie-chart";
import {
  // Aliased on §211's rule: this file already has two `AGGREGATIONS` and three
  // `needsProperty`-shaped questions.
  AGGREGATIONS as METRIC_AGGREGATIONS, aggregationOf as metricAggregationOf,
  DEFAULT_SPARK_POSITION, metricRequest, needsProperty as metricNeedsProperty,
  propertiesFor as metricPropertiesFor,
  showsSpark as metricShowsSpark, SPARK_POSITIONS,
  sparkEmptyReason as metricSparkEmptyReason,
  sparkPositionOf as metricSparkPositionOf,
  valueLabel as metricValueLabel,
  METRIC_SIZES, SPARK_RANGES, baselineOf as metricBaselineOf,
  descriptionOf as metricDescriptionOf, metricSizeOf, pageNow, sparkRangeOf as metricSparkRangeOf,
  sparkRangeProblem as metricSparkRangeProblem, sparkRangeTransform as metricSparkRangeTransform,
  secondaryLabelOf as metricSecondaryLabelOf,
  DIRECTIONS as METRIC_DIRECTIONS, LAYOUT_STYLES as METRIC_LAYOUT_STYLES,
  TEMPLATES as METRIC_TEMPLATES, addMetric, directionOf as metricDirectionOf,
  extraMetricsOf, layoutSettings as metricLayoutSettings, layoutStyleOf as metricLayoutStyleOf,
  metricLabelOf, moveMetric, sparkAllowedIn, templateOf as metricTemplateOf,
  type ExtraMetric,
  BASELINE_KINDS, BASELINE_SUMMARIES, RELATIVE_UNITS, baselineKindOf, summarise,
} from "./metric-card";
import { ValueFormatEditor } from "@/components/value-format-editor";
import {
  formatsByColumn, formatSummary, numberFormatOf, type NumberFormat,
} from "./value-formats";
import {
  METRIC_SUBJECT, paintFor, rulesByColumn, rulesOf, SERIES_SUBJECT,
  strokeFor, subjectProperties,
} from "./conditional-formats";
import {
  columnsFor, derivedInputs, problem as columnMathProblem, valueFor,
} from "./derived-columns";
import { derivedCell } from "@/lib/derived-values";
import { unknownColumns, visibleColumns } from "./column-visibility";
import { moved as movedColumn, storageKey as columnsKey, storedChoice, toggled as toggledColumn,
  viewerColumnsOf } from "./viewer-columns";
import { DerivedValue } from "@/components/derived-value";
import { ConditionalFormatEditor } from "@/components/conditional-format-editor";
import type { ConditionalRule, ObjectInstance } from "@/lib/types";
import { latest as latestOf } from "./sparkline";
import {
  // Aliased on the same rule. `PAGE_LIMIT` and `SEARCH_MODES` are generic
  // enough to collide with something later, and `labelOf` is the kind of name
  // three widgets could each want.
  DEFAULT_SORT as DROPDOWN_DEFAULT_SORT,
  PAGE_LIMIT as DROPDOWN_PAGE_LIMIT, SEARCH_MODES, SORTS as DROPDOWN_SORTS,
  allowNoSelectionOf, labelOf as dropdownLabelOf, matchesQuery,
  propertyListOf, searchModeOf, searchProperties, selectionSummary,
  sortOf as dropdownSortOf, titleOf as optionTitleOf, truncationNote,
} from "./object-dropdown";
import {
  ORDERABLE_HINT, orderableProperties, requestSort,
} from "./property-sort";
import {
  // §211's aliasing rule, hardest case yet: this module is *about* users, so
  // almost every export collides with something this file already means by the
  // same word. `usersOf` is the one name nothing else wants.
  SELECTION_MODES as USER_SELECTION_MODES,
  allowClearOf as userAllowClearOf, groupIdsOf as userGroupIdsOf,
  isMultiple as userIsMultiple, labelOf as userLabelOf, modeOf as userModeOf,
  pickedSingle as userPickedSingle, placeholderOf as userPlaceholderOf,
  selectedIds as userSelectedIds, shouldAsk as userShouldAsk,
  summaryOf as userSummaryOf, textOf as userTextOf, toOutput as userToOutput,
  toggled as userToggled, usersOf,
} from "./user-select";
import {
  // §211's aliasing rule again: `MODES`, `describe` and `without` are all names
  // this file could want for something else.
  MODES as PILL_MODES, OPERATOR_LABELS,
  canAdd, canEdit, canRemove, clausesOf, describe as describeClause,
  describe as describeFilterClause,
  editableValue, isEditable, isRemovable, modeOf as pillModeOf, operatorsFor,
  parseValue, withValue, without,
} from "./filter-clause";
import {
  LINK_SCOPES, MAX_SUGGESTED, PROPERTY_SCOPES, availableLinks, availableProperties, describeLinked,
  linkMenu, linkScopeOf, placeholderOf as searchPlaceholderOf, propertyScopeOf, searchMenu,
  suggestionDefinition, suggestionsOf, withLinkedFilter, type LinkEntry, type MenuEntry,
  type Link as SearchLink,
} from "./search-bar";
import { nextIndex } from "@/lib/search-keys";
import { hasItems, submittedValues } from "@/lib/array-parameter";
import {
  // §211's aliasing rule: `labelOf` is a name half the widgets here could want,
  // and `MAX_TERMS` says nothing about which list it caps once it is in this
  // file rather than beside p.475's Terms.
  MAX_TERMS as TERMS_MAX, blankTerm, countLabel, labelOf as termLabelOf,
  renderableTerms, selectedValues, termsOf, toClauses, toggled, visibleTerms,
} from "./prominent-terms";
import type { Property as SortableProperty } from "./property-sort";
import {
  // Aliased on §211's rule, and this pair is the plainest case yet: `typeOf`
  // and `templateOf` are names half the widgets in this file could want, and
  // `TEMPLATES` says nothing about which widget's. Unaliased they would each
  // resolve to something, silently.
  STEPPER_TYPES, TEMPLATES as STEPPER_TEMPLATES,
  activeColourOf, activeIndex, completedColourOf, isCompleted, isReachable,
  showsStepNumber, stateOf, stepsOf, templateOf as stepperTemplateOf,
  typeOf as stepperTypeOf,
} from "./stepper";
import {
  // Aliased on §211's rule, and this widget needs it more than most: `ORDERS`,
  // `TITLE_MODES`, `labelFor`, `layersOf`, `orderOf` and `eventsOf` are each a
  // name another widget in this file could want, and `eventsOf` in particular
  // already means "the module's events" one import away.
  COLOUR_MODES as TIMELINE_COLOUR_MODES, ICON_MODES as TIMELINE_ICON_MODES,
  ORDERS as TIMELINE_ORDERS, ORIENTATIONS as TIMELINE_ORIENTATIONS,
  PROPERTY_MODES as TIMELINE_PROPERTY_MODES, TITLE_MODES as TIMELINE_TITLE_MODES,
  colourModeOf as timelineColourModeOf, eventProperties,
  eventsOf as timelineEventsOf, gapLabel, iconModeOf as timelineIconModeOf,
  labelFor as timelineLabelFor, layerColour, layersOf as timelineLayersOf,
  orderOf as timelineOrderOf, orientationOf as timelineOrientationOf,
  propertyModeOf as timelinePropertyModeOf, showsIcon, sortFor,
  titleModeOf as timelineTitleModeOf, toggleLayer, visibleEvents,
  newLayerId, selectionItemOf,
  type Layer as TimelineLayer,
} from "./timeline";
import {
  // Aliased on §211's rule: `SOURCES` and `sourceOf` are names three widgets in
  // this file could each want, and `labelOf`/`kindOf` are the kind of name a
  // fourth would.
  SOURCES as MEDIA_SOURCES, attachmentOf, resolveMedia, sizeLabel,
  sourceOf as mediaSourceOf,
} from "./media";
import { frameRefusal, frameTitle, safeFrameUrl, youtubeEmbedUrl } from "./frame";
import { buttonLook, customColourOf, intentOf } from "./button-look";
import {
  addItem, buttonTypeOf, duplicateItem, itemsOf, removeItem, renameItem,
} from "./button-items";
import {
  FILTER_COMPONENT_LABELS, axisEnds, barWidth, bucketLabel, componentOf, componentsFor,
  defaultComponentFor, filtersOf, isBucketChosen, isPeriodChosen, periodLabel, periodOf,
  timelineIntervalOf, withBucket,
  keywordOf, layoutOf, newFilterId, pillSummary, rangeOf, toggleValue, valuesOf, viewerFilterId,
  visibleFilters, withKeyword, withRange, withValues, withoutFilter,
  hasLinkOf, linkedClausesOf, linkedPillLabel, withHasLink, withLinked, groupFilters, linkDisplayOf,
  LINK_DISPLAYS,
  type Clause, type DayRange, type FilterSpec,
} from "./filter-list";
import { keywordQueryProblem } from "./keyword-query";
import { glyph, swatch } from "@/lib/object-type-icon";
import {
  MAX_DRAGGED_OBJECTS, OBJECT_MEDIA_TYPE, OBJECT_SET_MEDIA_TYPE, carriesPayload, collectKeys,
  droppedClauses, objectPayload, objectSetPayload,
} from "./drag-payload";
import {
  // Aliased for the same reason: `sortsOf`, `labelOf` and `toRequest` are names
  // any widget with an ordering could want.
  FIXED_SORTS as TABLE_FIXED_SORTS, MAX_SORTS as TABLE_MAX_SORTS,
  blankEntry as blankTableSort, labelOf as tableSortLabel, sortsOf as tableSortsOf,
  toRequest as tableSortsToRequest, withDirection as withSortDirection,
  withFixed as withSortFixed, withProperty as withSortProperty,
} from "./table-sorts";
import {
  DEFAULT_BUTTON_TEXT, automaticMapping, buttonTextOf, canStage, canSubmit,
  cellValue, editByDefaultOf, editing, eligibleActions, isStaged, limitNotice,
  mappingOf, oneClickOf, parameterForColumn, rowLimitOf, stage, stagedCount,
  toEdits, undoRow, type Staged, variableFeedsOf, withVariables,
} from "./inline-edit";
import { readerLayout } from "./reader-layout";
import { PALETTE as WIDGET_LIST } from "./widget-list";
import { MarkdownReferences, MarkdownView } from "../markdown-view";
import {
  type SelectionEnd, selectedSource, selectionRange,
} from "./markdown-selection";
import {
  SELECTION_BEHAVIORS as REFERENCE_SELECTIONS, isLit as isReferenceLit, numberReferences, referenceTypesOf,
  selectionBehaviorOf as referenceSelectionOf,
} from "./markdown-references";
import {
  FORMATS, FORMAT_LABELS, applyFormat, autoRows, type MarkdownFormat,
} from "./markdown-editor";
import { SeriesCell } from "./SeriesCell";
import {
  COLUMN_BASELINE_KINDS, baselineFor, baselinesByColumn, withColumnBaseline, type ColumnBaseline,
} from "./series-baselines";
import { Sparkline } from "./Sparkline";
import { useSeriesPoints, type SeriesRef } from "./series-points";
import { ChartExport } from "./ChartExport";
import {
  readableTransforms, transformsByColumn, transformsText, withColumnTransforms,
} from "./series-transforms";
import { SeriesTransformsEditor } from "./SeriesTransformsEditor";
import { outputClauses } from "./action-output";
import {
  actionItemsOf, activeIndexOf, menuLabelOf, moreActionsOf, withAddedAction, withMoreAction,
  withoutMoreAction,
} from "./action-menu";
import {
  collapsedInitially, columnsOf as sectionColumnsOf, conditionKey, formLayout,
  hasConditions, labelOf as parameterLabel,
  requiredElsewhere, unreachableNote, type FormParameter, type FormSection,
} from "@/lib/action-sections";
import { isFilled } from "@/lib/struct-parameter";
import { hasOverrides, overrideKey } from "@/lib/action-overrides";
import {
  emptyNote as noChoicesNote, labelOf as choiceLabel, offerFor,
  truncationNote as choicesTruncatedNote, valuesFor,
} from "@/lib/action-choices";
import { emptyValuesNote, valuesTruncationNote } from "@/lib/action-options";
import { filterKey, isWaiting, waitingNote } from "@/lib/action-filters";
import { interfaceQuery } from "./routing";
import { LayoutTemplatePicker } from "./LayoutTemplatePicker";
import { activeTab, asTabName, tabLabels } from "./tab-selection";
import { CanvasNode, OffLayout, holdsKept } from "./SettingsPanel";
import {
  CanvasHeaderCollapsedContext,
  CanvasParameterProvider,
  useCanvasActions,
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
  MIN_SHARE, formatWeights, hasValue, holdsClauses, parseWeights, pivotClauses, resizeWeights,
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
import { Chart, MultiLineChart, PieChart, SegmentedBarChart, toPoints } from "./charts";
import {
  MAX_SERIES, axisSides, drillClauses, drilledLabel as drilledOn, layerKinds, mergeSeries,
  seriesName as seriesNameOf, seriesOf, seriesRequests, seriesSource,
} from "./chart-series";
import {
  SEGMENT_LEGEND_POSITIONS, SEGMENT_MODES, segmentLegendPositionOf, segmentModeOf, segmentedFrom,
  sortSegmented,
} from "./chart-segments";
import { useAttachmentUrl } from "./use-attachment-url";
import { HEADER_STYLES, headerStyleOf, paddingTarget, styleTarget } from "./section-header";
import {
  DEFAULT_LOGO_HEIGHT, MAX_LOGO_HEIGHT, MIN_LOGO_HEIGHT, headerMark, imageRefOf, logoHeightOf,
  logoPositionOf, logoPositionsFor, type ImageRef,
} from "./header-logo";
import {
  EDIT_ORDERS, chosenProperties as chosenEditProperties, editOrderOf, editSummary,
} from "./edit-history";
import {
  freshnessLabel, isStale, itemsOf as freshnessItemsOf, newItemId as newFreshnessItemId,
  type FreshnessItem,
} from "./data-freshness";
import {
  AREA_OPTIONS, CHART_SORTS, NULL_DISPLAYS, SCALE_TYPES, areaOf, axisProblem, axisTitlesOf,
  categoryText, chartSortOf, defaultValueTitle, missingCount, missingText, nullDisplayOf,
  orientationOf, sortPoints, valueAxisOf, valueText, withMissing,
} from "./chart-display";
import { MapCanvas, toLatLon, type MapPoint, type MapShape } from "./map";
import {
  extentOf, nextPlayback, pauseCrossed, pausesOf, positionAt, selectedTimeOf, selectedTimeText,
  timeLabel, timelineControls, timelineSpan, trackShape, windowOf, withinWindow, type TimeFormat,
} from "./map-tracks";
import {
  type Line as DrawnLine, lineOfShapes, lineText, shapeOutputOf, shapesText, syncShapes,
} from "./map-drawn";
import { perimeterModeOf } from "./map-measure";
// Aliased on §211's rule: `areaOf` is also §537's chart area option.
import {
  DRAWN_OPACITY, DRAW_TOOLS, DRAW_TOOL_LABELS, areaOf as mapAreaOf, drawToolsOf, drawnOpacityOf,
  withArea as withMapArea, withDrawTool,
} from "./map-area";
import { PropertyInput, PropertyValue } from "@/components/property-value";
import { PropertyInlineEdit } from "@/components/property-inline-edit";
import {
  constraintNote, fieldChoices, fieldNotes, multipleChoice,
} from "@/lib/parameter-constraint";
import { conditionalStyle, cssFor } from "@/lib/conditional-format";

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
  const typeId = (setDefinition as { object_type_id?: string } | undefined)?.object_type_id
    ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const typeProperties = type.data?.properties ?? [];
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
      {addable.map((p) => (
        <option key={p.api_name} value={p.api_name}>{p.display_name || p.api_name}</option>
      ))}
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
function AdvancedKeyword({ label, applied, onApply }: {
  label: string;
  applied: string;
  onApply: (text: string) => void;
}) {
  const [draft, setDraft] = useState(applied);
  const problem = draft.trim() ? keywordQueryProblem(draft) : null;
  return (
    <>
      <input
        type="search"
        aria-label={label}
        data-testid="filter-keyword-advanced"
        placeholder='north OR (south AND NOT "south east")'
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          if (!e.target.value.trim() || keywordQueryProblem(e.target.value) === null) {
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
            {glyph(far.data)}
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
        <p className="canvas-widget-empty">Couldn&apos;t read this property&apos;s values.</p>
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

      {component === "keyword" && spec.syntax !== "advanced" && (
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

function FilterListSettings() {
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
  const typeId = (bound as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const typeProperties = type.data?.properties ?? [];
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
                {typeProperties.map((p) => (
                  <option key={p.api_name} value={p.api_name}>{p.display_name || p.api_name}</option>
                ))}
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
                    return e.target.value === "advanced" ? { ...rest, syntax: "advanced" } : rest;
                  }))}
                >
                  <option value="simple">Starts with</option>
                  <option value="advanced">Advanced syntax</option>
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
          {typeProperties.map((p) => (
            <option key={p.api_name} value={p.api_name}>{p.display_name || p.api_name}</option>
          ))}
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

CanvasFilterList.craft = {
  displayName: "Filter list",
  props: {
    objectSetVariable: null, variable: null, properties: "", filters: null, title: "Filters",
    userEditable: false, layout: "vertical", linkDisplay: "inline", collapseLinked: false,
  },
  related: { settings: FilterListSettings },
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

function UserSelectSettings() {
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

CanvasUserSelect.craft = {
  displayName: "User select",
  props: {
    variable: null, groupsVariable: null, mode: "single",
    allowClear: false, label: "", placeholder: "",
  },
  related: { settings: UserSelectSettings },
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

function FilterPillsSettings() {
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

CanvasFilterPills.craft = {
  displayName: "Filter pills",
  props: {
    objectSetVariable: null, variable: null,
    mode: "read_only", showTypePill: false, title: "",
  },
  related: { settings: FilterPillsSettings },
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
  /** p.473's Icon, as a glyph (§445's reading of p.47: no icon library). */
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
          {icon ? <span aria-hidden="true" data-testid="search-bar-icon">{icon.slice(0, 2)}</span> : null}
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

function SearchBarSettings() {
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
        <input
          type="text"
          maxLength={2}
          value={icon ?? ""}
          data-testid="search-bar-icon-input"
          onChange={(e) => setProp((p: { icon: string }) => (p.icon = e.target.value))}
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

CanvasSearchBar.craft = {
  displayName: "Exploration search bar",
  props: {
    objectSetVariable: null, variable: null, mode: "add", showTypePill: false,
    placeholder: "", showClearButton: true, fillWidth: true, disableAutocomplete: false,
    disableKeyword: false, propertyScope: "visible", customProperties: [], showHelpIcon: false,
    icon: "", linkScope: "all", customLinks: [],
  },
  related: { settings: SearchBarSettings },
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
 * ○ for p.475's **Icon** as an icon: there is no icon library here, so it is one
 * or two characters — the same ○ every icon setting in this file carries.
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
                  <span className="canvas-term-icon" aria-hidden="true">{term.icon}</span>
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

function ProminentTermsSettings() {
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
            <input
              type="text"
              value={term.icon}
              placeholder="icon"
              maxLength={2}
              data-testid={`term-icon-${index}`}
              onChange={(e) => edit(index, { icon: e.target.value })}
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

CanvasProminentTerms.craft = {
  displayName: "Prominent terms",
  props: {
    objectSetVariable: null, variable: null, property: "",
    terms: [], hideEmpty: false, title: "",
  },
  related: { settings: ProminentTermsSettings },
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
 * **The rich view is a preview, not an editor**, and opens on the raw view:
 * p.466's "formatted preview with inline editing" needs a rich-text editor
 * this platform does not have, and a view nobody can type into is not the
 * one to open on. The toolbar formats the raw text, which is what p.466's
 * "without needing to know Markdown syntax" asks of it. */
function MarkdownTextEditor({ label, text, placeholder, autoSize, onText }: {
  label: string;
  text: string;
  placeholder: string;
  autoSize: boolean;
  onText: (next: string) => void;
}) {
  const [rich, setRich] = useState(false);
  const area = React.useRef<HTMLTextAreaElement | null>(null);
  const press = (format: MarkdownFormat) => {
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
            title={rich ? "Switch to Markdown to format" : FORMAT_LABELS[format]}
            disabled={rich}
            // Before the textarea loses its selection to the button.
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
        <div data-testid="md-rich" className="canvas-markdown">
          {text.trim()
            ? <MarkdownView blocks={parseMarkdown(text, { breaks: true })} align="left" />
            : <p className="canvas-widget-empty">{placeholder || "Nothing written yet"}</p>}
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

function TextInputSettings() {
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

CanvasTextInput.craft = {
  displayName: "Text input",
  props: { name: "", label: "", placeholder: "", format: "line", rows: 4, autoSize: true },
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

function StringSelectorSettings() {
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

CanvasStringSelector.craft = {
  displayName: "String selector",
  props: {
    name: "", label: "", selection: "single", display: "dropdown",
    optionSource: "static", options: [], optionsVariable: "",
    placeholder: "", allowClearing: true, layout: "vertical", columns: 3, allowCreating: false,
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

function DateInputSettings() {
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

CanvasDateInput.craft = {
  displayName: "Date input",
  props: { name: "", endVariable: "", label: "", mode: "single" },
  related: { settings: DateInputSettings },
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
  const selecting = !!(selectedTextVariable || selectionStartVariable || selectionEndVariable);
  const blocks = parseMarkdown(filled, {
    breaks: breaks !== false, references, offsets: selecting });
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
    if (selectedTextVariable) {
      setParameter(selectedTextVariable, range ? selectedSource(rawSource, range) : "");
    }
    if (selectionStartVariable) setParameter(selectionStartVariable, range ? range.start : null);
    if (selectionEndVariable) setParameter(selectionEndVariable, range ? range.end : null);
  };
  if (references) numberReferences(blocks);
  const types = referenceTypesOf(referenceTypes);
  const behavior = referenceSelectionOf(selectionBehavior);
  const selectedKeys = keysOf(selectedVariable ? parameterValues[selectedVariable] : undefined);
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
      lastAnchor, selectedKeys);
    return (
      <button
        type="button"
        className={`canvas-markdown-ref${lit ? " on" : ""}`}
        style={type.color ? ({ "--ref-color": type.color } as React.CSSProperties) : undefined}
        data-testid="markdown-ref"
        data-object-type={node.objectType}
        data-primary-key={node.primaryKey}
        aria-pressed={lit}
        onClick={() => {
          setLastAnchor(index);
          // p.320: "that object will be output into this object set variable".
          if (selectedVariable) {
            setParameter(selectedVariable, selectionClauses([node.primaryKey]));
          }
          // p.320's Event on selection, in a running module only: a navigate
          // fired while arranging the page would move the builder off it.
          if (mode === "run" && onSelect.length > 0) {
            runEvents(onSelect, { ...eventContext,
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
             onMouseUp={readSelection} onKeyUp={readSelection}>
          <MarkdownReferences.Provider value={references ? drawReference : null}>
            <MarkdownView blocks={blocks} align={widgetAlign} />
          </MarkdownReferences.Provider>
        </div>
      )}
    </div>
  );
}

function MarkdownSettings() {
  const {
    source, text, textVariable, monospace, scrolling, wordWrap, breaks, alignment,
    tagType, selectedVariable, referenceTypes, selectionBehavior,
    selectedTextVariable, selectionStartVariable, selectionEndVariable,
    actions: { setProp },
  } = useNode((node) => ({
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
  const writeTypes = (next: { objectType: string; color: string | null }[]) =>
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
          value={tagType === "inline_reference" ? "inline_reference" : "standard"}
          data-testid="markdown-tag-type"
          onChange={(e) => setProp((p: { tagType: string }) => (p.tagType = e.target.value))}
        >
          <option value="standard">Standard</option>
          <option value="inline_reference">Inline reference</option>
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
              <div key={i} className="field-inline" data-testid="markdown-ref-type">
                <input
                  type="text"
                  aria-label={`Object type ${i + 1}`}
                  data-testid="markdown-ref-type-name"
                  value={type.objectType}
                  onChange={(e) => writeTypes(types.map((t, j) =>
                    (j === i ? { ...t, objectType: e.target.value } : t)))}
                />
                <input
                  type="color"
                  aria-label={`Object type ${i + 1} highlight colour`}
                  data-testid="markdown-ref-type-color"
                  value={type.color ?? "#2563eb"}
                  onChange={(e) => writeTypes(types.map((t, j) =>
                    (j === i ? { ...t, color: e.target.value } : t)))}
                />
                <button
                  type="button"
                  className="btn quiet"
                  aria-label={`Remove object type ${i + 1}`}
                  onClick={() => writeTypes(types.filter((_, j) => j !== i))}
                >
                  ×
                </button>
              </div>
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
                  writeTypes([...types, { objectType: value, color: null }]);
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
  inlineEditAction = null,
  inlineEditMapping = null,
  inlineEditVariables = null,
  columnsVariable = null,
  inlineEditButtonText = "",
  inlineEditByDefault = false,
  inlineEditOneClick = false,
  exportCsv = false,
  hideColumnConfig = false,
  customMenu = false,
  menuItems = null,
  rightClickedVariable = null,
  seriesFormats = null,
  seriesRules = null,
  seriesTransforms = null,
  seriesBaselines = null,
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
  /** p.225's "Hide column configuration": no viewer-side Configure columns (§612). */
  hideColumnConfig?: boolean;
  /** p.243's "Customize right-click menu" (§613): the toggle, the menu's items
   * (`button-items.ts`'s shape, so the Events panel names them as it names a
   * menu button's), and the right-clicked object as selection clauses. */
  customMenu?: boolean;
  menuItems?: unknown;
  rightClickedVariable?: string | null;
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId, mode, derivedColumns } = useCanvasEnv();
  const eventContext = useEventContext(undefined, useOverlayIds());
  const filterValue = useCanvasParameter(filterParameter);
  const searchValue = useCanvasParameter(searchParameter);
  const setDefinition = useCanvasVariable(objectSetVariable);
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
  // p.223's Default sort(s), read from whichever shape the document holds and
  // sent as whichever shape the request wants - one ordering still goes as the
  // string the API has always taken.
  const sortRequest = useMemo(() => tableSortsToRequest(tableSortsOf(sort)), [sort]);
  const setPage = useSetPage(workspaceId, usingSet ? setDefinition : null, {
    pageSize,
    sort: sortRequest,
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
        // p.33's "in which Foundry applications" (§320): a widget's reads are
        // Workshop's, which is the answer somebody renaming a property needs.
        application: "workshop",
      }),
    enabled: !!objectTypeId,
  });

  const all = type.data?.properties ?? [];
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
  const listed: string[] | null = columnsVariable
    ? visibleColumns(
      configured.length ? configured : all.map((p) => p.api_name),
      variableValues[columnsVariable],
    )
    : configured.length ? configured : null;
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
    ? shownColumns.map((name) => all.find((p) => p.api_name === name)).filter((p) => !!p)
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
  const rows = usingSet ? setPage.rows : page.data?.items;
  const total = usingSet ? setPage.total : page.data?.total;
  const active = usingSet
    ? { isError: setPage.isError, isPending: setPage.isPending }
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
  const offersExport = mode === "run" && !!exportCsv && usingSet;
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
                    <th key={p.api_name} style={stick(column + 1 + leading)}>
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
                      activeKeys.includes(instance.primary_key) ? "row-active" : "",
                    ].filter(Boolean).join(" ") || undefined}
                    // The active row is announced rather than only coloured: a
                    // highlight nobody can hear is not a selection.
                    aria-current={
                      activeKeys.includes(instance.primary_key) ? "true" : undefined
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
                        setParameter(rightClickedVariable, selectionClauses([instance.primary_key]));
                      }
                    } : undefined}
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
                        ...stick(leading),
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
                      // p.242: "users can edit any modifiable column mapped to
                      // an action parameter" - so a column with no parameter
                      // pointed at it stays a value, in edit mode or out of it.
                      const parameter = inEditMode
                        ? parameterForColumn(editMapping, p.api_name)
                        : undefined;
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
                            ...stick(column + 1 + leading),
                          }}
                        >
                          <div style={cell}>
                            {parameter ? (
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
                            ) : (
                              <PropertyValue
                                workspaceId={workspaceId}
                                dataType={p.data_type}
                                valueFormat={p.value_format}
                                structFields={p.struct_fields}
                                style={paint}
                                value={instance.properties[p.api_name]}
                                emptyText={emptyText}
                              />
                            )}
                          </div>
                        </td>
                      );
                    })}
                    {derived.map((c) => {
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
              {offersExport && (<button
                type="button"
                role="menuitem"
                className="btn quiet"
                data-testid="table-export-csv"
                onClick={() => {
                  setRowMenu(null);
                  exportObjects({
                    variable: objectSetVariable!,
                    definition: setDefinition,
                    format: "csv",
                    fileName: null,
                    properties: properties.map((p) => p.api_name),
                  });
                }}
              >
                Export to CSV
              </button>)}
            </div>
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
function TableSortsField({ sort, properties, setProp }: {
  sort: unknown;
  /** Every property the type declares. Empty while the ontology resolves, and
   * empty is why the text box is still here rather than deleted. */
  properties: readonly SortableProperty[];
  setProp: (cb: (props: { sort: string | string[] }) => void) => void;
}) {
  const sortable = orderableProperties(properties);
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

function ObjectTableSettings() {
  const { workspaceId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    objectTypeId, filterProperty, filterParameter, searchParameter,
    objectSetVariable, pageSize, columns, sort,
    activeVariable, autoSelect, multiSelect, selectedVariable,
    lines, valueWrap, frozenColumns, emptyMode, emptyMessage,
    customNoValue, noValueText, fitColumns, narrowHeaders, formatFillsCell,
    inlineEditAction, inlineEditMapping, inlineEditVariables, inlineEditButtonText,
    inlineEditByDefault, inlineEditOneClick, seriesFormats, seriesRules, seriesTransforms, seriesBaselines,
    columnsVariable, exportCsv, hideColumnConfig, customMenu, menuItems, rightClickedVariable,
    actions: { setProp },
  } = useNode((node) => ({
    customMenu: node.data.props.customMenu,
    menuItems: node.data.props.menuItems,
    rightClickedVariable: node.data.props.rightClickedVariable,
    hideColumnConfig: node.data.props.hideColumnConfig,
    columnsVariable: node.data.props.columnsVariable,
    exportCsv: node.data.props.exportCsv,
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
    inlineEditAction: null, inlineEditMapping: null, inlineEditVariables: null,
    inlineEditButtonText: "",
    inlineEditByDefault: false, inlineEditOneClick: false,
    seriesFormats: null, seriesRules: null, seriesTransforms: null, seriesBaselines: null,
    columnsVariable: null, exportCsv: false, hideColumnConfig: false,
    customMenu: false, menuItems: null, rightClickedVariable: null,
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

CanvasObjectSetTitle.craft = {
  displayName: "Object set title",
  props: {
    objectSetVariable: null, single: false, showIcon: false,
    titleOverride: "", renderWhenEmpty: false, placeholderTypeId: null, enableDrag: false,
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

  // `[0]` and `[length - 1]` are the same expression here, because the fetch
  // above asks for one row: p.265's "only the first object will be displayed"
  // is kept by the *page size*, not by the index.
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
                  structFields={p.struct_fields}
                  style={conditionalStyle(p.conditional_format, instance.properties)}
                  value={instance.properties[p.api_name]}
                />
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
  const linkQuery = useQuery({
    queryKey: ["instance-links", workspaceId, setPage.typeId, instance?.id],
    queryFn: () => objApi.instanceLinks(workspaceId, setPage.typeId!, instance!.id, "workshop"),
    enabled: !!setPage.typeId && !!instance,
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
    specifying ? sortedLinkQuery(g, linkSortOf(chosen, linkKey(g)), setPage.typeId ?? undefined)
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
                {exploreLinks === true && slug && linkSubsetHref(slug, group) && (
                  <a
                    className="canvas-link-explore"
                    data-testid={`link-explore-${key}`}
                    href={linkSubsetHref(slug, group)!}
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

function LinksWidgetSettings() {
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

CanvasLinksWidget.craft = {
  displayName: "Links",
  props: {
    objectSetVariable: null, linkMode: "all", links: [], defaultExpand: 0,
    exploreLinks: false, openObjects: false, previewOnHover: false,
  },
  related: { settings: LinksWidgetSettings },
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
 * **Not built, and named rather than approximated**: p.261's **panel form
 * factor** and p.263's panel behaviours (Object instance / Adaptive / Object
 * set), because two of the three render an *object set* summary that this
 * platform has no such thing as — a "panel" that always showed one object
 * would be the full factor under another name; p.262-263's **Hide tabs**,
 * **Go to initial tab on object switch** and **Initial object view tab ID**,
 * because a configured view here is one module rather than a set of tabs;
 * p.263's **Interface configuration**, which is the embedded-module interface
 * mapping and belongs with that widget; p.263's **Revert to legacy widget**,
 * there being no legacy one; and p.262's Empty state **icon**, for the reason
 * every icon setting is ○ — there is no icon set to pick from.
 */
export function CanvasObjectViewWidget({
  objectSetVariable = null,
  viewMode = "configured",
  allowToggle = true,
  hideHeader = false,
  emptyMessage = "",
}: {
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
  const { pending: variablesPending } = useCanvasVariables();

  // p.261: "only the first object will be shown if the object set contains
  // multiple objects."
  const setPage = useSetPage(workspaceId, setDefinition, {
    pageSize: 1, variablesPending,
  });
  const instance = setPage.rows?.[0];
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
      ) : !instance || !setPage.typeId ? (
        <p className="canvas-widget-empty" data-testid="object-view-empty">
          {objectViewEmptyMessageOf(emptyMessage)}
        </p>
      ) : (
        <div data-testid="object-view-widget">
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
          />
        </div>
      )}
    </div>
  );
}

function ObjectViewWidgetSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    objectSetVariable, viewMode, allowToggle, hideHeader, emptyMessage,
    actions: { setProp },
  } = useNode((node) => ({
    objectSetVariable: node.data.props.objectSetVariable,
    viewMode: node.data.props.viewMode,
    allowToggle: node.data.props.allowToggle,
    hideHeader: node.data.props.hideHeader,
    emptyMessage: node.data.props.emptyMessage,
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
      </>}
    />
  );
}

CanvasObjectViewWidget.craft = {
  displayName: "Object view",
  props: {
    objectSetVariable: null, viewMode: "configured", allowToggle: true,
    hideHeader: false, emptyMessage: "",
  },
  related: { settings: ObjectViewWidgetSettings },
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
          Couldn&apos;t group this object set.
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

function PieChartSettings() {
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
          {(type.data?.properties ?? []).map((p) => (
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

CanvasPieChart.craft = {
  displayName: "Pie chart",
  props: {
    objectSetVariable: null, groupBy: "", aggregation: "count",
    aggregationProperty: "", inner: 0, legend: "right",
    showLegend: true, segments: [], ontologyColors: false, filterVariable: null,
  },
  related: { settings: PieChartSettings },
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
 * **Not built, and named rather than approximated**: p.313's **Icon** is a
 * name, and this platform has no icon set - the icon template draws a mark
 * carrying the configured name as its accessible label, which is the same call
 * §210's Object Set Title made for the same reason. A named-icon picker is one
 * decision for all of them, not a setting on this widget.
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
                    className="canvas-step-mark"
                    data-testid="step-mark"
                    style={colour ? { background: colour, borderColor: colour } : undefined}
                    // p.313's Icon, as a mark: the field holds a name like
                    // `check` and this platform has no icon set, so the name
                    // travels as the accessible label rather than being lost.
                    aria-label={useIcons ? (step.icon || "step") : undefined}
                  >
                    {!useIcons || numbered ? index + 1 : ""}
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

function StepperSettings() {
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

CanvasStepper.craft = {
  displayName: "Stepper",
  props: {
    steps: [], stepperType: "linear", template: "text", showStepNumber: false,
    completedColour: "", activeColour: "",
  },
  related: { settings: StepperSettings },
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
 * - p.348's **Icon override** draws a mark rather than a named icon, the call
 *   §210 and §219 both made: the field holds a name like `cart` and this
 *   platform has no icon set, so the name travels as the mark's accessible
 *   label rather than being lost.
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
        properties: declared,
        // p.348's **Object title** is the ontology's title property, not the
        // primary key. An object set page carries neither, so the type is what
        // says which property to read - and without this every event would be
        // labelled with its key, which is a title only a database has.
        titleProperty:
          declared.find((p) => p.id === type?.title_property_id)?.api_name ?? null,
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

  const chosenKeys = keysOf(activeVariable ? values[activeVariable] : undefined);
  const chosen = chosenKeys[0] ?? null;

  const pick = (key: string, layer: number) => {
    if (mode !== "run") return;
    if (activeVariable) set(activeVariable, selectionClauses([key]));
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
                      style={{ background: layerColour(layer, index, null) ?? undefined }}
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
                const colour = layerColour(layer, event.layer, null);
                const previous = events[index - 1];
                return (
                  <li
                    className="canvas-timeline-event"
                    key={`${event.layer}:${event.key}`}
                    data-testid="timeline-event"
                    data-layer={String(event.layer)}
                    data-selected={
                      highlightSelection && chosen === event.key ? "yes" : "no"
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
                      style={colour ? { background: colour, borderColor: colour } : undefined}
                      aria-label={
                        showsIcon(layer) ? (layer.icon || timelineLabelFor(layer, event.layer))
                          : undefined
                      }
                      disabled={mode !== "run"}
                      onClick={() => pick(event.key, event.layer)}
                    />
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

function TimelineSettings() {
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

CanvasTimeline.craft = {
  displayName: "Timeline",
  props: {
    layers: [], orientation: "vertical", order: "newest_first",
    showLegend: true, showGaps: false, activeVariable: null,
    highlightSelection: true, pageSize: 50,
  },
  related: { settings: TimelineSettings },
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

function MediaPreviewSettings() {
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

CanvasMediaPreview.craft = {
  displayName: "Media preview",
  props: {
    source: "string", url: "", textVariable: null, subjectVariable: null,
    property: "", label: "", maxHeight: 320,
  },
  related: { settings: MediaPreviewSettings },
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
}: {
  /** p.546's URL, as a static string. */
  url?: string;
  /** …or as a string variable. */
  textVariable?: string | null;
  /** The frame's accessible name. */
  title?: string;
  height?: number;
}) {
  const {
    connectors: { connect, drag },
  } = useNode();
  const { mode } = useCanvasEnv();
  const { resolved } = useCanvasVariables();
  const raw = textVariable ? resolved[textVariable] : url;
  const target = safeFrameUrl(raw);
  const refusal = frameRefusal(raw);
  const px = Math.max(120, Math.min(Number(height) || 480, 2000));

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
          src={target}
          title={frameTitle(title, target)}
          data-testid="iframe"
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

function IframeSettings() {
  const {
    url, textVariable, title, height,
    actions: { setProp },
  } = useNode((node) => ({
    url: node.data.props.url,
    textVariable: node.data.props.textVariable,
    title: node.data.props.title,
    height: node.data.props.height,
  }));
  const { declared } = useCanvasVariables();
  const strings = Object.values(declared).filter((v) => v.kind === "string");
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

CanvasIframe.craft = {
  displayName: "Iframe",
  props: { url: "", textVariable: null, title: "", height: 480 },
  related: { settings: IframeSettings },
};

// ---- Object dropdown (p.455-458) --------------------------------------------
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
 * **Not built, and named rather than approximated**: p.455's "data on one or
 * multiple object types", which needs an object set spanning types and is the
 * same ○ as the Object Table's; p.455's conditional and numerical formatting
 * *configured in the Ontology Manager* is in fact drawn — `PropertyValue` does
 * it — but the sort in p.458 is a single property here, because p.458's own
 * "only shared properties can be sorted on" is about the multi-type case that
 * does not exist yet.
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
  const typeId =
    (setDefinition as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const declared = type.data?.properties ?? [];
  const setPage = useSetPage(workspaceId, setDefinition, {
    pageSize: DROPDOWN_PAGE_LIMIT,
    // `undefined` rather than `declared` until the read lands: an empty list
    // reads as "this type orders nothing" and would send the fallback, which is
    // a different ordering from the one that is about to arrive.
    sort: dropdownSortOf(sortProperty, type.data ? declared : undefined),
    variablesPending,
  });
  const titleProperty = declared.find((p) => p.id === type.data?.title_property_id);
  const shownNames = propertyListOf(properties);
  const searchable = searchProperties({
    mode: searchMode,
    all: declared,
    // The title is on screen too, and p.458 says search runs on what is
    // displayed — a picker whose search ignored the words it is showing would
    // be the most surprising thing on the page.
    shown: [...(titleProperty ? [titleProperty.api_name] : []), ...shownNames],
    specific: searchPropertyNames,
  });

  const rows = setPage.rows ?? [];
  const options = rows.filter((row) => matchesQuery(row.properties, query, searchable));
  const keys = keysOf(selectedRaw);
  const chosenKey = keys[0] ?? null;
  const chosen = rows.find((row) => row.primary_key === chosenKey);
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
      setParameter(selectedVariable, selectionClauses([autoKey]));
      return;
    }
    if (!stated) setParameter(selectedVariable, selectionClauses([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoKey, selectedVariable, stated]);

  const pick = (key: string | null) => {
    setOpen(false);
    setQuery("");
    if (selectedVariable) {
      setParameter(selectedVariable, selectionClauses(key ? [key] : []));
    }
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
                  ? optionTitleOf(chosen.properties, titleProperty?.api_name ?? null,
                                  chosen.primary_key)
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
                    aria-selected={row.primary_key === chosenKey}
                    className="canvas-dropdown-option"
                    data-testid="dropdown-option"
                    onClick={() => pick(row.primary_key)}
                  >
                    <span className="canvas-dropdown-title">
                      {optionTitleOf(row.properties, titleProperty?.api_name ?? null,
                                     row.primary_key)}
                    </span>
                    {visibleProperties({
                      all: declared, chosen: properties,
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

function ObjectDropdownSettings() {
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
  const typeId = (bound as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const names = (type.data?.properties ?? []).map((p) => p.api_name).join(", ");

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
        properties={type.data?.properties ?? []}
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

CanvasObjectDropdown.craft = {
  displayName: "Object dropdown",
  props: {
    objectSetVariable: null, selectedVariable: null, label: "", properties: "",
    hideNull: false, sortProperty: "key", searchMode: "on_screen",
    searchPropertyNames: "", allowNoSelection: false,
  },
  related: { settings: ObjectDropdownSettings },
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

  // **The type is resolved from the set definition, not from the page**, so a
  // p.458 property sort can be checked before the first fetch rather than after
  // it. `useSetPage` reads `object_type_id` off the same definition — it never
  // needed the response for it — so this costs no request the panel and the
  // other widgets over this set are not already sharing by query key.
  const typeId =
    (setDefinition as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const declared = type.data?.properties ?? [];
  const setPage = useSetPage(workspaceId, setDefinition, {
    pageSize: DROPDOWN_PAGE_LIMIT,
    // `undefined` rather than `declared` until the read lands: an empty list
    // reads as "this type orders nothing" and would send the fallback, which is
    // a different ordering from the one that is about to arrive.
    sort: dropdownSortOf(sortProperty, type.data ? declared : undefined),
    variablesPending,
  });
  const titleProperty = declared.find((p) => p.id === type.data?.title_property_id);
  const searchable = searchProperties({
    mode: searchMode,
    all: declared,
    shown: [
      ...(titleProperty ? [titleProperty.api_name] : []),
      ...propertyListOf(properties),
    ],
    specific: searchPropertyNames,
  });

  const rows = setPage.rows ?? [];
  const options = rows.filter((row) => matchesQuery(row.properties, query, searchable));
  const keys = keysOf(selectedRaw);
  const stated = hasSelection(selectedRaw);

  // §207's rule: state the empty selection rather than leaving the variable
  // alone, or `narrow_set` hands downstream the whole set instead of none.
  useEffect(() => {
    if (!selectedVariable || stated) return;
    setParameter(selectedVariable, selectionClauses([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedVariable, stated]);

  const toggleKeyed = (key: string) => {
    if (selectedVariable) {
      setParameter(selectedVariable, selectionClauses(toggleKey(keys, key)));
    }
  };

  const onlyRow = keys.length === 1
    ? rows.find((row) => row.primary_key === keys[0])
    : undefined;
  const summary = selectionSummary(
    keys.length,
    onlyRow
      ? optionTitleOf(onlyRow.properties, titleProperty?.api_name ?? null, onlyRow.primary_key)
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
              {keys.length > 0 && (
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
                      checked={keys.includes(row.primary_key)}
                      data-testid={`selector-tick-${row.primary_key}`}
                      onChange={() => toggleKeyed(row.primary_key)}
                    />
                    <span>
                      <span className="canvas-dropdown-title">
                        {optionTitleOf(row.properties, titleProperty?.api_name ?? null,
                                       row.primary_key)}
                      </span>
                      {visibleProperties({
                        all: declared, chosen: properties,
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

function ObjectSelectorSettings() {
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
  const typeId = (bound as { object_type_id?: string } | undefined)?.object_type_id ?? null;
  const type = useQuery({
    queryKey: ["object-type", typeId],
    queryFn: () => objApi.getType(workspaceId, typeId!),
    enabled: !!typeId,
  });
  const names = (type.data?.properties ?? []).map((p) => p.api_name).join(", ");

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
        properties={type.data?.properties ?? []}
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

CanvasObjectSelector.craft = {
  displayName: "Object selector",
  props: {
    objectSetVariable: null, selectedVariable: null, label: "", properties: "",
    hideNull: false, sortProperty: "key", searchMode: "on_screen",
    searchPropertyNames: "",
  },
  related: { settings: ObjectSelectorSettings },
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
                            structFields={p.struct_fields}
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
  drawnShapesVariable = null,
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
  /** p.301's Drawn shapes and Shape output type (§574): a string variable
   * the drawn shape is read from and written to as GeoJSON, as features or
   * as geometries (`map-drawn.ts`). */
  drawnShapesVariable?: string | null;
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
}) {
  const {
    id: nodeId,
    connectors: { connect, drag },
  } = useNode();
  const { workspaceId, projectId } = useCanvasEnv();
  const filterValue = useCanvasParameter(filterParameter);
  const { set: setParameter } = useCanvasParameters();
  // Read back from the variable it writes, as a Filter List's clauses are:
  // the area on the map is the one the document holds.
  const areaWritten = useCanvasParameter(areaVariable);
  const areaResolved = useCanvasVariable(areaVariable);
  const areaClauses = clausesOf(areaWritten !== undefined ? areaWritten : areaResolved);
  const selectsArea = source === "objects" && !!objectSetVariable && !!areaVariable
    && !!locationProperty;
  const mapArea = selectsArea ? mapAreaOf(areaClauses, locationProperty!) : null;
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
  React.useEffect(() => {
    if (!selectsArea || !drawnShapesVariable) {
      shapesSeen.current = null;
      return;
    }
    const sync = syncShapes(shapesSeen.current, { area: mapArea, shapes: shapesNow }, shapeOutput);
    shapesSeen.current = { area: shapesText(mapArea, shapeOutput), shapes: shapesNow };
    if (sync?.write === "area") {
      setParameter(areaVariable!, withMapArea(areaClauses, locationProperty!, sync.area));
    } else if (sync?.write === "shapes") {
      setParameter(drawnShapesVariable, sync.text);
    }
  });
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
    return { points: collected, unplaceable: bad, notYet: later };
  }, [source, usingSet, setPage.data, objectPage.data, datasetRows.data,
      locationProperty, labelProperty, tracking, tracksByKey, selectedTime]);
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
        ? !locationProperty && !trackProperty ? "pick the geopoint property to plot" : null
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
          points={layerShown ? points : []}
          shapes={layerShown ? trackShapes : []}
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
              ...(layerShown ? [{ label: layerLabel || "Objects", kind: "points" as const,
                color: layerColorOf(layerColor) ?? "var(--accent, #14646e)",
                count: points.length }] : []),
              ...(layerShown && trackShapes.length ? [{ label: `${layerLabel || "Objects"} tracks`,
                kind: "track" as const, color: layerColorOf(layerColor) ?? "var(--accent, #14646e)",
                count: trackShapes.length }] : []),
            ],
          } : null}
          area={mapArea}
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
                // One drawn shape at a time (p.301's single draw mode): a line
                // replaces the area, which a line cannot be.
                if (selectsArea && mapArea) {
                  setParameter(areaVariable!, withMapArea(areaClauses, locationProperty!, null));
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
                setParameter(areaVariable!, withMapArea(areaClauses, locationProperty!, area));
                const text = shapesText(area, shapeOutput);
                if (drawnShapesVariable) setParameter(drawnShapesVariable, text);
                // Drawn, not cleared: `{{value}}` is the shape's GeoJSON.
                if (area && drawEvents.length > 0) {
                  runEvents(drawEvents, { ...eventContext, payload: { value: text } });
                }
              }
            : undefined}
          unplaceable={unplaceable}
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
            lockLayer ? undefined
            : selectedVariable || pinEvents.length > 0
              ? (point) => {
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
              : undefined
          }
        />
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

function MapSettings() {
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
    drawOptions, drawnShapeColor, drawnShapeOpacity, drawnShapesVariable, shapeOutputType,
    enableMeasurements, measurePerimeter, perimeterMode, measureArea, measureLine, lineMode,
    showLegend, legendCollapsed, legendSize, showSelectionPanel, autoZoom, autoZoomSetVariable,
    autoZoomOutsideOnly, boundsVariable, followSetVariable,
    actions: { setProp },
  } = useNode((node) => ({
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
    drawnShapesVariable: node.data.props.drawnShapesVariable,
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
    drawnShapesVariable: null, shapeOutputType: "features",
    enableMeasurements: false, measurePerimeter: true, perimeterMode: "total", measureArea: true,
    showLegend: false, legendCollapsed: false, legendSize: "full", showSelectionPanel: false,
    autoZoom: "default", autoZoomSetVariable: null, autoZoomOutsideOnly: false,
    boundsVariable: null, followSetVariable: null,
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
  const extras = usingSet && !segmenting && (drawnKind === "bar" || drawnKind === "line")
    ? seriesOf(series) : [];
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
      enabled: !!extraSources[i] && !!extraAsks[i],
    })),
  });
  const drawnExtras = extras.flatMap((spec, i) => {
    const data = extraResults[i]?.data;
    const request = extraAsks[i];
    const source = extraSources[i];
    if (!request || !data || !source) return [];
    return [{
      spec,
      source,
      name: seriesNameOf(spec, source.key !== objectSetVariable
        ? declared[source.key]?.label ?? source.key : undefined),
      points: data.groups.map((g) => ({
        label: g.value,
        value: request.aggregation !== "count" ? Number(g.metric ?? 0) : g.count,
      })),
    }];
  });
  const firstName = (typeof seriesName === "string" ? seriesName.trim() : "")
    || defaultValueTitle(kind ?? "bar", aggregate, measure);
  const multi = drawnExtras.length > 0 && points !== null
    ? mergeSeries(points, drawnExtras.map((e) => e.points),
      [firstName, ...drawnExtras.map((e) => e.name)])
    : null;
  // Only a series that asked is waited for: a disabled query stays pending.
  // p.282's Selection as filter per layer (§628): a series naming its own
  // variable narrows it on its own property; the rest narrow the chart's.
  const drills = multi ? [chartDrill, ...drawnExtras.map(({ spec, source }) => {
    const variable = spec.drilldownVariable;
    if (!variable) return chartDrill;
    const selected = drilledOn(parameterValues[variable], source.dimension);
    return {
      selected,
      onSelect: (label: string) =>
        setParameter(variable, drillClauses(source.dimension, label, selected)),
    };
  })] : undefined;
  // p.280's Layer type (§626): a chart whose series are drawn as both bars
  // and lines is drawn as bars with the lines across them.
  const kinds = layerKinds(drawnKind === "line" ? "line" : "bar",
    drawnExtras.map((e) => e.spec));
  const mixed = kinds.includes("bar") && kinds.includes("line");
  const extrasPending = extraResults.some(
    (r, i) => !!extraAsks[i] && !!extraSources[i] && r.isPending);
  const sides = axisSides(drawnExtras.map((e) => e.spec), multipleAxes === true);

  // p.283's value axis and titles. A problem with the bounds is said and the
  // chart drawn on calculated ones, rather than on an axis running backwards.
  const axis = valueAxisOf({ scaleType, minBound, maxBound });
  const axisTrouble = axisProblem(axis);
  const titles = axisTitlesOf(
    { showCategoryTitle, categoryTitle, showValueTitle, valueTitle },
    usingSeries
      // p.281: a series chart has "the time range on the X axis".
      ? { category: "Time", value: defaultValueTitle("line", seriesRef?.aggregate, seriesRef?.property) }
      // p.283: "the aggregation type(s) used within the chart's series".
      : { category: dimension,
          value: multi ? multi.segments.join(", ")
            : defaultValueTitle(kind ?? "bar", aggregate, measure) },
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
      {segmenting && crossTab.data && (
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
      {!multi && !segmenting && points && !(usingSeries && points.length === 0) && (
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

function ChartSettings() {
  const { workspaceId, projectId } = useCanvasEnv();
  const { declared, resolved } = useCanvasVariables();
  const {
    datasetId, kind, dimension, measure, aggregate, title,
    filterColumn, filterParameter, filterOperator, objectSetVariable, seriesVariable,
    drilldownVariable, segmentBy, segmentMode, showLegend, sort, orientation, valueLabels,
    scaleType, minBound, maxBound, showCategoryTitle, categoryTitle, showValueTitle, valueTitle,
    lineArea, nullDisplay, valueFormat, categoryFormat, legendPosition, segmentNames,
    series, seriesName, multipleAxes,
    actions: { setProp },
  } = useNode((node) => ({
    multipleAxes: node.data.props.multipleAxes,
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
          segmented={!!segmentBy && ((kind || "bar") === "bar" || kind === "line")}
          series={series}
          firstName={typeof seriesName === "string" ? seriesName : ""}
          firstDefault={defaultValueTitle(kind || "bar", aggregate, measure)}
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
              disabled={(aggregate || "count") !== "count" || seriesOf(series).length > 0}
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
            {seriesOf(series).length > 0 && (
              <span className="field-hint">A chart with several series is not segmented</span>
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
function ChartSeriesFields({
  segmented, series, firstName, firstDefault, numbers, names, showLegend, legend, twoAxes,
  sets, chartSet, clauses, setProp,
}: {
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
        A segmented chart has one series: its segments are what the legend names.
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
          <select
            aria-label={`Series ${i + 2} object set`}
            data-testid="chart-series-set"
            value={ownSet(spec) ?? ""}
            onChange={(e) => write(specs.map((s, j) =>
              // Another set's properties are another type's: what was picked
              // for the old one is let go.
              (j === i ? { ...s, objectSetVariable: e.target.value || null, dimension: null,
                           measure: null } : s)))}
          >
            <option value="">The chart&apos;s set</option>
            {sets.filter((v) => v.id !== chartSet).map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
          {own && (
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
              ? { ...s, kind: e.target.value === "bar" || e.target.value === "line"
                  ? e.target.value : null }
              : s)))}
          >
            <option value="">As the chart</option>
            <option value="bar">Bar</option>
            <option value="line">Line</option>
          </select>
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
          write([...specs, { aggregate: "count", measure: null, name: "", axis: "right",
                             objectSetVariable: null, dimension: null, kind: null,
                             drilldownVariable: null }])}
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
    multipleAxes: false,
  },
  related: { settings: ChartSettings },
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
}: {
  actionTypeId?: string | null;
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
    enabled: !!actionType?.object_type_id && !subjectVariable,
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
      {actionType && visibleForm && (
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

function ActionFormSettings() {
  const { workspaceId } = useCanvasEnv();
  const {
    actionTypeId,
    subjectVariable,
    title,
    hideHeader,
    invalidState,
    outputVariable,
    moreActions,
    actions: { setProp },
  } = useNode((node) => ({
    actionTypeId: node.data.props.actionTypeId,
    moreActions: node.data.props.actions,
    subjectVariable: node.data.props.subjectVariable,
    title: node.data.props.title,
    hideHeader: node.data.props.hideHeader,
    invalidState: node.data.props.invalidState,
    outputVariable: node.data.props.outputVariable,
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

CanvasActionForm.craft = {
  displayName: "Action form",
  props: {
    actionTypeId: null, subjectVariable: null, title: "", hideHeader: false,
    parameterDefaults: {}, invalidState: "disabled", outputVariable: null, actions: [],
  },
  related: { settings: ActionFormSettings },
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

function MetricCardSettings() {
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
  dropHandling = false,
  dropLabel = "",
  dropIcon = "",
  dropVariable = null,
  showHeader = false,
  headerIcon = "",
  description = "",
  headerStyle = "block",
  children,
}: {
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
  /** p.58's Block, Contained or Floating (`section-header.ts`). */
  headerStyle?: string;
  /** p.564-568's **Drop Handling**: this section becomes a drop zone for
   * objects dragged from a table cell, an Object View's icon or an Object Set
   * Title (p.569-570). Off by default, because a section that swallowed every
   * drag on the page would be a surprise. */
  dropHandling?: boolean;
  /** p.566's Drop label and Drop icon: what the zone shows while something
   * droppable is over it. The icon is typed, as the header's is, because this
   * platform has no icon set to choose from. */
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

  // p.58's header formats. A floating header moves the section's box to the
  // body (`section-header.styleTarget`), so the header sits on the parent.
  const withHeader = showHeader === true;
  const formatted = headerStyleOf(headerStyle);
  const { padding: boxPadding, ...boxStyle } =
    styleFor({ background, padding, customPadding, border }, saved) as React.CSSProperties;
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
      data-scheme={schemeFor({ background }, saved)}
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
          {dropIcon.trim() && <span aria-hidden="true">{dropIcon.trim()}</span>}
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
              {headerIcon.trim().slice(0, 2)}
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
    dropHandling,
    dropLabel,
    dropIcon,
    dropVariable,
    showHeader,
    headerIcon,
    description,
    headerStyle,
    actions: { setProp },
  } = useNode((node) => ({
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
            <input
              value={headerIcon ?? ""}
              maxLength={2}
              placeholder="◎"
              data-testid="section-header-icon"
              onChange={(e) => setProp((p: { headerIcon: string }) => (p.headerIcon = e.target.value))}
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
            <input
              value={dropIcon ?? ""}
              placeholder="+"
              maxLength={4}
              data-testid="section-drop-icon"
              onChange={(e) => setProp((p: { dropIcon: string }) => (p.dropIcon = e.target.value))}
            />
            <span className="field-hint">A character or emoji; this platform has no icon set</span>
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
    dropHandling: false, dropLabel: "", dropIcon: "", dropVariable: null,
    showHeader: false, headerIcon: "", description: "", headerStyle: "block",
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
   * **A glyph, not a picker** (§445) — the divergence `workshop.md` already
   * records for a Button and a Page, applied where p.47 names it: this
   * platform has no icon library, so a logo is one or two characters an author
   * types. The *behaviour* p.47 describes is faithful; the library is not
   * built, and an emoji or an initial is a mark somebody recognises where an
   * empty square is not.
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
            {mark.text}
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
        <input
          value={icon ?? ""}
          maxLength={2}
          placeholder="◎"
          data-testid="header-icon"
          onChange={(e) => setProp((p: { icon: string }) => (p.icon = e.target.value))}
        />
        <span className="field-hint">
          One or two characters — an emoji or an initial. There is no icon
          library here; it stays visible when a vertical header is collapsed.
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
            <span className="btn-icon btn-icon--left" aria-hidden="true">{item.leftIcon.trim()}</span>
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
              <span className="btn-icon btn-icon--left" aria-hidden="true">{leftIcon.trim()}</span>
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
                <span className="btn-icon btn-icon--left" aria-hidden="true">{leftIcon.trim()}</span>
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
        {collapsed ? glyphFor(icon || leftIcon, label) : (
          <>
            {leftIcon.trim() && (
              <span className="btn-icon btn-icon--left" aria-hidden="true">{leftIcon.trim()}</span>
            )}
            {text}
            {rightIcon.trim() && (
              <span className="btn-icon btn-icon--right" aria-hidden="true">{rightIcon.trim()}</span>
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

function ButtonSettings() {
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
        <span className="field-label">Left icon</span>
        <input
          value={leftIcon ?? ""}
          maxLength={2}
          data-testid="button-left-icon"
          onChange={(e) => setProp((p: { leftIcon: string }) => (p.leftIcon = e.target.value))}
        />
      </label>
      <label className="field">
        <span className="field-label">Right icon</span>
        <input
          value={rightIcon ?? ""}
          maxLength={2}
          data-testid="button-right-icon"
          onChange={(e) => setProp((p: { rightIcon: string }) => (p.rightIcon = e.target.value))}
        />
        <span className="field-hint">A character or emoji either side of the label</span>
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

function EditHistorySettings() {
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

CanvasEditHistory.craft = {
  displayName: "Edit history",
  props: { objectSetVariable: null, order: "newest", properties: "" },
  related: { settings: EditHistorySettings },
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

function DataFreshnessSettings() {
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

CanvasDataFreshness.craft = {
  displayName: "Data freshness",
  props: { items: [], title: "Data freshness" },
  related: { settings: DataFreshnessSettings },
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
