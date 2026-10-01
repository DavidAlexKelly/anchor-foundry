import { describe, expect, it } from "vitest";

import { STEP_LABELS, stepLabel, summary } from "./diagnose";

const step = (name: string, status: "ok" | "failed" | "skipped" | "info", hint: string | null = null) =>
  ({ name, status, detail: `${name} detail`, hint });

describe("Diagnose's answer (§646)", () => {
  it("names each step by the question it asks", () => {
    expect(Object.keys(STEP_LABELS)).toEqual(["destination", "egress", "dns", "tcp", "tls", "credentials"]);
    expect(stepLabel(step("dns", "ok"))).toBe("Name resolves");
    expect(stepLabel(step("carrier", "ok"))).toBe("carrier");
  });

  it("says where it stopped and what to do", () => {
    expect(summary({ ok: true, steps: [step("dns", "ok"), step("tls", "info")] })).toBe("Every step passed.");
    expect(summary({ ok: false, steps: [
      step("dns", "ok"), step("tcp", "failed", "Check the port."), step("tls", "skipped"),
    ] })).toBe("Stopped at port accepts a connection: Check the port.");
    // A failure with no hint says what happened instead.
    expect(summary({ ok: false, steps: [step("egress", "failed")] }))
      .toBe("Stopped at egress policies: egress detail");
  });
});
