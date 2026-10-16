"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { newQueryClient } from "../lib/query-client";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(newQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
