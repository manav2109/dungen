---
sidebar_position: 2
title: Product Requirements
description: What it took to move DrawGen from "works on my machine" to safe-to-share, and what's still deliberately deferred.
---

# Product Requirements

Scope: what was missing to take DrawGen from "works on my machine for me" to
"safe to hand a URL to other people." Written after auditing the codebase
(`webapp/backend`, `webapp/frontend`, `webapp/deploy`) in its pre-hardening
state.

## Starting state

- FastAPI + in-memory session store (1h TTL).
- SQLite-backed named project save/load, but global — no ownership, anyone
  who could reach the API could list, load, or delete anyone else's saved
  projects.
- No authentication anywhere. CORS wide open (mitigated only because the
  browser talked same-origin through Caddy).
- No upload/request size limits, no rate limiting.
- Deployed via Cloudflare Quick Tunnel — a public URL reachable by anyone
  who had it.
- No automated tests for the projects API, no backup automation for
  `projects.db`, no auto-save (an active editing session was lost on backend
  restart unless the user explicitly clicked Save).

A correctness bug surfaced during the audit: session expiry was computed off
`created_at` rather than last activity, so a session open and actively
edited for longer than the TTL got garbage-collected out from under the user
mid-edit, not just idle ones. Fixed regardless of what else shipped.

## Requirements, by area

### 1. Hardening (cheap, no architecture decisions)

- Fix the TTL/last-active bug above.
- Cap `.xlsx` upload size (not enforced by default — an unbounded upload was
  accepted and loaded fully into memory).
- Cap CSV-paste body size (same issue, as a text field rather than a file).
- Turn unhandled `KeyError`s from an unknown `entity_type`/`relation_type`
  into proper `400`s instead of an opaque `500`.
- Basic per-IP rate limiting on mutating endpoints.
- Cap saved-project count and name length, since SQLite enforces neither on
  its own.

### 2. Reliability

- Auto-save: once a session is tied to a saved project, periodically
  re-save in the background (debounced/interval-based, not on every
  keystroke) so a crash loses at most a short window of edits.
- Scheduled, pruned backups of `projects.db` — the only durable state in the
  system.
- Tests for the projects API and its new endpoints, in the style of the
  existing fixture-based engine test suite (no hand-rolled mocks).

### 3. Auth

Two materially different shapes were on the table:

- **Shared password (simple gate)** — one password for the whole app (HTTP
  Basic Auth, or a single login + signed cookie/token). No per-user data
  separation; matches a "one global project list" model with a lock added
  to the door. Minutes of work, no schema change.
- **Real multi-user accounts** — a users table, password hashes, project
  ownership, sessions tied to a logged-in user, one user unable to see or
  touch another's projects. More correct for a team tool, meaningfully more
  work (new table + migration of existing rows, login/signup UI, auth
  middleware on every route; "forgot password" stays out of scope for a
  self-hosted tool with no mail server).

These are different enough in shape that guessing wrong would have thrown
away real work, so the choice was made deliberately before building
anything — **real multi-user accounts** is what shipped. See
[Architecture → Web App](/architecture/overview#accounts) for how it works.

### 4. Onboarding / UX polish

- Replace the one-line empty state with a short "pick a starting point"
  screen (blank / sample / upload / template — all already existed as
  actions, just not surfaced together).
- Document the keyboard shortcuts that already existed (V/C/Ctrl+Z/Delete)
  but weren't visible in the UI.
- Friendlier error surface — raw `error.response.data.detail` text in the
  toolbar is fine for a dev tool, a bit raw for "hand someone a URL."
- Mobile/responsive: **non-goal.** This is a drag/click diagram editor over
  an SVG canvas — not a realistic mobile use case.

## Sequencing

1. Hardening (§1) + the TTL bug fix — no decisions needed, shipped first.
2. Auto-save + backup script + tests (§2) — no decisions needed.
3. Auth (§3) — blocked on picking a model, decided above.
4. Onboarding/UX (§4) — after auth, since login/signup screens are part of
   the first thing a new user sees and needed to be designed together.

## Status

All four sections shipped: hardening, auto-save + backup + tests,
multi-user accounts, and onboarding (empty-state screen, keyboard shortcuts
reference). Verified with 72 pytest cases (16 new, the rest the
pre-existing engine suite, still green), a manual curl battery for
signup/login/ownership-isolation/rate-limit/upload-cap/CSV-cap, and clean
`tsc -b` + `vite build` runs.

Deliberately deferred:

- **Password reset / email verification** — no mail server in this
  deployment; tracked as a known gap in the
  [Deployment](/deployment/home-server) docs.
- **Friendlier error-message redesign** in the toolbar (still raw `detail`
  text) — cosmetic, low priority next to everything else that shipped.
- **Mobile/responsive** — confirmed non-goal, not revisited.
