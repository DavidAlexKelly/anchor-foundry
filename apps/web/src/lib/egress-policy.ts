/**
 * A source's egress policies, as a form (Foundry `data-connection` p.12, p.37,
 * p.103; decision 0013; §264).
 *
 * §263 built the rule, the rows and the enforcement and left all three
 * reachable only by posting JSON — the shape §252 named and §258 and §261 have
 * each closed since. For a *security* control that gap is worse than usual: an
 * allowlist nobody can see is one nobody is checking, and p.37's own debugging
 * procedure opens with "confirm that the correct egress policies are attached
 * to the source, and that the host, port, and protocol they allow match the
 * system you are connecting to". That sentence is a screen.
 *
 * The division is this repo's usual one. The server owns what is **legal**
 * (`services/egress.parse`, which refuses every case below independently); this
 * owns what a form can say before a round trip, and what the panel may
 * **suggest**.
 *
 * **It does not decide whether a call would be permitted.** That mirror is the
 * one worth refusing: a browser that answered "allowed" where the server
 * refuses would be worse than one that says nothing, and §191's rule is that
 * two copies of a rule are two chances to be wrong. So {@link destinationsFor}
 * reports what a source is *configured to dial*, the panel puts that beside the
 * list of what is *allowed*, and the person compares two facts. The button that
 * gives a real answer is Test, which runs the server's own check.
 */

/** A hostname, mirroring `egress._HOST` and db 0068's CHECK.
 *
 * A mirror, and a deliberate one: the alternative is a form whose only
 * validation is a 422, and a refusal that arrives on Save is a refusal about a
 * form somebody has already left. The server refuses these cases whether or
 * not this does — that is what makes the duplication safe here and not safe in
 * {@link destinationsFor}'s neighbourhood. */
const HOST = /^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$/;

/** `egress._LOOKS_LIKE_A_RANGE`. p.103 pushes towards names rather than
 * addresses and decision 0013 declines CIDR outright. */
const LOOKS_LIKE_A_RANGE = /\/\d{1,3}$/;

/** The port a scheme implies, mirroring `egress.port_for`.
 *
 * Needed because the panel has to *show* the destination a source will dial,
 * and `https://api.example.com` dials 443 whether or not anybody typed it.
 * Showing no port there would be showing a different destination from the one
 * the server checks. */
const IMPLIED_PORT: Record<string, number> = { "http:": 80, "https:": 443 };

export interface Policy {
  id: string;
  host: string;
  port: number | null;
  description: string;
}

export interface PolicyDraft {
  host: string;
  /** Text, because it comes from an input and "" has to mean *any port* rather
   * than zero. {@link toPayload} is where it stops being text. */
  port: string;
  description: string;
}

export function blankPolicy(): PolicyDraft {
  return { host: "", port: "", description: "" };
}

/** `host:port`, or `host` when the policy says nothing about ports.
 *
 * The same string the server's refusal uses, on purpose: somebody reading
 * "not allowed to reach api.example.com:443" should be able to find that text
 * in the list without translating it. */
export function describe(policy: { host: string; port: number | null }): string {
  return policy.port === null ? policy.host : `${policy.host}:${policy.port}`;
}

/** What the panel says above the list.
 *
 * **Decision 0013 §2 requires this sentence to exist.** An empty allowlist
 * means unrestricted — it has to, because every source that already exists is
 * in that state — and an empty table with no explanation reads as the opposite.
 * A control whose off state is indistinguishable from its on state is not a
 * control anybody can rely on.
 */
export function summary(policies: readonly Policy[]): string {
  if (policies.length === 0) {
    return (
      "No policies: this source may reach any destination the platform itself " +
      "allows. Add one to restrict it to named destinations."
    );
  }
  const only = policies.length === 1 ? "the one destination" : `the ${policies.length} destinations`;
  return `Restricted: this source may reach ${only} below, and nothing else.`;
}

/** The message a form shows for a draft, or null when it has none.
 *
 * `existing` is checked too, because the duplicate is the refusal somebody is
 * most likely to hit twice: db 0068's unique constraint and `egress_store`
 * both refuse it, and finding out on Save means retyping a host.
 */
export function problem(draft: PolicyDraft, existing: readonly Policy[] = []): string | null {
  const host = draft.host.trim().toLowerCase();
  if (!host) return "Name the host this source may reach.";
  if (LOOKS_LIKE_A_RANGE.test(host)) {
    return (
      "An egress policy names one destination, not a range — name each host " +
      "you need to reach, or the domain they share."
    );
  }
  if (host.length > 253 || !HOST.test(host)) {
    return `“${draft.host.trim()}” is not a hostname or an address.`;
  }

  const port = draft.port.trim();
  let parsed: number | null = null;
  if (port) {
    if (!/^\d+$/.test(port)) return `“${port}” is not a port.`;
    parsed = Number(port);
    if (parsed < 1 || parsed > 65535) return `“${port}” is not a port.`;
  }

  const clash = existing.find((p) => p.host === host && p.port === parsed);
  if (clash) return `This source already allows ${describe(clash)}.`;
  return null;
}

