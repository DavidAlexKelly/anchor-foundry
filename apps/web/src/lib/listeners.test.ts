/** §516: HTTPS listeners on the Data Connection screen. */
import { describe, expect, it } from "vitest";

import {
  BLANK_LISTENER, LISTENER_TYPES, ROTATIONS, archivedText, notArchivedText, waitingText, VERIFICATIONS, curlExample, draftBody, draftProblem,
  endpointState, extendedExpiry, needsHeader, rotateBody, schemesOf, statusText, whyNoRotation,
  withType,
  verificationText,
  allowlistDraft, ingressText, parseAllowlist,
  MAX_BODY, RATE_PER_SECOND, limitsText, throttledText,
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
    const c = { listener_type: "custom" };
    expect(draftBody(draft({ display_name: " Hook ", secret: "left", verification_header: "X-A" })))
      .toEqual({ display_name: "Hook", ...c, verification: "none" });
    expect(draftBody(draft({ verification: "basic", secret: "u:p", verification_header: "X-A" })))
      .toEqual({ display_name: "Hook", ...c, verification: "basic", secret: "u:p" });
    expect(draftBody(draft({ verification: "hmac_sha256", secret: "k", verification_header: "X-S" })))
      .toEqual({ display_name: "Hook", ...c, verification: "hmac_sha256", secret: "k", verification_header: "X-S" });
    // A named type's header is fixed, so none is sent.
    expect(draftBody(draft({ listener_type: "github", verification: "hmac_sha256", secret: "k", verification_header: "X-S" })))
      .toEqual({ display_name: "Hook", listener_type: "github", verification: "hmac_sha256", secret: "k" });
  });

  it("knows which schemes name a header, per type", () => {
    expect(schemesOf("custom").filter((v) => needsHeader("custom", v)))
      .toEqual(["header_secret", "hmac_sha256", "hmac_sha256_base64"]);
    expect(needsHeader("github", "hmac_sha256")).toBe(false);
    expect(needsHeader("slack", "none")).toBe(false);
  });
});

describe("the listener's lines", () => {
  it("says whether it is taking events and how many it has", () => {
    expect(statusText({ running: true, events: 1 })).toBe("Running · 1 event received");
    expect(statusText({ running: false, events: 0 }))
      .toBe("Stopped · requests are refused until it is started · 0 events received");
  });

  it("names the type, the scheme and its header", () => {
    expect(verificationText({ listener_type: "custom", verification: "none", verification_header: null }))
      .toBe("None");
    expect(verificationText({ listener_type: "custom", verification: "hmac_sha256", verification_header: "X-Sig" }))
      .toBe("HMAC-SHA256 signature (X-Sig)");
    expect(verificationText({ listener_type: "slack", verification: "slack_v0", verification_header: "X-Slack-Signature" }))
      .toBe("Slack · Slack signing secret (X-Slack-Signature)");
  });

  it("gives a command that sends one event", () => {
    expect(curlExample("https://h/api/listen/t")).toBe(
      `curl -X POST -H 'Content-Type: application/json' -d '{"hello": "listener"}' https://h/api/listen/t`);
  });
});

describe("endpoint rotation (§517)", () => {
  const now = Date.parse("2026-09-26T12:00:00Z");
  const at = (hours: number) => new Date(now + hours * 3_600_000).toISOString();

  it("says what each endpoint is doing", () => {
    expect(endpointState({ active: true, expired: false, expires_at: null }, now)).toBe("Active");
    expect(endpointState({ active: false, expired: true, expires_at: at(-1) }, now))
      .toBe("Expired: no longer answers");
    expect(endpointState({ active: false, expired: false, expires_at: at(1) }, now))
      .toBe("Retiring: answers for 1 more hour");
    expect(endpointState({ active: false, expired: false, expires_at: at(0.1) }, now))
      .toBe("Retiring: answers for 1 more hour");
    expect(endpointState({ active: false, expired: false, expires_at: at(23.6) }, now))
      .toBe("Retiring: answers for 24 more hours");
    expect(endpointState({ active: false, expired: false, expires_at: at(47) }, now))
      .toBe("Retiring: answers for 47 more hours");
    expect(endpointState({ active: false, expired: false, expires_at: at(72) }, now))
      .toBe("Retiring: answers for 3 more days");
  });

  it("rotates keeping the old address a day, or not at all", () => {
    expect(rotateBody("day", now)).toEqual({ expire_old_at: at(24) });
    expect(rotateBody("now", now)).toEqual({ expire_old_at: null });
    expect(Object.keys(ROTATIONS)).toEqual(["day", "now"]);
  });

  it("extends by a day from whichever is later", () => {
    expect(extendedExpiry(at(5), now)).toBe(at(29));
    expect(extendedExpiry(at(-5), now)).toBe(at(24));
  });

  it("says why a third endpoint is not offered", () => {
    expect(whyNoRotation([{ active: true }])).toBe("");
    expect(whyNoRotation([{ active: true }, { active: false }]))
      .toBe("A listener has at most two endpoints. Delete the one being retired to rotate again.");
  });
});

