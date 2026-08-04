"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

/** Environment a canvas widget renders in - never part of the saved
 * definition (Craft.js node props), since it's the same app rendered from
 * different routes (editor, workspace-wide published view) rather than
 * per-widget configuration. Widgets read it via context instead. */
export interface CanvasEnv {
  workspaceId: string;
  projectId: string;
  /** "edit": dragged around the builder canvas, data-bound widgets show a
   * live preview but forms/buttons are inert so a builder can't accidentally
   * submit real writes while arranging the page. "run": the real app, as an
   * end user sees it - forms and actions are live. */
  mode: "edit" | "run";
}

const CanvasContext = createContext<CanvasEnv | null>(null);

export const CanvasEnvProvider = CanvasContext.Provider;

export function useCanvasEnv(): CanvasEnv {
  const env = useContext(CanvasContext);
  if (!env) throw new Error("useCanvasEnv used outside a CanvasEnvProvider");
  return env;
}

/**
 * Shared parameter state (ROADMAP Canvas item 1) — the mechanism cross-widget
 * interactivity is built on: one widget sets a named value, any number of
 * others read it.
 *
 * A separate context from CanvasEnv, for a reason worth keeping: this one
 * changes on every interaction, while CanvasEnv changes only when the app
 * remounts or the edit/run mode flips. Merging them would make every widget
 * that only wants "which workspace am I in" re-render on every keystroke.
 *
 * **Values are runtime state, not part of the saved app.** A parameter's
 * name, label and options are Craft.js node props and are serialised with the
 * app; the value a viewer currently has selected is not, for exactly the
 * reason CanvasEnv isn't — it belongs to this render of the app, not to its
 * definition. So a published app opens at its defaults for every viewer
 * rather than at whatever the last person happened to choose.
 */
export interface CanvasParameters {
  values: Record<string, unknown>;
  set: (name: string, value: unknown) => void;
  /** Apply several at once. One event's effects are one render, and applying
   * them one at a time would let a widget re-fetch against a half-applied set
   * of writes. */
  setMany: (values: Record<string, unknown>) => void;
}

const ParameterContext = createContext<CanvasParameters | null>(null);

/**
 * Resolved variable values, computed by the server (roadmap 1.2).
 *
 * Two maps rather than one, and the distinction is the whole design:
 * `values` above is **what the viewer has set** - a dropdown selection, a row
 * click - and is written by widgets. This one is **what every variable
 * currently resolves to**, including derived ones, and is written only by the
 * server. A widget reading a derived variable reads this; a widget setting a
 * filter writes that.
 *
 * Merging them would let a widget write a derived variable, which is a value
 * that is a function of its inputs - so the same document could show two
 * different things depending on which write the reader believed.
 */
export interface CanvasVariables {
  /** The module's events, by id. Widgets look up their own triggers here
   * rather than holding them in props - an event routinely spans widgets, and
   * nesting it in the trigger's node would hide it from the widget it acts
   * on (decision 0002 §4). */
  events?: Record<string, import("./events").WorkshopEventDef>;
  /** What the module *declares*. Widget settings read this to offer a picker
   * of variables to bind to, which is the whole reason a binding is a choice
   * from a list rather than a name somebody types and hopes matches. */
  declared: Record<string, import("@/lib/types").WorkshopVariable>;
  resolved: Record<string, unknown>;
  /** True while the first resolve is in flight. A widget that rendered "0
   * results" during it would be reporting an answer it does not have. */
  pending: boolean;
}

const VariableContext = createContext<CanvasVariables>({
  declared: {},
  resolved: {},
  pending: false,
});

export const CanvasVariableProvider = VariableContext.Provider;

export function useCanvasVariables(): CanvasVariables {
  return useContext(VariableContext);
}

/** One variable's resolved value - a scalar for most kinds, an object-set
 * *definition* for `object_set`. Undefined while nothing has resolved it, which
 * a consumer reads as "not yet", never as "empty". */
export function useCanvasVariable(id: string | null | undefined): unknown {
  const { resolved } = useCanvasVariables();
  return id ? resolved[id] : undefined;
}

export function CanvasParameterProvider({ children }: { children: React.ReactNode }) {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const set = useCallback((name: string, value: unknown) => {
    setValues((current) => ({ ...current, [name]: value }));
  }, []);
  const setMany = useCallback((next: Record<string, unknown>) => {
    setValues((current) => ({ ...current, ...next }));
  }, []);
  const value = useMemo(() => ({ values, set, setMany }), [values, set, setMany]);
  return <ParameterContext.Provider value={value}>{children}</ParameterContext.Provider>;
}

export function useCanvasParameters(): CanvasParameters {
  const params = useContext(ParameterContext);
  if (!params) {
    throw new Error("useCanvasParameters used outside a CanvasParameterProvider");
  }
  return params;
}

/** One parameter's current value. `undefined` when nothing has set it, which
 * a consumer must read as "no filter" rather than "filter to nothing" — an
 * app whose table is empty until you touch a dropdown looks broken on first
 * load. */
export function useCanvasParameter(name: string | null | undefined): unknown {
  const { values } = useCanvasParameters();
  return name ? values[name] : undefined;
}

/**
 * Which page of a multi-page module is showing (roadmap 1.4).
 *
 * **Runtime state, never persisted** — the same rule variable values follow
 * (decision 0002 §3). A published app opens on its first page for every
 * viewer rather than on whatever page the last person happened to be looking
 * at; a saved app is not a saved session.
 *
 * `current` is null until something sets it, which a page reads as "show me if
 * I am the first one". That is a deliberate alternative to seeding it with the
 * first page's id at mount: the layout is what decides which page is first,
 * and duplicating that decision into state would make the two disagree the
 * moment somebody reorders the pages.
 */
export interface CanvasPageState {
  current: string | null;
  go: (nodeId: string) => void;
  /** The overlay covering the page, if any. Held apart from `current` because
   * an overlay does not replace the page - closing one returns you to what was
   * underneath, which a single "where am I" value cannot express. */
  overlay: string | null;
  openOverlay: (nodeId: string) => void;
  closeOverlay: () => void;
}

const PageContext = createContext<CanvasPageState>({
  current: null,
  go: () => {},
  overlay: null,
  openOverlay: () => {},
  closeOverlay: () => {},
});

export const CanvasPageProvider = PageContext.Provider;

export function useCanvasPage(): CanvasPageState {
  return useContext(PageContext);
}
