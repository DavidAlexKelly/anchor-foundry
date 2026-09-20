import { describe, expect, it } from "vitest";

import { REDACT_PARAM, WARNING, carry, redactHref, redactOn } from "./redact";

describe("redactOn", () => {
  it("reads p.615's parameter", () => {
    expect(redactOn(`${REDACT_PARAM}=true`)).toBe(true);
    expect(redactOn(`?${REDACT_PARAM}=true`)).toBe(true);
  });

  it("is off when the parameter is absent", () => {
    expect(redactOn("")).toBe(false);
    expect(redactOn("page=p1&other=true")).toBe(false);
  });

  it("accepts only the spelling p.615 gives", () => {
    // A link copied out of Foundry's documentation has to work here, and one
    // written here has to work there. Accepting `1` would break the second.
    for (const value of ["1", "yes", "True", "", "false"]) {
      expect(redactOn(`${REDACT_PARAM}=${value}`)).toBe(false);
    }
  });

  it("does not turn on for a bare key", () => {
    // Failing open on an unreadable value would make a typo redact the page.
    expect(redactOn(REDACT_PARAM)).toBe(false);
  });
});

describe("redactHref", () => {
  it("turns the mode on and off again", () => {
    const on = redactHref("/r/mod", true);
    expect(redactOn(on.split("?")[1] ?? "")).toBe(true);
    expect(redactHref(on, false)).toBe("/r/mod");
  });

  it("keeps every other parameter", () => {
    // p.197: a routed link carries its variable values in the address, and
    // dropping them would redact a different module state than the one shown.
    const href = redactHref("/r/mod?page=p2&region=North", true);
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("page")).toBe("p2");
    expect(params.get("region")).toBe("North");
    expect(params.get(REDACT_PARAM)).toBe("true");
  });

  it("leaves no empty question mark behind", () => {
    expect(redactHref(`/r/mod?${REDACT_PARAM}=true`, false)).toBe("/r/mod");
  });

  it("does not add a second copy of the parameter", () => {
    const href = redactHref(`/r/mod?${REDACT_PARAM}=true`, true);
    expect(new URLSearchParams(href.split("?")[1]).getAll(REDACT_PARAM))
      .toEqual(["true"]);
  });
});

describe("carry", () => {
  it("passes the mode into a module opened by an event", () => {
    // p.90's Open Workshop module builds a fresh address. A redacted screen
    // share whose first link opens an unredacted module has redacted nothing.
    expect(carry({ region: "North" }, `${REDACT_PARAM}=true`))
      .toEqual({ region: "North", [REDACT_PARAM]: "true" });
  });

  it("adds nothing when the mode is off", () => {
    const query = { region: "North" };
    expect(carry(query, "page=p1")).toBe(query);
  });

  it("leaves the event's own value alone", () => {
    expect(carry({ [REDACT_PARAM]: "false" }, `${REDACT_PARAM}=true`))
      .toEqual({ [REDACT_PARAM]: "false" });
  });

  it("does not modify the query it was given", () => {
    const query = { region: "North" };
    carry(query, `${REDACT_PARAM}=true`);
    expect(query).toEqual({ region: "North" });
  });
});

describe("the warning", () => {
  it("says the data is still there", () => {
    // p.614's paragraph is part of the feature: a blurred page looks like a
    // page that is protecting something, and somebody who believes that will
    // screen-share a DOM that still holds every value.
    expect(WARNING).toContain("not a security feature");
    expect(WARNING.toLowerCase()).toContain("still");
  });
});
