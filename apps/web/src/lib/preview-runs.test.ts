import { describe, expect, it } from "vitest";
import type { CodePreviewRun, TransformPreview } from "./types";
import {
  previewLabel,
  queuedRunId,
  rowCountLabel,
  runIsAProblem,
  runStatus,
  samplingWarning,
  shouldPoll,
  shown,
} from "./preview-runs";

function sqlResult(over: Partial<TransformPreview> = {}): TransformPreview {
  return {
    output: "daily_orders",
    columns: [{ name: "id", data_type: "BIGINT" }],
    rows: [["1"], ["2"]],
    row_count: 2,
    truncated: false,
    sampled: false,
    inputs: [
      {
        alias: "orders",
        dataset: "orders_raw",
        dataset_id: "d1",
        rows_available: 2,
        rows_used: 2,
        sampled: false,
      },
    ],
    schema_changes: null,
    writes_to_existing_dataset: false,
    ...over,
  };
}

function run(over: Partial<CodePreviewRun> = {}): CodePreviewRun {
  return {
    id: "r1",
    repo_id: "repo",
    branch: "main",
    path: "build.py",
    status: "succeeded",
    columns: [{ name: "id", data_type: "BIGINT" }],
    rows: [["1"]],
    row_count: 1,
    truncated: false,
    sampled: false,
    failure: null,
    inputs: [{ alias: "orders", rows_available: 5, rows_used: 5, sampled: false }],
    error: null,
    queued_at: "2026-01-01T00:00:00Z",
    started_at: "2026-01-01T00:00:01Z",
    finished_at: "2026-01-01T00:00:02Z",
    ...over,
  };
}

describe("which machinery answered", () => {
  it("reads the queued run off a Python press", () => {
    expect(queuedRunId(sqlResult({ run_id: "abc", status: "queued" }))).toBe("abc");
  });

  it("finds none on a SQL press, which answered outright", () => {
    expect(queuedRunId(sqlResult())).toBeNull();
    expect(queuedRunId(null)).toBeNull();
  });
});

describe("one shape, two sources", () => {
  it("flattens a SQL result", () => {
    const view = shown(sqlResult(), undefined);
    expect(view?.output).toBe("daily_orders");
    expect(view?.rowCount).toBe(2);
    expect(view?.inputs).toEqual([
      { alias: "orders", label: "orders = orders_raw", sampled: false },
    ]);
  });

  it("flattens a settled run into the same shape", () => {
    const view = shown(null, run());
    expect(view?.columns).toEqual([{ name: "id", data_type: "BIGINT" }]);
    expect(view?.rows).toEqual([["1"]]);
    expect(view?.rowCount).toBe(1);
  });

  it("names the dataset for SQL and only the alias for a run", () => {
    // The run does not know the dataset's name - the API resolved names to ids
    // before queueing. Inventing one would be a label that goes stale silently.
    const sampled = shown(null, run({
      sampled: true,
      inputs: [{ alias: "orders", rows_available: 1500, rows_used: 1000, sampled: true }],
    }));
    expect(sampled!.inputs[0]?.label).toBe("orders (1,000 of 1,500)");

    const sql = shown(
      sqlResult({
        sampled: true,
        inputs: [
          {
            alias: "orders",
            dataset: "orders_raw",
            dataset_id: "d1",
            rows_available: 1500,
            rows_used: 1000,
            sampled: true,
          },
        ],
      }),
      undefined,
    );
    expect(sql!.inputs[0]?.label).toBe("orders = orders_raw (1,000 of 1,500)");
  });

  it("shows nothing for a run that has not finished", () => {
    // A table of no rows over a running job reads as "it produced nothing",
    // which is the one answer nobody has yet.
    expect(shown(null, run({ status: "queued", rows: [], row_count: 0 }))).toBeNull();
    expect(shown(null, run({ status: "running", rows: [], row_count: 0 }))).toBeNull();
  });

  it("shows nothing for a run that failed, however many rows it carries", () => {
    expect(shown(null, run({ status: "failed", failure: "boom" }))).toBeNull();
    expect(shown(null, run({ status: "errored", error: "gone" }))).toBeNull();
  });

  it("shows nothing for the receipt a Python press comes back with", () => {
    // Between the press and the first poll there is a TransformPreview with a
    // run_id and no rows. Drawing it would flash an empty table.
    expect(shown(sqlResult({ run_id: "abc", status: "queued", rows: [], row_count: 0 }), undefined))
      .toBeNull();
  });

  it("prefers the run over the result once there is one", () => {
    const view = shown(sqlResult({ run_id: "abc" }), run({ rows: [["9"]] }));
    expect(view?.rows).toEqual([["9"]]);
  });
});

