import { describe, expect, it } from "vitest";
import { summarise, visibleProperties } from "./object-properties";
import type { ObjectTypeProperty } from "@/lib/types";

function prop(
  api_name: string,
  visibility: ObjectTypeProperty["visibility"] = "normal",
  display_name = "",
): ObjectTypeProperty {
  return {
    id: api_name,
    api_name,
    display_name,
    data_type: "string",
    required: false,
    description: "",
    sort_order: 0,
    visibility,
    value_format: null,
  };
}

describe("visibleProperties", () => {
  it("drops hidden properties entirely", () => {
    const { prominent, normal } = visibleProperties([
      prop("name", "prominent"),
      prop("region"),
      prop("secret", "hidden"),
    ]);
    expect(prominent.map((p) => p.api_name)).toEqual(["name"]);
    expect(normal.map((p) => p.api_name)).toEqual(["region"]);
  });

  it("keeps the object type's own order within each group", () => {
    // A view that re-sorted would disagree with the Ontology Manager about
    // what the type looks like.
    const { normal } = visibleProperties([prop("z"), prop("a"), prop("m")]);
    expect(normal.map((p) => p.api_name)).toEqual(["z", "a", "m"]);
  });
});

describe("summarise", () => {
  const properties = [
    prop("region"),
    prop("name", "prominent", "Name"),
    prop("secret", "hidden"),
    prop("owner"),
  ];
  const instance = {
    properties: { region: "north", name: "Alpha", secret: "DO NOT SHOW", owner: "ada" },
  };

  it("never shows a hidden property", () => {
    // The bug this rule was extracted for: the link list read straight off
    // `instance.properties`, so a property somebody marked hidden appeared
    // next to every linked object that had one.
    expect(summarise(instance, properties)).not.toContain("DO NOT SHOW");
    expect(summarise(instance, properties)).not.toContain("secret");
  });

  it("leads with prominent, whatever order the type declares", () => {
    // `region` is declared first; `name` is what the type says identifies one
    // of these (p.10), so it goes first.
    expect(summarise(instance, properties).indexOf("Name: Alpha")).toBe(0);
  });

  it("uses the display name when there is one", () => {
    expect(summarise(instance, properties)).toContain("Name: Alpha");
    expect(summarise(instance, properties)).toContain("region: north");
  });

  it("stops at the limit", () => {
    expect(summarise(instance, properties, 2).split(" · ")).toHaveLength(2);
  });

  it("skips empty values rather than counting them against the limit", () => {
    const sparse = { properties: { region: "", name: null, owner: "ada" } };
    expect(summarise(sparse, properties, 2)).toBe("owner: ada");
  });

  it("ignores a stored key the type no longer declares", () => {
    // An instance can carry one (§38 makes that possible) and a summary that
    // read the instance would show a property the ontology has never heard of.
    const stale = { properties: { name: "Alpha", removed_long_ago: "still here" } };
    expect(summarise(stale, properties)).toBe("Name: Alpha");
  });

  it("is empty when nothing may be shown", () => {
    expect(summarise({ properties: { secret: "x" } }, [prop("secret", "hidden")])).toBe("");
  });
});
