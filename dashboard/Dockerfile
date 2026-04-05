FROM nginx:alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY dashboard/index.html /usr/share/nginx/html/index.html
COPY dashboard/login.html /usr/share/nginx/html/login.html
