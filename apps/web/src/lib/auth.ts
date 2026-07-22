/** Cognito hosted-UI login with PKCE (spec §9 login flow steps 1-6).
 *
 * Token storage: sessionStorage, deliberately. Access tokens live 15 minutes
 * (§9) so exposure is bounded; sessionStorage clears on tab close and is not
 * sent with requests the way cookies are (no CSRF surface). Flagged for
 * review: an httpOnly-cookie session brokered by the API is the stronger
 * design and slots in behind this same interface.
 */

const KEY_TOKEN = "anchor.access_token";
const KEY_VERIFIER = "anchor.pkce_verifier";

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
  if (!verifier) throw new Error("Missing PKCE verifier — restart sign-in");
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
  setToken(data.access_token);
}

export function setToken(token: string): void {
  sessionStorage.setItem(KEY_TOKEN, token);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(KEY_TOKEN);
}

export function clearToken(): void {
  sessionStorage.removeItem(KEY_TOKEN);
}

/** Local development without a Cognito pool: paste a token minted by the API
 * test tooling. Enabled only when NEXT_PUBLIC_AUTH_MODE=dev. Flagged for
 * review: never enable in a deployed environment. */
export function devAuthEnabled(): boolean {
  return process.env.NEXT_PUBLIC_AUTH_MODE === "dev";
}
