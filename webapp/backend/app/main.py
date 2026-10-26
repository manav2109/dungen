"""FastAPI backend for the diagen web app.

Design in one line: the Python `diagen` engine (spec parsing, layout,
routing, SVG/draw.io/HTML rendering, templates, outline mode) is the ONLY
place diagram geometry or diagram-editing logic is ever computed. This API
is a thin wrapper around it — every mutating endpoint (create/edit/delete a
node or edge, reparent, auto-arrange, undo/redo, apply a CSV paste, generate
a template) mutates the same live `Diagram` object in the session and
re-renders through the exact same renderer used for the initial render.
There is no second, JS/TS-side copy of layout, routing, or editing logic
anywhere in this project — the React frontend is a thin client over this API.

This module only wires the app together (middleware, startup seeding, router
registration) — the actual endpoints live in `app/routers/*`, request/response
shapes in `app/schemas.py`, and the shared diagram-session helpers in
`app/diagram_helpers.py`.
"""
from __future__ import annotations
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import auth as auth_store
from . import db
from .diagram_store import store  # noqa: F401 — re-exported: tests reach in via app_main.store
from .diagram_helpers import MIN_EDGE_GAP  # noqa: F401 — re-exported: test_api_diagram.py imports this
from .ratelimit import RateLimiter
from .routers import auth as auth_router
from .routers import bootstrap as bootstrap_router
from .routers import diagrams as diagrams_router
from .routers import editing as editing_router
from .routers import templates as templates_router
from .routers import export as export_router
from .routers import projects as projects_router

# Accounts created automatically on startup so the team always has a way in
# without anyone signing up first. Seeding is idempotent: an existing username
# is left completely alone, so a password changed later is never reset by a
# restart. Set SEED_USERS=0 to skip it — do that for any deployment where these
# well-known credentials would be a real exposure.
SEED_USERS = [
    "abhijit.davande",
    "jacob.c",
    "pallash.padman",
    "manav.rathi",
]
SEED_USER_PASSWORD_ENV = "SEED_USER_PASSWORD"


def _seed_password() -> str:
    env_password = os.environ.get(SEED_USER_PASSWORD_ENV)
    if env_password:
        return env_password
    if db.BACKEND == "postgres":
        # These usernames are public (committed to this file, in a public repo),
        # so on a Cloud Run deploy reachable from the internet there's no safe
        # default to fall back to — same reasoning as AUTH_SECRET_KEY in auth.py.
        raise RuntimeError(
            f"{SEED_USER_PASSWORD_ENV} env var is required when running against "
            "Postgres/Cloud Run — the SEED_USERS usernames are public, so the "
            "seeded accounts must not fall back to a guessable default on a "
            "deployment reachable from the internet. Set SEED_USERS=0 instead "
            "if you don't want these accounts at all."
        )
    return "password"


def _seed_users() -> None:
    if os.environ.get("SEED_USERS", "1") == "0":
        return
    seed_password = _seed_password()
    for username in SEED_USERS:
        try:
            if auth_store.get_user_by_username(username):
                continue
            auth_store.create_user(username, seed_password)
            print(f"[seed] created user {username}")
        except Exception as exc:                       # noqa: BLE001
            # A seeding failure must never stop the API from coming up.
            print(f"[seed] could not create {username}: {exc}")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _seed_users()
    yield


app = FastAPI(title="DrawGen API", lifespan=_lifespan)

# `FRONTEND_ORIGIN` (comma-separated) restricts CORS to real cross-origin
# deployments — e.g. GCP Cloud Run, where frontend and backend are two
# separate services on two separate URLs (see webapp/deploy-gcp/). Unset
# (the default, and what webapp/deploy/ uses) falls back to wide-open,
# which is low-risk there specifically because the browser only ever talks
# to Caddy same-origin — Caddy forwards to this backend server-side, so no
# real cross-origin browser request ever happens.
_frontend_origins = [o.strip() for o in os.environ.get("FRONTEND_ORIGIN", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths reachable without a token. Everything else under /api/* requires
# `Authorization: Bearer <token>` — see auth_middleware below.
PUBLIC_API_PATHS = {"/api/health", "/api/auth/signup", "/api/auth/login"}

_limiter = RateLimiter()


def _client_ip(request: Request) -> str:
    # Cloudflare Tunnel sets this to the real visitor IP; fall back for direct/local access.
    return (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for", "").split(",")[0].strip())
        or (request.client.host if request.client else "unknown")
    )


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        ip = _client_ip(request)
        # Tighter limit on auth endpoints — this is the brute-force-guessing surface.
        if request.url.path.startswith("/api/auth/"):
            allowed = _limiter.check(f"auth:{ip}", max_requests=20, window_seconds=60)
        else:
            allowed = _limiter.check(f"api:{ip}", max_requests=300, window_seconds=60)
        if not allowed:
            return JSONResponse({"detail": "Too many requests — slow down."}, status_code=429)
    return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path not in PUBLIC_API_PATHS:
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else None
        payload = auth_store.verify_token(token) if token else None
        if payload is None:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        request.state.user_id = payload["user_id"]
        request.state.username = payload["username"]
    return await call_next(request)


app.include_router(auth_router.router)
app.include_router(bootstrap_router.router)
app.include_router(diagrams_router.router)
app.include_router(editing_router.router)
app.include_router(templates_router.router)
app.include_router(export_router.router)
app.include_router(projects_router.router)
