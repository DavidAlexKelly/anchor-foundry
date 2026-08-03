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
  /** Applies every variable write from this run, once, at the end. Called with
   * the accumulated map rather than per effect so one click is one render. */
  setVariables: (values: Record<string, unknown>) => void;
  /** What the widget knows about the thing that was acted on — the clicked
   * row, the chosen option. `{{...}}` in an effect's value reads from here. */
  payload?: Record<string, unknown>;
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
        const raw = config.value;
        written[target] =
          typeof raw === "string" ? interpolate(raw, { ...payload, ...written }) : raw;
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
