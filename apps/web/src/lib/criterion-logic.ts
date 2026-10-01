/**
 * p.56's logical operators over submission criteria (§643).
 *
 * > "A logical operator can be used to combine different conditions. Logical
 * > operators can also be nested to create even more complex logic and can
 * > require either all, any, or no conditions underneath it to be met to
 * > pass." (p.56)
 *
 * A criterion's config is a condition (`left`, `operator`, `right`) or a group
 * of them, `{ logic, conditions }`, nested up to `MAX_DEPTH` groups deep. Only
 * the root carries the failure message, as p.56 says. The server decides
 * whether one holds (`actions.check_criteria`); this is the shape the editor
 * builds, addressed by a path of indexes from the root.
 *
 * Pure.
 */

export type Config = Record<string, unknown>;

export const LOGIC = ["all", "any", "none"] as const;
export type Logic = (typeof LOGIC)[number];
export const LOGIC_LABELS: Record<Logic, string> = {
  all: "All of these",
  any: "Any of these",
  none: "None of these",
};
/** `actions.MAX_CRITERION_DEPTH`. */
export const MAX_DEPTH = 4;

export function isGroup(config: unknown): boolean {
  return !!config && typeof config === "object" && "logic" in (config as Config);
}

export function childrenOf(config: Config): Config[] {
  const list = config.conditions;
  return Array.isArray(list) ? list.map((c) => (c && typeof c === "object" ? c as Config : {})) : [];
}

/** A new condition, as the editor starts one: a parameter that must be
 * filled in. */
export function newCondition(): Config {
  return { left: { kind: "parameter", parameter: "" }, operator: "is_not", right: { kind: "none" } };
}

/** The node at a path of child indexes from the root, or undefined. */
export function atPath(root: Config, path: readonly number[]): Config | undefined {
  let node: Config | undefined = root;
  // A condition has no children, so a path through one finds nothing (a
  // group check here survived the sweep as equivalent).
  for (const at of path) node = node ? childrenOf(node)[at] : undefined;
  return node;
}

/** The root with the node at a path replaced. */
export function withAt(root: Config, path: readonly number[], next: Config): Config {
  if (path.length === 0) return next;
  const [first, ...rest] = path;
  const children = childrenOf(root);
  return { ...root, conditions: children.map((c, n) => (n === first ? withAt(c, rest, next) : c)) };
}

/** The root with the node at a path taken out of its group. A group keeps at
 * least one condition, since the server refuses an empty one: taking out the
 * last leaves the root unchanged. */
export function withoutAt(root: Config, path: readonly number[]): Config {
  if (path.length === 0) return root;
  const parent = atPath(root, path.slice(0, -1));
  if (!parent || childrenOf(parent).length <= 1) return root;
  const last = path[path.length - 1];
  return withAt(root, path.slice(0, -1), {
    ...parent, conditions: childrenOf(parent).filter((_, n) => n !== last),
  });
}

/** The root with a node added to the group at a path: a new condition, or a
 * new group holding one, while the nesting has room for it. */
export function withAdded(root: Config, path: readonly number[], kind: "condition" | "group"): Config {
  const parent = atPath(root, path);
  if (!parent || !isGroup(parent)) return root;
  if (kind === "group" && path.length + 1 >= MAX_DEPTH) return root;
  const added = kind === "group" ? { logic: "all", conditions: [newCondition()] } : newCondition();
  return withAt(root, path, { ...parent, conditions: [...childrenOf(parent), added] });
}

/** A root condition wrapped in an `all` group, so more can join it; a group
 * is returned as it is. */
export function grouped(root: Config): Config {
  return isGroup(root) ? root : { logic: "all", conditions: [root] };
}

/** How deep the node at a path sits: the root group is 1. */
export function depthOf(path: readonly number[]): number {
  return path.length + 1;
}

/** Every parameter renamed throughout the tree, so a rename in the editor
 * does not leave a condition naming the old one somewhere inside a group. */
export function renamed(config: Config, before: string, after: string): Config {
  if (isGroup(config)) {
    return { ...config, conditions: childrenOf(config).map((c) => renamed(c, before, after)) };
  }
  const next = { ...config };
  for (const key of ["left", "right"]) {
    const spec = config[key] as Config | undefined;
    if (spec && spec.kind === "parameter" && spec.parameter === before) {
      next[key] = { ...spec, parameter: after };
    }
  }
  return next;
}

/** p.55's operators whose right-hand value is a list (§644), typed as values
 * separated by commas. */
export const RIGHT_LIST_OPERATORS = ["is_included_in", "includes_any"];

/** A condition's right-hand side from what is typed: blank is p.55's "no
 * value" (is it empty?), and a list operator's is its comma-separated
 * values. */
export function rightOf(operator: string, text: string): Config {
  if (text === "") return { kind: "none" };
  return { kind: "value", value: valueFor(operator, text) };
}

/** A typed value as the operator takes it: a list operator's values between
 * commas, anything else's text as it is. */
export function valueFor(operator: string, text: string): unknown {
  if (!RIGHT_LIST_OPERATORS.includes(operator)) return text;
  return text.split(",").map((v) => v.trim()).filter((v) => v !== "");
}

/** What the value box shows for a right-hand side. */
export function rightText(spec: unknown): string {
  const s = (spec ?? {}) as Config;
  if (s.kind !== "value") return "";
  return Array.isArray(s.value) ? s.value.map(String).join(", ") : String(s.value ?? "");
}

/** A condition with its operator changed, its value re-read for it: a value
 * typed for "is" becomes a one-item list for "is included in", and back. */
export function withOperator(node: Config, operator: string): Config {
  const right = node.right as Config | undefined;
  return { ...node, operator, right: right?.kind === "value" ? rightOf(operator, rightText(right)) : right };
}

/** p.50's two condition templates for the left side (§644): a parameter, or
 * the current user - their id, or the groups they are in (p.140: "Simple
 * submission criteria can require a specific user ID or group ID"). The
 * dialog's choice is a parameter's name or one of these. */
export const USER_CHOICES: [string, string][] = [
  ["@user:id", "Current user"],
  ["@user:group_ids", "Current user's groups"],
];

export function leftOf(choice: string): Config {
  return choice.startsWith("@user:")
    ? { kind: "current_user", attribute: choice.slice("@user:".length) }
    : { kind: "parameter", parameter: choice };
}

export function leftChoice(spec: unknown): string {
  const s = (spec ?? {}) as Config;
  if (s.kind === "current_user") return `@user:${String(s.attribute ?? "id")}`;
  return String(s.parameter ?? "");
}
