import { afterEach, describe, expect, it, vi } from "vitest";
import { reportPageError } from "./api";
import { pageErrorReport } from "./page-error";

/** §926: how the error page tells the operators. */
describe("reportPageError", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the report, with the session header the API asks of a cookie, and lets it outlive a reload", () => {
    const fetch = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetch);
    const report = pageErrorReport({ message: "boom" }, "/acme");
    reportPageError(report);
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/client-errors");
    expect(init.method).toBe("POST");
    expect(init.keepalive).toBe(true);
    expect((init.headers as Record<string, string>)["X-Anchor-Session"]).toBe("1");
    expect(JSON.parse(init.body as string)).toEqual(report);
  });

  it("never throws, whether fetch fails or rejects", async () => {
    vi.stubGlobal("fetch", vi.fn(() => { throw new Error("no network"); }));
    expect(() => reportPageError(pageErrorReport(null, "/"))).not.toThrow();
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    expect(() => reportPageError(pageErrorReport(null, "/"))).not.toThrow();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
});
