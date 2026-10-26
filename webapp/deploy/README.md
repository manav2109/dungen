# Deploying diagen from this machine

**Current setup: Docker Compose.** `webapp/deploy/docker-compose.yml` runs
the 4 services (`backend`, `caddy`, `tunnel`, `backup`) against the named
Cloudflare tunnel already bound to `dev-ai.site` / `drawgen.dev-ai.site`.
Cut over from the original bash-watchdog setup on 2026-10-26 — that setup
is kept below under "Legacy" for reference/rollback, but it's not what's
currently serving the site.

```
Internet → Cloudflare edge (named tunnel "diagen")
         → cloudflared container ("tunnel")
         → Caddy container ("caddy") :8080  → /api/*    → backend container :8000
                                             → /docs/*   → Docusaurus build (bind-mounted)
                                             → /*        → frontend build (baked into the image)
```

Backend runs as **one uvicorn worker** — required. Sessions live in an
in-memory dict (`app/diagram_store.py`); multiple workers would each get
their own copy and requests would randomly 404 on the wrong worker.

The app requires a login (multi-user accounts — see
`docs/PRD-user-ready.md`). Nobody can use it, including you, until someone
signs up through the app's own signup screen once it's live — there's no
separate admin bootstrap step, the first signup is just a normal account.

## Docker (current setup)

New files, none of them reusing the GCP-oriented Dockerfiles in
`webapp/backend/Dockerfile` / `webapp/frontend/Dockerfile` (those target
Cloud Run: two independent services, cross-origin, no in-process `/api`
proxy — see `webapp/deploy-gcp/README.md`):

- `docker-compose.yml` — the 4 services.
- `backend.Dockerfile` — `python:3.12-slim`, fixed `--port 8000 --workers 1`
  (no Cloud-Run-style `$PORT` indirection).
- `frontend.Dockerfile` — builds the frontend, then becomes the `caddy`
  service's image (`FROM caddy:2-alpine`, frontend dist + `portal/` +
  `Caddyfile.docker` baked in) — one shared Caddy serving both hostnames,
  not two independent static servers.
- `Caddyfile.docker` — same routing as the legacy `./Caddyfile`, retargeted
  at container-network service names instead of `127.0.0.1`/relative
  paths, plus a `/docs/*` block for the Docusaurus build.
- `.env.example` — copy to `.env` (gitignored) and fill in.

### Fresh setup / redeploy to a new machine

```bash
cd webapp/deploy
cp .env.example .env
# edit .env: at minimum set CLOUDFLARED_CERT_PATH / CLOUDFLARED_CREDENTIALS_PATH
docker compose build backend caddy
docker compose up -d backend caddy backup
```

`tunnel` is left out of that command on purpose — see "About the `tunnel`
service" below. `backend`/`caddy`'s host ports default to 8001/8081, not
8000/8080, so this can come up without a port conflict if anything else
(e.g. a resurrected bash-watchdog stack) is still using those — safe to
point them at 8000/8080 in `.env` instead on a clean machine where nothing
else is listening there.

Verify, then add the tunnel once you're satisfied:

```bash
curl http://127.0.0.1:8001/api/health
curl -H "Host: drawgen.dev-ai.site" http://127.0.0.1:8081/
docker compose up -d tunnel
```

Or point a hosts-file entry at `127.0.0.1` for `drawgen.dev-ai.site` /
`dev-ai.site` and browse normally on port 8081 before flipping the tunnel.

### About the `tunnel` service

It points the **existing** named tunnel `diagen` (already bound to
`dev-ai.site` + `drawgen.dev-ai.site` — this never creates a new tunnel or
touches DNS) at this stack's `caddy` container. Cloudflare load-balances a
named tunnel's traffic across *every* currently-connected replica — so if
you ever bring up a second stack (e.g. testing a change, or the legacy bash
`tunnel-watchdog.sh`) while this one's tunnel is also running, some share
of real visitors gets routed to whichever backend/data that second stack
has up at the time. Keep it to one connected replica at a time; stop
whichever one isn't supposed to be live before starting the other's
tunnel.

### Day-to-day

```bash
docker compose ps                 # status
docker compose logs -f backend    # or caddy / tunnel / backup
```

Redeploy after a code change — Compose only rebuilds/restarts the service
that changed:

```bash
docker compose up -d --build backend   # backend change
docker compose up -d --build caddy     # frontend change (rebuilds + redeploys the frontend too)
```

Stop / restart:

```bash
docker compose restart backend   # one service
docker compose down               # everything — keeps the named volume
docker compose up -d              # bring it all back
```

`restart: unless-stopped` on every service means Docker restarts them
automatically on crash, and again whenever Docker Desktop itself starts
(e.g. at login) — no Task Scheduler / watchdog-script equivalent needed,
as long as Docker Desktop is set to start at login (its default).
That covers the same cases the legacy `--register` step did, with the same
caveat: it fires at user login, not at a raw unattended boot with nobody
logging in — identical characteristic to `schtasks /sc onlogon`, not a
regression.

