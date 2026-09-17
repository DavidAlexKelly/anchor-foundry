/** What a proposal does to its datasets (§364; `code-repositories` p.53). */
import { describe, expect, it } from "vitest";
import {
  DERIVED_NOTE,
  derivedSummary,
  describeDerived,
  describeExpectationsAtRisk,
  describeImpact,
  describeSample,
  describeSchemaChange,
  expectationsAtRiskSummary,
  impactSummary,
  type AffectedDataset,
  type DerivedAnalysis,
  type DerivedImpact,
  type ExpectationAtRisk,
} from "./proposal-impact";

const affected = (name: string, version = 3, rows = 1200): AffectedDataset => ({
  state: "affected",
  model_id: "m1",
  model_name: "Daily",
  dataset: { id: "d1", name, slug: name.toLowerCase(), row_count: rows, current_version: version },
});

describe("what one row says", () => {
  it("names the dataset, its version and its size", () => {
    const said = describeImpact(affected("Ledger"));
    expect(said).toContain("Ledger");
    expect(said).toContain("v3");
    expect(said).toContain("1,200");
  });

  it("says a transform that has never been built has nothing to compare against", () => {
    expect(describeImpact({ state: "never_built", model_id: "m1", model_name: "Daily" }))
      .toContain("never been built");
  });

  it("says a new transform has no dataset at all, in different words", () => {
    // The two no-dataset states mean different things: one transform exists
    // and will produce a dataset; the other does not exist yet. Sharing a
    // sentence would send a reader to find out which.
    const unbuilt = describeImpact({ state: "never_built" });
    const fresh = describeImpact({ state: "new_transform", path: "src/x.sql" });
    expect(fresh).toContain("does not exist yet");
    expect(fresh).not.toBe(unbuilt);
  });

  it("does not claim a dataset for an affected row that has none", () => {
    // The server cannot produce this, and the component must not draw
    // `undefined` if it ever does — the fallback is the honest sentence rather
    // than a crash or a blank.
    expect(describeImpact({ state: "affected", dataset: null })).toContain(
      "does not exist yet",
    );
  });
});

describe("the panel's heading", () => {
  it("counts datasets rather than files", () => {
    // p.53's question is which datasets change. The two numbers differ exactly
    // when something has no dataset behind it, which is the case worth
    // noticing rather than the one to round away.
    const rows: AffectedDataset[] = [affected("A"), { state: "never_built" }];
    expect(impactSummary(rows)).toContain("1 dataset changes");
    expect(impactSummary(rows)).toContain("1 file has no dataset yet");
  });

  it("is singular for one and plural for several", () => {
    expect(impactSummary([affected("A")])).toBe("1 dataset changes.");
    expect(impactSummary([affected("A"), affected("B")])).toBe("2 datasets change.");
  });

  it("says plainly when nothing has a dataset", () => {
    expect(impactSummary([{ state: "never_built" }])).toContain("No datasets change");
    expect(impactSummary([{ state: "never_built" }])).toContain("1 file has");
  });

  it("pluralises the files without a dataset too", () => {
    const rows: AffectedDataset[] = [{ state: "never_built" }, { state: "new_transform" }];
    expect(impactSummary(rows)).toContain("2 files have no dataset yet");
  });

  it("has an answer for a list with nothing in it", () => {
    // The server cannot produce one — a proposal with no files is refused —
    // but a heading built by joining counts would read "0 datasets change."
    // and leave somebody wondering what was analysed.
    expect(impactSummary([])).toBe("Nothing to analyse.");
  });
});

describe("the limit of the answer", () => {
  it("says the derived datasets are not analysed", () => {
    // p.53's own default is the same, and Foundry offers "Add datasets to
    // analysis" to go further. That is not built, so the limit is stated
    // rather than left to be discovered by trusting a short list.
    expect(DERIVED_NOTE).toContain("downstream");
    expect(DERIVED_NOTE).toContain("not analysed");
  });
});

