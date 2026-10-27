# Builds the SPA, then serves it with nginx, which also forwards /api to the backend (see nginx.conf).
FROM node:25-slim AS build
WORKDIR /fe
RUN npm install -g pnpm@11.9.0
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm exec vite build           # tsc is skipped here: the generated client is committed and checked in dev

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /fe/dist /usr/share/nginx/html
