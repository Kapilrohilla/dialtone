import type { Metadata } from "next";
import { Hanken_Grotesk, JetBrains_Mono, Noto_Sans_Devanagari } from "next/font/google";
import { cookies } from "next/headers";
import { cache } from "react";
import { DEFAULT_FAVICON, DEFAULT_THEME, themeOrDefault, type Theme } from "@/lib/palette";
import { themeFromCookie } from "@/lib/theme";
import { Providers } from "./providers";
import "./globals.css";

const hanken = Hanken_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-hanken", display: "swap" });
const devanagari = Noto_Sans_Devanagari({ subsets: ["devanagari"], weight: ["400", "500", "600"], variable: "--font-devanagari", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-jetbrains", display: "swap" });

const DEFAULT_PROJECT_NAME = "Dialtone";

type InstanceLook = { name: string; theme: Theme; logoUrl: string | null };

const FALLBACK: InstanceLook = { name: DEFAULT_PROJECT_NAME, theme: DEFAULT_THEME, logoUrl: null };

/** The install's name, theme and logo from Django (GET /api/instance/), or the defaults if it doesn't answer within a
 *  second. One request per page render: generateMetadata and the layout share it. DJANGO_URL is the same one
 *  next.config.ts proxies /api/* to. */
const instanceLook = cache(async (): Promise<InstanceLook> => {
  try {
    const res = await fetch(`${process.env.DJANGO_URL ?? "http://127.0.0.1:8787"}/api/instance/`, {
      cache: "no-store",
      signal: AbortSignal.timeout(1000),
    });
    if (!res.ok) return FALLBACK;
    const body = (await res.json()) as { project_name?: unknown; theme?: unknown; logo_url?: unknown };
    const name = typeof body.project_name === "string" && body.project_name.trim() ? body.project_name.trim() : DEFAULT_PROJECT_NAME;
    const logoUrl = typeof body.logo_url === "string" && body.logo_url.startsWith("/api/") ? body.logo_url : null;
    return { name, theme: themeOrDefault(body.theme), logoUrl };
  } catch {
    return FALLBACK;
  }
});

export async function generateMetadata(): Promise<Metadata> {
  const { name, logoUrl } = await instanceLook();
  return {
    title: { default: name, template: `%s - ${name}` },
    description: "Run and review your voice agents.",
    icons: { icon: logoUrl ?? DEFAULT_FAVICON },
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const theme = themeFromCookie((await cookies()).get("cv_theme")?.value);
  // data-theme is the user's light / dark choice; data-palette is the install's theme.
  const { theme: palette } = await instanceLook();
  return (
    <html lang="en" data-theme={theme} data-palette={palette} className={`${hanken.variable} ${devanagari.variable} ${mono.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
