---
sidebar_position: 2
title: Operator Guide
description: Day-to-day commands for running the home-server deployment — starting, checking, restarting, and restoring it.
---

# Operator Guide

Day-to-day operation of the home-server deployment described in
[Deployment → Home Server](/deployment/home-server). All paths below assume
that layout; adjust them if you're running elsewhere.

## 1. Start everything

Task Scheduler auto-starts all four services (`diagen-backend`,
`diagen-caddy`, `diagen-tunnel`, `diagen-backup`) on login — nothing to do
manually after a reboot. To force-start now without rebooting:

```bash
cd webapp/deploy
for name in backend caddy tunnel backup; do
  schtasks /run /tn "diagen-$name"
  sleep 2
done
```

## 2. Get the public URL

The Quick Tunnel URL **changes every time cloudflared restarts**. Always
fetch the latest:

```bash
cd webapp/deploy
grep -n "trycloudflare.com" logs/tunnel.log | tail -3
```

Use the URL from the most recent `Requesting new quick Tunnel` block — old
URLs stay in the log.

## 3. Health check

Run this after any restart:

```bash
cd webapp/deploy
tasklist | grep -iE "python|caddy|cloudflared"
```

All three must appear. If one's missing, restart just that one (§5) —
never a broad `taskkill` across multiple services at once; it can take down
processes sharing the same console that you didn't intend to touch.

## 4. First-time sign up

Open the public URL in a browser and use the app's own signup screen. There
is no admin bootstrap step. Password reset doesn't exist — losing a
password means a new account or a manual database edit.

## 5. Restart a single service

Restart one service at a time and verify with `tasklist` before touching
the next:

```bash
cd webapp/deploy

# backend only
schtasks /end /tn "diagen-backend" 2>/dev/null
taskkill //F //IM python.exe //T 2>/dev/null
schtasks /run /tn "diagen-backend"
sleep 3
tasklist | grep -i python

# caddy only
schtasks /end /tn "diagen-caddy" 2>/dev/null
taskkill //F //IM caddy.exe //T 2>/dev/null
schtasks /run /tn "diagen-caddy"
sleep 3
tasklist | grep -i caddy

# tunnel only
schtasks /end /tn "diagen-tunnel" 2>/dev/null
taskkill //F //IM cloudflared.exe //T 2>/dev/null
schtasks /run /tn "diagen-tunnel"
sleep 5
tasklist | grep -i cloudflared
```

After any tunnel restart, re-fetch the URL (§2) — it will have changed.

## 6. Redeploy after a code change

```bash
cd webapp/deploy

# backend change
schtasks /end /tn "diagen-backend" 2>/dev/null
taskkill //F //IM python.exe //T 2>/dev/null
schtasks /run /tn "diagen-backend"

# frontend change
cd ../frontend && npm run build && cd ../deploy
schtasks /end /tn "diagen-caddy" 2>/dev/null
taskkill //F //IM caddy.exe //T 2>/dev/null
schtasks /run /tn "diagen-caddy"
```

## 7. Check logs

```bash
cd webapp/deploy
tail -n 40 logs/backend.log
tail -n 40 logs/caddy.log
tail -n 40 logs/tunnel.log
tail -n 40 logs/backup.log
```

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Error 1033 (Cloudflare Tunnel error) | cloudflared not running, or you're using a stale URL | Check §3; if dead, restart per §5; re-fetch URL per §2 |
| Bad Gateway 502 | cloudflared is up, but backend/Caddy is down | Check §3; restart the missing service per §5 |
| `date`/`sleep: command not found` in logs | PATH missing Git's bin directory in the Task Scheduler context | Already patched in all four watchdog scripts — shouldn't recur |
| One restart kills unrelated services too | Shared console signal broadcast | Never batch multiple `taskkill /T` calls together — one at a time, verify between each |

## 9. Stop everything

```bash
cd webapp/deploy
for name in backend caddy tunnel backup; do
  schtasks /end /tn "diagen-$name" 2>/dev/null
done
taskkill //F //IM python.exe //T 2>/dev/null
taskkill //F //IM caddy.exe //T 2>/dev/null
taskkill //F //IM cloudflared.exe //T 2>/dev/null
```

## 10. Backups

Auto-backed up every 6h to `webapp/backend/data/backups/`, pruned after 14
days. To restore: stop the backend (§9, backend only), copy a backup file
over `webapp/backend/data/projects.db`, restart the backend (§5).
