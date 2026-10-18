/** The pages' Content-Security-Policy (§993), as directives. What a browser
 * does with it is `e2e/test_security_headers.py`'s, and every signed-in
 * browser test fails on a load the policy refused (`e2e/conftest.py`). */
import { describe, expect, it } from "vitest";
import { contentSecurityPolicy } from "../../csp.mjs";

function directives(policy: string): Record<string, string[]> {
  return Object.fromEntries(
    policy.split(";").map((part) => {
      const [name = "", ...values] = part.trim().split(/\s+/);
      return [name, values];
    }),
  );
}

describe("a build's policy", () => {
  const built = directives(contentSecurityPolicy());

  it("loads scripts from this origin and evaluates no strings", () => {
    expect(built["script-src"]).toEqual(["'self'", "'unsafe-inline'"]);
    expect(built["default-src"]).toEqual(["'self'"]);
  });

  it("sends requests to this origin and Cognito, and nowhere else", () => {
    expect(built["connect-src"]).toEqual(["'self'", "https://*.amazoncognito.com"]);
  });

  it("keeps what §860 said", () => {
    expect(built["object-src"]).toEqual(["'none'"]);
    expect(built["base-uri"]).toEqual(["'self'"]);
    expect(built["form-action"]).toEqual(["'self'"]);
    expect(built["frame-ancestors"]).toEqual(["'self'"]);
  });

  it("lets a module show media and frame pages from where its author points", () => {
    expect(built["img-src"]).toEqual(["*", "data:", "blob:"]);
    expect(built["frame-src"]).toEqual(["*"]);
  });
});

describe("next dev's", () => {
  it("adds hot reload's eval and socket, and only those", () => {
    const dev = directives(contentSecurityPolicy({ development: true }));
    const built = directives(contentSecurityPolicy());
    expect(dev["script-src"]).toEqual([...built["script-src"]!, "'unsafe-eval'"]);
    expect(dev["connect-src"]).toEqual([...built["connect-src"]!, "ws:", "wss:"]);
    const others = (d: Record<string, string[]>) =>
      Object.fromEntries(Object.entries(d).filter(([k]) => k !== "script-src" && k !== "connect-src"));
    expect(others(dev)).toEqual(others(built));
  });
});

describe("a stack's own Cognito domain", () => {
  it("is already covered when it is Cognito's", () => {
    const policy = contentSecurityPolicy({
      cognitoDomain: "https://platform-acme.auth.eu-west-1.amazoncognito.com",
    });
    expect(directives(policy)["connect-src"]).toEqual(["'self'", "https://*.amazoncognito.com"]);
  });

  it("is named when it is a custom one", () => {
    const policy = contentSecurityPolicy({ cognitoDomain: "https://login.acme.example/" });
    expect(directives(policy)["connect-src"]).toEqual([
      "'self'", "https://*.amazoncognito.com", "https://login.acme.example"]);
  });
});
