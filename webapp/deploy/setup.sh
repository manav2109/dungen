#!/usr/bin/env bash
# One-click setup + redeploy for diagen. Works on Linux, macOS, and Windows
# (via Git Bash) - picks the right package manager and binary downloads for
# whichever machine it's run on.
#
# Usage, from webapp/deploy:
#   bash setup.sh
#
# Safe to re-run any time, on the same machine or a new one: every step
# skips work that's already done, and only rebuilds/restarts what's needed.
# Use it both for first-time setup on a fresh machine AND for redeploying
# after a code change on a machine already running it.
#
# Flags:
#   --register     also register the 4 services to auto-start at login/boot
#                   and auto-restart on crash (Task Scheduler on Windows,
#                   launchd on macOS, crontab @reboot on Linux). Only the
#                   Windows path has been exercised live - macOS/Linux use
#                   standard, well-documented patterns but check the first
#                   run. Without this flag, services run now but won't
#                   survive a reboot/logout.
#   --new-tunnel   create a brand-new named Cloudflare tunnel instead of
#                   expecting credentials copied from the original machine
#                   (prompts before touching DNS - see "Moving to a new
#                   machine" below).
#
# Moving to a new machine:
#   The Cloudflare tunnel "diagen" already exists in your Cloudflare
#   account, but the private credentials file that lets a machine RUN it
#   was only ever written to the machine that created it. To move:
#     1. Copy ~/.cloudflared/ (cert.pem + the tunnel's .json file) from
#        the old machine to the new one, OR
#     2. Run this script with --new-tunnel to create a fresh tunnel and
#        repoint DNS at it instead.
set -u

REGISTER=0
NEW_TUNNEL=0
for arg in "$@"; do
  case "$arg" in
    --register) REGISTER=1 ;;
    --new-tunnel) NEW_TUNNEL=1 ;;
    *) echo "Unknown flag: $arg" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

section() { printf "\n\033[1;36m== %s ==\033[0m\n" "$1"; }
warn()    { printf "\033[1;33m%s\033[0m\n" "$1"; }
err()     { printf "\033[1;31m%s\033[0m\n" "$1"; }
ok()      { printf "\033[1;32m%s\033[0m\n" "$1"; }

# ---------------------------------------------------------------------------
# OS / arch detection

case "$(uname -s)" in
  Darwin) PLATFORM="macos" ;;
  Linux) PLATFORM="linux" ;;
  MINGW*|MSYS*|CYGWIN*) PLATFORM="windows" ;;
  *) err "Unrecognized OS: $(uname -s)"; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64|amd64) ARCH="amd64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *) err "Unrecognized architecture: $(uname -m)"; exit 1 ;;
esac

if [ "$PLATFORM" = "windows" ]; then
  EXE_EXT=".exe"
else
  EXE_EXT=""
fi

BIN_DIR="$SCRIPT_DIR/bin"
CADDY_EXE="$BIN_DIR/caddy${EXE_EXT}"
CF_EXE="$BIN_DIR/cloudflared${EXE_EXT}"

# ---------------------------------------------------------------------------
section "Checking tools"

have() { command -v "$1" >/dev/null 2>&1; }

PY=""
if have python3; then PY="python3"; elif have python; then PY="python"; fi
NEED_PY=0; have_node=0
[ -z "$PY" ] && NEED_PY=1
have node && have_node=1

