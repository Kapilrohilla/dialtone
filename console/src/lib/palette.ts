import type { Theme } from "@/lib/types";

export type { Theme };

/** The install-wide palettes, in the order Settings → General shows them. Saffron is the default. */
export const THEMES: { value: Theme; label: string }[] = [
  { value: "saffron", label: "Saffron" },
  { value: "ocean", label: "Ocean" },
  { value: "forest", label: "Forest" },
];

export const DEFAULT_THEME: Theme = "saffron";

export function themeOrDefault(value: unknown): Theme {
  return THEMES.some((t) => t.value === value) ? (value as Theme) : DEFAULT_THEME;
}

export const DEFAULT_FAVICON = "/favicon.ico";

/** Switches the open page to `theme` (globals.css keys the palettes off <html data-palette>). The root layout sets
 *  the same attribute on the server, so a page load never flashes the default palette. */
export function applyPalette(theme: Theme): void {
  document.documentElement.dataset.palette = theme;
}

/** Points the tab icon at the logo, or back at favicon.ico. */
export function applyFavicon(logoUrl: string | null): void {
  const href = logoUrl ?? DEFAULT_FAVICON;
  const links = document.querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="shortcut icon"]');
  if (links.length === 0) {
    const link = document.createElement("link");
    link.rel = "icon";
    link.href = href;
    document.head.appendChild(link);
    return;
  }
  links.forEach((link) => {
    link.href = href;
    link.removeAttribute("type");
    link.removeAttribute("sizes");
  });
}

type Swatch = { page: string; sidebar: string; panel: string; border: string; primary: string; ink: string };

/** The colours a theme card previews (the same values as globals.css), light and dark, so each card shows its own
 *  theme whatever the page is using. */
export const THEME_SWATCHES: Record<Theme, { light: Swatch; dark: Swatch }> = {
  saffron: {
    light: { page: "#FBF9F5", sidebar: "#F3F0EA", panel: "#FFFFFF", border: "#E4DFD6", primary: "#F2B544", ink: "#1E1A16" },
    dark: { page: "#221F1C", sidebar: "#1C1A17", panel: "#2B2824", border: "#403B34", primary: "#F2B544", ink: "#F2EEE8" },
  },
  ocean: {
    light: { page: "#F7F9FC", sidebar: "#EEF3FA", panel: "#FFFFFF", border: "#E1E7F0", primary: "#2563EB", ink: "#0F172A" },
    dark: { page: "#0F1623", sidebar: "#0B111C", panel: "#162030", border: "#26334A", primary: "#3B82F6", ink: "#E6ECF5" },
  },
  forest: {
    light: { page: "#F6F9F7", sidebar: "#EBF2EE", panel: "#FFFFFF", border: "#DDE7E1", primary: "#2F855A", ink: "#10241A" },
    dark: { page: "#18211C", sidebar: "#121A16", panel: "#1F2A24", border: "#2E3B34", primary: "#52A27A", ink: "#E8F0EB" },
  },
};
