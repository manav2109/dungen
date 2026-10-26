---
sidebar_position: 1
title: Home Server
description: The bash-watchdog deployment behind a Cloudflare Tunnel and Caddy — architecture, setup, and day-to-day commands.
---

# Home Server

```text
Internet → Cloudflare edge (TLS, random *.trycloudflare.com URL)
         → cloudflared (outbound-only, no router config needed)
         → Caddy :8080  → /api/*  → uvicorn 127.0.0.1:8000 (backend)
                         → /*      → frontend/dist (static files)
```

No Docker, no port forwarding, no router changes. Four lightweight
processes (backend, Caddy, tunnel, backup), each supervised by its own bash
watchdog script (`*-watchdog.sh`) plus a Task Scheduler entry, so they
auto-start at login and restart if they crash. Everything here runs
through Git Bash — no PowerShell.

:::tip[Docker Compose alternative]
A container-based version of this same deployment also exists — see
[Docker](#docker) below. It's additive, not a replacement for the
bash-watchdog path on this page: pick one per machine, don't run both
against the same data at once.
:::

The backend runs as **one uvicorn worker** — required. Sessions live in an
in-memory dict; multiple workers would each get their own copy, and
requests would randomly 404 on the wrong worker.

The app requires a login (real multi-user accounts — see
[Product Requirements](/product/requirements)). Nobody can use it,
including you, until someone signs up through the app's own signup screen
once it's live — there's no separate admin bootstrap step; the first
signup is just a normal account.

No Cloudflare account, login, or domain is needed for this path — it uses
Cloudflare's anonymous Quick Tunnel. The trade-off is that the public URL
is random (`https://something-random.trycloudflare.com`) and **changes
every time the tunnel restarts**. Fine to get live today; see
[Upgrade to a named tunnel](#upgrade-to-a-named-tunnel) below if you later
want a stable custom domain.

## One-click setup / redeploy

```bash
cd webapp/deploy
bash setup.sh
```

Works on Linux, macOS, and Windows (via Git Bash) — detects the OS and
picks the right package manager (`winget`/`brew`/`apt`/`dnf`/`pacman`) and
binary downloads for each. Installs any missing tools (Python, Node),
creates the venv, builds the frontend, downloads Caddy/cloudflared, checks
Cloudflare tunnel auth, and (re)starts all four services — safe to re-run
any time, on this machine or a new one. `bash setup.sh --register` also
sets services to auto-start at login/boot (Task Scheduler / launchd /
crontab depending on OS). Moving to a different machine needs either a copy
of `~/.cloudflared/` from this one, or `bash setup.sh --new-tunnel` to
create a fresh tunnel. Full details live in the script's own header
comment.

The manual steps below are what that script automates — kept here for
reference and troubleshooting.

## One-time setup

If you've already run these — venv, frontend build, Caddy/cloudflared
downloaded into `bin/` — skip to [Sanity-check](#sanity-check-each-piece-manually).

```bash
cd webapp/deploy
mkdir -p bin
```

**1. Backend venv**

```bash
cd ../backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cd ../deploy
```

**2. Frontend build**

```bash
cd ../frontend
npm install
npm run build
cd ../deploy
```

**3. Caddy + cloudflared** (single exes, no installer)

```bash
cd bin
CADDY_URL=$(curl -sL "https://api.github.com/repos/caddyserver/caddy/releases/latest" \
  | grep "browser_download_url.*windows_amd64.zip\"" | cut -d '"' -f 4)
curl -L -o caddy.zip "$CADDY_URL"
powershell -Command "Expand-Archive -Path caddy.zip -DestinationPath . -Force"
rm caddy.zip
curl -L -o cloudflared.exe "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
cd ..
```

(The PowerShell call above only unzips a file — the only Windows-native way
to do that without a separate tool — no PowerShell scripts of our own are
involved anywhere in this deployment.)

## Sanity-check each piece manually

Run one at a time from `webapp/deploy`, Ctrl+C before starting the next:

```bash
bash backend-watchdog.sh    # then in a browser: http://127.0.0.1:8000/api/health
bash caddy-watchdog.sh      # then: http://127.0.0.1:8080  (needs backend running too)
bash tunnel-watchdog.sh     # prints a trycloudflare.com URL — check logs/tunnel.log in another terminal
```

## Register as Task Scheduler entries

`schtasks` is a native Windows command — no PowerShell needed. Each
watchdog script already loops forever internally (restarting the process
it wraps on crash), so Task Scheduler's job is just "start this once at
login":

```bash
DEPLOY_DIR=$(cygpath -w "$(pwd)")
BASH_EXE=$(cygpath -w "$(command -v bash)")

for name in backend caddy tunnel backup; do
  schtasks /create /tn "diagen-$name" \
    /tr "\"$BASH_EXE\" \"$DEPLOY_DIR\\$name-watchdog.sh\"" \
    /sc onlogon /rl limited /f
done
```

Start them now (without logging out/in):

```bash
for name in backend caddy tunnel backup; do
  schtasks /run /tn "diagen-$name"
  sleep 2
done
```

Get your public URL:

```bash
bash check-url.sh
```

Open that URL from any device off your network to confirm it's actually
public, not just reachable on localhost.

## Operating it day to day

Starting, stopping, restarting a single service, redeploying after a code
change, reading logs, and restoring from backup are all covered in the
[Operator Guide](/user-guide/operations) — that page is the one to bookmark
once this is running.

## Upgrade to a named tunnel

Needs a domain added to a free Cloudflare account:

```bash
./bin/cloudflared.exe tunnel login                      # opens browser, one-time auth
./bin/cloudflared.exe tunnel create diagen
./bin/cloudflared.exe tunnel route dns diagen app.yourdomain.com
```

Then replace `tunnel-watchdog.sh`'s run line with:

```bash
"$CF_EXE" tunnel run --url http://127.0.0.1:8080 diagen >> "$LOG_FILE" 2>&1
```

(or a `config.yml` with an ingress rule — see cloudflared's own docs). The
URL becomes fixed (`https://app.yourdomain.com`), so there's no more need
to check `check-url.sh`.

## Docker

A Docker Compose version of the same four processes (`backend`, `caddy`,
`tunnel`, `backup`) lives alongside the bash-watchdog setup above, not in
place of it. Both read and write the same hardcoded backend data path
(`webapp/backend/data/` → a named volume when containerized), so **don't
run both against the same data at the same time** — pick one path per
machine until you've actually cut over.

None of it reuses the GCP-oriented Dockerfiles from
[GCP Cloud Run](/deployment/gcp-cloud-run) — those target two independent,
cross-origin Cloud Run services with no in-process `/api` proxy, a
different shape entirely:

| File | Role |
|---|---|
| `docker-compose.yml` | The four services |
| `backend.Dockerfile` | `python:3.12-slim`, fixed `--port 8000 --workers 1` (no Cloud-Run-style `$PORT` indirection) |
| `frontend.Dockerfile` | Builds the frontend, then becomes the `caddy` service's image (`FROM caddy:2-alpine`, frontend dist + `portal/` + `Caddyfile.docker` baked in) — one shared Caddy serving both hostnames, matching what's actually live today rather than two independent static servers |
| `Caddyfile.docker` | Same routing as `./Caddyfile`, retargeted at container-network service names instead of `127.0.0.1`/relative paths, plus a `/docs/*` block for this documentation site's build |
| `.env.example` | Copy to `.env` (gitignored) and fill in |

### Quick start

```bash
cd webapp/deploy
cp .env.example .env
# edit .env: at minimum set CLOUDFLARED_CERT_PATH / CLOUDFLARED_CREDENTIALS_PATH
docker compose up -d --build backend caddy backup
```

`tunnel` is deliberately left out of that command — see
[About the tunnel service](#about-the-tunnel-service) below. The
`backend`/`caddy` host ports default to 8001/8081 (not 8000/8080)
specifically so this can come up side-by-side with the live bash-watchdog
stack without a port conflict; see `.env.example`.

Verify the same way as the bash setup's own sanity-check, just on the
alternate ports:

```bash
curl http://127.0.0.1:8001/api/health
curl -H "Host: drawgen.dev-ai.site" http://127.0.0.1:8081/
```

Or point a hosts-file entry at `127.0.0.1` for `drawgen.dev-ai.site` /
`dev-ai.site` and browse normally on port 8081.

### About the tunnel service

It points the **existing** named tunnel `diagen` (already bound to
`dev-ai.site` + `drawgen.dev-ai.site` — this never creates a new tunnel or
touches DNS) at this stack's `caddy` container. Cloudflare load-balances a
named tunnel's traffic across *every* currently-connected replica, so
starting this container while `tunnel-watchdog.sh` is also running would
send some share of real visitors to whichever backend/data this stack
happens to have up at the time. Only start it for a real cutover, after
the bash watchdogs are stopped:

```bash
# stop the bash side first (see "Stopping / removing" above), then:
docker compose up -d tunnel
```

### Persistence

`projects.db`, `secret.key`, and `backups/` all live under one named
volume, `diagen-data`, mounted at `/app/data` in the backend container —
the same path the backend already hardcodes, so no code change was needed.
`docker compose down` (without `-v`) leaves the volume alone;
`docker compose down -v` deletes it, same as deleting
`webapp/backend/data/` by hand — don't pass `-v` unless that's actually
what you want.

### Running the backend test suite against the image's own environment

```bash
docker compose build backend
docker run --rm \
  -v "$(pwd)/../backend:/app" \
  -w /app \
  --entrypoint sh \
  diagen-backend:latest \
  -c "pip install --no-cache-dir -r requirements-dev.txt && pytest -q"
```

Confirms the `python:3.12-slim` base image plus `requirements.txt` pins
pass the same suite the bash deploy's `.venv` does — catches
dependency/version drift the Dockerfile's base image choice could
otherwise introduce silently.

## Notes / known trade-offs

- Single point of failure: your machine's power and internet. No failover.
- A live editing session (undo history, unsaved in-progress edits) is
  still in-memory — a backend restart drops anything not saved. The app
  auto-saves every 2 minutes once a diagram is tied to a saved project, on
  top of manual Save. `diagen-backup` copies
  `webapp/backend/data/projects.db` (users + saved diagrams — the only
  durable state) every 6h to `data/backups/`, pruned after 14 days. Restore
  by stopping `diagen-backend` and copying a backup file back over
  `data/projects.db`.
- Accounts are real multi-user (signup/login, PBKDF2-hashed passwords,
  each user only sees their own saved projects). No email verification or
  password reset — this is a self-hosted tool with no mail server
  configured. If someone forgets their password, there's no recovery flow;
  they need a new account, or a direct edit of `data/projects.db`'s `users`
  table.
- Rate-limited: 300 req/min/IP generally, 20 req/min/IP on `/api/auth/*`
  (signup/login) to slow down password guessing. Uploads capped at 15MB,
  CSV pastes at 5MB, 500 saved projects per user.
- CORS is left wide open (`allow_origins=["*"]`) — harmless here because
  the browser only ever talks to Caddy (same-origin); Caddy is what
  forwards to the backend server-side. Worth tightening anyway if this
  ever gets a real domain and you want defense in depth.
- Check your ISP's terms of service — some residential plans restrict
  running always-on servers.
