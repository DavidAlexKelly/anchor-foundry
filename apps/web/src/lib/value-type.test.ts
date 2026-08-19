/**
 * Building and offering a value type (Foundry `object-link-types` p.222–234).
 *
 * The server is authoritative and is tested in
 * `apps/api/tests/test_value_constraints.py`. This is the form's copy of the
 * same rules, asked for a different reason: what to *offer*, and what to say
 * before somebody presses Save.
 *
 * It gets its own tests because the failure is quiet in both directions. A
 * kind offered that the base type does not allow is a dropdown full of saves
 * that fail; a problem the form does not name is a 422 arriving after somebody
 * has already committed to their answer.
 */
import { describe, expect, it } from "vitest";

import type { ValueType } from "@/lib/types";
import {
  constraintProblem, kindsFor, offerableTo, optionLabel, rangeLabel,
} from "./value-type";

function valueType(over: Partial<ValueType> = {}): ValueType {
  return {
    id: "vt1",
    api_name: "email",
    display_name: "Email address",
    description: "",
    example_value: "ada@example.com",
    base_type: "string",
    version_number: 1,
    constraint: { kind: "regex", pattern: "[a-z]+@example\\.com" },
    constraint_summary: "matches [a-z]+@example\\.com",
    usage_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("kindsFor", () => {
  it("offers every kind a string can carry", () => {
    // p.233 puts regex and uuid under String only, and string is also the one
    // type where a *range* means something other than magnitude.
    expect(kindsFor("string")).toEqual(["enum", "range", "regex", "uuid"]);
  });

  it("offers a number an enum and a range, and no regex", () => {
    expect(kindsFor("integer")).toEqual(["enum", "range"]);
    expect(kindsFor("float")).toEqual(["enum", "range"]);
  });

  it("offers a temporal type a range only", () => {
    // p.233 lists Date and Timestamp under Range, and not under Enum.
    expect(kindsFor("date")).toEqual(["range"]);
    expect(kindsFor("timestamp")).toEqual(["range"]);
  });

  it("offers a boolean an enum only", () => {
    expect(kindsFor("boolean")).toEqual(["enum"]);
  });

  it("offers nothing for a type p.233 does not cover", () => {
    // A geopoint has no constraint kind here, and an empty list is the honest
    // answer — the alternative is a form offering a check that could not pass.
    expect(kindsFor("geopoint")).toEqual([]);
    expect(kindsFor("attachment")).toEqual([]);
  });
});

describe("rangeLabel", () => {
  it("says length for a string and value for everything else", () => {
    // p.233: "For String properties, the length of the string is
    // constrained." One word for two different meanings is how somebody ends
    // up thinking they bounded the alphabet.
    expect(rangeLabel("string")).toBe("Length");
    expect(rangeLabel("integer")).toBe("Value");
    expect(rangeLabel("date")).toBe("Value");
  });
});

describe("constraintProblem", () => {
  it("accepts no constraint at all", () => {
    // p.224 step 6 marks it "(Optional)".
    expect(constraintProblem(null, "string")).toBeNull();
  });

  it("refuses a kind the base type does not allow", () => {
    expect(
      constraintProblem({ kind: "regex", pattern: "^x$" }, "integer"),
    ).toMatch(/does not apply/);
  });

  it("wants at least one enum value, and no duplicates", () => {
    expect(constraintProblem({ kind: "enum", values: [] }, "string"))
      .toMatch(/at least one/);
    expect(constraintProblem({ kind: "enum", values: ["a", "a"] }, "string"))
      .toMatch(/same value twice/);
    expect(constraintProblem({ kind: "enum", values: ["a", "b"] }, "string"))
      .toBeNull();
  });

  it("wants a range to bound something", () => {
    expect(constraintProblem({ kind: "range" }, "integer")).toMatch(/needs a minimum/);
    expect(constraintProblem({ kind: "range", minimum: 1 }, "integer")).toBeNull();
    expect(constraintProblem({ kind: "range", maximum: 9 }, "integer")).toBeNull();
  });

  it("refuses a range nothing could satisfy", () => {
    expect(
      constraintProblem({ kind: "range", minimum: 10, maximum: 1 }, "integer"),
    ).toMatch(/nothing could satisfy/);
    expect(
      constraintProblem({ kind: "range", minimum: 1, maximum: 10 }, "integer"),
    ).toBeNull();
    // Equal bounds are a legitimate "exactly this".
    expect(
      constraintProblem({ kind: "range", minimum: 5, maximum: 5 }, "integer"),
    ).toBeNull();
  });

  it("compares temporal bounds as instants, not as text", () => {
    // The bug §168's mutation testing found on the server, in its browser
    // form: these two are ordered one way as strings and the other way as
    // instants, and only the instants are what a date range means.
    expect(
      constraintProblem(
        { kind: "range", minimum: "2026-01-01T05:00:00+06:00",
          maximum: "2026-01-01T00:30:00Z" },
        "timestamp",
      ),
    ).toBeNull();
    expect(
      constraintProblem(
        { kind: "range", minimum: "2026-06-01", maximum: "2026-01-01" },
        "date",
      ),
    ).toMatch(/nothing could satisfy/);
  });

  it("refuses a negative string length", () => {
    expect(constraintProblem({ kind: "range", minimum: -1 }, "string"))
      .toMatch(/cannot be negative/);
    // And zero is fine: an empty string is a legitimate thing to allow.
    expect(constraintProblem({ kind: "range", minimum: 0 }, "string")).toBeNull();
  });

  it("wants a regex that is present and compiles", () => {
    expect(constraintProblem({ kind: "regex", pattern: "  " }, "string"))
      .toMatch(/needs a pattern/);
    expect(constraintProblem({ kind: "regex", pattern: "([unclosed" }, "string"))
      .toMatch(/not a valid regular expression/);
    expect(constraintProblem({ kind: "regex", pattern: "^[a-z]+$" }, "string"))
      .toBeNull();
  });

  it("has nothing to say about a uuid constraint", () => {
    expect(constraintProblem({ kind: "uuid" }, "string")).toBeNull();
  });
});

describe("offerableTo", () => {
  const email = valueType();
  const score = valueType({ id: "vt2", api_name: "score", base_type: "integer" });

  it("offers only the value types whose base type matches", () => {
    expect(offerableTo([email, score], "string").map((t) => t.id)).toEqual(["vt1"]);
    expect(offerableTo([email, score], "integer").map((t) => t.id)).toEqual(["vt2"]);
  });

  it("offers nothing rather than everything when none matches", () => {
    // Falling back to the whole list would be offering a save the server
    // refuses — the trap this function exists to avoid.
    expect(offerableTo([email, score], "date")).toEqual([]);
  });
});

describe("optionLabel", () => {
  it("says what the value type actually enforces", () => {
    // The name alone does not distinguish an `email` that checks a pattern
    // from one that checks nothing, and that is the difference somebody
    // choosing between them cares about.
    expect(optionLabel(valueType())).toBe(
      "Email address — matches [a-z]+@example\\.com",
    );
  });
});
