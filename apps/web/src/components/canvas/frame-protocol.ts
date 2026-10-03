/**
 * The Iframe's Bidirectional mode, with no React in it (`workshop` p.552-553;
 * decision 0023; §756).
 *
 * > "This enables the embedded application to act as if it were any other
 * > Workshop widget, with the ability to read from and write to Workshop
 * > variables, as well as execute Workshop events." (p.552)
 *
 * The framed application says what it needs (a definition of fields and
 * events), the builder binds each field to a variable and wires each event,
 * and the two then talk by `postMessage`. Everything here is a decision about
 * one message, so a test can ask about it without a frame.
 */

/** Every message's `type` begins with this (decision 0023 §1). */
export const PREFIX = "anchor-widget//";
export const VERSION = 1;

export const MESSAGE = {
  definition: `${PREFIX}definition`,
  requestDefinition: `${PREFIX}request-definition`,
  values: `${PREFIX}values`,
  setValue: `${PREFIX}set-value`,
  executeEvent: `${PREFIX}execute-event`,
} as const;

/** The variable kinds a field may be: the ones with a plain JSON value. An
 * object or an object set needs an ontology SDK on the far side (p.552). */
export const FIELD_TYPES = ["string", "number", "boolean", "date", "timestamp"] as const;
export type FieldType = (typeof FIELD_TYPES)[number];

export const ACCESS = ["read", "write", "read_write"] as const;
export type Access = (typeof ACCESS)[number];

export const MAX_FIELDS = 50;
export const MAX_EVENTS = 50;
const ID = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;

export interface FrameField {
  id: string;
  label: string;
  type: FieldType;
  access: Access;
}

export interface FrameEvent {
  id: string;
  label: string;
}

export interface FrameDefinition {
  fields: FrameField[];
  events: FrameEvent[];
}

/** What a frame may say, read off `MessageEvent.data`. */
export type Incoming =
  | { type: "definition"; definition: FrameDefinition }
  | { type: "set-value"; fieldId: string; value: unknown }
  | { type: "execute-event"; eventId: string };

function labelOf(raw: unknown, id: string): string {
  return typeof raw === "string" && raw.trim() ? raw.trim().slice(0, 100) : id;
}

/** A definition, or null when any part of it is not one: a definition is
 * taken whole or not at all, since half of one would bind some fields and
 * silently drop the rest. */
export function parseDefinition(data: Record<string, unknown>): FrameDefinition | null {
  const rawFields = data.fields ?? [];
  const rawEvents = data.events ?? [];
  if (!Array.isArray(rawFields) || !Array.isArray(rawEvents)) return null;
  if (rawFields.length > MAX_FIELDS || rawEvents.length > MAX_EVENTS) return null;
  const fields: FrameField[] = [];
  for (const f of rawFields) {
    if (!f || typeof f !== "object") return null;
    const { id, label, type, access } = f as Record<string, unknown>;
    if (typeof id !== "string" || !ID.test(id)) return null;
    if (!(FIELD_TYPES as readonly unknown[]).includes(type)) return null;
    if (access !== undefined && !(ACCESS as readonly unknown[]).includes(access)) return null;
    if (fields.some((other) => other.id === id)) return null;
    fields.push({
      id, label: labelOf(label, id), type: type as FieldType,
      access: (access as Access | undefined) ?? "read_write",
    });
  }
  const events: FrameEvent[] = [];
  for (const e of rawEvents) {
    if (!e || typeof e !== "object") return null;
    const { id, label } = e as Record<string, unknown>;
    if (typeof id !== "string" || !ID.test(id)) return null;
    if (events.some((other) => other.id === id)) return null;
    events.push({ id, label: labelOf(label, id) });
  }
  return { fields, events };
}

/** One message from a frame, or null for anything that is not ours: another
 * library's message, a version this does not speak, a malformed body. */
export function readMessage(data: unknown): Incoming | null {
  if (!data || typeof data !== "object") return null;
  const body = data as Record<string, unknown>;
  if (body.version !== VERSION || typeof body.type !== "string") return null;
  switch (body.type) {
    case MESSAGE.definition: {
      const definition = parseDefinition(body);
      return definition ? { type: "definition", definition } : null;
    }
    case MESSAGE.setValue:
      return typeof body.fieldId === "string" && "value" in body
        ? { type: "set-value", fieldId: body.fieldId, value: body.value }
        : null;
    case MESSAGE.executeEvent:
      return typeof body.eventId === "string" ? { type: "execute-event", eventId: body.eventId } : null;
    default:
      return null;
  }
}

