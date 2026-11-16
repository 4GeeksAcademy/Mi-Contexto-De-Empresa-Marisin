FROM node:20-alpine

WORKDIR /app

COPY website/package.json ./website/package.json
COPY backoffice/package.json ./backoffice/package.json
COPY application/package.json ./application/package.json
RUN npm install --prefix website && npm install --prefix backoffice && npm install --prefix application

COPY . .

EXPOSE 3000 3001 3002

CMD ["./start.sh"]
