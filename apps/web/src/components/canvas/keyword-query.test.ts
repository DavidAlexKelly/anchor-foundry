import { describe, expect, it } from "vitest";

import { MAX_QUERY_LENGTH, MAX_QUERY_TERMS, keywordQueryProblem } from "./keyword-query";

describe("keywordQueryProblem (p.452's advanced syntax, as the server parses it)", () => {
  it("takes what the server takes", () => {
    for (const text of [
      "north", "north OR south", "a OR b AND NOT c", "(a OR b) AND c", "NOT (a OR b)",
      "((a))", "a b c", "NOT NOT a", "a NOT b", '"north west"', '"NOT sure" OR x', 'a"b"',
      "a and b", "not", "or",
      "a ".repeat(MAX_QUERY_TERMS), "a".repeat(MAX_QUERY_LENGTH),
    ]) {
      expect(keywordQueryProblem(text), text).toBeNull();
    }
  });

  // The same cases as test_keyword_query.py, and the same words.
  it.each([
    ["", "the query is empty"],
    ["   ", "the query is empty"],
    ['"a', "a quotation is not closed"],
    ['""', "a quotation is empty, and would match every value"],
    ['"  "', "a quotation is empty, and would match every value"],
    ["(a", "a bracket is not closed"],
    ["a)", "a closing bracket has no opening one"],
    [")", "a closing bracket has no opening one"],
    ["()", "a pair of brackets holds nothing"],
    ["AND a", "AND needs a term on each side"],
    ["a OR OR b", "OR needs a term on each side"],
    ["a AND", "the query ends where a term was expected"],
    ["NOT", "the query ends where a term was expected"],
  ])("refuses %j: %s", (text, says) => {
    expect(keywordQueryProblem(text)).toBe(says);
  });

  it("is bounded as the server bounds it", () => {
    expect(keywordQueryProblem("a ".repeat(MAX_QUERY_TERMS + 1)))
      .toBe(`an advanced keyword query has at most ${MAX_QUERY_TERMS} terms`);
    expect(keywordQueryProblem("a".repeat(MAX_QUERY_LENGTH + 1)))
      .toBe(`an advanced keyword query is at most ${MAX_QUERY_LENGTH} characters`);
  });
});
