/** An outbound application's screens (decision 0022; `data-connection` p.39-40,
 * p.243; §754).
 *
 * A REST source whose `auth_type` is `oauth2_authorization_code` is called as
 * the person using it, so each person authorizes it once: the source says
 * whether *you* have, offers to, and says how it went when the provider sends
 * you back (`/api/oauth/callback` redirects here with `?authorization=`). */

export const OUTBOUND_AUTH = "oauth2_authorization_code";

/** The config fields only an outbound application has (decision 0022 §1):
 * the form leaves them out for every other auth type, where they mean
 * nothing and the server ignores them. */
export const OUTBOUND_FIELDS = ["authorize_url", "oauth_scope"] as const;

/** Whether a source (or a form's draft of one) is called as its user. */
export function isOutbound(config: Record<string, unknown>): boolean {
  return config.auth_type === OUTBOUND_AUTH;
}

/** Whether the connection form shows a config field, given the draft. */
export function showsField(key: string, config: Record<string, unknown>): boolean {
  return !(OUTBOUND_FIELDS as readonly string[]).includes(key) || isOutbound(config);
}

export interface Grant {
  authorized: boolean;
  scope: string | null;
  expires_at: string | null;
  granted_at: string | null;
}

/** The caller's own standing on the source, in a sentence. */
export function grantText(grant: Grant): string {
  if (!grant.authorized) {
    // p.40's first check: "The user invoking the function has completed the
    // interactive authorization flow at least once."
    return "You have not authorized this source. It is called as whoever uses it, " +
      "so authorize it before testing, exploring or syncing it.";
  }
  const scope = grant.scope ? ` with scope ${grant.scope}` : "";
  return `You have authorized this source${scope}. Calls on it are made as you.`;
}

export interface Notice {
  ok: boolean;
  text: string;
}

/** What the callback's return says, or null when the address carries none.
 * `reason` is the provider's or the token exchange's, shown as given. */
export function returnNotice(search: string): Notice | null {
  const query = new URLSearchParams(search);
  const outcome = query.get("authorization");
  const reason = query.get("reason");
  const why = reason ? ` (${reason})` : "";
  switch (outcome) {
    case "granted":
      return { ok: true, text: "Authorized. Calls on the source are now made as you." };
    case "denied":
      // Declining at the provider is the person's to do, not a fault here.
      return { ok: false, text: `The provider did not authorize the source${why}.` };
    case "failed":
      return { ok: false, text: `Authorization failed${why}. Try again from the source.` };
    default:
      return null;
  }
}

/** The same address without the callback's parameters, so a reload does not
 * say it again. */
export function withoutReturn(pathname: string, search: string): string {
  const query = new URLSearchParams(search);
  query.delete("authorization");
  query.delete("reason");
  const rest = query.toString();
  return rest ? `${pathname}?${rest}` : pathname;
}
