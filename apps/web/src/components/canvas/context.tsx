"use client";

import { createContext, useContext } from "react";

/** Environment a canvas widget renders in — never part of the saved
 * definition (Craft.js node props), since it's the same app rendered from
 * different routes (editor, workspace-wide published view) rather than
 * per-widget configuration. Widgets read it via context instead. */
export interface CanvasEnv {
  workspaceId: string;
  projectId: string;
  /** "edit": dragged around the builder canvas, data-bound widgets show a
   * live preview but forms/buttons are inert so a builder can't accidentally
   * submit real writes while arranging the page. "run": the real app, as an
   * end user sees it — forms and actions are live. */
  mode: "edit" | "run";
}

const CanvasContext = createContext<CanvasEnv | null>(null);

export const CanvasEnvProvider = CanvasContext.Provider;

export function useCanvasEnv(): CanvasEnv {
  const env = useContext(CanvasContext);
  if (!env) throw new Error("useCanvasEnv used outside a CanvasEnvProvider");
  return env;
}