describe("named listener types (§518)", () => {
  it("offers each type's schemes, its default first", () => {
    expect(schemesOf("jira")).toEqual(["hmac_sha256", "none"]);
    expect(schemesOf("pubsub")).toEqual(["query_token"]);
    expect(Object.keys(LISTENER_TYPES))
      .toEqual(["custom", "slack", "jira", "github", "gitlab", "stripe", "shopify", "pubsub",
        "bitbucket", "meta", "azure_event_grid", "jotform", "pagerduty", "zendesk", "airtable"]);
    // §591: Jotform signs nothing, so a token in its address is the default.
    expect(schemesOf("jotform")).toEqual(["query_token", "none"]);
  });

  it("moves a draft onto the new type's default", () => {
    const moved = withType(draft({ verification: "basic", secret: "u:p" }), "stripe");
    expect([moved.listener_type, moved.verification, moved.secret]).toEqual(["stripe", "stripe_v1", "u:p"]);
  });

  it("asks for Airtable's MAC secret as base64 (§591)", () => {
    expect(draftProblem(draft({ listener_type: "airtable", verification: "airtable", secret: "not base64!" })))
      .toBe("Airtable's MAC secret is the base64 text Airtable gave.");
    // Unpadded, as the server's decoder refuses it too.
    expect(draftProblem(draft({ listener_type: "airtable", verification: "airtable", secret: "c2VjcmV" })))
      .toBe("Airtable's MAC secret is the base64 text Airtable gave.");
    for (const secret of ["c2VjcmV0", "c2VjcmU=", "c2VjcmV0cw=="]) {
      expect(draftProblem(draft({ listener_type: "airtable", verification: "airtable", secret }))).toBe("");
    }
  });

  it("asks a named type for its secret and nothing else", () => {
    expect(draftProblem(draft({ listener_type: "github", verification: "hmac_sha256", secret: "" })))
      .toBe("This verification needs a secret.");
    expect(draftProblem(draft({ listener_type: "github", verification: "hmac_sha256", secret: "k" }))).toBe("");
  });

  it("labels every scheme a type can offer", () => {
    for (const type of Object.keys(LISTENER_TYPES) as (keyof typeof LISTENER_TYPES)[]) {
      for (const v of schemesOf(type)) expect(VERIFICATIONS[v].label, v).toBeTruthy();
    }
  });
});

describe("the archive (§519)", () => {
  it("says how many events are waiting, and what makes the dataset", () => {
    expect([0, 1, 3].map(waitingText)).toEqual(["nothing waiting", "1 event waiting", "3 events waiting"]);
    expect(notArchivedText(2))
      .toBe("Not archived yet · 2 events waiting. The first archive makes the dataset.");
  });

  it("says what Archive now did", () => {
    expect(archivedText({ archived: 0, version: null })).toBe("Nothing new to archive.");
    expect(archivedText({ archived: 1, version: 4 })).toBe("Archived 1 event as version 4.");
    expect(archivedText({ archived: 2, version: 1 })).toBe("Archived 2 events as version 1.");
  });
});

describe("ingress (§520)", () => {
  it("reads ranges one per line, or by commas or spaces, blanks dropped", () => {
    expect(parseAllowlist("10.0.0.0/8\n\n  192.0.2.7 ,2001:db8::/32\t203.0.113.0/24\n"))
      .toEqual(["10.0.0.0/8", "192.0.2.7", "2001:db8::/32", "203.0.113.0/24"]);
    expect(parseAllowlist("")).toEqual([]);
    expect(parseAllowlist(" \n, ")).toEqual([]);
  });

  it("opens the editor with the saved ranges, and reads them back unchanged", () => {
    const ranges = ["10.0.0.0/8", "192.0.2.7/32"];
    expect(allowlistDraft(ranges)).toBe("10.0.0.0/8\n192.0.2.7/32");
    expect(parseAllowlist(allowlistDraft(ranges))).toEqual(ranges);
    expect(allowlistDraft([])).toBe("");
  });

  it("says who may send", () => {
    expect(ingressText([])).toBe("Any address the platform accepts may send (inherited ingress).");
    expect(ingressText(["10.0.0.0/8"])).toBe("Only 10.0.0.0/8 may send.");
    expect(ingressText(["10.0.0.0/8", "192.0.2.7/32"]))
      .toBe("Only these 2 ranges may send: 10.0.0.0/8, 192.0.2.7/32.");
  });
});

describe("limits (§521)", () => {
  it("says p.261's rate and p.262's size", () => {
    expect(RATE_PER_SECOND).toBe(100);
    expect(MAX_BODY).toBe(1024 * 1024);
    expect(limitsText()).toBe(
      "Each listener takes up to 100 requests a second, each at most 1 MB. For more than that, use a streaming sync.");
  });

  it("says how many requests were refused for rate, and when", () => {
    const when = (iso: string) => `at ${iso}`;
    expect(throttledText({ throttled: 0, throttled_at: null }, when)).toBe("");
    expect(throttledText({ throttled: 1, throttled_at: "T" }, when))
      .toBe("1 request was refused over the limit of 100 a second, most recently at T.");
    expect(throttledText({ throttled: 12, throttled_at: "T" }, when))
      .toBe("12 requests were refused over the limit of 100 a second, most recently at T.");
    // A count with no time is not something the server says; nothing is shown.
    expect(throttledText({ throttled: 2, throttled_at: null }, when)).toBe("");
  });
});
