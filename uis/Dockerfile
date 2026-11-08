FROM node:20-alpine

WORKDIR /app

COPY website/package.json ./website/package.json
COPY backoffice/package.json ./backoffice/package.json
RUN npm install --prefix website && npm install --prefix backoffice

COPY . .

EXPOSE 3000 3001

CMD ["./start.sh"]