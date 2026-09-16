/** Reading a model run (§358; `dataset-preview` p.3). */
import { describe, expect, it } from "vitest";
import { durationText } from "./action-metrics";
import { runDuration, whyNoLog } from "./run-logs";

const at = (iso: string) => iso;

describe("how long a run took", () => {
  it("counts from when it started, not when it was queued", () => {
    // **The distinction the number exists for.** A run that waited a minute
    // for the worker and ran for a second is a fast transform on a busy
    // worker, which is a different problem from a slow transform.
    expect(runDuration({
      started_at: at("2026-01-01T00:00:10Z"),
      finished_at: at("2026-01-01T00:00:12Z"),
    })).toBe("2.0s");
  });

  it("reads sub-second runs in milliseconds", () => {
    expect(runDuration({
      started_at: at("2026-01-01T00:00:00.000Z"),
      finished_at: at("2026-01-01T00:00:00.250Z"),
    })).toBe("250ms");
  });

  it("reads long runs in minutes and seconds", () => {
    expect(runDuration({
      started_at: at("2026-01-01T00:00:00Z"),
      finished_at: at("2026-01-01T00:02:30Z"),
    })).toBe("2m 30s");
  });

  it("drops the seconds when there are none", () => {
    // "2m", not "2m 0s". The seconds exist to save the reader arithmetic and
    // there is none to do at zero — and this is the case the two formatters
    // disagreed on before §358 made them one.
    expect(runDuration({
      started_at: at("2026-01-01T00:00:00Z"),
      finished_at: at("2026-01-01T00:02:00Z"),
    })).toBe("2m");
  });

  it("says nothing about a run that has not finished", () => {
    // The negative control: a duration that always produced a number would
    // put "0ms" against a run that is still going.
    expect(runDuration({ started_at: at("2026-01-01T00:00:00Z"), finished_at: null })).toBe("");
    expect(runDuration({ started_at: null, finished_at: null })).toBe("");
  });

  it("says nothing about a run that finished without ever starting", () => {
    // **Both guards, not one.** A run refused before the worker picked it up
    // has a finish and no start, and a build checking only `finished_at`
    // measures from the epoch — which reads as a run that took fifty-six
    // years rather than one that never began.
    expect(runDuration({ started_at: null, finished_at: at("2026-01-01T00:00:02Z") }))
      .toBe("");
  });

  it("says nothing rather than something impossible", () => {
    // Clocks move. A finish before a start is not a negative duration, it is
    // an unanswerable question, and "-3.0s" against a run would read as a bug
    // in the run rather than in the clock.
    expect(runDuration({
      started_at: at("2026-01-01T00:00:10Z"),
      finished_at: at("2026-01-01T00:00:07Z"),
    })).toBe("");
    expect(runDuration({ started_at: at("nonsense"), finished_at: at("also nonsense") })).toBe("");
  });
});

describe("why there is no log", () => {
  it("says nothing when there is one", () => {
    expect(whyNoLog({ status: "succeeded", has_log: true }, "python")).toBe("");
  });

  it("distinguishes a run that has not finished", () => {
    expect(whyNoLog({ status: "queued", has_log: false }, "python"))
      .toBe("this run has not finished yet");
    expect(whyNoLog({ status: "running", has_log: false }, "python"))
      .toBe("this run has not finished yet");
  });

  it("distinguishes a SQL model, which can never have one", () => {
    // **Not the same answer as "printed nothing".** One says come back after
    // adding a print; the other says there is nowhere to put one.
    expect(whyNoLog({ status: "succeeded", has_log: false }, "sql"))
      .toBe("SQL transforms have no output to capture — this is a query, not a program");
  });

  it("distinguishes a Python run that printed nothing", () => {
    expect(whyNoLog({ status: "succeeded", has_log: false }, "python"))
      .toBe("this run printed nothing");
    expect(whyNoLog({ status: "failed", has_log: false }, "python"))
      .toBe("this run printed nothing");
  });

  it("gives four different answers, which is the whole point", () => {
    // A single "no logs" would satisfy every assertion above if they were
    // written loosely, and would make a SQL model look like a Python one
    // somebody forgot to instrument.
    const answers = new Set([
      whyNoLog({ status: "succeeded", has_log: true }, "python"),
      whyNoLog({ status: "running", has_log: false }, "python"),
      whyNoLog({ status: "succeeded", has_log: false }, "sql"),
      whyNoLog({ status: "succeeded", has_log: false }, "python"),
    ]);
    expect(answers.size).toBe(4);
  });

  it("a finished SQL run is SQL's answer, not the queued one", () => {
    // Ordering inside the function: the not-finished check comes first, so a
    // *running* SQL model reports that rather than its language. Asserted so
    // the order is a decision rather than an accident.
    expect(whyNoLog({ status: "running", has_log: false }, "sql"))
      .toBe("this run has not finished yet");
  });
});


describe("one duration formatter, not two (§298's shape)", () => {
  it("agrees with the action metrics for every elapsed time", () => {
    // **The check that would have caught it.** `action-metrics.durationText`
    // was written for p.164's P95 and §358 wrote a second formatter for a
    // model run; they agreed everywhere except whole minutes, where one said
    // "2m" and the other "2m 0s" — so which spelling a reader saw depended on
    // which page they were on. They are one function now, and this is the
    // comparison kept rather than the conclusion written down.
    const start = "2026-01-01T00:00:00.000Z";
    for (const seconds of [0, 0.25, 0.999, 1, 2, 59.9, 60, 90, 120, 121, 599, 3600]) {
      const finished = new Date(Date.parse(start) + seconds * 1000).toISOString();
      expect(runDuration({ started_at: start, finished_at: finished }))
        .toBe(durationText(seconds));
    }
  });
});
