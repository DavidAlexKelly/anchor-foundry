import { describe, expect, it } from "vitest";

import { MAX_REGEX_LENGTH, regexProblem } from "./regex-query";

/** The server's `test_regex_search.py` refusals, sentence for sentence, and
 * p.131's examples allowed (§728). */
describe("regexProblem (ontology p.130-131, as the server reads it)", () => {
  it("allows p.131's examples", () => {
    for (const ok of ["cat", ".*cat.*", "c.t", "colou?r", "go+d", "go*d", "go{2}d", "go{2,}d",
      "go{2,4}d", "cat|dog", "(un)?happy", "gr[ae]y", "[a-z]", "[A-Za-z]", "[^0-9]", "[-x]",
      "[a\\-z]", '"v2.0"', "\\d{3}-\\d{4}", "\\w+\\s\\w+", "example\\.com", "a#b@c&d<e>f~g",
      "[\\d]"]) {
      expect(regexProblem(ok), ok).toBeNull();
    }
  });

  it("refuses what p.130 does not allow, with the server's reason", () => {
    const cases: [string, string][] = [
      ["^cat", "anchors are not supported"],
      ["cat$", "anchors are not supported"],
      ["[ab", "has no closing ]"],
      ['"ab', 'has no closing "'],
      ["a{2", "must be {n}"],
      ["a{x}", "must be {n}"],
      ["a{4,2}", "runs backwards"],
      ["[z-a]", "runs backwards"],
      ["ab\\", "nothing to escape"],
      ["[\\D]", "cannot be used inside"],
      ["*a", "not a pattern"],
      ["(ab", "not a pattern"],
      ["", "non-empty text"],
      ["a".repeat(MAX_REGEX_LENGTH + 1), "at most"],
    ];
    for (const [pattern, why] of cases) {
      expect(regexProblem(pattern), pattern).toContain(why);
    }
  });
});
