import { describe, expect, it } from "vitest";
import { pageErrorKind, pageErrorReport } from "./page-error";

describe("pageErrorKind", () => {
  it("calls a chunk missing after a deploy stale", () => {
    expect(pageErrorKind({ name: "ChunkLoadError", message: "x" })).toBe("stale");
    expect(pageErrorKind({ message: "Loading chunk 4512 failed." })).toBe("stale");
    expect(pageErrorKind({ message: "Loading CSS chunk app-pages failed" })).toBe("stale");
    expect(pageErrorKind({ message: "Failed to fetch dynamically imported module: /_next/x.js" })).toBe("stale");
    expect(pageErrorKind({ message: "Importing a module script failed." })).toBe("stale");
  });

  it("calls anything else a fault in the page", () => {
    expect(pageErrorKind({ name: "TypeError", message: "x is undefined" })).toBe("fault");
    expect(pageErrorKind({ message: "Request failed with status 500" })).toBe("fault");
    expect(pageErrorKind(null)).toBe("fault");
    expect(pageErrorKind({})).toBe("fault");
  });
});

describe("pageErrorReport (§926)", () => {
  it("sends the path without a query string or fragment, which can carry a token", () => {
    const report = pageErrorReport({ message: "boom" }, "/acme/p/objects?token=secret#x");
    expect(report.path).toBe("/acme/p/objects");
    expect(JSON.stringify(report)).not.toContain("secret");
  });

  it("cuts every field to what the API takes", () => {
    const long = "x".repeat(10_000);
    const report = pageErrorReport({ message: long, stack: long, digest: long }, `/${long}`);
    expect(report.message).toHaveLength(500);
    expect(report.stack).toHaveLength(4000);
    expect(report.digest).toHaveLength(100);
    expect(report.path).toHaveLength(300);
  });

  it("says which kind it is, so a stale page is not counted as a fault", () => {
    expect(pageErrorReport({ name: "ChunkLoadError", message: "x" }, "/").kind).toBe("stale");
    expect(pageErrorReport({ message: "x is undefined" }, "/").kind).toBe("fault");
  });

  it("has something to say about an error with no message", () => {
    expect(pageErrorReport(null, "/").message).toBe("unknown error");
    expect(pageErrorReport({ name: "TypeError" }, "/")).toMatchObject({
      message: "TypeError", digest: null, stack: null });
  });
});
