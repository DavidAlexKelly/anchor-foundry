"use client";

/** Redact mode's banner (`workshop` p.614).
 *
 * **Its text is the feature, not a label on it.** p.614 spends a whole warning
 * box saying that redact mode "is a visual aid only and is not a security
 * feature" — and a blurred page is exactly what somebody takes for one. The
 * only moment that sentence can reach the person about to share their screen
 * is while the page is blurred in front of them.
 *
 * The Exit link is ours rather than p.615's, which describes only the URL
 * parameter. A mode whose one exit is editing the address by hand is a mode
 * people stay in by accident, and an accidentally redacted page is read as a
 * broken one.
 */

import { WARNING } from "./redact";

export function RedactBanner({ href }: { href: string }) {
  return (
    <div className="canvas-redact-banner" role="status" data-testid="redact-banner">
      <span>Redact mode — {WARNING}</span>
      <a className="btn quiet" data-testid="redact-exit" href={href}>
        Exit
      </a>
    </div>
  );
}
