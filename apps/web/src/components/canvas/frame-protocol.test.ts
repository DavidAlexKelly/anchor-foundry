/** The Iframe's Bidirectional protocol (§756; decision 0023; `workshop`
 * p.552-553). */
import { describe, expect, it } from "vitest";
import {
  MAX_FIELDS, MESSAGE, VERSION, acceptWrite, bindable, frameOrigin, knownEvent,
  parseDefinition, readMessage, sameDefinition, savedDefinition, valuesOf,
  type FrameDefinition, type FrameField,
} from "./frame-protocol";

const DEF: FrameDefinition = {
  fields: [
    { id: "query", label: "Query", type: "string", access: "read_write" },
    { id: "count", label: "count", type: "number", access: "read" },
    { id: "picked", label: "Picked", type: "date", access: "write" },
  ],
  events: [{ id: "open", label: "Open details" }],
};

describe("a definition", () => {
  it("is read whole, with labels and access defaulted", () => {
    expect(parseDefinition({
      fields: [{ id: "query", label: " Query ", type: "string" }, { id: "count", type: "number", access: "read" }],
      events: [{ id: "open", label: "Open details" }],
    })).toEqual({
      fields: [
        { id: "query", label: "Query", type: "string", access: "read_write" },
        { id: "count", label: "count", type: "number", access: "read" },
      ],
      events: [{ id: "open", label: "Open details" }],
    });
    expect(parseDefinition({})).toEqual({ fields: [], events: [] });
  });

  it("is refused whole when any part is not one", () => {
    const field = { id: "a", type: "string" };
    expect(parseDefinition({ fields: [{ id: "a", type: "object_set" }] })).toBeNull();
    expect(parseDefinition({ fields: [{ id: "1a", type: "string" }] })).toBeNull();
    expect(parseDefinition({ fields: [{ id: "a", type: "string", access: "all" }] })).toBeNull();
    expect(parseDefinition({ fields: [field, field] })).toBeNull();
    expect(parseDefinition({ events: [{ id: "e" }, { id: "e" }] })).toBeNull();
    expect(parseDefinition({ events: [{ id: "has space" }] })).toBeNull();
    expect(parseDefinition({ fields: "a" })).toBeNull();
    expect(parseDefinition({ events: [null] })).toBeNull();
    expect(parseDefinition({ fields: [7] })).toBeNull();
  });

  it("has a ceiling on its size", () => {
    const many = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `f${i}`, type: "string" }));
    expect(parseDefinition({ fields: many(MAX_FIELDS) })?.fields).toHaveLength(MAX_FIELDS);
    expect(parseDefinition({ fields: many(MAX_FIELDS + 1) })).toBeNull();
    const events = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `e${i}` }));
    expect(parseDefinition({ events: events(MAX_FIELDS + 1) })).toBeNull();
  });
});

describe("a message", () => {
  const msg = (type: string, body: Record<string, unknown> = {}) => ({ type, version: VERSION, ...body });

  it("is one of ours, of this version", () => {
    expect(readMessage(msg(MESSAGE.definition, { fields: [], events: [] }))).toEqual(
      { type: "definition", definition: { fields: [], events: [] } });
    expect(readMessage(msg(MESSAGE.setValue, { fieldId: "query", value: null }))).toEqual(
      { type: "set-value", fieldId: "query", value: null });
    expect(readMessage(msg(MESSAGE.executeEvent, { eventId: "open" }))).toEqual(
      { type: "execute-event", eventId: "open" });
  });

  it("is nothing otherwise", () => {
    expect(readMessage({ ...msg(MESSAGE.executeEvent, { eventId: "open" }), version: 2 })).toBeNull();
    expect(readMessage(msg("WORKSHOP//TRIGGER_WORKSHOP_EVENT", { eventKey: "open" }))).toBeNull();
    expect(readMessage(msg(MESSAGE.setValue, { fieldId: "query" }))).toBeNull();
    expect(readMessage(msg(MESSAGE.setValue, { value: 1 }))).toBeNull();
    expect(readMessage(msg(MESSAGE.executeEvent))).toBeNull();
    expect(readMessage(msg(MESSAGE.definition, { fields: [{ id: "x", type: "object" }] }))).toBeNull();
    // The module's own messages are not a frame's.
    expect(readMessage(msg(MESSAGE.values, { values: {} }))).toBeNull();
    expect(readMessage("anchor-widget//definition")).toBeNull();
    expect(readMessage(null)).toBeNull();
    expect(readMessage({ version: VERSION })).toBeNull();
  });
});

describe("who a frame is", () => {
  const BASE = "https://anchor.example.com/w/p/apps/1";
  it("is its URL's origin, and this platform's for a path", () => {
    expect(frameOrigin("https://tool.example.org/app?x=1", BASE)).toBe("https://tool.example.org");
    expect(frameOrigin("/w/p/datasets", BASE)).toBe("https://anchor.example.com");
  });

  it("is nobody without a URL that names one", () => {
    expect(frameOrigin(null, BASE)).toBeNull();
    expect(frameOrigin("", BASE)).toBeNull();
    expect(frameOrigin("http://[bad", BASE)).toBeNull();
    expect(frameOrigin("about:blank", BASE)).toBeNull();
  });
});

