# ── Build stage ──
FROM node:20-alpine AS build
WORKDIR /app
COPY dashboard-new/package.json dashboard-new/package-lock.json ./
RUN npm ci
COPY dashboard-new/ ./
RUN npm run build

# ── Serve stage ──
FROM nginx:alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY dashboard-new/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
