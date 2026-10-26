"""Layout engine — ranked rows + recursive container fit (SZ-08..SZ-11).

rank_hint / order_hint are OPTIONAL: when missing, ranks are derived from edge
topology (longest path); groups without internal edges fall back to a grid.
"""
from __future__ import annotations
import math
from collections import defaultdict, deque
from .model import Diagram, Node
from .spec import Spec
from . import sizing as SZ
from . import ordering as ORD


def _sibling_adjacency(d: Diagram, ns):
    """Edges between the members of one parent group, lifted to that level.

    An edge between two deeply-nested nodes still tells us something about how
    their top-level ancestors should sit relative to each other, so each
    endpoint is walked up to whichever sibling contains it.
    """
    ids = {n.id for n in ns}

    def lift(nid):
        n = d.nodes.get(nid)
        while n is not None and n.id not in ids:
            n = d.nodes.get(n.parent)
        return n.id if n is not None else None

    adj = defaultdict(set)
    weight = defaultdict(int)
    for e in d.edges:
        a, b = lift(e.source), lift(e.target)
        # 'reports_to' points from subordinate to manager; the hierarchy reads
        # the other way round.
        if e.relation == 'reports_to':
            a, b = b, a
        if a and b and a != b:
            adj[a].add(b)
            weight[(a, b)] += 1
    return adj, sum(len(v) for v in adj.values())


