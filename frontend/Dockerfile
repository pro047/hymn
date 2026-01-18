FROM node:20-alpine AS builder
WORKDIR /ap

COPY package.json pnpm-lock.yaml* package-lock.json* yarn.lock* ./
RUN corepack enable && pnpm install --frozen-lockfile || npm install

COPY . .
RUN pnpm build || npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]