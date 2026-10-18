import { fileURLToPath } from "node:url";
import path from "node:path";
import { contentSecurityPolicy } from "./csp.mjs";

const repoRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

const CONTENT_SECURITY_POLICY = contentSecurityPolicy({
  development: process.env.NODE_ENV !== "production",
  cognitoDomain: process.env.NEXT_PUBLIC_COGNITO_DOMAIN ?? "",
});

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
  // No dev-tools button (§855). Next 15's `next dev` puts one on every page,
  // labelled "Open Next.js Dev Tools", and the browser suite runs against
  // `next dev`: every test that finds a button by a name containing "Open"
  // found two. It is a development aid only - a production build has none.
  devIndicators: false,
  // No `X-Powered-By: Next.js` on every page (§923), naming the software to
  // anyone matching it against advisories; the API's `server` header goes too.
  poweredByHeader: false,
  // What every page says about itself (§836): not to sniff it, not to frame it
  // anywhere but here - the platform frames its own pages, nothing else may -
  // and to send other sites the origin and no more. The API sets the same
  // three on its own responses (apps/api/src/lib/security_headers.py), because
  // CloudFront sends /api/* to it directly; /api/* is left out here so the
  // dev proxy does not send each header twice.
  async headers() {
    return [{
      source: "/((?!api/).*)",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "SAMEORIGIN" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        // What a page may load and where it may send things (§860, §993):
        // `csp.mjs` says what each directive allows and why.
        { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
      ],
    }];
  },
  async rewrites() {
    // Dev convenience: proxy /api to the local FastAPI process so the browser
    // sees one origin, mirroring the CloudFront layout in production.
    const api = process.env.API_ORIGIN ?? "http://localhost:8300";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
export default nextConfig;
