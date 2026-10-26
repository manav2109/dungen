#!/usr/bin/env bash
# Runs the named Cloudflare Tunnel "diagen" (bound to dev-ai.site via
# `cloudflared tunnel route dns diagen dev-ai.site`) and restarts it if it
# ever exits.
#
# Public URL is fixed: https://dev-ai.site
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/tunnel.log"
mkdir -p "$LOG_DIR"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    export PATH="/usr/bin:/mingw64/bin:/c/Windows/System32:$PATH"
    CF_EXE="$SCRIPT_DIR/bin/cloudflared.exe"
    ;;
  *)
    CF_EXE="$SCRIPT_DIR/bin/cloudflared"
    ;;
esac

if [ ! -f "$CF_EXE" ]; then
  echo "[watchdog] $(date) - cloudflared not found at $CF_EXE. Run setup.sh first." >> "$LOG_FILE"
  exit 1
fi

cd "$SCRIPT_DIR" || exit 1

while true; do
  "$CF_EXE" tunnel --no-autoupdate run --url http://127.0.0.1:8080 diagen >> "$LOG_FILE" 2>&1
  {
    echo ""
    echo "[watchdog] $(date) - tunnel exited, restarting in 3s"
  } >> "$LOG_FILE"
  sleep 3
done
