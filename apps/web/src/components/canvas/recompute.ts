/** p.76's recompute behaviours, and what the browser has to hold for them.
 *
 * > "**Automatic**: The variable value is recomputed automatically when the
 * > value of any of the variables it depends on changes. This is the default
 * > option…
 * >
 * > **Only when triggered by an event**: The variable value is recomputed only
 * > when explicitly triggered by a recompute {variable name} event.
 * >
 * > **On module load, and when triggered by an event**: The variable value is
 * > recomputed when the module is initially loaded, and when explicitly
 * > triggered by a recompute {variable name} event." (p.76)
 *
 * **The server computes; the browser remembers.** Derived values are resolved
 * on the server (one implementation of the transforms, not two), and the
 * server has no memory between requests — every resolve is a fresh evaluation
 * of a document. So "do not recompute this time" can only come from the
 * caller: the browser keeps the value each held variable last computed and
 * sends it back, and the evaluator uses it *as the input to everything
 * downstream* rather than merely displaying it.
 *
 * That last point is the reason the held value goes to the server at all
 * rather than being frozen on screen. Freezing locally would leave a variable
 * showing one number while its dependants recomputed from a fresh copy of it —
 * two different answers to the same question on one page, which is exactly the
 * class of silent disagreement this repo keeps removing.
 *
 * The wire has **two** parts, not one. `held` is memory — what each holding
 * variable last computed. `recompute` is an ask — p.85's event, naming the ids
 * to compute fresh this time. They cannot be collapsed into one: for
 * `only_on_event`, "nothing remembered" is already the state at load, so an
 * event expressed as an absence would be indistinguishable from a fresh page
 * and would do nothing at all.
 *
 * This module is the bookkeeping: which variables hold, what to send, and what
 * to remember afterwards. It has no opinion about *values*, which is what
 * keeps it testable without a server.
 */
import type { WorkshopVariable } from "../../lib/types";

export type RecomputeBehaviour = "automatic" | "only_on_event" | "on_load_and_event";

/** A variable's behaviour, defaulting the way an absent field should.
 *
 * Absent is `automatic` because that is both p.76's default and what every
 * document written before this existed means — a stored `"automatic"` and a
 * missing field have to resolve to the same thing or upgrading the platform
 * would change what old modules do.
 */
export function behaviourOf(variable: WorkshopVariable | undefined): RecomputeBehaviour {
  const raw = variable?.recompute;
  return raw === "only_on_event" || raw === "on_load_and_event" ? raw : "automatic";
}

/** Whether this variable's value survives between resolves.
 *
 * Only a **derived** variable can: a static one holds what somebody typed, so
 * there is nothing to defer, and the server refuses the setting on one. Checked
 * here as well because a document can arrive from anywhere, and a static
 * variable wrongly marked would otherwise be sent as held and pinned forever.
 */
export function holds(variable: WorkshopVariable | undefined): boolean {
  return Boolean(variable?.derivation) && behaviourOf(variable) !== "automatic";
}

/** What to send as `held` on the next resolve.
 *
 * `remembered` is what the browser has captured so far. Entries for variables
 * that no longer hold — the author changed the behaviour, or deleted the
 * variable — are dropped rather than sent: the server ignores them, but
 * sending them would keep a stale value alive in the request forever and make
 * the wire hard to read while debugging.
 *
 * A variable with a recompute **pending** is left out too, so that what comes
 * back for it is the fresh value and `remember` captures it rather than
 * carrying the stale one.
 */
export function heldFor(
  declared: Record<string, WorkshopVariable>,
  remembered: Record<string, unknown>,
  pending: ReadonlySet<string> = new Set(),
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [vid, value] of Object.entries(remembered)) {
    if (holds(declared[vid]) && !pending.has(vid)) out[vid] = value;
  }
  return out;
}

/** What to remember after a resolve came back.
 *
 * Everything currently held stays as it was — the server echoed it, and
 * re-capturing an echo is a no-op with one hazard: a resolve that raced a
 * recompute would put the old value straight back. So a held variable's entry
 * is *carried*, never re-read.
 *
 * A holding variable that was **not** sent is one the server just computed —
 * a first load, or the resolve after a recompute event dropped it — and its
 * fresh value is what gets captured.
 *
 * **`only_on_event` is captured too, `null` and all.** p.76 says it is
 * recomputed "only when explicitly triggered", so before the first event it
 * genuinely has no value, and the server resolves it to null. Capturing that
 * null is what stops the next resolve computing it: without it the variable
 * would be treated as "never captured" forever and would flicker into life the
 * moment anything else changed.
 */
export function remember(
  declared: Record<string, WorkshopVariable>,
  remembered: Record<string, unknown>,
  sent: Record<string, unknown>,
  resolved: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [vid, variable] of Object.entries(declared)) {
    if (!holds(variable)) continue;
    if (vid in sent) out[vid] = remembered[vid];
    else if (vid in resolved) out[vid] = resolved[vid];
  }
  return out;
}

/** Add the variables a recompute event named to the pending set.
 *
 * **Why a pending set rather than forgetting the held value.** Dropping what is
 * remembered *looks* like it says "compute this next time", and for
 * `on_load_and_event` it accidentally does. For `only_on_event` it cannot: p.76
 * says that one has no value until an event fires, so "nothing remembered" is
 * already its state at load, and an event that produced the same request as a
 * fresh page would be inert. The ask has to be sent as an ask.
 *
 * A name that is not held is ignored rather than refused: the server already
 * refuses a `recompute` aimed at a static or Automatic variable at save time,
 * so one arriving here means the document changed underneath the event, and
 * skipping it is the same rule every other effect follows.
 *
 * Returns the same set when nothing is added — identity, because the bridge
 * uses the difference to decide whether a resolve is worth making.
 */
export function request(
  declared: Record<string, WorkshopVariable>,
  pending: ReadonlySet<string>,
  names: readonly string[],
): ReadonlySet<string> {
  const add = names.filter((vid) => holds(declared[vid]) && !pending.has(vid));
  if (add.length === 0) return pending;
  return new Set([...pending, ...add]);
}

/** What to send as `recompute` on the next resolve.
 *
 * Filtered against the document for the same reason `heldFor` is: a variable
 * can stop holding between the event and the request.
 */
export function requested(
  declared: Record<string, WorkshopVariable>,
  pending: ReadonlySet<string>,
): string[] {
  return [...pending].filter((vid) => holds(declared[vid]));
}

/** Drop the asks a resolve has now answered.
 *
 * `sent` rather than the whole set, deliberately: a recompute fired while the
 * request was in flight is not answered by it, and clearing the set wholesale
 * would swallow that event with no trace.
 *
 * Returns the same set when nothing is dropped, so a resolve that carried no
 * asks cannot make the bridge think something changed.
 */
export function settled(
  pending: ReadonlySet<string>,
  sent: readonly string[],
): ReadonlySet<string> {
  const drop = sent.filter((vid) => pending.has(vid));
  if (drop.length === 0) return pending;
  const next = new Set(pending);
  for (const vid of drop) next.delete(vid);
  return next;
}
