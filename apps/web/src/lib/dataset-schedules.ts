/** The schedules that will update a dataset (§508; `dataset-preview` p.3).
 *
 * > "Schedules: Information about any configured build schedules that will
 * > run to update the dataset." (p.3)
 *
 * What is scheduled is the API's (`services/dataset_schedules.py`); this is
 * how the Details tab says it.
 */

export type DatasetSchedule = {
  kind: "transform" | "sync";
  name: string;
  resource_id: string;
  /** `cron`, or `upstream` for a transform that runs when an input updates. */
  trigger: string;
  cron: string | null;
  /** Null with a cron set means never fired yet, which the worker runs now. */
  next_run_at: string | null;
  watches: string[];
  /** A sync's mode; null for a transform. */
  mode: string | null;
};

/** Said when nothing will run on its own. The three things that do change
 * it are named, so the empty state still answers "then how does it change". */
export const NO_SCHEDULES =
  "Nothing is scheduled to update this dataset. It changes when somebody runs, syncs or uploads it.";

/** What is scheduled: "Transform Nightly", "Sync Warehouse (incremental)". */
export function scheduleName(schedule: DatasetSchedule): string {
  const label = schedule.kind === "transform" ? "Transform" : "Sync";
  const mode = schedule.mode ? ` (${schedule.mode})` : "";
  return `${label} ${schedule.name}${mode}`;
}

/** When it runs. A cron says its expression and the next run; an upstream
 * trigger says what it waits on, since that *is* its schedule. */
export function scheduleWhen(schedule: DatasetSchedule): string {
  if (schedule.trigger === "upstream") {
    return schedule.watches.length === 0
      ? "runs when an input updates"
      : `runs when ${orList(schedule.watches)} updates`;
  }
  const next = schedule.next_run_at
    ? `next run ${new Date(schedule.next_run_at).toLocaleString()}`
    : "due now: it has not run on this schedule yet";
  return `on cron ${schedule.cron} · ${next}`;
}

/** "A", "A or B", "A, B or C". */
function orList(names: string[]): string {
  if (names.length === 1) return names[0] as string;
  return `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
}
