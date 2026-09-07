/**
 * Configuring a webhook (Foundry `data-connection` p.216-242; §261).
 *
 * §259 built the resource and §260 the action rule, and left both reachable
 * only by posting JSON. That is the shape §258 closed for the notify rule and
 * §252 before it: a feature the product cannot express is a feature that does
 * not exist for the person who would use it.
 *
 * The division is the usual one. The server owns what is **legal**
 * (`services/webhooks.parse`, which refuses every case below and several this
 * cannot see); this owns what is **offered** and what a form can say before a
 * round trip. They overlap in {@link problem}, because a refusal that arrives
 * on Save is a refusal about a form somebody has already left.
 *
 * **The body is the hard part of this form and the reason it is not a
 * textarea.** p.233 lists seven body types and the one that matters is
 * `Raw JSON` — a *document*, not a string, whose values may be references. A
 * plain textarea would let somebody type invalid JSON and find out on Save;
 * worse, it would hide the one distinction that decides what gets sent, which
 * is whether a value is exactly one reference (and keeps the input's type) or
 * merely contains one (and becomes text). So the editor is text with a live
 * parse, and {@link bodyProblem} is what it says.
 */

/** p.233's methods, in the order a request builder should offer them: the one
 * that reads first, then the ones that write, then the two that ask about a
 * resource without wanting it.
 *
 * The order is not the server's — `webhooks.METHODS` is grouped by safety,
 * because that is the question `system_changed` asks. Here the question is
 * "what am I doing", and `POST` belongs next to `GET` rather than after two
 * methods almost nobody configures. */
export const METHODS = [
  "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS",
] as const;

/** p.237's "by default, only GET, OPTIONS, and HEAD requests are considered
 * safe" — the three that carry no body. Offered as a *hint* rather than as a
 * refusal, because the server refuses the body and this only has to stop
 * somebody typing one into a field that will be discarded. */
export const BODYLESS_METHODS: readonly string[] = ["GET", "HEAD", "OPTIONS"];

/** p.228's input types, matching `webhooks.INPUT_TYPES`. Absent from the list
 * are `Attachment` (p.229 — needs an action form's uploaded file) and the two
 * container types, for the reasons the server's own comment gives. */
export const INPUT_TYPES = [
  ["string", "Text"],
  ["integer", "Whole number"],
  ["double", "Number"],
  ["boolean", "True or false"],
  ["date", "Date"],
  ["timestamp", "Date and time"],
] as const;

/** p.229's output types. `record` is here and not in the inputs because
 * capturing a JSON object out of a response is a slice and accepting one in is
 * a schema to validate. */
export const OUTPUT_TYPES = [
  ["string", "Text"],
  ["integer", "Whole number"],
  ["double", "Number"],
  ["boolean", "True or false"],
  ["record", "Object"],
] as const;

export interface WebhookInput {
  api_name: string;
  data_type: string;
  required: boolean;
}

export interface WebhookOutput {
  api_name: string;
  data_type: string;
  path: string;
}

export interface WebhookDraft {
  connection_id: string;
  api_name: string;
  display_name: string;
  description: string;
  method: string;
  path: string;
  query: Record<string, string>;
  headers: Record<string, string>;
  /** The body **as typed**, not as parsed. A form that held the parsed value
   * would have nowhere to put a half-finished document, and somebody editing
   * JSON is in a half-finished state most of the time. */
  bodyText: string;
  inputs: WebhookInput[];
  outputs: WebhookOutput[];
  store_responses: boolean;
  retry_statuses: number[];
  timeout_seconds: number;
}

export function blankWebhook(connectionId: string): WebhookDraft {
  return {
    connection_id: connectionId,
    api_name: "",
    display_name: "",
    description: "",
    // POST rather than GET: p.216's own example is "a webhook that performs an
    // HTTP request to an external server when a user selects a button", and
    // p.220's is a POST to /api/v1/createItem. A webhook that reads is the
    // less common one, and the connector already covers reading.
    method: "POST",
    path: "",
    query: {},
    headers: {},
    bodyText: "",
    inputs: [],
    outputs: [],
    // p.242's default, and the one that makes a webhook debuggable. Turning it
    // off is the deliberate act, for a webhook "known to return sensitive
    // information".
    store_responses: true,
    retry_statuses: [],
    timeout_seconds: 20,
  };
}

/** Every `{{{name}}}` in a template. The one copy of the server's pattern this
 * file has, for `notify-rule.referencesIn`'s reason: a form that could not see
 * its own references would report nothing until Save. An API test reads this
 * expression back out of the file and asserts it matches the server's (§190). */
export function referencesIn(template: string): string[] {
  return [...(template ?? "").matchAll(/\{\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}\}/g)]
    .map((match) => match[1] as string);
}

/** What is wrong with the body as typed, or null.
 *
 * Three answers rather than two, and the third is the point:
 *
 * * empty is fine — a request with no body is a request with no body;
 * * unparseable is a problem this form can name *now*, with the position, and
 *   the server would name on Save without one;
 * * parseable-but-not-an-object is allowed, because a JSON array is a
 *   perfectly good request body and p.233 does not say otherwise.
 */
export function bodyProblem(text: string): string | null {
  if (!text.trim()) return null;
  try {
    JSON.parse(text);
    return null;
  } catch (error) {
    // The browser's own message names the position, which is the useful half
    // and the half a hand-written message would lose.
    return `The body is not valid JSON: ${(error as Error).message}`;
  }
}

