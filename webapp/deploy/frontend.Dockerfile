# Builds the frontend, then hands the static output to the SAME Caddy image
# this compose stack uses for the "caddy" service — one Caddy serving both
# hostnames (dev-ai.site, drawgen.dev-ai.site) + the /api proxy, matching
# what's actually live today. This is deliberately NOT webapp/frontend/
# Dockerfile (the GCP image): that one runs its own standalone Caddy as a
# second, independent service talking cross-origin to the backend — wrong
# shape for this single-host deploy.
#
# Build context must be webapp/ (the parent of both frontend/ and deploy/),
# since this file also needs deploy/portal and deploy/Caddyfile.docker —
# see docker-compose.yml's `caddy` service.

FROM node:20-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv/frontend
COPY deploy/portal /srv/portal
COPY deploy/Caddyfile.docker /etc/caddy/Caddyfile
EXPOSE 8080
