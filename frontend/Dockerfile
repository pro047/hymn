FROM node:22-alpine AS builder
WORKDIR /app

COPY package.json pnpm-workspace.yaml* pnpm-lock.yaml* package-lock.json* yarn.lock* ./
RUN corepack enable && pnpm install --frozen-lockfile || npm install

COPY . .

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN pnpm build || npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# Overwrites the stock default.conf, whose lack of an SPA fallback makes every
# client route — including the /login the app hard-navigates to on logout — a
# 404. See the file itself for why this is not only about deep links.
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
