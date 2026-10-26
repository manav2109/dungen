"""Shared helpers for the diagram-editing routers: session/node/edge lookup,
response building, and the post-layout spacing passes that keep directly
connected shapes from ending up edge-to-edge.

Every router that mutates or renders a diagram goes through `_build_response`
so every reply is produced the exact same way — see app/main.py's module
docstring for why that matters.
"""
from __future__ import annotations
import csv
import io
from typing import Optional

from fastapi import HTTPException

from diagen.spec import Spec
from diagen.layout import layout, _shift
from diagen.render_svg import SvgRenderer
from diagen.render_drawio import to_drawio
from diagen.interop import node_dicts, edge_dicts, connections_map
from diagen.model import Node, Edge

from .diagram_store import store, Session
from .schemas import (
    NodeOut, EdgeOut, ConnectionOut, DiagramInfo, ShapeOut, LineOut, DiagramResponse,
)


def _first_diagram_id(spec: Spec) -> str:
    for did, d in spec.diagrams.items():
        if d.nodes:
            return did
    # no diagram has nodes yet (e.g. a freshly-uploaded rules-only workbook) —
    # fall back to the first declared diagram, or synthesize one
    if spec.diagrams:
        return next(iter(spec.diagrams))
    from diagen.model import Diagram
    spec.diagrams['D1'] = Diagram('D1', '', 'Untitled diagram')
    return 'D1'


def _html_snapshot(title: str, svg: str) -> str:
    esc_title = (title or 'Diagram').replace('<', '&lt;').replace('>', '&gt;')
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{esc_title}</title>'
        '<style>body{margin:0;padding:32px;background:#F7F7F8;'
        'font-family:Arial,Helvetica,sans-serif;display:flex;justify-content:center}'
        '.sheet{background:#fff;border:1px solid #ddd;border-radius:8px;'
        'padding:24px;box-shadow:0 1px 4px rgba(0,0,0,.08);max-width:100%}'
        'svg{max-width:100%;height:auto;display:block}</style></head>'
        f'<body><div class="sheet">{svg}</div></body></html>'
    )


def _parse_style_rules(text: str):
    rules = []
    for line in (text or '').split('\n'):
        line = line.strip()
        if not line or ':' not in line:
            continue
        cond, styles = line.split(':', 1)
        if '=' not in cond:
            continue
        mkey, mval = (x.strip() for x in cond.split('=', 1))
        fill = stroke = ''
        for part in styles.split(','):
            part = part.strip()
            if part.lower().startswith('fill='):
                fill = part[5:].strip()
            elif part.lower().startswith('stroke='):
                stroke = part[7:].strip()
        rules.append(((mkey, mval), (fill, stroke)))
    return rules


def _apply_style_rules_transient(d, rules_text: str):
    """Temporarily overlays fill/stroke for nodes whose metadata matches a
    rule, for THIS render only — restore() puts the node's real stored
    fill_override/stroke_override back afterward. Rules never mutate the
    authored data, only what gets drawn (mirrors the playground's live
    rule-preview, which is a display layer, not an edit)."""
    rules = _parse_style_rules(rules_text)
    if not rules:
        return lambda: None
    originals = {}
    for n in d.nodes.values():
        meta = n.meta_dict()
        for (mkey, mval), (fill, stroke) in rules:
            if meta.get(mkey) == mval:
                originals[n.id] = (n.fill_override, n.stroke_override)
                if fill:
                    n.fill_override = fill
                if stroke:
                    n.stroke_override = stroke
                break

    def restore():
        for nid, (f, s) in originals.items():
            node = d.nodes.get(nid)
            if node:
                node.fill_override, node.stroke_override = f, s
    return restore


def _gen_id(prefix: str, existing: set) -> str:
    i = len(existing) + 1
    while f'{prefix}{i}' in existing:
        i += 1
    return f'{prefix}{i}'


def _relayout(session: Session):
    w, h = layout(session.diagram, session.spec)
    _space_connected_nodes(session.diagram)
    session.canvas_w, session.canvas_h = w, h


# Room kept beyond the outermost shape so there is always somewhere to drag to.
CANVAS_PAD = 240.0

