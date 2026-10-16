import { QueryClient } from "@tanstack/react-query";
import { retryQuery } from "./query-retry";

/** The app's query client: one more try only for a failure that may pass
 * (§959, `retryQuery`). */
export function newQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: retryQuery, staleTime: 15_000, refetchOnWindowFocus: false },
    },
  });
}
