# diagen web app

React + TypeScript + Axios frontend on top of a FastAPI backend that wraps
the existing `diagen` Python engine. There is exactly **one** place layout,
routing, and diagram-editing logic ever run — the Python engine — so the
frontend is a thin client and can never drift out of sync the way the
standalone JS playground had to be kept in sync by hand. The frontend has
full parity with `diagen_playground.html`: palette drag-to-create, connect
tool, node/edge editing, undo/redo, multi-diagram workbooks, CSV paste,
template generator, outline (mind-map) mode, live style rules, and
SVG/draw.io/HTML export.

```
webapp/
  backend/    FastAPI app (main.py, diagram_store.py) + bundled sample .xlsx files
  frontend/   Vite + React + TypeScript + Axios app
```

## How it fits together

1. You upload an `.xlsx`, pick a bundled sample, generate from a template/outline, or
   start blank → the backend builds/loads a `diagen.Spec`, runs `layout()`, renders SVG +
   draw.io + an HTML snapshot, and caches the live multi-diagram `Spec` in memory under a
   `session_id`.
2. Every edit — drag, palette-create, connect-tool edge, label/color/metadata change,
   delete, duplicate, reparent, auto-arrange, undo/redo, CSV re-apply, style rules — is a
   POST to the backend. It mutates the *same* cached `Diagram` object and re-renders
   through the exact same renderer used for the initial load, so nothing is ever
   recomputed twice or drifts between what you see and what exports.
3. The frontend renders the returned SVG and layers interactivity on top of it: click to
   select/inspect (`PropertiesPanel`), drag to reposition, palette drag-drop or click to
   create, connect-tool click-click to wire two shapes together, search to dim
   non-matching shapes.

One disclosed scope boundary: creating/deleting/reparenting a node triggers a full
auto-layout recompute, rather than the JS playground's precise "resize only the touched
container, leave everyone else exactly where they were" behavior — Python's layout engine
has no in-place container-resize primitive equivalent to that yet.

## Accounts

The app requires a login — real multi-user accounts (`app/auth.py`), not a shared
password. Sign up from the app's own login screen; there's no separate admin bootstrap.
Passwords are PBKDF2-HMAC-SHA256 hashed (stdlib `hashlib`, no `bcrypt`/`passlib`
dependency). Every API route except `/api/health`, `/api/auth/signup`, and
`/api/auth/login` requires `Authorization: Bearer <token>` — enforced by middleware in
`app/main.py`, not per-route, so a route can't accidentally ship unauthenticated.
Saved projects (below) are scoped per-user; nobody can list, load, or delete another
user's saved diagrams. Editing *sessions* (the in-memory `Spec` behind a `session_id`)
are not user-scoped — anyone with a valid token and a `session_id` can act on that
session, matching the original design (a session is a short-lived editing handle, not a
resource with an owner).

## Saved projects

Beyond the ephemeral, TTL'd editing session, a diagram can be explicitly **saved** as a
named project (`app/projects.py`, SQLite at `webapp/backend/data/projects.db`) — survives
backend restarts, reopen anytime from the Projects sidebar tab. The frontend also
auto-saves every 2 minutes once a diagram is tied to a saved project, so a crash loses at
most that much unsaved work. See `webapp/deploy/README.md` for the backup schedule.

## Hardening

- Per-IP rate limiting: 300 req/min general, 20 req/min on `/api/auth/*` (brute-force
  guard on login/signup) — `app/ratelimit.py`, in-memory sliding window.
- Upload cap 15MB, CSV-paste field cap 5MB, 500 saved projects per user, project names
  capped at 200 chars — all return a clean 4xx, never an unbounded-memory 500.
- Session TTL (1h, `app/diagram_store.py`) is based on last activity, not creation time —
  an actively-edited session won't expire out from under you mid-edit.

## Run it

**Backend**
```bash
cd webapp/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
The `diagen` engine lives right here as `webapp/backend/diagen/` (plain local
source, not a separate package) — `app/` imports it directly, nothing extra
to install. See `webapp/backend/README.md` for the engine's own docs.

**Frontend** (separate terminal)
```bash
cd webapp/frontend
npm install
npm run dev
```
Open the URL Vite prints (usually `http://localhost:5173`). The dev server proxies
`/api/*` to `http://127.0.0.1:8000` (see `vite.config.ts`), so there's no CORS setup
needed locally. First run: sign up an account from the login screen — there's no
pre-seeded user.

