import type { Metadata } from "next";
import { Hanken_Grotesk, JetBrains_Mono, Noto_Sans_Devanagari } from "next/font/google";
import { cookies } from "next/headers";
import { themeFromCookie } from "@/lib/theme";
import { Providers } from "./providers";
import "./globals.css";

const hanken = Hanken_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-hanken", display: "swap" });
const devanagari = Noto_Sans_Devanagari({ subsets: ["devanagari"], weight: ["400", "500", "600"], variable: "--font-devanagari", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-jetbrains", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Carrum Voice", template: "%s - Carrum Voice" },
  description: "Run and review your voice agents.",
};

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