describe("what the status line says", () => {
  it("says nothing when there is no run", () => {
    expect(runStatus(undefined)).toBeNull();
  });

  it("distinguishes waiting from running", () => {
    expect(runStatus(run({ status: "queued" }))).toBe("Waiting to run…");
    expect(runStatus(run({ status: "running" }))).toBe("Running…");
  });

  it("keeps the transform raising apart from the run not happening", () => {
    // db 0092's distinction, and the reason it is worth keeping: one sends you
    // to your code, the other does not.
    expect(runStatus(run({ status: "failed", failure: "KeyError: 'region'" })))
      .toBe("KeyError: 'region'");
    expect(runStatus(run({ status: "errored", error: "the datasets are no longer here" })))
      .toBe("the datasets are no longer here");
  });

  it("still says something when a failure arrived without a message", () => {
    expect(runStatus(run({ status: "failed", failure: null })))
      .toBe("This transform raised while previewing.");
    expect(runStatus(run({ status: "errored", error: null })))
      .toBe("This preview could not be run.");
  });

  it("says nothing about a run that succeeded, because the table does", () => {
    expect(runStatus(run())).toBeNull();
  });

  it("colours both kinds of bad news and nothing else", () => {
    expect(runIsAProblem(run({ status: "failed" }))).toBe(true);
    expect(runIsAProblem(run({ status: "errored" }))).toBe(true);
    expect(runIsAProblem(run({ status: "running" }))).toBe(false);
    expect(runIsAProblem(run())).toBe(false);
    expect(runIsAProblem(undefined)).toBe(false);
  });
});

describe("the sampling warning", () => {
  it("is silent when nothing was cut", () => {
    expect(samplingWarning(shown(sqlResult(), undefined))).toBeNull();
    expect(samplingWarning(null)).toBeNull();
  });

  it("names the inputs that were cut, and only those", () => {
    const view = shown(null, run({
      sampled: true,
      inputs: [
        { alias: "orders", rows_available: 1500, rows_used: 1000, sampled: true },
        { alias: "regions", rows_available: 2, rows_used: 2, sampled: false },
      ],
    }));
    const warning = samplingWarning(view);
    expect(warning).toContain("orders");
    expect(warning).not.toContain("regions");
    expect(warning).toContain("not the answer");
  });

  it("is the same sentence for both languages", () => {
    // §292: the SQL path used to carry its own copy inline. Two sentences that
    // mean the same thing drift the first time one is edited.
    const fromRun = samplingWarning(shown(null, run({
      sampled: true,
      inputs: [{ alias: "orders", rows_available: 9, rows_used: 4, sampled: true }],
    })));
    const fromSql = samplingWarning(shown(
      sqlResult({
        sampled: true,
        inputs: [
          {
            alias: "orders",
            dataset: "orders_raw",
            dataset_id: "d1",
            rows_available: 9,
            rows_used: 4,
            sampled: true,
          },
        ],
      }),
      undefined,
    ));
    expect(fromRun).toBe(fromSql);
  });
});

describe("the row count line", () => {
  it("says the plain number when nothing is hidden", () => {
    expect(rowCountLabel(shown(sqlResult(), undefined)!)).toBe("2 rows");
  });

  it("does not pluralise one row", () => {
    expect(rowCountLabel(shown(null, run())!)).toBe("1 row");
  });

  it("says how much of it is on screen when the table is cut", () => {
    const view = shown(null, run({ row_count: 40000, truncated: true, rows: [["1"], ["2"]] }))!;
    expect(rowCountLabel(view)).toBe("40,000 rows, showing 2");
  });

  it("says the count came from a sample, which is a different claim", () => {
    // Truncation is about this table; sampling is about whether the total is
    // real. A label carrying only one of them is wrong half the time.
    const view = shown(null, run({
      row_count: 40000,
      truncated: true,
      sampled: true,
      rows: [["1"]],
      inputs: [{ alias: "orders", rows_available: 1500, rows_used: 1000, sampled: true }],
    }))!;
    expect(rowCountLabel(view)).toBe("40,000 rows from the sample, showing 1");
  });
});

describe("the button", () => {
  it("reports progress while the request is in flight", () => {
    expect(previewLabel(true, undefined)).toBe("Running…");
  });

  it("keeps reporting it while the queued run is unsettled", () => {
    // The mutation settles the moment the run is queued. A button that went
    // back to "Preview" there invites a second press the server refuses.
    expect(previewLabel(false, run({ status: "queued" }))).toBe("Running…");
    expect(previewLabel(false, run({ status: "running" }))).toBe("Running…");
  });

  it("offers the press again once there is an answer", () => {
    expect(previewLabel(false, run())).toBe("Preview");
    expect(previewLabel(false, run({ status: "failed" }))).toBe("Preview");
    expect(previewLabel(false, undefined)).toBe("Preview");
  });
});

describe("polling", () => {
  it("stops on every settled status and on none of the others", () => {
    expect(shouldPoll(run({ status: "queued" }))).toBe(true);
    expect(shouldPoll(run({ status: "running" }))).toBe(true);
    expect(shouldPoll(run({ status: "succeeded" }))).toBe(false);
    expect(shouldPoll(run({ status: "failed" }))).toBe(false);
    expect(shouldPoll(run({ status: "errored" }))).toBe(false);
    expect(shouldPoll(undefined)).toBe(false);
  });
});
