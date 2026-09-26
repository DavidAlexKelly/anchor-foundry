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
  listener_type: ListenerType;
  verification: Verification;
  verification_header: string | null;
  running: boolean;
  events: number;
  last_event_at: string | null;
  endpoints: ListenerEndpoint[];
  created_at: string;
  updated_at: string;
  /** p.264's backing dataset (§519), once the first archive has run. */
  archive_dataset_name: string | null;
  archive_dataset_resource_id: string | null;
  archived_at: string | null;
  /** Events the next archive run will write. */
  pending_events: number;
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

export type Verification =
  | "none" | "basic" | "header_secret" | "hmac_sha256" | "hmac_sha256_base64" | "slack_v0"
  | "stripe_v1" | "query_token";

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
  hmac_sha256_base64: {
    label: "HMAC-SHA256 signature, base64",
    hint: "As above, with the digest in base64 rather than hex.",
  },
  slack_v0: {
    label: "Slack signing secret",
    hint: "Slack signs each request with the app's signing secret and a timestamp; a stale one is refused.",
  },
  stripe_v1: {
    label: "Stripe signing secret",
    hint: "Stripe signs each request with the endpoint's signing secret and a timestamp; a stale one is refused.",
  },
  query_token: {
    label: "Token in the address",
    hint: "The sender adds ?token=<secret> to the endpoint address.",
  },
};

/** p.262's named listeners (§518), mirroring `LISTENER_TYPES` in
 * `services/listeners.py`: each fixes its schemes and the header each reads.
 * `"*"` is a header the author names; null is a scheme with no header. */
export const LISTENER_TYPES = {
  custom: { label: "Custom", schemes: {
    none: null, basic: null, header_secret: "*", hmac_sha256: "*", hmac_sha256_base64: "*",
    query_token: null } },
  slack: { label: "Slack", schemes: { slack_v0: "X-Slack-Signature" } },
  jira: { label: "Jira", schemes: { hmac_sha256: "X-Hub-Signature", none: null } },
  github: { label: "GitHub", schemes: { hmac_sha256: "X-Hub-Signature-256" } },
  gitlab: { label: "GitLab", schemes: { header_secret: "X-Gitlab-Token" } },
  stripe: { label: "Stripe", schemes: { stripe_v1: "Stripe-Signature" } },
  shopify: { label: "Shopify", schemes: { hmac_sha256_base64: "X-Shopify-Hmac-Sha256" } },
  pubsub: { label: "Google Cloud Pub/Sub", schemes: { query_token: null } },
} as const satisfies Record<string, { label: string; schemes: Partial<Record<Verification, string | null>> }>;

export type ListenerType = keyof typeof LISTENER_TYPES;

/** The schemes a type offers, its default first. */
export function schemesOf(type: ListenerType): Verification[] {
  return Object.keys(LISTENER_TYPES[type].schemes) as Verification[];
}

/** The header a scheme reads for this type: the author's, a fixed one, or none. */
function headerOf(type: ListenerType, v: Verification): string | null | undefined {
  return (LISTENER_TYPES[type].schemes as Partial<Record<Verification, string | null>>)[v];
}

export type ListenerDraft = {
  display_name: string;
  listener_type: ListenerType;
  verification: Verification;
  verification_header: string;
  secret: string;
};

export const BLANK_LISTENER: ListenerDraft = {
  display_name: "", listener_type: "custom", verification: "none", verification_header: "", secret: "",
};

/** Whether the author names the header: only a custom listener's header schemes. */
export function needsHeader(type: ListenerType, v: Verification): boolean {
  return headerOf(type, v) === "*";
}

/** A draft moved to another type starts on that type's default scheme. */
export function withType(draft: ListenerDraft, type: ListenerType): ListenerDraft {
  return { ...draft, listener_type: type, verification: schemesOf(type)[0] as Verification };
}

/** Why a draft cannot be saved, or "" when it can. The server's rules, said
 * before the request rather than after it. */
