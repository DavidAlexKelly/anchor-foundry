/**
 * Scheduling from the lineage graph (§387; `data-lineage` p.10).
 *
 * > "The schedules helper allows you to **set and edit** build schedules for
 * >  selected resources on the graph." (p.10)
 *
 * One sentence, and the last of the three rows the README collects under
 * *work starts from the resource, never from a view of it*. Schedules already
 * exist — a model carries `trigger_mode='cron'` with a `cron_schedule`, and
 * the worker runs them (db 0024) — so what was missing is setting them over a
 * selection rather than one model at a time.
 *
 * **Which models a selection means is `buildPlan`'s question, already
 * answered** (§386, §292). This module owns only what is different: what the
 * selection's *current* schedules amount to, and what changing them would do.
 *
 * **p.10's other half has nowhere to go here**, and that is worth saying
 * rather than leaving unremarked: "the schedules apply to the branches
 * (including fallback branches) configured in the graph". This platform's
 * pipeline graph has no notion of a branch, so there is no branch for a
 * schedule to apply to.
 *
 * **Every model in the selection can be scheduled**, including one authored
 * in a repository. That looks wrong and is not: `services/models.py` refuses
 * a direct edit to a repository-authored model's *code or inputs* only, and
 * says why — "trigger mode, schedule and health policy are how and when it
 * runs... Gating them would make a project that requires review unable to
 * pause a job." The review gate draws the same line. So nothing here filters
 * on where a model is authored.
 */
import type { PlannedModel } from "./graph-builds";

/** How many of these models already run on a schedule. */
export function alreadyScheduled(models: readonly PlannedModel[]): PlannedModel[] {
  return models.filter((m) => m.trigger_mode === "cron");
}

/**
 * What setting a schedule over this selection would do.
 *
 * **Overwriting is the behaviour, and saying so is the point.** p.10 says
 * "set and edit", so a selection holding models that already have a schedule
 * is the ordinary case rather than an error — but replacing three schedules
 * while the reader believes they are setting one is exactly §214's control
 * that looks like it works. The count goes on the screen before the click.
 */
export function scheduleSummary(models: readonly PlannedModel[]): string {
  if (models.length === 0) return "select a dataset or a transform to schedule";
  const existing = alreadyScheduled(models);
  const what = `${models.length} transform${models.length === 1 ? "" : "s"}`;
  if (existing.length === 0) return `schedule ${what}`;
  // Named while there are few enough to name: with two or three, which ones
  // are being replaced is the question a reader actually has.
  const named = existing.length <= 3
    ? ` (${existing.map((m) => m.name).join(", ")})`
    : "";
  return `schedule ${what}, replacing ${existing.length} existing${named}`;
}

/**
 * What clearing would do, or `""` when there is nothing to clear.
 *
 * p.10's "set and edit" includes turning one off, and a model with no
 * schedule has nothing to turn off — so the control says which it is rather
 * than being offered over a selection it would not change.
 */
export function clearSummary(models: readonly PlannedModel[]): string {
  const existing = alreadyScheduled(models);
  if (existing.length === 0) return "";
  return `clear ${existing.length} schedule${existing.length === 1 ? "" : "s"}`;
}

/**
 * Whether this looks like a five-field cron expression.
 *
 * **A shape check, not a validator**, and the distinction is deliberate:
 * `lib/cron.py` parses the expression with `croniter` and refuses it by name,
 * which is the authority. A second validator here would be a second opinion
 * that disagrees the first time one of them changes (§191). What this stops
 * is a request that was never going to be a cron expression — an empty box,
 * or four fields — so the button can be unusable instead of earning a refusal
 * for something the reader can see is unfinished.
 *
 * **Five fields, and nothing about their contents.** The first draft also
 * required every field to be non-empty, and a sweep could not make that fail:
 * splitting a *trimmed* string on runs of whitespace never yields an empty
 * field, so the only input that produces one is the empty string — which has
 * one field, not five, and is already refused. Deleted rather than covered by
 * a test that would have passed either way (§213). An empty box is still
 * refused, by the count.
 */
export function looksLikeCron(expression: string): boolean {
  return expression.trim().split(/\s+/).length === 5;
}
