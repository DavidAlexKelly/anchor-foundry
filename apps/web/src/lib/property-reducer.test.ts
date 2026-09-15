/**
 * Declaring a property reducer in the editor (§349; Foundry
 * `object-link-types` p.131–133; db 0088).
 *
 * The operation table is guarded against the *server's* by
 * `apps/api/tests/test_property_reducers.py`, which is the direction that
 * catches an addition. What is here is the part the server cannot see: which
 * rows this dialog offers, what it seeds them with, and what it refuses before
 * anybody waits for a 422.
 */
import { describe, expect, it } from "vitest";
import {
  OPERATIONS, OPERATION_LABELS, basisOf, blankReducer, canReduce,
  operationsFor, problem, reducerSummary, reducible, reducibleFields,
  withField,
} from "./property-reducer";
import type { PropertyDataType, StructField } from "@/lib/types";

const FIELDS: StructField[] = [
  { api_name: "on", display_name: "On", description: "", data_type: "date" },
  { api_name: "score", display_name: "Score", description: "", data_type: "integer" },
  { api_name: "where", display_name: "Where", description: "", data_type: "geopoint" },
];

const row = (over: Record<string, unknown> = {}) => ({
  data_type: "array" as PropertyDataType,
  array_of: "date" as PropertyDataType | null,
  struct_fields: null as StructField[] | null,
  reducers: null,
  ...over,
});

const structs = (over: Record<string, unknown> = {}) =>
  row({ array_of: "struct", struct_fields: FIELDS, ...over });

describe("which rows may be reduced (p.132)", () => {
  it("an array of a type p.132 orders", () => {
    expect(canReduce(row())).toBe(true);
    expect(canReduce(row({ array_of: "string" }))).toBe(true);
    expect(canReduce(row({ array_of: "boolean" }))).toBe(true);
  });

  it("not an array of a type it does not", () => {
    // Without this a Reduce button would appear on an array of geopoints and
    // open a dialog whose only outcome is the server's refusal — §214.
    expect(canReduce(row({ array_of: "geopoint" }))).toBe(false);
    expect(canReduce(row({ array_of: "json" }))).toBe(false);
    expect(canReduce(row({ array_of: "attachment" }))).toBe(false);
  });

  it("not a property that is not an array at all", () => {
    expect(canReduce(row({ data_type: "string", array_of: null }))).toBe(false);
    expect(canReduce(row({ data_type: "struct", array_of: null,
                           struct_fields: FIELDS }))).toBe(false);
  });

  it("a struct array, but only for the fields p.132 orders", () => {
    expect(canReduce(structs())).toBe(true);
    expect(reducibleFields(structs()).map((f) => f.api_name)).toEqual(["on", "score"]);
    // The negative control, and it is a real shape: a struct whose every field
    // is a geopoint has nothing to reduce *by*, so the button must not appear
    // even though the element type is reducible in principle.
    const only = [FIELDS[2]];
    expect(canReduce(structs({ struct_fields: only }))).toBe(false);
    expect(canReduce(structs({ struct_fields: [] }))).toBe(false);
  });

  it("does not read a plain array's fields", () => {
    // `struct_fields` means the element's fields only when the element is a
    // struct (db 0064), so a date array carrying a stale declaration must not
    // become reducible by one.
    expect(reducibleFields(row({ struct_fields: FIELDS }))).toEqual([]);
  });
});

describe("which operations a row offers (p.132–133)", () => {
  it("the element type's, for a plain array", () => {
    expect(operationsFor(row(), { operation: "latest", field: null }))
      .toEqual(["latest", "earliest"]);
    expect(operationsFor(row({ array_of: "string" }), { operation: "first", field: null }))
      .toEqual(["first", "last"]);
  });

  it("the struct field's, for a struct array", () => {
    // p.133: reducers "function on struct arrays based on a specific field
    // within the struct, not the struct itself" — so the same property offers
    // different operations on different rows.
    expect(operationsFor(structs(), { operation: "latest", field: "on" }))
      .toEqual(["latest", "earliest"]);
    expect(operationsFor(structs(), { operation: "highest", field: "score" }))
      .toEqual(["highest", "lowest"]);
    expect(basisOf(structs(), { operation: "latest", field: "on" })).toBe("date");
  });

  it("none, for a field that is gone or was retyped", () => {
    // Not reachable through the dialog and reachable through a stored
    // declaration, which is why `problem` asks rather than trusting the row.
    expect(operationsFor(structs(), { operation: "latest", field: "missing" })).toEqual([]);
    expect(operationsFor(structs(), { operation: "first", field: "where" })).toEqual([]);
  });

  it("every operation reads as p.132's own words", () => {
    // The table is the API's vocabulary; this is what somebody chooses
    // between. A missing label would render a row as the stored name.
    for (const ops of Object.values(OPERATIONS)) {
      for (const op of ops) expect(OPERATION_LABELS[op]).toBeTruthy();
    }
    expect(OPERATION_LABELS.latest).toBe("Most recent");
    // p.132 puts "lexicographically" on the string pair, where it says *which*
    // order — "latest" already carries its own.
    expect(OPERATION_LABELS.first).toContain("lexicographically");
    expect(OPERATION_LABELS.latest).not.toContain("lexicographically");
  });

  it("knows which base types can be ordered at all", () => {
    expect(reducible("date")).toBe(true);
    expect(reducible("geopoint")).toBe(false);
    expect(reducible(null)).toBe(false);
    expect(reducible(undefined)).toBe(false);
  });
});