### Persistence

`projects.db`, `secret.key`, and `backups/` all live under one named
volume, `diagen-data`, mounted at `/app/data` in the backend container —
the same path `app/auth.py`/`app/db.py` already hardcode, so no code
change was needed. `docker compose down` (without `-v`) leaves the volume
alone; `docker compose down -v` deletes it, same as deleting
`webapp/backend/data/` by hand — don't pass `-v` unless that's actually
what you want.

### Running the backend test suite against the image's own environment

```bash
docker compose build backend
docker run --rm \
  -v "$(pwd)/../backend:/app" \
  -w /app \
  --entrypoint sh \
  deploy-backend:latest \
  -c "pip install --no-cache-dir -r requirements-dev.txt && pytest -q"
```

Confirms the `python:3.12-slim` base image + `requirements.txt` pins pass
the same suite the legacy `.venv` does — catches dependency/version drift
the Dockerfile's base image choice could otherwise introduce silently.

## Legacy: bash-watchdog setup (superseded — kept for reference/rollback)

Everything in this section describes the **original** deploy method: four
bash-supervised processes instead of containers. It's no longer what runs
the site, but the scripts are still here and still work, in case you ever
need to roll back (`bash setup.sh` brings it straight back up — just make
sure the Docker stack's `tunnel` is stopped first, so you don't end up with
two connected replicas splitting traffic against two different data
copies).

Original architecture note (kept as written — describes Cloudflare's
anonymous Quick Tunnel flow this script can also fall back to, not the
named tunnel both setups actually use today):

```
Internet → Cloudflare edge (TLS, random *.trycloudflare.com URL)
         → cloudflared (outbound-only, no router config needed)
         → Caddy :8080  → /api/*  → uvicorn 127.0.0.1:8000 (backend)
                         → /*      → frontend/dist (static files)
```

No Docker, no port forwarding, no router changes. Four lightweight
processes (backend, Caddy, tunnel, backup), each supervised by its own
bash watchdog script (`*-watchdog.sh`) + Task Scheduler entry so they
auto-start at login and restart if they crash. Everything here runs
through Git Bash — no PowerShell.

No Cloudflare account, login, or domain needed for this path — it uses
Cloudflare's anonymous Quick Tunnel. Trade-off: the public URL is random
(`https://something-random.trycloudflare.com`) and **changes every time the
tunnel restarts**. Fine to get live today; see "Upgrade to a named tunnel"
at the bottom if you later want a stable custom domain.

### One-click setup / redeploy

```bash
cd webapp/deploy
bash setup.sh
```

Works on Linux, macOS, and Windows (via Git Bash) — detects the OS and
picks the right package manager (`winget`/`brew`/`apt`/`dnf`/`pacman`) and
binary downloads for each. Installs any missing tools (Python, Node),
creates the venv, builds the frontend, downloads Caddy/cloudflared, checks
Cloudflare tunnel auth, and (re)starts all 4 services — safe to re-run any
time, on this machine or a new one. `bash setup.sh --register` also sets
services to auto-start at login/boot (Task Scheduler / launchd / crontab
depending on OS). Moving to a different machine needs either a copy of
`~/.cloudflared/` from this one, or `bash setup.sh --new-tunnel` to create
a fresh tunnel. Full details in the script's own header comment.

The manual steps below are what that script automates — kept for
reference/troubleshooting.

### One-time setup

(If you've already run these — venv, frontend build, Caddy/cloudflared
downloaded into `bin/` — skip to "Sanity-check".)

```bash
cd /c/Users/manav/Desktop/dungen/webapp/deploy
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
powershell -Command "Expand-Archive -Path caddy.zip -DestinationPath . -Force"  # only Windows-native way to unzip; still no PowerShell scripts of ours involved
rm caddy.zip
curl -L -o cloudflared.exe "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
cd ..
```

### Sanity-check each piece manually

Run one at a time from `webapp/deploy`, Ctrl+C before starting the next:

```bash
bash backend-watchdog.sh    # then in a browser: http://127.0.0.1:8000/api/health
bash caddy-watchdog.sh      # then: http://127.0.0.1:8080  (needs backend running too)
bash tunnel-watchdog.sh     # prints a trycloudflare.com URL — check logs/tunnel.log in another terminal
```

### Register as Task Scheduler entries (auto-start + auto-restart)

`schtasks` is a native Windows command — no PowerShell needed. Each
watchdog script already loops forever internally (restarts the process it
wraps on crash), so Task Scheduler's job is just "start this once at
login":

