/** §506: the Details tab's "Made by" and "Made from" (`dataset-preview` p.3). */
import { describe, expect, it } from "vitest";

import { TOOL_LABELS, kindText, madeByText, originHref, type DatasetOrigin } from "./dataset-origin";

const base: DatasetOrigin = {
  version_number: 2, kind: "model", made_at: "2026-09-26T10:00:00Z",
  tool: null, inputs: [], note: null,
};

describe("madeByText", () => {
  it("names the tool by its label and its name", () => {
    expect(madeByText({ ...base, tool: { kind: "transform", name: "Clean", resource_id: "r1" } }))
      .toBe("Transform Clean");
    expect(madeByText({ ...base, kind: "sync", tool: { kind: "sync", name: "Warehouse", resource_id: "r2" } }))
      .toBe("Sync Warehouse");
    expect(madeByText({ ...base, kind: "action", tool: { kind: "action", name: "Retriage", resource_id: null } }))
      .toBe("Action Retriage");
  });

  it("falls back to the tool's own kind for one it has no label for", () => {
    expect(madeByText({ ...base, tool: { kind: "pipeline", name: "P", resource_id: null } }))
      .toBe("pipeline P");
  });

  it("says what kind of thing wrote it when no tool can be named", () => {
    expect(madeByText(base)).toBe("A transform");
    expect(madeByText({ ...base, kind: "upload" })).toBe("An upload");
  });
});

describe("kindText", () => {
  it("has a phrase for every producer the API writes", () => {
    expect(Object.fromEntries(
      ["model", "sync", "action", "action_batch", "fork", "rollback", "reparse", "upload", "other"]
        .map((k) => [k, kindText(k)]),
    )).toEqual({
      model: "A transform", sync: "A sync", action: "An action",
      action_batch: "A batch of actions", fork: "A branch", rollback: "A rollback",
      reparse: "A re-parse", upload: "An upload", other: "other",
    });
  });

  it("labels the three tools", () => {
    expect(TOOL_LABELS).toEqual({ transform: "Transform", sync: "Sync", action: "Action" });
  });
});

describe("originHref", () => {
  it("opens the resource", () => {
    expect(originHref("abc")).toBe("/r/abc");
  });
});
