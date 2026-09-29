import { describe, expect, it } from "vitest";

import {
  NO_JOIN_TABLE, draftOf, isChosen, joinDescription, joinTablePayload, joinTableProblem,
} from "./link-join-table";

const label = (p: string) => (p === "$primary_key" ? "primary key" : p);
const whole = { dataset: "d1", from: "flight", to: "aircraft" };

describe("p.197's join table in the link dialogs (§552)", () => {
  it("has nothing to say about a link with no join table", () => {
    expect(joinTableProblem(NO_JOIN_TABLE, "one_to_many")).toBeNull();
    expect(isChosen(NO_JOIN_TABLE)).toBe(false);
  });

  it("backs only a many-to-many link", () => {
    // p.197: "Join table dataset: For "many-to-many" cardinality link types."
    expect(joinTableProblem(whole, "one_to_many")).toMatch(/many-to-many/);
    expect(joinTableProblem(whole, "many_to_many")).toBeNull();
  });

  it("needs the dataset and both columns", () => {
    for (const part of [{ dataset: "" }, { from: "" }, { to: "" }]) {
      expect(joinTableProblem({ ...whole, ...part }, "many_to_many")).toMatch(/each end/);
      expect(isChosen({ ...whole, ...part })).toBe(true);
    }
  });

  it("gives each end its own column", () => {
    // p.35: "A column can only be mapped to one primary key."
    expect(joinTableProblem({ ...whole, to: "flight" }, "many_to_many")).toMatch(/own column/);
  });

  it("sends all three, or clears all three", () => {
    expect(joinTablePayload(whole)).toEqual({
      join_dataset_id: "d1", join_from_column: "flight", join_to_column: "aircraft" });
    expect(joinTablePayload({ ...whole, to: "" })).toEqual({
      join_dataset_id: null, join_from_column: null, join_to_column: null });
  });

  it("reads a link's join table back into the dialog", () => {
    expect(draftOf({ join_dataset_id: "d1", join_from_column: "flight",
      join_to_column: "aircraft" })).toEqual(whole);
    expect(draftOf({})).toEqual(NO_JOIN_TABLE);
  });

  it("says what each link joins on", () => {
    const none = { from_property: null, to_property: null };
    expect(joinDescription({ ...none, join_dataset_id: "d1", join_from_column: "flight",
      join_to_column: "aircraft" }, label)).toBe("join table: flight ↔ aircraft");
    // db 0115: the dataset deleted, its columns kept.
    expect(joinDescription({ ...none, join_dataset_id: null, join_from_column: "flight",
      join_to_column: "aircraft" }, label)).toMatch(/join table was deleted/);
    expect(joinDescription({ from_property: "customer_id", to_property: "$primary_key" }, label))
      .toBe("customer_id = primary key");
    expect(joinDescription(none, label)).toBe("not traversable");
  });
});
