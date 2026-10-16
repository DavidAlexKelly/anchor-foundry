import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { retryQuery } from "./query-retry";

describe("retryQuery (§959)", () => {
  it("asks once more after a failure that may pass", () => {
    for (const status of [500, 502, 503, 504, 408, 429]) {
      expect(retryQuery(0, new ApiError(status, "x"))).toBe(true);
    }
    expect(retryQuery(0, new TypeError("Failed to fetch"))).toBe(true);
  });

  it("does not ask again for the API's own answer", () => {
    for (const status of [400, 403, 404, 409, 413, 422]) {
      expect(retryQuery(0, new ApiError(status, "x"))).toBe(false);
    }
  });

  it("asks once, not twice", () => {
    expect(retryQuery(1, new ApiError(503, "x"))).toBe(false);
    expect(retryQuery(1, new TypeError("Failed to fetch"))).toBe(false);
  });
});

describe("the app's query client", () => {
  it("retries by that rule", async () => {
    const { newQueryClient } = await import("./query-client");
    expect(newQueryClient().getDefaultOptions().queries?.retry).toBe(retryQuery);
  });
});
