"use client";

/**
 * Auto-refresh, wired up (`foundry_workshop` p.576-580; §408).
 *
 * > "When an update occurs, all data in the current module will automatically
 * > refresh without user interaction." (p.576)
 *
 * A component rather than a hook so it can sit once beside the canvas and
 * render nothing: the rules are `auto-refresh.ts`, the effect is
 * `invalidateCanvasReads`, and what is here is the timer between them.
 */
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { objects as objApi } from "@/lib/api";
import {
  applyNow, changed, intervalMs, running, settingsOf, stamp, watchedTypes,
} from "./auto-refresh";
import { invalidateCanvasReads } from "./refresh";
import { useCanvasEnv, useCanvasPage, useCanvasVariables } from "./context";

export function AutoRefresh({ setting }: { setting: unknown }) {
  const { workspaceId, mode } = useCanvasEnv();
  const { resolved } = useCanvasVariables();
  // p.578: a reader can pause the *application* of updates with a button.
  const { autoRefreshPaused } = useCanvasPage();
  const queryClient = useQueryClient();

  const settings = settingsOf(setting);
  const types = watchedTypes(settings, resolved as Record<string, unknown>);
  const on = running(settings, mode) && types.length > 0;

  /** The last watermark seen. A ref, not state: it changes on every poll and
   * re-rendering the whole module to remember a string would be a re-render
   * per interval for nothing. */
  const seen = useRef<string | null>(null);
  /** A change noticed while the tab was in the background (p.579). Held rather
   * than dropped, which is the difference between catching up and silently
   * missing the update. */
  const pending = useRef(false);
  const [visible, setVisible] = useState(true);
  // A ref as well as the value, so the poll running on a timer reads what
  // is true now rather than what was true when the interval was armed.
  const paused = useRef(autoRefreshPaused);
  paused.current = autoRefreshPaused;

  useEffect(() => {
    if (typeof document === "undefined") return;
    const read = () => setVisible(document.visibilityState !== "hidden");
    read();
    document.addEventListener("visibilitychange", read);
    return () => document.removeEventListener("visibilitychange", read);
  }, []);

  // **The watermark is forgotten when the watch list changes.** Otherwise
  // registering a second set would compare the new list's stamp against the
  // old list's and refresh once for a change nobody made.
  const key = types.join(",");
  useEffect(() => {
    seen.current = null;
    pending.current = false;
  }, [key, on]);

  useEffect(() => {
    if (!on) return;
    let stopped = false;

    async function poll() {
      let next: string | null = null;
      try {
        const answer = await objApi.objectTypeFreshness(workspaceId, types);
        next = stamp(answer.types);
      } catch {
        // **A failed poll is not a change.** p.580 names an unstable network
        // as a thing that breaks auto-refresh; the worst version of that is a
        // dropped request read as "everything changed", which would refresh
        // the module every time the connection wobbled.
        return;
      }
      if (stopped) return;
      if (changed(seen.current, next)) pending.current = true;
      seen.current = next;
      if (pending.current
          && applyNow(document.visibilityState !== "hidden", paused.current)) {
        pending.current = false;
        void invalidateCanvasReads(queryClient);
      }
    }

    void poll();
    const timer = setInterval(() => { void poll(); }, intervalMs(settings));
    return () => { stopped = true; clearInterval(timer); };
    // `key` stands in for `types`, which is a new array every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, key, workspaceId, settings.seconds, queryClient]);

  // p.579's "at which point a reload will immediately be triggered": a change
  // that arrived while the tab was away is applied the moment it comes back,
  // without waiting for the next interval.
  // p.579's "at which point a reload will immediately be triggered", and
  // p.578's "Allows updates from auto-refresh to take effect": a change that
  // arrived while the tab was away *or* while a reader had paused is applied
  // the moment that stops being true, without waiting for the next interval.
  useEffect(() => {
    if (!on || !applyNow(visible, autoRefreshPaused) || !pending.current) return;
    pending.current = false;
    void invalidateCanvasReads(queryClient);
  }, [on, visible, autoRefreshPaused, queryClient]);

  return null;
}
