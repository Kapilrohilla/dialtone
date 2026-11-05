import type { Appearance } from "@/lib/types";

export type { Appearance };

export const THEME_COOKIE = "cv_theme";

export function themeFromCookie(value: string | undefined): "light" | "dark" | undefined {
  return value === "light" || value === "dark" ? value : undefined;
}

/** "light" and "dark" are remembered in a cookie the root layout reads; "system" forgets them. */
export function applyAppearance(a: Appearance): void {
  const root = document.documentElement;
  if (a === "system") {
    delete root.dataset.theme;
    document.cookie = `${THEME_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
    return;
  }
  root.dataset.theme = a;
  document.cookie = `${THEME_COOKIE}=${a}; path=/; max-age=31536000; SameSite=Lax`;
}
