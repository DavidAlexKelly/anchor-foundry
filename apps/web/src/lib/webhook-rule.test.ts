import { describe, expect, it } from "vitest";
import {
  DEFAULT_MODE, MODES, OUTPUT_PREFIX, blankWebhookConfig, listProblem,
  outputName, problem, requiredInputs, valueOptions,
} from "./webhook-rule";

const PARAMETERS = ["priority", "note"];

const WEBHOOK = {
  inputs: [
    { api_name: "priority", required: true },
    { api_name: "note", required: false },
  ],
};

function config(over: Record<string, unknown> = {}) {
  return {
    ...blankWebhookConfig(),
    webhook: "w1",
    inputs: { priority: { parameter: "priority" } },
    ...over,
  } as ReturnType<typeof blankWebhookConfig>;
}

function outputsFor(id: string): string[] {
  return id === "w1" ? ["unique_id"] : [];
}

describe("the two modes", () => {
  it("offers p.106's two and no third", () => {
    expect(MODES.map(([v]) => v)).toEqual(["side_effect", "writeback"]);
  });

  it("defaults to the one that cannot break an action", () => {
    // p.114: "By default, the newly added webhook is configured as a side
    // effect." The default is the safe one, which is why it is worth a test.
    expect(DEFAULT_MODE).toBe("side_effect");
    expect(blankWebhookConfig().mode).toBe("side_effect");
  });

  it("lists the default first", () => {
    // A list whose first entry is not the default reads as though the default
    // were a deviation.
    expect(MODES[0][0]).toBe(DEFAULT_MODE);
  });
});

describe("requiredInputs", () => {
  it("names the ones a rule must supply", () => {
    expect(requiredInputs(WEBHOOK)).toEqual(["priority"]);
  });

  it("treats a webhook with no inputs as needing nothing", () => {
    expect(requiredInputs(undefined)).toEqual([]);
    expect(requiredInputs({ inputs: [] })).toEqual([]);
  });
});

describe("problem", () => {
  it("passes a rule the server would take", () => {
    expect(problem(config(), PARAMETERS, WEBHOOK)).toBeNull();
  });

  it("wants the webhook chosen", () => {
    expect(problem(config({ webhook: "" }), PARAMETERS, WEBHOOK)).toContain(
      "Choose the webhook",
    );
  });

  it("wants a mode it recognises", () => {
    expect(problem(config({ mode: "eventually" }), PARAMETERS, WEBHOOK)).toContain(
      "when this webhook runs",
    );
  });

  it("wants exactly one source for an input", () => {
    // Both is as wrong as neither, and for the same reason: it leaves the rule
    // with no answer to "where does this value come from".
    for (const source of [{}, { parameter: "priority", value: "x" }]) {
      expect(
        problem(config({ inputs: { priority: source } }), PARAMETERS, WEBHOOK),
      ).toContain("not both");
    }
  });

  it("accepts a static value on its own", () => {
    expect(
      problem(config({ inputs: { priority: { value: "fixed" } } }), PARAMETERS, WEBHOOK),
    ).toBeNull();
  });

  it("accepts an empty static value, which is a value", () => {
    // `""` is a thing somebody meant to send; treating it as "no source" would
    // make an empty string unsendable.
    expect(
      problem(config({ inputs: { priority: { value: "" } } }), PARAMETERS, WEBHOOK),
    ).toBeNull();
  });

  it("catches a parameter that does not exist", () => {
    expect(
      problem(config({ inputs: { priority: { parameter: "nope" } } }), PARAMETERS, WEBHOOK),
    ).toContain("nope");
  });

  it("wants every required input supplied", () => {
    expect(problem(config({ inputs: {} }), PARAMETERS, WEBHOOK)).toContain("priority");
  });

  it("does not want the optional one", () => {
    // The presence half: without it, the check above would pass against an
    // implementation that demanded every input.
    expect(problem(config(), PARAMETERS, WEBHOOK)).toBeNull();
  });
});