/** The origin a frame of this URL speaks from, which is the only one its
 * messages are read from and the only one sent to (decision 0023 §2). A path
 * on this platform is this platform's origin. Null when there is none to
 * name, so nothing is sent. */
export function frameOrigin(url: string | null, base: string): string | null {
  if (!url) return null;
  try {
    const origin = new URL(url, base).origin;
    return origin === "null" ? null : origin;
  } catch {
    return null;
  }
}

/** The variables the panel offers a field: of its own kind, since a string
 * variable bound to a number field would be a write the frame cannot make;
 * and, for a field the frame writes, not derived ones, which are computed
 * rather than set. */
export function bindable<V extends { id: string; kind: string; derivation?: unknown }>(
  field: FrameField, declared: readonly V[],
): V[] {
  return declared.filter((v) => v.kind === field.type && (field.access === "read" || !v.derivation));
}

/** What the frame is sent: every bound field it may read, with the value and
 * whether it is still loading (p.553: "each time the value or loading state
 * of the variable changes"). A field the saved definition lacks is not
 * bound, whatever a binding says. */
export function valuesOf(
  definition: FrameDefinition | null,
  bindings: Record<string, string>,
  resolved: Record<string, unknown>,
  loading: boolean,
): Record<string, { value: unknown; loading: boolean }> {
  const out: Record<string, { value: unknown; loading: boolean }> = {};
  for (const field of definition?.fields ?? []) {
    const variable = bindings[field.id];
    if (!variable || field.access === "write") continue;
    const value = resolved[variable];
    out[field.id] = { value: value === undefined ? null : value, loading: loading && value === undefined };
  }
  return out;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;

function ofType(type: FieldType, value: unknown): boolean {
  if (value === null) return true;
  switch (type) {
    case "string":
      return typeof value === "string";
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "boolean":
      return typeof value === "boolean";
    case "date":
      return typeof value === "string" && DATE.test(value) && !Number.isNaN(Date.parse(value));
    case "timestamp":
      return typeof value === "string" && !DATE.test(value) && !Number.isNaN(Date.parse(value));
  }
}

/** Whether a frame's write lands, and on which variable, or why it does not
 * (decision 0023 §3). The reason goes to the console, for the application's
 * author: a viewer did nothing wrong. */
export function acceptWrite(
  definition: FrameDefinition | null,
  bindings: Record<string, string>,
  declared: Record<string, { kind: string; derivation?: unknown }>,
  fieldId: string,
  value: unknown,
): { ok: true; variable: string; value: unknown } | { ok: false; reason: string } {
  const field = definition?.fields.find((f) => f.id === fieldId);
  if (!field) return { ok: false, reason: `the module asked for no field "${fieldId}"` };
  if (field.access === "read") return { ok: false, reason: `"${fieldId}" is read-only` };
  const variable = bindings[fieldId];
  if (!variable || !declared[variable]) {
    return { ok: false, reason: `"${fieldId}" is not bound to a variable` };
  }
  if (declared[variable].derivation) {
    return { ok: false, reason: `"${fieldId}" is bound to a derived variable, which is computed, not set` };
  }
  if (!ofType(field.type, value)) {
    return { ok: false, reason: `"${fieldId}" takes a ${field.type}` };
  }
  return { ok: true, variable, value };
}

/** Whether the frame may fire this event: it is one the saved definition
 * requests. Whether anything is wired to it is the events' own question. */
export function knownEvent(definition: FrameDefinition | null, eventId: string): boolean {
  return (definition?.events ?? []).some((e) => e.id === eventId);
}

/** The same definition, by value, so the builder does not rewrite the widget
 * (and mark the module unsaved) each time the frame says it again. */
export function sameDefinition(a: FrameDefinition | null, b: FrameDefinition | null): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** A saved definition read back off the widget's props, defensively: a
 * document is anybody's JSON. */
export function savedDefinition(raw: unknown): FrameDefinition | null {
  if (!raw || typeof raw !== "object") return null;
  return parseDefinition(raw as Record<string, unknown>);
}