describe("a new row arrives answered (§349)", () => {
  it("with the element type's first operation", () => {
    expect(blankReducer(row(), [])).toEqual({ operation: "latest", field: null });
    expect(blankReducer(row({ array_of: "boolean" }), []))
      .toEqual({ operation: "true_first", field: null });
  });

  it("with the first struct field nothing has claimed", () => {
    // p.133's reason for a list is reducing by *different* fields, so opening
    // on a duplicate would be opening on a complaint.
    expect(blankReducer(structs(), [])).toEqual({ operation: "latest", field: "on" });
    expect(blankReducer(structs(), [{ operation: "latest", field: "on" }]))
      .toEqual({ operation: "highest", field: "score" });
  });

  it("never on a field p.132 cannot order", () => {
    const taken = [
      { operation: "latest", field: "on" },
      { operation: "highest", field: "score" },
    ];
    // `where` is a geopoint, so the fallback is a duplicate rather than an
    // unorderable field — a row `problem` can explain beats one it cannot.
    expect(blankReducer(structs(), taken).field).toBe("on");
  });
});

describe("changing which field a reducer reads (p.133)", () => {
  it("keeps an operation the new field also takes", () => {
    const moved = withField(structs(), { operation: "earliest", field: "on" }, "on");
    expect(moved.operation).toBe("earliest");
  });

  it("replaces one the new field cannot do", () => {
    // **The half a plain `{...reducer, field}` gets wrong**, and it gets it
    // wrong the way §347's transition did: the row still looks right and the
    // server refuses it with a message about a control the dialog is no longer
    // showing.
    const moved = withField(structs(), { operation: "latest", field: "on" }, "score");
    expect(moved).toEqual({ operation: "highest", field: "score" });
  });
});

describe("what the dialog refuses before saving (§349)", () => {
  it("nothing, for an empty list", () => {
    // p.131 makes reduction optional, so removing every row is how a property
    // stops reducing rather than a state to complain about.
    expect(problem(row(), [])).toBeNull();
  });

  it("nothing, for a declaration the server will take", () => {
    // The negative control: a refusal that fired on everything would pass
    // every assertion below.
    expect(problem(row(), [{ operation: "latest", field: null }])).toBeNull();
    expect(problem(structs(), [
      { operation: "latest", field: "on" },
      { operation: "highest", field: "score" },
    ])).toBeNull();
  });

  it("a struct array row with no field", () => {
    const said = problem(structs(), [{ operation: "latest", field: null }]);
    expect(said).toContain("struct field");
  });

  it("a field that cannot be ordered", () => {
    const said = problem(structs(), [{ operation: "first", field: "where" }]);
    expect(said).toContain("where");
  });

  it("an operation the basis cannot do", () => {
    const said = problem(row({ array_of: "string" }),
                         [{ operation: "latest", field: null }]);
    expect(said).toContain("string");
  });

  it("a second reducer over the same basis", () => {
    // p.133 gives a second reducer one job, and two values tied on a basis are
    // tied on it whichever operation asks — so this one provably does nothing.
    const said = problem(structs(), [
      { operation: "latest", field: "on" },
      { operation: "earliest", field: "on" },
    ]);
    expect(said).toContain("on");
    expect(said).toContain("tie");
  });

  it("any second reducer on a plain array", () => {
    const said = problem(row(), [
      { operation: "latest", field: null },
      { operation: "earliest", field: null },
    ]);
    expect(said).toContain("tie");
  });

  it("names the row it is about", () => {
    // Two bad rows and the second one is the one reported, which is what makes
    // "Reducer 2" worth printing at all.
    const said = problem(structs(), [
      { operation: "latest", field: "on" },
      { operation: "first", field: "where" },
    ]);
    expect(said).toContain("Reducer 2");
  });
});

describe("what a row's button says", () => {
  it("counts the reducers, and says nothing when there are none", () => {
    expect(reducerSummary(row({ reducers: null }))).toBe("");
    expect(reducerSummary(row({ reducers: [] }))).toBe("");
    expect(reducerSummary(row({ reducers: [{ operation: "latest", field: null }] })))
      .toBe(" (1)");
  });
});
