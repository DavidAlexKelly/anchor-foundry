import { describe, expect, it } from "vitest";

import {
  MAX_DEPTH, atPath, childrenOf, depthOf, grouped, isGroup, newCondition, renamed, withAdded,
  withAt, withoutAt,
} from "./criterion-logic";

const cond = (parameter: string) => ({
  left: { kind: "parameter", parameter }, operator: "is", right: { kind: "value", value: 1 },
});
const tree = {
  logic: "all",
  conditions: [cond("a"), { logic: "any", conditions: [cond("b"), cond("c")] }],
};

describe("p.56's logical operators in the editor (§643)", () => {
  it("tells a group from a condition", () => {
    expect(isGroup(tree)).toBe(true);
    expect(isGroup(cond("a"))).toBe(false);
    expect(isGroup(null)).toBe(false);
    expect(childrenOf({ logic: "all", conditions: "x" })).toEqual([]);
    expect(childrenOf({ logic: "all", conditions: [null] })).toEqual([{}]);
  });

  it("finds and replaces a node by its path", () => {
    expect(atPath(tree, [])).toBe(tree);
    expect(atPath(tree, [1, 0])).toEqual(cond("b"));
    expect(atPath(tree, [0, 0])).toBeUndefined();
    expect(atPath(tree, [5])).toBeUndefined();
    const next = withAt(tree, [1, 1], cond("z"));
    expect(atPath(next, [1, 1])).toEqual(cond("z"));
    expect(atPath(next, [1, 0])).toEqual(cond("b"));
    expect(atPath(next, [0])).toEqual(cond("a"));
    expect(withAt(tree, [], cond("r"))).toEqual(cond("r"));
  });

  it("takes a node out, but never a group's last condition", () => {
    expect(childrenOf(atPath(withoutAt(tree, [1, 0]), [1])!)).toEqual([cond("c")]);
    const lone = { logic: "all", conditions: [cond("a")] };
    expect(withoutAt(lone, [0])).toBe(lone);
    expect(withoutAt(tree, [])).toBe(tree);
  });

  it("adds a condition or a group, while there is room to nest", () => {
    const added = withAdded(tree, [1], "condition");
    expect(childrenOf(atPath(added, [1])!)).toHaveLength(3);
    expect(atPath(added, [1, 2])).toEqual(newCondition());
    const nested = withAdded(tree, [], "group");
    expect(atPath(nested, [2])).toEqual({ logic: "all", conditions: [newCondition()] });
    // A condition is not a group to add to.
    expect(withAdded(tree, [0], "condition")).toBe(tree);
    // The deepest group takes conditions and no more groups.
    let deep: Record<string, unknown> = { logic: "all", conditions: [cond("a")] };
    const path: number[] = [];
    for (let d = 1; d < MAX_DEPTH; d++) {
      deep = withAdded(deep, path, "group");
      path.push(childrenOf(atPath(deep, path)!).length - 1);
    }
    expect(depthOf(path)).toBe(MAX_DEPTH);
    expect(withAdded(deep, path, "group")).toBe(deep);
    expect(childrenOf(atPath(withAdded(deep, path, "condition"), path)!)).toHaveLength(2);
  });

  it("wraps a lone condition so more can join it", () => {
    expect(grouped(cond("a"))).toEqual({ logic: "all", conditions: [cond("a")] });
    expect(grouped(tree)).toBe(tree);
  });

  it("renames a parameter wherever the tree reads it", () => {
    const both = { logic: "none", conditions: [
      { left: { kind: "parameter", parameter: "b" }, operator: "is",
        right: { kind: "parameter", parameter: "b" } },
      cond("c"),
    ] };
    const next = renamed({ logic: "all", conditions: [cond("b"), both] }, "b", "bee");
    expect(atPath(next, [0])).toEqual(cond("bee"));
    expect(atPath(next, [1, 0])).toEqual({ left: { kind: "parameter", parameter: "bee" },
      operator: "is", right: { kind: "parameter", parameter: "bee" } });
    expect(atPath(next, [1, 1])).toEqual(cond("c"));
    // A current-user side is not a parameter, whatever it is called.
    const user = { left: { kind: "current_user", parameter: "b" }, operator: "is" };
    expect(renamed(user, "b", "x")).toEqual(user);
  });
});