if [ "$NEED_PY" -eq 1 ] || [ "$have_node" -eq 0 ]; then
  case "$PLATFORM" in
    macos)
      if ! have brew; then
        err "Homebrew not found. Install it from https://brew.sh, then re-run this script."
        exit 1
      fi
      [ "$NEED_PY" -eq 1 ] && { echo "Installing Python via brew..."; brew install python; }
      [ "$have_node" -eq 0 ] && { echo "Installing Node via brew..."; brew install node; }
      ;;
    linux)
      if have apt-get; then
        SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
        echo "Installing via apt-get (may prompt for your password)..."
        $SUDO apt-get update
        $SUDO apt-get install -y python3 python3-venv python3-pip nodejs npm
      elif have dnf; then
        SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
        $SUDO dnf install -y python3 python3-pip nodejs npm
      elif have pacman; then
        SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
        $SUDO pacman -Sy --noconfirm python nodejs npm
      else
        err "Unrecognized Linux package manager. Install python3 + node/npm manually, then re-run."
        exit 1
      fi
      ;;
    windows)
      if ! have winget.exe; then
        err "winget not found. Install 'App Installer' from the Microsoft Store, then re-run this script."
        exit 1
      fi
      [ "$NEED_PY" -eq 1 ] && winget.exe install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
      [ "$have_node" -eq 0 ] && winget.exe install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
      warn "If the next step can't find python/node, close and reopen this terminal, then re-run this script."
      ;;
  esac
  have python3 && PY="python3" || { have python && PY="python"; }
fi

if [ -z "$PY" ] || ! have node; then
  err "Python and/or Node still not on PATH. Open a new terminal and re-run this script."
  exit 1
fi
ok "Python: OK ($PY)"
ok "Node: OK ($(node --version))"

# ---------------------------------------------------------------------------
section "Backend (venv + dependencies)"

BACKEND_DIR="$SCRIPT_DIR/../backend"
if [ "$PLATFORM" = "windows" ]; then
  VENV_PY="$BACKEND_DIR/.venv/Scripts/python.exe"
else
  VENV_PY="$BACKEND_DIR/.venv/bin/python"
fi

if [ ! -f "$VENV_PY" ]; then
  echo "Creating venv..."
  "$PY" -m venv "$BACKEND_DIR/.venv"
fi
echo "Installing backend requirements..."
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r "$BACKEND_DIR/requirements.txt"

# ---------------------------------------------------------------------------
section "Frontend (npm install + build)"

FRONTEND_DIR="$SCRIPT_DIR/../frontend"
(
  cd "$FRONTEND_DIR"
  [ ! -d node_modules ] && { echo "Running npm install..."; npm install; }
  echo "Building frontend..."
  npm run build
)

# ---------------------------------------------------------------------------
section "Caddy + cloudflared binaries"

mkdir -p "$BIN_DIR"

if [ ! -f "$CADDY_EXE" ]; then
  echo "Downloading Caddy..."
  release_json=$(curl -fsSL "https://api.github.com/repos/caddyserver/caddy/releases/latest")
  case "$PLATFORM" in
    windows) pattern="windows_amd64\.zip" ;;
    macos)   pattern="(mac|darwin)_${ARCH}\.tar\.gz" ;;
    linux)   pattern="linux_${ARCH}\.tar\.gz" ;;
  esac
  asset_url=$(echo "$release_json" | grep -oE "\"browser_download_url\": *\"[^\"]*${pattern}\"" | head -1 | sed -E 's/.*"(https:[^"]+)"/\1/')
  if [ -z "$asset_url" ]; then
    err "Couldn't find a Caddy release asset matching $PLATFORM/$ARCH. Download it manually into $BIN_DIR."
    exit 1
  fi
  tmp="$BIN_DIR/caddy_dl"
  if [ "$PLATFORM" = "windows" ]; then
    curl -fsSL -o "$tmp.zip" "$asset_url"
    if have unzip; then
      unzip -o -q "$tmp.zip" -d "$BIN_DIR"
    else
      powershell.exe -NoProfile -Command "Expand-Archive -Path '$(cygpath -w "$tmp.zip" 2>/dev/null || echo "$tmp.zip")' -DestinationPath '$(cygpath -w "$BIN_DIR" 2>/dev/null || echo "$BIN_DIR")' -Force"
    fi
    rm -f "$tmp.zip"
  else
    curl -fsSL -o "$tmp.tar.gz" "$asset_url"
    tar -xzf "$tmp.tar.gz" -C "$BIN_DIR"
    rm -f "$tmp.tar.gz"
    chmod +x "$CADDY_EXE" 2>/dev/null || true
  fi
