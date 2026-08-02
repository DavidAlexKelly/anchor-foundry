/** Cognito hosted-UI login with PKCE (spec §9 login flow steps 1-6).
 *
 * Token storage: **none**. The access token is handed straight to the API,
 * which verifies it and returns an httpOnly session cookie; it is never
 * written anywhere this code can read it back. That is the httpOnly-cookie
 * design this file used to flag as the stronger one and defer (STATUS.md §55).
 *
 * It replaced sessionStorage, which stored the token per *tab*. That was a
 * defensible security choice and an impossible product one: a resource-centric
 * UI opens every resource in its own tab, and Chrome does not clone
 * sessionStorage into a tab opened from a link, so every new tab arrived with
 * no credentials at all.
 *
 * `anchor.signed_in` remains in localStorage. It is a flag, not a credential -
 * it tells the route guards whether to render or redirect without waiting on a
 * request, and being wrong about it costs a redirect rather than access. The
 * API's 401 is what actually decides.
 */

const KEY_SIGNED_IN = "anchor.signed_in";
const KEY_VERIFIER = "anchor.pkce_verifier";
const KEY_RETURN = "anchor.return_to";

interface CognitoConfig {
  domain: string;   // e.g. https://acme-anchor.auth.eu-west-1.amazoncognito.com
  clientId: string;
  redirectUri: string;
}

export function cognitoConfig(): CognitoConfig | null {
  const domain = process.env.NEXT_PUBLIC_COGNITO_DOMAIN;
  const clientId = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID;
  if (!domain || !clientId) return null;
  return {
    domain,
    clientId,
    redirectUri: `${window.location.origin}/callback`,
  };
}

function base64url(bytes: Uint8Array): string {
  let s = "";
  bytes.forEach((b) => (s += String.fromCharCode(b)));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sha256(input: string): Promise<Uint8Array> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return new Uint8Array(digest);
}

/** Step 1: send the user to the hosted UI with a PKCE challenge. */
export async function beginLogin(): Promise<void> {
  const cfg = cognitoConfig();
  if (!cfg) throw new Error("Cognito is not configured (NEXT_PUBLIC_COGNITO_*)");
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(48)));
  sessionStorage.setItem(KEY_VERIFIER, verifier);
  const challenge = base64url(await sha256(verifier));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: cfg.clientId,
    redirect_uri: cfg.redirectUri,
    scope: "openid email",
    code_challenge_method: "S256",
    code_challenge: challenge,
  });
  window.location.assign(`${cfg.domain}/oauth2/authorize?${params}`);
}

/** Steps 4-5: exchange the code for tokens at the Cognito token endpoint. */
export async function completeLogin(code: string): Promise<void> {
  const cfg = cognitoConfig();
  if (!cfg) throw new Error("Cognito is not configured");
  const verifier = sessionStorage.getItem(KEY_VERIFIER);
  if (!verifier) throw new Error("Missing PKCE verifier - restart sign-in");
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: cfg.clientId,
    code,
    redirect_uri: cfg.redirectUri,
    code_verifier: verifier,
  });
  const res = await fetch(`${cfg.domain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) throw new Error(`Token exchange failed (${res.status})`);
  const data: { access_token?: string } = await res.json();
  if (!data.access_token) throw new Error("Token endpoint returned no access token");
  sessionStorage.removeItem(KEY_VERIFIER);
  await establishSession(data.access_token);
}

/** Hand a verified token to the API and keep only the cookie it sets.
 *
 * The token is a local variable for the length of one fetch and is never
 * stored. An XSS on this origin can still act as the user while the page is
 * open - nothing short of removing the browser from the loop prevents that -
 * but it cannot walk away with a credential.
 */
export async function establishSession(token: string): Promise<void> {
  const res = await fetch("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ access_token: token }),
  });
  if (!res.ok) {
    let detail = `Sign-in failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep the status-based message */
    }
    throw new Error(detail);
  }
  localStorage.setItem(KEY_SIGNED_IN, "1");
}

/** Whether to render or redirect. Deliberately synchronous and deliberately
 * only a hint: the cookie is the truth and only the API can read it. */
export function isSignedIn(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(KEY_SIGNED_IN) === "1";
}

/** Forget the local flag. Clearing the cookie is the API's job (it is
 * httpOnly, so this code cannot), which is why sign-out calls the endpoint
 * rather than only doing this. */
export function clearSignedIn(): void {
  localStorage.removeItem(KEY_SIGNED_IN);
}

/** Local development without a Cognito pool: paste a token minted by the API
 * test tooling. Enabled only when NEXT_PUBLIC_AUTH_MODE=dev. Flagged for
 * review: never enable in a deployed environment. */
export function devAuthEnabled(): boolean {
  return process.env.NEXT_PUBLIC_AUTH_MODE === "dev";
}

/** Where to send someone after they sign in.
 *
 * sessionStorage is per-tab, so a resource link that somebody *shares* is
 * always loaded cold: there is no session to inherit and the guard bounces it
 * to /login. Without this, signing in then dropped them at /home having lost
 * the thing they were sent - which would make "send someone a link to what you
 * are looking at" false in the one case it matters.
 *
 * Only same-origin paths are honoured. An absolute URL, or a protocol-relative
 * "//evil.example" (which the browser treats as a host, not a path), would
 * turn the login page into an open redirect.
 */
export function safeReturnPath(raw: string | null): string | null {
  if (!raw) return null;
  if (!raw.startsWith("/") || raw.startsWith("//")) return null;
  return raw;
}

/** The hosted UI round trip leaves and re-enters the app, so the return path
 * cannot ride on a query param the way the dev sign-in box's can. Same tab,
 * so sessionStorage survives it. */
export function rememberReturnPath(path: string | null): void {
  const safe = safeReturnPath(path);
  if (safe) sessionStorage.setItem(KEY_RETURN, safe);
  else sessionStorage.removeItem(KEY_RETURN);
}

export function consumeReturnPath(): string | null {
  const raw = sessionStorage.getItem(KEY_RETURN);
  sessionStorage.removeItem(KEY_RETURN);
  return safeReturnPath(raw);
}

export function loginHrefFor(pathname: string, search = ""): string {
  const target = `${pathname}${search}`;
  // No point round-tripping somebody back to the page that sent them away.
  if (pathname === "/login" || pathname === "/") return "/login";
  return `/login?next=${encodeURIComponent(target)}`;
}
