/** What an error that reached a route's error boundary calls for (§908).
 *
 * Most are faults in the page: "Try again" re-renders it, which is worth a
 * press when the cause was a request that failed. One kind is not: after a
 * deploy, a page loaded before it asks for a script chunk the new build no
 * longer has. Re-rendering asks for the same missing chunk. Only loading the
 * page again, from the new build, recovers it. */
export type PageErrorKind = "stale" | "fault";

const STALE = [
  /Loading chunk [\w-]+ failed/i,
  /Loading CSS chunk/i,
  /Failed to fetch dynamically imported module/i,
  /error loading dynamically imported module/i,
  /Importing a module script failed/i,
];

export function pageErrorKind(error: { name?: string; message?: string } | null | undefined): PageErrorKind {
  if (!error) return "fault";
  if (error.name === "ChunkLoadError") return "stale";
  const message = error.message ?? "";
  return STALE.some((pattern) => pattern.test(message)) ? "stale" : "fault";
}

/** What the error page tells the platform's operators (§926), cut to what the
 * API takes (`routes/client_errors.py`). The path only: a page's query string
 * or fragment can carry a token. */
export interface PageErrorReport {
  kind: PageErrorKind;
  message: string;
  path: string;
  digest: string | null;
  stack: string | null;
}

export function pageErrorReport(
  error: { name?: string; message?: string; stack?: string; digest?: string } | null | undefined,
  pathname: string,
): PageErrorReport {
  return {
    kind: pageErrorKind(error),
    message: (error?.message || error?.name || "unknown error").slice(0, 500),
    path: (pathname.split(/[?#]/, 1)[0] ?? "").slice(0, 300),
    digest: error?.digest ? error.digest.slice(0, 100) : null,
    stack: error?.stack ? error.stack.slice(0, 4000) : null,
  };
}
