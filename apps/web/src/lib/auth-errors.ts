/**
 * What Cognito said when a sign-in failed, in its own words (§816).
 *
 * The first real deployment's owner could not sign in, and nobody could say
 * why: "the owner's chosen password was rejected at the login step" is as far
 * as `STATUS.md` §20 got, because "frontend today doesn't display Cognito's
 * specific rejection reason". Two places dropped it:
 *
 * - **The hosted UI's redirect.** A sign-in Cognito refuses comes back to
 *   `/callback` as `?error=...&error_description=...` (OAuth 2.0 §4.1.2.1)
 *   rather than with a code, and the page said "Missing authorization code"
 *   - true, and no use to anyone.
 * - **The token endpoint.** A refused exchange answers 400 with
 *   `{"error": "invalid_grant", ...}`, and the page said "Token exchange
 *   failed (400)".
 *
 * Pure, so the wording is tested here and the page only shows it.
 */

/** The reason Cognito sent the browser back without a code, or null when
 * it did not send an error at all. */
export function callbackError(params: URLSearchParams): string | null {
  const error = params.get("error")?.trim();
  if (!error) return null;
  const description = params.get("error_description")?.trim();
  return description ? `${description} (${error})` : `Sign-in was refused (${error})`;
}

/** A failed token exchange, with the endpoint's own error when it sent one. */
export function tokenFailure(status: number, body: unknown): string {
  const record = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  const error = typeof record.error === "string" ? record.error.trim() : "";
  const description =
    typeof record.error_description === "string" ? record.error_description.trim() : "";
  if (description && error) return `Token exchange failed: ${description} (${error})`;
  if (error) return `Token exchange failed: ${error} (${status})`;
  return `Token exchange failed (${status})`;
}
