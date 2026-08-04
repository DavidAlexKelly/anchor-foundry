/** Running Workshop events (roadmap phase 2, item 1.3).
 *
 * An event is a trigger and an ordered list of effects. This runs them, and
 * the ordering rules are the whole of it — Foundry's semantics, matched
 * deliberately, because the alternative produces different results for the
 * same configuration and is invisible until somebody's app misbehaves.
 *
 * **Effects run in configured order.** Two effects writing two variables must
 * apply in the order somebody arranged them.
 *
 * **Setting a variable copies the value immediately, so the next effect sees
 * it.** That is why `run` threads a plain object through the loop rather than
 * reading React state between effects: state updates are batched and would not
 * be visible to the next iteration, so an effect reading a variable a previous
 * effect just set would read the *old* value — silently, and only sometimes.
 *
 * **Nothing here awaits downstream recomputation.** Setting a variable
 * eventually causes the server to re-resolve and widgets to re-fetch; effects
 * do not wait for that. Awaiting it would serialise a click's effects behind
 * network round trips, and would change what a second effect sees.
 *
 * The server refuses the events that cannot work at all — a trigger on a
 * missing widget, a write to a derived variable, a url a browser should not
 * follow (`services/workshop_events.py`). This side assumes a validated
 * document and concerns itself with *when* things happen.
 */

import { useCanvasPage, useCanvasParameters } from "./context";

export interface WorkshopEffect {
  type: string;
  config?: Record<string, unknown>;
}

export interface WorkshopEventDef {
  id: string;
  trigger: { node: string; on: string };
  effects?: WorkshopEffect[];
}

export interface EventContext {
  /** Go to a page (roadmap 1.4). Absent in a context that has no pages, in
   * which case a navigate effect is skipped rather than throwing — see the
   * note on unknown effects below. */
  goToPage?: (nodeId: string) => void;
  /** Open a node as an overlay over the current page, and close it again. */
  openOverlay?: (nodeId: string) => void;
  closeOverlay?: () => void;
  /** Which node ids are overlays rather than pages. `navigate` accepts either
   * and this is how it tells them apart - read from the tree by the caller,
   * because the effect itself has no view of the layout. */
  overlayIds?: Set<string>;
  /** Applies every variable write from this run, once, at the end. Called with
   * the accumulated map rather than per effect so one click is one render. */
  setVariables: (values: Record<string, unknown>) => void;
  /** What the widget knows about the thing that was acted on — the clicked
   * row, the chosen option. `{{...}}` in an effect's value reads from here. */
  payload?: Record<string, unknown>;
  /** The *object* the trigger was about, whole: type, key and properties.
   * What a `set_variable` with `from: "object"` writes into a `single_object`
   * variable, and what `object_property` then reads a property out of.
   *
   * Separate from `payload`, which is flattened for `{{...}}` interpolation
   * and cannot say which of its keys is the primary key. */
  object?: { object_type_id?: string; primary_key: unknown; properties: Record<string, unknown> };
  openUrl?: (url: string) => void;
}

/** Events on one widget for one act, in id order — the same order the server's
 * `for_node` produces, so what runs does not depend on which side sorted it. */
export function eventsFor(
  events: Record<string, WorkshopEventDef> | undefined,
  node: string,
  on: string,
): WorkshopEventDef[] {
  if (!events) return [];
  return Object.keys(events)
    .sort()
    .map((id) => events[id]!)
    .filter((e) => e.trigger?.node === node && e.trigger?.on === on);
}

const TOKEN = /\{\{\s*([A-Za-z0-9_.]+)\s*\}\}/g;

/** `{{name}}` from the trigger's payload. A token naming nothing resolves to
 * an empty string rather than to the literal `{{name}}`: a half-substituted
 * label reads as a data problem, while an empty one reads as a missing value,
 * which is what it is. */
export function interpolate(template: string, payload: Record<string, unknown>): string {
  return template.replace(TOKEN, (_match, key: string) => {
    const value = payload[key];
    return value === undefined || value === null ? "" : String(value);
  });
}

/** Everything a widget needs to run an event, assembled once.
 *
 * Widgets used to build this by hand, and the first one to do so forgot
 * `goToPage` — so a `navigate` effect was silently skipped and a row click
 * that should have changed page did nothing. Skipping an effect whose
 * capability is absent is the right *runtime* rule (see the note in `run`),
 * which is exactly why the capability must not be absent by accident. One
 * hook, so there is nothing to forget.
 */
export function useEventContext(
  payload?: Record<string, unknown>,
  overlayIds?: Set<string>,
  object?: EventContext["object"],
): EventContext {
  const { setMany } = useCanvasParameters();
  const { go, openOverlay, closeOverlay } = useCanvasPage();
  return {
    setVariables: setMany,
    goToPage: go,
    openOverlay,
    closeOverlay,
    overlayIds,
    openUrl: (url: string) => window.open(url, "_blank", "noopener,noreferrer"),
    payload,
    object,
  };
}

/** Run one widget's events for one act.
 *
 * Returns the variables it wrote, mostly so tests can assert on them without a
 * React tree; the context's `setVariables` is what actually applies them.
 */
export function run(
  events: WorkshopEventDef[],
  context: EventContext,
): Record<string, unknown> {
  const payload = context.payload ?? {};
  // The copy every effect reads and writes. Threaded through the loop so an
  // effect sees what the previous one set — see the note at the top.
  const written: Record<string, unknown> = {};

  for (const event of events) {
    for (const effect of event.effects ?? []) {
      const config = effect.config ?? {};
      if (effect.type === "set_variable") {
        const target = String(config.variable ?? "");
        if (!target) continue;
        if (config.from === "object") {
          // Nothing picked writes nothing, rather than writing undefined: an
          // effect that cleared the variable it was meant to fill would be
          // indistinguishable from one that ran and found nothing.
          if (context.object) written[target] = context.object;
          continue;
        }
        const raw = config.value;
        written[target] =
          typeof raw === "string" ? interpolate(raw, { ...payload, ...written }) : raw;
      } else if (effect.type === "navigate") {
        const target = String(config.page ?? "");
        if (!target) continue;
        if (context.overlayIds?.has(target)) context.openOverlay?.(target);
        else context.goToPage?.(target);
      } else if (effect.type === "close_overlay") {
        context.closeOverlay?.();
      } else if (effect.type === "open_url") {
        const url = typeof config.url === "string"
          ? interpolate(config.url, { ...payload, ...written })
          : "";
        if (url && context.openUrl) context.openUrl(url);
      }
      // An unknown effect type is skipped rather than thrown: the server
      // refuses them at save, so one arriving here means a document written by
      // something older, and a click that does part of its job beats a click
      // that throws in the middle of the list.
    }
  }

  if (Object.keys(written).length > 0) context.setVariables(written);
  return written;
}
