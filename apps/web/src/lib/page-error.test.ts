import { describe, expect, it } from "vitest";
import { pageErrorKind } from "./page-error";

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
