/**
 * p.452's advanced keyword syntax, checked as it is typed (§543).
 *
 * > "… you can chain search operations with each other and define the order
 * > of operations through brackets. If no brackets are defined, common Boolean
 * > logic is used to determine precedence of operators as follows: quotations,
 * > parentheses, NOT, AND, OR." (p.452)
 *
 * **The server parses the query and is the authority** (`object_sets.
 * parse_keyword_query`); this says what is wrong before a query is sent, in
 * the server's own words, so a half-typed `(north OR` is a sentence under the
 * box rather than a refusal every widget reading the set would show. The same
 * cases are in `keyword-query.test.ts` and `test_keyword_query.py`.
 */

export const MAX_QUERY_LENGTH = 500;
export const MAX_QUERY_TERMS = 32;

const WORDS = ["AND", "OR", "NOT"];

type Token = { kind: string; text: string };

function tokens(text: string): Token[] {
  const out: Token[] = [];
  let i = 0;
  while (i < text.length) {
    const c = text[i]!;
    if (/\s/.test(c)) {
      i += 1;
    } else if (c === "(" || c === ")") {
      out.push({ kind: c, text: c });
      i += 1;
    } else if (c === '"') {
      const end = text.indexOf('"', i + 1);
      if (end < 0) throw new Error("a quotation is not closed");
      const quoted = text.slice(i + 1, end);
      if (!quoted.trim()) throw new Error("a quotation is empty, and would match every value");
      out.push({ kind: "term", text: quoted });
      i = end + 1;
    } else {
      const start = i;
      while (i < text.length && !/\s/.test(text[i]!) && !'()"'.includes(text[i]!)) i += 1;
      const word = text.slice(start, i);
      out.push({ kind: WORDS.includes(word) ? word : "term", text: word });
    }
  }
  return out;
}

/** Walks the grammar the server does, keeping nothing: validity is all the
 * browser needs. */
function check(list: Token[]): void {
  let at = 0;
  const peek = () => list[at]?.kind;
  const orExpr = (): void => {
    andExpr();
    while (peek() === "OR") {
      at += 1;
      andExpr();
    }
  };
  const andExpr = (): void => {
    notExpr();
    for (;;) {
      const kind = peek();
      if (kind === "AND") at += 1;
      else if (kind !== "term" && kind !== "(" && kind !== "NOT") return;
      notExpr();
    }
  };
  const notExpr = (): void => {
    if (peek() === "NOT") {
      at += 1;
      notExpr();
      return;
    }
    atom();
  };
  const atom = (): void => {
    const token = list[at];
    if (!token) throw new Error("the query ends where a term was expected");
    at += 1;
    if (token.kind === "term") return;
    if (token.kind === "(") {
      if (peek() === ")") throw new Error("a pair of brackets holds nothing");
      orExpr();
      if (peek() !== ")") throw new Error("a bracket is not closed");
      at += 1;
      return;
    }
    if (token.kind === ")") throw new Error("a closing bracket has no opening one");
    throw new Error(`${token.text} needs a term on each side`);
  };
  orExpr();
  if (peek() !== undefined) throw new Error("a closing bracket has no opening one");
}

/** What is wrong with the query, or null when the server would take it. */
export function keywordQueryProblem(text: string): string | null {
  if (text.length > MAX_QUERY_LENGTH) {
    return `an advanced keyword query is at most ${MAX_QUERY_LENGTH} characters`;
  }
  try {
    const list = tokens(text);
    if (list.length === 0) return "the query is empty";
    if (list.filter((t) => t.kind === "term").length > MAX_QUERY_TERMS) {
      return `an advanced keyword query has at most ${MAX_QUERY_TERMS} terms`;
    }
    check(list);
    return null;
  } catch (e) {
    return (e as Error).message;
  }
}
