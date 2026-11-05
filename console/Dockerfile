# Carrum Voice console: Next.js standalone server. Listens on 127.0.0.1:3000 (host networking, like the
# dashboard) and proxies /api/* to Django at DJANGO_URL, which is baked in at build time.
# The build needs network access: npm ci, and next/font/google downloads the fonts.

FROM node:22.11-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22.11-alpine AS build
WORKDIR /app
ARG DJANGO_URL=http://127.0.0.1:8787
ENV DJANGO_URL=$DJANGO_URL NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# package.json says "type": "module", and next build copies it next to server.js. With the default
# distDir Next emits an ES module server.js to match; with a custom distDir (the e2e run) it emits
# CommonJS, which then fails with "require is not defined". If server.js is CommonJS, say so.
# The trace also picks up sharp's glibc binaries, which can't load on Alpine (musl); drop them.
RUN npm run build && cd .next/standalone \
  && { grep -q 'import\.meta' server.js || echo '{"type": "commonjs"}' > package.json; } \
  && rm -rf node_modules/@img/sharp-linux-* node_modules/@img/sharp-libvips-linux-*

FROM node:22.11-alpine AS run
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=127.0.0.1 NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
