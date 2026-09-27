import { describe, expect, it } from "vitest";

import { namesObject, settableLink } from "./link-rules";

const fk = {
  from_object_type_id: "order", to_object_type_id: "customer",
  from_property: "customer_id", to_property: "$primary_key", cardinality: "one_to_many" as const,
};
const joined = {
  from_object_type_id: "flight", to_object_type_id: "aircraft",
  from_property: null, to_property: null, cardinality: "many_to_many" as const,
  join_dataset_id: "d1",
};

describe("which links an action's link rules can set", () => {
  it("sets a foreign-key link from either end", () => {
    expect(settableLink(fk, "order")).toBe(true);
    expect(settableLink(fk, "customer")).toBe(true);
    expect(settableLink(fk, "product")).toBe(false);
  });

  it("does not set a link one foreign key cannot express", () => {
    expect(settableLink({ ...fk, cardinality: "many_to_many" }, "order")).toBe(false);
    expect(settableLink({ ...fk, from_property: "$primary_key" }, "order")).toBe(false);
    expect(settableLink({ ...fk, from_property: null }, "order")).toBe(false);
    expect(settableLink({ ...fk, to_property: null }, "customer")).toBe(false);
  });

  it("sets a many-to-many link through its join table, from either end (§553)", () => {
    expect(settableLink(joined, "flight")).toBe(true);
    expect(settableLink(joined, "aircraft")).toBe(true);
    expect(settableLink(joined, "crew")).toBe(false);
    expect(settableLink({ ...joined, join_dataset_id: null }, "flight")).toBe(false);
  });

  it("asks which object to link on a far side or a join table", () => {
    expect(namesObject(fk, "order")).toBe(false);
    expect(namesObject(fk, "customer")).toBe(true);
    expect(namesObject(joined, "flight")).toBe(true);
  });
});