/** The body as the API takes it: a parsed document, or `null` for none.
 *
 * Returns `undefined` when the text does not parse, which the caller must
 * treat as "cannot save" rather than as "no body" — the two look the same in a
 * request and are opposite in intent. {@link problem} refuses the save first,
 * so this is the second guard rather than the only one. */
export function parsedBody(text: string): unknown | undefined {
  if (!text.trim()) return null;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/** Every string anywhere in a decoded JSON value, keys included.
 *
 * Keys as well as values, for the server's reason: `{"{{{name}}}": 1}` is a
 * reference too, and a form that checked one position and not the other would
 * be right about the common case and silently wrong about the other. */
export function stringsIn(node: unknown): string[] {
  if (typeof node === "string") return [node];
  if (Array.isArray(node)) return node.flatMap(stringsIn);
  if (node && typeof node === "object") {
    return Object.entries(node as Record<string, unknown>).flatMap(
      ([key, value]) => [key, ...stringsIn(value)],
    );
  }
  return [];
}

/** What is wrong with this webhook as typed, in one sentence, or null.
 *
 * The subset of `webhooks.parse`'s refusals a form can see without the
 * connection: the fields p.216 requires, the reserved headers p.233 names, and
 * a reference to something that is not a declared input. A subset rather than
 * a copy — an incomplete mirror that says nothing is right, and a complete one
 * would be a second parser to keep in step (§191).
 */
export function problem(draft: WebhookDraft): string | null {
  if (!draft.display_name.trim()) return "A webhook needs a name.";
  if (!/^[a-z][a-z0-9_]{0,62}$/.test(draft.api_name)) {
    return "The API name must start with a letter and use only lowercase letters, numbers and underscores.";
  }
  if (!draft.connection_id) return "Choose the source this webhook calls.";

  const body = bodyProblem(draft.bodyText);
  if (body) return body;
  const parsed = parsedBody(draft.bodyText);
  if (parsed !== null && BODYLESS_METHODS.includes(draft.method)) {
    // Not a rule about HTTP, which permits it, but about intent: many servers
    // and proxies drop a GET body, so it would look configured and send
    // nothing. The server refuses it too.
    return `A ${draft.method} request cannot carry a body.`;
  }

  const names = new Set<string>();
  for (const input of draft.inputs) {
    if (!/^[a-z][a-z0-9_]{0,62}$/.test(input.api_name)) {
      return `${input.api_name || "An input"} is not a valid input name.`;
    }
    if (names.has(input.api_name)) return `Two inputs are both called ${input.api_name}.`;
    names.add(input.api_name);
  }
  const outputNames = new Set<string>();
  for (const output of draft.outputs) {
    if (!/^[a-z][a-z0-9_]{0,62}$/.test(output.api_name)) {
      return `${output.api_name || "An output"} is not a valid output name.`;
    }
    if (outputNames.has(output.api_name)) {
      return `Two outputs are both called ${output.api_name}.`;
    }
    outputNames.add(output.api_name);
  }
  if (draft.outputs.length && draft.method === "HEAD") {
    return "A HEAD request has no body to read outputs from.";
  }

  for (const name of Object.keys(draft.headers)) {
    if (RESERVED_HEADERS.includes(name.toLowerCase())) {
      return `The ${name} header is set by the source and cannot be overridden here.`;
    }
  }

  for (const [where, text] of templatesIn(draft, parsed)) {
    for (const reference of referencesIn(text)) {
      if (!names.has(reference)) {
        return `The ${where} references ${reference}, which is not an input of this webhook.`;
      }
    }
  }
  return null;
}

/** Headers the source sets, matching `webhooks.RESERVED_HEADERS`. */
export const RESERVED_HEADERS: readonly string[] = [
  "authorization", "host", "content-length",
];

/** Every string in a draft that may hold a reference, named for the message.
 *
 * The body is walked whole rather than scanned as text, so a reference at any
 * depth is found and a `{{{` that happens to sit inside a JSON *string escape*
 * is not counted twice. */
function templatesIn(draft: WebhookDraft, body: unknown): [string, string][] {
  const found: [string, string][] = [["path", draft.path]];
  for (const [key, value] of Object.entries(draft.query)) {
    found.push([`${key} query parameter`, value]);
  }
  for (const [key, value] of Object.entries(draft.headers)) {
    found.push([`${key} header`, value]);
  }
  for (const text of stringsIn(body)) found.push(["body", text]);
  return found;
}

/** An api_name suggested from a display name, the way every other create
 * dialog here does it: somebody typing "Modify ticket priority" should not
 * also have to type `modify_ticket_priority`. */
export function suggestedApiName(displayName: string): string {
  return displayName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^([0-9])/, "h$1")
    .slice(0, 63);
}

/** p.242's history, as one line per run.
 *
 * **Three states, not two**, because `system_changed` is three-valued and the
 * third is the one worth showing: p.237 captures it "to enable debugging of
 * write failures", and a 500 after a POST that renders as "no" would be
 * believed. */
export function outcomeLabel(run: {
  ok: boolean;
  status_code: number | null;
  system_changed: boolean | null;
}): string {
  if (run.ok) return `Succeeded${run.status_code ? ` (${run.status_code})` : ""}`;
  const status = run.status_code ? ` (${run.status_code})` : "";
  if (run.system_changed === false) return `Failed${status} — nothing was changed`;
  if (run.system_changed === true) return `Failed${status} — after the change landed`;
  return `Failed${status} — the far end may have changed`;
}
