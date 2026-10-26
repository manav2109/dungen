# Deploying diagen from this machine

Architecture:

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

Backend runs as **one uvicorn worker** — required. Sessions live in an
in-memory dict (`app/diagram_store.py`); multiple workers would each get
their own copy and requests would randomly 404 on the wrong worker.

The app requires a login (multi-user accounts — see
`docs/PRD-user-ready.md`). Nobody can use it, including you, until someone
signs up through the app's own signup screen once it's live — there's no
separate admin bootstrap step, the first signup is just a normal account.

No Cloudflare account, login, or domain needed for this path — it uses
Cloudflare's anonymous Quick Tunnel. Trade-off: the public URL is random
(`https://something-random.trycloudflare.com`) and **changes every time the
tunnel restarts**. Fine to get live today; see "Upgrade to a named tunnel"
at the bottom if you later want a stable custom domain.

## One-click setup / redeploy

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

## One-time setup

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

## Sanity-check each piece manually

Run one at a time from `webapp/deploy`, Ctrl+C before starting the next:

```bash
bash backend-watchdog.sh    # then in a browser: http://127.0.0.1:8000/api/health
bash caddy-watchdog.sh      # then: http://127.0.0.1:8080  (needs backend running too)
bash tunnel-watchdog.sh     # prints a trycloudflare.com URL — check logs/tunnel.log in another terminal
```

## Register as Task Scheduler entries (auto-start + auto-restart)

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

## Checking on it later

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

## Stopping / removing

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

To remove the scheduled tasks entirely:

```bash
for name in backend caddy tunnel backup; do
  schtasks /delete /tn "diagen-$name" /f
done
```

## Redeploying after a code change

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

## Upgrade to a named tunnel (stable URL, needs a domain in Cloudflare)

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
  (Projects tab → Save), on top of manual Save. `diagen-backup` then copies
  `webapp/backend/data/projects.db` (users + saved diagrams — the only
  durable state) every 6h to `data/backups/`, pruned after 14 days. Restore
  by stopping `diagen-backend` and copying a backup file back over
  `data/projects.db`.
- Accounts: real multi-user (signup/login, PBKDF2-hashed passwords, each
  user only sees their own saved projects). No email verification or
  password reset — self-hosted tool, no mail server configured. If someone
  forgets their password, there's no recovery flow; they need a new
  account, or you edit `data/projects.db`'s `users` table by hand.
- Rate-limited: 300 req/min/IP generally, 20 req/min/IP on
  `/api/auth/*` (signup/login) to slow down password guessing. Uploads
  capped at 15MB, CSV pastes at 5MB, 500 saved projects per user.
- CORS (`app/main.py`) is left wide open (`allow_origins=["*"]`) — harmless
  here because the browser only ever talks to Caddy (same-origin); Caddy
  is what forwards to the backend server-side. Tighten it anyway if this
  ever gets a real domain and you want defense in depth.
- Check your ISP's terms of service — some residential plans restrict
  running always-on servers.
