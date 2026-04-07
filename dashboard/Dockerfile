FROM node:20-alpine

RUN apk add --no-cache wget

WORKDIR /app
RUN chown -R node:node /app
USER node

COPY --chown=node:node package.json package-lock.json* ./
RUN npm install

COPY --chown=node:node . .

EXPOSE 5173

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -q --spider http://localhost:5173/ || exit 1

CMD ["npm", "run", "dev", "--", "--host"]
