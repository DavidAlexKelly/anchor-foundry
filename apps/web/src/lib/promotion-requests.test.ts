/** p.255's proposals to promote an object type (§767). */
import { describe, expect, it } from "vitest";

import type { PromotionRequest } from "@/lib/types";
import { pendingFor, promotionOffer, requestLine } from "./promotion-requests";

function request(over: Partial<PromotionRequest> = {}): PromotionRequest {
  return {
    id: "r1", object_type_id: "t1", object_type_api_name: "site",
    object_type_name: "Site", object_type_status: "active",
    requested_by: "u1", requested_by_name: "Ada", reason: "Used by every app",
    state: "pending", decided_by: null, decided_by_name: "", decision_note: "",
    decided_at: null, created_at: "2026-01-01T00:00:00Z", mine: true,
    ...over,
  };
}

describe("the proposal waiting about a type", () => {
  it("is the pending one for that type only", () => {
    const mine = request();
    const other = request({ id: "r2", object_type_id: "t2" });
    const answered = request({ id: "r3", state: "rejected" });
    expect(pendingFor([answered, other, mine], "t1")).toBe(mine);
    expect(pendingFor([answered, other], "t1")).toBeNull();
    expect(pendingFor([], "t1")).toBeNull();
  });
});

describe("what the editor offers in place of promoted", () => {
  it("offers nothing to somebody who may promote, or for a promoted type", () => {
    expect(promotionOffer("active", true, null)).toBe("none");
    expect(promotionOffer("promoted", false, null)).toBe("none");
  });

  it("offers a proposal otherwise, and says when one is waiting", () => {
    expect(promotionOffer("active", false, null)).toBe("ask");
    expect(promotionOffer("experimental", false, request())).toBe("waiting");
  });
});

describe("a proposal in one line", () => {
  it("says who asked and why", () => {
    expect(requestLine(request())).toBe("Ada asked: Used by every app");
    expect(requestLine(request({ reason: "  " }))).toBe("Ada asked, giving no reason.");
    expect(requestLine(request({ requested_by_name: "" }))).toBe(
      "Somebody asked: Used by every app");
  });
});