def _longest_path_ranks(ids, adj):
    """Rank = longest path from any source. `adj` must already be acyclic."""
    indeg = {i: 0 for i in ids}
    for u, vs in adj.items():
        for v in vs:
            if v in indeg:
                indeg[v] += 1
    rank = {i: 1 for i in ids}
    # sorted, not raw set order — see the note in ordering.acyclic; the ranking
    # has to come out the same every time the same workbook is opened
    q = deque(i for i in sorted(ids) if indeg[i] == 0)
    guard = 0
    while q and guard < 500000:
        guard += 1
        u = q.popleft()
        for v in sorted(adj.get(u, ())):
            if v not in indeg:
                continue
            rank[v] = max(rank[v], rank[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return rank


def _auto_rank(d: Diagram) -> None:
    groups = defaultdict(list)
    for n in d.nodes.values():
        groups[n.parent].append(n)
    for parent, ns in groups.items():
        if all(n.rank > 0 for n in ns):
            continue
        ids = {n.id for n in ns}
        adj_raw, internal = _sibling_adjacency(d, ns)
        adj = ORD.acyclic(ids, adj_raw)
        rank = _longest_path_ranks(ids, adj)
        maxr = max(rank.values(), default=1)

        if internal == 0 or (maxr == 1 and len(ns) > 4):
            # Nothing to derive a hierarchy from — lay the group out as a grid.
            cols = max(1, round(math.sqrt(len(ns) * 1.2)))
            for i, n in enumerate(ns):
                if n.rank == 0:
                    n.rank = i // cols + 1
                if n.order == 0:
                    n.order = i % cols + 1
            continue

        for n in ns:
            if n.rank == 0:
                n.rank = rank.get(n.id, maxr)

        # Wrapping a very wide rank keeps the drawing from becoming a single
        # enormous row, but it also splits siblings across rows — so only do it
        # when a rank is genuinely unmanageable, and chunk it in crossing-aware
        # order (below) rather than in arbitrary dict order.
        byrank = defaultdict(list)
        for n in ns:
            byrank[n.rank].append(n)
        seed = {n.id: (n.order or 0) for n in ns}
        pre = ORD.order_ranks({r: [n.id for n in v] for r, v in byrank.items()}, adj, seed=seed)

        cap = max(6, round(math.sqrt(len(ns) * 1.6)))
        widest = max((len(v) for v in pre.values()), default=0)
        if widest > cap:
            newrank = 0
            remapped = {}
            for r in sorted(pre):
                row = pre[r]
                for i in range(0, len(row), cap):
                    newrank += 1
                    for nid in row[i:i + cap]:
                        remapped[nid] = newrank
            for n in ns:
                n.rank = remapped.get(n.id, n.rank)
            byrank = defaultdict(list)
            for n in ns:
                byrank[n.rank].append(n)
            pre = ORD.order_ranks({r: [n.id for n in v] for r, v in byrank.items()}, adj, seed=seed)

        for r, row in pre.items():
            for i, nid in enumerate(row):
                d.nodes[nid].order = i + 1

    for n in d.nodes.values():          # safety net
        if n.rank == 0:
            n.rank = 1
        if n.order == 0:
            n.order = 1


# A horizontal edge run needs its own lane; when many edges cross the same rank
# boundary the gap has to grow or they end up drawn through the boxes below it.
LANE_H = 9.0
MAX_EXTRA_GUTTER = 120.0


def _gutters(nodes, edges_between):
    """Extra space to add after each rank so edge runs have somewhere to go.

    `edges_between[r]` is how many edges cross the boundary after rank r.
    """
    out = {}
    for r, count in edges_between.items():
        if count > 1:
            out[r] = min(MAX_EXTRA_GUTTER, (count - 1) * LANE_H * 0.6)
    return out


def _rank_rows(nodes, gap_x, gap_y, lr=False, gutters=None):
    """Place nodes rank by rank. TB: ranks = rows. LR: ranks = columns."""
    if not nodes:  # empty diagram/container (e.g. a fresh blank canvas) — no rows to place
        return 0.0, 0.0
    gutters = gutters or {}
    ranks = sorted({n.rank for n in nodes})
    if lr:
        cols = []
        for r in ranks:
            col = sorted([n for n in nodes if n.rank == r], key=lambda n: n.order)
            ch = sum(n.h for n in col) + gap_y * (len(col) - 1)
            cw = max(n.w for n in col)
            cols.append((col, cw, ch))
        total_h = max(ch for _, _, ch in cols)
        x = 0.0
        for r, (col, cw, ch) in zip(ranks, cols):
            y = (total_h - ch) / 2
            for n in col:
                n.x, n.y = SZ.snap(x + (cw - n.w) / 2), SZ.snap(y)
                y += n.h + gap_y
            x += cw + gap_x + gutters.get(r, 0.0)
        return x - gap_x, total_h
    rows = []
    for r in ranks:
        row = sorted([n for n in nodes if n.rank == r], key=lambda n: n.order)
        rw = sum(n.w for n in row) + gap_x * (len(row) - 1)
        rh = max(n.h for n in row)
        rows.append((row, rw, rh))
    total_w = max(rw for _, rw, _ in rows)
    y = 0.0
    last_gutter = 0.0
    for r, (row, rw, rh) in zip(ranks, rows):
        x = (total_w - rw) / 2
        for n in row:
            n.x, n.y = SZ.snap(x), SZ.snap(y + (rh - n.h) / 2)
            x += n.w + gap_x
        last_gutter = gutters.get(r, 0.0)
        y += rh + gap_y + last_gutter
    return total_w, y - gap_y - last_gutter


def _shift(n: Node, dx: float, dy: float):
    n.x += dx
    n.y += dy
    for c in n.children:
        _shift(c, dx, dy)


def _crossing_counts(d: Diagram, nodes):
    """How many edges span each rank boundary within this sibling group."""
    ids = {n.id for n in nodes}
    rank_of = {n.id: n.rank for n in nodes}

    def lift(nid):
        n = d.nodes.get(nid)
        while n is not None and n.id not in ids:
            n = d.nodes.get(n.parent)
        return n.id if n is not None else None

    counts = defaultdict(int)
    for e in d.edges:
        a, b = lift(e.source), lift(e.target)
        if not a or not b or a == b:
            continue
        ra, rb = rank_of.get(a), rank_of.get(b)
        if ra is None or rb is None or ra == rb:
            continue
        for r in range(min(ra, rb), max(ra, rb)):
            counts[r] += 1
    return counts


def _layout_container(n: Node, spec: Spec, lr=False, d: Diagram = None):
    for c in n.children:
        _layout_container(c, spec, lr, d)
    if n.children:
        gut = _gutters(n.children, _crossing_counts(d, n.children)) if d else {}
        w, h = _rank_rows(n.children, SZ.GAP_X_IN, SZ.GAP_Y_IN, lr, gutters=gut)
        # SZ-08: container wraps children
        n.w = max(n.w if spec.shape_of(n).is_container is False else 0,
                  w + 2 * SZ.PAD_C)
        n.h = h + SZ.PAD_C + SZ.HEADER_H
        # Immediate children only - NOT the recursive _shift() (same trap its
        # own docstring warns about for absolutize(), just unfixed here
        # until now): a child that's itself a container already positioned
        # ITS children correctly relative to ITSELF one recursion level ago,
        # so recursing into them again here double-applies this PAD_C/
        # HEADER_H offset to every descendant 2+ levels down - e.g. a
        # grandchild lands HEADER_H past where its own (correctly-sized)
        # parent box actually ends, overflowing it, while the overflow
        # looks nothing like the fixed amount since it's whatever headroom
        # the inner container happened to have left after its own sizing.
        for c in n.children:
            c.x += SZ.PAD_C
            c.y += SZ.HEADER_H
        n.w, n.h = SZ.snap(n.w), SZ.snap(n.h)


def _axis_gap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """Clearance between two 1-D intervals; negative when they overlap (by
    that much)."""
    if a_hi <= b_lo:
        return b_lo - a_hi
    if b_hi <= a_lo:
        return a_lo - b_hi
    return -(min(a_hi, b_hi) - max(a_lo, b_lo))


def _grow_room(d: Diagram, mover: Node, dx: float, dy: float):
    """Open up (dx, dy) of room at `mover` for a label that needs more space
    than its current gap gives it, and keep every container that owns it
    honest about its own size.

    Shifting `mover` alone would just relocate the overlap: whatever sibling
    already sat on the far side of it is now sitting inside it instead
    (containers are packed tight, which is exactly why the gap was too
    small to begin with), and if `mover` has a parent, that parent's box no
    longer actually contains it. So each step here does up to three things
    together — shift (or, one level up, grow) the one thing that needs more
    room, carry along whichever of its *siblings* sat further out in that
    same direction so the new space doesn't immediately become a new
    overlap, and resize the shared parent to fit. If the parent's own
    resize pushes it past where it used to end, that parent is now the
    thing that needs room at the next level up — so the same steps repeat
    there, same as a growing container can itself crowd whatever sits
    beside it. A top-level shape has no parent box to resize, but it still
    has siblings — other top-level shapes its growth can just as easily
    run into — so that carry step runs there too; the canvas itself is
    what grows to fit, handled by `_fit_label_space`'s own caller. Stops as
    soon as a level didn't actually need to grow.
    """
    def _siblings(n: Node):
        if n.parent:
            p = d.nodes.get(n.parent)
            return (p.children if p is not None else []), p
        return [x for x in d.nodes.values() if not x.parent], None

    before = (mover.x, mover.y, mover.x + mover.w, mover.y + mover.h)
    _shift(mover, dx, dy)
    node = mover
    while True:
        sibs, p = _siblings(node)
        for c in sibs:
            if c is node:
                continue
            carry_x = (dx > 0 and c.x >= before[2]) or (dx < 0 and c.x + c.w <= before[0])
            carry_y = (dy > 0 and c.y >= before[3]) or (dy < 0 and c.y + c.h <= before[1])
            if carry_x or carry_y:
                _shift(c, dx if carry_x else 0.0, dy if carry_y else 0.0)
        if p is None:
            return  # reached the top level - nothing left to grow, just shift clear of
        max_x = max(c.x + c.w for c in p.children)
        max_y = max(c.y + c.h for c in p.children)
        new_w = max(p.w, max_x - p.x + SZ.PAD_C)
        new_h = max(p.h, max_y - p.y + SZ.PAD_C)
        grow_w, grow_h = new_w - p.w, new_h - p.h
        if grow_w <= 0.01 and grow_h <= 0.01:
            return
        before = (p.x, p.y, p.x + p.w, p.y + p.h)
        p.w, p.h = new_w, new_h
        node, dx, dy = p, grow_w, grow_h


def _fit_label_space(d: Diagram, spec: Spec, w: float, h: float):
    """SZ-12d lever 2 (space) — the fallback for render_svg.py's lever 1
    (reroute): a trial render gives every labelled edge's *actual* wrapped
    box, which this checks against the real gap between its own two shapes.
    A label can end up too big for that gap two different ways, and both
    need the same fix: another edge's line crossing it (lever 1 had every
    chance to route that clear and couldn't), or nothing crossing it at all
    — just its own box wider than the straight run it has to sit on, so it
    spills into the neighbouring shapes on either side. That second case
    has no line on top of it to detect, so checking only
    `renderer.overshadowed_edges` (crossing-flagged edges) missed it
    entirely: nodes paint over edges (see render_svg.py's draw order), so
    the overflow doesn't show as two things visibly fighting for the same
    pixels — it shows as the label's own text silently losing whatever
    part landed under a box's fill, which is what reads as "content isn't
    visible." Widen *that* gap, content-aware (the real measured box, not a
    guess), then let the caller re-render once against the corrected
    positions.

    A pair whose two shapes sit in different containers (or one nested and
    one not) is left alone — which container's layout should even change is
    ambiguous there, unlike a pair that share one immediate parent (where
    `_grow_room` can resize exactly that parent) or sit top-level together
    (where `_grow_room` degenerates to the plain shift this used to do
    unconditionally, since a node with no parent has nothing to grow).
    """
    from .render_svg import SvgRenderer   # deferred: avoids a hard import-time dependency for callers that never need lever 2
    renderer = SvgRenderer(spec)
    renderer.render(d, w, h)   # trial pass purely to populate label_boxes; the SVG itself is discarded
    moved = False
    for e in d.edges:
        box = renderer.label_boxes.get(id(e))
        if box is None:
            continue
        a, b = d.nodes.get(e.source), d.nodes.get(e.target)
        if a is None or b is None or a is b or a.parent != b.parent:
            continue
        needed_w, needed_h = box[2] - box[0], box[3] - box[1]
        hgap = _axis_gap(a.x, a.x + a.w, b.x, b.x + b.w)
        vgap = _axis_gap(a.y, a.y + a.h, b.y, b.y + b.h)
        if hgap >= vgap:
            if hgap >= needed_w:
                continue
            mover, anchor = (b, a) if a.cx <= b.cx else (a, b)
            dx = (needed_w - hgap) * (1.0 if mover.cx >= anchor.cx else -1.0)
            _grow_room(d, mover, dx, 0.0)
        else:
            if vgap >= needed_h:
                continue
            mover, anchor = (b, a) if a.cy <= b.cy else (a, b)
            dy = (needed_h - vgap) * (1.0 if mover.cy >= anchor.cy else -1.0)
            _grow_room(d, mover, 0.0, dy)
        moved = True
    if not moved:
        return w, h
    max_x = max(n.x + n.w for n in d.nodes.values())
    max_y = max(n.y + n.h for n in d.nodes.values())
    return max(w, max_x + SZ.MARGIN), max(h, max_y + SZ.MARGIN)


def layout(d: Diagram, spec: Spec):
    _auto_rank(d)
    lr = 'lr' in (d.direction or '').lower() or 'left' in (d.direction or '').lower()
    for n in d.nodes.values():
        SZ.size_node(n, spec)
    tops = d.top_level()
    for n in tops:
        _layout_container(n, spec, lr, d)
    # EA layer bands: if every top-level node is a container, unify widths
    if not lr and all(spec.shape_of(n).is_container for n in tops) and len(tops) > 1:
        target = max(n.w for n in tops)
        for n in tops:
            extra = target - n.w
            if extra > 0:
                n.w = target
                for c in n.children:
                    _shift(c, extra / 2, 0)
    _rank_rows(tops, SZ.GAP_X + (30 if lr else 0), SZ.GAP_Y, lr,
               gutters=_gutters(tops, _crossing_counts(d, tops)))
    # make positions absolute (children were local to parent).
    # NOTE: must shift only the immediate child here, NOT via the recursive
    # _shift() (which also walks grandchildren) — this function's own
    # recursion already visits each level exactly once. Using _shift's
    # recursive walk here double-counts every container nested 2+ levels
    # deep once that container isn't sitting at x=0/y=0 within its parent
    # (a 1-level-deep container, or one that happens to land at the origin,
    # never showed the bug — which is exactly how it stayed latent).
    def absolutize(n: Node):
        for c in n.children:
            c.x += n.x
            c.y += n.y
            absolutize(c)
    for n in tops:
        absolutize(n)
    # canvas (SZ-14)
    def walk(n):
        yield n
        for c in n.children:
            yield from walk(c)
    all_nodes = [x for t in tops for x in walk(t)]
    max_x = max((n.x + n.w for n in all_nodes), default=0.0)
    max_y = max((n.y + n.h for n in all_nodes), default=0.0)
    for t in tops:
        _shift(t, SZ.MARGIN, SZ.MARGIN + 34)  # room for title
    extra = 70 if any('route:right' in e.hint for e in d.edges) else 0
    w, h = max_x + 2 * SZ.MARGIN + extra, max_y + 2 * SZ.MARGIN + 34
    return _fit_label_space(d, spec, w, h)
