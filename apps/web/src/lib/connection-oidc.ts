/** A source that authenticates with OpenID Connect (§599; `data-connection`
 * p.391): "you do not need to configure credentials for a source system in
 * Foundry. Instead, you will configure a trust relationship between Foundry
 * and the source system."
 *
 * The browser's half: a source that names a role stores no key, so the form
 * does not ask for one, and the connection says what its trust policy has to
 * name. */

/** Whether a connection's config, as the form holds it, uses OpenID Connect. */
export function usesOidc(config: Record<string, unknown>): boolean {
  const role = config.oidc_role_arn;
  return typeof role === "string" && role.trim() !== "";
}

export interface OidcTrust {
  issuer: string | null;
  audience: string | null;
  subject: string | null;
}

/** p.391's three things a source system checks, as lines to copy into its
 * trust policy. The subject is the one p.391 says to filter on. */
export function trustLines(trust: OidcTrust): [string, string][] {
  return [
    ["Issuer", trust.issuer ?? "not set up on this platform"],
    ["Audience", trust.audience ?? ""],
    ["Subject", trust.subject ?? ""],
  ];
}
