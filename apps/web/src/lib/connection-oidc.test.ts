import { describe, expect, it } from "vitest";
import { trustLines, usesOidc } from "./connection-oidc";

describe("an OpenID Connect source (§599, p.391)", () => {
  it("is one that names a role", () => {
    expect(usesOidc({ oidc_role_arn: "arn:aws:iam::123456789012:role/r" })).toBe(true);
    expect(usesOidc({ oidc_role_arn: "  " })).toBe(false);
    expect(usesOidc({ bucket: "b" })).toBe(false);
    expect(usesOidc({ oidc_role_arn: 3 })).toBe(false);
  });

  it("says what its trust policy names", () => {
    expect(trustLines({ issuer: "https://p/api/oidc", audience: "sts.amazonaws.com",
      subject: "connection.1" })).toEqual([
      ["Issuer", "https://p/api/oidc"], ["Audience", "sts.amazonaws.com"],
      ["Subject", "connection.1"]]);
    expect(trustLines({ issuer: null, audience: null, subject: null })[0])
      .toEqual(["Issuer", "not set up on this platform"]);
  });
});
