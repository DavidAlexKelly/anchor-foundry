"use client";

import Link from "next/link";
import { useEffect } from "react";
import { pageErrorKind } from "@/lib/page-error";

/** A page that failed to render, said in words (§908).
 *
 * Without a route error boundary, a production build answers an exception in
 * any page with a blank screen and "Application error: a client-side exception
 * has occurred", and the top bar goes with it. This keeps the layout around
 * it, says what can be done, and offers it. */
export function PageError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // The browser console is where somebody reporting it will be asked to look.
    console.error(error);
  }, [error]);
  const stale = pageErrorKind(error) === "stale";
  return (
    <div className="state error" role="alert" data-testid="page-error">
      <p style={{ fontWeight: 600, marginBottom: 6 }}>
        {stale ? "Anchor has been updated since this page loaded." : "This page ran into a problem."}
      </p>
      <p style={{ marginTop: 0 }}>
        {stale
          ? "Reload it to pick up the new version."
          : "Nothing you entered elsewhere is affected. Try the page again, or go back home."}
      </p>
      {error.digest && <p className="slug">Reference {error.digest}</p>}
      <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 12 }}>
        {stale ? (
          <button className="btn" data-testid="page-error-reload"
            onClick={() => window.location.reload()}>
            Reload
          </button>
        ) : (
          <button className="btn" data-testid="page-error-retry" onClick={() => reset()}>
            Try again
          </button>
        )}
        <Link className="btn quiet" href="/home">Go home</Link>
      </div>
    </div>
  );
}
