/** What a proposal does to its datasets (§364; `code-repositories` p.53). */
import { describe, expect, it } from "vitest";
import {
  DERIVED_NOTE,
  describeImpact,
  impactSummary,
  type AffectedDataset,
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
