/**
 * p.170's **Column math**: a derived property defined at the module level
 * (`foundry_workshop` p.168-172).
 *
 * > "Derived properties are properties that are calculated at runtime based on
 * > the values of other properties or links on objects… Derived properties are
 * > defined at the module level and per object type." (p.168)
 *
 * > "Column math: Combine values from multiple properties on a single object
 * > type. Both the object type's native properties and aggregation type
 * > derived properties may be used and referenced. Note that other column math
 * > type derived properties may not be used." (p.170)
 *
 * ---
 *
 * **Why this half of p.168 and not the other.** p.169's *Linked
 * property/aggregation* is the shape §161-§163 and §406 already built on the
 * ontology, and it carries that shape's wall: a chain costs a query per hop,
 * so it is answered on a single-object read and a table column would be a read
 * per row (`_with_derived` says so). Column math has no such wall — every
 * value it needs is already on the row the table just fetched, so it costs
 * nothing per row and works exactly where p.169's cannot.
 *
 * **Computed in the browser, and displayed rather than queried.** p.171 calls
 * these "computed on the fly"; p.172 adds that *"saved states do not support
 * object sets that reference derived properties"*, which says plainly that a
 * derived property is not part of a set definition. So this filters nothing
 * and sorts nothing — it is a column, and the parity row says so rather than
 * letting somebody discover it by sorting on one.
 *
 * ---
 *
 * **A calculator, not an expression language.** §158 declined p.105's Math
 * rule for conditional formatting on the grounds that "arithmetic over
 * properties is an expression language rather than a comparison", and that
 * judgement stands for *that* feature: a rule engine given arbitrary
 * expressions is a rule engine nobody can predict. p.170 is a different
 * request — it asks for one number built from other numbers on the same row,
 * which is the narrowest possible arithmetic, and the grammar below is
 * deliberately too small to grow into anything else. Four operators, unary
 * minus, parentheses, numbers and property names. No functions, no strings,
 * no comparisons, no conditionals.
 *
 * **Nulls propagate; they do not become zero.** The trap §149 caught in a
 * chart and §226 caught in an aggregation is the same one here and worse,
 * because it compounds: `Number(null)` is `0`, so `revenue - cost` over a row
 * missing `cost` would report the whole revenue as profit. A missing or
 * non-numeric input makes the whole expression `null`, which the cell renders
 * as "no value" rather than as a figure somebody would act on.
 */

/** What a parsed expression is. Kept as a tree rather than a closure so the
 * references can be read back out — the panel needs them to say which
 * properties an expression depends on, and p.170's own restriction is a rule
 * about references. */
export type Expr =
  | { kind: "number"; value: number }
  | { kind: "ref"; name: string }
  | { kind: "neg"; over: Expr }
  | { kind: "op"; op: "+" | "-" | "*" | "/"; left: Expr; right: Expr };

export class MathError extends Error {}

const NAME = /^[A-Za-z_][A-Za-z0-9_]*/;
const NUMBER = /^\d+(\.\d+)?/;

type Token = { t: "num"; v: number } | { t: "name"; v: string } | { t: "sym"; v: string };

function tokenise(source: string): Token[] {
  const out: Token[] = [];
  let rest = source;
  while (rest.length) {
    const ch = rest[0]!;
    if (ch === " " || ch === "\t" || ch === "\n") { rest = rest.slice(1); continue; }
    if ("+-*/()".includes(ch)) { out.push({ t: "sym", v: ch }); rest = rest.slice(1); continue; }
    const num = NUMBER.exec(rest);
    if (num) { out.push({ t: "num", v: Number(num[0]) }); rest = rest.slice(num[0].length); continue; }
    const name = NAME.exec(rest);
    if (name) { out.push({ t: "name", v: name[0] }); rest = rest.slice(name[0].length); continue; }
    // **Named, not skipped.** A stray character silently dropped would make
    // `a + b;` mean `a + b`, and the author would never learn the `;` did
    // nothing - which is the same failure as a formatter that formats nothing.
    throw new MathError(`${JSON.stringify(ch)} is not something this can use`);
  }
  return out;
}

