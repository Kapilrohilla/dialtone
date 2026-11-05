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
// One instance per search string, as the real hook returns a stable object (a new one each render would loop effects).
let params: { search: string; value: URLSearchParams } | null = null;
export const useSearchParams = () => {
  if (!params || params.search !== route.search) params = { search: route.search, value: new URLSearchParams(route.search) };
  return params.value;
};
// Dynamic segments for useParams; tests set them with setParams, vitest.setup resets them.
let segments: Record<string, string> = {};
export const setParams = (p: Record<string, string>) => {
  segments = p;
};
export const useParams = () => segments;
export const redirect = vi.fn();
export const notFound = vi.fn();