describe("what the columns do", () => {
  it("lists what was added, removed and retyped", () => {
    const lines = describeSchemaChange({
      ok: true,
      changes: {
        added: [{ name: "total", data_type: "BIGINT" }],
        removed: [{ name: "note", data_type: "VARCHAR" }],
        retyped: [{ name: "val", from: "BIGINT", to: "VARCHAR" }],
      },
    });
    expect(lines).toHaveLength(3);
    expect(lines[0]).toContain("total");
    expect(lines[1]).toContain("note");
    expect(lines[2]).toContain("BIGINT");
    expect(lines[2]).toContain("VARCHAR");
  });

  it("marks the three kinds differently", () => {
    // A reviewer scanning a list needs to know which direction each line goes
    // without reading it; three lines that all begin the same way are three
    // lines that have to be read.
    const lines = describeSchemaChange({
      ok: true,
      changes: {
        added: [{ name: "a", data_type: "BIGINT" }],
        removed: [{ name: "b", data_type: "BIGINT" }],
        retyped: [{ name: "c", from: "BIGINT", to: "VARCHAR" }],
      },
    });
    expect(new Set(lines.map((l) => l[0])).size).toBe(3);
  });

  it("says no column changes rather than nothing at all", () => {
    // The answer a reviewer most wants, and an empty space is
    // indistinguishable from a panel that did not load.
    expect(describeSchemaChange({ ok: true, changes: null })).toEqual([
      "No column changes.",
    ]);
  });

  it("reports code that does not run instead of the columns", () => {
    // Being shown "no column changes" for a transform that fails to compile is
    // true and useless, and reads as a safe change.
    const lines = describeSchemaChange({ ok: false, error: 'Referenced column "nope" not found' });
    expect(lines).toHaveLength(1);
    expect(lines[0]).toContain("nope");
  });

  it("has words for a failure that came with no message", () => {
    expect(describeSchemaChange({ ok: false, error: "   " })[0]).toBe(
      "This code does not run.",
    );
  });

  it("does not leave a heading with nothing under it", () => {
    // `diff_schemas` returns null rather than an empty object, so this cannot
    // arrive from this server — and an empty list would read as a failure.
    expect(describeSchemaChange({ ok: true, changes: {} })).toEqual([
      "No column changes.",
    ]);
  });
});

describe("how much was read", () => {
  it("says so plainly when the whole input was read", () => {
    expect(describeSample([{ alias: "raw", rows_used: 3, rows_available: 3 }])).toBe(
      "Run over every input row.",
    );
  });

  it("gives the numbers when it was a sample, and says they do not matter here", () => {
    const said = describeSample([{ alias: "raw", rows_used: 1000, rows_available: 5000 }]);
    expect(said).toContain("1,000 of 5,000 raw rows");
    // The point of saying it: the columns are the same either way, measured.
    expect(said).toContain("Columns do not depend on");
  });

  it("names only the inputs that were actually sampled", () => {
    // An input read whole is not a caveat, and listing it beside one that was
    // sampled makes the reader work out which is which.
    const said = describeSample([
      { alias: "whole", rows_used: 5, rows_available: 5 },
      { alias: "big", rows_used: 1000, rows_available: 9000 },
    ]);
    expect(said).toContain("big");
    expect(said).not.toContain("whole");
  });

  it("says nothing when there is nothing to say", () => {
    expect(describeSample([])).toBe("");
    expect(describeSample(undefined)).toBe("");
  });
});

describe("p.54's expectations, in the words a reviewer needs (§371)", () => {
  const at = (
    patch: Partial<ExpectationAtRisk> & Pick<ExpectationAtRisk, "outcome" | "reason">,
  ): ExpectationAtRisk => ({
    rule_type: "not_null", column_name: "amount", severity: "error", ...patch,
  });

  it("says a column_exists rule fails, because that is it working", () => {
    // The distinction the server keeps and this must not lose: `fail` is the
    // rule doing its job, `error` is the rule no longer applying.
    expect(
      describeExpectationsAtRisk([
        at({ rule_type: "column_exists", outcome: "fail", reason: "removed" }),
      ]),
    ).toEqual(["column_exists on amount fails: the column is removed (blocks a build)"]);
  });

  it("says every other rule can no longer run", () => {
    expect(
      describeExpectationsAtRisk([at({ outcome: "error", reason: "removed" })]),
    ).toEqual([
      "not_null on amount can no longer run: the column is removed (blocks a build)",
    ]);
  });

  it("names the type a retype moved to", () => {
    expect(
      describeExpectationsAtRisk([
        at({
          rule_type: "value_in_range", outcome: "error", reason: "retyped",
          new_type: "VARCHAR",
        }),
      ]),
    ).toEqual([
      "value_in_range on amount can no longer run: the column becomes VARCHAR (blocks a build)",
    ]);
  });

  it("carries the severity, because it decides whether this can land", () => {
    expect(
      describeExpectationsAtRisk([
        at({ severity: "warn", outcome: "error", reason: "removed" }),
      ]),
    ).toEqual([
      "not_null on amount can no longer run: the column is removed (a warning)",
    ]);
  });
});