describe("binding and sending", () => {
  const declared = [
    { id: "v_text", kind: "string" },
    { id: "v_derived", kind: "string", derivation: { kind: "x" } },
    { id: "v_num", kind: "number" },
  ];

  it("offers a field the variables of its kind, and no derived one to a writer", () => {
    const [query, count] = DEF.fields as [FrameField, FrameField];
    expect(bindable(query, declared).map((v) => v.id)).toEqual(["v_text"]);
    expect(bindable({ ...query, access: "read" }, declared).map((v) => v.id)).toEqual(
      ["v_text", "v_derived"]);
    expect(bindable(count, declared).map((v) => v.id)).toEqual(["v_num"]);
  });

  it("sends each bound field the frame may read, and whether it is loading", () => {
    const bindings = { query: "v_text", count: "v_num", picked: "v_date", stray: "v_text" };
    expect(valuesOf(DEF, bindings, { v_text: "hi", v_date: "2026-01-01" }, true)).toEqual({
      query: { value: "hi", loading: false },
      count: { value: null, loading: true },
    });
    expect(valuesOf(DEF, bindings, { v_text: "hi", v_num: 0 }, false)).toEqual({
      query: { value: "hi", loading: false },
      count: { value: 0, loading: false },
    });
    expect(valuesOf(DEF, {}, { v_text: "hi" }, false)).toEqual({});
    expect(valuesOf(null, bindings, { v_text: "hi" }, false)).toEqual({});
  });
});

describe("a write from the frame (decision 0023 §3)", () => {
  const declared = {
    v_text: { kind: "string" },
    v_derived: { kind: "string", derivation: { kind: "x" } },
    v_num: { kind: "number" },
    v_date: { kind: "date" },
    v_ts: { kind: "timestamp" },
  };
  const bindings = { query: "v_text", count: "v_num", picked: "v_date" };
  const write = (fieldId: string, value: unknown, over: Record<string, string> = {}, def = DEF) =>
    acceptWrite(def, { ...bindings, ...over }, declared, fieldId, value);

  it("lands on the bound variable", () => {
    expect(write("query", "abc")).toEqual({ ok: true, variable: "v_text", value: "abc" });
    expect(write("picked", "2026-10-03")).toEqual({ ok: true, variable: "v_date", value: "2026-10-03" });
    expect(write("query", null)).toEqual({ ok: true, variable: "v_text", value: null });
  });

  it("is refused for a field that is not asked for, read-only, or unbound", () => {
    expect(write("nope", "x")).toEqual({ ok: false, reason: 'the module asked for no field "nope"' });
    expect(write("count", 3)).toEqual({ ok: false, reason: '"count" is read-only' });
    expect(write("query", "x", { query: "" })).toEqual(
      { ok: false, reason: '"query" is not bound to a variable' });
    expect(write("query", "x", { query: "v_gone" })).toEqual(
      { ok: false, reason: '"query" is not bound to a variable' });
    expect(write("query", "x", {}, null as unknown as FrameDefinition)).toMatchObject({ ok: false });
  });

  it("is refused onto a derived variable", () => {
    expect(write("query", "x", { query: "v_derived" })).toEqual({
      ok: false, reason: '"query" is bound to a derived variable, which is computed, not set' });
  });

  it("must be of the field's type", () => {
    const typed = (type: string, value: unknown) => write("f", value, { f: "v_text" }, {
      fields: [{ id: "f", label: "f", type: type as "string", access: "write" }], events: [],
    }).ok;
    expect(typed("string", 1)).toBe(false);
    expect(typed("number", "1")).toBe(false);
    expect(typed("number", Number.NaN)).toBe(false);
    expect(typed("number", 2.5)).toBe(true);
    expect(typed("boolean", "true")).toBe(false);
    expect(typed("boolean", false)).toBe(true);
    expect(typed("date", "2026-10-03T00:00:00Z")).toBe(false);
    expect(typed("date", "2026-13-45")).toBe(false);
    expect(typed("date", "2026-10-03")).toBe(true);
    expect(typed("timestamp", "2026-10-03")).toBe(false);
    expect(typed("timestamp", "yesterday")).toBe(false);
    expect(typed("timestamp", "2026-10-03T09:00:00Z")).toBe(true);
    expect(write("picked", 20261003)).toMatchObject({ ok: false, reason: '"picked" takes a date' });
  });
});

describe("events and the saved definition", () => {
  it("knows only the events the definition asks for", () => {
    expect(knownEvent(DEF, "open")).toBe(true);
    expect(knownEvent(DEF, "close")).toBe(false);
    expect(knownEvent(null, "open")).toBe(false);
  });

  it("compares by value, and reads a saved one defensively", () => {
    expect(sameDefinition(DEF, JSON.parse(JSON.stringify(DEF)))).toBe(true);
    expect(sameDefinition(DEF, { ...DEF, events: [] })).toBe(false);
    expect(sameDefinition(null, null)).toBe(true);
    expect(savedDefinition(DEF)).toEqual(DEF);
    expect(savedDefinition("x")).toBeNull();
    expect(savedDefinition(null)).toBeNull();
    expect(savedDefinition({ fields: [{ id: "x", type: "object" }] })).toBeNull();
  });
});