export function draftProblem(draft: ListenerDraft): string {
  if (!draft.display_name.trim()) return "Name the listener.";
  if (draft.verification === "none") return "";
  if (!draft.secret) return "This verification needs a secret.";
  if (needsHeader(draft.listener_type, draft.verification)
      && !/^[A-Za-z0-9-]{1,100}$/.test(draft.verification_header)) {
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
    display_name: draft.display_name.trim(), listener_type: draft.listener_type,
    verification: draft.verification,
  };
  if (draft.verification !== "none") body.secret = draft.secret;
  if (needsHeader(draft.listener_type, draft.verification)) {
    body.verification_header = draft.verification_header;
  }
  return body;
}

/** What a listener is doing, in one line. */
export function statusText(listener: Pick<Listener, "running" | "events">): string {
  const taken = `${listener.events} event${listener.events === 1 ? "" : "s"} received`;
  return listener.running
    ? `Running · ${taken}`
    : `Stopped · requests are refused until it is started · ${taken}`;
}

/** The type, the scheme, and the header it reads when it reads one. */
export function verificationText(
  listener: Pick<Listener, "listener_type" | "verification" | "verification_header">,
): string {
  const label = VERIFICATIONS[listener.verification].label;
  const scheme = listener.verification_header ? `${label} (${listener.verification_header})` : label;
  return listener.listener_type === "custom"
    ? scheme : `${LISTENER_TYPES[listener.listener_type].label} · ${scheme}`;
}

/** A command that sends the listener one test event, for whoever is setting
 * up the other end. */
export function curlExample(url: string): string {
  return `curl -X POST -H 'Content-Type: application/json' -d '{"hello": "listener"}' ${url}`;
}

// ---- endpoint rotation (§517; p.258-259) ---------------------------------------
const DAY_MS = 86_400_000;

/** What an endpoint is doing: p.258's active one, a retiring one with the time
 * it has left, or an expired one that answers nothing. */
export function endpointState(endpoint: Pick<ListenerEndpoint, "active" | "expired" | "expires_at">, now: number): string {
  if (endpoint.active) return "Active";
  if (endpoint.expired || !endpoint.expires_at) return "Expired: no longer answers";
  const left = Date.parse(endpoint.expires_at) - now;
  const hours = Math.max(1, Math.round(left / 3_600_000));
  return hours < 48 ? `Retiring: answers for ${hours} more hour${hours === 1 ? "" : "s"}`
    : `Retiring: answers for ${Math.round(hours / 24)} more days`;
}

/** p.258's two ways to rotate: keep the old address a day for a move with no
 * downtime, or retire it now. */
export const ROTATIONS = {
  day: "Keep the old address for a day",
  now: "Retire the old address now",
} as const;

export function rotateBody(choice: keyof typeof ROTATIONS, now: number): { expire_old_at: string | null } {
  return { expire_old_at: choice === "day" ? new Date(now + DAY_MS).toISOString() : null };
}

/** p.259's extension: a day more than whichever is later, now or the current
 * expiry, so extending never shortens. */
export function extendedExpiry(expiresAt: string, now: number): string {
  return new Date(Math.max(now, Date.parse(expiresAt)) + DAY_MS).toISOString();
}

/** Why Rotate is not offered, or "" when it is: p.258's two-endpoint limit. */
export function whyNoRotation(endpoints: Pick<ListenerEndpoint, "active">[]): string {
  return endpoints.length >= 2
    ? "A listener has at most two endpoints. Delete the one being retired to rotate again."
    : "";
}

// ---- the archive (§519; p.264) ---------------------------------------------------
/** p.264: "Every few minutes, the listener event stream will archive into a
 * backing dataset." How many events the next run will write. */
export function waitingText(pending: number): string {
  return pending === 0 ? "nothing waiting" : `${pending} event${pending === 1 ? "" : "s"} waiting`;
}

/** Before the first run there is no dataset to name, and the line says what
 * will make one. */
export function notArchivedText(pending: number): string {
  return `Not archived yet · ${waitingText(pending)}. The first archive makes the dataset.`;
}

/** What "Archive now" did, for the line under the button. */
export function archivedText(done: { archived: number; version: number | null }): string {
  return done.version === null
    ? "Nothing new to archive."
    : `Archived ${done.archived} event${done.archived === 1 ? "" : "s"} as version ${done.version}.`;
}
