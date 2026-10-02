import { describe, expect, it } from "vitest";

import { describeConflict, rebase } from "./module-merge";

/** Rebasing a module branch (Foundry `workshop` p.619-621).
 *
 * > "Workshop auto-merges changes that do not overlap. A change is only
 * > flagged as a merge conflict when the same widget, variable, section, or
 * > layout position was edited on both main and your branch" (p.620)
 *
 * The tests come in the two halves that sentence has: what merges without a
 * word, and each of p.620's three examples of what does not.
 */

const text = (value: string, parent = "ROOT") => ({
  type: { resolvedName: "CanvasText" }, props: { text: value }, parent, nodes: [],
});
const section = (kids: string[], parent = "ROOT", props: object = {}) => ({
  type: { resolvedName: "CanvasFlowSection" }, isCanvas: true, props, parent, nodes: kids,
});

function doc(nodes: Record<string, object>, over: object = {}) {
  const top = Object.entries(nodes).filter(([, n]) => (n as { parent?: string }).parent === "ROOT");
  return {
    format: 2,
    layout: {
      ROOT: { type: { resolvedName: "CanvasContainer" }, isCanvas: true, props: {},
              nodes: top.map(([id]) => id) },
      ...nodes,
    },
    variables: {},
    events: {},
    ...over,
  };
}

type Node = { props?: Record<string, unknown>; nodes?: string[]; parent?: string };
type Layout = Record<string, Node>;
const layoutOf = (d: Record<string, unknown>) => d.layout as Layout;
/** One node of a merged layout, which the test asserts is there. */
const at = (d: Record<string, unknown>, id: string): Node => {
  const node = layoutOf(d)[id];
  if (!node) throw new Error(`no node ${id}`);
  return node;
};

describe("changes that do not overlap", () => {
  it("takes a change made only on the branch", () => {
    const base = doc({ a: text("one"), b: text("two") });
    const main = base;
    const branch = doc({ a: text("ONE"), b: text("two") });
    const { document, conflicts } = rebase(base, main, branch);
    expect(conflicts).toEqual([]);
    expect(at(document, "a").props).toEqual({ text: "ONE" });
  });

  it("keeps a change made only on main", () => {
    const base = doc({ a: text("one"), b: text("two") });
    const main = doc({ a: text("one"), b: text("TWO") });
    const { document, conflicts } = rebase(base, main, base);
    expect(conflicts).toEqual([]);
    expect(at(document, "b").props).toEqual({ text: "TWO" });
  });

  it("takes both sides' edits to different widgets", () => {
    const base = doc({ a: text("one"), b: text("two") });
    const main = doc({ a: text("main"), b: text("two") });
    const branch = doc({ a: text("one"), b: text("branch") });
    const { document, conflicts } = rebase(base, main, branch);
    expect(conflicts).toEqual([]);
    expect(at(document, "a").props).toEqual({ text: "main" });
    expect(at(document, "b").props).toEqual({ text: "branch" });
  });

  it("keeps a widget each side added to the same page, in a sensible order", () => {
    const base = doc({ a: text("a") });
    const main = doc({ a: text("a"), m: text("from main") });
    const branch = doc({ a: text("a"), r: text("from branch") });
    const { document, conflicts } = rebase(base, main, branch);
    expect(conflicts).toEqual([]);
    expect(at(document, "ROOT").nodes).toEqual(["a", "r", "m"]);
  });

  it("puts a branch addition after the sibling it followed there", () => {
    const base = doc({ a: text("a"), b: text("b") });
    const main = doc({ m: text("m"), a: text("a"), b: text("b") });
    const branch = doc({ a: text("a"), r: text("r"), b: text("b") });
    const { document } = rebase(base, main, branch);
    expect(at(document, "ROOT").nodes).toEqual(["m", "a", "r", "b"]);
  });

  it("puts a branch addition with nothing before it first", () => {
    const base = doc({ a: text("a") });
    const main = doc({ a: text("a"), m: text("m") });
    const branch = doc({ r: text("r"), a: text("a") });
    expect(at(rebase(base, main, branch).document, "ROOT").nodes).toEqual(["r", "a", "m"]);
  });

  it("follows the nearest sibling before it, not the first", () => {
    const base = doc({ a: text("a"), b: text("b") });
    const main = doc({ m: text("m"), a: text("a"), b: text("b") });
    const branch = doc({ a: text("a"), b: text("b"), r: text("r") });
    expect(at(rebase(base, main, branch).document, "ROOT").nodes).toEqual(["m", "a", "b", "r"]);
  });

  it("takes a reorder made only on the branch", () => {
    const base = doc({ a: text("a"), b: text("b") });
    const branch = { ...base, layout: { ...layoutOf(base), ROOT: { ...at(base, "ROOT"), nodes: ["b", "a"] } } };
    const { document, conflicts } = rebase(base, base, branch);
    expect(conflicts).toEqual([]);
    expect(at(document, "ROOT").nodes).toEqual(["b", "a"]);
  });

  it("takes a widget deleted on the branch and untouched on main", () => {
    const base = doc({ a: text("a"), b: text("b") });
    const branch = doc({ a: text("a") });
    const { document, conflicts } = rebase(base, base, branch);
    expect(conflicts).toEqual([]);
    expect(Object.keys(layoutOf(document))).not.toContain("b");
    expect(at(document, "ROOT").nodes).toEqual(["a"]);
  });

  it("takes a move made only on the branch", () => {
    const base = doc({ s: section([]), a: text("a") });
    const branch = doc({ s: section(["a"]), a: text("a", "s") });
    const { document, conflicts } = rebase(base, base, branch);
    expect(conflicts).toEqual([]);
    expect(at(document, "a").parent).toBe("s");
    expect(at(document, "s").nodes).toEqual(["a"]);
    expect(at(document, "ROOT").nodes).toEqual(["s"]);
  });

  it("does not call the same edit on both sides a conflict", () => {
    const base = doc({ a: text("one") });
    const both = doc({ a: text("same") });
    expect(rebase(base, both, both).conflicts).toEqual([]);
  });

  it("merges variables, events and settings an entry at a time", () => {
    const base = doc({}, { variables: { v1: { label: "One" } }, routing: { enabled: false } });
    const main = doc({}, { variables: { v1: { label: "One" }, v2: { label: "Main's" } },
                           routing: { enabled: false } });
    const branch = doc({}, { variables: { v1: { label: "One!" } }, routing: { enabled: true } });
    const { document, conflicts } = rebase(base, main, branch);
    expect(conflicts).toEqual([]);
    expect(document.variables).toEqual({ v1: { label: "One!" }, v2: { label: "Main's" } });
    expect(document.routing).toEqual({ enabled: true });
  });

  it("ignores key order, which a round trip can change", () => {
    const base = doc({ a: text("one") });
    const reordered = JSON.parse(JSON.stringify(base));
    const node = reordered.layout.a;
    reordered.layout.a = { props: node.props, nodes: node.nodes, parent: node.parent, type: node.type };
    const branch = doc({ a: text("branch") });
    expect(rebase(base, reordered, branch).conflicts).toEqual([]);
  });
});