describe("the line above that list (§371)", () => {
  const rule = (severity: string): ExpectationAtRisk => ({
    rule_type: "not_null", column_name: "amount", severity,
    outcome: "error", reason: "removed",
  });

  it("is silent when nothing is at risk", () => {
    // A heading reading "0 at risk" on every logic change is a panel to be
    // dismissed rather than one that speaks when it matters.
    expect(expectationsAtRiskSummary([])).toBe("");
  });

  it("counts one in the singular", () => {
    expect(expectationsAtRiskSummary([rule("error")])).toBe(
      "1 expectation would stop this build",
    );
  });

  it("says so when every one of them is only a warning", () => {
    expect(expectationsAtRiskSummary([rule("warn"), rule("warn")])).toBe(
      "2 expectations would stop reporting",
    );
  });

  it("splits the count when they are mixed", () => {
    // The number that decides whether this can land is the blocking one, and
    // a reviewer holding "3 at risk" cannot tell how many of those stop it.
    expect(expectationsAtRiskSummary([rule("warn"), rule("error"), rule("error")])).toBe(
      "3 expectations at risk, 2 of which would stop this build",
    );
  });
});

describe("what the change does downstream (§372)", () => {
  const hop = (patch: Partial<DerivedImpact> = {}): DerivedImpact => ({
    dataset_name: "Ledger", model_name: "Roll up", depth: 1, ok: true, ...patch,
  });

  it("says the transform no longer runs, first and alone", () => {
    // The code that breaks here is code the diff does not contain, so "no
    // column changes" for it would answer a question nobody asked.
    expect(describeDerived(hop({ ok: false, error: 'Referenced column "val" not found' })))
      .toEqual(['Referenced column "val" not found']);
  });

  it("falls back to a sentence when the failure carried no message", () => {
    expect(describeDerived(hop({ ok: false, error: "  " })))
      .toEqual(["This transform no longer runs."]);
  });

  it("says so plainly when the columns did not move", () => {
    expect(describeDerived(hop({ changes: null }))).toEqual(["No column changes."]);
  });

  it("reuses the schema wording rather than a second copy of it", () => {
    // §292: one description of a column change, so the downstream list and the
    // panel above it cannot come to word the same fact differently.
    expect(describeDerived(hop({ changes: { retyped: [{ name: "val", from: "BIGINT", to: "DECIMAL(21,1)" }] } })))
      .toEqual(["~ val: BIGINT → DECIMAL(21,1)"]);
  });
});

describe("the line above the downstream list (§372)", () => {
  const analysis = (patch: Partial<DerivedAnalysis> = {}): DerivedAnalysis => ({
    datasets: [], not_analysed: [], max_depth: 3, truncated: false, ...patch,
  });
  const one = { dataset_name: "Ledger", model_name: "Roll up", depth: 1, ok: true };

  it("says when nothing is built from the dataset", () => {
    expect(derivedSummary(analysis())).toBe("Nothing is built from this dataset.");
  });

  it("counts one in the singular", () => {
    expect(derivedSummary(analysis({ datasets: [one] })))
      .toBe("1 dataset built from this one.");
  });

  it("says when the walk stopped short", () => {
    // A bounded list with no sign of its bound is a short answer wearing a
    // complete one's clothes.
    expect(derivedSummary(analysis({ datasets: [one, one], truncated: true })))
      .toBe("2 datasets built from this one; stopping 3 steps down — there is more below.");
  });

  it("counts what could not be analysed at all", () => {
    expect(
      derivedSummary(analysis({
        datasets: [one],
        not_analysed: [{ model_name: "Draft", reason: "never built" }],
      })),
    ).toBe("1 dataset built from this one; 1 transform could not be analysed.");
  });

  it("carries both limits at once", () => {
    expect(
      derivedSummary(analysis({
        datasets: [one], truncated: true,
        not_analysed: [
          { model_name: "A", reason: "x" },
          { model_name: "B", reason: "y" },
        ],
      })),
    ).toBe(
      "1 dataset built from this one; stopping 3 steps down — there is more below; " +
      "2 transforms could not be analysed.",
    );
  });
});
