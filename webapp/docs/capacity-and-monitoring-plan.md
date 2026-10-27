# Capacity & Monitoring Plan — Handling a Burst of 100+ Concurrent Users

Status: planning document only. No code changed as part of writing this.
Scope: `webapp/deploy/` (home server — Docker Compose + Cloudflare Tunnel +
SQLite). This is the only deploy target — Cloud Run support was removed
from the repo and is out of scope for this plan.

## Executive summary

**Survivable, with two concrete fixes.** The home deploy has no cold start
and no per-request network hop to a remote database — a burst (signups,
loads, pokes) lands directly on the host's CPU and SQLite, with no
platform-level queuing or auto-scaling underneath it either way. Nothing
catastrophic (data loss, total outage) should happen at 100 users. What
actually breaks first, in order:

1. **SQLite "database is locked" errors under concurrent writes.**
   `app/db.py`'s SQLite connections run in the default rollback-journal
   mode — no WAL, no explicit busy-timeout beyond Python's 5-second
   default. 100 users arriving together plausibly means several
   near-simultaneous signups/saves; a writer transaction holds an
   exclusive lock on the whole file for its duration, and a concurrent
   writer that waits past 5s raises an uncaught
   `sqlite3.OperationalError`, which surfaces as an unhandled 500. This is
   the single highest-leverage fix for this deploy — one pragma pair, no
   architecture change.
2. **`auth_middleware` blocks the event loop on every authenticated
   request** (`app/main.py`) — it's `async def` but calls
   `auth.verify_token()` synchronously, un-threaded, and `verify_token`
   opens a fresh `sqlite3.connect()` per request. Each call is fast (a
   local file, no network/TLS), so this alone probably won't *break* the
   deploy at 100 users — but it's real, avoidable serialization on every
   single API call, and the fix is cheap: offload it to a thread, or cache
   verified tokens briefly.

All live editing state is also a plain in-process Python dict
(`app/diagram_store.py`), which is why the backend runs as a single
process. That ceiling doesn't break at 100 users by itself — one process
can *hold* 100 sessions' worth of dicts in memory fine — but it does mean
100 truly-concurrent, continuously-editing users is **not** compatible
with the current architecture without real pain (see "Out of scope" at
the bottom). 100 users arriving as a *burst* is survivable once the two
fixes above are applied, with the host machine's actual hardware being
the one real wildcard this plan can't quantify (see bottleneck #3 below).

---

## Current setup

Confirmed from `webapp/deploy/docker-compose.yml`, `backend.Dockerfile`,
and the watchdog scripts:
- `uvicorn ... --workers 1` — one process, one event loop.
- Every route handler in `app/routers/*.py` (reposition, node/edge CRUD,
  auto-arrange, undo/redo, CSV apply, PPTX export, bootstrap/upload) is a
  plain **sync `def`**, not `async def`. FastAPI/Starlette runs those
  through anyio's thread-pool offload, whose **default cap is 40 threads,
  shared by the whole process** (confirmed against anyio/Starlette docs).
- `app/db.py`'s `connect()` calls plain `sqlite3.connect(SQLITE_DB_PATH)`
  with **no `journal_mode=WAL` pragma, no explicit busy-timeout** anywhere
  in `db.py`/`auth.py`/`projects.py` — so it's on SQLite's default
  rollback-journal mode (a writer holds an exclusive lock on the whole
  file for the duration of its transaction, blocking all concurrent
  readers/writers) and Python's `sqlite3` default 5-second busy-timeout
  before raising `OperationalError: database is locked`.
- No CPU/memory limits are set on the `backend`/`caddy` containers in
  `docker-compose.yml` — they can use the whole host, which is good (no
  artificial ceiling) but also means capacity is **however powerful the
  actual home machine is**, which this plan can't quantify without
  knowing the hardware.
- Traffic reaches the box through a single `cloudflared` connector process
  tunneling to Caddy, which proxies to the backend over the compose
  network — all single-hop, no extra queuing layer of its own at these
  volumes.

## Priority-ordered bottlenecks

