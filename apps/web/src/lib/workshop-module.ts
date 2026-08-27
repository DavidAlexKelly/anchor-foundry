/** Reading and writing the Workshop module document (decision 0002).
 *
 * Every place in the browser that touches a saved app goes through here, for
 * one reason: after migration 0034 a stored definition is `{format, layout,
 * variables, events}`, and anything that still hands the whole document to
 * Craft.js's `<Frame data=…>` renders an app with three widgets called
 * "format", "variables" and "events" - or, more likely, nothing at all.
 *
 * Both shapes are handled rather than only v2. A deployment that has not run
 * the migration yet still serves v1 documents, and the browser is not the
 * place to find that out. `isV2` is a structural check, not a version compare,
 * because a v1 document has `ROOT` at the top level and a v2 one has `layout` -
 * exactly the distinction decision 0002 §5 says a reader must not have to
 * guess at.
 *
 * **Nothing here evaluates a variable.** Derived values come from the server
 * (`canvasApi.evaluateVariables`), so the transformation semantics have one
 * implementation rather than two that drift - see the API route's own note.
 */
import type { WorkshopEvent, WorkshopModule, WorkshopVariable } from "./types";

/** A Craft.js serialised node map: what `<Frame data>` wants and what
 * `query.getSerializedNodes()` produces. */
export type LayoutNodes = Record<string, unknown>;

export function isV2(definition: unknown): definition is WorkshopModule {
  return (
    typeof definition === "object" &&
    definition !== null &&
    (definition as { format?: unknown }).format === 2
  );
}

/** The node map to render, whichever format the document is in. */
export function layoutOf(definition: unknown): LayoutNodes {
  if (isV2(definition)) return (definition.layout ?? {}) as LayoutNodes;
  return (definition ?? {}) as LayoutNodes;
}

export function variablesOf(definition: unknown): Record<string, WorkshopVariable> {
  return isV2(definition) ? definition.variables ?? {} : {};
}

/** The module's events. Empty for a v1 document, which had no way to express
 * one - a Filter's behaviour was hardcoded into the Filter. */
export function eventsOf(definition: unknown): Record<string, WorkshopEvent> {
  return isV2(definition) ? definition.events ?? {} : {};
}

/** True when there is something to render - the question the builder asks to
 * decide between a saved app and a starter layout. Asked of the *layout*, so a
 * module carrying variables but no widgets still reads as empty, which is what
 * it looks like on screen. */
export function hasLayout(definition: unknown): boolean {
  return Object.keys(layoutOf(definition)).length > 0;
}

/** The document to save.
 *
 * The layout and the variables come from two different places - Craft.js owns
 * one, the variables panel owns the other - and **both have to be in the same
 * save**. Anything left out is carried across from the stored document rather
 * than dropped: a save that omitted the variables would unbind every widget in
 * the app, and it would do it on the first save after opening, which is to say
 * immediately and invisibly.
 */
export function moduleFrom(
  definition: unknown,
  parts: {
    layout?: LayoutNodes;
    variables?: Record<string, WorkshopVariable>;
    events?: Record<string, WorkshopEvent>;
    routing?: { enabled: boolean };
    stateSaving?: WorkshopModule["state_saving"];
    /** The variable backing page selection (p.81). `""` clears it — which is
     * why this is `string` rather than `string | undefined`: an undefined
     * would be indistinguishable from "not part of this save" and would make
     * the setting impossible to turn off. */
    pageSelection?: string;
  },
): WorkshopModule {
  const current = isV2(definition) ? definition : undefined;
  const routing = parts.routing ?? current?.routing;
  const stateSaving = parts.stateSaving ?? current?.state_saving;
  const pageSelection = parts.pageSelection ?? current?.page_selection;
  return {
    format: 2,
    layout: parts.layout ?? layoutOf(definition),
    variables: parts.variables ?? current?.variables ?? {},
    events: parts.events ?? current?.events ?? {},
    ...(current?.broken_bindings ? { broken_bindings: current.broken_bindings } : {}),
    // Carried rather than defaulted: a save that omitted it would turn routing
    // off for every module built before this existed, which is the same class
    // of quiet loss `broken_bindings` is carried to avoid.
    ...(routing ? { routing } : {}),
    ...(stateSaving ? { state_saving: stateSaving } : {}),
    // Same carry, same reason. Omitted when empty rather than written as `""`
    // so that turning it off leaves a document indistinguishable from one that
    // never had it - the server reads absent and empty alike, and a stored
    // empty string is a setting that looks configured in a diff.
    ...(pageSelection ? { page_selection: pageSelection } : {}),
  };
}

