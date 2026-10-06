import { describe, expect, it } from "vitest";
import { resolveCognitoConfig } from "./auth";

// Where the sign-in page sends a person (§851): what the API says this stack's
// hosted UI is, ahead of anything the build carried.
const back = "https://d1.cloudfront.net/callback";
const built = { domain: "https://built.auth.eu-west-2.amazoncognito.com", clientId: "built" };
const told = { domain: "https://told.auth.eu-west-2.amazoncognito.com", client_id: "told" };

describe("resolveCognitoConfig", () => {
  it("takes the API's answer over the build's", () => {
    expect(resolveCognitoConfig(told, built, back)).toEqual({
      domain: told.domain, clientId: "told", redirectUri: back,
    });
  });

  it("falls back to the build when the API has none, as in development", () => {
    expect(resolveCognitoConfig({ domain: null, client_id: null }, built, back)?.clientId).toBe("built");
    expect(resolveCognitoConfig(null, built, back)?.clientId).toBe("built");
  });

  it("has nothing to offer when neither says, and never half of one", () => {
    expect(resolveCognitoConfig(null, {}, back)).toBeNull();
    expect(resolveCognitoConfig({ domain: told.domain, client_id: null }, { domain: built.domain }, back))
      .toBeNull();
  });
});
