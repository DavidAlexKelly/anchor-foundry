/** §531: p.8's histogram over a selection on the lineage graph. */
import { describe, expect, it } from "vitest";

import { HISTOGRAM_PROPERTIES, copiedNames, histogram, litByValue } from "./graph-histogram";
import type { PipelineNode } from "./types";

function node(id: string, over: Partial<PipelineNode>): PipelineNode {
  return {
    id, kind: "dataset", resource_id: id, name: id, layer: 0, position: 0, in_cycle: false,
    is_focus: false, slug: null, origin: null, repository_name: null, row_count: null, current_version: null,
    health_status: null, language: null, trigger_mode: null, last_run_status: null,
    last_run_at: null, updated_at: null, built_at: null, build_started_at: null, build_finished_at: null, out_of_date: false,
    out_of_date_reason: null, ...over,
  };
}

const NODES = [
  node("d1", { origin: "upload", built_at: "2026-01-01", health_status: "healthy" }),
  node("d2", { origin: "transform", built_at: "2026-01-02", out_of_date: true, health_status: "healthy" }),
  node("d3", { origin: "transform", built_at: "2026-01-03" }),
  node("m1", { kind: "model", language: "python", trigger_mode: "manual", last_run_status: "succeeded" }),
];

describe("the histogram", () => {
  it("counts each property's values, most frequent first and then by value", () => {
    const rows = histogram(NODES);
    expect(rows.map((r) => r.label)).toEqual(
      ["Kind", "Origin", "Health", "Language", "Runs", "Last run", "Up to date"]);
    const byProperty = Object.fromEntries(rows.map((r) => [r.property, r.values]));
    expect(byProperty.kind).toEqual([
      { value: "dataset", count: 3, ids: ["d1", "d2", "d3"] },
      { value: "model", count: 1, ids: ["m1"] },
    ]);
    expect(byProperty.origin?.map((v) => [v.value, v.count])).toEqual([["transform", 2], ["upload", 1]]);
    // A model is neither up to date nor out of it.
    expect(byProperty.out_of_date?.map((v) => [v.value, v.count])).toEqual(
      [["up to date", 2], ["out of date", 1]]);
  });

  it("leaves out a property nobody selected has", () => {
    const rows = histogram(NODES.slice(0, 3));
    expect(rows.map((r) => r.property)).toEqual(["kind", "origin", "health_status", "out_of_date"]);
    expect(histogram([])).toEqual([]);
  });

  it("does not count an empty value as one", () => {
    const rows = histogram([node("a", { origin: "" }), node("b", { origin: "" })]);
    expect(rows.map((r) => r.property)).toEqual(["kind"]);
  });

  it("orders equal counts by value", () => {
    const rows = histogram([node("a", { origin: "zeta" }), node("b", { origin: "alpha" })]);
    expect(rows.find((r) => r.property === "origin")?.values.map((v) => v.value)).toEqual(["alpha", "zeta"]);
  });

  it("names every kind the graph draws", () => {
    const kinds = histogram([
      node("a", { kind: "object_type" }), node("b", { kind: "connection" }),
    ]).find((r) => r.property === "kind")?.values.map((v) => v.value);
    expect(kinds).toEqual(["data source", "object type"]);
    expect(HISTOGRAM_PROPERTIES).toHaveLength(7);
  });
});

describe("what a chosen value lights", () => {
  const rows = histogram(NODES);
  it("is the nodes with that value", () => {
    expect(litByValue(rows, { property: "origin", value: "transform" })).toEqual(["d2", "d3"]);
    expect(litByValue(rows, { property: "kind", value: "model" })).toEqual(["m1"]);
  });
  it("is nothing when nothing is chosen, or the value is gone", () => {
    expect(litByValue(rows, null)).toEqual([]);
    expect(litByValue(rows, { property: "origin", value: "sync" })).toEqual([]);
    expect(litByValue(rows, { property: "colour", value: "red" })).toEqual([]);
  });
});

describe("Copy names", () => {
  it("is the names, comma-separated, in selection order", () => {
    expect(copiedNames([{ name: "Orders" }, { name: "Daily totals" }])).toBe("Orders, Daily totals");
    expect(copiedNames([])).toBe("");
  });
});
