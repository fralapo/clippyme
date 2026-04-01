FROM node:18-alpine

WORKDIR /app

# Change ownership of /app to node user
RUN chown -R node:node /app

USER node

COPY --chown=node:node package.json package-lock.json* ./

RUN npm install

COPY --chown=node:node . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]
