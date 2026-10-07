"use client";

import { PageError } from "@/components/page-error";

/** The route error boundary (§908): a page that throws says so, instead of
 * blanking the screen. One, at the root, below the root layout: a boundary
 * in a route group made Next 15's dev server warn about a missing key in its
 * own `ClientSegmentRoot` on every page, which the browser suite counts as a
 * console error. */
export default function RouteError(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <PageError {...props} />;
}
