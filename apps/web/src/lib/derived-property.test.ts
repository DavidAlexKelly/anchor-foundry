/**
 * Building a derived property's link chain (Foundry `object-link-types`
 * p.144–147).
 *
 * The server decides what is legal and is tested in
 * `apps/api/tests/test_derived_properties.py`. This is the editor's copy of
 * the same walk, asked for a different reason: what to *offer*. It gets its
 * own tests because the one thing the server got wrong was the direction of a
 * `one_to_many` hop — a mistake no rendering test can see, and one this file
 * could repeat independently.
 */
import { describe, expect, it } from "vitest";

import type { LinkType } from "@/lib/types";
import {
  NUMERIC_AGGREGATES, chainState, derivableProperties, derivationProblem, hopsFrom,
  reachesMany,
} from "./derived-property";

const DEPARTMENT = "dept";
const EMPLOYEE = "emp";
const PROJECT = "proj";

function link(over: Partial<LinkType>): LinkType {
  return {
    id: "l1", api_name: "l", display_name: "Link", cardinality: "one_to_many",
    from_object_type_id: EMPLOYEE, from_display_name: "Employee",
    to_object_type_id: DEPARTMENT, to_display_name: "Department",
    from_property: "department", to_property: "$primary_key",
    from_side_name: null, to_side_name: null,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  } as LinkType;
}

const WORKS_IN = link({ id: "works_in", display_name: "Works in",
  from_side_name: "Employees", to_side_name: "Department" });
const ASSIGNED = link({
  id: "assigned", display_name: "Assigned to", cardinality: "many_to_many",
  from_object_type_id: EMPLOYEE, from_display_name: "Employee",
  to_object_type_id: PROJECT, to_display_name: "Project",
});
const UNJOINED = link({
  id: "unjoined", display_name: "Related", from_property: null, to_property: null,
});

describe("reachesMany", () => {
  it("reads one_to_many from the `to` side", () => {
    // The foreign key is on the `from` side, so many `from` rows point at one
    // `to` row: outbound lands on exactly one, inbound on many. Getting this
    // backwards is what §161 did, and it would let a department derive an
    // employee's salary with no aggregation.
    expect(reachesMany("one_to_many", true)).toBe(false);
    expect(reachesMany("one_to_many", false)).toBe(true);
  });

  it("is many both ways for many_to_many and never for one_to_one", () => {
    expect(reachesMany("many_to_many", true)).toBe(true);
    expect(reachesMany("many_to_many", false)).toBe(true);
    expect(reachesMany("one_to_one", true)).toBe(false);
    expect(reachesMany("one_to_one", false)).toBe(false);
  });
});

describe("hopsFrom", () => {
  it("offers a link from the end that touches this type, named for where it lands", () => {
    const fromDept = hopsFrom([WORKS_IN], DEPARTMENT);
    expect(fromDept).toHaveLength(1);
    expect(fromDept[0]!.far_type_id).toBe(EMPLOYEE);
    expect(fromDept[0]!.label).toBe("Employees → Employee");
    // A department reaches many employees, so this hop demands an aggregation.
    expect(fromDept[0]!.reaches_many).toBe(true);

    const fromEmp = hopsFrom([WORKS_IN], EMPLOYEE);
    expect(fromEmp[0]!.far_type_id).toBe(DEPARTMENT);
    expect(fromEmp[0]!.label).toBe("Department → Department");
    expect(fromEmp[0]!.reaches_many).toBe(false);
  });

  it("falls back to the link's own name when a side is unnamed", () => {
    expect(hopsFrom([ASSIGNED], EMPLOYEE)[0]!.label).toBe("Assigned to → Project");
  });

  it("offers a self-link twice, because the two ends land apart", () => {
    const self = link({
      id: "reports_to", display_name: "Reports to",
      from_object_type_id: EMPLOYEE, to_object_type_id: EMPLOYEE,
      from_display_name: "Employee", to_display_name: "Employee",
      from_side_name: "Direct reports", to_side_name: "Manager",
    });
    const both = hopsFrom([self], EMPLOYEE);
    expect(both.map((h) => h.label)).toEqual([
      "Manager → Employee", "Direct reports → Employee",
    ]);
    // And the two directions disagree about reaching many, which is the whole
    // reason they are separate offers.
    expect(both.map((h) => h.reaches_many)).toEqual([false, true]);
  });

  it("leaves out a link with no join", () => {
    // db 0027 allows a link type to be defined and not traversable. There is
    // nothing to follow along one, so offering it would be offering a hop the
    // save refuses.
    expect(hopsFrom([UNJOINED], DEPARTMENT)).toEqual([]);
  });

  it("leaves out links that do not touch this type", () => {
    expect(hopsFrom([ASSIGNED], DEPARTMENT)).toEqual([]);
  });
});

