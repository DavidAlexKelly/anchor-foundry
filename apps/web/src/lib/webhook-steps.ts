/**
 * The calls a webhook makes before its own request (§523; `data-connection`
 * p.234-237).
 *
 * > "A single webhook may contain multiple requests. Requests may be chained
 * > together, with response values from a previous call referenced in
 * > subsequent calls." (p.234)
 *
 * A subset of `webhooks._steps`, for `webhook-form.problem`'s reason: the form
 * names what it can see before Save, and the server has the last word.
 */
import { BODYLESS_METHODS, bodyProblem, parsedBody, referencesIn, stringsIn } from "./webhook-form";

export interface StepExtract {
  api_name: string;
  path: string;
}

/** One call as the form holds it: the body as typed, like the request's. */
export interface StepDraft {
  method: string;
  path: string;
  bodyText: string;
  /** p.237's isHttpMethodSafe: this call only reads, whatever its method. */
  safe: boolean;
  extract: StepExtract[];
}

/** One call as the API holds it. */
export interface WebhookStep {
  method: string;
  path: string;
  body: unknown | null;
  safe: boolean;
  extract: StepExtract[];
}

/** The server's `webhooks.MAX_STEPS`. */
export const MAX_STEPS = 9;

/** A new call reads: p.235's example starts with a GET whose answer the
 * request uses. */
export function blankStep(): StepDraft {
  return { method: "GET", path: "", bodyText: "", safe: false, extract: [] };
}

export function stepDrafts(steps: WebhookStep[] | undefined): StepDraft[] {
  return (steps ?? []).map((step) => ({
    method: step.method,
    path: step.path,
    bodyText: step.body === null || step.body === undefined ? "" : JSON.stringify(step.body, null, 2),
    safe: step.safe,
    extract: step.extract,
  }));
}

/** What the API takes. A row with no name is dropped, as the request's
 * key/value rows are, so "add a row, change your mind" needs no delete. */
export function stepsPayload(drafts: StepDraft[]): WebhookStep[] {
  return drafts.map((draft) => ({
    method: draft.method,
    path: draft.path,
    body: parsedBody(draft.bodyText) ?? null,
    safe: BODYLESS_METHODS.includes(draft.method) ? false : draft.safe,
    extract: draft.extract.filter((e) => e.api_name !== ""),
  }));
}

/** p.237: "By default, only GET, OPTIONS, and HEAD requests are considered
 * safe", unless the call is marked safe. */
export function unsafeStep(draft: Pick<StepDraft, "method" | "safe">): boolean {
  return !BODYLESS_METHODS.includes(draft.method) && !draft.safe;
}

/** Every name the chain extracts, in order: what the request may reference
 * besides its inputs. */
export function extractedNames(drafts: StepDraft[]): string[] {
  return drafts.flatMap((d) => d.extract.map((e) => e.api_name)).filter((n) => n !== "");
}

/** What is wrong with the chain, or null. `inputs` are the webhook's input
 * names; `method` is its own request's, which counts towards p.237's one
 * unsafe call. */
export function stepsProblem(drafts: StepDraft[], inputs: string[], method: string): string | null {
  if (drafts.length > MAX_STEPS) return `A webhook makes at most ${MAX_STEPS} calls before its request.`;
  const known = new Set(inputs);
  for (const [index, draft] of drafts.entries()) {
    const where = `Call ${index + 1}`;
    const body = bodyProblem(draft.bodyText);
    if (body) return `${where}: ${body.charAt(0).toLowerCase()}${body.slice(1)}`;
    const parsed = parsedBody(draft.bodyText);
    if (parsed !== null && BODYLESS_METHODS.includes(draft.method)) {
      return `${where}: a ${draft.method} request cannot carry a body.`;
    }
    for (const text of [draft.path, ...stringsIn(parsed)]) {
      for (const name of referencesIn(text)) {
        if (!known.has(name)) {
          return `${where} references ${name}, which is neither an input nor extracted by an earlier call.`;
        }
      }
    }
    for (const extract of draft.extract) {
      if (extract.api_name === "") continue;
      if (!/^[a-z][a-z0-9_]{0,62}$/.test(extract.api_name)) {
        return `${where}: ${extract.api_name} is not a valid name for an extracted value.`;
      }
      if (known.has(extract.api_name)) {
        return `${where}: ${extract.api_name} is already an input or an extracted value.`;
      }
      if (!extract.path.trim()) {
        return `${where}: ${extract.api_name} needs a path, or "." for the whole response.`;
      }
      known.add(extract.api_name);
    }
  }
  const unsafe = drafts.filter(unsafeStep).length + (BODYLESS_METHODS.includes(method) ? 0 : 1);
  if (unsafe > 1) {
    return "Only one call may change the external system (p.237). Mark an earlier call as only reading if it does.";
  }
  return null;
}

/** One call in one line, for the list above its editor. */
export function stepSummary(draft: Pick<StepDraft, "method" | "path" | "extract">): string {
  const names = draft.extract.map((e) => e.api_name).filter((n) => n !== "");
  return `${draft.method} /${draft.path}${names.length ? ` → ${names.join(", ")}` : ""}`;
}

/** A call with a new method. A method that carries no body drops the one
 * typed, and the mark that it only reads, since the editor stops showing
 * both: a hidden body the form then refused would be a refusal nobody could
 * act on. */
export function withMethod(draft: StepDraft, method: string): StepDraft {
  return BODYLESS_METHODS.includes(method)
    ? { ...draft, method, bodyText: "", safe: false }
    : { ...draft, method };
}