describe("listProblem", () => {
  const writeback = (id: string) => ({
    kind: "webhook", config: { webhook: id, mode: "writeback" },
  });
  const sideEffect = (id: string) => ({
    kind: "webhook", config: { webhook: id, mode: "side_effect" },
  });
  const reads = (name: string) => ({
    kind: "modify_object", config: { property: "p", parameter: name },
  });

  it("has nothing to say about rules that are fine", () => {
    expect(
      listProblem([writeback("w1"), reads("webhook.unique_id")], outputsFor),
    ).toBeNull();
  });

  it("refuses a second writeback", () => {
    // p.106: "you can only configure a single webhook as a writeback". The
    // rule that breaks it is the *second* one, so no single rule is wrong —
    // which is why this check is over the list.
    expect(listProblem([writeback("w1"), writeback("w2")], outputsFor)).toContain(
      "only one writeback",
    );
  });

  it("allows many side effects", () => {
    // p.107, and the presence half of the refusal above: without it that check
    // would pass against an implementation refusing every second webhook.
    expect(
      listProblem([sideEffect("w1"), sideEffect("w2"), sideEffect("w1")], outputsFor),
    ).toBeNull();
  });

  it("refuses an output read above the writeback that produces it", () => {
    // p.110's word is *subsequent*, and the order of the walk is what makes it
    // checkable rather than aspirational.
    expect(
      listProblem([reads("webhook.unique_id"), writeback("w1")], outputsFor),
    ).toContain("below the writeback");
  });

  it("refuses an output a side effect would have produced", () => {
    // Only a writeback's outputs are usable, and the reason is structural: a
    // side effect runs after every rule, so there is no subsequent rule for
    // its output to reach.
    expect(
      listProblem([sideEffect("w1"), reads("webhook.unique_id")], outputsFor),
    ).toContain("below the writeback");
  });

  it("refuses an output the named webhook does not declare", () => {
    expect(
      listProblem([writeback("w2"), reads("webhook.unique_id")], outputsFor),
    ).toContain("below the writeback");
  });

  it("has nothing to say about an ordinary parameter", () => {
    expect(listProblem([reads("priority")], outputsFor)).toBeNull();
  });
});

describe("valueOptions", () => {
  const writeback = { kind: "webhook", config: { webhook: "w1", mode: "writeback" } };
  const other = { kind: "modify_object", config: {} };

  it("offers the action's parameters", () => {
    expect(valueOptions(PARAMETERS, [other], 0, outputsFor)).toEqual(PARAMETERS);
  });

  it("offers a writeback's outputs to a rule below it", () => {
    expect(valueOptions(PARAMETERS, [writeback, other], 1, outputsFor)).toEqual([
      ...PARAMETERS, "webhook.unique_id",
    ]);
  });

  it("offers nothing extra to a rule above it", () => {
    // Offering an output to a rule that cannot use it would be offering a save
    // that fails (§214) — and the refusal would name something the reader can
    // see in the very dropdown they picked it from.
    expect(valueOptions(PARAMETERS, [other, writeback], 0, outputsFor)).toEqual(
      PARAMETERS,
    );
  });

  it("offers nothing extra for a side effect", () => {
    const sideEffect = {
      kind: "webhook", config: { webhook: "w1", mode: "side_effect" },
    };
    expect(valueOptions(PARAMETERS, [sideEffect, other], 1, outputsFor)).toEqual(
      PARAMETERS,
    );
  });
});

describe("the reserved prefix", () => {
  it("cannot be a parameter name, which is what makes it a namespace", () => {
    // An api_name matches ^[a-z][a-z0-9_]*$ on both sides of the wire, so a
    // dot is the one character that guarantees no collision. An API test
    // asserts this string matches the server's.
    expect(OUTPUT_PREFIX).toContain(".");
    expect(outputName("unique_id")).toBe("webhook.unique_id");
  });
});
