"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toast } from "@/components/ui";
import { isSignedOut } from "@/lib/api";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: (count, error) => !isSignedOut(error) && count < 1,
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
