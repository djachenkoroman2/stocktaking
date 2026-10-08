#!/bin/sh
# Если сертификат не подключён (TLS_CERT_PATH/TLS_KEY_PATH), создаётся самоподписанный — только для первого запуска.
set -e
if [ ! -f /etc/nginx/certs/server.crt ] || [ ! -f /etc/nginx/certs/server.key ]; then
  mkdir -p /etc/nginx/certs
  echo "Сертификат не найден: создаю самоподписанный для ${SERVER_NAME:-localhost}"
  openssl req -x509 -nodes -newkey rsa:2048 -days 365 -subj "/CN=${SERVER_NAME:-localhost}" \
    -keyout /etc/nginx/certs/server.key -out /etc/nginx/certs/server.crt 2>/dev/null
fi
