# Multi-stage Dockerfile for React SPA Frontend
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first for Docker caching
COPY frontend/package*.json ./
RUN npm install

# Copy source and static assets
COPY frontend/ ./

# Build arguments for browser-accessible backend URLs
ARG VITE_MOVIE_CATALOG_WS_URL=ws://localhost:8000/ws/movies/
ARG VITE_STREAMING_SESSION_WS_URL=ws://localhost:8001/ws/sessions/
ARG VITE_STREAMING_SESSION_HTTP_URL=http://localhost:8001

ENV VITE_MOVIE_CATALOG_WS_URL=$VITE_MOVIE_CATALOG_WS_URL
ENV VITE_STREAMING_SESSION_WS_URL=$VITE_STREAMING_SESSION_WS_URL
ENV VITE_STREAMING_SESSION_HTTP_URL=$VITE_STREAMING_SESSION_HTTP_URL

# Compile TypeScript and build production bundle
RUN npm run build

# Stage 2: Serve with lightweight Nginx web server
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
