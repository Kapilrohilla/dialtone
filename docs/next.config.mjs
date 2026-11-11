import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** @type {import('next').NextConfig} */
const config = {
  // Static site for GitHub Pages: https://kapilrohilla.github.io/dialtone/
  output: 'export',
  basePath: '/dialtone',
  images: { unoptimized: true },
  trailingSlash: true,
  reactStrictMode: true,
};

export default withMDX(config);
