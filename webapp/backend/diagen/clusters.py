"""Grouping one Diagram's nodes into the separate logical diagrams a user
may have arranged side by side on a single canvas — purely geometric/graph
analysis for export (e.g. PPTX, one slide per logical diagram), never a
layout concern. Nothing here mutates a node's position.
"""
from __future__ import annotations
import math
from .model import Diagram, Node
from .interop import connections_map

# How far (in multiples of the nearest cluster's own typical node spacing)
# an orphan can sit from a cluster's bounding box before the suggestion is
# "confident" rather than just a guess worth a second look. No diagram has
# a fixed physical scale, so this is relative to that cluster's own
# geometry rather than a flat pixel number — same reasoning layout.py's
# own spacing code (_space_connected_nodes, _fit_label_space) uses
# elsewhere in this codebase.
CONFIDENT_GAP_FACTOR = 1.5


def _descendant_ids(n: Node) -> list[str]:
    out = [n.id]
    for c in n.children:
        out.extend(_descendant_ids(c))
    return out


def _bbox(nodes: list[Node]) -> tuple[float, float, float, float]:
    x1 = min(n.x for n in nodes)
    y1 = min(n.y for n in nodes)
    x2 = max(n.x + n.w for n in nodes)
    y2 = max(n.y + n.h for n in nodes)
    return x1, y1, x2, y2


def _bbox_dict(box: tuple[float, float, float, float]) -> dict:
    x1, y1, x2, y2 = box
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _bbox_gap(a: tuple, b: tuple) -> float:
    """Shortest distance between two bounding boxes; 0 if they touch/overlap."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    dx = max(ax1 - bx2, bx1 - ax2, 0.0)
    dy = max(ay1 - by2, by1 - ay2, 0.0)
    return math.hypot(dx, dy)


def find_clusters(d: Diagram) -> dict:
    """Partition `d`'s TOP-LEVEL nodes into connected components by edge
    adjacency (any path of edges, direct or through descendants, joins two
    top-level shapes into the same cluster), plus a best-effort suggestion
    for every top-level node with no edges touching it or any descendant
    at all — an "orphan", present for context rather than linked to
    anything.

    A nested child is never a cluster member or orphan on its own — it's
    folded into whichever top-level ancestor owns it, the same
    "top-level only" boundary `_space_connected_nodes`/`_fit_label_space`
    already use elsewhere (a child can't sensibly land on a different
    slide than its own container).

    Pure read: only looks at already-computed `x/y/w/h` and existing
    edges, never mutates anything, safe to call on any loaded diagram.

    Returns `{"clusters": [...], "orphans": [...]}`.
    """
    tops = d.top_level()
    if not tops:
        return {"clusters": [], "orphans": []}

    top_of: dict[str, Node] = {}

    def mark(n: Node, top: Node):
        top_of[n.id] = top
        for c in n.children:
            mark(c, top)

    for t in tops:
        mark(t, t)

    conns = connections_map(d)
    adj: dict[str, set] = {t.id: set() for t in tops}
    degree: dict[str, int] = {t.id: 0 for t in tops}
    for nid, edges in conns.items():
        top = top_of.get(nid)
        if top is None or not edges:
            continue
        degree[top.id] = degree.get(top.id, 0) + len(edges)
        for e in edges:
            other_top = top_of.get(e["other_id"])
            if other_top is not None and other_top.id != top.id:
                adj[top.id].add(other_top.id)
                adj.setdefault(other_top.id, set()).add(top.id)

    visited: set = set()
    clusters: list[dict] = []
    for t in tops:
        if degree.get(t.id, 0) == 0 or t.id in visited:
            continue
        stack, member_ids = [t.id], []
        visited.add(t.id)
        while stack:
            cur = stack.pop()
            member_ids.append(cur)
            for nxt in adj.get(cur, ()):
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append(nxt)
        members = [n for n in tops if n.id in member_ids]
        box = _bbox(members)
        clusters.append({
            # Content-derived, not a positional counter: a persisted export
            # setting keyed by this id (see Session.export_settings) should
            # still match on reopening the same diagram even if detection
            # happens to visit clusters in a different order, as long as
            # the cluster's anchor member is still around.
            "id": f"cluster_{min(member_ids)}",
            "node_ids": [nid for top in members for nid in _descendant_ids(top)],
            "top_level_ids": [n.id for n in members],
            "bbox": _bbox_dict(box),
            "suggested_name": members[0].label if len(members) == 1 else f"Diagram ({len(members)} shapes)",
        })

    orphans: list[dict] = []
    for t in tops:
        if degree.get(t.id, 0) != 0:
            continue
        box = _bbox([t])
        best_cluster, best_gap, second_gap = None, None, None
        for cl in clusters:
            cb = cl["bbox"]
            cbox = (cb["x"], cb["y"], cb["x"] + cb["w"], cb["y"] + cb["h"])
            gap = _bbox_gap(box, cbox)
            if best_gap is None or gap < best_gap:
                second_gap = best_gap
                best_gap, best_cluster = gap, cl
            elif second_gap is None or gap < second_gap:
                second_gap = gap
        confident = False
        if best_cluster is not None:
            cb = best_cluster["bbox"]
            # Typical spacing for that cluster, as a stand-in for "this
            # diagram's usual gap between shapes" — crude, but there's no
            # absolute scale to compare against otherwise.
            typical = max(cb["w"], cb["h"]) / max(1, len(best_cluster["top_level_ids"]))
            close_enough = best_gap <= typical * CONFIDENT_GAP_FACTOR
            # Close to the nearest cluster isn't enough on its own — if a
            # second cluster is nearly as close, which one this orphan
            # actually belongs to is genuinely ambiguous (the "equidistant
            # between two diagrams" case), and guessing wrong silently
            # would be worse than just asking. Require the runner-up to be
            # at least noticeably farther, not merely farther.
            unambiguous = second_gap is None or best_gap <= second_gap * 0.7
            confident = close_enough and unambiguous
        orphans.append({
            "node_id": t.id,
            "label": t.label,
            "bbox": _bbox_dict(box),
            "suggested_cluster_id": best_cluster["id"] if best_cluster else None,
            "confident": confident,
        })

    return {"clusters": clusters, "orphans": orphans}
