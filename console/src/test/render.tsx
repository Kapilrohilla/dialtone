import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { Toast } from "@/components/ui";
import { setRoute } from "@/test/navigation";

export { router } from "@/test/navigation";

export function testQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
}

/** Renders `ui` inside a fresh QueryClient (retries off) and the toast region, with next/navigation at `route`. */
export function renderWithProviders(
  ui: ReactElement,
  { route = "/" }: { route?: string } = {},
): RenderResult & { queryClient: QueryClient } {
  setRoute(route);
  const queryClient = testQueryClient();
  const result = render(
    <QueryClientProvider client={queryClient}>
      <Toast>{ui}</Toast>
    </QueryClientProvider>,
  );
  return Object.assign(result, { queryClient });
}
