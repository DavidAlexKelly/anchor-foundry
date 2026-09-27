import { describe, expect, it } from "vitest";
import { viewerZone } from "./viewer-zone";

describe("the viewer's time zone (§596)", () => {
  it("is what the browser names", () => {
    expect(viewerZone(() => "Europe/Paris")).toBe("Europe/Paris");
    // `check.sh unit` runs with TZ set, so the default reads it.
    expect(viewerZone()).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  });

  it("is nothing when the browser will not say", () => {
    expect(viewerZone(() => "")).toBeUndefined();
    expect(viewerZone(() => undefined)).toBeUndefined();
    expect(viewerZone(() => { throw new Error("no Intl"); })).toBeUndefined();
  });
});
