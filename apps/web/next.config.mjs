import { fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Pin tracing to the monorepo root so the standalone layout is stable
  // (apps/web/server.js) regardless of where the build runs — the web
  // Dockerfile's COPY paths depend on it.
  experimental: { outputFileTracingRoot: repoRoot },
  async rewrites() {
    // Dev convenience: proxy /api to the local FastAPI process so the browser
    // sees one origin, mirroring the CloudFront layout in production.
    const api = process.env.API_ORIGIN ?? "http://localhost:8300";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
export default nextConfig;
