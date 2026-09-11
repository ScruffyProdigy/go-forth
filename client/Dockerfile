# Build context is the REPO ROOT, not client/ — see api/Dockerfile for why.
#   docker build -f client/Dockerfile .

# ---- Build stage ----
FROM node:20-alpine AS build
WORKDIR /app
COPY client/package.json client/package-lock.json* ./
RUN npm ci
COPY client/ ./
RUN npm run build

# ---- Runtime stage: nginx serving the static build ----
FROM nginx:alpine AS runtime

COPY client/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

# nginx:alpine runs everything in /docker-entrypoint.d/ before starting nginx.
# This script writes /env.js from container env vars, so ONE image runs in
# local, staging and production — the config arrives at container start rather
# than being frozen into the bundle at build time.
COPY client/docker-entrypoint.d/40-env-js.sh /docker-entrypoint.d/40-env-js.sh
RUN chmod +x /docker-entrypoint.d/40-env-js.sh

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
