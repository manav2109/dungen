"""Native-PowerPoint-shape PPTX exporter — the alternative to the raster
picture embed in app/main.py's /api/export/pptx/generate. Every node becomes
a real editable AutoShape (or a small composite of them for container/rows
nodes) and every edge becomes a real PowerPoint connector snapped to both
shapes, instead of one flat image. Mirrors render_drawio.py's
shape-kind -> style mapping (the only existing precedent for "diagen shape
kind -> some other tool's shape vocabulary"), including its two
intentionally-unspecial-cased kinds: plain 'rectangle' and 'title band' both
fall back to a plain rectangle there and here, since drawio never gives
'title band' a distinct look either.

PowerPoint's own connectors — not our A* router's path — draw the lines:
`begin_connect`/`end_connect` snap a connector's ends to the two shapes'
connection sites and PowerPoint auto-routes the elbow itself once the file
is opened. This is a known, deliberate visual difference from the app's own
rendering (simpler bends), not a bug — see the PPTX export plan doc.
"""
from __future__ import annotations
from lxml import etree
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from .model import Diagram, Node, Edge, ShapeDef, LineDef
from .spec import Spec
from . import sizing as SZ

# Ordered, substring-matched against `shape.lower()` — same pattern as
# render_drawio.py's SHAPE_STYLE. First match wins; no match falls back to
# a plain rectangle (deliberately includes 'rectangle' and 'title band').
SHAPE_KIND_TO_MSO: list[tuple[str, int]] = [
    ('stadium', MSO_SHAPE.ROUNDED_RECTANGLE),
    ('diamond', MSO_SHAPE.DIAMOND),
    ('parallelogram', MSO_SHAPE.PARALLELOGRAM),
    ('cylinder', MSO_SHAPE.CAN),
    ('cloud', MSO_SHAPE.CLOUD),
    ('3d box', MSO_SHAPE.CUBE),
    ('chevron', MSO_SHAPE.CHEVRON),
    ('wavy bottom', MSO_SHAPE.FLOWCHART_DOCUMENT),
    ('circle', MSO_SHAPE.OVAL),
    ('rounded', MSO_SHAPE.ROUNDED_RECTANGLE),
]

# Best-effort cosmetic match to LineDef.source_end/target_end — OOXML
# connector ends only support none/triangle/stealth/diamond/oval/arrow, so
# several diagen ends (hollow variants, crow's foot, ticks) collapse onto
# the closest of those rather than rendering exactly. Substring-matched,
# same style as render_drawio.py's END + _end().
ARROW_END_TO_PPTX: list[tuple[str, str]] = [
    ('filled arrow', 'triangle'),
    ('open arrow', 'arrow'),
    ('hollow triangle', 'triangle'),
    ('filled diamond', 'diamond'),
    ('open diamond', 'diamond'),
    ('filled ball', 'oval'),
    ('open circle', 'oval'),
    ("crow's foot", 'arrow'),
    ('single tick', 'none'),
    ('none', 'none'),
]

DASH_STYLE_MAP = {
    'solid': None,  # leave unset -> PowerPoint's default solid line
    'dashed': MSO_LINE_DASH_STYLE.DASH,
    'dotted': MSO_LINE_DASH_STYLE.ROUND_DOT,
    'dash-dot': MSO_LINE_DASH_STYLE.DASH_DOT,
}


def _mso_shape_kind(shape_name: str) -> int:
    low = shape_name.lower()
    for key, kind in SHAPE_KIND_TO_MSO:
        if key in low:
            return kind
    return MSO_SHAPE.RECTANGLE


def _arrow_end_type(end_name: str) -> str:
    low = (end_name or 'none').lower()
    for key, kind in ARROW_END_TO_PPTX:
        if key in low or low in key:
            return kind
    return 'none'


def _rgb(hexval: str, fallback: str) -> RGBColor:
    v = (hexval or fallback or '333333').lstrip('#') or '333333'
    return RGBColor.from_string(v)


def _fit_box(tx: float, ty: float, tw: float, th: float, aspect: float) -> tuple[float, float, float, float]:
    """Scale-to-fit + center, preserving `aspect` — the exact math of
    ExportPanel.tsx's `fitBox`, ported so a native-shape placement whose
    included-node subset has a different aspect than the full cluster still
    lands centered inside the user's chosen target rectangle."""
    w = tw
    h = w / max(aspect, 1e-6)
    if h > th:
        h = th
        w = h * aspect
    return tx + (tw - w) / 2, ty + (th - h) / 2, w, h