else
  ok "Caddy: OK"
fi

if [ ! -f "$CF_EXE" ]; then
  echo "Downloading cloudflared..."
  release_json=$(curl -fsSL "https://api.github.com/repos/cloudflare/cloudflared/releases/latest")
  case "$PLATFORM" in
    windows) pattern="cloudflared-windows-amd64\.exe" ;;
    macos)   pattern="cloudflared-darwin-${ARCH}\.tgz" ;;
    linux)   pattern="cloudflared-linux-${ARCH}\$" ;;
  esac
  asset_url=$(echo "$release_json" | grep -oE "\"browser_download_url\": *\"[^\"]*${pattern}[^\"]*\"" | head -1 | sed -E 's/.*"(https:[^"]+)"/\1/')
  if [ -z "$asset_url" ]; then
    err "Couldn't find a cloudflared release asset matching $PLATFORM/$ARCH. Download it manually into $BIN_DIR as cloudflared${EXE_EXT}."
    exit 1
  fi
  case "$asset_url" in
    *.tgz|*.tar.gz)
      tmp="$BIN_DIR/cloudflared_dl.tgz"
      curl -fsSL -o "$tmp" "$asset_url"
      tar -xzf "$tmp" -C "$BIN_DIR"
      rm -f "$tmp"
      ;;
    *)
      curl -fsSL -o "$CF_EXE" "$asset_url"
      ;;
  esac
  chmod +x "$CF_EXE" 2>/dev/null || true
else
  ok "cloudflared: OK"
fi

# ---------------------------------------------------------------------------
section "Cloudflare Tunnel auth"

CERT_PATH="$HOME/.cloudflared/cert.pem"

if [ ! -f "$CERT_PATH" ]; then
  echo "No Cloudflare login found on this machine."
  echo "Opening a browser to authorize - pick the dev-ai.site zone when prompted."
  "$CF_EXE" tunnel login
fi