| # | What breaks | Roughly at what load | Why (actual code path) |
|---|---|---|---|
| 1 | **Event loop blocks on every authenticated request** | Adds real, avoidable latency well before 100 users; unlikely to fully break the deploy on its own at this scale | `app/main.py`'s `auth_middleware` is `async def` but calls `auth_store.verify_token(token)` directly — a synchronous, blocking call, not awaited, not offloaded to a thread. `verify_token` → `get_user_by_id` → `with _conn() as conn:` → `db.connect()` → a fresh `sqlite3.connect()` per request (`app/db.py`, `app/auth.py` lines ~104-128, ~173-180). It's a local file open (fast, no network/TLS), but it still runs on the one event-loop thread, not the 40-thread pool, so it blocks *all* request processing — including unrelated users' requests — for the duration of each call. 100 users clicking around means a continuous queue of these blocking calls serializing on one thread. |
| 2 | **SQLite "database is locked" errors under write bursts** | Many simultaneous *writes* (saves, signups, logouts bumping `token_version`) landing inside the same ~second | No WAL mode means a writer transaction (`INSERT`/`UPDATE` in `create_user`, `save_project`, `bump_token_version`) takes an exclusive file lock for its duration; a concurrent writer waits up to the 5s default timeout, then raises an uncaught `sqlite3.OperationalError`, which the route handler doesn't catch anywhere reviewed — it would surface as an unhandled 500. 100 users arriving together plausibly means several near-simultaneous signups/saves; this is a real, user-visible failure mode. |
| 3 | **Single CPU core contention for layout/render/export** | Depends entirely on the actual host's core count — a real unknown this plan can't quantify without knowing the hardware | `layout()` (`diagen/layout.py`), `SvgRenderer` (`diagen/render_svg.py`, 1279 lines), and PPTX assembly (`app/routers/export.py`) are synchronous CPU-bound Python. They run in the 40-thread pool, but all 40 threads share whatever cores the host actually has under the GIL — a burst of simultaneous `/api/upload`, `/api/auto-arrange`, or `/api/export/pptx/generate` calls will serialize on CPU and each one's latency balloons; the 41st-and-up simultaneous sync call queues behind the thread-pool limiter entirely. |
| 4 | **Residential upload bandwidth through the Cloudflare Tunnel** | Unknown without knowing the link's actual upload speed; flagging as a real unknown, not a guess | Every diagram re-render, SVG payload, and PPTX download egresses through the home connection's upload bandwidth via `cloudflared`. 100 simultaneous users pulling diagram JSON/SVG responses could saturate a modest residential upload link well before CPU or SQLite become the limiter — this is genuinely unknown without the actual connection's specs, so it's flagged rather than estimated. |
| 5 | **Unbounded log growth, not a crash risk but a disk-usage one** | Slow, cumulative | Every watchdog script (`backend-watchdog.sh`, `caddy-watchdog.sh`, `tunnel-watchdog.sh`, `backup-watchdog.sh`) appends to its own `logs/*.log` file forever with **no rotation or truncation anywhere** in `webapp/deploy/`. Not a 100-concurrent-user failure mode by itself, but a sustained burst (more traffic = more log lines) accelerates disk fill on a box that also stores the SQLite DB + backups on the same `diagen-data` volume. |

## Fixes, cheapest/highest-leverage first

