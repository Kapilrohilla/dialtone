import type { NextConfig } from "next";

// DJANGO_URL is read at build time: the standalone output bakes the rewrites in, and `env` bakes the same
// value into the server code (the root layout reads the project name from it for the page title).
// NEXT_DIST_DIR lets the e2e run (scripts/console-e2e.sh) build into .next/e2e without
// replacing the normal .next build.
const DJANGO_URL = process.env.DJANGO_URL ?? "http://127.0.0.1:8787";

const nextConfig: NextConfig = {
  output: "standalone",
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  skipTrailingSlashRedirect: true,
  env: { DJANGO_URL },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${DJANGO_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