creds_file=$(ls "$HOME"/.cloudflared/*.json 2>/dev/null | head -1 || true)

if [ -z "$creds_file" ]; then
  if [ "$NEW_TUNNEL" -eq 1 ]; then
    echo "Creating a new tunnel 'diagen' on this machine..."
    "$CF_EXE" tunnel create diagen
    warn "About to add DNS records for dev-ai.site and drawgen.dev-ai.site pointing at this tunnel."
    read -r -p "Type 'yes' to continue: " confirm
    if [ "$confirm" = "yes" ]; then
      "$CF_EXE" tunnel route dns diagen dev-ai.site
      "$CF_EXE" tunnel route dns diagen drawgen.dev-ai.site
    else
      warn "Skipped DNS routing - the tunnel exists but nothing points to it yet. Run the two 'tunnel route dns' commands above manually when ready."
    fi
  else
    err "No tunnel credentials file found in ~/.cloudflared/."
    err "The 'diagen' tunnel already exists in your Cloudflare account, but its"
    err "private credentials file only lives on the machine that created it."
    echo ""
    warn "Fix: copy the .json file from the original machine's ~/.cloudflared/ folder"
    warn "into this machine's same folder, then re-run this script."
    warn "(Or re-run with --new-tunnel to create a fresh tunnel instead.)"
    exit 1
  fi
else
  ok "Tunnel credentials: OK ($(basename "$creds_file"))"
fi

# ---------------------------------------------------------------------------
section "Starting services"

# Not relying on pgrep/pkill - some environments (notably vanilla Git Bash
# on Windows) have neither, and even where a `ps` exists its command-line
# column may show only the binary's own path with no arguments, so
# argument-based matching (e.g. "uvicorn app.main:app") silently never
# matches there. Two different, more portable mechanisms instead:
#   - wrapper idempotency (is a watchdog already supervising this service)
#     via a pidfile + `kill -0`, which only needs $! and kill - both are
#     plain shell builtins, available everywhere.
#   - inner-process restart (so a redeploy actually picks up new code)
#     via `ps` + matching each process's own unique absolute binary path,
#     which shows correctly even where arguments don't.

mkdir -p "$SCRIPT_DIR/logs"

find_pids_by_path() {
  if [ "$PLATFORM" = "windows" ]; then
    ps -W 2>/dev/null | grep -F -- "$1" | awk '{print $1}'
  else
    ps -eo pid=,args= 2>/dev/null | grep -F -- "$1" | grep -v grep | awk '{print $1}'
  fi
}

kill_by_path() {
  for p in $(find_pids_by_path "$1"); do
    kill -9 "$p" 2>/dev/null || true
  done
}

ensure_watchdog() {
  name="$1"
  pidfile="$SCRIPT_DIR/logs/${name}-watchdog.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile" 2>/dev/null)" 2>/dev/null; then
    echo "$name watchdog already running (pid $(cat "$pidfile"))"
  else
    echo "Starting $name watchdog..."
    nohup bash "$SCRIPT_DIR/${name}-watchdog.sh" >/dev/null 2>&1 &
    echo $! > "$pidfile"
    disown 2>/dev/null || true
  fi
}

echo "Restarting backend/caddy/tunnel processes (existing watchdogs will relaunch them fresh)..."
kill_by_path "$VENV_PY"
kill_by_path "$CADDY_EXE"
kill_by_path "$CF_EXE"
sleep 2

for svc in backend caddy tunnel backup; do
  ensure_watchdog "$svc"
  sleep 2
done

if [ "$REGISTER" -eq 1 ]; then
  section "Registering auto-start on login/boot"
  case "$PLATFORM" in
    windows)
      for svc in backend caddy tunnel backup; do
        winpath=$(cygpath -w "$SCRIPT_DIR/${svc}-watchdog.sh")
        bashwin=$(cygpath -w "$(command -v bash)")
        schtasks /create /tn "diagen-$svc" /tr "\"$bashwin\" \"$winpath\"" /sc onlogon /rl limited /f
      done
      ok "Registered via Task Scheduler."
      ;;
    macos)
      mkdir -p "$HOME/Library/LaunchAgents"
      for svc in backend caddy tunnel backup; do
        plist="$HOME/Library/LaunchAgents/site.dev-ai.diagen.$svc.plist"
        cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>site.dev-ai.diagen.$svc</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$SCRIPT_DIR/${svc}-watchdog.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
PLIST
        launchctl unload "$plist" 2>/dev/null || true
        launchctl load "$plist"
      done
      ok "Registered via launchd."
      ;;
    linux)
      tmp_cron=$(mktemp)
      crontab -l 2>/dev/null | grep -v "# diagen-autostart" > "$tmp_cron" || true
      for svc in backend caddy tunnel backup; do
        echo "@reboot bash $SCRIPT_DIR/${svc}-watchdog.sh # diagen-autostart-$svc" >> "$tmp_cron"
      done
      crontab "$tmp_cron"
      rm -f "$tmp_cron"
      ok "Registered via crontab @reboot."
      ;;
  esac
fi

# ---------------------------------------------------------------------------
section "Health check"

sleep 5
if curl -fsS -m 5 "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
  ok "Backend: OK"
else
  warn "Backend did not respond yet - check logs/backend.log"
fi

if curl -fsS -m 5 "http://127.0.0.1:8080/" >/dev/null 2>&1; then
  ok "Caddy: OK"
else
  warn "Caddy did not respond yet - check logs/caddy.log"
fi

echo ""
echo "Done. Public URLs (tunnel takes ~5-10s to connect):"
echo "  https://dev-ai.site"
echo "  https://drawgen.dev-ai.site"
