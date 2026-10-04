/** An outbound application's screens (§754; decision 0022). */
import { describe, expect, it } from "vitest";
import {
  grantText, isOutbound, returnNotice, showsField, withoutReturn,
} from "./outbound-app";

describe("which sources are called as their user", () => {
  it("is the authorization-code auth type and no other", () => {
    expect(isOutbound({ auth_type: "oauth2_authorization_code" })).toBe(true);
    expect(isOutbound({ auth_type: "oauth2_client_credentials" })).toBe(false);
    expect(isOutbound({})).toBe(false);
  });

  it("shows the application's fields only for it", () => {
    const outbound = { auth_type: "oauth2_authorization_code" };
    const other = { auth_type: "bearer" };
    expect(showsField("authorize_url", outbound)).toBe(true);
    expect(showsField("oauth_scope", outbound)).toBe(true);
    expect(showsField("authorize_url", other)).toBe(false);
    expect(showsField("oauth_scope", other)).toBe(false);
    // Every other field is the form's as before.
    expect(showsField("token_url", other)).toBe(true);
    expect(showsField("base_url", outbound)).toBe(true);
  });
});

describe("the caller's grant", () => {
  const none = { authorized: false, scope: null, expires_at: null, granted_at: null };

  it("says p.40's first check when there is none", () => {
    expect(grantText(none)).toBe(
      "You have not authorized this source. It is called as whoever uses it, " +
      "so authorize it before testing, exploring or syncing it.");
  });

  it("names the scope granted, when the provider said one", () => {
    const granted = { ...none, authorized: true, granted_at: "2026-10-03T09:00:00Z" };
    expect(grantText({ ...granted, scope: "read" })).toBe(
      "You have authorized this source with scope read. Calls on it are made as you.");
    expect(grantText(granted)).toBe(
      "You have authorized this source. Calls on it are made as you.");
  });
});

describe("the provider sending the person back", () => {
  it("says each outcome", () => {
    expect(returnNotice("?authorization=granted")).toEqual(
      { ok: true, text: "Authorized. Calls on the source are now made as you." });
    expect(returnNotice("?authorization=denied&reason=access_denied")).toEqual(
      { ok: false, text: "The provider did not authorize the source (access_denied)." });
    expect(returnNotice("?authorization=denied")).toEqual(
      { ok: false, text: "The provider did not authorize the source." });
    expect(returnNotice("?authorization=failed&reason=bad+code")).toEqual(
      { ok: false, text: "Authorization failed (bad code). Try again from the source." });
  });

  it("is nothing on an address without one", () => {
    expect(returnNotice("")).toBeNull();
    expect(returnNotice("?authorization=maybe")).toBeNull();
    expect(returnNotice("?tab=webhooks")).toBeNull();
  });

  it("is taken off the address, and nothing else is", () => {
    expect(withoutReturn("/w/p/connections", "?authorization=failed&reason=x")).toBe(
      "/w/p/connections");
    expect(withoutReturn("/w/p/connections", "?tab=x&authorization=granted")).toBe(
      "/w/p/connections?tab=x");
  });
});
