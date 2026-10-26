"""Orthogonal edge routing with obstacle avoidance.

The old router picked a jog at a fixed fraction of the gap an edge crossed. On
small diagrams that is fine; on a large one it draws long horizontal runs
straight through whatever boxes happen to sit in the way, and stacks parallel
edges on the same line.

This routes on a *channel grid* instead: the candidate x/y lines are the
corridors between node boxes, and each edge is A*-searched through them. Cost
penalises length, turns, and — crucially — reusing a corridor another edge has
already taken, which is what keeps parallel connections visually separate.

The search is bounded; anything past the limits falls back to the caller's
simple route so a pathological diagram degrades instead of hanging.
"""
from __future__ import annotations
import heapq
from bisect import bisect_left

CLEAR = 8.0          # gap kept between an edge and a box it passes
# A run that lands exactly on a box face is not "outside" it to a reader — it
# reads as touching that shape, which makes it ambiguous which box the line is
# actually connected to. Edge endpoints sit on faces and are registered as grid
# lines, so without this margin A* was free to send long runs straight down a
# box's edge. Kept well below CLEAR so the real corridors stay usable.
GRAZE = 1.0
TURN_COST = 26.0     # discourages staircases; a straight run reads better
REUSE_COST = 45.0    # per shared bucket of an existing run
LANE_TOL = 7.0       # two runs closer than this read as one line
POS_BUCKET = 16.0    # granularity of the congestion map along a line
HEURISTIC_W = 1.2   # weighted A*: slightly longer paths, far fewer expansions
SUBLANE = 11.0       # spacing of extra tracks added inside a wide corridor
MAX_SUBLANES = 4     # per corridor, so the grid stays small enough to search
# Cost is driven by total grid cells, not by either axis on its own — a tall
# narrow grid searches fine. `max_expand` in route() is the real safety valve.
MAX_CELLS = 60000
TOTAL_BUDGET = 200000  # A* expansions per render, across all edges


