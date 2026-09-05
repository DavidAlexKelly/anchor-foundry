import { describe, expect, it } from "vitest";

import { outputClauses, outputKeys, type Touched } from "./action-output";
import { keysOf } from "./object-table-selection";

const T = "type-1";
const OTHER = "type-2";

const touched = (over: Partial<Touched> = {}): Touched => ({
  object_type_id: T,
  primary_key: "k1",
  change: "modified",
  ...over,
});

describe("which keys the output names (p.513)", () => {
  it("names what the action wrote", () => {
    expect(outputKeys([touched({ primary_key: "a" }), touched({ primary_key: "b" })], T))
      .toEqual(["a", "b"]);
  });

  it("keeps created and modified alike", () => {
    // p.513's own two verbs. The set is "what this submission produced", and a
    // reader acting on it does not care which verb made each row.
    expect(outputKeys([
      touched({ primary_key: "a", change: "modified" }),
      touched({ primary_key: "b", change: "created" }),
    ], T)).toEqual(["a", "b"]);
  });

  it("leaves out another object type's objects", () => {
    // **The stated divergence.** `narrow_set` narrows one base set, so a mixed
    // list would name rows that set does not contain - a set resolving to fewer
    // rows than it names is worse than one that never claimed them.
    expect(outputKeys([
      touched({ primary_key: "a" }),
      touched({ primary_key: "b", object_type_id: OTHER }),
    ], T)).toEqual(["a"]);
  });

  it("names nothing when there is no type to name it against", () => {
    expect(outputKeys([touched()], null)).toEqual([]);
    expect(outputKeys([touched()], undefined)).toEqual([]);
  });

  it("does not repeat an object", () => {
    // An action can write the subject and also name it through a parameter.
    expect(outputKeys([
      touched({ primary_key: "a" }),
      touched({ primary_key: "a", change: "created" }),
    ], T)).toEqual(["a"]);
  });

  it("survives whatever the wire holds", () => {
    expect(outputKeys(undefined, T)).toEqual([]);
    expect(outputKeys([], T)).toEqual([]);
    expect(outputKeys([touched({ primary_key: null })], T)).toEqual([]);
    expect(outputKeys([touched({ primary_key: "" })], T)).toEqual([]);
    expect(outputKeys([touched({ object_type_id: null })], T)).toEqual([]);
  });
});

describe("what the widget writes", () => {
  it("writes clauses the selection language already speaks", () => {
    // Read back through `keysOf`, which is what every consumer of a clause list
    // uses — so this asserts the two halves agree rather than asserting a shape.
    expect(keysOf(outputClauses([
      touched({ primary_key: "a" }), touched({ primary_key: "b" }),
    ], T))).toEqual(["a", "b"]);
  });

  it("writes the empty set rather than nothing", () => {
    // **Stated, not skipped.** Leaving the variable alone would leave the
    // previous submission's objects on screen, and a reader would act on rows
    // this press of Submit did not touch. `object_sets.parse` reads `in []` as
    // the empty set (§207).
    const clauses = outputClauses([touched({ object_type_id: OTHER })], T);
    expect(clauses).toHaveLength(1);
    expect(keysOf(clauses)).toEqual([]);
  });
});