describe("chainState", () => {
  it("stands at the start with nothing chosen", () => {
    const state = chainState(DEPARTMENT, []);
    expect(state.here).toBe(DEPARTMENT);
    expect(state.reachesMany).toBe(false);
    expect(state.canExtend).toBe(true);
  });

  it("walks to the last landing and remembers a many hop", () => {
    const first = hopsFrom([WORKS_IN], DEPARTMENT)[0]!;
    const second = hopsFrom([ASSIGNED], EMPLOYEE)[0]!;
    const state = chainState(DEPARTMENT, [first, second]);
    expect(state.here).toBe(PROJECT);
    expect(state.reachesMany).toBe(true);
  });

  it("stops offering another hop at p.147's third", () => {
    const hop = hopsFrom([WORKS_IN], DEPARTMENT)[0]!;
    expect(chainState(DEPARTMENT, [hop, hop]).canExtend).toBe(true);
    expect(chainState(DEPARTMENT, [hop, hop, hop]).canExtend).toBe(false);
  });

  it("keeps `reachesMany` once any hop has set it", () => {
    // A one-to-one hop after a many hop does not undo the many: the chain can
    // still reach more than one object, so the aggregation is still required.
    const many = hopsFrom([WORKS_IN], DEPARTMENT)[0]!;
    const one = hopsFrom([WORKS_IN], EMPLOYEE)[0]!;
    expect(chainState(DEPARTMENT, [many, one]).reachesMany).toBe(true);
  });
});

describe("derivationProblem", () => {
  const many = chainState(DEPARTMENT, hopsFrom([WORKS_IN], DEPARTMENT));
  const one = chainState(EMPLOYEE, hopsFrom([WORKS_IN], EMPLOYEE));

  it("wants a link before anything else", () => {
    expect(derivationProblem(chainState(DEPARTMENT, []), "", "")).toMatch(/Choose a link/);
  });

  it("demands an aggregation only when the chain can reach many", () => {
    expect(derivationProblem(many, "", "")).toMatch(/more than one object/);
    expect(derivationProblem(one, "", "")).toBeNull();
  });

  it("wants a property for everything except count", () => {
    expect(derivationProblem(many, "collect_list", "")).toMatch(/which property/);
    expect(derivationProblem(many, "collect_list", "salary")).toBeNull();
    // p.146: "For Count aggregation, you do not need to select a property."
    expect(derivationProblem(many, "count", "")).toBeNull();
  });
});

// ---- §406: p.145's four arithmetic aggregations -----------------------------

describe("which properties an aggregation may run over", () => {
  const FAR = [
    { api_name: "salary", data_type: "integer", derivation: null },
    { api_name: "rating", data_type: "float", derivation: null },
    { api_name: "title", data_type: "string", derivation: null },
    { api_name: "started", data_type: "date", derivation: null },
    { api_name: "headcount", data_type: "integer", derivation: { links: [] } },
  ];

  it("offers every property to the aggregations that need no declared type", () => {
    // `count_distinct`-shaped questions are text identity and work on
    // anything, which is why this is two lists rather than one narrowed one.
    for (const aggregate of ["", "count", "exact_cardinality", "collect_list"]) {
      expect(derivableProperties(FAR, aggregate).map((p) => p.api_name))
        .toEqual(["salary", "rating", "title", "started", "headcount"]);
    }
  });

  it("narrows to declared numbers for the four arithmetic ones", () => {
    for (const aggregate of NUMERIC_AGGREGATES) {
      expect(derivableProperties(FAR, aggregate).map((p) => p.api_name))
        .toEqual(["salary", "rating"]);
    }
  });

  it("excludes a derived property, which is p.169's word 'native'", () => {
    // `headcount` is a declared integer and still not offered: it is itself a
    // chain, so an aggregation over it would be an aggregation over a
    // per-object walk, with no column to push into.
    expect(derivableProperties(FAR, "sum").map((p) => p.api_name))
      .not.toContain("headcount");
    // And the exclusion is about the derivation rather than about the name.
    expect(derivableProperties(
      [{ api_name: "headcount", data_type: "integer", derivation: null }], "sum",
    ).map((p) => p.api_name)).toEqual(["headcount"]);
  });
});

describe("the arithmetic rule as a sentence", () => {
  const many = chainState("dept", [
    { link_type_id: "l1", far_type_id: "emp", reaches_many: true, label: "Employees" },
  ]);
  const FAR = [
    { api_name: "salary", data_type: "integer", derivation: null },
    { api_name: "title", data_type: "string", derivation: null },
  ];

  it("passes p.143's own first example", () => {
    expect(derivationProblem(many, "avg", "salary", FAR)).toBeNull();
  });

  it("names the property and what it would need", () => {
    const problem = derivationProblem(many, "sum", "title", FAR);
    expect(problem).toContain("title");
    expect(problem).toContain("integer or float");
    // The aggregation is named as a person would read it, not as it is stored.
    expect(problem).toContain("Sum");
  });

  it("catches a property invalidated by switching the aggregation", () => {
    // The picker narrows the list, so this is the state somebody reaches by
    // choosing `title` under `count_distinct` and then switching to `max`.
    expect(derivationProblem(many, "max", "title", FAR)).not.toBeNull();
    expect(derivationProblem(many, "exact_cardinality", "title", FAR)).toBeNull();
  });

  it("does not guess when the far type has not been read", () => {
    // **A missing list is not a verdict.** The editor fetches the far type, so
    // an empty list means "not yet" rather than "no properties" - and refusing
    // on it would put a sentence about types in front of somebody whose form
    // is still loading. The server checks it either way.
    expect(derivationProblem(many, "sum", "title")).toBeNull();
    expect(derivationProblem(many, "sum", "title", [])).toBeNull();
  });
});