1. **Turn on SQLite WAL mode and set an explicit busy_timeout.** One pragma pair, no new dependency, no architecture change: `conn.execute("PRAGMA journal_mode=WAL")` and `sqlite3.connect(path, timeout=15)` (or similar) in `app/db.py`'s `connect()`. WAL lets readers proceed concurrently with a writer (only writer-vs-writer still serializes), and a longer busy-timeout turns most lock contention into "briefly slower" instead of "500 error." This is the single highest-leverage fix — it directly addresses bottleneck #2.
2. **Fix `auth_middleware` to not block the event loop.** Either run `auth_store.verify_token` through `starlette.concurrency.run_in_threadpool`, or — better, since the DB call inside it is the actual cost — cache verified tokens for a few seconds (e.g. an in-memory `{token: (payload, expiry_ts)}` dict with a short TTL, same spirit as the existing rate limiter) so most requests skip the DB round-trip entirely and only re-check `token_version` periodically. A few lines, zero new infra, removes a real source of serialized latency under concurrency.
3. **Catch `sqlite3.OperationalError` (locked) at the route layer and retry once or return a clean 503** instead of letting it surface as an unhandled 500 — cheap defensive coding on top of fix #1, not a replacement for it.
4. **Add basic log rotation** (`logrotate` on the host, or swap each watchdog's `>> "$LOG_FILE"` for a size-capped append, e.g. via `rotatelogs` or a simple size-check-and-truncate in the script) so sustained higher traffic doesn't silently grow disk usage unbounded. Cheap, no architecture change.
5. **Measure actual upload bandwidth under a synthetic 100-concurrent-request test before assuming it's fine.** Not a code fix — a one-time check (e.g. a quick load test against the public tunnel URL) to turn bottleneck #4 from an unknown into either "fine" or "the real limiter," before spending effort anywhere else.
6. **Raise the anyio thread-pool limiter from 40 if CPU-bound endpoints turn out to be the observed bottleneck (not the DB ones).** One line at startup (`anyio.to_thread.current_default_thread_limiter().total_tokens = <N>`), after fixes #1-2 are in — no point raising the thread cap while the real stalls are on locking/un-threaded DB calls. Keep it modest; more threads than the host has cores to back them has diminishing/negative returns per anyio's own docs.

**What is explicitly NOT proposed here:** moving off SQLite to Postgres, or
adding Redis. WAL mode plus a sane busy-timeout solves the actual failure
mode (lock contention under bursty writes) that 100 concurrent users would
realistically trigger; a full database swap is not justified by anything
found in this review.

---

## Monitoring plan

Scoped to what a solo/small project can realistically keep running:
free-tier-first, reach for what's already built into Docker Compose before
adding any new service. **Nothing watches this deploy from outside
today** — the only existing health signal is `/api/health`
(`app/routers/bootstrap.py`) and the Docker Compose healthcheck that
already hits it internally (`docker-compose.yml` lines ~32-37), neither of
which alerts anyone.

### What to monitor, and with what

- **Uptime, from outside the home network** — nothing does this today.
  Add a **free external uptime pinger** (UptimeRobot or healthchecks.io,
  both have a no-cost tier sufficient for one URL at a few-minute
  interval) hitting the public tunnel URL's `/api/health`. This is the
  single most valuable addition here — there's no platform underneath
  watching the box the way a cloud provider would; without this, nothing
  tells you it's down.
- **Container health** — already exists (`docker-compose.yml`
  healthchecks on `backend` and `caddy`) and already drives
  `restart: unless-stopped`; no change needed, just worth noting it's
  there and working as designed.
- **Structured logging** — no `logging`/`structlog`/Sentry usage anywhere
  in `app/` today (confirmed). Docker Compose already captures each
  container's stdout/stderr (`docker compose logs`); the real gap is the
  app prints nothing useful beyond `main.py`'s user-seeding messages.
  Lowest-effort improvement: add a few stdlib `logging` lines at the
  points this plan identifies as risky (SQLite lock errors, the auth
  DB-call path, layout/render exceptions) so there's something to find
  when you go looking, without adding a dependency.
- **Error tracking**: not proposing Sentry or any paid error tracker at
  this scale — the structured-logging addition above, plus `docker
  compose logs` when something looks wrong, covers "find out what threw"
  without a new service or bill.
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
  what hardware this runs on (`nproc`, `free -h`) once, since bottlenecks
  #3 and #4 above are bounded by unknowns specific to this one machine
  that no amount of code-reading can determine.

### What this monitoring plan deliberately leaves out

No Prometheus/Grafana stack, no Datadog/New Relic, no paid error tracker,
no APM agent. At this project's actual traffic (personal/low, occasional
bursts, one maintainer) the free tooling already available — one external
uptime pinger, Docker Compose's own healthchecks and log capture — covers
every signal that matters (uptime, error visibility, disk usage, backup
freshness) without adding a bill or an operational burden a solo project
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
  limit on ever running more than one backend process/worker**, which in
  turn caps total CPU available to the single process at whatever the
  home box's actual core count is. No amount of connection-handling or
  middleware fixes changes that — the only real fix is moving session
  state out of the process (Redis, or SQLite itself with a session table)
  so multiple workers could share it. That is a genuine architecture
  change, not a tuning pass, and this plan is not proposing it now because
  nothing found in this review shows it's *necessary* at 100 users
  specifically — the actual first failures are SQLite lock contention and
  the event-loop-blocking auth check above, both fixable without it. If
  sustained (not bursty) 100-way concurrent editing becomes the real
  target, revisit this specific point first.
- **The rate limiter (`app/ratelimit.py`) and the auth-token-cache fix
  proposed above are both explicitly single-process, in-memory designs**
  (said outright in the module's own docstring) — fine as long as this
  stays a single process, and would need to move to a shared store
  (Redis, or the DB) the moment that constraint is ever relaxed. Not a
  problem today; flagged so it isn't forgotten if multiple workers are
  ever introduced.
- **No load test has actually been run** against this deploy as part of
  this plan — every number above (the thread-pool cap, SQLite's default
  busy-timeout, "whatever the host's actual core count is") is a
  documented platform limit, traced against this app's real code paths,
  not a measurement of this app under real synthetic load. Before
  trusting this plan's priority order under a real event, a cheap
  synthetic burst test (e.g. `locust`/`hey` against a staging copy) would
  confirm which bottleneck actually hits first in practice — and would
  also finally answer bottleneck #4's open bandwidth question and reveal
  the host's real headroom for bottleneck #3.
