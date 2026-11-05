import type { NextConfig } from "next";

// DJANGO_URL is read at build time: the standalone output bakes the rewrites in.
const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.DJANGO_URL ?? "http://127.0.0.1:8787"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