/**
 * Parse an expression, or refuse it with a sentence.
 *
 * Recursive descent over the smallest grammar that covers p.170:
 * `sum := product (("+"|"-") product)*`, `product := unary (("*"|"/") unary)*`,
 * `unary := "-"? atom`, `atom := number | name | "(" sum ")"`.
 */
export function parse(source: string): Expr {
  const tokens = tokenise(source);
  if (!tokens.length) throw new MathError("this needs an expression");
  let at = 0;
  const peek = () => tokens[at];
  const eat = (v: string) => {
    const token = peek();
    if (token && token.t === "sym" && token.v === v) { at += 1; return true; }
    return false;
  };

  function sum(): Expr {
    let left = product();
    for (;;) {
      if (eat("+")) left = { kind: "op", op: "+", left, right: product() };
      else if (eat("-")) left = { kind: "op", op: "-", left, right: product() };
      else return left;
    }
  }
  function product(): Expr {
    let left = unary();
    for (;;) {
      if (eat("*")) left = { kind: "op", op: "*", left, right: unary() };
      else if (eat("/")) left = { kind: "op", op: "/", left, right: unary() };
      else return left;
    }
  }
  function unary(): Expr {
    if (eat("-")) return { kind: "neg", over: unary() };
    return atom();
  }
  function atom(): Expr {
    const token = peek();
    if (!token) throw new MathError("this expression stops in the middle");
    if (token.t === "num") { at += 1; return { kind: "number", value: token.v }; }
    if (token.t === "name") { at += 1; return { kind: "ref", name: token.v }; }
    if (eat("(")) {
      const inner = sum();
      if (!eat(")")) throw new MathError("a bracket is left open");
      return inner;
    }
    throw new MathError(`${JSON.stringify(token.v)} cannot start a value here`);
  }

  const tree = sum();
  if (at !== tokens.length) {
    const left = tokens[at]!;
    throw new MathError(`${JSON.stringify(String(left.v))} is left over at the end`);
  }
  return tree;
}

/** Every property an expression reads, in first-seen order.
 *
 * p.170's restriction is a rule about *references*, so the references have to
 * be readable without evaluating anything. */
export function references(expr: Expr): string[] {
  const out: string[] = [];
  const walk = (node: Expr) => {
    if (node.kind === "ref") { if (!out.includes(node.name)) out.push(node.name); return; }
    if (node.kind === "neg") { walk(node.over); return; }
    if (node.kind === "op") { walk(node.left); walk(node.right); }
  };
  walk(expr);
  return out;
}

/**
 * One row's value, or `null` when the expression cannot be answered.
 *
 * **`null` rather than a partial number**, for the reason the module docstring
 * gives: `revenue - cost` over a row with no `cost` is not `revenue`. Every
 * arm returns `null` the moment anything it needs is missing, so the emptiness
 * reaches the cell instead of being absorbed into a figure.
 */
export function evaluate(expr: Expr, properties: Record<string, unknown>): number | null {
  if (expr.kind === "number") return expr.value;
  if (expr.kind === "ref") return numberOf(properties[expr.name]);
  if (expr.kind === "neg") {
    const over = evaluate(expr.over, properties);
    return over === null ? null : -over;
  }
  const left = evaluate(expr.left, properties);
  const right = evaluate(expr.right, properties);
  if (left === null || right === null) return null;
  if (expr.op === "+") return left + right;
  if (expr.op === "-") return left - right;
  if (expr.op === "*") return left * right;
  // **Division by zero is nothing, not Infinity.** `1/0` renders as "∞",
  // which is a figure somebody reads as a result; there is no answer here and
  // the cell should say so.
  if (right === 0) return null;
  return left / right;
}

/** A stored value as a number, or `null`.
 *
 * Properties are stored untyped, so a `float` column commonly holds `"72.5"` -
 * the same coercion `sparkline.ts` needed for uploaded series, and the same
 * refusal of `""`, which `Number` reads as `0`.
 */
function numberOf(raw: unknown): number | null {
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : null;
  if (typeof raw === "string" && raw.trim() !== "") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}
