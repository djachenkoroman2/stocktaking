FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DJANGO_MEDIA_ROOT=/data/media DJANGO_STATIC_ROOT=/data/static DJANGO_EXPORT_ROOT=/data/exports

# Библиотеки для WeasyPrint (PDF-отчёты) и шрифты с кириллицей.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
      fonts-dejavu-core fonts-liberation postgresql-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --system --uid 1000 --home /app app \
 && mkdir -p /data/media /data/static /data/exports && chown -R app /data \
 && chmod +x docker/entrypoint.sh
USER app

EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "180", \
     "--access-logfile", "-", "--no-control-socket"]