/** Whether a module writes its state to the URL (p.195). */
export function routingOf(definition: unknown): boolean {
  return isV2(definition) ? Boolean(definition.routing?.enabled) : false;
}

/** The variable backing Variable-Based Page Selection, or "" (p.81).
 *
 * Empty string rather than null for the reason `moduleFrom` takes one: this is
 * the value of a `<select>`, and a control whose "none" is null needs every
 * reader to convert it back.
 */
export function pageSelectionOf(definition: unknown): string {
  const stored = isV2(definition) ? definition.page_selection : undefined;
  return typeof stored === "string" ? stored : "";
}

/** A module's state-saving settings (p.201, p.204), with Foundry's own default
 * wording so an unconfigured module still has something to call a state. */
export function stateSavingOf(
  definition: unknown,
): NonNullable<WorkshopModule["state_saving"]> {
  const stored = isV2(definition) ? definition.state_saving : undefined;
  return {
    enabled: Boolean(stored?.enabled),
    display_name: stored?.display_name || "module state",
    display_name_plural: stored?.display_name_plural || "module states",
    include_page: stored?.include_page ?? true,
  };
}

/** Props whose value is a variable id. Mirrors `REFERENCE_PROPS` in
 * `services/workshop_variables.py`; the server is what refuses a save, so this
 * copy only decides what the builder *shows* as a usage. Drift here makes the
 * builder's warning wrong, not the document. */
export const REFERENCE_PROPS = [
  "filterParameter",
  "searchParameter",
  "variable",
  "objectSetVariable",
  "enabledVariable",
  "visibleWhen",
  "subjectVariable",
  "drilldownVariable",
  "seriesVariable",
  // A section's collapse backing (p.82) and its tab backing (p.84). Both hold
  // a variable id and neither was here until §191 found them; see the note on
  // the API's copy.
  "collapsedWhen",
  "tabVariable",
  // p.133's array to loop through — see the note on the API's copy.
  "arrayVariable",
  // p.461's dynamic option generation - a String Selector's options come from
  // a string array variable, so that variable is in use. See the API's copy.
  "optionsVariable",
  // p.464's Default timezone read from a variable. See the API's copy.
  "timezoneVariable",
  "name",
] as const;

export interface Usage {
  node: string;
  prop: string;
}

/** Where a variable is referenced, so the builder can say "used by 2 widgets"
 * before offering to delete it rather than after the server refuses. */
export function usagesOf(
  definition: unknown,
  variableId: string,
): Usage[] {
  const found: Usage[] = [];
  const layout = layoutOf(definition);
  for (const [nodeId, node] of Object.entries(layout)) {
    const props = (node as { props?: Record<string, unknown> })?.props;
    if (!props) continue;
    for (const prop of REFERENCE_PROPS) {
      if (props[prop] === variableId) found.push({ node: nodeId, prop });
    }
  }
  for (const variable of Object.values(variablesOf(definition))) {
    if (variable.derivation?.inputs?.includes(variableId)) {
      found.push({ node: variable.id, prop: "derivation" });
    }
  }
  return found;
}

/** `v_` plus a short random suffix (decision 0002 §2). Not derived from the
 * label: a derived id is a rename waiting to break every reference, which is
 * the exact failure this format removes. */
export function newVariableId(): string {
  return `v_${Math.random().toString(36).slice(2, 10)}`;
}

export function newEventId(): string {
  return `e_${Math.random().toString(36).slice(2, 10)}`;
}

/** A fresh layout node id, for a paste (p.55).
 *
 * Craft.js mints its own when a widget is dragged in, and this is the same
 * kind of thing by a different route: a paste rewrites the serialised map
 * directly, so it has to supply ids Craft has not seen. The format is ours
 * rather than Craft's on purpose - nothing may depend on the shape of a node
 * id, which is exactly why a page carries an author-set `pageId` (p.197).
 */
export function newNodeId(): string {
  return `n_${Math.random().toString(36).slice(2, 10)}`;
}
