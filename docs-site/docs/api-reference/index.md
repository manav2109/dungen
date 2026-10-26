---
sidebar_position: 1
title: API Reference
description: Where to find the live, always-current API docs instead of a hand-maintained copy.
---

# API Reference

The backend is a FastAPI app, and FastAPI generates interactive API
documentation automatically from the route definitions — `app/main.py`
never overrides `docs_url`, `redoc_url`, or `openapi_url`, so all three
defaults are live:

| What | Path (relative to the backend's own root) |
|---|---|
| Swagger UI | `/docs` |
| ReDoc | `/redoc` |
| Raw OpenAPI schema | `/openapi.json` |

This page intentionally doesn't re-author that reference by hand — it
would just drift out of sync with the real routes. For a structural,
human-written overview of the endpoints instead, see
[Architecture → Web App](/architecture/overview#api).

## In local development

With the backend running directly (`uvicorn app.main:app --port 8000`, see
[Web App → Run it](/architecture/overview#run-it)), the live docs are at:

```text
http://localhost:8000/docs
http://localhost:8000/redoc
http://localhost:8000/openapi.json
```

(Adjust the port if you ran uvicorn on a different one.)

## In production

:::caution[Not currently wired through]
Caddy's `handle /api/*` block forwards the request path to the backend
**unchanged** — it doesn't strip the `/api` prefix. That's correct for the
app's own routes, since they're already declared with a literal `/api/...`
path (see the [endpoint table](/architecture/overview#api)). But FastAPI's
auto-generated `/docs`, `/redoc`, and `/openapi.json` routes are fixed at
the backend's root regardless of how other routes are prefixed — so a
request to `/api/docs` doesn't match anything the backend serves, and a
request to the bare `/docs` on this domain now reaches *this*
documentation site instead (same path, different purpose, same domain).

Net effect: the live Swagger/ReDoc UI isn't currently exposed publicly
under `drawgen.dev-ai.site` at all, through either `/api/docs` or `/docs`.
Reaching it today means running the backend locally and using the
`localhost` URLs above. Exposing it in production needs either a small
backend-side alias (serving those three routes again under an `/api/`
prefix) or a dedicated Caddy rule for just those three paths — tracked as a
follow-up for whoever owns the Caddy configuration, not something this
docs site can route around on its own.
:::
