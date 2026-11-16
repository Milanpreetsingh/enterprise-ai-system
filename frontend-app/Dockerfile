# -------------------------------------------------------------
# Enterprise AI System - Frontend App Production Dockerfile
# Production Standard: Nginx Alpine, custom SSE proxying, <25MB
# -------------------------------------------------------------

FROM nginx:alpine

# Remove default static pages
RUN rm -rf /usr/share/nginx/html/*

# Copy static web assets
COPY frontend-app/index.html frontend-app/styles.css frontend-app/app.js /usr/share/nginx/html/

# Copy tailored Nginx configuration
COPY frontend-app/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

