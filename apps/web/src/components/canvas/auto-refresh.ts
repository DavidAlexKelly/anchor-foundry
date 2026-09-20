/**
 * Auto-refresh (`foundry_workshop` p.576-580).
 *
 * > "With auto-refresh, you can register object sets within a module to be
 * > watched for updates from anywhere in Foundry. When an update occurs, all
 * > data in the current module will automatically refresh without user
 * > interaction." (p.576)
 *
 * **The refreshing half already existed.** `invalidateCanvasReads` is "all
 * data in the current module" said in one call, and it has been what a write
 * inside a module triggers since it was written. What §408 adds is the
 * *watching*: a registered set, a watermark from the server, and the
 * comparison that turns a changed watermark into that same refresh.
 *
 * ---
 *
 * **Registration names variables, not sets.** p.576 says "register object sets
 * within a module", and in this platform an object set that a module can name
 * *is* a variable — that is what §151's `object_set` kind is. Storing the
 * variable id rather than a resolved definition also means a set that is
 * narrowed at runtime keeps being watched as the same registration.
 *
 * **What is watched is the object type behind it**, which is p.579's own
 * boundary: *"Auto-refresh does not automatically watch for updates of linked
 * object types"*. A set is a filtered view of a type and any write to the type
 * can move a row into or out of it, so the type is both the correct unit and
 * the smallest one that does not need the filter re-evaluated every poll.
 *
 * ---
 *
 * **Divergences, stated rather than silently skipped.**
 *
 * * p.578's **OSv1/OSv2** limitation has no analogue here — there is one
 *   instance store behind an interface with two implementations, and neither
 *   is a Foundry storage generation. Nothing to port.
 * * p.579's **unsupported filter types** (`terms`, `phrase`, `multiMatch`,
 *   `prefixOnLastToken`, `objectSetLink`) are Foundry's filter vocabulary, not
 *   this platform's. Watching by *type* rather than by set makes the question
 *   moot here: no filter is evaluated to decide whether to refresh, which is
 *   also exactly the workaround p.579 recommends — "watch an unfiltered object
 *   set of the same type".
 * * p.579's **"must be used within a visible widget"** is not reproduced. Here
 *   a registered variable is watched whether or not a widget reads it, because
 *   the registration is explicit: somebody named this set in the settings
 *   panel, and quietly not watching it because no widget happens to bind it
 *   would be a setting that sometimes works. The *tab* half of the same rule
 *   is kept, and for the reason p.579 gives — a background tab refreshes
 *   nothing and catches up when it returns.
 * * p.580's **no inheritance when embedded** falls out of where the setting
 *   lives: it is on the module document, and an embedded module renders its
 *   own document. Nothing carries it across, which is what p.580 asks for.
 */

import type { WorkshopVariable } from "@/lib/types";

/** p.577: "The current minimum, or most frequent, refresh rate is 10 seconds,
 * which ensures stability of services due to the increased load from
 * auto-refreshing." Foundry's own number, kept as Foundry's. */
export const MIN_SECONDS = 10;

/** What an unconfigured module polls at once it is switched on. Foundry does
 * not name a default, so this is the floor rather than a guess at one: the
 * setting exists to slow polling down, and a builder who has not chosen wants
 * the behaviour the feature advertises. */
export const DEFAULT_SECONDS = MIN_SECONDS;

export interface AutoRefresh {
  enabled: boolean;
  /** p.577's "Minimum seconds between refresh". */
  seconds: number;
  /** p.578's "Disable in edit mode" — "Auto-refresh will remain configured and
   * active in view mode with this setting enabled." */
  disable_in_edit: boolean;
  /** The `object_set` variable ids this module registered (p.576). */
  variables: string[];
}

export const OFF: AutoRefresh = {
  enabled: false,
  seconds: DEFAULT_SECONDS,
  disable_in_edit: true,
  variables: [],
};

/**
 * One stored setting, read defensively (§212).
 *
 * **A refusal is `OFF`, not a throw.** Every other reader in this family drops
 * what it cannot use; here the thing being dropped polls a server on a timer,
 * so the safe direction is unambiguous — a module with a malformed setting
 * renders and does not poll, rather than polling on a schedule nobody chose.
 */
