FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
ARG VITE_API_BASE_URL=http://127.0.0.1:8001/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM build AS dev
EXPOSE 5173
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0"]

FROM caddy:2-alpine AS prod
COPY --from=build /app/dist /srv
EXPOSE 80 443