describe("p.620's conflicts", () => {
  it("a widget modified on both main and the branch", () => {
    const base = doc({ a: text("one") });
    const main = doc({ a: text("main") });
    const branch = doc({ a: text("branch") });
    const { document, conflicts } = rebase(base, main, branch);
    expect(conflicts).toEqual([
      { key: "layout:a", section: "layout", id: "a", label: "Text (a)", kind: "changed" },
    ]);
    // Unchosen, the conflict takes main's side - and is still listed.
    expect(at(document, "a").props).toEqual({ text: "main" });
    const chosen = rebase(base, main, branch, { "layout:a": "branch" });
    expect(at(chosen.document, "a").props).toEqual({ text: "branch" });
    expect(chosen.conflicts).toHaveLength(1);
  });

  it("a variable modified on both", () => {
    const base = doc({}, { variables: { v: { label: "V", value: 1 } } });
    const main = doc({}, { variables: { v: { label: "V", value: 2 } } });
    const branch = doc({}, { variables: { v: { label: "V", value: 3 } } });
    const { conflicts, document } = rebase(base, main, branch, { "variables:v": "branch" });
    expect(conflicts.map((c) => [c.key, c.kind, c.label])).toEqual([
      ["variables:v", "changed", "V (v)"],
    ]);
    expect(document.variables).toEqual({ v: { label: "V", value: 3 } });
  });

  it("a section deleted on main and edited on the branch", () => {
    const base = doc({ s: section(["a"]), a: text("a", "s") });
    const main = doc({});
    const branch = doc({ s: section(["a", "b"]), a: text("a", "s"), b: text("added", "s") });
    const { conflicts, document } = rebase(base, main, branch);
    expect(conflicts.map((c) => [c.key, c.kind])).toEqual([["layout:s", "deleted-on-main"]]);
    // Main's side: the section is gone, and so is what the branch put in it.
    expect(Object.keys(layoutOf(document)).sort()).toEqual(["ROOT"]);
    const kept = rebase(base, main, branch, { "layout:s": "branch" }).document;
    expect(at(kept, "s").nodes).toEqual(["b"]);
    expect(at(kept, "ROOT").nodes).toEqual(["s"]);
  });

  it("a widget deleted on the branch and edited on main", () => {
    const base = doc({ a: text("one") });
    const main = doc({ a: text("main") });
    const branch = doc({});
    const { conflicts, document } = rebase(base, main, branch);
    expect(conflicts.map((c) => c.kind)).toEqual(["deleted-on-branch"]);
    expect(at(document, "a").props).toEqual({ text: "main" });
    // Kept, so still on the page - although the branch's list for the page,
    // the one that changed, no longer names it.
    expect(at(document, "ROOT").nodes).toEqual(["a"]);
    const gone = rebase(base, main, branch, { "layout:a": "branch" }).document;
    expect(layoutOf(gone)["a"]).toBeUndefined();
    expect(at(gone, "ROOT").nodes).toEqual([]);
  });

  it("a widget moved from A to B on main and from A to C on the branch", () => {
    const base = doc({ s1: section(["w"]), s2: section([]), s3: section([]), w: text("w", "s1") });
    const main = doc({ s1: section([]), s2: section(["w"]), s3: section([]), w: text("w", "s2") });
    const branch = doc({ s1: section([]), s2: section([]), s3: section(["w"]), w: text("w", "s3") });
    const { conflicts, document } = rebase(base, main, branch);
    expect(conflicts.map((c) => [c.key, c.kind])).toEqual([["layout:w@position", "moved"]]);
    expect(at(document, "w").parent).toBe("s2");
    expect(at(document, "s2").nodes).toEqual(["w"]);
    expect(at(document, "s3").nodes).toEqual([]);
    const theirs = rebase(base, main, branch, { "layout:w@position": "branch" }).document;
    expect(at(theirs, "w").parent).toBe("s3");
    expect(at(theirs, "s3").nodes).toEqual(["w"]);
    expect(at(theirs, "s2").nodes).toEqual([]);
  });

  it("a widget deleted on main and moved on the branch", () => {
    const base = doc({ s: section([]), w: text("w") });
    const main = doc({ s: section([]) });
    const branch = doc({ s: section(["w"]), w: text("w", "s") });
    expect(rebase(base, main, branch).conflicts.map((c) => [c.key, c.kind])).toEqual([
      ["layout:w", "deleted-on-main"],
    ]);
  });

  it("p.621's example: a column added on each side to one table", () => {
    const table = (columns: string) => ({
      type: { resolvedName: "CanvasObjectTable" }, props: { columns }, parent: "ROOT", nodes: [],
    });
    const base = doc({ t: table("id") });
    const main = doc({ t: table("id,departure_airport_code") });
    const branch = doc({ t: table("id,action_required") });
    const { conflicts } = rebase(base, main, branch);
    expect(conflicts.map((c) => [c.label, c.kind])).toEqual([["ObjectTable (t)", "changed"]]);
  });

  it("a module-wide setting changed on both", () => {
    const base = doc({}, { routing: { enabled: false } });
    const main = doc({}, { routing: { enabled: true, x: 1 } });
    const branch = doc({}, { routing: { enabled: true, x: 2 } });
    expect(rebase(base, main, branch).conflicts.map((c) => c.key)).toEqual(["settings:routing"]);
  });
});

describe("the conflict list", () => {
  it("is in key order, whatever order the sections were merged in", () => {
    const base = doc({ a: text("one") }, { routing: { enabled: false } });
    const main = doc({ a: text("main") }, { routing: { enabled: true, x: 1 } });
    const branch = doc({ a: text("branch") }, { routing: { enabled: true, x: 2 } });
    expect(rebase(base, main, branch).conflicts.map((c) => c.key)).toEqual([
      "layout:a", "settings:routing",
    ]);
  });
});

describe("describeConflict", () => {
  it("says each kind in words", () => {
    const of = (kind: Parameters<typeof describeConflict>[0]["kind"]) =>
      describeConflict({ key: "k", section: "layout", id: "a", label: "A", kind });
    expect(of("changed")).toBe("edited on main and on this branch");
    expect(of("deleted-on-main")).toBe("deleted on main and edited on this branch");
    expect(of("deleted-on-branch")).toBe("deleted on this branch and edited on main");
    expect(of("moved")).toBe("moved to different places on main and on this branch");
  });
});
