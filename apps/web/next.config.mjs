import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // No image optimizer (§806). Nothing here uses `next/image`, and the
  // optimizer's endpoint is where Next 14's unpatched advisories live -
  // GHSA-2xp9-vwfh-vxw4 (remote code execution via AVIF) among them - so the
  // endpoint is switched off rather than left serving nothing on purpose.
  images: { unoptimized: true },
  // Pin tracing to the monorepo root so the standalone layout is stable
  // (apps/web/server.js) regardless of where the build runs - the web
  // Dockerfile's COPY paths depend on it.
  outputFileTracingRoot: repoRoot,
  async rewrites() {
    // Dev convenience: proxy /api to the local FastAPI process so the browser
    // sees one origin, mirroring the CloudFront layout in production.
    const api = process.env.API_ORIGIN ?? "http://localhost:8300";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
export default nextConfig;
