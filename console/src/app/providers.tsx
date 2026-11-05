"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toast } from "@/components/ui";
import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            // One retry, and only for network failures and server errors: a 4xx will not change on a second try.
            retry: (count, error) => count < 1 && (!(error instanceof ApiError) || error.status >= 500),
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Toast>{children}</Toast>
    </QueryClientProvider>
  );
}
