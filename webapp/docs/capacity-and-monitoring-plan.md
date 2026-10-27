# Capacity & Monitoring Plan — Handling a Burst of 100+ Concurrent Users

Status: planning document only. No code changed as part of writing this.
Scope: `webapp/deploy-gcp/` (Cloud Run + Neon) and `webapp/deploy/` (home
Docker Compose + Cloudflare Tunnel + SQLite).

## Executive summary

**Depends — and on the current Cloud Run config specifically, it will
visibly degrade and likely throw errors for a real chunk of 100 simultaneous
users, even though nothing catastrophic (data loss, total outage) should
happen.** The home-tunnel deploy is actually the more forgiving of the two
for a *short* burst, because it has no cold start and no per-request network
hop to a remote database — its limits are the host machine's single CPU
core and SQLite's single-writer lock. Both deploys share the same deepest
structural limit: **all live editing state is a plain in-process Python
dict** (`webapp/backend/app/diagram_store.py`), which is why both are
pinned to one process/one instance. That ceiling does not break at 100
users by itself — one process can *hold* 100 sessions' worth of dicts in
memory fine. What breaks first is **CPU and I/O contention inside that one
process**, not the session store's memory footprint. The single highest-
leverage fix — before touching infrastructure — is that
`app/main.py`'s `auth_middleware` calls `auth.verify_token()`
**synchronously, un-threaded, inside an `async def` middleware**, and
`verify_token` opens a fresh database connection on every single
authenticated request. On Cloud Run that's a fresh TCP+TLS handshake to
Neon, blocking the *entire* event loop, on *every* API call, for every one
of the 100 users — not just the DB-heavy ones. Fixing that one function is
cheap and buys more real headroom than any infra change below it.

100 truly-concurrent, continuously-editing users is **not** compatible with
the current architecture without real pain (see "Out of scope" at the
bottom) — but 100 users arriving as a *burst* (sign up, load a sample,
poke around, leave) is survivable on both targets once the fixes below are
applied, with the home deploy's hardware being the real wildcard.

---

## Cloud Run deploy (`webapp/deploy-gcp/`)

Confirmed from the actual deploy command (`webapp/deploy-gcp/README.md`,
steps 4–5) and `webapp/backend/Dockerfile`:
- `gcloud run deploy` sets only `--min-instances=0 --max-instances=1
  --cpu-boost`. No `--cpu`, `--memory`, or `--concurrency` flag is set, so
  Cloud Run's **current platform defaults apply: 1 vCPU, 512 MiB memory,
  concurrency = 80 requests/instance** (per Cloud Run docs as of this
  writing).
- The container runs `uvicorn ... --workers 1` — one process, one event
  loop.
- Every route handler in `app/routers/*.py` (reposition, node/edge CRUD,
  auto-arrange, undo/redo, CSV apply, PPTX export, bootstrap/upload) is a
  plain **sync `def`**, not `async def`. FastAPI/Starlette runs those
  through anyio's thread-pool offload, whose **default cap is 40 threads,
  shared by the whole process** (confirmed against anyio/Starlette docs).

### Priority-ordered bottlenecks

