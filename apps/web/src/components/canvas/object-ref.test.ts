import { describe, expect, it } from "vitest";

import { REF_SEPARATOR, refFor } from "./object-ref";

const TYPE = "22222222-2222-2222-2222-222222222222";
const INSTANCE = "11111111-1111-1111-1111-111111111111";

function picked(over: Record<string, unknown> = {}) {
  return {
    id: INSTANCE,
    object_type_id: TYPE,
    primary_key: "R1",
    properties: { name: "North" },
    ...over,
  };
}

describe("refFor", () => {
  it("names the type and the instance", () => {
    expect(refFor(picked())).toBe(`${TYPE}${REF_SEPARATOR}${INSTANCE}`);
  });

  it("carries no properties", () => {
    // A reference, not a snapshot: properties in a link are values somebody
    // could edit by hand before sending it on, and the recipient could not
    // tell. p.199 says RID for the same reason.
    const ref = refFor(picked())!;
    expect(ref).not.toContain("North");
    expect(ref).not.toContain("R1");
  });

  it("answers null when nothing is picked", () => {
    // The state a detail panel is in before the first click. `routingParams`
    // reads null as "this key does not belong in the address".
    for (const value of [null, undefined, "", 7, [], {}]) {
      expect(refFor(value)).toBeNull();
    }
  });

  it("answers null for an object missing either half", () => {
    // Half a reference is not a shorter reference — it is one the reader
    // cannot resolve, and writing it would be the half-working link that
    // `ROUTABLE_KINDS` exists to prevent.
    expect(refFor(picked({ id: undefined }))).toBeNull();
    expect(refFor(picked({ object_type_id: undefined }))).toBeNull();
    expect(refFor(picked({ id: "" }))).toBeNull();
    expect(refFor(picked({ object_type_id: "" }))).toBeNull();
  });

  it("answers null when either half is not a string", () => {
    expect(refFor(picked({ id: 7 }))).toBeNull();
    expect(refFor(picked({ object_type_id: { nested: true } }))).toBeNull();
  });
});
