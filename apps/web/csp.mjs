/** What a page may load and where it may send things (§860, §993).
 *
 * §860 set the directives nothing relied on the absence of, and left scripts,
 * styles and connections open, because Next's hydration and Monaco needed a
 * policy written for them. This is that policy.
 *
 * - **Scripts and styles come from this origin.** Next's App Router writes
 *   its page data as inline scripts, and React and Monaco write inline
 *   styles, so both keep `'unsafe-inline'`; what goes is loading either from
 *   anywhere else, which is what an injected `<script src>` needs. A nonce
 *   would close inline scripts too, but needs every page rendered per
 *   request, and most of these are static. `'unsafe-eval'` is for
 *   `next dev`'s hot reload only, never a build.
 * - **Requests go to this origin**, and to the stack's Cognito domain, where
 *   the sign-in page exchanges its code for tokens (`src/lib/auth.ts`). A
 *   stack's domain is `platform-<org>.auth.<region>.amazoncognito.com`
 *   (`infra/cdk/src/constructs/auth.ts`) and is told to the page at run time,
 *   not at build, so the policy names the suffix. A script that did get in
 *   cannot post what it reads somewhere else.
 * - **Images, media and frames come from anywhere** a module's author points
 *   them: the Media Preview and the Iframe widget take any http(s) URL, and
 *   media a data URL, by design (`components/canvas/media.ts`, `frame.ts`).
 *   Those widgets keep their own rules for which URLs they accept.
 * - **Workers** are Monaco's, built into `/_next/static/`.
 */
export function contentSecurityPolicy({ development = false, cognitoDomain = "" } = {}) {
  const cognito = ["https://*.amazoncognito.com"];
  if (cognitoDomain) {
    const origin = new URL(cognitoDomain).origin;
    if (!origin.endsWith(".amazoncognito.com")) cognito.push(origin);
  }
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${development ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src * data: blob:",
    "media-src * data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' ${cognito.join(" ")}${development ? " ws: wss:" : ""}`,
    "frame-src *",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
  ].join("; ");
}
