FROM node:22-alpine AS build
WORKDIR /opt/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:alpine
RUN sed -i 's@/var/run/nginx.pid@/tmp/nginx.pid@' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /var/cache/nginx
COPY infrastructure/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /opt/frontend/dist /usr/share/nginx/html
USER nginx
