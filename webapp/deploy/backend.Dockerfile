# Home-deploy backend image (docker-compose, co-located with Caddy on one
# Docker network). Unlike webapp/backend/Dockerfile (the GCP Cloud Run image,
# which listens on Cloud Run's injected $PORT), this one has a fixed port —
# there's no platform injecting one here, and the compose network/Caddyfile
# both hardcode 8000 for this service.
FROM python:3.12-slim

WORKDIR /app

# libpq5: psycopg2-binary's runtime dependency (Postgres path is unused by
# this deploy — SQLite is the default per app/db.py — but kept installable
# in case DATABASE_URL is ever set). curl: container healthcheck below.
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY diagen ./diagen
COPY samples ./samples

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Single worker, non-negotiable: sessions live in an in-memory dict
# (app/diagram_store.py) — see webapp/deploy/README.md.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
