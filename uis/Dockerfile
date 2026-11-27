FROM node:20-alpine

# Node no corre como root (auditoría OWASP, D17): /app y las dependencias son del usuario `node`.
WORKDIR /app
RUN chown node:node /app

USER node

COPY --chown=node:node website/package.json ./website/package.json
COPY --chown=node:node backoffice/package.json ./backoffice/package.json
COPY --chown=node:node application/package.json ./application/package.json
RUN npm install --prefix website && npm install --prefix backoffice && npm install --prefix application

COPY --chown=node:node . .

EXPOSE 3000 3001 3002

CMD ["./start.sh"]