class Router:
    def __init__(self, boxes, canvas_w, canvas_h):
        """`boxes` are (x1, y1, x2, y2) obstacle rectangles (leaf nodes)."""
        self.boxes = boxes
        self.w, self.h = canvas_w, canvas_h
        self.used = {}       # drawing line -> intervals already occupied
        self._xs = None
        self._ys = None
        self._masks = None
        self._terms_x = set()
        self._terms_y = set()
        # Whole-diagram work budget. Every edit round-trips through a render, so
        # a big diagram must not spend seconds routing: once the budget is gone
        # the remaining edges keep their simple routes.
        self.budget = TOTAL_BUDGET

    def set_terminals(self, points):
        """Register every edge endpoint before routing starts.

        Endpoints have to be reachable on the grid. Adding them per-route would
        change the grid for every edge and force the blocked-step masks to be
        rebuilt each time; folding them in once keeps the grid — and therefore
        the masks — fixed for the whole render.
        """
        for x, y in points:
            self._terms_x.add(float(x))
            self._terms_y.add(float(y))
        self._xs = self._ys = self._masks = None

    # ---------- grid ----------
    def _lines(self):
        if self._xs is not None:
            return self._xs, self._ys
        xs, ys = {4.0, self.w - 4.0}, {4.0, self.h - 4.0}
        for x1, y1, x2, y2 in self.boxes:
            xs.add(x1 - CLEAR)
            xs.add(x2 + CLEAR)
            ys.add(y1 - CLEAR)
            ys.add(y2 + CLEAR)
        self._xs = sorted(set(_with_sublanes(sorted(v for v in xs if 0 <= v <= self.w)))
                          | self._terms_x)
        self._ys = sorted(set(_with_sublanes(sorted(v for v in ys if 0 <= v <= self.h)))
                          | self._terms_y)
        return self._xs, self._ys

    def _get_masks(self):
        if self._masks is None:
            xs, ys = self._lines()
            self._xi = {v: i for i, v in enumerate(xs)}
            self._yi = {v: i for i, v in enumerate(ys)}
            self._masks = self._build_masks(xs, ys)
        return self._masks

    def usable(self):
        xs, ys = self._lines()
        return bool(xs) and bool(ys) and len(xs) * len(ys) <= MAX_CELLS

    # ---------- geometry ----------
    def _blocked_h(self, y, xa, xb):
        lo, hi = (xa, xb) if xa <= xb else (xb, xa)
        for x1, y1, x2, y2 in self.boxes:
            if y1 - GRAZE < y < y2 + GRAZE and x1 < hi and x2 > lo:
                return True
        return False

    def _blocked_v(self, x, ya, yb):
        lo, hi = (ya, yb) if ya <= yb else (yb, ya)
        for x1, y1, x2, y2 in self.boxes:
            if x1 - GRAZE < x < x2 + GRAZE and y1 < hi and y2 > lo:
                return True
        return False

    def _build_masks(self, xs, ys):
        """Precompute which single grid steps are blocked.

        The A* inner loop asked "does this step hit a box?" millions of times,
        and each answer scanned every box — which made a large diagram take tens
        of seconds to render. Grid lines sit on box boundaries, so a step
        between two adjacent lines is either wholly inside a box or wholly
        outside: that can be settled once, up front, and then read as an O(1)
        lookup.
        """
        nx, ny = len(xs), len(ys)
        # hblk[iy][i] -> step xs[i]..xs[i+1] along ys[iy] is blocked
        hblk = [bytearray(max(0, nx - 1)) for _ in range(ny)]
        vblk = [bytearray(max(0, ny - 1)) for _ in range(nx)]
        for x1, y1, x2, y2 in self.boxes:
            ix_lo = bisect_left(xs, x1)
            ix_hi = bisect_left(xs, x2)
            iy_lo = bisect_left(ys, y1)
            iy_hi = bisect_left(ys, y2)
            for iy in range(ny):
                if not (y1 - GRAZE < ys[iy] < y2 + GRAZE):
                    continue
                row = hblk[iy]
                for i in range(max(0, ix_lo - 1), min(len(row), ix_hi + 1)):
                    if xs[i] < x2 and xs[i + 1] > x1:
                        row[i] = 1
            for ix in range(nx):
                if not (x1 - GRAZE < xs[ix] < x2 + GRAZE):
                    continue
                col = vblk[ix]
                for i in range(max(0, iy_lo - 1), min(len(col), iy_hi + 1)):
                    if ys[i] < y2 and ys[i + 1] > y1:
                        col[i] = 1
        return hblk, vblk

    def _seg_key(self, axis, line, pos):
        """Bucket a piece of a run: which drawing line, and where along it.

        Congestion is looked up on every A* expansion, so it has to be a single
        dict hit. Quantising the position as well as the line turns "how much
        does this overlap an existing run" into an O(1) count.
        """
        return (axis, int(line // LANE_TOL), int(pos // POS_BUCKET))

    def _congestion(self, axis, line, a, b):
        used = self.used
        if not used:
            return 0.0
        lo, hi = (a, b) if a <= b else (b, a)
        n = 0
        p = lo
        while p < hi:
            n += used.get(self._seg_key(axis, line, p), 0)
            p += POS_BUCKET
        n += used.get(self._seg_key(axis, line, hi), 0)
        return REUSE_COST * n

    def commit(self, pts):
        """Record a finished route so later edges pay to reuse its corridors."""
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if abs(ay - by) < 1.0:
                axis, line, lo, hi = "h", ay, min(ax, bx), max(ax, bx)
            elif abs(ax - bx) < 1.0:
                axis, line, lo, hi = "v", ax, min(ay, by), max(ay, by)
            else:
                continue
            p = lo
            while p < hi:
                k = self._seg_key(axis, line, p)
                self.used[k] = self.used.get(k, 0) + 1
                p += POS_BUCKET
            k = self._seg_key(axis, line, hi)
            self.used[k] = self.used.get(k, 0) + 1

    def avoid_rect(self, x1, y1, x2, y2, weight=3):
        """Bias the search away from a rectangle that isn't a route — a
        placed label's own footprint, most often, when a different edge
        needs to be re-routed clear of it. Same congestion bucket mechanism
        `commit()` uses for a finished path, just seeded from an area: every
        grid line passing through the rectangle gets its overlapping stretch
        marked used. `weight` > 1 (vs. the 1 `commit()` adds per route) so a
        label is a stronger deterrent than one more shared route corridor —
        still a cost, not a hard wall, so a diagram with no real alternative
        degrades to routing through it rather than failing to route at all.
        """
        xs, ys = self._lines()
        lo_x, hi_x = (x1, x2) if x1 <= x2 else (x2, x1)
        lo_y, hi_y = (y1, y2) if y1 <= y2 else (y2, y1)
        for x in xs:
            if lo_x <= x <= hi_x:
                p = lo_y
                while p < hi_y:
                    k = self._seg_key("v", x, p)
                    self.used[k] = self.used.get(k, 0) + weight
                    p += POS_BUCKET
                k = self._seg_key("v", x, hi_y)
                self.used[k] = self.used.get(k, 0) + weight
        for y in ys:
            if lo_y <= y <= hi_y:
                p = lo_x
                while p < hi_x:
                    k = self._seg_key("h", y, p)
                    self.used[k] = self.used.get(k, 0) + weight
                    p += POS_BUCKET
                k = self._seg_key("h", y, hi_x)
                self.used[k] = self.used.get(k, 0) + weight

    # ---------- search ----------
    def route(self, p1, p2, max_expand=9000):
        """A* an orthogonal path from p1 to p2, or None if it can't find one."""
        xs, ys = self._lines()
        if not xs or not ys or self.budget <= 0:
            return None
        hblk, vblk = self._get_masks()
        max_expand = min(max_expand, self.budget)
        # Endpoints were folded into the grid by set_terminals(); anything else
        # (a caller that skipped it) simply isn't routable here.
        try:
            start = (self._xi[p1[0]], self._yi[p1[1]])
            goal = (self._xi[p2[0]], self._yi[p2[1]])
        except KeyError:
            return None

        gx, gy = xs[goal[0]], ys[goal[1]]

        def hcost(a):
            return HEURISTIC_W * (abs(xs[a[0]] - gx) + abs(ys[a[1]] - gy))

        # state = (ix, iy, direction) so turns can be priced
        openq = [(hcost(start), 0.0, start, -1)]
        best = {(start, -1): 0.0}
        came = {}
        expands = 0
        while openq:
            _, g, cur, dirn = heapq.heappop(openq)
            expands += 1
            if expands > max_expand:
                self.budget -= expands
                return None
            if cur == goal:
                self.budget -= expands
                return self._rebuild(came, (cur, dirn), xs, ys)
            if g > best.get((cur, dirn), 1e18) + 1e-9:
                continue
            cx, cy = cur
            for nd, (dx, dy) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < len(xs) and 0 <= ny < len(ys)):
                    continue
                if dx:
                    if hblk[cy][min(cx, nx)]:
                        continue
                    step = abs(xs[nx] - xs[cx])
                    con = self._congestion("h", ys[cy], xs[cx], xs[nx])
                else:
                    if vblk[cx][min(cy, ny)]:
                        continue
                    step = abs(ys[ny] - ys[cy])
                    con = self._congestion("v", xs[cx], ys[cy], ys[ny])
                axis = 0 if dx else 1
                turn = TURN_COST if dirn >= 0 and (dirn // 2) != axis else 0.0
                ng = g + step + turn + con
                key = ((nx, ny), nd)
                if ng < best.get(key, 1e18) - 1e-9:
                    best[key] = ng
                    came[key] = (cur, dirn)
                    heapq.heappush(openq, (ng + hcost((nx, ny)), ng, (nx, ny), nd))
        return None

    def _rebuild(self, came, endkey, xs, ys):
        pts = []
        key = endkey
        while key in came:
            (ix, iy), _ = key
            pts.append((xs[ix], ys[iy]))
            key = came[key]
        (ix, iy), _ = key
        pts.append((xs[ix], ys[iy]))
        pts.reverse()
        return _simplify(pts)


def _with_sublanes(lines):
    """Add extra tracks inside wide corridors.

    Box edges alone give one track per corridor, so every edge crossing that
    corridor has to be drawn on the same line as the others. A handful of
    intermediate tracks lets parallel connections sit side by side instead.
    """
    if len(lines) < 2:
        return lines
    out = []
    for a, b in zip(lines, lines[1:]):
        out.append(a)
        gap = b - a
        if gap <= SUBLANE * 2:
            continue
        n = min(MAX_SUBLANES, int(gap // SUBLANE) - 1)
        for i in range(1, n + 1):
            out.append(a + gap * i / (n + 1))
    out.append(lines[-1])
    return out


def _simplify(pts):
    """Drop collinear intermediate points so the path is bend-to-bend."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for prev, cur, nxt in zip(pts, pts[1:], pts[2:]):
        if (abs(prev[0] - cur[0]) < 1e-6 and abs(cur[0] - nxt[0]) < 1e-6) or \
           (abs(prev[1] - cur[1]) < 1e-6 and abs(cur[1] - nxt[1]) < 1e-6):
            continue
        out.append(cur)
    out.append(pts[-1])
    return out
