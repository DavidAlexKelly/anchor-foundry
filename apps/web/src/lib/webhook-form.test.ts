import { describe, expect, it } from "vitest";
import {
  BODYLESS_METHODS, INPUT_TYPES, METHODS, OUTPUT_TYPES, RESERVED_HEADERS,
  WebhookDraft, blankWebhook, bodyProblem, outcomeLabel, parsedBody, problem,
  referencesIn, stringsIn, suggestedApiName,
} from "./webhook-form";

function draft(over: Partial<WebhookDraft> = {}): WebhookDraft {
  return {
    ...blankWebhook("c1"),
    api_name: "modify_ticket",
    display_name: "Modify ticket priority",
    ...over,
  };
}

describe("the offered vocabularies", () => {
  it("offers every method the server takes", () => {
    // The two lists have to agree on their *contents* and are deliberately in
    // different orders: the server groups by safety because that is what
    // `system_changed` asks, and a request builder groups by what somebody is
    // doing. An API test compares them across the wire; this one keeps the
    // browser's own list from losing a member.
    expect([...METHODS].sort()).toEqual([
      "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT",
    ]);
  });

  it("names p.237's three safe methods as the ones with no body", () => {
    expect([...BODYLESS_METHODS].sort()).toEqual(["GET", "HEAD", "OPTIONS"]);
  });

  it("offers no input type the platform cannot send", () => {
    // p.229's Attachment needs an action form's uploaded file, and the two
    // container types are a validator of their own. Absent rather than
    // offered-and-refused (§214).
    expect(INPUT_TYPES.map(([v]) => v)).toEqual([
      "string", "integer", "double", "boolean", "date", "timestamp",
    ]);
  });

  it("offers an object as an output and not as an input", () => {
    // The direction is what makes it cheap: capturing a JSON object out of a
    // response is a slice; accepting one in is a schema to validate.
    expect(OUTPUT_TYPES.map(([v]) => v)).toContain("record");
    expect(INPUT_TYPES.map(([v]) => v)).not.toContain("record");
  });
});

describe("blankWebhook", () => {
  it("starts on the method p.216's own example uses", () => {
    // "a webhook that performs an HTTP request to an external server when a
    // user selects a button". Reading is what the connector already does.
    expect(blankWebhook("c1").method).toBe("POST");
  });

  it("starts with responses stored, which is p.242's default", () => {
    expect(blankWebhook("c1").store_responses).toBe(true);
  });
});

describe("bodyProblem", () => {
  it("has nothing to say about an empty body", () => {
    // A request with no body is a request with no body, not an error.
    expect(bodyProblem("")).toBeNull();
    expect(bodyProblem("   ")).toBeNull();
  });

  it("names the fault in something that is not JSON", () => {
    expect(bodyProblem("{oops")).toContain("not valid JSON");
  });

  it("accepts an array, which is a perfectly good request body", () => {
    // p.233 does not say a body must be an object, and refusing one would
    // refuse every bulk endpoint.
    expect(bodyProblem('[{"a":1}]')).toBeNull();
  });
});

describe("parsedBody", () => {
  it("tells an empty body from an unparseable one", () => {
    // **They look the same in a request and are opposite in intent**, so the
    // two answers are different values rather than both being null.
    expect(parsedBody("")).toBeNull();
    expect(parsedBody("{oops")).toBeUndefined();
  });

  it("keeps the document's own types", () => {
    expect(parsedBody('{"n": 3}')).toEqual({ n: 3 });
  });
});

describe("stringsIn", () => {
  it("finds a string at any depth", () => {
    expect(stringsIn({ a: { b: ["deep"] } })).toContain("deep");
  });

  it("finds keys as well as values", () => {
    // `{"{{{name}}}": 1}` is a reference too, and a form that checked one
    // position and not the other would be right about the common case.
    expect(stringsIn({ key: 1 })).toContain("key");
  });

  it("has nothing to say about numbers", () => {
    expect(stringsIn({ n: 3, b: true, z: null })).toEqual(["n", "b", "z"]);
  });
});

describe("referencesIn", () => {
  it("finds three-brace references and not two", () => {
    // Two braces are not a reference: the template renders literally and
    // nothing on screen says so.
    expect(referencesIn("{{{a}}} and {{b}}")).toEqual(["a"]);
  });
});