| # | What breaks | Roughly at what load | Why (actual code path) |
|---|---|---|---|
| 1 | **Entire event loop stalls on every authenticated request** | Starts mattering at double-digit concurrent requests; falls over hard well before 100 | `app/main.py` `auth_middleware` is `async def` but calls `auth_store.verify_token(token)` directly — a **synchronous, blocking call**, not awaited, not offloaded to a thread. `verify_token` → `get_user_by_id` → `with _conn() as conn:` → `db.connect()` → **a brand-new `psycopg2.connect()` TCP+TLS handshake to Neon, per request, every request** (`app/db.py`, `app/auth.py` lines ~104-128, ~173-180). Since this runs on the one and only event-loop thread (not the 40-thread pool), it blocks *all* request processing — including completely unrelated users' requests — for the full round-trip time of that connect+query. 100 users clicking around means a continuous queue of these blocking calls serializing on one thread. |
| 2 | **Neon connection churn / cap pressure** | A sustained burst of 100 concurrent requests | Every request (not just login) opens a fresh Postgres connection via `db.connect()` (`app/db.py`) and closes it at the end of the `with` block — there is no pooling anywhere in the app. Neon's free tier's *direct* connection limit scales with compute size (as low as ~112 at the smallest 0.25 CU autoscale step, up to ~901 at the free tier's max 2 CU — Neon does not publish one fixed number). Neon also offers a **pooled** connection string (PgBouncer, up to 10,000 concurrent) — the README's setup step just says "copy the connection string from the dashboard," so it's unclear whether the pooled or direct string is actually in use today. If it's the direct one, 100 concurrent users each triggering 1-3 requests (load + a few edits) could plausibly spike past the smaller end of that range, especially combined with #1's slow connects holding sockets open longer than they need to. |
| 3 | **CPU-bound layout/render work queues up on 1 vCPU** | Noticeable latency from ~20-30 concurrent edits/exports; real slowdowns near 100 | `layout()` (`diagen/layout.py`), `SvgRenderer` (`diagen/render_svg.py`, 1279 lines), and PPTX assembly (`app/routers/export.py`) are synchronous CPU-bound Python. They run in the 40-thread pool, but all 40 threads share **one vCPU** under the GIL — so this isn't 40-way parallelism, it's 40 threads time-slicing one core. A burst of simultaneous `/api/upload`, `/api/auto-arrange`, or `/api/export/pptx/generate` calls will serialize on CPU and each one's latency balloons; the 41st-and-up simultaneous sync call queues behind the thread-pool limiter entirely. |
| 4 | **Cold start on the only instance** | First request after any idle period | `--min-instances=0` means the single instance can scale to zero. The *first* request after idling pays uvicorn/Python/FastAPI startup (a few seconds, per the README). This can't "break" capacity at 100 users once warm, but a burst arriving right after a quiet period means the first few users eat that cold-start latency (and if Neon's own compute also auto-suspended, it's two stacked cold starts — already documented in the README). |
| 5 | **In-memory session loss if the instance is ever replaced mid-burst** | Rare, but not impossible | `--max-instances=1` guarantees never *two concurrent* instances, but Cloud Run can still **replace** the single instance (new revision rollout, instance recycling, a crash) — at that moment a fresh container starts with an *empty* `DiagramStore` dict (`diagram_store.py`). Anyone with an active undo/redo session or unsaved in-progress edit loses it; this is already called out in the README as an accepted trade-off. Not new risk from 100 users specifically, but a burst makes it more likely *someone* is mid-edit when/if that happens. |
| 6 | **SQLite-shaped assumptions don't apply here** | N/A | Not a real risk on this target — `db.py`'s Postgres path is used, so there's no single-writer-lock concern. Listed only to confirm it was checked. |

### Fixes, cheapest/highest-leverage first

1. **Fix `auth_middleware` to not block the event loop (do this regardless of scale).** Either run `auth_store.verify_token` through `starlette.concurrency.run_in_threadpool`, or — better, since the DB call inside it is the actual cost — cache verified tokens for a few seconds (e.g. an in-memory `{token: (payload, expiry_ts)}` dict with a short TTL, same spirit as the existing rate limiter) so most requests skip the DB round-trip entirely and only re-check `token_version` periodically. This is a few lines, zero new infra, and removes the single biggest source of serialized latency under concurrency on *both* deploy targets.
2. **Use Neon's pooled connection string, not the direct one.** Confirm which one `DATABASE_URL` currently holds; if it's the direct string, switch to Neon's PgBouncer-pooled variant (same `psycopg2.connect(DATABASE_URL)` call in `app/db.py`, zero code change — just the connection string value). This is exactly the kind of "swap a secret's value" fix that fits the $0 philosophy and removes the connection-cap risk from #2 above without adding any new service.
3. **Set `--concurrency` deliberately instead of leaving the 80 default.** Since this process can only usefully run ~40 sync handlers at once (thread-pool cap) on 1 vCPU, letting Cloud Run route 80 simultaneous requests to it just means the back half queue inside the container instead of at Cloud Run's layer, with worse visibility. Setting `--concurrency=40` doesn't add capacity, but it makes Cloud Run's own queuing/latency metrics reflect reality, and the Cloud Run side will 429/queue cleanly rather than the process starving internally.
4. **Raise the anyio thread-pool limiter from 40 if CPU-bound endpoints are the observed bottleneck (not the DB one).** One line at startup (`anyio.to_thread.current_default_thread_limiter().total_tokens = <N>`), after fix #1 is in — no point raising the thread cap while the real stall is on the un-threaded DB call. Keep it modest (e.g. 60-80, matching concurrency); more threads on one vCPU has diminishing/negative returns per anyio's own docs.
5. **If a burst is expected (e.g. a demo, a launch), temporarily set `--min-instances=1` for that window.** This is the one line in the README's own "What's NOT handled here" section (~$12-15/mo) — it removes cold start entirely but costs money continuously, so it's a deliberate, temporary opt-in, not a default change.

**What is explicitly NOT proposed here:** multi-instance Cloud Run,
Redis-backed session state, or Cloud SQL. At 100 users doing normal
edit-session traffic (not 100 users all mashing auto-arrange in the same
second), fixes 1-3 above remove the real bottlenecks without touching the
single-instance architecture. Horizontal scaling only becomes *necessary*
if sustained concurrency regularly exceeds ~40 simultaneous CPU-bound
requests — that's a real number to watch for (see monitoring plan), not an
assumption to build against today.

---

## Home deploy (`webapp/deploy/`, Docker Compose + Cloudflare Tunnel + SQLite)

Confirmed from `webapp/deploy/docker-compose.yml`, `backend.Dockerfile`,
and the watchdog scripts:
- Same `uvicorn ... --workers 1`, same sync-`def`-handlers-in-a-thread-pool
  shape as Cloud Run — but now backed by **SQLite**, not Postgres.
- `app/db.py`'s `connect()` calls plain `sqlite3.connect(SQLITE_DB_PATH)`
  with **no `journal_mode=WAL` pragma, no explicit busy-timeout** anywhere
  in `db.py`/`auth.py`/`projects.py` — so it's on SQLite's default rollback-
  journal mode (a writer holds an exclusive lock on the whole file for the
  duration of its transaction, blocking all concurrent readers/writers)
  and Python's `sqlite3` default 5-second busy-timeout before raising
  `OperationalError: database is locked`.
- No CPU/memory limits are set on the `backend`/`caddy` containers in
  `docker-compose.yml` — they can use the whole host, which is good (no
  artificial ceiling) but also means capacity is **however powerful the
  actual home machine is**, which this plan can't quantify without
  knowing the hardware.
- Traffic reaches the box through a single `cloudflared` connector process
  tunneling to Caddy, which proxies to the backend over the compose
  network — all single-hop, no extra queuing layer of its own at these
  volumes.

### Priority-ordered bottlenecks

| # | What breaks | Roughly at what load | Why |
|---|---|---|---|
| 1 | **Same event-loop-blocking auth check as Cloud Run (fix #1 above applies here too)** | Same shape, less severe in absolute latency | `verify_token`'s DB call is now a local `sqlite3.connect()` — fast (no network/TLS), but still synchronous inside the `async def` middleware, so it still serializes all request handling through one thread while each query runs. Much cheaper per-call than Neon's network round trip, so this alone probably won't *break* the home deploy at 100 users, but it's still real, avoidable serialization and the fix is identical. |
| 2 | **SQLite "database is locked" errors under write bursts** | Many simultaneous *writes* (saves, signups, logouts bumping `token_version`) landing inside the same ~second | No WAL mode means a writer transaction (`INSERT`/`UPDATE` in `create_user`, `save_project`, `bump_token_version`) takes an exclusive file lock for its duration; a concurrent writer waits up to the 5s default timeout, then raises an uncaught `sqlite3.OperationalError`, which the route handler doesn't catch anywhere reviewed — it would surface as an unhandled 500. 100 users arriving together plausibly means several near-simultaneous signups/saves; this is a real, user-visible failure mode that the Cloud Run/Postgres path doesn't share. |
| 3 | **Single CPU core contention for layout/render/export** | Same mechanism as Cloud Run's #3, but now bounded by whatever the actual home box's core count is, not a fixed 1 vCPU — could be meaningfully better *or* worse depending on hardware | Same sync-`def`-in-threadpool code path. If the home box has more cores, it genuinely has more real parallelism than Cloud Run's 1 vCPU default — this is one place the home deploy could outperform Cloud Run at 100 users, hardware permitting. |
| 4 | **Residential upload bandwidth through the Cloudflare Tunnel** | Unknown without knowing the link's actual upload speed; flagging as a real unknown, not a guess | Every diagram re-render, SVG payload, and PPTX download egresses through the home connection's upload bandwidth via `cloudflared`. 100 simultaneous users pulling diagram JSON/SVG responses could saturate a modest residential upload link well before CPU or SQLite become the limiter — this is genuinely unknown without the actual connection's specs, so it's flagged rather than estimated. |
| 5 | **Unbounded log growth, not a crash risk but a disk-usage one** | Slow, cumulative | Every watchdog script (`backend-watchdog.sh`, `caddy-watchdog.sh`, `tunnel-watchdog.sh`, `backup-watchdog.sh`) appends to its own `logs/*.log` file forever with **no rotation or truncation anywhere** in `webapp/deploy/`. Not a 100-concurrent-user failure mode by itself, but a sustained burst (more traffic = more log lines) accelerates disk fill on a box that also stores the SQLite DB + backups on the same `diagen-data` volume. |

### Fixes, cheapest/highest-leverage first

1. **Apply the same auth-check fix as Cloud Run (#1 above).** Same code, same fix, both targets benefit — do it once.
2. **Turn on SQLite WAL mode and set an explicit busy_timeout.** One pragma pair, no new dependency, no architecture change: `conn.execute("PRAGMA journal_mode=WAL")` and `sqlite3.connect(path, timeout=15)` (or similar) in `app/db.py`'s `connect()`. WAL lets readers proceed concurrently with a writer (only writer-vs-writer still serializes), and a longer busy-timeout turns most lock contention into "briefly slower" instead of "500 error." This is the single highest-leverage fix specific to the home deploy — it directly addresses bottleneck #2, the one failure mode Cloud Run's Postgres path doesn't share.
3. **Catch `sqlite3.OperationalError` (locked) at the route layer and retry once or return a clean 503** instead of letting it surface as an unhandled 500 — cheap defensive coding on top of fix #2, not a replacement for it.
4. **Add basic log rotation** (`logrotate` on the host, or swap each watchdog's `>> "$LOG_FILE"` for a size-capped append, e.g. via `rotatelogs` or a simple size-check-and-truncate in the script) so sustained higher traffic doesn't silently grow disk usage unbounded. Cheap, no architecture change.
5. **Measure actual upload bandwidth under a synthetic 100-concurrent-request test before assuming it's fine.** Not a code fix — a one-time check (e.g. a quick load test against the public tunnel URL) to turn bottleneck #4 from an unknown into either "fine" or "the real limiter," before spending effort anywhere else on this target.

**What is explicitly NOT proposed here:** moving off SQLite to Postgres for
the home deploy, or adding Redis. WAL mode plus a sane busy-timeout solves
the actual failure mode (lock contention under bursty writes) that 100
concurrent users would realistically trigger; a full database swap is not
justified by anything found in this review.

---

## Monitoring plan

Scoped to what a solo/small project can realistically keep running:
free-tier-first, reach for Cloud Run's and Neon's own built-in
dashboards before adding any new service, and keep the home deploy's
monitoring to "something pings it from outside and tells me if it's down,"
since **nothing watches it from outside today** — the only existing health
signal is `/api/health` (`app/routers/bootstrap.py`) and the Docker
Compose healthcheck that already hits it internally (`docker-compose.yml`
lines ~32-37), neither of which alerts anyone.

### What to monitor, and with what, per target

**Cloud Run (backend + frontend services):**
- **Error rate (5xx) and request latency (p50/p95/p99)** — built into the
  Cloud Run console's own per-service metrics tab, zero setup, already
  collected today; the only gap is nobody's looking at it. Set a **Cloud
  Monitoring alerting policy** (free tier covers this at this volume) on
  5xx rate and on p95 latency, delivered to email — this is the cheapest
  possible "tell me when it's actually broken" and uses only GCP-native
  tooling already paid for (as in, free) by this deploy.
- **Concurrent/active instance count and cold starts** — also native to
  the Cloud Run console (instance count graph); confirms whether
  `--max-instances=1` is ever actually being hit/queued against, which is
  the real signal for "do we need more than one instance yet."
- **Request count** as a rough proxy for "is a burst happening right
  now" — same console, same zero-setup metric.
- **Structured logging**: today there is no structured logging anywhere
  in the backend (confirmed — no `logging`/`structlog`/Sentry usage in
  `app/`). Cloud Run already captures stdout/stderr into **Cloud Logging**
  for free at this volume with zero code change; the only real gap is the
  app prints nothing useful (`print(...)` only appears in `main.py`'s user
  seeding). Lowest-effort improvement: add a few `print()`/stdlib
  `logging` lines at the points this plan identifies as risky (the auth
  DB-call path, SQLite lock errors, layout/render exceptions) so Cloud
  Logging actually has something to alert on beyond raw HTTP status.
- **Error tracking**: not proposing Sentry or any paid error tracker at
  this scale — Cloud Logging + a log-based alert on `severity>=ERROR` (or
  on the stderr tracebacks FastAPI already prints for unhandled
  exceptions) covers "tell me when something threw" without a new
  service or bill.

**Neon (Postgres):**
- **Connection count and compute usage** — Neon's own dashboard already
  shows active connections and compute-hours against the free tier's
  limits; check it manually after any real burst, or (if available on the
  free tier) use Neon's own usage-alert emails rather than building
  anything custom.
- This is also where to verify, concretely, **whether the pooled or
  direct connection string is in use** (fix #2 above) — the dashboard
  shows which endpoint is being hit.

**Home deploy (Docker Compose + Cloudflare Tunnel):**
- **Uptime, from outside the home network** — nothing does this today.
  Add a **free external uptime pinger** (UptimeRobot or healthchecks.io,
  both have a no-cost tier sufficient for one URL at a few-minute
  interval) hitting the public tunnel URL's `/api/health`. This is the
  single most valuable addition for this target, because it's the only
  deploy with no platform-level health monitoring underneath it at all —
  Cloud Run has Google watching the box; the home deploy has nothing
  unless this is added.
- **Container health** — already exists (`docker-compose.yml`
  healthchecks on `backend` and `caddy`) and already drives
  `restart: unless-stopped`; no change needed, just worth noting it's
  there and working as designed.
- **Disk usage** (SQLite DB + `backups/` + the never-rotated `logs/*.log`
  files, all on the same `diagen-data` volume) — add a simple `df`/`du`
  check to an existing watchdog loop (or a cron job) that writes a
  warning line to its log past some threshold (e.g. 80% full); this is a
  few lines of shell, no new tool, and directly covers the one disk-fill
  risk this review found with no monitoring today.
- **Backup freshness** — `backup-watchdog.sh`/the compose `backup`
  service already log success/failure per run; point the same free
  uptime-pinger service's "dead man's switch" feature (healthchecks.io
  supports this specifically; UptimeRobot does not) at a ping the backup
  job makes on success, so a silently-stopped backup loop gets noticed
  instead of discovered at restore time.
- **CPU core count and current load** — worth literally just finding out
  what hardware this runs on (`nproc`, `free -h`) once, since several
  bottlenecks above (#3, #4) are bounded by unknowns specific to this one
  machine that no amount of code-reading can determine.

### What this monitoring plan deliberately leaves out

No Prometheus/Grafana stack, no Datadog/New Relic, no paid error tracker,
no APM agent. At this project's actual traffic (personal/low, occasional
bursts, one maintainer) the free, built-in tooling each platform already
offers (Cloud Run console + Cloud Logging, Neon's dashboard, one free
external uptime pinger) covers every signal listed in the task brief
(error rate, latency, Neon connections, cold starts, home-deploy uptime,
disk usage) without adding a bill or an operational burden a solo project
would realistically keep up with. In-memory session *count* specifically
isn't exposed anywhere today (`DiagramStore` has no introspection
endpoint) — if that number specifically becomes interesting, the cheapest
way to get it is a tiny addition to the existing `/api/health` response
(e.g. `len(store._sessions)`), not a new monitoring system.

---

## Out of scope / needs a real architecture change

Being direct about the one thing this plan does **not** paper over: if
"100 concurrent users" means **100 people simultaneously, continuously
editing distinct diagrams for an extended session** (not a short burst of
signups/loads/pokes), the current design has a real ceiling that the fixes
above do not remove:

- **In-memory session state (`diagram_store.py`) is the hard architectural
  limit on ever running more than one backend instance or worker**, which
  in turn caps total CPU available to the single process at whatever one
  Cloud Run instance's vCPU allocation (or the home box's core count) is.
  No amount of connection-pooling or middleware fixes changes that — the
  only real fix is moving session state out of the process (Redis, or
  Postgres/SQLite itself with a session table) so multiple workers/
  instances can share it. That is a genuine architecture change, not a
  tuning pass, and this plan is not proposing it now because nothing found
  in this review shows it's *necessary* at 100 users specifically — the
  actual first failures are the event-loop-blocking auth check and
  connection/lock contention above, both fixable without it. If sustained
  (not bursty) 100-way concurrent editing becomes the real target, revisit
  this specific point first.
- **The rate limiter (`app/ratelimit.py`) and the auth-token-cache fix
  proposed above are both explicitly single-process, in-memory designs**
  (said outright in the module's own docstring) — fine as long as the
  single-instance constraint above holds, and would need to move to a
  shared store (Redis, or the DB) the moment that constraint is ever
  relaxed. Not a problem today; flagged so it isn't forgotten if/when
  `max-instances=1` is ever revisited.
- **No load test has actually been run** against either deploy as part of
  this plan — every number above (thread-pool cap, Cloud Run defaults,
  Neon's connection ceiling) is a documented platform limit, traced
  against this app's real code paths, not a measurement of this app under
  real synthetic load. Before trusting this plan's priority order under a
  real event, a cheap synthetic burst test (e.g. `locust`/`hey` against a
  staging copy) would confirm which bottleneck actually hits first in
  practice.
