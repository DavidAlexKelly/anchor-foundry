import { describe, expect, it } from "vitest";
import {
  NOT_INTERFACE_TYPES, blankProperty, candidates, draftProblem, extendable,
  implementationLabel, interfacePropertyTypes, suggestMapping,
  toInterfaceApiName, toPropertyApiName, unmappedRequired,
} from "./interfaces";
import type {
  InterfaceProperty, InterfaceSummary, PropertyDataType,
} from "./types";

function prop(
  api_name: string,
  data_type: PropertyDataType,
  required = true,
): InterfaceProperty {
  return { api_name, display_name: api_name, description: "", data_type, required };
}

function summary(id: string, api_name: string): InterfaceSummary {
  return {
    id,
    api_name,
    display_name: api_name,
    description: "",
    status: "experimental",
    deprecation: null,
    property_count: 0,
    implementation_count: 0,
    created_at: "",
    updated_at: "",
  };
}

describe("toInterfaceApiName", () => {
  // p.60's own examples are the specification here.
  it("names an interface the way p.60 names one", () => {
    expect(toInterfaceApiName("Inspectable")).toBe("Inspectable");
    expect(toInterfaceApiName("Schedulable Resource")).toBe("SchedulableResource");
    expect(toInterfaceApiName("military-asset")).toBe("MilitaryAsset");
  });

  it("keeps the letters already inside a word", () => {
    // Lowercasing first would turn `MedicalDevice` into `Medicaldevice`, which
    // is a different name from the one that was typed.
    expect(toInterfaceApiName("MedicalDevice")).toBe("MedicalDevice");
  });

  it("gives up rather than propose a name the server refuses", () => {
    // `^[A-Za-z]` — capitalising cannot rescue a name starting with a digit,
    // and offering `3DAsset` would be offering a save that fails.
    expect(toInterfaceApiName("3D Asset")).toBe("");
    expect(toInterfaceApiName("!!!")).toBe("");
  });

  it("stays inside the server's hundred characters", () => {
    expect(toInterfaceApiName("a".repeat(200))).toHaveLength(100);
  });
});

describe("toPropertyApiName", () => {
  it("is a property's rule, not an interface's", () => {
    expect(toPropertyApiName("Last Inspection Date")).toBe("last_inspection_date");
    expect(toPropertyApiName("MedicalDevice")).toBe("medicaldevice");
  });

  it("gives up on a name that cannot start a property", () => {
    expect(toPropertyApiName("2nd check")).toBe("");
  });
});

describe("draftProblem", () => {
  const ok = {
    display_name: "Inspectable",
    api_name: "Inspectable",
    properties: [
      { ...blankProperty(), api_name: "last_inspection_date", data_type: "date" as const },
    ],
  };

  it("passes a draft the server would take", () => {
    expect(draftProblem(ok)).toBeNull();
  });

  it("wants a name", () => {
    expect(draftProblem({ ...ok, display_name: "   " })).toBe("An interface needs a name.");
  });

  it("wants an API name the server's pattern accepts", () => {
    expect(draftProblem({ ...ok, api_name: "" })).toContain("must start with a letter");
    expect(draftProblem({ ...ok, api_name: "3Things" })).toContain("must start with a letter");
    expect(draftProblem({ ...ok, api_name: "has-a-dash" })).toContain("must start with a letter");
  });

  it("wants every property named", () => {
    expect(
      draftProblem({ ...ok, properties: [blankProperty()] }),
    ).toBe("Every property needs a name.");
  });

  it("refuses a property name shaped like an interface's", () => {
    // The two rules genuinely differ — `Inspectable` is a legal interface name
    // and an illegal property name — so a single check would let one through.
    expect(
      draftProblem({
        ...ok,
        properties: [{ ...blankProperty(), api_name: "LastInspection" }],
      }),
    ).toContain("lowercase");
  });

  it("catches the same name declared twice", () => {
    const twice = { ...blankProperty(), api_name: "status" };
    expect(draftProblem({ ...ok, properties: [twice, { ...twice }] })).toBe(
      "Two properties are both called status.",
    );
  });
});

