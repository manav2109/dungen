# Cloud Run backend image. Listens on $PORT (Cloud Run injects this, 8080
# by default) — never hardcode the port, Cloud Run health-checks whatever
# it told the container to listen on.
FROM python:3.12-slim

WORKDIR /app

# psycopg2-binary needs libpq at runtime; build deps only needed transiently
# if a wheel isn't available for the target arch, so this stays slim either way.
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY app ./app
COPY diagen ./diagen
COPY samples ./samples

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# Single worker: sessions live in an in-memory dict (app/diagram_store.py) —
# see webapp/deploy-gcp/README.md for why this service is pinned to one
# Cloud Run instance rather than autoscaled.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