## Production build
```bash
cd webapp/frontend
npm run build        # outputs frontend/dist — serve it with any static host
```
Point `VITE_API_BASE` (a build-time env var) at wherever you deploy the FastAPI
backend if it isn't reachable at `/api` in that environment.

## API

For the interface changes and frontend verification commands, see
[Editor UI Polish](../docs/editor-ui-polish.md).

All endpoints below except `/api/health`, `/api/auth/signup`, `/api/auth/login` require
`Authorization: Bearer <token>` (see Accounts, above).

| Endpoint | Method | Body | Notes |
|---|---|---|---|
| `/api/health` | GET | — | liveness check, no auth |
| `/api/auth/signup` | POST | `{username, password}` | creates an account, returns `{token, username}`, no auth |
| `/api/auth/login` | POST | `{username, password}` | returns `{token, username}`, no auth |
| `/api/auth/me` | GET | — | `{username}` for the current token |
| `/api/projects` | GET | — | this user's saved projects: `[{id, name, created_at, updated_at}]` |
| `/api/projects/save` | POST | `{session_id, name, project_id?}` | insert new, or update in place if `project_id` is given and owned by you |
| `/api/projects/load` | POST | `{project_id}` | starts a fresh session from a saved project (404 if not yours) |
| `/api/projects/delete` | POST | `{project_id}` | 404 if not yours |
| `/api/samples` | GET | — | bundled sample filenames |
| `/api/palette` | GET | — | standalone default shape/line palette |
| `/api/sample` | POST | `{name}` | load a bundled workbook |
| `/api/upload` | POST | multipart `file` (.xlsx) | load an uploaded workbook |
| `/api/blank` | POST | `{title?}` | start an empty diagram |
| `/api/diagram/{session_id}/list` | GET | — | diagrams in this session's workbook |
| `/api/diagram/switch` | POST | `{session_id, diagram_id}` | switch the active diagram |
| `/api/reposition` | POST | `{session_id, node_id, x, y}` | drag-to-move |
| `/api/node/create` | POST | `{session_id, entity_type, label?, parent?, x?, y?}` | palette/drop create |
| `/api/node/update` | POST | `{session_id, node_id, label?, entity_type?, fill_override?, stroke_override?, metadata?}` | |
| `/api/node/delete` | POST | `{session_id, node_id}` | also removes descendants + incident edges |
| `/api/node/duplicate` | POST | `{session_id, node_id}` | |
| `/api/node/reparent` | POST | `{session_id, node_id, parent}` | |
| `/api/edge/create` | POST | `{session_id, source_id, target_id, relation_type, label?}` | connect tool |
| `/api/edge/update` | POST | `{session_id, edge_id, relation_type?, label?, reverse?}` | |
| `/api/edge/delete` | POST | `{session_id, edge_id}` | |
| `/api/auto-arrange` | POST | `{session_id, direction?}` | `direction`: `TB` \| `LR` |
| `/api/undo` / `/api/redo` | POST | `{session_id}` | per-diagram snapshot history |
| `/api/csv/apply` | POST | `{session_id, nodes_csv, edges_csv?, shapes_csv?, lines_csv?}` | replaces active diagram's data |
| `/api/templates` | GET | — | parameterized diagram generators + their fields |
| `/api/template/generate` | POST | `{template_name, params}` | starts a fresh session |
| `/api/outline/generate` | POST | `{text, entity_type, relation_type}` | indented-text mind-map, fresh session |
| `/api/style-rules` | POST | `{session_id, rules_text}` | transient display-only fill/stroke overlay |

Every mutating endpoint returns the full diagram payload (svg, drawio, html, nodes, edges,
connections, the session's diagrams/shapes/lines, style_rules) so the frontend always has
a complete, consistent snapshot to render from.

Editing sessions are kept in an in-memory, TTL'd dict (`app/diagram_store.py`, TTL
tracked off last activity) — fine for local use; swap for Redis if this ever needs to
survive a backend restart or run multi-process. Saved *projects* are durable (SQLite,
see above) independent of session TTL.
