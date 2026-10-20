# syntax=docker/dockerfile:1.7
# Build stage: the site (dist) and the admin console (build/admin, vite.admin.config.ts)
FROM node:26-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
# The npm cache survives dependency changes, so a bump downloads only what changed.
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

COPY . .

# Base path of the API as seen from the browser (Caddy proxies /api to the backend)
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# Serve stage
FROM caddy:2-alpine

COPY --from=build /app/dist /srv
COPY --from=build /app/build/admin /srv/admin
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 80
EXPOSE 443
