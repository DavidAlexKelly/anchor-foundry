# Anchor web shell. Multi-stage: workspace-aware install, standalone Next
# build, minimal runtime. NEXT_PUBLIC_* values are baked at build time by
# the control plane's image pipeline per customer (spec §6).
FROM node:20-slim AS deps
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
COPY packages/types/package.json packages/types/
RUN npm ci --no-audit --no-fund

FROM node:20-slim AS build
WORKDIR /repo
COPY --from=deps /repo/node_modules ./node_modules
COPY package.json package-lock.json ./
COPY apps/web apps/web
COPY packages/types packages/types
ARG NEXT_PUBLIC_COGNITO_DOMAIN
ARG NEXT_PUBLIC_COGNITO_CLIENT_ID
ENV NEXT_PUBLIC_COGNITO_DOMAIN=$NEXT_PUBLIC_COGNITO_DOMAIN \
    NEXT_PUBLIC_COGNITO_CLIENT_ID=$NEXT_PUBLIC_COGNITO_CLIENT_ID \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build -w @platform/web

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN useradd --create-home --uid 10001 apprunner
COPY --from=build --chown=apprunner /repo/apps/web/.next/standalone ./
COPY --from=build --chown=apprunner /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=apprunner /repo/apps/web/public ./apps/web/public
USER apprunner
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
