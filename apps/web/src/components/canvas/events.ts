/** The React half of running Workshop events.
 *
 * **Split from `event-run.ts` so the ordering rules can be unit-tested.** This
 * file reaches into `context.tsx` for the capabilities an effect needs, and a
 * `.tsx` in the import graph is a file vitest cannot parse - so before the
 * split, `run` was reachable only through a browser. The rules it enforces
 * (p.80's configured order, and p.85's Reset winning or losing by position)
 * are arithmetic, and arithmetic belongs in a unit test.
 *
 * Everything pure is re-exported here, so no call site had to change.
 */

import { useEditor } from "@craftjs/core";
import { useQueryClient } from "@tanstack/react-query";

import { invalidateCanvasReads } from "./refresh";

import { collapseState, nextCollapsed } from "./collapse";
import { asTabName, tabLabels } from "./tab-selection";
import {
  useCanvasActions,
  useCanvasPage,
  useCanvasParameters,
  useCanvasVariables,
} from "./context";
import type { EventContext } from "./event-run";

export * from "./event-run";

export function useEventContext(
  payload?: Record<string, unknown>,
  overlayIds?: Set<string>,
  object?: EventContext["object"],
): EventContext {
  const { setMany, reset } = useCanvasParameters();
  const {
    go, openOverlay, closeOverlay, collapsed, setCollapsed, tabs, setTab, recompute,
    toggleScheme,
  } = useCanvasPage();
  const queryClient = useQueryClient();
  const { run: runAction } = useCanvasActions();
  const { resolved } = useCanvasVariables();
  const { query } = useEditor();
  return {
    setVariables: setMany,
    resetVariables: reset,
    recomputeVariables: recompute,
    runAction,
    variables: resolved,
    goToPage: go,
    openOverlay,
    closeOverlay,
    overlayIds,
    openUrl: (url: string) => window.open(url, "_blank", "noopener,noreferrer"),
    // p.91's two. `invalidateCanvasReads` is "all data in the module" said by
    // prefix, which is the only form of that sentence a widget added tomorrow
    // is already covered by.
    refreshData: () => { void invalidateCanvasReads(queryClient); },
    toggleTheme: toggleScheme,
    // **Toggle is resolved here, against what is on screen.** The section's
    // own props say which variable backs it and how it starts, and `resolved`
    // says what that variable currently holds - so this is the only place with
    // all three inputs. Reading the tree rather than asking the section is what
    // lets a button expand a section it has never met, which is p.82's own
    // worked example.
    setSectionCollapsed: (section, effect) => {
      let backing: unknown;
      let byDefault = false;
      try {
        const props = query.node(section).get()?.data?.props ?? {};
        const bound = props.collapsedWhen as string | null | undefined;
        backing = bound ? resolved[bound] : undefined;
        byDefault = Boolean(props.collapsedByDefault);
      } catch {
        // No tree to ask - a bare render, or a section deleted since the event
        // was saved. Falling through leaves the effect acting on defaults,
        // which beats throwing part-way through a list of effects.
      }
      const now = collapseState(collapsed[section], backing, byDefault);
      setCollapsed(section, {
        collapsed: nextCollapsed(effect, now),
        against: backing === undefined ? null : Boolean(collapseState(undefined, backing, false)),
      });
    },
    // p.84's event, resolved here for `setSectionCollapsed`'s reason: the
    // section's props say which variable backs its tabs and what they are
    // called, and `resolved` says what that variable holds, so this is the
    // only place with both. Reading the tree rather than asking the section is
    // what lets a button switch a tab in a section it has never met.
    setSectionTab: (section, tab) => {
      let bound: string | null = null;
      let labels: string[] = [];
      try {
        const node = query.node(section).get();
        const props = (node?.data?.props ?? {}) as Record<string, unknown>;
        bound = (props.tabVariable as string | null | undefined) ?? null;
        labels = tabLabels(
          props.tabs as string | undefined,
          (node?.data?.nodes ?? []).length,
        );
      } catch {
        // No tree to ask - a bare render, or a section deleted since the event
        // was saved. Same fall-through as the collapse effect above.
      }
      // An event naming a tab this section does not have is skipped rather
      // than applied. The server refuses one at save, so reaching here means
      // the tab was renamed afterwards - and moving to a tab that is not
      // there would blank the section.
      if (labels.length && !labels.includes(tab)) return null;
      setTab(section, {
        name: tab,
        against: asTabName(bound ? resolved[bound] : undefined, labels),
      });
      return bound ? { variable: bound } : null;
    },
    payload,
    object,
  };
}

/** Run one widget's events for one act.
 *
 * Returns the variables it wrote, mostly so tests can assert on them without a
 * React tree; the context's `setVariables` is what actually applies them.
 */