/** The draft as the API takes it. Only meaningful once {@link problem} is null. */
export function toPayload(draft: PolicyDraft): {
  host: string;
  port: number | null;
  description: string;
} {
  const port = draft.port.trim();
  return {
    host: draft.host.trim().toLowerCase(),
    port: port ? Number(port) : null,
    description: draft.description.trim(),
  };
}

export interface Destination {
  /** The configuration field this came from, in the words that field uses on
   * the source's own form. */
  label: string;
  host: string;
  port: number | null;
}

export interface Destinations {
  known: Destination[];
  /** Why {@link Destinations.known} may be short of the whole truth, or null
   * when it is not. Never an empty string: a caveat that renders as nothing is
   * a caveat nobody reads. */
  caveat: string | null;
}

/** The host and port a URL dials, or null if it is not one this can read.
 *
 * `URL` rather than a regex, because the cases a regex gets wrong here — a
 * userinfo section, an IPv6 literal, a port written with leading zeroes — are
 * exactly the ones somebody would use to make a destination look like a
 * different one.
 */
export function urlDestination(raw: string): { host: string; port: number | null } | null {
  const text = (raw ?? "").trim();
  if (!text) return null;
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  if (!url.hostname) return null;
  const port = url.port ? Number(url.port) : (IMPLIED_PORT[url.protocol] ?? null);
  // **No `.toLowerCase()` here, and that is deliberate.** There was one, and
  // §264's harness could not make its removal fail: WHATWG host parsing
  // lowercases the host itself, so `new URL("https://API.Example.COM").hostname`
  // is already `api.example.com`. §213's question — is another layer already
  // making this guarantee? — answers yes, and a line that cannot fail is a line
  // that reads as a guarantee this function makes when it does not.
  //
  // The *property* still matters and is still asserted, because everything this
  // is compared against is stored lowercase. The test that covers it belongs to
  // `URL`, not to a call this file makes, and it would go red if somebody
  // replaced the parser with a regex — which is exactly the change that would
  // break it.
  return { host: url.hostname, port };
}

/** The destinations a source is configured to reach, read from its own config.
 *
 * **This is p.37's step 1 turned into something a screen can show.** The list
 * of what a source is *allowed* to reach is only useful next to the list of
 * what it will *try* to reach, and the second one is otherwise spread across
 * four fields on a different form.
 *
 * A source type this does not know returns an empty list **with a caveat**,
 * never a bare empty list: "no destinations" and "I cannot read this source's
 * destinations" are different answers, and only one of them means the policies
 * below are complete. That is also what makes adding a connector without
 * coming here visible rather than silent.
 */
export function destinationsFor(
  sourceType: string,
  config: Record<string, unknown> | null | undefined,
): Destinations {
  const cfg = config ?? {};
  const text = (key: string): string => String(cfg[key] ?? "").trim();
  const known: Destination[] = [];

  switch (sourceType) {
    case "postgres":
    case "mysql": {
      const host = text("host").toLowerCase();
      if (!host) return { known: [], caveat: "This source has no host configured yet." };
      const port = Number(cfg.port);
      known.push({
        label: "Database host",
        host,
        port: Number.isInteger(port) && port > 0 ? port : null,
      });
      return { known, caveat: null };
    }

    case "rest": {
      const base = urlDestination(text("base_url"));
      if (base) known.push({ label: "Base URL", ...base });
      // p.12's own example is a source that fetches a credential from one
      // system and spends it on another, and §263 found this destination
      // unguarded for exactly the reason it is easy to leave off a screen: it
      // is auth, so it does not read as a place data comes from.
      if (text("auth_type") === "oauth2_client_credentials") {
        const token = urlDestination(text("token_url"));
        if (token) known.push({ label: "Token endpoint", ...token });
      }
      return {
        known,
        caveat: known.length ? null : "This source has no readable URL configured yet.",
      };
    }

    case "s3": {
      const endpoint = urlDestination(text("endpoint_url"));
      if (endpoint) return { known: [{ label: "Custom endpoint", ...endpoint }], caveat: null };
      // The gap `S3Connector._client` documents and
      // `test_an_aws_bucket_is_not_scoped_by_a_policy_and_this_is_deliberate`
      // holds. Saying it here is the point of the caveat field: a bucket with
      // no policies and a bucket with policies reach the same destinations,
      // and somebody who added one has to be told it did nothing.
      return {
        known: [],
        caveat:
          "An AWS bucket's host is derived from the bucket and region when the " +
          "request is made, so egress policies cannot restrict this source. " +
          "Only a custom endpoint (MinIO, Ceph, R2) can be named as a destination.",
      };
    }

    default:
      return {
        known: [],
        caveat: `Destinations for a ${sourceType} source cannot be read from its configuration.`,
      };
  }
}

/** A destination as a draft, for the panel's "Allow this" button.
 *
 * Pre-filling rather than saving: p.37 asks somebody to *confirm* the policies
 * match, and a one-click write would let them agree with a suggestion they had
 * not read. The description names where the suggestion came from, so a list
 * read six months later still says why each row is there.
 */
export function draftFor(destination: Destination): PolicyDraft {
  return {
    host: destination.host,
    port: destination.port === null ? "" : String(destination.port),
    description: `This source's ${destination.label.toLowerCase()}`,
  };
}
