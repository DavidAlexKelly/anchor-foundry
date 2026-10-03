import { describe, expect, it } from "vitest";

import { ICONS, ICON_NAMES, iconNamed } from "./icons";
import { MAX_GLYPH } from "./object-type-icon";

/** §705's named icons. */

describe("ICONS", () => {
  it("has the column's default, which every older type holds", () => {
    expect(iconNamed("cube")?.label).toBe("Cube");
  });

  it("draws each on the 16-unit grid it is viewed through", () => {
    for (const name of ICON_NAMES) {
      const def = ICONS[name];
      expect(def.paths.length, name).toBeGreaterThan(0);
      for (const d of def.paths) {
        expect(d, name).toMatch(/^M/);
        // Absolute coordinates stay inside the 0-16 viewBox.
        const absolute = d.match(/[ML]\s*-?[\d.]+[ ,]-?[\d.]+/g) ?? [];
        for (const pair of absolute) {
          const [x, y] = pair.slice(1).trim().split(/[ ,]/).map(Number);
          expect(x, `${name} ${pair}`).toBeGreaterThanOrEqual(0);
          expect(x, `${name} ${pair}`).toBeLessThanOrEqual(16);
          expect(y, `${name} ${pair}`).toBeGreaterThanOrEqual(0);
          expect(y, `${name} ${pair}`).toBeLessThanOrEqual(16);
        }
      }
    }
  });

  it("names each longer than a typed glyph can be, so the two never collide", () => {
    // An icon setting holds a name or one or two typed characters; a
    // two-letter name would turn somebody's initials into a picture.
    for (const name of ICON_NAMES) expect(name.length, name).toBeGreaterThan(MAX_GLYPH);
  });

  it("names each in Foundry's kebab case, so stored names keep working", () => {
    for (const name of ICON_NAMES) expect(name).toMatch(/^[a-z]+(-[a-z]+)*$/);
  });

  it("labels each differently, since the picker is read by its labels", () => {
    const labels = ICON_NAMES.map((name) => ICONS[name].label);
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe("iconNamed", () => {
  it("reads a name with space round it", () => {
    expect(iconNamed(" airplane ")?.label).toBe("Airplane");
  });

  it("is nothing for a glyph, a stranger, a blank or an inherited key", () => {
    expect(iconNamed("🚢")).toBeNull();
    expect(iconNamed("shopping-cart")).toBeNull();
    expect(iconNamed("")).toBeNull();
    expect(iconNamed(null)).toBeNull();
    expect(iconNamed("constructor")).toBeNull();
  });
});