def _expand_ids(diagram: Diagram, node_ids: list[str]) -> set[str]:
    """A selected container pulls in every descendant automatically, even if
    the caller only named the container itself."""
    out: set[str] = set()

    def add_all(n: Node):
        out.add(n.id)
        for c in n.children:
            add_all(c)

    for nid in node_ids:
        n = diagram.nodes.get(nid)
        if n is not None:
            add_all(n)
    return out


def _render_order(diagram: Diagram, selected: set[str]) -> list[Node]:
    """DFS pre-order starting from each selected node with no selected
    parent — guarantees a container shape is added (and therefore drawn
    behind) before its children."""
    roots = [n for n in diagram.nodes.values()
             if n.id in selected and (not n.parent or n.parent not in selected)]
    order: list[Node] = []

    def visit(n: Node):
        order.append(n)
        for c in n.children:
            if c.id in selected:
                visit(c)

    for r in roots:
        visit(r)
    return order


def _bbox(nodes: list[Node]) -> tuple[float, float, float, float]:
    x1 = min(n.x for n in nodes)
    y1 = min(n.y for n in nodes)
    x2 = max(n.x + n.w for n in nodes)
    y2 = max(n.y + n.h for n in nodes)
    return x1, y1, x2, y2


def _set_arrow_ends(connector, line_def: LineDef) -> None:
    ln = connector.line._get_or_add_ln()
    head_type = _arrow_end_type(line_def.source_end)
    tail_type = _arrow_end_type(line_def.target_end)
    if head_type != 'none':
        el = etree.SubElement(ln, qn('a:headEnd'))
        el.set('type', head_type)
    if tail_type != 'none':
        el = etree.SubElement(ln, qn('a:tailEnd'))
        el.set('type', tail_type)


def _apply_text(shape, label: str, *, bold=False, align=PP_ALIGN.CENTER,
                 anchor=MSO_ANCHOR.MIDDLE, size_pt: float | None = None) -> None:
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.text = label
    p = tf.paragraphs[0]
    p.alignment = align
    p.font.bold = bold
    if size_pt:
        p.font.size = Pt(size_pt)


def _add_plain_shape(slide, shape_def: ShapeDef, node: Node, box: tuple[float, float, float, float]):
    x, y, w, h = box
    kind = _mso_shape_kind(shape_def.shape)
    shape = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if 'stadium' in shape_def.shape.lower():
        try:
            shape.adjustments[0] = 0.5
        except (IndexError, ValueError):
            pass
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(node.fill_override, shape_def.fill)
    shape.line.color.rgb = _rgb(node.stroke_override, shape_def.stroke)
    shape.line.width = Pt(1)
    _apply_text(shape, node.label)
    return shape


def _add_container_shape(slide, shape_def: ShapeDef, node: Node, box: tuple[float, float, float, float]):
    x, y, w, h = box
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(node.fill_override, shape_def.fill)
    shape.line.color.rgb = _rgb(node.stroke_override, shape_def.stroke)
    shape.line.width = Pt(1)
    if 'dashed' in shape_def.shape.lower():
        shape.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    _apply_text(shape, node.label, bold=True, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)
    return shape


def _add_rows_shape(slide, scale: float, shape_def: ShapeDef, node: Node, box: tuple[float, float, float, float]):
    x, y, w, h = box
    outer = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    outer.fill.solid()
    outer.fill.fore_color.rgb = _rgb(node.fill_override, shape_def.fill)
    outer.line.color.rgb = _rgb(node.stroke_override, shape_def.stroke)
    outer.line.width = Pt(1)
    outer.text_frame.word_wrap = True

    title_h = SZ.TITLE_H * scale
    row_h = SZ.ROW_H * scale
    header = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(title_h))
    _apply_text(header, node.label, bold=True)
    header.fill.background()
    header.line.fill.background()

    divider_y = y + title_h
    rows = node.rows()
    if rows:
        divider = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(divider_y), Inches(x + w), Inches(divider_y))
        divider.line.color.rgb = _rgb(node.stroke_override, shape_def.stroke)
        divider.line.width = Pt(0.75)
    for i, r in enumerate(rows):
        row_box = slide.shapes.add_textbox(Inches(x), Inches(divider_y + i * row_h), Inches(w), Inches(row_h))
        _apply_text(row_box, r, align=PP_ALIGN.LEFT, size_pt=11)
        row_box.fill.background()
        row_box.line.fill.background()
    return outer


_SIDE_TOP, _SIDE_LEFT, _SIDE_BOTTOM, _SIDE_RIGHT = 0, 1, 2, 3


