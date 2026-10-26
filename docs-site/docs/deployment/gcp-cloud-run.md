---
sidebar_position: 2
title: GCP Cloud Run
description: The alternative Cloud Run + Neon Postgres deployment target, kept at effectively $0/month.
---

# GCP Cloud Run

A separate deployment target from [Home Server](/deployment/home-server) —
two independent Cloud Run services plus an external managed Postgres,
rather than one machine running everything behind a tunnel.

```text
Cloud Run "diagen-frontend"  (Caddy + static build)
        ↓ VITE_API_BASE (cross-origin fetch, browser → backend directly)
Cloud Run "diagen-backend"   (FastAPI/uvicorn)
        ↓ TCP/TLS (DATABASE_URL)
Neon Postgres                (external, free tier — the "db service")
```

This corrects two assumptions a naive "three Cloud Run services" design
would make, both driven by a $4-5/month budget ceiling:

1. The database tier isn't a third Cloud Run service running Postgres
   itself — Cloud Run's local disk is ephemeral (wiped on restart, not
   shared across instances), so a real database engine can't safely live
   inside a Cloud Run container without risking corruption on
   restart/redeploy.
2. It's also not **Cloud SQL** (GCP's managed Postgres) — even the
   cheapest tier (`db-f1-micro`) runs ~$8-10/month on its own, over budget
   before anything else is counted. Instead: **[Neon](https://neon.tech)**,
   a free-tier serverless Postgres host — $0/month at this scale, reached
   over the public internet (TLS) rather than Cloud Run's private
   Unix-socket integration. The backend's `DATABASE_URL` env var support
   was built with exactly this option in mind — no code change needed.

The backend runs with `--max-instances=1`, `--min-instances=0` — never more
than one copy at once (sessions live in an in-memory dict; two instances
would each get their own copy and requests would randomly 404 on the wrong
one), and scales to zero when idle so it costs nothing between requests.
The trade-off is a cold start (a few seconds) on the first request after
idling, and if the one instance happens to recycle mid-edit, whoever's
actively editing loses their undo history and anything since the last
auto-save (every 2 min) — saved projects themselves are safe regardless,
since they live in Neon, not that in-memory dict. The frontend (stateless
static files) scales to zero too.

**Cost at this config is effectively $0/month** at low/personal traffic —
Neon's free tier (0.5GB storage, auto-suspends when idle) plus Cloud Run's
free tier (per-service monthly vCPU/memory/request allowances) covers it.
A bill only appears once traffic or stored-project volume grows past those
free-tier ceilings.

## 1. Neon (Postgres, free tier)

Done through Neon's own dashboard, not a `gcloud` command (a CLI,
`neonctl`, exists too if you'd rather script it):

1. Sign up at [neon.tech](https://neon.tech) (free, no credit card
   required for the free tier).
2. Create a project — it creates a default Postgres database and
   connection string for you.
3. Copy the connection string from the dashboard — it looks like
   `postgresql://<user>:<password>@<host>/<dbname>?sslmode=require`. Neon
   requires TLS (`sslmode=require`); `psycopg2` handles that automatically
   from the URL, no extra config needed on the app side.

```bash
DATABASE_URL="postgresql://...you copied this..."   # keep this in your shell for the Secrets step below
```

## Prerequisites

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com \
    artifactregistry.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com
```

## 2. Secrets

Two secrets, both consumed as env vars by the backend service:

```bash
echo -n "$DATABASE_URL" | gcloud secrets create diagen-database-url --data-file=-

# The token-signing secret — MUST be set on Cloud Run; there's no
# file-based fallback there (ephemeral, per-instance disk).
openssl rand -hex 32 | tr -d '\n' | gcloud secrets create diagen-auth-secret --data-file=-
```

## 3. Artifact Registry (image storage)

```bash
gcloud artifacts repositories create diagen \
    --repository-format=docker \
    --location=us-central1

REGION=us-central1
REPO="$REGION-docker.pkg.dev/$(gcloud config get-value project)/diagen"
```

No local Docker is needed anywhere below — every image is built by
**Cloud Build** (`gcloud builds submit`), which uploads your source and
builds the image on GCP's side, so this works even on a machine without
Docker Desktop installed. If you have Docker locally and prefer it, swap
the `gcloud builds submit` line in each step for
`docker build ... && docker push ...` — functionally identical.

## 4. Build + deploy the backend

```bash
cd webapp/backend
gcloud builds submit --tag "$REPO/backend:latest"

gcloud run deploy diagen-backend \
    --image "$REPO/backend:latest" \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated \
    --min-instances=0 \
    --max-instances=1 \
    --cpu-boost \
    --set-secrets="DATABASE_URL=diagen-database-url:latest,AUTH_SECRET_KEY=diagen-auth-secret:latest"

BACKEND_URL=$(gcloud run services describe diagen-backend --region "$REGION" --format='value(status.url)')
echo "$BACKEND_URL"
```

`--allow-unauthenticated`: the app has its own login (see
[Architecture → Web App](/architecture/overview#accounts)) — that's the
access control. If you'd rather also gate it behind Google/IAM auth (e.g.
only people in your GCP org can even reach it), drop that flag and front it
with Identity-Aware Proxy instead — out of scope here.

## 5. Build + deploy the frontend

This needs the backend's URL baked in at build time (Vite env vars are
build-time, not runtime):

```bash
cd ../frontend
gcloud builds submit --config cloudbuild.yaml \
    --substitutions=_VITE_API_BASE="$BACKEND_URL/api",_IMAGE="$REPO/frontend:latest"

gcloud run deploy diagen-frontend \
    --image "$REPO/frontend:latest" \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated

FRONTEND_URL=$(gcloud run services describe diagen-frontend --region "$REGION" --format='value(status.url)')
echo "$FRONTEND_URL"
```

## 6. Lock CORS down to the real frontend URL

Step 4 deployed the backend before the frontend URL existed, so CORS is
still wide open (`FRONTEND_ORIGIN` unset → `allow_origins=["*"]`). Tighten
it now that a real URL exists:

```bash
gcloud run services update diagen-backend \
    --region "$REGION" \
    --set-env-vars="FRONTEND_ORIGIN=$FRONTEND_URL"
```

(`update` merges rather than replaces, so every other env var/secret
already set stays in place.)

## 7. Verify

```bash
curl "$BACKEND_URL/api/health"      # {"status":"ok"}
open "$FRONTEND_URL"                # or just visit it — sign up, save a diagram
```

Confirm data survives a backend restart/cold-start — this is the actual
point of Neon over the in-memory session dict:

```bash
gcloud run services update diagen-backend --region "$REGION" --update-env-vars="_=$(date +%s)"  # force new revision
# reload the frontend, log back in, saved project should still be there
```

## Redeploying after a code change

```bash
# backend:
cd webapp/backend
gcloud builds submit --tag "$REPO/backend:latest"
gcloud run deploy diagen-backend --image "$REPO/backend:latest" --region "$REGION"

# frontend (VITE_API_BASE doesn't change unless the backend URL changes):
cd ../frontend
gcloud builds submit --config cloudbuild.yaml \
    --substitutions=_VITE_API_BASE="$BACKEND_URL/api",_IMAGE="$REPO/frontend:latest"
gcloud run deploy diagen-frontend --image "$REPO/frontend:latest" --region "$REGION"
```

## Testing the Postgres path locally before you deploy

The dual-backend logic picks Postgres automatically whenever `DATABASE_URL`
(or `INSTANCE_CONNECTION_NAME`, if you ever move to Cloud SQL later) is
set — test it against a throwaway local Postgres before trusting it
against the real Neon database:

```bash
docker run -d --name diagen-pg-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=diagen -p 5432:5432 postgres:16

cd webapp/backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
DATABASE_URL="postgresql://postgres:test@localhost:5432/diagen" \
    .venv/bin/uvicorn app.main:app --port 8000
# in another terminal:
# curl -X POST localhost:8000/api/auth/signup -d '{"username":"test","password":"correcthorse1"}' -H 'Content-Type: application/json'
```

If that round-trips (signup → save a project → restart uvicorn → project
still there), the Cloud SQL path will too — same code path, same driver,
only the connection method differs (TCP here vs. a Unix socket on Cloud
Run).

## Cost note

Everything here scales to zero or free tiers at low/personal traffic:
Cloud Run backend + frontend (`min-instances=0`), Neon Postgres (free tier,
auto-suspends when idle), Artifact Registry (free tier covers one image),
Cloud Build (free build-minutes/month). Realistic total: **$0/month** at
this app's scale, growing only if usage genuinely outgrows Neon's free
0.5GB storage or Cloud Run's free monthly request/compute allowances —
still meaningfully less ops than the [Home Server](/deployment/home-server)
path, and cheaper than the Cloud SQL version of this same architecture.

## What's not handled here

- No custom domain / managed TLS cert mapping — Cloud Run gives you a
  `*.run.app` URL out of the box; domain mapping is a separate
  `gcloud run domain-mappings create` step if you want one.
- No CI/CD — these are manual `gcloud builds submit && gcloud run deploy`
  commands. Wire up Cloud Build triggers if you want push-to-deploy.
- No automated backups beyond whatever Neon does on its free tier by
  default — check their retention policy if that matters; paid Neon tiers
  add point-in-time restore.
- Neon's free tier auto-suspends after inactivity — combined with the
  backend also scaling to zero, the very first request after both have
  been idle a while can take noticeably longer (two cold starts stacked,
  not one). Later requests are fast again. An acceptable trade for
  $0/month at low-traffic personal use; worth revisiting (e.g. pinning
  backend `min-instances=1` again, ~$12-15/mo) if that latency ever
  becomes a real problem.