describe("extendable", () => {
  const all = [summary("a", "Trackable"), summary("b", "Schedulable")];

  it("offers everything when nothing is being edited yet", () => {
    expect(extendable(all, undefined).map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("does not offer an interface itself", () => {
    // The one cycle a list of summaries can see, and the one most likely to be
    // clicked by accident.
    expect(extendable(all, "a").map((i) => i.id)).toEqual(["b"]);
  });
});

describe("interfacePropertyTypes", () => {
  it("is a subtraction, so a new base type arrives here too", () => {
    const all = ["string", "date", "geopoint"] as PropertyDataType[];
    expect(interfacePropertyTypes(all)).toEqual(all);
  });

  it("holds back struct, whose promise base types cannot check", () => {
    const all = ["string", "struct", "date"] as PropertyDataType[];
    expect(interfacePropertyTypes(all)).toEqual(["string", "date"]);
    expect(NOT_INTERFACE_TYPES).toContain("struct");
  });
});

describe("suggestMapping", () => {
  const effective = [prop("last_inspection_date", "date"), prop("status", "string")];

  it("matches on name when the base type agrees", () => {
    expect(
      suggestMapping(effective, { last_inspection_date: "date", status: "string" }),
    ).toEqual({ last_inspection_date: "last_inspection_date", status: "status" });
  });

  it("suggests nothing when a name matches and the type does not", () => {
    // The case where agreeing names are a coincidence. Filling it in would
    // turn a question into a refusal.
    expect(suggestMapping(effective, { last_inspection_date: "string" })).toEqual({});
  });

  it("suggests nothing for a property the type does not have", () => {
    expect(suggestMapping(effective, { something_else: "date" })).toEqual({});
  });
});

describe("candidates", () => {
  it("offers only the type's properties of that base type, in name order", () => {
    // **Declared out of order on purpose.** `Object.keys` preserves insertion
    // order, so a candidate list built from a type whose date columns happen
    // to be declared alphabetically would pass with the sort deleted — and a
    // dropdown that follows the order somebody happened to declare properties
    // in is a dropdown nobody can scan.
    expect(
      candidates(prop("when", "date"), {
        made_on: "date",
        name: "string",
        checked_on: "date",
      }),
    ).toEqual(["checked_on", "made_on"]);
  });

  it("offers nothing rather than something of the wrong type", () => {
    expect(candidates(prop("when", "date"), { name: "string" })).toEqual([]);
  });
});

describe("unmappedRequired", () => {
  const effective = [
    prop("last_inspection_date", "date"),
    prop("inspection_status", "string"),
    prop("notes", "string", false),
  ];

  it("names the required properties nothing answers, in declaration order", () => {
    expect(unmappedRequired(effective, {})).toEqual([
      "last_inspection_date",
      "inspection_status",
    ]);
  });

  it("leaves an optional property out, which is why `required` exists", () => {
    expect(
      unmappedRequired(effective, {
        last_inspection_date: "checked_on",
        inspection_status: "state",
      }),
    ).toEqual([]);
  });

  it("counts an empty mapping value as unmapped", () => {
    // A select set back to "—" writes nothing rather than "", but a stale
    // mapping loaded from the server could carry one, and an empty string is
    // not a property name.
    expect(unmappedRequired([prop("a", "string")], { a: "" })).toEqual(["a"]);
  });
});

describe("implementationLabel", () => {
  it("says what an interface nothing implements has not done yet", () => {
    expect(implementationLabel(0)).toBe("Nothing yet");
  });

  it("counts, and agrees with itself about the plural", () => {
    expect(implementationLabel(1)).toBe("1 object type");
    expect(implementationLabel(3)).toBe("3 object types");
  });
});
