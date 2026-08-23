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

import { collapseState, nextCollapsed } from "./collapse";
import { asTabName, tabLabels } from "./tab-selection";

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
  /** p.85's Reset. A separate capability from `setVariables` because it is a
   * *deletion* - writing the default instead would be wrong for a variable an
   * embedding module has mapped, whose definition is the parent's (p.128). */
  resetVariables?: (names: readonly string[]) => void;
  /** What the widget knows about the thing that was acted on — the clicked
   * row, the chosen option. `{{...}}` in an effect's value reads from here. */
  payload?: Record<string, unknown>;
  /** The *object* the trigger was about, whole: type, key and properties.
   * What a `set_variable` with `from: "object"` writes into a `single_object`
   * variable, and what `object_property` then reads a property out of.
   *
   * Separate from `payload`, which is flattened for `{{...}}` interpolation
   * and cannot say which of its keys is the primary key. */
  object?: {
    /** The instance's own id. Carried because it is what the *write* APIs
     * take: an action executes against an instance id, so an object you can
     * look at but not edit would be half a reference. */
    id?: string;
    object_type_id?: string;
    primary_key: unknown;
    properties: Record<string, unknown>;
  };
  openUrl?: (url: string) => void;
  /** p.82's Expand/Collapse/Toggle. Takes the effect rather than a boolean so
   * Toggle is resolved against *what is on screen* - the caller knows both the
   * override and the backing variable, and this list does not. A Toggle
   * computed from the variable instead would look like the feature working
   * right up until an event and a variable disagree, which p.82 says they are
   * allowed to. */
  setSectionCollapsed?: (
    section: string,
    effect: "expand_section" | "collapse_section" | "toggle_section",
  ) => void;
  /** p.84's Switch to {tab name}. Takes the tab's *name* because that is how
   * p.84 addresses one, and returns the variable write it implies rather than
   * performing it — see the note beside the `switch_tab` branch in `run`. */
  setSectionTab?: (section: string, tab: string) => { variable: string } | null;
  /** Run an action against the object the trigger was about (roadmap 1.3).
   * The only effect that writes, and so the only one whose outcome anybody
   * has to be told about — see `CanvasActions`. */
  runAction?: (
    config: { action: string; subject: string; values?: Record<string, string> },
    context: { object?: EventContext["object"] | null },
  ) => void;
  /** The module's variables as last resolved. Read by `run_action` to find
   * the object its subject variable holds, when this click did not set it. */
  variables?: Record<string, unknown>;
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
export function run(
  events: WorkshopEventDef[],
  context: EventContext,
): Record<string, unknown> {
  const payload = context.payload ?? {};
  // The copy every effect reads and writes. Threaded through the loop so an
  // effect sees what the previous one set — see the note at the top.
  const written: Record<string, unknown> = {};
  // p.85's Resets, accumulated beside the writes. Kept apart because one is a
  // write and the other a deletion, and applied together at the end so a click
  // is one render - the same argument `setMany` makes.
  const toReset = new Set<string>();

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
          if (context.object) { toReset.delete(target); written[target] = context.object; }
          continue;
        }
        const raw = config.value;
        toReset.delete(target);
        written[target] =
          typeof raw === "string" ? interpolate(raw, { ...payload, ...written }) : raw;
      } else if (effect.type === "navigate") {
        const target = String(config.page ?? "");
        if (!target) continue;
        if (context.overlayIds?.has(target)) context.openOverlay?.(target);
        else context.goToPage?.(target);
      } else if (effect.type === "close_overlay") {
        context.closeOverlay?.();
      } else if (effect.type === "run_action") {
        const action = String(config.action ?? "");
        const subject = String(config.subject ?? "");
        if (!action || !subject || !context.runAction) continue;
        // The subject is a variable holding an object, and a previous effect
        // in this same click may have just set it — a row click that picks the
        // object and then acts on it is the obvious pairing. So read the
        // written copy first, exactly as `{{...}}` does.
        // The variable the config names, and nothing else. Falling back to the
        // trigger's own object when that variable holds something different
        // would act on an object nobody named — a write to the wrong row,
        // which is the one mistake this effect must not make quietly.
        const held = (written[subject] ?? context.variables?.[subject]) as
          | EventContext["object"]
          | undefined;
        const raw = (config.values ?? {}) as Record<string, unknown>;
        const values: Record<string, string> = {};
        for (const [prop, template] of Object.entries(raw)) {
          values[prop] =
            typeof template === "string"
              ? interpolate(template, { ...payload, ...written })
              : String(template ?? "");
        }
        context.runAction({ action, subject, values }, { object: held ?? null });
      } else if (
        effect.type === "expand_section"
        || effect.type === "collapse_section"
        || effect.type === "toggle_section"
      ) {
        const section = String(config.section ?? "");
        // **p.82's gotcha lives in what is *not* here.** These three write no
        // variable: "If the specified section has a Boolean variable backing
        // the collapse state, the value of this variable will not be updated
        // as a result of one of these events." Nothing is added to `written`,
        // so a backing variable is left exactly as it was - which is why the
        // page tells the builder to add a Set Variable Value event if they
        // want the two to agree.
        if (section) context.setSectionCollapsed?.(section, effect.type);
      } else if (effect.type === "reset_variable") {
        const target = String(config.variable ?? "");
        if (target) {
          // A pending write to the same variable is discarded rather than
          // left to race: this Reset came after it, and p.80's ordering says
          // the later instruction stands.
          delete written[target];
          toReset.add(target);
        }
      } else if (effect.type === "switch_tab") {
        const section = String(config.section ?? "");
        const tab = String(config.tab ?? "");
        // **And here is p.84's difference, in the line the three above do not
        // have.** "Unlike the Switch to {page name}, and section collapse
        // state events, events that change the selected tab will also update
        // the value of the string variable configured for Variable-Based Tab
        // Selection." So this one *does* add to `written`, which is what
        // carries the write out to `setVariables` with everything else the
        // click wrote — one render for the whole click, in order.
        if (section && tab) {
          const wrote = context.setSectionTab?.(section, tab);
          if (wrote) written[wrote.variable] = tab;
        }
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

  // **Writes then deletions, and the bookkeeping above is what makes that
  // safe.** p.80 says effects run in configured order, so a Set after a Reset
  // of the same variable must win and a Reset after a Set must win. Each
  // branch removes the variable from the other's pile as it goes, so by the
  // time we get here the two are disjoint and the order of these two calls
  // cannot matter.
  if (Object.keys(written).length > 0) context.setVariables(written);
  if (toReset.size > 0) context.resetVariables?.([...toReset]);
  return written;
}
