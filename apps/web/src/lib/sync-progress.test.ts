import { describe, expect, it } from "vitest";
import { endedText, followedRun, stillRunning } from "./sync-progress";
import type { SyncResult, SyncRun } from "./types";

const running: SyncResult = {
  run_id: "r2", ok: null, running: true, error: null, rows_synced: 0,
  created_dataset: false, dataset: null,
};
const answered: SyncResult = { ...running, ok: true, running: false };

function run(id: string, status: SyncRun["status"], extra: Partial<SyncRun> = {}): SyncRun {
  return {
    id, mode: "full", source_table: "public.orders", status, rows_synced: 0, error: null,
    started_at: "2026-10-16T10:00:00Z", finished_at: null, dataset_id: null,
    dataset_name: null, schema_changes: null, ...extra,
  };
}

describe("following a sync that outlasted its request (§967)", () => {
  it("follows only the run the answer named", () => {
    const runs = [run("r1", "succeeded"), run("r2", "running")];
    expect(followedRun(running, runs)?.id).toBe("r2");
    expect(followedRun(answered, runs)).toBeUndefined();
  });

  it("is running until the history says the run ended", () => {
    expect(stillRunning(running, undefined)).toBe(true);
    // Not yet in the history the dialog last read.
    expect(stillRunning(running, [run("r1", "succeeded")])).toBe(true);
    expect(stillRunning(running, [run("r2", "running")])).toBe(true);
    expect(stillRunning(running, [run("r2", "succeeded")])).toBe(false);
    expect(stillRunning(running, [run("r2", "failed")])).toBe(false);
    // An answer that was the outcome is followed no further.
    expect(stillRunning(answered, undefined)).toBe(false);
  });

  it("says what an ended run did", () => {
    expect(endedText(run("r2", "succeeded", { rows_synced: 12345, dataset_name: "Orders" })))
      .toEqual({ ok: true, text: "Synced 12,345 rows into the dataset Orders." });
    expect(endedText(run("r2", "succeeded", { rows_synced: 3 })))
      .toEqual({ ok: true, text: "Synced 3 rows." });
    expect(endedText(run("r2", "succeeded", { rows_synced: 1 })))
      .toEqual({ ok: true, text: "Synced 1 row." });
    expect(endedText(run("r2", "failed", { error: "relation does not exist" })))
      .toEqual({ ok: false, text: "relation does not exist" });
    expect(endedText(run("r2", "failed"))).toEqual({ ok: false, text: "The sync failed." });
  });
});
