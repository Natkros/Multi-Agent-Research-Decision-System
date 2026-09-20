/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Phase 10: standalone output produces a minimal self-contained server
  // (node_modules pruned to only what's traced as actually used) so the
  // Docker runtime stage can skip `npm install`/the full node_modules tree.
  output: "standalone",
};

export default nextConfig;
