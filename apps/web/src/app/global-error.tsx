"use client";

import "./globals.css";
import { PageError } from "@/components/page-error";

/** The last boundary (§908): an error in the root layout itself, which the
 * route boundaries sit inside of. It replaces the layout, so it brings its own
 * document. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body>
        <PageError error={error} reset={reset} />
      </body>
    </html>
  );
}
