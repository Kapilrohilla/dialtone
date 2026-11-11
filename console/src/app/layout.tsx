import type { Metadata } from "next";
import { Hanken_Grotesk, JetBrains_Mono, Noto_Sans_Devanagari } from "next/font/google";
import { cookies } from "next/headers";
import { themeFromCookie } from "@/lib/theme";
import { Providers } from "./providers";
import "./globals.css";

const hanken = Hanken_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-hanken", display: "swap" });
const devanagari = Noto_Sans_Devanagari({ subsets: ["devanagari"], weight: ["400", "500", "600"], variable: "--font-devanagari", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-jetbrains", display: "swap" });

const DEFAULT_PROJECT_NAME = "Dialtone";

/** The install's name from Django (GET /api/instance/), or "Dialtone" if it doesn't answer within a second.
 *  DJANGO_URL is the same one next.config.ts proxies /api/* to. */
async function projectName(): Promise<string> {
  try {
    const res = await fetch(`${process.env.DJANGO_URL ?? "http://127.0.0.1:8787"}/api/instance/`, {
      cache: "no-store",
      signal: AbortSignal.timeout(1000),
    });
    if (!res.ok) return DEFAULT_PROJECT_NAME;
    const name = ((await res.json()) as { project_name?: unknown }).project_name;
    return typeof name === "string" && name.trim() ? name.trim() : DEFAULT_PROJECT_NAME;
  } catch {
    return DEFAULT_PROJECT_NAME;
  }
}

export async function generateMetadata(): Promise<Metadata> {
  const name = await projectName();
  return {
    title: { default: name, template: `%s - ${name}` },
    description: "Run and review your voice agents.",
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const theme = themeFromCookie((await cookies()).get("cv_theme")?.value);
  return (
    <html lang="en" data-theme={theme} className={`${hanken.variable} ${devanagari.variable} ${mono.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
