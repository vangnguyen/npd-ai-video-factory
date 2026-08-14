FROM node:22-bookworm-slim

WORKDIR /renderer
COPY package.json tsconfig.json ./
RUN npm install --no-audit --no-fund
COPY src ./src

EXPOSE 3001
CMD ["npm", "start"]
