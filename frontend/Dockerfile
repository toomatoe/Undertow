# Standalone image for the Next.js frontend (output: "standalone" in next.config.ts). Used by the optional
# `web` service in docker-compose.yml (`docker compose --profile web up -d --build`). The defaults are local:
#   docker build -t afterfile-web \
#     --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 \
#     --build-arg NEXT_PUBLIC_SITE_URL=http://localhost:3000 frontend
# NEXT_PUBLIC_* values are inlined into the browser bundle at build time: rebuild to change them.
# API_URL_INTERNAL (server-side fetches, e.g. http://api:8000 inside compose) is read at runtime.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_SITE_URL=http://localhost:3000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# The repo has no public/ directory yet; create it so the runner COPY below always succeeds.
RUN mkdir -p public && npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 1001 nodejs && adduser -S -u 1001 -G nodejs nextjs
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
