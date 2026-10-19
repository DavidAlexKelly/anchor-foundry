/** An error a screen reader is told about (§1011).
 *
 * The platform shows a failure in one of two ways: `.form-error`, under the
 * control or form that failed, and `.state.error`, in place of a page or panel
 * that could not load. Both appear when something goes wrong, which a sighted
 * user sees and a screen reader user does not, unless the element is a live
 * region: `role="alert"` (or `role="status"` for the few that are news rather
 * than a failure). 198 of them were neither. This holds every one written as
 * a literal class to one of the two roles. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");

function tsx(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return tsx(path);
    return name.endsWith(".tsx") && !name.includes(".test.") ? [path] : [];
  });
}

const OPENING = /<[a-z]+\s[^<>]*className="(form-error|state error)"[^<>]*>/g;

describe("an error the page shows", () => {
  const found = tsx(SRC).flatMap((file) =>
    [...readFileSync(file, "utf8").matchAll(OPENING)].map((m) => ({
      where: `${relative(SRC, file)}: ${m[0].slice(0, 80)}`,
      tag: m[0],
    })),
  );

  it("is found where it is written - the walk is not empty", () => {
    expect(found.length).toBeGreaterThan(150);
  });

  it("is announced when it appears", () => {
    const silent = found.filter((f) => !/\srole="(alert|status)"/.test(f.tag)).map((f) => f.where);
    expect(silent).toEqual([]);
  });
});
