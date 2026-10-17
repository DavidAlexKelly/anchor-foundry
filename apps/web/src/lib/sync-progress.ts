/** Following a sync that outlasted its request (§967).
 *
 * A sync the API could not finish while an answer would still reach the
 * browser answers 202 with the run it carries on under, instead of the 504 a
 * proxy gave up with while it went on and finished. The dialog then reads the
 * connection's run history until that run has ended, and says what it did. */
import type { SyncResult, SyncRun } from "./types";

/** How often the history is read while a run is followed. */
export const FOLLOW_EVERY_MS = 2000;

/** The run `result` named, once the history has it. */
export function followedRun(
  result: SyncResult | undefined,
  runs: SyncRun[] | undefined,
): SyncRun | undefined {
  if (!result?.running) return undefined;
  return runs?.find((run) => run.id === result.run_id);
}

/** Whether the run is still going: true until the history says otherwise. */
export function stillRunning(result: SyncResult | undefined, runs: SyncRun[] | undefined): boolean {
  if (!result?.running) return false;
  const run = followedRun(result, runs);
  return !run || run.status === "running";
}

export const RUNNING_TEXT =
  "Still syncing - this one is taking a while. It carries on if you close this, " +
  "and the connection's sync history has it.";

/** What a run that has ended did, in the dialog's own words. */
export function endedText(run: SyncRun): { ok: boolean; text: string } {
  if (run.status === "succeeded") {
    const into = run.dataset_name ? ` into the dataset ${run.dataset_name}` : "";
    const rows = `${run.rows_synced.toLocaleString()} ${run.rows_synced === 1 ? "row" : "rows"}`;
    return { ok: true, text: `Synced ${rows}${into}.` };
  }
  return { ok: false, text: run.error || "The sync failed." };
}
