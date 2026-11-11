FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 dashboard && mkdir /data && chown dashboard /data
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Settings need a secret key and a database password to import; this throwaway one is only used to collect static files.
RUN DJANGO_SECRET_KEY=collectstatic-only POSTGRES_PASSWORD=collectstatic-only python manage.py collectstatic --noinput

USER dashboard
# exec: uvicorn becomes PID 1 and gets SIGTERM directly, so `docker compose down` stops it promptly.
# Cutover from the old SQLite file runs here, before the server accepts webhooks (no-op once copied).
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py copy_from_sqlite --if-needed && exec uvicorn config.asgi:application --host ${DASHBOARD_HOST:-127.0.0.1} --port ${DASHBOARD_PORT:-8787}"]
