import { ApiError } from "./api";

/** Whether a query that failed is asked again (§959).
 *
 * Once, for a failure that may pass: a server error (the API answers a
 * restarting database or a full pool with 503, §951), a timeout, a rate
 * limit, or a request that never reached it. Never for the API's own answer
 * to the request - a 404 or a 403 says the same thing a second later, and
 * retrying it only sent the request twice and showed the error a second
 * late. A 401 is handled before it gets here (`request` renews the session
 * or signs out). */
export function retryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1) return false;
  if (error instanceof ApiError) {
    return error.status >= 500 || error.status === 408 || error.status === 429;
  }
  return true;
}