export function settingsOf(raw: unknown): AutoRefresh {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return OFF;
  const it = raw as Record<string, unknown>;
  const seconds = typeof it.seconds === "number" && Number.isFinite(it.seconds)
    ? Math.max(MIN_SECONDS, Math.floor(it.seconds))
    : DEFAULT_SECONDS;
  const variables = Array.isArray(it.variables)
    ? it.variables.filter((v): v is string => typeof v === "string" && v !== "")
    : [];
  return {
    enabled: it.enabled === true,
    seconds,
    // **Absent means on**, which is p.578's own default reading: the setting is
    // offered as a thing a builder switches *off*, and a document that predates
    // it should not start refreshing somebody's canvas while they build.
    disable_in_edit: it.disable_in_edit !== false,
    variables,
  };
}

/** Whether the module should be polling at all, in this mode (p.578). */
export function running(settings: AutoRefresh, mode: string): boolean {
  if (!settings.enabled) return false;
  if (settings.variables.length === 0) return false;
  if (mode !== "run" && settings.disable_in_edit) return false;
  return true;
}

/** p.577's floor, applied to whatever the document holds. */
export function intervalMs(settings: AutoRefresh): number {
  return Math.max(MIN_SECONDS, settings.seconds) * 1000;
}

/**
 * The object types behind the registered variables.
 *
 * `resolved` is the variable resolver's output — a set definition per
 * variable id. A registration whose variable has gone, or which resolves to
 * nothing yet, contributes nothing: an unresolved set is not an empty one,
 * and polling for a type nobody named would be watching at random.
 *
 * Deduplicated, because two registered sets over one type are one thing to
 * watch, and ordered, so the poll key is stable across renders.
 */
export function watchedTypes(
  settings: AutoRefresh,
  resolved: Record<string, unknown>,
): string[] {
  const out = new Set<string>();
  for (const id of settings.variables) {
    const definition = resolved[id] as { object_type_id?: unknown } | undefined;
    const typeId = definition?.object_type_id;
    if (typeof typeId === "string" && typeId !== "") out.add(typeId);
  }
  return [...out].sort();
}

/** One type's watermark, as the freshness route returns it. */
export interface Watermark {
  object_type_id: string;
  updated_at: string | null;
  count: number;
}

/** The watermarks as one comparable string, keyed by type.
 *
 * A string rather than the array, because the array's *order* is the server's
 * and comparing two of them would report a change every time the server
 * happened to answer in a different order.
 */
export function stamp(marks: readonly Watermark[] | undefined): string | null {
  if (!marks) return null;
  return [...marks]
    .map((m) => `${m.object_type_id}:${m.updated_at ?? ""}:${m.count}`)
    .sort()
    .join("|");
}

/**
 * Whether this poll saw a change worth refreshing for.
 *
 * **The first answer is never a change.** There was nothing to compare it to,
 * and treating it as one would refresh every module once on open — the
 * unresolved state read as the changed one, which is §210's rule.
 *
 * A *count-only* change is a change, and it is the case the timestamp cannot
 * see: a delete lowers the newest `updated_at` rather than raising it.
 */
export function changed(before: string | null, after: string | null): boolean {
  if (before === null || after === null) return false;
  return before !== after;
}

/**
 * Whether a refresh should be applied now, or held.
 *
 * p.579: *"If an auto-refresh notification occurs while a variable is hidden,
 * it will be delayed until the variable becomes visible again, at which point
 * a reload will immediately be triggered. This behavior also applies if the
 * browser tab is minimized, or is not the currently active tab."*
 *
 * So a change seen while the tab is in the background is **remembered, not
 * dropped** — which is the difference between catching up and silently missing
 * an update. The caller holds the pending flag; this says what to do with it.
 */
export function applyNow(visible: boolean): boolean {
  return visible;
}

/** The object-set variables a module can register (p.576). */
export function registrable(
  declared: Record<string, WorkshopVariable>,
): WorkshopVariable[] {
  return Object.values(declared).filter((v) => v.kind === "object_set");
}
