/** Building the current file (§385; `code-repositories` p.13-14). */
import { describe, expect, it } from "vitest";
import type { Model, ModelRun } from "./types";
import {
  buildIsAProblem,
  buildLabel,
  buildVerdict,
  isSettled,
  latestRun,
  modelForFile,
  shouldPoll,
  whyNoBuild,
} from "./build-runs";

const input = () => ({
  dataset_id: "d0",
  input_alias: "src",
  dataset_name: "Source",
}) as Model["inputs"][number];

const model = (patch: Partial<Model> = {}): Model => ({
  id: "m1",
  project_id: "p1",
  name: "Daily",
  description: "",
  language: "python",
  code: "",
  output_dataset_id: "d1",
  trigger_mode: "manual",
  cron_schedule: null,
  next_run_at: null,
  upstream_watermark: null,
  input_health_policy: "ignore",
  last_run_status: null,
  last_run_at: null,
  source_repo_id: "r1",
  source_path: "transforms/daily.py",
  inputs: [input()],
  ...patch,
} as Model);

const run = (patch: Partial<ModelRun> = {}): ModelRun => ({
  id: "run1",
  status: "succeeded",
  trigger_kind: "manual",
  queued_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:01Z",
  finished_at: "2026-01-01T00:00:03Z",
  rows_produced: 12,
  error_message: null,
  output_version: "4",
  input_health: null,
  model_version: "2",
  has_log: false,
  ...patch,
});

describe("which model a file publishes to", () => {
  it("finds the model published from this path", () => {
    expect(modelForFile([model()], "r1", "transforms/daily.py")?.id).toBe("m1");
  });

  it("does not match the same path in another repository", () => {
    // **The case the pair exists for.** `source_path` is repository-relative,
    // so two repositories in one project can both hold `transforms/daily.py`;
    // matching on the path alone builds the wrong one, and the screen looks
    // right while it happens.
    expect(modelForFile([model()], "r2", "transforms/daily.py")).toBeUndefined();
  });

  it("does not match a model authored directly rather than in a repository", () => {
    // db 0038: both columns are NULL together for every model authored the
    // way models always were. A file with no path must not collect them.
    expect(
      modelForFile([model({ source_repo_id: null, source_path: null })], "r1", "transforms/daily.py"),
    ).toBeUndefined();
  });

  it("has no answer when no file is open", () => {
    expect(modelForFile([model()], "r1", undefined)).toBeUndefined();
  });

  it("has no answer before the listing has arrived", () => {
    // Not the same as "this file publishes to nothing": one is a fact and the
    // other is a read in flight, and the panel says different things about
    // them.
    expect(modelForFile(undefined, "r1", "transforms/daily.py")).toBeUndefined();
  });
});

describe("why a file cannot be built", () => {
  it("says nothing when it can", () => {
    expect(whyNoBuild(model({ inputs: [input()] }), { isSourceFile: true })).toBe("");
  });

  it("names the refusal the server would give before the button earns it", () => {
    // §214: `run_model` rejects a model with no inputs, so a Build button on
    // one is a control that looks like it works. The listing carries `inputs`,
    // so this is knowable before the click rather than after it.
    const said = whyNoBuild(model({ inputs: [] }), { isSourceFile: true });
    expect(said).toContain("no input datasets");
    // Named, because a project has more than one transform and "it" is not an
    // answer when the panel is one of four open at once.
    expect(said).toContain("Daily");
  });

  it("tells an unpublished transform apart from a file that is not one", () => {
    // **p.13's rule said rather than performed.** Foundry triggers no build
    // and explains nothing; these two send a reader to different places, and
    // "does not generate any datasets" covers both without distinguishing.
    const unpublished = whyNoBuild(undefined, { isSourceFile: true });
    const notATransform = whyNoBuild(undefined, { isSourceFile: false });
    expect(unpublished).toContain("not been published");
    expect(notATransform).toContain("only a transform file");
    expect(unpublished).not.toBe(notATransform);
  });
});

describe("whether the panel keeps asking", () => {
  it("asks while a run is queued or running", () => {
    expect(shouldPoll(run({ status: "queued" }))).toBe(true);
    expect(shouldPoll(run({ status: "running" }))).toBe(true);
  });

  it("stops once the run has settled, whichever way", () => {
    for (const status of ["succeeded", "failed", "cancelled"] as const) {
      expect(shouldPoll(run({ status }))).toBe(false);
      expect(isSettled(run({ status }))).toBe(true);
    }
  });

  it("does not ask when there is no run at all", () => {
    // A model nobody has built has nothing to poll for, and a panel that
    // polled forever over `undefined` is the bug this rule is named to stop.
    expect(shouldPoll(undefined)).toBe(false);
  });
});

describe("which run the panel is about", () => {
  it("takes the newest by when it was queued, not by position", () => {
    // §298: the history endpoint's order is its own decision, and a rule that
    // leaned on it could not be caught by a test that shares the assumption.
    const older = run({ id: "old", queued_at: "2026-01-01T00:00:00Z" });
    const newer = run({ id: "new", queued_at: "2026-01-02T00:00:00Z" });
    expect(latestRun([older, newer])?.id).toBe("new");
    expect(latestRun([newer, older])?.id).toBe("new");
  });

  it("has no answer for a model that has never been built", () => {
    expect(latestRun([])).toBeUndefined();
    expect(latestRun(undefined)).toBeUndefined();
  });
});

describe("what the panel says", () => {
  it("offers a first build and a repeat differently", () => {
    expect(buildLabel(undefined)).toBe("Build");
    expect(buildLabel(run({ status: "succeeded" }))).toBe("Build again");
  });

  it("says what it is doing while it is doing it", () => {
    expect(buildLabel(run({ status: "queued" }))).toBe("Queued…");
    expect(buildLabel(run({ status: "running" }))).toBe("Building…");
  });

  it("distinguishes a model never built from one whose panel has not loaded", () => {
    expect(buildVerdict(undefined)).toBe("never built");
  });

  it("carries the server's reason for a failure rather than restating it", () => {
    // The refusals worth reading are the server's — "add at least one input
    // dataset before running" names the fix. A panel that replaced them with
    // "failed" would be hiding the only useful half.
    expect(buildVerdict(run({ status: "failed", error_message: "no inputs" })))
      .toBe("failed: no inputs");
    expect(buildVerdict(run({ status: "failed", error_message: null }))).toBe("failed");
  });

  it("reports what a successful build produced", () => {
    expect(buildVerdict(run({ rows_produced: 1234 }))).toBe("built 1,234 rows");
    expect(buildVerdict(run({ rows_produced: null }))).toBe("built");
  });

  it("counts a failure and a cancellation as worth noticing, and a success as not", () => {
    expect(buildIsAProblem(run({ status: "failed" }))).toBe(true);
    expect(buildIsAProblem(run({ status: "cancelled" }))).toBe(true);
    expect(buildIsAProblem(run({ status: "succeeded" }))).toBe(false);
    expect(buildIsAProblem(undefined)).toBe(false);
  });
});
