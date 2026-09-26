/** §508: the Details tab's Schedules (`dataset-preview` p.3). */
import { describe, expect, it } from "vitest";

import { NO_SCHEDULES, scheduleName, scheduleWhen, type DatasetSchedule } from "./dataset-schedules";

const cron: DatasetSchedule = {
  kind: "transform", name: "Nightly", resource_id: "r1", trigger: "cron",
  cron: "0 3 * * *", next_run_at: "2026-09-27T03:00:00Z", watches: [], mode: null,
};

describe("scheduleName", () => {
  it("names a transform, and a sync with its mode", () => {
    expect(scheduleName(cron)).toBe("Transform Nightly");
    expect(scheduleName({ ...cron, kind: "sync", name: "Warehouse", mode: "incremental" }))
      .toBe("Sync Warehouse (incremental)");
  });
});

describe("scheduleWhen", () => {
  it("says a cron's expression and its next run", () => {
    expect(scheduleWhen(cron)).toBe(
      `on cron 0 3 * * * · next run ${new Date("2026-09-27T03:00:00Z").toLocaleString()}`);
  });

  it("says a cron that has not fired yet is due now", () => {
    expect(scheduleWhen({ ...cron, next_run_at: null }))
      .toBe("on cron 0 3 * * * · due now: it has not run on this schedule yet");
  });

  it("says what an upstream trigger waits on", () => {
    const upstream = { ...cron, trigger: "upstream", cron: null, next_run_at: null };
    expect(scheduleWhen({ ...upstream, watches: ["Orders"] })).toBe("runs when Orders updates");
    expect(scheduleWhen({ ...upstream, watches: ["A", "B"] })).toBe("runs when A or B updates");
    expect(scheduleWhen({ ...upstream, watches: ["A", "B", "C"] }))
      .toBe("runs when A, B or C updates");
    expect(scheduleWhen({ ...upstream, watches: [] })).toBe("runs when an input updates");
  });

  it("says what changes a dataset nothing schedules", () => {
    expect(NO_SCHEDULES).toBe(
      "Nothing is scheduled to update this dataset. It changes when somebody runs, syncs or uploads it.");
  });
});