describe("problem", () => {
  it("passes a webhook the server would take", () => {
    expect(problem(draft())).toBeNull();
  });

  it("wants a name", () => {
    expect(problem(draft({ display_name: "  " }))).toContain("needs a name");
  });

  it("wants an api name it can address", () => {
    expect(problem(draft({ api_name: "Modify Ticket" }))).toContain("API name");
  });

  it("wants the source the webhook calls", () => {
    expect(problem(draft({ connection_id: "" }))).toContain("source");
  });

  it("carries the body's own fault up", () => {
    // One message rather than "the form is invalid": the browser's parse error
    // names the position, which is the useful half.
    expect(problem(draft({ bodyText: "{oops" }))).toContain("not valid JSON");
  });

  it("refuses a body on a method that drops it", () => {
    expect(problem(draft({ method: "GET", bodyText: '{"a":1}' }))).toContain(
      "cannot carry a body",
    );
  });

  it("allows a read-only method with no body", () => {
    // The presence half of §157: the refusal above only means something if the
    // method itself is allowed.
    expect(problem(draft({ method: "GET" }))).toBeNull();
  });

  it("refuses two inputs with one name", () => {
    expect(
      problem(draft({
        inputs: [
          { api_name: "a", data_type: "string", required: true },
          { api_name: "a", data_type: "string", required: true },
        ],
      })),
    ).toContain("both called");
  });

  it("refuses two outputs with one name", () => {
    // **The inputs check does not cover this**, and a mutant deleting it
    // survived until this existed: the two lists are separate loops over
    // separate sets, and one of them having a guard says nothing about the
    // other. Any pair of near-identical validations needs both halves checked
    // for the same reason.
    expect(
      problem(draft({
        outputs: [
          { api_name: "id", data_type: "string", path: "id" },
          { api_name: "id", data_type: "string", path: "other" },
        ],
      })),
    ).toContain("both called");
  });

  it("refuses outputs on a HEAD request", () => {
    expect(
      problem(draft({
        method: "HEAD",
        outputs: [{ api_name: "id", data_type: "string", path: "id" }],
      })),
    ).toContain("no body");
  });

  it("refuses a header the source sets", () => {
    expect(
      problem(draft({ headers: { Authorization: "Bearer x" } })),
    ).toContain("set by the source");
  });

  it("refuses a reserved header whatever its case", () => {
    // HTTP header names are case-insensitive, so a check that was not would be
    // a guard with a one-character bypass.
    expect(
      problem(draft({ headers: { authorization: "Bearer x" } })),
    ).toContain("set by the source");
  });

  it("catches a reference to something that is not an input", () => {
    expect(problem(draft({ path: "items/{{{nope}}}" }))).toContain("nope");
  });

  it("catches a reference deep inside the body", () => {
    // A check that only read the top level would pass the one that matters:
    // bodies nest, and the reference somebody gets wrong is rarely at depth 0.
    expect(
      problem(draft({ bodyText: '{"a":{"b":["{{{nope}}}"]}}' })),
    ).toContain("nope");
  });

  it("catches a reference in a body key", () => {
    expect(problem(draft({ bodyText: '{"{{{nope}}}": 1}' }))).toContain("nope");
  });

  it("accepts a reference that names a declared input", () => {
    expect(
      problem(draft({
        bodyText: '{"p":"{{{priority}}}"}',
        inputs: [{ api_name: "priority", data_type: "string", required: true }],
      })),
    ).toBeNull();
  });
});

describe("RESERVED_HEADERS", () => {
  it("names the three the source owns", () => {
    expect([...RESERVED_HEADERS].sort()).toEqual([
      "authorization", "content-length", "host",
    ]);
  });
});

describe("suggestedApiName", () => {
  it("turns a sentence into a name", () => {
    expect(suggestedApiName("Modify ticket priority")).toBe("modify_ticket_priority");
  });

  it("leaves no leading or trailing underscore", () => {
    expect(suggestedApiName("  Close!  ")).toBe("close");
  });

  it("does not start with a digit, which the server refuses", () => {
    expect(suggestedApiName("2nd try")).toBe("h2nd_try");
  });
});

describe("outcomeLabel", () => {
  it("says which of p.237's three answers a failure got", () => {
    // **The third state is the point.** A 500 after a POST may well have
    // written, and rendering that as "nothing was changed" would be believed.
    expect(outcomeLabel({ ok: false, status_code: 404, system_changed: false }))
      .toContain("nothing was changed");
    expect(outcomeLabel({ ok: false, status_code: 500, system_changed: null }))
      .toContain("may have changed");
    expect(outcomeLabel({ ok: true, status_code: 201, system_changed: true }))
      .toContain("Succeeded");
  });

  it("names the status when there is one", () => {
    expect(outcomeLabel({ ok: false, status_code: 503, system_changed: null }))
      .toContain("503");
  });

  it("says nothing about a status when the request never got one", () => {
    // A timeout has no status, and "(null)" on screen is worse than silence.
    const label = outcomeLabel({ ok: false, status_code: null, system_changed: false });
    expect(label).not.toContain("(");
    expect(label).toContain("nothing was changed");
  });
});
