ARG NODE_IMAGE=node:22-alpine
FROM ${NODE_IMAGE}

WORKDIR /app

ENV NODE_ENV=production

COPY package*.json ./
RUN npm ci --omit=dev

COPY server.mjs ./
COPY public ./public

EXPOSE 8787

CMD ["node", "server.mjs"]