```bash
DEPLOY_DIR=$(cygpath -w "$(pwd)")
BASH_EXE=$(cygpath -w "$(command -v bash)")
echo "Using bash at: $BASH_EXE"

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

### Checking on it later

```bash
schtasks /query /tn "diagen-backend" /v /fo list
schtasks /query /tn "diagen-caddy"   /v /fo list
schtasks /query /tn "diagen-tunnel"  /v /fo list
schtasks /query /tn "diagen-backup"  /v /fo list

tail -n 40 logs/backend.log
tail -n 40 logs/caddy.log
tail -n 40 logs/tunnel.log
tail -n 40 logs/backup.log

bash check-url.sh   # current public URL
```

### Stopping / removing

`schtasks /end` stops the top-level bash process Task Scheduler started,
but the actual server processes it spawned (uvicorn/caddy/cloudflared)
can outlive that — kill them explicitly too:

```bash
for name in backend caddy tunnel backup; do
  schtasks /end /tn "diagen-$name" 2>/dev/null
done
taskkill //F //IM python.exe //T 2>/dev/null
taskkill //F //IM caddy.exe //T 2>/dev/null
taskkill //F //IM cloudflared.exe //T 2>/dev/null
```

(`//F //IM //T` — double slashes because Git Bash otherwise tries to
path-convert single-slash flags into Windows paths.)

**Known sharp edge, found while cutting over to Docker:** this same
exact-path-match approach, reused inside `setup.sh`'s own
`kill_by_path`/`find_pids_by_path` functions (via `ps -W` + a literal
string match ending in `.exe`), can silently match zero processes — Git
Bash's `ps -W` sometimes lists a process's image name/path **without**
the `.exe` suffix, so a pattern that includes it never matches and the old
process is left running untouched while a redeploy starts a second one
pointed at the same port. Health checks don't tell the two apart, so this
can go unnoticed. If you ever rely on this path again, verify an actual
stop with `tasklist //FI "IMAGENAME eq caddy.exe"` (etc.) rather than
trusting the kill command's silence — or kill by exact PID from
`Get-Process | Select Id,Path` in PowerShell instead.

To remove the scheduled tasks entirely:

```bash
for name in backend caddy tunnel backup; do
  schtasks /delete /tn "diagen-$name" /f
done
```

### Redeploying after a code change

```bash
# backend change:
schtasks /end /tn "diagen-backend" 2>/dev/null
taskkill //F //IM python.exe //T 2>/dev/null
schtasks /run /tn "diagen-backend"

# frontend change:
cd ../frontend
npm run build
cd ../deploy
schtasks /end /tn "diagen-caddy" 2>/dev/null
taskkill //F //IM caddy.exe //T 2>/dev/null
schtasks /run /tn "diagen-caddy"
```

### Upgrade to a named tunnel (stable URL, needs a domain in Cloudflare)

If you later add a domain to a free Cloudflare account:

```bash
./bin/cloudflared.exe tunnel login                      # opens browser, one-time auth
./bin/cloudflared.exe tunnel create diagen
./bin/cloudflared.exe tunnel route dns diagen app.yourdomain.com
```

Then replace `tunnel-watchdog.sh`'s run line with:

```bash
"$CF_EXE" tunnel run --url http://127.0.0.1:8080 diagen >> "$LOG_FILE" 2>&1
```

(or a `config.yml` with an ingress rule — see cloudflared docs). URL
becomes fixed (`https://app.yourdomain.com`), no more checking
`check-url.sh`.

## Notes / known trade-offs

- Single point of failure: your machine's power + internet. No failover.
- Live editing session (undo history, unsaved in-progress edits) is still
  in-memory — a backend restart drops anything not saved. The app
  auto-saves every 2 minutes once a diagram is tied to a saved project
  (Projects tab → Save), on top of manual Save. The `backup` service (or
  `diagen-backup` on the legacy path) then copies `projects.db` (users +
  saved diagrams — the only durable state) every 6h to `backups/`, pruned
  after 14 days. Restore by stopping the backend and copying a backup file
  back over `projects.db` — `data/backups/` on the legacy path, or inside
  the `diagen-data` volume on the Docker path.
- Accounts: real multi-user (signup/login, PBKDF2-hashed passwords, each
  user only sees their own saved projects). No email verification or
  password reset — self-hosted tool, no mail server configured. If someone
  forgets their password, there's no recovery flow; they need a new
  account, or you edit `projects.db`'s `users` table by hand.
- Rate-limited: 300 req/min/IP generally, 20 req/min/IP on
  `/api/auth/*` (signup/login) to slow down password guessing. Uploads
  capped at 15MB, CSV pastes at 5MB, 500 saved projects per user.
- CORS (`app/main.py`) is left wide open (`allow_origins=["*"]`) — harmless
  here because the browser only ever talks to Caddy (same-origin); Caddy
  is what forwards to the backend server-side. Tighten it anyway if this
  ever gets a real domain and you want defense in depth.
- Check your ISP's terms of service — some residential plans restrict
  running always-on servers.
