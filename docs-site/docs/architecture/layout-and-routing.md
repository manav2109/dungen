---
sidebar_position: 3
title: Layout & Routing
description: How rank_hint/order_hint (or plain edge topology) become a ranked, crossing-reduced, obstacle-avoiding drawing.
---

# Layout & Routing

`layout.py`, `ordering.py`, and `routing.py` together implement a standard
**Sugiyama-style** layered layout: assign each node to a rank (row, or
column in left-right mode), decide node order within each rank to minimize
crossings, then route edges around obstacles on an orthogonal grid. All
three stages are deterministic — the same workbook produces the same
drawing on every reload, which matters because node/edge iteration in
Python otherwise has no guaranteed order.

## 1. Ranking (`layout.py`)

`rank_hint` / `order_hint` are optional. When a node has no `rank_hint`,
its rank is derived from edge topology instead:

1. Build the adjacency between siblings (nodes sharing a parent). An edge
   between two deeply-nested nodes still constrains their top-level
   ancestors, so each endpoint is walked up to whichever sibling contains
   it (`_sibling_adjacency`). `reports_to` edges are flipped here too — they
   point from subordinate to manager, but the hierarchy should read the
   other way.
2. Break cycles in that adjacency (delegated to `ordering.acyclic` — see
   below), since a cyclic graph has no valid rank order.
3. Rank = longest path from any source node in the now-acyclic graph
   (`_longest_path_ranks`), computed with a Kahn's-algorithm-style queue:
   nodes with in-degree zero seed the queue, and a node's rank is pulled up
   to `max(current, predecessor + 1)` as each predecessor is processed.
4. Groups with no internal edges at all fall back to a grid rather than a
   single degenerate rank.

Sorting matters throughout: the initial queue seed is `sorted(ids)`, not
raw set order, specifically so the same workbook gets the same layout every
time it's opened — Python set iteration order for strings isn't guaranteed
stable across processes.

## 2. Ordering (`ordering.py`)

Ranking decides *which row* a node is in; ordering decides its *position
within the row*, which is what actually determines how tangled the edges
look. The pipeline:

1. **Break cycles** (`acyclic`) — an iterative DFS (iterative so a long
   chain can't blow the call stack) over `sorted(ids)`, coloring nodes
   white/grey/black and dropping any edge back to a grey (in-progress)
   node as a back-edge. Which edges get cut depends on where the DFS
   starts, so the sorted traversal is again what keeps results stable
   across runs.
2. **Seed** each rank by the barycenter of already-placed neighbours in the
   adjacent rank.
3. **Alternate** down-sweeps and up-sweeps using the median heuristic, each
   followed by an adjacent-transpose pass (swap neighbouring nodes if the
   swap reduces crossings), keeping whichever arrangement crossed least.
   Sweeps are capped at `MAX_SWEEPS = 8` — cheap on graphs of the size this
   engine actually sees (hundreds of nodes at most), and each sweep is
   checked monotonically, so the cap costs nothing in practice while
   bounding worst-case work.

`count_crossings` tallies total edge crossings between every pair of
adjacent ranks, and is what the sweep/transpose steps use to decide whether
a candidate arrangement is actually better.

## 3. Routing (`routing.py`)

The router's own docstring explains the design choice directly: a naive
router that jogs at a fixed fraction of the gap an edge crosses is fine on
small diagrams, but on a large one it draws long runs straight through
whatever boxes happen to be in the way, and stacks parallel edges on top of
each other.

Instead, `routing.py` builds a **channel grid**: candidate x/y lines are
the corridors *between* node boxes, and each edge is A\*-searched through
that grid. The search cost function penalizes:

- **Length** — longer paths cost more, as usual.
- **Turns** (`TURN_COST = 26.0`) — discourages staircase paths; a straight
  run reads better.
- **Corridor reuse** (`REUSE_COST = 45.0` per shared bucket) — the key term
  that keeps parallel connections visually separated instead of overlapping
  on the same line.

A few supporting constants shape the grid itself:

- `CLEAR = 8.0` — gap kept between a routed edge and any box it passes.
- `GRAZE = 1.0` — a run that lands exactly on a box's face still reads as
  "touching that shape" to a human, which is ambiguous about which box the
  line actually connects to. Edge endpoints sit on faces and are registered
  as grid lines, so without this margin A* was free to send long runs
  straight down a box's edge; it's kept well below `CLEAR` so the real
  corridors stay usable.
- `LANE_TOL = 7.0` — two runs closer together than this read as one line to
  a viewer.
- `SUBLANE = 11.0` / `MAX_SUBLANES = 4` — extra tracks added inside a wide
  corridor, capped so the search grid doesn't grow unbounded.
- `HEURISTIC_W = 1.2` — a weighted A* heuristic: slightly longer paths in
  exchange for far fewer node expansions.

Two budgets keep this bounded on pathological input:

- `MAX_CELLS = 60000` per search — cost is driven by total grid cells, not
  either axis alone, so a tall-narrow grid still searches fine; this is the
  real safety valve.
- `TOTAL_BUDGET = 200000` A* expansions **per render, across all edges** —
  every edit round-trips through a full render, so a large diagram must not
  spend seconds routing. Once the budget is spent, remaining edges keep
  their simple fallback route instead of hanging the request.

All edge endpoints are registered up front via `set_terminals()` before any
edge is routed, rather than per-edge — adding terminals one at a time would
change the grid (and therefore invalidate the blocked-step masks) on every
single edge, instead of keeping both fixed for the whole render.

## Why this split

Keeping ranking, ordering, and routing as separate modules means each can
be reasoned about — and replaced — independently. The module table in
[Engine](/architecture/engine#module-breakdown) lists `layout.py` as the
place a genuinely different layout strategy (e.g. force-directed) would
plug in, without touching how edges get routed once node positions exist.