def _connect_sides(src_box, tgt_box) -> tuple[int, int]:
    sx, sy, sw, sh = src_box
    tx, ty, tw, th = tgt_box
    scx, scy = sx + sw / 2, sy + sh / 2
    tcx, tcy = tx + tw / 2, ty + th / 2
    dx, dy = tcx - scx, tcy - scy
    if abs(dx) >= abs(dy):
        return (_SIDE_RIGHT, _SIDE_LEFT) if dx >= 0 else (_SIDE_LEFT, _SIDE_RIGHT)
    return (_SIDE_BOTTOM, _SIDE_TOP) if dy >= 0 else (_SIDE_TOP, _SIDE_BOTTOM)


def _side_point(box, side: int) -> tuple[float, float]:
    x, y, w, h = box
    return {
        _SIDE_TOP: (x + w / 2, y),
        _SIDE_LEFT: (x, y + h / 2),
        _SIDE_BOTTOM: (x + w / 2, y + h),
        _SIDE_RIGHT: (x + w, y + h / 2),
    }[side]


def _add_edge_connector(slide, shape_boxes: dict, shapes: dict, spec: Spec, edge: Edge) -> None:
    src_box, tgt_box = shape_boxes.get(edge.source), shape_boxes.get(edge.target)
    src_shape, tgt_shape = shapes.get(edge.source), shapes.get(edge.target)
    if src_box is None or tgt_box is None or src_shape is None or tgt_shape is None:
        return
    src_side, tgt_side = _connect_sides(src_box, tgt_box)
    x1, y1 = _side_point(src_box, src_side)
    x2, y2 = _side_point(tgt_box, tgt_side)
    connector = slide.shapes.add_connector(
        MSO_CONNECTOR.ELBOW, Inches(min(x1, x2)), Inches(min(y1, y2)),
        Inches(max(x1, x2)), Inches(max(y1, y2)),
    )
    connector.begin_connect(src_shape, src_side)
    connector.end_connect(tgt_shape, tgt_side)

    line_def = spec.line_of(edge)
    connector.line.color.rgb = _rgb('', line_def.color)
    connector.line.width = Pt(max(0.5, line_def.width))
    dash = DASH_STYLE_MAP.get(line_def.style)
    if dash is not None:
        connector.line.dash_style = dash
    _set_arrow_ends(connector, line_def)

    if edge.label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        label_box = slide.shapes.add_textbox(Inches(mx - 0.6), Inches(my - 0.15), Inches(1.2), Inches(0.3))
        _apply_text(label_box, edge.label, size_pt=9)
        label_box.fill.background()
        label_box.line.fill.background()


def render_native_placement(slide, diagram: Diagram, spec: Spec, node_ids: list[str],
                             box: tuple[float, float, float, float]) -> None:
    """Entry point for app/main.py's /api/export/pptx/generate. `box` is the
    target (x, y, w, h) in inches the user positioned via a preset/fine-tune
    in ExportPanel.tsx — the included-node subset is re-fit (scaled +
    centered, aspect preserved) inside that rectangle, since excluding nodes
    can change the subset's own aspect ratio relative to the full cluster."""
    selected = _expand_ids(diagram, node_ids)
    if not selected:
        return
    ordered = _render_order(diagram, selected)
    x1, y1, x2, y2 = _bbox(ordered)
    bbox_w, bbox_h = max(x2 - x1, 1.0), max(y2 - y1, 1.0)
    tx, ty, tw, th = box
    fit_x, fit_y, fit_w, fit_h = _fit_box(tx, ty, tw, th, bbox_w / bbox_h)
    scale = fit_w / bbox_w

    def to_slide_box(n: Node) -> tuple[float, float, float, float]:
        return (
            fit_x + (n.x - x1) * scale,
            fit_y + (n.y - y1) * scale,
            n.w * scale,
            n.h * scale,
        )

    shapes: dict[str, object] = {}
    shape_boxes: dict[str, tuple[float, float, float, float]] = {}
    for n in ordered:
        shape_def = spec.shape_of(n)
        slide_box = to_slide_box(n)
        if shape_def.is_container:
            shape = _add_container_shape(slide, shape_def, n, slide_box)
        elif shape_def.auto == 'rows':
            shape = _add_rows_shape(slide, scale, shape_def, n, slide_box)
        else:
            shape = _add_plain_shape(slide, shape_def, n, slide_box)
        shapes[n.id] = shape
        shape_boxes[n.id] = slide_box

    for e in diagram.edges:
        if e.source in selected and e.target in selected:
            _add_edge_connector(slide, shape_boxes, shapes, spec, e)
