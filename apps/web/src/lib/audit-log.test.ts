import { describe, expect, it } from "vitest";
import {
  AUDIT_PAGE, NO_FILTERS, actorText, auditQuery, exportQuery, filterProblem, nextCursor,
  originText,
} from "./audit-log";
import type { AuditEntry } from "./types";

const entry = (id: number): AuditEntry => ({
  id, action: "dataset.export", resource_type: "dataset", resource_id: null, workspace_id: null,
  project_id: null, metadata: {}, actor_email: "ada@example.com", actor_name: "Ada",
  created_at: "2026-10-17T10:00:00Z",
});

describe("the audit log (§988)", () => {
  it("asks for what was chosen and nothing else", () => {
    expect(auditQuery(NO_FILTERS)).toBe(`limit=${AUDIT_PAGE}`);
    const q = new URLSearchParams(auditQuery({
      action: " dataset. ", userId: "u1", resourceId: "", since: "2026-10-01", until: "2026-10-16",
    }, 42));
    expect(q.get("action")).toBe("dataset.");
    expect(q.get("user_id")).toBe("u1");
    expect(q.has("resource_id")).toBe(false);
    expect(q.get("since")).toBe("2026-10-01T00:00:00Z");
    // The last day is the whole of it.
    expect(q.get("until")).toBe("2026-10-17T00:00:00.000Z");
    expect(q.get("before_id")).toBe("42");
  });

  it("pages on while a page is full", () => {
    const full = Array.from({ length: AUDIT_PAGE }, (_, i) => entry(1000 - i));
    expect(nextCursor(full)).toBe(1000 - AUDIT_PAGE + 1);
    expect(nextCursor(full.slice(1))).toBeUndefined();
  });

  it("says what is wrong with a filter before asking", () => {
    expect(filterProblem(NO_FILTERS)).toBe("");
    expect(filterProblem({ ...NO_FILTERS, resourceId: "not-an-id" })).toContain("by its id");
    expect(filterProblem({ ...NO_FILTERS, since: "2026-10-05", until: "2026-10-01" }))
      .toBe("The end of the span is before its start.");
  });

  it("says who and where from", () => {
    expect(actorText(entry(1))).toBe("Ada (ada@example.com)");
    expect(actorText({ actor_name: null, actor_email: null })).toBe("the platform");
    expect(actorText({ actor_name: "ada@example.com", actor_email: "ada@example.com" }))
      .toBe("ada@example.com");
    expect(originText({ ip_address: "10.0.0.1", user_agent: "curl/8.5" })).toBe("10.0.0.1 · curl/8.5");
    expect(originText({ ip_address: null, user_agent: null })).toBe("not recorded");
  });

  it("exports what is narrowed, every page of it (§989)", () => {
    expect(exportQuery(NO_FILTERS)).toBe("");
    expect(exportQuery({ ...NO_FILTERS, action: "model." })).toBe("action=model.");
  });
});
