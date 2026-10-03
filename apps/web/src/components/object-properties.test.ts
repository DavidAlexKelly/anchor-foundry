import { describe, expect, it } from "vitest";
import { asViewed, objectViewSections, summarise, visibleProperties } from "./object-properties";
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
    conditional_format: null,
    edit_only: false,
    derivation: null,
    struct_fields: null,
    array_of: null,
    reducers: null,
    shared_property_id: null,
    shared_property_api_name: null,
    value_type_id: null,
    effective_value_type_id: null,
    value_type_api_name: null,
    value_constraint: null,
    status: "experimental",
    deprecation: null,
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

describe("objectViewSections (§725; object-link-types p.250)", () => {
  const hinted = (api_name: string, hints: string[], visibility: ObjectTypeProperty["visibility"] = "normal") =>
    ({ ...prop(api_name, visibility), render_hints: hints });

  it("takes Keywords and Long text out of the table into their own sections", () => {
    const got = objectViewSections([
      hinted("title", ["keywords"], "prominent"),
      hinted("tags", ["keywords", "searchable"]),
      hinted("notes", ["long_text"]),
      hinted("both", ["keywords", "long_text"]),
      hinted("plain", ["searchable"]),
      prop("unhinted"),
      hinted("gone", ["keywords"], "hidden"),
    ]);
    const names = (ps: ObjectTypeProperty[]) => ps.map((p) => p.api_name);
    // Prominent keeps its card; hidden stays hidden; Keywords wins over Long text.
    expect(names(got.prominent)).toEqual(["title"]);
    expect(names(got.keywords)).toEqual(["tags", "both"]);
    expect(names(got.long)).toEqual(["notes"]);
    expect(names(got.normal)).toEqual(["plain", "unhinted"]);
  });
});

describe("asViewed (§725; p.249-250's Identifier)", () => {
  it("drops the formatter of an identifier, and only of one", () => {
    const formatted = { ...prop("code"), data_type: "integer" as const,
      value_format: { kind: "number" as const, grouping: true } as ObjectTypeProperty["value_format"] };
    expect(asViewed({ ...formatted, render_hints: ["identifier"] }).value_format).toBeNull();
    expect(asViewed({ ...formatted, render_hints: ["searchable"] }).value_format).toEqual(formatted.value_format);
    const bare = { ...prop("code"), render_hints: ["identifier"] };
    expect(asViewed(bare)).toBe(bare);
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