# Smallest face-to-face clearance a dragged node is allowed to leave against a
# node it's directly connected to. Below this, the edge router has nowhere
# clean to put the line and falls back to an ugly dip-under reroute. ~5cm on a
# normal 96dpi screen — this canvas has no real physical unit, so it's a
# screen-pixel approximation, not a precise conversion.
MIN_EDGE_GAP = 190.0


def _axis_gap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """Clearance between two 1-D intervals; negative when they overlap (by
    that much)."""
    if a_hi <= b_lo:
        return b_lo - a_hi
    if b_hi <= a_lo:
        return a_lo - b_hi
    return -(min(a_hi, b_hi) - max(a_lo, b_lo))


def _keep_clear_of(n: Node, other: Node, min_gap: float = MIN_EDGE_GAP) -> None:
    """Jump `n` a short distance further from `other` if dragging it left less
    than `min_gap` of clear room between their boxes — keeps the connector
    between two directly-linked shapes from being squeezed into a messy
    dip-under route. Only `n` moves; `other` (and whatever it's connected to)
    stays put. Pushes along whichever axis is already the more "separated"
    one, so a side-by-side pair stays side-by-side rather than jumping to a
    stacked layout."""
    if n is other:
        return
    hgap = _axis_gap(n.x, n.x + n.w, other.x, other.x + other.w)
    vgap = _axis_gap(n.y, n.y + n.h, other.y, other.y + other.h)
    if max(hgap, vgap) >= min_gap:
        return
    if hgap >= vgap:
        dx = (min_gap - hgap) * (1.0 if n.cx >= other.cx else -1.0)
        _shift(n, dx, 0.0)
    else:
        dy = (min_gap - vgap) * (1.0 if n.cy >= other.cy else -1.0)
        _shift(n, 0.0, dy)


def _keep_connections_clear(d, n: Node) -> None:
    """Apply `_keep_clear_of` against every node `n` has a direct edge to.
    Two passes so an earlier push (to clear neighbour A) doesn't quietly
    re-crowd neighbour B — cheap, and converges for the common case of a
    node with a handful of connections."""
    for _ in range(2):
        for e in d.edges:
            if e.source == n.id:
                other = d.nodes.get(e.target)
            elif e.target == n.id:
                other = d.nodes.get(e.source)
            else:
                continue
            if other is not None:
                _keep_clear_of(n, other)


def _space_connected_nodes(d) -> None:
    """Diagram-wide version of `_keep_connections_clear`, run after every
    fresh layout (sample/upload/template/outline/auto-arrange/project-load) —
    not just an interactive drag. `layout()`'s own rank spacing (SZ.GAP_X/
    GAP_Y) is sized for short-or-no labels; two directly-connected nodes a
    workbook happens to rank right next to each other can still end up only
    a few pixels apart, which starves a long edge label of room to wrap and
    forces it into the tall, heavily-stacked block that then overlaps
    whatever else is nearby (as well as risking the dip-under reroute
    `MIN_EDGE_GAP` exists for). Pushes whichever of the two already sits
    further out, in the direction it's already offset, so the layout's
    left-to-right/top-to-bottom flow stays intact — never flips which one
    leads. Two passes for the same reason `_keep_connections_clear` uses them.

    Top-level nodes only. `_shift`/`_keep_clear_of` move a node in absolute
    coordinates and don't touch its ancestors, so applying this to a nested
    child shoves it without the container it sits in growing to match —
    the child ends up partly outside its own container, or (with many
    cross-container edges, e.g. an EA landscape where most connections run
    between children of different domains) repeatedly yanked around by
    every edge touching it. Top-level-to-top-level is the one case this is
    actually safe for."""
    for _ in range(2):
        for e in d.edges:
            a, b = d.nodes.get(e.source), d.nodes.get(e.target)
            if a is None or b is None or a is b or a.parent or b.parent:
                continue
            hgap = _axis_gap(a.x, a.x + a.w, b.x, b.x + b.w)
            vgap = _axis_gap(a.y, a.y + a.h, b.y, b.y + b.h)
            if max(hgap, vgap) >= MIN_EDGE_GAP:
                continue
            if hgap >= vgap:
                mover, anchor = (b, a) if a.cx <= b.cx else (a, b)
            else:
                mover, anchor = (b, a) if a.cy <= b.cy else (a, b)
            _keep_clear_of(mover, anchor)


