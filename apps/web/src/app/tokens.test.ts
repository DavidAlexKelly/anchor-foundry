import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/** Every custom property `globals.css` reads must be one it defines.
 *
 * **A CSS variable is the one reference in this codebase with no compiler
 * behind it.** `var(--surface)` where nothing declares `--surface` is not an
 * error anywhere: the declaration is simply dropped, so a `background` goes
 * transparent and a `border-top` draws no line. Nothing fails, nothing logs,
 * and the page looks *almost* right - which is why it survived four times.
 *
 * The file already carried a comment about it, written the first time
 * (`--panel, not --surface`). §219 found `--rule`, `--border`, `--surface` and
 * `--muted` all still being referenced by the state bar and the layout
 * template picker, and reached for two of the same invented names itself. A
 * comment is a warning to whoever reads it; this is the check that does not
 * depend on being read.
 */

const CSS = readFileSync(
  join(__dirname, "globals.css"),
  "utf8",
);

/** Names declared as `--x: value`, anywhere - including inside the media and
 * `[data-*]` blocks that redefine the palette, since a token defined only
 * there is still defined for the subtree that uses it. */
function declared(css: string): Set<string> {
  return new Set([...css.matchAll(/(--[a-z0-9-]+)\s*:/gi)].map((m) => m[1] as string));
}

/** Names read as `var(--x)` **with no fallback**. A fallback is the author
 * saying what happens when the token is absent, so `var(--muted-bg, #c9d1d9)`
 * is a deliberate optional read rather than a typo. */
function readWithoutFallback(css: string): Set<string> {
  return new Set(
    [...css.matchAll(/var\(\s*(--[a-z0-9-]+)\s*\)/gi)].map((m) => m[1] as string),
  );
}

describe("globals.css custom properties", () => {
  it("defines every token it reads without a fallback", () => {
    const defined = declared(CSS);
    const used = [...readWithoutFallback(CSS)].sort();
    // The vacuity guard. A scan that matches nothing passes every assertion
    // below it, and this repo has met that failure more than once.
    expect(used.length).toBeGreaterThanOrEqual(15);
    expect(used.filter((name) => !defined.has(name))).toEqual([]);
  });

  it("has a fallback wherever it reads an undeclared token deliberately", () => {
    // The other direction, and the reason the check above excludes fallbacks:
    // it must stay true that the *only* undeclared names in the file are ones
    // written with an explicit fallback. Without this, "add a fallback" would
    // be a way to silence the check above rather than a decision.
    const defined = declared(CSS);
    const withFallback = [...CSS.matchAll(/var\(\s*(--[a-z0-9-]+)\s*,/gi)].map((m) => m[1] as string);
    const undeclaredFallbacks = [...new Set(withFallback)]
      .filter((name) => !defined.has(name))
      .sort();
    // `--muted-bg` is the one: the template picker's cell colour, which has no
    // token because the shade is specific to that drawing. Listed rather than
    // pattern-matched away, so a second one is a decision somebody makes.
    expect(undeclaredFallbacks).toEqual(["--muted-bg"]);
  });
});
