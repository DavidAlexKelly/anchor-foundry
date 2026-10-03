/** `ontology` p.130-131's regular expression search (§728), as the browser
 * checks it before applying: the server's `regex_search.parse` refusals, in
 * its words, so the Filter List's box applies a pattern only once it is one -
 * as the advanced keyword box does (`keyword-query.ts`). The server stays the
 * authority; a drift here is a box that waits for a pattern the server would
 * take, or applies one it refuses, and `regex-query.test.ts` pins the
 * sentences.
 */

export const MAX_REGEX_LENGTH = 200;

const CLASSES = "dDsSwW";

/** What is wrong with a pattern, or null when p.130-131 allows it. */
export function regexProblem(pattern: string): string | null {
  if (!pattern) return "a regular expression is non-empty text";
  if (pattern.length > MAX_REGEX_LENGTH) {
    return `a regular expression is at most ${MAX_REGEX_LENGTH} characters`;
  }
  // The same reading as the server's, written as JavaScript to compile.
  let js = "";
  let i = 0;
  while (i < pattern.length) {
    const c = pattern[i]!;
    if (c === "\\") {
      if (i + 1 >= pattern.length) return "a \\ ends the pattern with nothing to escape";
      const next = pattern[i + 1]!;
      js += CLASSES.includes(next) ? `\\${next}` : escapeChar(next);
      i += 2;
    } else if (c === '"') {
      const end = pattern.indexOf('"', i + 1);
      if (end < 0) return 'a " has no closing "';
      js += `(?:${[...pattern.slice(i + 1, end)].map(escapeChar).join("")})`;
      i = end + 1;
    } else if (c === "[") {
      const read = bracket(pattern, i + 1);
      if (typeof read === "string") return read;
      js += read.js;
      i = read.end;
    } else if (c === "{") {
      const found = /^\{(\d{1,4})(,(\d{0,4}))?\}/.exec(pattern.slice(i));
      if (!found) return "a { must be {n}, {n,} or {n,m}";
      if (found[3] && Number(found[3]) < Number(found[1])) {
        return `{${found[1]},${found[3]}} runs backwards`;
      }
      js += found[0];
      i += found[0].length;
    } else if (c === "^" || c === "$") {
      return "^ and $ anchors are not supported: a pattern already matches the whole value (ontology p.130)";
    } else if (".?+*|()".includes(c)) {
      js += c;
      i += 1;
    } else {
      js += escapeChar(c);
      i += 1;
    }
  }
  try {
    new RegExp(`^(?:${js})$`);
  } catch {
    return "not a pattern: an operator has nothing to apply to, or a ( is not closed";
  }
  return null;
}

function escapeChar(c: string): string {
  return /[\\^$.*+?()[\]{}|/-]/.test(c) ? `\\${c}` : c;
}

/** `[…]` from just past the `[`: its JavaScript, and where it ended, or why
 * it is not one. */
function bracket(pattern: string, start: number): { js: string; end: number } | string {
  let i = start;
  let js = "[";
  if (pattern[i] === "^") {
    js += "^";
    i += 1;
  }
  let first = true;
  let held = 0;
  let lastSingle: string | null = null;
  while (true) {
    if (i >= pattern.length) return "a [ has no closing ]";
    const c = pattern[i]!;
    if (c === "]" && !first) break;
    if (c === "\\") {
      if (i + 1 >= pattern.length) return "a \\ ends the pattern with nothing to escape";
      const next = pattern[i + 1]!;
      if ("DSW".includes(next)) return `\\${next} cannot be used inside [ ]`;
      js += "dsw".includes(next) ? `\\${next}` : escapeChar(next);
      lastSingle = "dsw".includes(next) ? null : next;
      i += 2;
    } else if (c === "-" && !first && pattern[i + 1] !== undefined && pattern[i + 1] !== "]"
               && lastSingle !== null) {
      let high = pattern[i + 1]!;
      let step = 2;
      if (high === "\\") {
        if (i + 2 >= pattern.length) return "a \\ ends the pattern with nothing to escape";
        high = pattern[i + 2]!;
        step = 3;
      }
      if (high.codePointAt(0)! < lastSingle.codePointAt(0)!) {
        return `the range ${lastSingle}-${high} runs backwards`;
      }
      js += `-${escapeChar(high)}`;
      lastSingle = null;
      i += step;
    } else {
      js += escapeChar(c);
      lastSingle = c;
      i += 1;
    }
    first = false;
    held += 1;
  }
  if (!held) return "[ ] holds nothing";
  return { js: `${js}]`, end: i + 1 };
}
