#!/usr/bin/env bash
# Periodically copies webapp/backend/data/projects.db (users + saved
# diagrams) to a timestamped backup, prunes anything older than
# RETAIN_DAYS. Runs forever, sleeping between backups.
set -u
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) export PATH="/usr/bin:/mingw64/bin:/c/Windows/System32:$PATH" ;;
esac
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="$SCRIPT_DIR/../backend/data/projects.db"
BACKUP_DIR="$SCRIPT_DIR/../backend/data/backups"
INTERVAL_SEC=$((6 * 60 * 60))   # every 6 hours
RETAIN_DAYS=14
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/backup.log"
mkdir -p "$LOG_DIR" "$BACKUP_DIR"

while true; do
  if [ -f "$DB_PATH" ]; then
    STAMP=$(date +%Y-%m-%d_%H%M%S)
    DEST="$BACKUP_DIR/projects_$STAMP.db"
    if cp "$DB_PATH" "$DEST"; then
      echo "$(date) - backed up to $DEST" >> "$LOG_FILE"
    else
      echo "$(date) - backup FAILED" >> "$LOG_FILE"
    fi
    find "$BACKUP_DIR" -name "projects_*.db" -mtime "+$RETAIN_DAYS" -print -delete >> "$LOG_FILE" 2>&1
  else
    echo "$(date) - no projects.db yet, nothing to back up" >> "$LOG_FILE"
  fi
  sleep "$INTERVAL_SEC"
done
