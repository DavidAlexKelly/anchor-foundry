import { describe, expect, it } from "vitest";
import { callbackError, tokenFailure } from "./auth-errors";

describe("callbackError", () => {
  it("is nothing when Cognito sent no error", () => {
    expect(callbackError(new URLSearchParams("code=abc"))).toBeNull();
    expect(callbackError(new URLSearchParams(""))).toBeNull();
    expect(callbackError(new URLSearchParams("error=%20%20"))).toBeNull();
  });

  it("says what Cognito said, and its code", () => {
    expect(
      callbackError(new URLSearchParams("error=access_denied&error_description=User+is+disabled.")),
    ).toBe("User is disabled. (access_denied)");
  });

  it("names the code when there is no description", () => {
    expect(callbackError(new URLSearchParams("error=invalid_request"))).toBe(
      "Sign-in was refused (invalid_request)",
    );
    expect(callbackError(new URLSearchParams("error=invalid_request&error_description=+"))).toBe(
      "Sign-in was refused (invalid_request)",
    );
  });
});

describe("tokenFailure", () => {
  it("quotes the endpoint's error and description", () => {
    expect(
      tokenFailure(400, { error: "invalid_grant", error_description: "Code has expired" }),
    ).toBe("Token exchange failed: Code has expired (invalid_grant)");
  });

  it("quotes the error alone, with the status", () => {
    expect(tokenFailure(400, { error: "invalid_grant" })).toBe(
      "Token exchange failed: invalid_grant (400)",
    );
  });

  it("falls back to the status for a body that is not an OAuth error", () => {
    expect(tokenFailure(502, null)).toBe("Token exchange failed (502)");
    expect(tokenFailure(500, "<html>")).toBe("Token exchange failed (500)");
    expect(tokenFailure(400, { error: 7, error_description: "x" })).toBe(
      "Token exchange failed (400)",
    );
  });
});
