/** §516: HTTPS listeners on the Data Connection screen. */
import { describe, expect, it } from "vitest";

import {
  BLANK_LISTENER, VERIFICATIONS, curlExample, draftBody, draftProblem, needsHeader, statusText,
  verificationText,
} from "./listeners";

const draft = (extra: Partial<typeof BLANK_LISTENER>) => ({ ...BLANK_LISTENER, display_name: "Hook", ...extra });

describe("draftProblem", () => {
  it("needs a name, and nothing else for no verification", () => {
    expect(draftProblem(BLANK_LISTENER)).toBe("Name the listener.");
    expect(draftProblem(draft({ display_name: "   " }))).toBe("Name the listener.");
    expect(draftProblem(draft({}))).toBe("");
  });

  it("asks each scheme for what it reads", () => {
    expect(draftProblem(draft({ verification: "header_secret" }))).toBe("This verification needs a secret.");
    expect(draftProblem(draft({ verification: "header_secret", secret: "s" })))
      .toBe("Name the header it arrives in: letters, digits and hyphens.");
    expect(draftProblem(draft({ verification: "hmac_sha256", secret: "s", verification_header: "X Sig" })))
      .toBe("Name the header it arrives in: letters, digits and hyphens.");
    expect(draftProblem(draft({ verification: "hmac_sha256", secret: "s", verification_header: "X-Sig" }))).toBe("");
    expect(draftProblem(draft({ verification: "basic", secret: "nocolon" })))
      .toBe("Basic authentication's secret is username:password.");
    expect(draftProblem(draft({ verification: "basic", secret: "u:p" }))).toBe("");
  });
});

describe("draftBody", () => {
  it("sends only what the scheme uses", () => {
    expect(draftBody(draft({ display_name: " Hook ", secret: "left", verification_header: "X-A" })))
      .toEqual({ display_name: "Hook", verification: "none" });
    expect(draftBody(draft({ verification: "basic", secret: "u:p", verification_header: "X-A" })))
      .toEqual({ display_name: "Hook", verification: "basic", secret: "u:p" });
    expect(draftBody(draft({ verification: "hmac_sha256", secret: "k", verification_header: "X-S" })))
      .toEqual({ display_name: "Hook", verification: "hmac_sha256", secret: "k", verification_header: "X-S" });
  });

  it("knows which schemes name a header", () => {
    expect((Object.keys(VERIFICATIONS) as (keyof typeof VERIFICATIONS)[]).filter(needsHeader))
      .toEqual(["header_secret", "hmac_sha256"]);
  });
});

describe("the listener's lines", () => {
  it("says whether it is taking events and how many it has", () => {
    expect(statusText({ running: true, events: 1 })).toBe("Running · 1 event received");
    expect(statusText({ running: false, events: 0 }))
      .toBe("Stopped · requests are refused until it is started · 0 events received");
  });

  it("names the scheme and its header", () => {
    expect(verificationText({ verification: "none", verification_header: null })).toBe("None");
    expect(verificationText({ verification: "hmac_sha256", verification_header: "X-Sig" }))
      .toBe("HMAC-SHA256 signature (X-Sig)");
  });

  it("gives a command that sends one event", () => {
    expect(curlExample("https://h/api/listen/t")).toBe(
      `curl -X POST -H 'Content-Type: application/json' -d '{"hello": "listener"}' https://h/api/listen/t`);
  });
});
