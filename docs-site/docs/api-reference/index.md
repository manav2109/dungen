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

Bare `/docs` on this domain reaches *this* documentation site, not the
backend's Swagger UI — that path's already claimed here. The backend's own
interactive docs are reachable instead under the `/api/` prefix, via a
Caddy rule that rewrites the three routes above to the backend's
unprefixed paths before proxying (FastAPI's `docs_url`/`redoc_url`/
`openapi_url` are still the plain defaults — `app/main.py` is untouched):

```text
https://drawgen.dev-ai.site/api/docs
https://drawgen.dev-ai.site/api/redoc
https://drawgen.dev-ai.site/api/openapi.json
```
