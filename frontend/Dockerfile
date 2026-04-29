FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:20-alpine AS builder
ARG BACKEND_ORIGIN=http://backend:8000
ENV BACKEND_ORIGIN=${BACKEND_ORIGIN}
WORKDIR /app
COPY --from=deps /app/node_modules /app/node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
ARG BACKEND_ORIGIN=http://backend:8000
ENV BACKEND_ORIGIN=${BACKEND_ORIGIN}
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next /app/.next
COPY --from=builder /app/public /app/public
COPY --from=builder /app/package*.json /app/
COPY --from=builder /app/node_modules /app/node_modules
COPY --from=builder /app/next.config.mjs /app/next.config.mjs

EXPOSE 3000
CMD ["npm", "run", "start"]
