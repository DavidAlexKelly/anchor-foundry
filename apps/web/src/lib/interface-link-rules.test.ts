import { describe, expect, it } from "vitest";
import { generatedName } from "./interface-link-rules";

describe("the generated parameter's name (§762; p.63)", () => {
  it("is the link's name when that is free", () => {
    expect(generatedName("desk", ["priority"])).toBe("desk");
  });

  it("takes the first free number otherwise", () => {
    expect(generatedName("desk", ["desk"])).toBe("desk_2");
    expect(generatedName("desk", ["desk", "desk_2", "desk_3"])).toBe("desk_4");
    expect(generatedName("desk", ["desk", "desk_3"])).toBe("desk_2");
  });
});
