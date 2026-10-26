---
slug: /
sidebar_position: 1
title: Overview
description: What DrawGen is and how to run it locally.
---

# DrawGen

DrawGen turns a spreadsheet into a finished diagram. Managers author plain
**Nodes** and **Edges** rows (in Excel or CSV) — entity type, label, who's
nested inside whom, who connects to whom — and the tool auto-sizes shapes,
lays them out, routes the edges, and renders SVG, draw.io, and HTML output.
No manual drawing.

It's a FastAPI + React web app built on a small Python layout engine, the
**diagen** engine. The engine is the single source of truth for sizing,
layout, and routing — the frontend is a thin client, so what you see on
screen and what you export never drift apart.

Everything is also editable interactively: drag shapes, drag-create from a
palette, connect two shapes with a click-click tool, edit labels/colors/
metadata, undo/redo, switch between diagrams in a multi-diagram workbook,
paste CSV, generate from a template or an indented outline, and apply live
style rules.

```text
webapp/
  backend/    FastAPI app + the diagen engine + bundled samples
  frontend/   Vite + React + TypeScript UI
```

## Quick start

**Backend**

```bash
cd webapp/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (separate terminal)

```bash
cd webapp/frontend
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`). Sign up an
account from the login screen — there's no pre-seeded user.

Continue with [Architecture](/architecture/overview) for how the pieces fit
together, or the [User Guide](/user-guide/operations) for running an actual
deployment.
