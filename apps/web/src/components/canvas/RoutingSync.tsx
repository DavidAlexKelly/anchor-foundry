"use client";

/** Keeps the address bar and a running module in step (p.195–199).
 *
 * Renders nothing. It exists because routing is two effects pointing in
 * opposite directions, and both need the running module's state:
 *
 *   **inbound, once**: the page a link names becomes the page on screen
 *     (p.197). Variable values arrive by `seedFromQuery` before this mounts,
 *     which is why only the page is read here — that rule is not gated on
 *     routing being on, and this one is.
 *   **outbound, continuously**: what `routingParams` says the URL should hold
 *     is written to it as the viewer filters and navigates (p.198).
 *
 * **Mounted only where routing is on**, so a module that has not enabled it
 * costs nothing and touches no history. That is also why the hooks live here
 * rather than in `VariableBridge`: conditionally *rendering* a component is
 * allowed where conditionally calling a hook is not.
 *
 * **Not in the builder.** In edit mode every page is on screen at once, so
 * "the current page" has no answer and `when_visible` would mean "all of
 * them" — and an author arranging widgets should not be rewriting the URL
 * they will share.
 */

import { useEffect, useMemo, useRef } from "react";

import { useUrlState } from "@/components/use-url-state";
import type { WorkshopVariable } from "@/lib/types";
import { useCanvasPage, useCanvasParameters } from "./context";
import {
  PAGE_PARAM, defaultPageNode, pageIdOf, pageNodeFor, routingParams, variablesOnPage,
} from "./routing";

export function RoutingSync({
  layout,
  declared,
}: {
  layout: unknown;
  declared: Record<string, WorkshopVariable>;
}) {
  const url = useUrlState();
  const { values } = useCanvasParameters();
  const { current, go } = useCanvasPage();

  // The page a link names, applied once. Re-applying it would fight the
  // viewer: navigating away rewrites the parameter, and reading it back would
  // send them straight to where they came from.
  const seeded = useRef(false);
  const wanted = url.get(PAGE_PARAM);
  useEffect(() => {
    if (seeded.current) return;
    seeded.current = true;
    const node = pageNodeFor(layout, wanted);
    if (node) go(node);
    // A page ID that names nothing is not an error (p.197): the module opens
    // on its default page, which is what `current === null` already means.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // `current` is null until somebody navigates, and that means "the first
  // page" rather than "no page" — so the URL has to say what the reader is
  // actually looking at, not what they have clicked.
  const showing = current ?? defaultPageNode(layout);
  const visible = useMemo(() => variablesOnPage(layout, showing), [layout, showing]);
  const next = routingParams({
    enabled: true,
    variables: declared as Record<string, WorkshopVariable & { id: string; kind: string }>,
    values,
    pageId: pageIdOf(layout, showing),
    visible,
  });

  // Every key this module could own, so a value that stops qualifying is
  // *removed* rather than left behind. A stale parameter is worse than a
  // missing one: it would be read back by `seedFromQuery` on the next load and
  // restore a filter nobody has applied.
  const owned = useMemo(
    () => [PAGE_PARAM, ...Object.values(declared).map((v) => v.external_id).filter(Boolean)],
    [declared],
  );

  const serialised = JSON.stringify(next);
  useEffect(() => {
    const change: Record<string, string | undefined> = {};
    for (const key of owned) change[key as string] = undefined;
    url.set({ ...change, ...next });
    // Keyed on the *content* of the answer, not on the objects that produced
    // it: `values` is a fresh object every render, and depending on it would
    // write to the router on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialised, owned.join(",")]);

  return null;
}
