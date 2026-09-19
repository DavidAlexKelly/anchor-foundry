"use client";

/** Profiler mode: recording what a module loads (§394; p.177-178).
 *
 * > "Entering Profiler mode will refresh the module's web browser page to
 * > allow the profiler to record network requests, starting from the module's
 * > initialization." (p.177)
 *
 * **The reload is the feature, not an implementation detail.** A recorder that
 * started when somebody pressed a button would miss everything a module does
 * on the way up, which is the part worth profiling. So profiler mode lives in
 * the URL: entering navigates with the flag on, leaving navigates with it off,
 * and either way the page comes up fresh with the recorder already listening.
 *
 * Two sources feed it, and they are different kinds of measurement for a
 * reason `profiler.ts` sets out:
 *
 *   * **variables**, timed by the evaluator and sent back with the values,
 *     because this platform resolves the whole visible closure in one request
 *     and a network measurement could only report one number for all of them;
 *   * **requests**, timed here by subscribing to the query cache — one
 *     chokepoint rather than sixty-two call sites, which is also why a row
 *     names the request rather than the widget that made it.
 */

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { merge, PROFILER_PARAM, keyName, type LoadEvent } from "./profiler";

export interface ProfilerState {
  on: boolean;
  events: LoadEvent[];
  /** p.178's "clear all captured load events". */
  clear: () => void;
  /** Report a batch of variable timings from a resolve that has landed. */
  recordVariables: (
    timings: Record<string, number>,
    labelFor: (id: string) => string,
  ) => void;
}

const ProfilerContext = createContext<ProfilerState | null>(null);

/** Never throws for a canvas rendered outside a recorder — a Craft.js preview,
 * a test, an object view. Profiling is an opt-in overlay on a module, so its
 * absence is the ordinary case and must not be an error. */
export function useProfiler(): ProfilerState {
  return useContext(ProfilerContext) ?? OFF;
}

const OFF: ProfilerState = {
  on: false,
  events: [],
  clear: () => {},
  recordVariables: () => {},
};


export function ProfilerRecorder({
  on,
  children,
}: {
  on: boolean;
  children: React.ReactNode;
}) {
  void PROFILER_PARAM;
  const client = useQueryClient();
  const [events, setEvents] = useState<LoadEvent[]>([]);
  // The zero of every `at`. Captured on mount rather than at the first event,
  // because p.177 measures "starting from the module's initialization" and the
  // gap before the first request is exactly what a slow module spends.
  const origin = useRef(0);
  if (origin.current === 0) origin.current = performance.now();
  // Fetch starts, by query hash. A ref rather than state: a render per
  // in-flight request would make the profiler the slowest thing in the module.
  const started = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    if (!on) return;
    const cache = client.getQueryCache();
    return cache.subscribe((event) => {
      const query = event.query;
      if (query === undefined) return;
      const hash = query.queryHash;
      const fetching = query.state.fetchStatus === "fetching";
      if (fetching) {
        if (!started.current.has(hash)) started.current.set(hash, performance.now());
        return;
      }
      const began = started.current.get(hash);
      if (began === undefined) return;
      started.current.delete(hash);
      const now = performance.now();
      const row: LoadEvent = {
        id: hash,
        kind: "request",
        name: keyName(query.queryKey as readonly unknown[]),
        ms: now - began,
        at: began - origin.current,
        loads: 1,
      };
      setEvents((current) => merge(current, row));
    });
  }, [on, client]);

  const state: ProfilerState = {
    on,
    events,
    clear: () => {
      // The clock restarts with the list. p.178 offers "clear all captured
      // load events" as a way to watch one interaction, and a timeline whose
      // zero was still the page load would put every new row at the far right.
      origin.current = performance.now();
      started.current.clear();
      setEvents([]);
    },
    recordVariables: (timings, labelFor) => {
      const at = performance.now() - origin.current;
      setEvents((current) => {
        let next = current;
        for (const [id, ms] of Object.entries(timings)) {
          next = merge(next, {
            id, kind: "variable", name: labelFor(id), ms, at, loads: 1,
          });
        }
        return next;
      });
    },
  };

  return <ProfilerContext.Provider value={state}>{children}</ProfilerContext.Provider>;
}
