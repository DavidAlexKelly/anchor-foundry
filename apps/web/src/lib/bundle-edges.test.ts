/** What a page loads before it draws (§992).
 *
 * The widget table (`canvas/widgets.tsx`, every Workshop widget) and Monaco
 * are most of the platform's JavaScript. A page that does not render a
 * module or an editor reaches them only through a dynamic import, which
 * loads when one is shown. One static import anywhere under such a page puts
 * them back on its first load - the Explorer was 447 kB that way - and
 * nothing else would notice. These walk each page's static imports and hold
 * that neither is among them. */
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");

/** `import x from "y"` and `export { x } from "y"`, not `import type`, and
 * not `import("y")`, which is the dynamic edge this is about. */
const STATIC = /^\s*(?:import|export)\s+(?!type\s)(?:[^;"']*?\sfrom\s+)?["']([^"']+)["']/gm;

function resolveImport(from: string, spec: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) base = join(SRC, spec.slice(2));
  else if (spec.startsWith(".")) base = resolve(dirname(from), spec);
  else return null; // a package: not this repository's to split
  const candidates = [base, `${base}.ts`, `${base}.tsx`, join(base, "index.ts"), join(base, "index.tsx")];
  return candidates.find((c) => existsSync(c) && statSync(c).isFile()) ?? null;
}

function specifiersOf(file: string): string[] {
  return [...readFileSync(file, "utf8").matchAll(STATIC)].flatMap((m) => (m[1] ? [m[1]] : []));
}

/** Every file, and every package, a page reaches by static imports. */
function reach(page: string): { files: Set<string>; packages: Set<string> } {
  const files = new Set<string>();
  const packages = new Set<string>();
  const todo = [join(SRC, page)];
  while (todo.length) {
    const file = todo.pop()!;
    if (files.has(file)) continue;
    files.add(file);
    for (const spec of specifiersOf(file)) {
      const next = resolveImport(file, spec);
      if (next) todo.push(next);
      else if (!spec.startsWith(".") && !spec.startsWith("@/")) packages.add(spec);
    }
  }
  return { files, packages };
}

const WIDGETS = join(SRC, "components/canvas/widgets.tsx");
const SETTINGS = join(SRC, "components/canvas/widget-settings.tsx");
const BASEMAP = join(SRC, "components/canvas/basemap.ts");

describe("pages that do not render a module load without the widget table", () => {
  it.each([
    "app/(app)/r/[resourceId]/page.tsx",
    "app/(platform)/[workspace]/explore/page.tsx",
    "app/(platform)/[workspace]/[project]/objects/[typeId]/page.tsx",
    "components/object-view.tsx",
  ])("%s", (page) => {
    const { files, packages } = reach(page);
    expect(files.has(WIDGETS)).toBe(false);
    expect([...packages].filter((p) => p.startsWith("monaco-editor"))).toEqual([]);
  });

  it("and a module's reader loads the widgets without their settings panels (§995)", () => {
    for (const page of [
      "components/canvas/widgets.tsx",
      "components/canvas/published-module.tsx",
      "app/kiosk/page.tsx",
      "app/(platform)/[workspace]/apps/[appId]/page.tsx",
    ]) {
      expect(reach(page).files.has(SETTINGS), page).toBe(false);
    }
  });

  it("and no page loads the map's basemap before a map is drawn (§999)", () => {
    for (const page of [
      "app/(platform)/[workspace]/explore/page.tsx",
      "app/(platform)/[workspace]/[project]/objects/[typeId]/page.tsx",
      "components/canvas/published-module.tsx",
      "components/canvas/map.tsx",
    ]) {
      expect(reach(page).files.has(BASEMAP), page).toBe(false);
    }
  });

  it("and the walk does find it where it is meant to be", () => {
    // Without this, a walk that found nothing would pass everything above.
    expect(reach("components/configured-object-view.tsx").files.has(WIDGETS)).toBe(true);
    expect(reach("components/applications/workshop-app.tsx").files.has(WIDGETS)).toBe(true);
    expect(reach("components/code-editor.tsx").packages.has("monaco-editor")).toBe(true);
    expect(reach("components/canvas/widget-settings.tsx").files.has(WIDGETS)).toBe(true);
    // The builder has its panels before a widget can be selected.
    expect(reach("components/applications/workshop-app.tsx").files.has(SETTINGS)).toBe(true);
  });
});
