# syntax=docker/dockerfile:1.7
# One build, two images:
#   web   — the server renderer (react-router-serve on :3000): HTML of every page
#   caddy — frontend/Caddyfile: static files, the admin console, /api and /web routing (default)
# The npm cache survives dependency changes, so a bump downloads only what changed.

FROM node:26-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

# The site (build/client + build/server, react-router build) and the console (build/admin).
FROM deps AS build
COPY . .
# Base path of the API as seen from the browser (Caddy proxies /api to the backend)
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM node:26-alpine AS prod-deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev --no-audit --no-fund

FROM node:26-alpine AS web
WORKDIR /app
ENV NODE_ENV=production PORT=3000
COPY package.json ./
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=build /app/build/server ./build/server
COPY --from=build /app/build/client ./build/client
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD wget -qO /dev/null http://127.0.0.1:3000/healthz || exit 1
CMD ["node_modules/.bin/react-router-serve", "./build/server/index.js"]

FROM caddy:2-alpine AS caddy
COPY --from=build /app/build/client /srv
COPY --from=build /app/build/admin /srv/admin
COPY Caddyfile /etc/caddy/Caddyfile
EXPOSE 80
EXPOSE 443
