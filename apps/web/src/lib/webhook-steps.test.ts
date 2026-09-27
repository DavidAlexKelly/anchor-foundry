/** §523: the calls a webhook makes before its own request (p.234-237). */
import { describe, expect, it } from "vitest";

import { blankWebhook, problem, type WebhookDraft } from "./webhook-form";
import {
  MAX_STEPS, blankStep, extractedNames, stepDrafts, stepSummary, stepsPayload, stepsProblem,
  unsafeStep, withMethod, type StepDraft,
} from "./webhook-steps";

const step = (over: Partial<StepDraft>): StepDraft => ({ ...blankStep(), ...over });
const UNSAFE = "Only one call may change the external system (p.237). Mark an earlier call as only reading if it does.";

describe("a call before the request", () => {
  it("starts as a read with nothing extracted", () => {
    expect(blankStep()).toEqual({ method: "GET", path: "", bodyText: "", safe: false, extract: [] });
    expect(MAX_STEPS).toBe(9);
  });

  it("round-trips through the API's shape", () => {
    const saved = [{ method: "POST", path: "a", body: { k: 1 }, safe: true,
                     extract: [{ api_name: "x", path: "y" }] },
                   { method: "GET", path: "b", body: null, safe: false, extract: [] }];
    const drafts = stepDrafts(saved);
    expect(drafts[0]).toEqual({ method: "POST", path: "a", bodyText: '{\n  "k": 1\n}', safe: true,
                                extract: [{ api_name: "x", path: "y" }] });
    expect(drafts[1]?.bodyText).toBe("");
    expect(stepsPayload(drafts)).toEqual(saved);
    expect(stepDrafts(undefined)).toEqual([]);
  });

  it("sends no unnamed extract row, and no safe mark on a read", () => {
    expect(stepsPayload([step({ extract: [{ api_name: "", path: "p" }, { api_name: "a", path: "b" }] })])[0]?.extract)
      .toEqual([{ api_name: "a", path: "b" }]);
    expect(stepsPayload([step({ method: "GET", safe: true })])[0]?.safe).toBe(false);
    expect(stepsPayload([step({ method: "PUT", safe: true })])[0]?.safe).toBe(true);
  });

  it("drops the body and the mark when the method stops carrying a body", () => {
    const post = step({ method: "POST", bodyText: "{}", safe: true });
    expect(withMethod(post, "GET")).toEqual({ ...post, method: "GET", bodyText: "", safe: false });
    expect(withMethod(post, "PUT")).toEqual({ ...post, method: "PUT" });
  });

  it("knows which calls may change the far end", () => {
    expect(unsafeStep({ method: "GET", safe: false })).toBe(false);
    expect(unsafeStep({ method: "POST", safe: false })).toBe(true);
    expect(unsafeStep({ method: "POST", safe: true })).toBe(false);
  });

  it("lists what the chain extracts, in order", () => {
    expect(extractedNames([step({ extract: [{ api_name: "a", path: "x" }, { api_name: "", path: "" }] }),
                           step({ extract: [{ api_name: "b", path: "y" }] })])).toEqual(["a", "b"]);
  });

  it("says a call in one line", () => {
    expect(stepSummary(step({ path: "created" }))).toBe("GET /created");
    expect(stepSummary(step({ method: "POST", path: "x", extract: [{ api_name: "a", path: "p" }, { api_name: "", path: "" }, { api_name: "b", path: "q" }] })))
      .toBe("POST /x → a, b");
  });
});

describe("what is wrong with a chain", () => {
  it("allows a read then the request's change, or a change marked as a read", () => {
    expect(stepsProblem([step({ path: "a" })], [], "POST")).toBeNull();
    expect(stepsProblem([step({ method: "POST", safe: true })], [], "POST")).toBeNull();
    expect(stepsProblem([step({ method: "POST" })], [], "GET")).toBeNull();
    expect(stepsProblem([], [], "POST")).toBeNull();
  });

  it("refuses a second change (p.237)", () => {
    expect(stepsProblem([step({ method: "POST" })], [], "PUT")).toBe(UNSAFE);
    expect(stepsProblem([step({ method: "POST" }), step({ method: "DELETE" })], [], "GET")).toBe(UNSAFE);
  });

  it("refuses more than nine calls", () => {
    expect(stepsProblem(Array.from({ length: 9 }, () => step({})), [], "POST")).toBeNull();
    expect(stepsProblem(Array.from({ length: 10 }, () => step({})), [], "POST"))
      .toBe("A webhook makes at most 9 calls before its request.");
  });

  it("says what is wrong with a body", () => {
    expect(stepsProblem([step({ method: "POST", safe: true, bodyText: "{" })], [], "POST"))
      .toMatch(/^Call 1: the body is not valid JSON: /);
    expect(stepsProblem([step({ method: "GET", bodyText: "{}" })], [], "POST"))
      .toBe("Call 1: a GET request cannot carry a body.");
  });

  it("lets a call use the inputs and what earlier calls extracted, nothing else", () => {
    const first = step({ path: "{{{who}}}", extract: [{ api_name: "a", path: "x" }] });
    expect(stepsProblem([first, step({ path: "{{{a}}}/{{{who}}}" })], ["who"], "POST")).toBeNull();
    expect(stepsProblem([step({ path: "{{{later}}}" }), step({ extract: [{ api_name: "later", path: "x" }] })], [], "POST"))
      .toBe("Call 1 references later, which is neither an input nor extracted by an earlier call.");
    expect(stepsProblem([step({ path: "{{{own}}}", extract: [{ api_name: "own", path: "x" }] })], [], "POST"))
      .toBe("Call 1 references own, which is neither an input nor extracted by an earlier call.");
    expect(stepsProblem([step({ method: "POST", safe: true, bodyText: '{"k": "{{{nope}}}"}' })], [], "POST"))
      .toBe("Call 1 references nope, which is neither an input nor extracted by an earlier call.");
  });

  it("checks the names and paths of what is extracted", () => {
    const one = (api_name: string, path = "x") => [step({ extract: [{ api_name, path }] })];
    expect(stepsProblem(one("Bad"), [], "POST")).toBe("Call 1: Bad is not a valid name for an extracted value.");
    expect(stepsProblem(one("who"), ["who"], "POST")).toBe("Call 1: who is already an input or an extracted value.");
    expect(stepsProblem([step({ extract: [{ api_name: "a", path: "x" }] }), step({ extract: [{ api_name: "a", path: "y" }] })], [], "POST"))
      .toBe("Call 2: a is already an input or an extracted value.");
    expect(stepsProblem(one("a", " "), [], "POST")).toBe('Call 1: a needs a path, or "." for the whole response.');
    // A row not yet named is not a problem; it is dropped on Save.
    expect(stepsProblem(one("", ""), [], "POST")).toBeNull();
  });
});

describe("the webhook's form with a chain", () => {
  const draft = (over: Partial<WebhookDraft>): WebhookDraft => ({
    ...blankWebhook("c1"), display_name: "Hook", api_name: "hook", ...over,
  });

  it("lets the request use what the chain extracted", () => {
    const steps = [step({ path: "created", extract: [{ api_name: "unique_id", path: "results.unique_id" }] })];
    expect(problem(draft({ steps, bodyText: '{"id": "{{{unique_id}}}"}' }))).toBeNull();
    expect(problem(draft({ bodyText: '{"id": "{{{unique_id}}}"}' })))
      .toBe("The body references unique_id, which is not an input of this webhook.");
  });

  it("says what is wrong with the chain", () => {
    expect(problem(draft({ steps: [step({ method: "POST" })] }))).toBe(UNSAFE);
  });
});
