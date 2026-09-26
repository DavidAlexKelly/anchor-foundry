/** HTTPS listeners, as the Data Connection screen says them (§516;
 * `data-connection` p.249-266).
 *
 * > "data connection listeners provision a URL endpoint, implement the
 * > specific message signing or other verification schemes for specific
 * > external systems" (p.249)
 *
 * What a request must prove is the API's (`services/listeners.py`); this is
 * the form's copy of the configuration rules, so a listener that cannot
 * verify is refused before it is sent, and the wording of the screen.
 */

export type ListenerEndpoint = {
  id: string;
  url: string;
  active: boolean;
  expired: boolean;
  expires_at: string | null;
  created_at: string;
};

export type Listener = {
  id: string;
  display_name: string;
  verification: Verification;
  verification_header: string | null;
  running: boolean;
  events: number;
  last_event_at: string | null;
  endpoints: ListenerEndpoint[];
  created_at: string;
  updated_at: string;
};

export type ListenerEvent = {
  id: number;
  received_at: string;
  content_type: string | null;
  size_bytes: number;
  preview: string | null;
  truncated: boolean;
  headers: Record<string, string>;
};

export type Verification = "none" | "basic" | "header_secret" | "hmac_sha256";

/** The schemes, with what each asks of a sender. p.265: "listeners implement
 * the security protocols laid out by those external systems". */
export const VERIFICATIONS: Record<Verification, { label: string; hint: string }> = {
  none: {
    label: "None",
    hint: "Anyone with the address can send. The random address is the only secret.",
  },
  basic: {
    label: "Basic authentication",
    hint: "The sender signs in with a username and password, sent as username:password.",
  },
  header_secret: {
    label: "Secret in a header",
    hint: "The sender puts a shared secret in the header you name.",
  },
  hmac_sha256: {
    label: "HMAC-SHA256 signature",
    hint: "The sender signs the body with a shared key and puts the hex digest in the header you name.",
  },
};

export type ListenerDraft = {
  display_name: string;
  verification: Verification;
  verification_header: string;
  secret: string;
};

export const BLANK_LISTENER: ListenerDraft = {
  display_name: "", verification: "none", verification_header: "", secret: "",
};

export function needsHeader(v: Verification): boolean {
  return v === "header_secret" || v === "hmac_sha256";
}

/** Why a draft cannot be saved, or "" when it can. The server's rules, said
 * before the request rather than after it. */
export function draftProblem(draft: ListenerDraft): string {
  if (!draft.display_name.trim()) return "Name the listener.";
  if (draft.verification === "none") return "";
  if (!draft.secret) return "This verification needs a secret.";
  if (needsHeader(draft.verification) && !/^[A-Za-z0-9-]{1,100}$/.test(draft.verification_header)) {
    return "Name the header it arrives in: letters, digits and hyphens.";
  }
  if (draft.verification === "basic" && !draft.secret.includes(":")) {
    return "Basic authentication's secret is username:password.";
  }
  return "";
}

/** The body the API takes: fields a scheme does not use are left out, since
 * the server refuses them rather than ignoring them. */
export function draftBody(draft: ListenerDraft): Record<string, unknown> {
  const body: Record<string, unknown> = {
    display_name: draft.display_name.trim(), verification: draft.verification,
  };
  if (draft.verification !== "none") body.secret = draft.secret;
  if (needsHeader(draft.verification)) body.verification_header = draft.verification_header;
  return body;
}

/** What a listener is doing, in one line. */
export function statusText(listener: Pick<Listener, "running" | "events">): string {
  const taken = `${listener.events} event${listener.events === 1 ? "" : "s"} received`;
  return listener.running
    ? `Running · ${taken}`
    : `Stopped · requests are refused until it is started · ${taken}`;
}

/** The scheme, and the header it reads when it reads one. */
export function verificationText(listener: Pick<Listener, "verification" | "verification_header">): string {
  const label = VERIFICATIONS[listener.verification].label;
  return listener.verification_header ? `${label} (${listener.verification_header})` : label;
}

/** A command that sends the listener one test event, for whoever is setting
 * up the other end. */
export function curlExample(url: string): string {
  return `curl -X POST -H 'Content-Type: application/json' -d '{"hello": "listener"}' ${url}`;
}
