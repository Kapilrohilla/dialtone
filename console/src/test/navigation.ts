// The next/navigation mock that vitest.setup.ts installs. renderWithProviders sets the route.
import { vi } from "vitest";

export const route = { pathname: "/", search: "" };

export const router = {
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
};

export function setRoute(href: string) {
  const url = new URL(href, "http://localhost:3000");
  route.pathname = url.pathname;
  route.search = url.search;
}

export const useRouter = () => router;
export const usePathname = () => route.pathname;
export const useSearchParams = () => new URLSearchParams(route.search);
export const useParams = () => ({});
export const redirect = vi.fn();
export const notFound = vi.fn();
