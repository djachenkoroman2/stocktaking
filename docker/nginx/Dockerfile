FROM nginx:1.28-alpine
# Повторы на случай временной недоступности зеркала Alpine (иначе apk пишет «no such package»)
RUN for i in 1 2 3 4 5; do apk add --no-cache openssl && exit 0; echo "apk: попытка $i не удалась"; sleep 5; done; exit 1
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY 10-certificate.sh /docker-entrypoint.d/10-certificate.sh
RUN chmod +x /docker-entrypoint.d/10-certificate.sh
