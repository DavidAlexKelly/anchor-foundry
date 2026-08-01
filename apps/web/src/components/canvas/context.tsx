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
}

const ParameterContext = createContext<CanvasParameters | null>(null);

export function CanvasParameterProvider({ children }: { children: React.ReactNode }) {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const set = useCallback((name: string, value: unknown) => {
    setValues((current) => ({ ...current, [name]: value }));
  }, []);
  const value = useMemo(() => ({ values, set }), [values, set]);
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
