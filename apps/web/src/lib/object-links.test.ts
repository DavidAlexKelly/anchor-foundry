import { describe, expect, it } from "vitest";

import {
  OBJECT_PARAM,
  decodeObject,
  encodeObject,
  missingNote,
} from "./object-links";

const TYPE = "3f2a1b9c-1111-4222-8333-444455556666";
const INSTANCE = "aabbccdd-7777-4888-9999-aaaabbbbcccc";

describe("naming one object in a link", () => {
  it("carries both halves", () => {
    // The instance store is partitioned by object type — one index per type —
    // so reading a single instance takes both ids. A link with only the
    // instance would need a search across every type in the workspace.
    expect(encodeObject({ typeId: TYPE, instanceId: INSTANCE })).toBe(
      `${TYPE}:${INSTANCE}`,
    );
  });

  it("reads back what it wrote", () => {
    const ref = { typeId: TYPE, instanceId: INSTANCE };
    expect(decodeObject(encodeObject(ref))).toEqual(ref);
  });

  it("uses one parameter, so half a link is malformed rather than plausible", () => {
    // `?objectType=…` with no instance would look like a filter.
    expect(OBJECT_PARAM).toBe("object");
  });
});

describe("a link that does not name an object", () => {
  it("is nothing at all", () => {
    expect(decodeObject(null)).toBeNull();
    expect(decodeObject("")).toBeNull();
  });

  it("is a value with no separator", () => {
    expect(decodeObject(TYPE)).toBeNull();
  });

  it("is a value cut short, which is what a chat client does to a long URL", () => {
    expect(decodeObject(`${TYPE}:aabbccdd-7777`)).toBeNull();
    expect(decodeObject(`${TYPE}:`)).toBeNull();
  });

  it("is a separator with nothing before it", () => {
    expect(decodeObject(`:${INSTANCE}`)).toBeNull();
  });

  it("is anything that is not a pair of UUIDs", () => {
    // Both halves go into a request path, so a value that cannot name an
    // object here is refused before it costs a round trip that could only
    // ever 404 — and nothing else reaches the URL this browser builds.
    expect(decodeObject("../../etc:passwd")).toBeNull();
    expect(decodeObject(`${TYPE}:<script>`)).toBeNull();
    expect(decodeObject(`not-a-uuid:${INSTANCE}`)).toBeNull();
  });

  it("accepts the same UUID however it was cased", () => {
    const ref = decodeObject(`${TYPE.toUpperCase()}:${INSTANCE}`);
    expect(ref).not.toBeNull();
    expect(ref!.typeId).toBe(TYPE.toUpperCase());
  });
});

describe("what a dead link says", () => {
  it("tells a deleted object from a broken link", () => {
    // The remedies differ: a deleted object is gone and the reader should
    // stop looking; a link that arrived broken can be asked for again.
    expect(missingNote(true)).toContain("no longer here");
    expect(missingNote(false)).toContain("cut short");
  });

  it("does not blame the reader's link for a deletion", () => {
    expect(missingNote(true)).not.toContain("cut short");
    expect(missingNote(false)).not.toContain("deleted");
  });
});