def _fit_canvas(session: Session) -> None:
    """Grow the canvas so every shape stays on it, with room to spare.

    Dragging a node only moved the node — the canvas kept whatever size the last
    full layout produced, so anything pushed past the edge was simply clipped
    and there was nowhere to drop a shape once you reached the border. This
    expands to fit instead, and pulls content back in if a node is dragged off
    the top or left (where growing alone can't help, since those edges are the
    origin).
    """
    nodes = list(session.diagram.nodes.values())
    if not nodes:
        return
    min_x = min(n.x for n in nodes)
    min_y = min(n.y for n in nodes)
    max_x = max(n.x + n.w for n in nodes)
    max_y = max(n.y + n.h for n in nodes)

    # Off the top/left: shift the whole drawing back into positive space. The
    # diagram keeps its shape; only its origin moves.
    dx = CANVAS_PAD - min_x if min_x < CANVAS_PAD / 4 else 0.0
    dy = CANVAS_PAD - min_y if min_y < CANVAS_PAD / 4 else 0.0
    if dx or dy:
        for n in session.diagram.top_level():
            _shift(n, dx, dy)
        max_x += dx
        max_y += dy

    session.canvas_w = max(session.canvas_w, max_x + CANVAS_PAD)
    session.canvas_h = max(session.canvas_h, max_y + CANVAS_PAD)


def _build_response(session: Session, unknown_types: Optional[list[str]] = None) -> DiagramResponse:
    spec, d = session.spec, session.diagram
    # Every response goes through here, so this is the one place that guarantees
    # the canvas is big enough for whatever the last edit did.
    _fit_canvas(session)
    restore = _apply_style_rules_transient(d, session.style_rules) if session.style_rules else (lambda: None)
    try:
        renderer = SvgRenderer(spec)
        svg = renderer.render(d, session.canvas_w, session.canvas_h)
        drawio = to_drawio(d, spec)
    finally:
        restore()
    html = _html_snapshot(d.title, svg)
    return DiagramResponse(
        session_id=session.session_id,
        diagram_id=session.active_id,
        title=d.title,
        direction=d.direction or 'top-down',
        svg=svg, drawio=drawio, html=html,
        canvas_w=session.canvas_w, canvas_h=session.canvas_h,
        nodes=[NodeOut(**nd) for nd in node_dicts(d)],
        edges=[EdgeOut(**ed) for ed in edge_dicts(d)],
        connections={k: [ConnectionOut(**c) for c in v] for k, v in connections_map(d).items()},
        diagrams=[DiagramInfo(**di) for di in session.diagram_list()],
        shapes=[ShapeOut(entity_type=s.entity_type, family=s.family, shape=s.shape, fill=s.fill,
                          stroke=s.stroke, auto=s.auto, default_w=s.default_w, default_h=s.default_h,
                          min_w=s.min_w, min_h=s.min_h) for s in spec.shapes.values()],
        lines=[LineOut(relation_type=l.relation_type, family=l.family, style=l.style, width=l.width,
                        source_end=l.source_end, target_end=l.target_end, routing=l.routing,
                        label_pos=l.label_pos, color=l.color) for l in spec.lines.values()],
        style_rules=session.style_rules,
        unknown_types=unknown_types or [],
        export_settings=session.export_settings,
    )


def _get_session(session_id: str) -> Session:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, "Session expired or not found — reload the diagram")
    return session


def _get_node(session: Session, node_id: str) -> Node:
    node = session.diagram.nodes.get(node_id)
    if node is None:
        raise HTTPException(404, f"No such node: {node_id}")
    return node


def _get_edge(session: Session, edge_id: str) -> Edge:
    for e in session.diagram.edges:
        if e.id == edge_id:
            return e
    raise HTTPException(404, f"No such edge: {edge_id}")


def _descendants(d, node_id: str) -> set:
    out = set()

    def walk(nid):
        for n in d.nodes.values():
            if n.parent == nid and n.id not in out:
                out.add(n.id)
                walk(n.id)
    walk(node_id)
    return out


def _csv_rows(text: str) -> list[dict]:
    if not text or not text.strip():
        return []
    return list(csv.DictReader(io.StringIO(text)))
