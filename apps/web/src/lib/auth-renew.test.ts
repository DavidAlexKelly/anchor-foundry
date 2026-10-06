import { describe, expect, it, vi } from "vitest";
import { renewSession } from "./auth";

// §859: one renewal for every request a session's expiry fails at once.
function answering(...oks: boolean[]) {
  const fetcher = vi.fn(async () => {
    await new Promise((done) => setTimeout(done, 5));
    return { ok: oks.shift() ?? false } as Response;
  });
  return fetcher as unknown as typeof fetch & typeof fetcher;
}

describe("renewSession", () => {
  it("asks once for all the requests waiting on it", async () => {
    const fetcher = answering(true);
    const answers = await Promise.all([renewSession(fetcher), renewSession(fetcher), renewSession(fetcher)]);
    expect(answers).toEqual([true, true, true]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith("/api/auth/refresh", expect.objectContaining({
      method: "POST", headers: { "X-Anchor-Session": "1" } }));
  });

  it("asks afresh once the last answer is in, and a refusal or a failure is false", async () => {
    const fetcher = answering(false);
    expect(await renewSession(fetcher)).toBe(false);
    const broken = vi.fn(async () => { throw new TypeError("offline"); }) as unknown as typeof fetch;
    expect(await renewSession(broken)).toBe(false);
    const again = answering(true);
    expect(await renewSession(again)).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(again).toHaveBeenCalledTimes(1);
  });
});
