"""SVG renderer: shapes per Shape_Library, edges per Line_Rules."""
from __future__ import annotations
import zlib
import math
from xml.sax.saxutils import escape
from .model import Diagram, Node, Edge
from .spec import Spec
from . import sizing as SZ
from .routing import Router

FONT = "Arial, Helvetica, sans-serif"
TEXT = '#333333'
DASH = {'solid': None, 'dashed': '6,4', 'dotted': '2,3', 'dash-dot': '8,3,2,3'}

MARKERS = {
    'filled arrow':    ('<path d="M0,0 L10,4 L0,8 z" fill="{c}"/>', 10, 4, 12, 10),
    'open arrow':      ('<path d="M1,1 L9,4.5 L1,8" fill="none" stroke="{c}" stroke-width="1.4"/>', 9, 4.5, 12, 10),
    'hollow triangle': ('<path d="M0,0 L12,5 L0,10 z" fill="white" stroke="{c}" stroke-width="1.2"/>', 12, 5, 14, 12),
    'filled diamond':  ('<path d="M0,4.5 L7,0 L14,4.5 L7,9 z" fill="{c}"/>', 14, 4.5, 16, 10),
    'open diamond':    ('<path d="M0,4.5 L7,0 L14,4.5 L7,9 z" fill="white" stroke="{c}" stroke-width="1.2"/>', 14, 4.5, 16, 10),
    'filled ball':     ('<circle cx="5" cy="5" r="4" fill="{c}"/>', 9, 5, 12, 10),
    'open circle':     ('<circle cx="5" cy="5" r="4" fill="white" stroke="{c}" stroke-width="1.2"/>', 9, 5, 12, 10),
    "crow's foot (N)": ('<path d="M0,5 L12,0 M0,5 L12,5 M0,5 L12,10" fill="none" stroke="{c}" stroke-width="1.2"/>', 12, 5, 14, 12),
    "crow's foot":     ('<path d="M0,5 L12,0 M0,5 L12,5 M0,5 L12,10" fill="none" stroke="{c}" stroke-width="1.2"/>', 12, 5, 14, 12),
    'single tick':     ('<path d="M6,0 L6,10" fill="none" stroke="{c}" stroke-width="1.4"/>', 10, 5, 12, 12),
    'single tick (1)': ('<path d="M6,0 L6,10" fill="none" stroke="{c}" stroke-width="1.4"/>', 10, 5, 12, 12),
}


def _mid(pts):
    seg = len(pts) // 2
    (x1, y1), (x2, y2) = pts[seg - 1], pts[seg]
    return (x1 + x2) / 2, (y1 + y2) / 2


def _mid_seg(pts, wpx):
    """Where to put a label, and whether to turn it to run along the line.

    Anchors on the run's *middle* segment — the part of the connector a reader
    associates with it. (Picking the longest segment instead put captions on
    whichever riser happened to be longest, often far from either endpoint, and
    turned nearly all of them on their side at once.)

    Turning it is only worth it on a vertical segment with enough length to hold
    the text; on a short one a rotated caption just sticks out past both ends.
    """
    seg = len(pts) // 2
    (x1, y1), (x2, y2) = pts[seg - 1], pts[seg]
    length = abs(x2 - x1) + abs(y2 - y1)
    vertical = abs(x1 - x2) < abs(y1 - y2) and length >= wpx * 0.9
    return (x1 + x2) / 2, (y1 + y2) / 2, vertical, length


def _stable_hash(*parts) -> int:
    """Process-independent hash.

    Python randomises str/tuple hashing per process, so anything derived from
    the built-in hash() changed on every backend restart — the same workbook
    rendered with different edge offsets and different marker ids each time.
    """
    return zlib.crc32('\x1f'.join(str(p) for p in parts).encode('utf-8'))


def _attr(value: str) -> str:
    """Escape a value for use inside a double-quoted SVG attribute.

    fill/stroke/color values come straight from user input (node overrides,
    style rules, uploaded Shape_Library/Line_Rules rows) and are otherwise
    the only attribute values in this renderer not run through `escape()` —
    unescaped, a value like `"/><script>...` breaks out of the attribute and
    injects arbitrary markup into the SVG this app `innerHTML`s into the DOM.
    """
    return escape(value, {'"': '&quot;'})


# Separation between two parallel horizontal edge runs, and the clearance an
# edge keeps from a node box it passes.
LANE_GAP = 9.0
LANE_CLEAR = 5.0

# How far a label may be nudged from its own line to dodge a neighbour. Beyond
# this it stops looking like it belongs to that connector, which is worse than
# a small overlap.
LABEL_MAX_DRIFT = 26.0   # perpendicular to the line
LABEL_SLIDE = 150.0      # along the line, where it stays clearly attached
# Edge captions wrap instead of running as one long bar; these bound how narrow
# or wide that block may get.
LABEL_WRAP_MIN = 90.0
LABEL_WRAP_MAX = 210.0
LABEL_MAX_LINES = 3


STUB = 8.0  # must match routing.CLEAR so the stub lands on a grid line
# How long the final straight run into an arrowhead should read as, when the
# router's own path would otherwise leave it pinned at exactly STUB (8px) —
# long enough to land one real elbow back from the arrowhead instead of
# right on top of it.
MIN_APPROACH = 24.0


def _stub(pt, n: Node):
    """A point one clearance out from whichever face `pt` sits on.

    Forcing a route to start and end at these keeps the first and last segment
    perpendicular to the box face, so an arrowhead always points into the shape.
    Returns None if the point isn't on a face (nothing sensible to anchor to).
    """
    x, y = pt
    if abs(x - n.x) < 0.6:
        return (n.x - STUB, y)
    if abs(x - (n.x + n.w)) < 0.6:
        return (n.x + n.w + STUB, y)
    if abs(y - n.y) < 0.6:
        return (x, n.y - STUB)
    if abs(y - (n.y + n.h)) < 0.6:
        return (x, n.y + n.h + STUB)
    return None


def _face_axis(pt, n: Node):
    """Which axis a point can move along without leaving its box face."""
    x, y = pt
    if abs(x - n.x) < 0.6 or abs(x - (n.x + n.w)) < 0.6:
        return "y"      # on a left/right face — slides vertically
    if abs(y - n.y) < 0.6 or abs(y - (n.y + n.h)) < 0.6:
        return "x"      # on a top/bottom face — slides horizontally
    return None


def _slide_on_face(pt, n: Node, off: float):
    """Move an attachment point along the box face it sits on, staying on it.

    Used to fan parallel connectors apart without lifting either end away from
    its shape. Points not on a face are returned untouched.
    """
    x, y = pt
    pad = 6.0
    on_side = abs(x - n.x) < 0.6 or abs(x - (n.x + n.w)) < 0.6
    on_tb = abs(y - n.y) < 0.6 or abs(y - (n.y + n.h)) < 0.6
    if on_side:
        lo, hi = n.y + pad, n.y + n.h - pad
        return (x, min(max(y + off, lo), hi) if hi > lo else y)
    if on_tb:
        lo, hi = n.x + pad, n.x + n.w - pad
        return (min(max(x + off, lo), hi) if hi > lo else x, y)
    return pt


CORNER_MARGIN = 10.0  # keep a connector's face position clear of a rounded corner's curve


def _away_from_corner(pos, lo, hi, margin=CORNER_MARGIN):
    """Keep a point on a box face at least `margin` from either end.

    A rounded corner's curve recedes from the bounding box before the box's
    own edge actually ends there - a connector landing mathematically "on
    the face" but within that curve's reach draws into the gap between the
    curve and the straight part of the border instead of touching the
    visible shape. Only clamps when the face has real room to spare; one too
    short for any margin is left centred rather than pushed somewhere
    arbitrary.
    """
    if hi - lo <= 2 * margin:
        return (lo + hi) / 2
    return min(max(pos, lo + margin), hi - margin)


def _simplify_pts(pts):
    """Drop duplicate and collinear points so the path is bend-to-bend."""
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 0.01 or abs(p[1] - out[-1][1]) > 0.01:
            out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - c[0]) < 0.01) or \
           (abs(a[1] - b[1]) < 0.01 and abs(b[1] - c[1]) < 0.01):
            out.pop(i)
        else:
            i += 1
    return out


def _lengthen_final_approach(full, router):
    """Give the arrowhead a real straight run to sit on instead of landing
    right on an elbow.

    `_route_around`'s path always ends by stepping from the router's last
    grid point to the target's own face point — a fixed STUB-length (8px)
    hop, by construction (see `_stub`). When the leg just before that hop
    runs a different direction (the common case: the route doubles back or
    dips around something, then turns into the target), that turn lands
    only 8px from the arrowhead — the elbow and the arrowhead visually
    collide instead of reading as a line arriving cleanly. Push the elbow
    back along the leg before it so the final run is a real length, as long
    as the extended run is still clear of every box and every already-routed
    edge; otherwise leave the path exactly as the router found it.
    """
    if len(full) < 3:
        return full
    p0, p1, p2 = full[-3], full[-2], full[-1]
    final_vertical = abs(p2[0] - p1[0]) < 0.5
    prior_vertical = abs(p0[0] - p1[0]) < 0.5
    if final_vertical == prior_vertical:
        return full  # a straight continuation (or a diagonal, which shouldn't
                      # happen here) - no elbow sitting right on the arrowhead
    final_len = abs(p2[0] - p1[0]) + abs(p2[1] - p1[1])
    if final_len < 1 or final_len >= MIN_APPROACH:
        return full
    need = MIN_APPROACH - final_len
    if final_vertical:
        prior_len = abs(p0[0] - p1[0])  # prior leg is horizontal - its length runs along x
        if prior_len < need + 2:
            return full
        sign = 1 if p2[1] > p1[1] else -1
        shared_y = p1[1] - sign * need
        new_p0, new_p1 = (p0[0], shared_y), (p1[0], shared_y)
        # Box collisions only - _congestion is a cost the A* search weighs
        # against alternatives, not a hard "nothing else may ever run near
        # here" rule, and it returns a number (truthy for any reuse at all,
        # however incidental) rather than a yes/no. Vetoing on it rejected
        # exactly the elbows most in need of this fix, in the busiest parts
        # of a diagram - where something else sharing the general corridor
        # is normal, not a sign the extension itself is unsafe.
        if router._blocked_h(shared_y, p0[0], p1[0]) or router._blocked_v(p1[0], shared_y, p2[1]):
            return full
    else:
        prior_len = abs(p0[1] - p1[1])  # prior leg is vertical - its length runs along y
        if prior_len < need + 2:
            return full
        sign = 1 if p2[0] > p1[0] else -1
        shared_x = p1[0] - sign * need
        new_p0, new_p1 = (shared_x, p0[1]), (shared_x, p1[1])
        if router._blocked_v(shared_x, p0[1], p1[1]) or router._blocked_h(p1[1], shared_x, p2[0]):
            return full
    return full[:-3] + [new_p0, new_p1, p2]


def _prefer_vertical(s: Node, t: Node) -> bool:
    """Should this edge leave/arrive through the top-bottom faces?

    The old test was simply "are the centres more than 10px apart vertically",
    which sent almost every edge out of the bottom face — so two boxes sitting
    side by side got an arrow that dropped out of one, ran along underneath, and
    poked up into the other, instead of going straight across between their
    facing sides.

    What actually matters is which way round the boxes are separated: if their
    vertical extents overlap they are side by side (go horizontal), if their
    horizontal extents overlap they are stacked (go vertical), and when neither
    or both overlap, follow whichever centre gap is larger.
    """
    overlap_y = s.y < t.y + t.h and t.y < s.y + s.h
    overlap_x = s.x < t.x + t.w and t.x < s.x + s.w
    if overlap_y and not overlap_x:
        return False            # side by side — arrow should touch the side faces
    if overlap_x and not overlap_y:
        return True             # stacked — arrow should touch top/bottom faces
    return abs(t.cy - s.cy) >= abs(t.cx - s.cx)


def _fan_frac(idx: int, n: int) -> float:
    """Where the idx-th of n parallel connectors sharing one hub should jog,
    spread so they read as n separate lines instead of running on top of
    each other. Same SZ-12b/SZ-13 spread the vertical branch's fan-out uses
    (shelved rather than proportional past 6, so separation stays large and
    bounded instead of shrinking to near-zero as n grows) — pulled out here
    so the horizontal branch's convergence/divergence spread (SZ-12c) can
    use it too, on the jog position as well as the entry/exit point."""
    if n <= 6:
        return 0.24 + 0.52 * (idx / (n - 1))
    k = min(5, max(3, (n + 2) // 3))
    shelf = idx % k
    return 0.12 + 0.76 * (shelf / (k - 1))


class SvgRenderer:
    def __init__(self, spec: Spec):
        self.spec = spec
        self.defs = {}
        self._obst = None
        self._lanes_used = []
        self._router = None
        self._edge_segs = []

    # ---------- markers ----------
    def _marker(self, end: str, color: str) -> str:
        key = None
        for k in MARKERS:
            if k in end.lower() or end.lower() in k:
                key = k
                break
        if key is None:
            return ''
        mid = f"m{_stable_hash(key, color) % 10**8}"
        if mid not in self.defs:
            body, refx, refy, mw, mh = MARKERS[key]
            self.defs[mid] = (
                f'<marker id="{mid}" viewBox="0 0 {mw} {mh}" markerWidth="{mw}" markerHeight="{mh}" '
                f'refX="{refx}" refY="{refy}" orient="auto-start-reverse" '
                f'markerUnits="userSpaceOnUse">{body.format(c=_attr(color))}</marker>')
        return mid

    # ---------- text ----------
    def _text(self, x, y, lines, size=12, weight='normal', anchor='middle', color=TEXT,
              halo=False, rotate=0, line_h=None):
        """`halo` outlines the glyphs in white instead of sitting them on a solid
        panel — the connector stays visible in the gaps between letters, where a
        filled box used to blank out a chunk of it. `rotate` turns the text about
        its own anchor, used to run a label along a vertical connector."""
        out = []
        total = len(lines)
        lh = SZ.LINE_H if line_h is None else line_h
        y0 = y - (total - 1) * lh / 2
        extra = (' paint-order="stroke" stroke="#ffffff" stroke-width="3.5" '
                 'stroke-linejoin="round"' if halo else '')
        for i, ln in enumerate(lines):
            out.append(f'<text x="{x:.0f}" y="{y0 + i*lh:.1f}" font-family="{FONT}" '
                       f'font-size="{size}" font-weight="{weight}" fill="{color}" '
                       f'text-anchor="{anchor}" dominant-baseline="middle"{extra}>{escape(ln)}</text>')
        body = ''.join(out)
        if rotate:
            return f'<g transform="rotate({rotate} {x:.0f} {y:.0f})">{body}</g>'
        return body

    # ---------- shapes ----------
    def _node_svg(self, n: Node) -> str:
        s = self.spec.shape_of(n)
        fill = n.fill_override or s.fill
        st = n.stroke_override or s.stroke
        x, y, w, h = n.x, n.y, n.w, n.h
        shape = s.shape.lower()
        label = self._text(n.cx, n.cy, n.lines)
        A = f'stroke="{_attr(st)}" stroke-width="1.2"'

        if s.is_container:
            dash = ' stroke-dasharray="6,4"' if 'dashed' in shape else ''
            return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{_attr(fill)}" {A}{dash}/>'
                    + self._text(x + 10, y + 15, [n.label], 13, 'bold', 'start', '#555555'))
        if s.auto == 'rows':
            rows = n.rows()
            out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="white" {A}/>',
                   f'<rect x="{x}" y="{y}" width="{w}" height="{SZ.TITLE_H}" fill="{_attr(fill if fill != "#FFFFFF" else "#E8E8E8")}" {A}/>',
                   self._text(n.cx, y + SZ.TITLE_H / 2, [n.label], 12, 'bold')]
            has_ports = 'ports=' in (n.meta or '')
            for i, r in enumerate(rows):
                ry = y + SZ.TITLE_H + i * SZ.ROW_H
                if i:
                    out.append(f'<line x1="{x}" y1="{ry}" x2="{x+w}" y2="{ry}" stroke="#DDDDDD"/>')
                bold = 'bold' if '(PK)' in r else 'normal'
                out.append(self._text(x + 10, ry + SZ.ROW_H / 2, [r], 11, bold, 'start'))
                if has_ports:
                    py = ry + SZ.ROW_H / 2
                    out.append(f'<circle cx="{x}" cy="{py}" r="2.6" fill="{st}"/>')
                    out.append(f'<circle cx="{x+w}" cy="{py}" r="2.6" fill="{st}"/>')
            return ''.join(out)
        if 'person_card' in n.type:
            name, _, title = n.label.partition(' — ')
            return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{_attr(fill)}" {A}/>'
                    f'<circle cx="{x+22}" cy="{n.cy}" r="14" fill="#E8EEF9" stroke="{_attr(st)}"/>'
                    f'<circle cx="{x+22}" cy="{n.cy-4}" r="5" fill="{st}"/>'
                    f'<path d="M{x+13},{n.cy+9} a9,7 0 0 1 18,0" fill="{st}"/>'
                    + self._text(x + 44, n.cy - 8, [name], 12, 'bold', 'start')
                    + self._text(x + 44, n.cy + 9, [title or ''], 10.5, 'normal', 'start', '#666666'))
        if 'stadium' in shape or 'pill' in shape:
            return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2}" fill="{_attr(fill)}" {A}/>' + label
        if 'diamond' in shape:
            pts = f'{n.cx},{y} {x+w},{n.cy} {n.cx},{y+h} {x},{n.cy}'
            return f'<polygon points="{pts}" fill="{_attr(fill)}" {A}/>' + label
        if 'parallelogram' in shape:
            k = 14
            pts = f'{x+k},{y} {x+w},{y} {x+w-k},{y+h} {x},{y+h}'
            return f'<polygon points="{pts}" fill="{_attr(fill)}" {A}/>' + label
        if 'hexagon' in shape:
            k = min(22, w * 0.16)
            pts = f'{x+k},{y} {x+w-k},{y} {x+w},{n.cy} {x+w-k},{y+h} {x+k},{y+h} {x},{n.cy}'
            return f'<polygon points="{pts}" fill="{_attr(fill)}" {A}/>' + label
        if 'cylinder' in shape:
            ry = 9
            return (f'<path d="M{x},{y+ry} a{w/2},{ry} 0 0 1 {w},0 v{h-2*ry} a{w/2},{ry} 0 0 1 -{w},0 z" fill="{_attr(fill)}" {A}/>'
                    f'<path d="M{x},{y+ry} a{w/2},{ry} 0 0 0 {w},0" fill="none" {A}/>'
                    + self._text(n.cx, n.cy + ry / 2, n.lines))
        if 'cloud' in shape:
            return (f'<path d="M{x+w*.25},{y+h*.9} h{w*.55} a{w*.16},{h*.22} 0 0 0 {w*.13},-{h*.38} '
                    f'a{w*.15},{h*.25} 0 0 0 -{w*.15},-{h*.30} a{w*.18},{h*.28} 0 0 0 -{w*.34},-{h*.08} '
                    f'a{w*.16},{h*.25} 0 0 0 -{w*.27},{h*.12} a{w*.15},{h*.24} 0 0 0 {w*.08},{h*.64} z" '
                    f'fill="{_attr(fill)}" {A}/>' + label)
        if '3d box' in shape:
            d = 10
            return (f'<rect x="{x}" y="{y+d}" width="{w-d}" height="{h-d}" fill="{_attr(fill)}" {A}/>'
                    f'<polygon points="{x},{y+d} {x+d},{y} {x+w},{y} {x+w-d},{y+d}" fill="{_attr(fill)}" {A}/>'
                    f'<polygon points="{x+w-d},{y+d} {x+w},{y} {x+w},{y+h-d} {x+w-d},{y+h}" fill="{_attr(fill)}" {A}/>'
                    + self._text(n.cx - d / 2, n.cy + d / 2, n.lines))
        if 'chevron' in shape:
            k = 18
            pts = f'{x},{y} {x+w-k},{y} {x+w},{n.cy} {x+w-k},{y+h} {x},{y+h} {x+k},{n.cy}'
            return f'<polygon points="{pts}" fill="{_attr(fill)}" {A}/>' + label
        if 'wavy bottom' in shape:
            return (f'<path d="M{x},{y} h{w} v{h*.75} c{-w*.25},{h*.35} {-w*.5},{-h*.2} {-w},{h*.1} z" '
                    f'fill="{_attr(fill)}" {A}/>' + self._text(n.cx, n.cy - 4, n.lines))
        if 'circle' in shape:
            r = min(w, h) / 2
            return f'<circle cx="{n.cx}" cy="{n.cy}" r="{r}" fill="{_attr(fill)}" {A}/>' + label
        if 'title band' in shape:
            return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{_attr(fill)}" {A}/>'
                    f'<line x1="{x}" y1="{y+16}" x2="{x+w}" y2="{y+16}" {A}/>'
                    + self._text(n.cx, n.cy + 8, n.lines))
        rx = 8 if 'rounded' in shape else 0
        icon = ''
        if n.type == 'firewall':
            icon = (f'<g stroke="{_attr(st)}" stroke-width="0.8">'
                    + ''.join(f'<line x1="{x+6}" y1="{y+8+i*7}" x2="{x+w-6}" y2="{y+8+i*7}"/>' for i in range(2))
                    + '</g>')
        if 'icon=gears' in (n.meta or ''):
            # small settings/cog glyphs under the label, e.g. an "(API)"
            # service box — purely decorative, driven by node metadata so any
            # box shape can opt in without a dedicated entity_type. Needs the
            # box tall enough (h_override) to clear the label text above it.
            gy = y + h - 15
            icon += self._gear(n.cx - 20, gy, 7) + self._gear(n.cx + 20, gy, 7)
        if 'icon=predefined' in (n.meta or ''):
            # "predefined process / subroutine" flowchart shape — a plain
            # rectangle with a second vertical rule inset from each side.
            inset = min(12, w * 0.12)
            icon += (f'<g stroke="{_attr(st)}" stroke-width="1">'
                     f'<line x1="{x+inset}" y1="{y}" x2="{x+inset}" y2="{y+h}"/>'
                     f'<line x1="{x+w-inset}" y1="{y}" x2="{x+w-inset}" y2="{y+h}"/>'
                     f'</g>')
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{_attr(fill)}" {A}/>' + icon + label

    def _gear(self, cx, cy, r=8, color='#2AA7A0'):
        teeth = 8
        pts = []
        for i in range(teeth * 2):
            ang = math.pi * i / teeth
            rad = r if i % 2 == 0 else r * 0.62
            pts.append(f'{cx + rad * math.cos(ang):.1f},{cy + rad * math.sin(ang):.1f}')
        return (f'<polygon points="{" ".join(pts)}" fill="{color}"/>'
                f'<circle cx="{cx}" cy="{cy}" r="{r*0.38:.1f}" fill="white"/>')

    # ---------- edges ----------
    def _blocked(self, d, x1, x2, y, exclude=()):
        """Nodes crossed by horizontal segment y between x1..x2 -> max bottom."""
        lo, hi = min(x1, x2), max(x1, x2)
        bot = None
        for n in d.nodes.values():
            if n.id in exclude or n.children or self.spec.shape_of(n).is_container:
                continue
            if n.x + 2 > hi or n.x + n.w - 2 < lo:
                continue
            if n.y < y < n.y + n.h:
                bot = max(bot or 0, n.y + n.h)
        return bot

    def _port_pt(self, n: Node, port: str, other: Node):
        rows = n.rows()
        if port and port in rows:
            y = n.y + SZ.TITLE_H + rows.index(port) * SZ.ROW_H + SZ.ROW_H / 2
        else:
            y = n.cy
        right = other.cx >= n.cx
        return (n.x + n.w if right else n.x, y)

    def _obstacles(self, d):
        """Leaf boxes edges must not be drawn through (cached per render)."""
        if self._obst is None:
            self._obst = [(n.x, n.y, n.x + n.w, n.y + n.h) for n in d.nodes.values()
                          if not n.children and not self.spec.shape_of(n).is_container]
        return self._obst

    def _route_around(self, pts, s, t, e):
        """Re-route an edge through the corridors between boxes.

        Only kicks in when the simple route actually misbehaves — cutting
        through a box, or retracing a corridor another edge already uses. A
        clean short route is left exactly as it was, so small diagrams keep
        their existing (already good) appearance.
        """
        r = self._router
        # An explicit route: hint is the author overriding us on purpose. Ports
        # are *not* an override — they pin which side of a box the line leaves
        # from, and the path between those points still has to dodge obstacles.
        if r is None or 'route:' in (e.hint or ''):
            return None
        if self._path_is_bad(pts, s, t):
            # Route between stubs a short way out from each box face, not
            # between the anchors themselves. Without this the search could
            # arrive at, say, a left-hand face travelling upwards, leaving
            # the arrowhead pointing along the box edge instead of into it.
            a, b = pts[0], pts[-1]
            sa, sb = _stub(a, s), _stub(b, t)
            routed = r.route(sa, sb) if sa is not None and sb is not None else None
            if routed and len(routed) <= 10:
                pts = _simplify_pts([a] + routed + [b])
            # else: A* found nothing usable (or the stubs weren't valid) -
            # fall through on the original anchor-point path rather than no
            # route at all.
        # Whichever path was chosen - the simple one, or A*'s - still worth
        # checking for an elbow sitting right on the arrowhead (e.g. the "dip
        # under an obstacle" shape _anchor_pts can produce on its own, with
        # no A* routing involved). Commit whatever ends up actually drawn,
        # lengthened or not, so later edges see it.
        pts = _lengthen_final_approach(list(pts), r)
        r.commit(pts)
        return pts

    def _path_is_bad(self, pts, s, t):
        """True if this route crosses a box it shouldn't, or doubles up."""
        r = self._router
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if abs(ay - by) < 1.0:
                if r._blocked_h(ay, ax, bx) or r._congestion('h', ay, ax, bx):
                    return True
            elif abs(ax - bx) < 1.0:
                if r._blocked_v(ax, ay, by) or r._congestion('v', ax, ay, by):
                    return True
        return False

    def _free_bands(self, d, x1, x2, lo, hi):
        """Sub-intervals of [lo, hi] where a run from x1..x2 crosses no box.

        In a ranked layout the gaps between rows are exactly these bands, so
        this is what steers a long horizontal run into the gutter between ranks
        instead of straight across the boxes sitting in them.
        """
        lo_x, hi_x = (x1, x2) if x1 <= x2 else (x2, x1)
        blocked = []
        for bx1, by1, bx2, by2 in self._obstacles(d):
            if bx2 - 2 <= lo_x or bx1 + 2 >= hi_x:
                continue
            blocked.append((by1 - LANE_CLEAR, by2 + LANE_CLEAR))
        blocked.sort()
        free, cur = [], lo
        for a, b in blocked:
            if b <= lo or a >= hi:
                continue
            a, b = max(a, lo), min(b, hi)
            if a > cur:
                free.append((cur, a))
            cur = max(cur, b)
        if cur < hi:
            free.append((cur, hi))
        return free

    def _lane_conflict(self, x1, x2, y):
        """Does a run at `y` sit on top of one already committed to?"""
        lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
        for (olo, ohi, oy) in self._lanes_used:
            if abs(oy - y) < LANE_GAP and not (ohi - 1 <= lo or olo + 1 >= hi):
                return True
        return False

    def _plan_jog(self, d, eid, p1, p2, ideal_y):
        """Choose the y for an edge's horizontal jog.

        Previously every jog sat at a fixed fraction of the gap it crossed, so
        edges spanning the same band were drawn on top of one another and cut
        straight through any box in between. Now the run is placed in a band
        that is actually free of boxes — preferring the one nearest its ideal
        position — and then nudged within that band to avoid runs already
        placed, so parallel connections read as separate lines.
        """
        lo_y, hi_y = sorted((p1[1], p2[1]))
        if hi_y - lo_y < 2:
            return ideal_y
        lo_b, hi_b = lo_y + 3, hi_y - 3
        if hi_b <= lo_b:
            return ideal_y

        bands = self._free_bands(d, p1[0], p2[0], lo_b, hi_b)
        if not bands:
            return ideal_y
        # nearest band to the ideal y (0 distance if the ideal already sits in one)
        def dist(band):
            a, b = band
            return 0.0 if a <= ideal_y <= b else min(abs(ideal_y - a), abs(ideal_y - b))
        bands.sort(key=dist)

        for a, b in bands:
            if b - a < 2:
                continue
            base = min(max(ideal_y, a + 1), b - 1)
            step = LANE_GAP
            k = 0
            while step * k <= (b - a):
                for cand in ((base + step * k), (base - step * k)) if k else (base,):
                    if a + 1 <= cand <= b - 1 and not self._lane_conflict(p1[0], p2[0], cand):
                        self._lanes_used.append((min(p1[0], p2[0]), max(p1[0], p2[0]), cand))
                        return cand
                k += 1
            # band is full — still better inside it than through a box
            self._lanes_used.append((min(p1[0], p2[0]), max(p1[0], p2[0]), base))
            return base
        return ideal_y

    def _anchor_pts(self, s: Node, t: Node, hint: str, d=None, sp='', tp='', fan=None, twin=None,
                    conv=None, div=None, eid='', plan=True):
        if sp or tp:
            p1 = self._port_pt(s, sp, t)
            p2 = self._port_pt(t, tp, s)
            if abs(p1[1] - p2[1]) < 1:
                return [p1, p2]
            off = (_stable_hash(sp, tp, s.id, t.id) % 7 - 3) * 8
            mx = (p1[0] + p2[0]) / 2 + off
            return [p1, (mx, p1[1]), (mx, p2[1]), p2]
        if 'route:right' in hint:
            xr = max(s.x + s.w, t.x + t.w) + 50
            return [(s.x + s.w, s.cy), (xr, s.cy), (xr, t.cy), (t.x + t.w, t.cy)]
        dx, dy = t.cx - s.cx, t.cy - s.cy
        if _prefer_vertical(s, t):
            if dy > 0:
                p1, p2 = (s.cx, s.y + s.h), (t.cx, t.y)
            else:
                p1, p2 = (s.cx, s.y), (t.cx, t.y + t.h)
            if abs(p1[0] - p2[0]) < 1:
                return [p1, p2]
            if fan and fan[1] > 1:
                # SZ-12b: hub/bus fan-out — spread the horizontal jog across a band
                # instead of stacking every sibling edge at the exact same midpoint,
                # so parallel risers (and their labels) stay visually distinct.
                idx, n = fan
                if n <= 6:
                    frac = 0.24 + 0.52 * (idx / (n - 1))
                else:
                    # SZ-13: large hub (>6 siblings, e.g. a bus box) — proportional
                    # spread packs everything into a near-identical height (tiny
                    # frac deltas), which forces the label-collision search to
                    # cascade labels far away from their own line. Use a small,
                    # fixed number of height "shelves" instead so vertical
                    # separation stays large and bounded regardless of n.
                    k = min(5, max(3, (n + 2) // 3))
                    shelf = idx % k
                    frac = 0.12 + 0.76 * (shelf / (k - 1))
                # also spread the exit point across the hub's own width — otherwise
                # every riser leaves from the exact same center point and only
                # diverges after the jog, stacking near the source.
                p1 = (_away_from_corner(s.x + (idx + 1) * s.w / (n + 1), s.x, s.x + s.w), p1[1])
            else:
                frac = 0.5
            if twin and twin[1] > 1:
                # multiple edges converging on the same target: spread the arrival
                # point across its width instead of every arrow piling into its
                # exact center.
                tidx, tn = twin
                p2 = (_away_from_corner(t.x + (tidx + 1) * t.w / (tn + 1), t.x, t.x + t.w), p2[1])
            my = p1[1] + frac * (p2[1] - p1[1])
            if d and plan:
                # Global lane assignment: keep this jog clear of node boxes *and*
                # of every jog already placed, instead of the old single-obstacle
                # nudge that still let parallel runs stack on one line.
                my = self._plan_jog(d, eid, p1, p2, my)
            return [p1, (p1[0], my), (p2[0], my), p2]
        else:  # horizontal
            # When the two boxes' vertical extents overlap, both ends can sit on
            # one shared y and the connector is a single straight line. The old
            # code left each end on its own centre and, if they were within 12px,
            # joined them directly — which drew a shallow diagonal rather than a
            # horizontal line whenever the centres didn't match exactly.
            lo = max(s.y, t.y)
            hi = min(s.y + s.h, t.y + t.h)
            shared_y = (lo + hi) / 2 if hi - lo >= 4 else None
            sy = shared_y if shared_y is not None else s.cy
            ty = shared_y if shared_y is not None else t.cy
            spread = (div and div[1] > 1) or (conv and conv[1] > 1)
            if div and div[1] > 1:
                # SZ-12c: one source feeding several targets on its own side —
                # each edge's own shared_y tends to land close to the others
                # when the targets sit near each other, so spread the exit
                # points across the source's face instead.
                didx, dn = div
                sy = _away_from_corner(s.y + (didx + 1) * s.h / (dn + 1), s.y, s.y + s.h)
            if conv and conv[1] > 1:
                # SZ-12c: several different sources converging on one target —
                # the horizontal-branch counterpart of the vertical branch's
                # `twin` spread above (twin only covers repeated edges on the
                # exact same source/target pair, not distinct sources sharing
                # a target). Without this every arrowhead lands near the same
                # point on the target's face instead of fanning out.
                cidx, cn = conv
                ty = _away_from_corner(t.y + (cidx + 1) * t.h / (cn + 1), t.y, t.y + t.h)
            if dx > 0:
                p1, p2 = (s.x + s.w, sy), (t.x, ty)
            else:
                p1, p2 = (s.x, sy), (t.x + t.w, ty)
            if not spread and abs(p1[1] - p2[1]) < 0.5:
                bot = d and self._blocked(d, p1[0], p2[0], p1[1])
                if bot:
                    # Dip under whatever sits between the two boxes, but keep both
                    # ends on the side faces they started on. The previous version
                    # moved them to the bottom faces instead, so a left-to-right
                    # connection arrived pointing straight up into the underside of
                    # its target.
                    yd = bot + 10
                    out_x = p1[0] + (STUB if dx > 0 else -STUB)
                    in_x = p2[0] - (STUB if dx > 0 else -STUB)
                    # When the dipped run still falls within a box's side face,
                    # leave/enter at that y directly — the 8px climb-back elbow
                    # hard against the face read as a detached arrowhead.
                    s_face = s.y + 4 <= yd <= s.y + s.h - 4
                    t_face = t.y + 4 <= yd <= t.y + t.h - 4
                    start = [(p1[0], yd)] if s_face else [p1, (out_x, p1[1]), (out_x, yd)]
                    end = [(p2[0], yd)] if t_face else [(in_x, yd), (in_x, p2[1]), p2]
                    return start + end
                return [p1, p2]
            if spread:
                # SZ-12c: without this, every one of these edges' jogs lands at
                # the same (p1.x+p2.x)/2 — since they share a source (or a
                # target) their p1.x (or p2.x) is identical, so the spread
                # above only separated the end *points*; the risers in between
                # still ran on top of each other for most of their length.
                # Spreading the jog itself fans them into separate lanes too.
                idx, n = div if (div and div[1] > 1) else conv
                frac = _fan_frac(idx, n)
            else:
                frac = 0.5
            mx = p1[0] + frac * (p2[0] - p1[0])
            return [p1, (mx, p1[1]), (mx, p2[1]), p2]

    def _edge_geom(self, e: Edge, d: Diagram, par_idx=0, par_n=1, fan=None, conv=None, div=None):
        """Final drawn geometry for one edge, with no label placed yet.

        Labels are positioned in a second pass over the whole diagram, so the
        routing decided here — which commits corridors to the shared router in
        edge order — has to be settled for *every* edge before the first
        caption is placed. Returns None for arc edges, which draw themselves.
        """
        l = self.spec.line_of(e)
        s, t = d.nodes[e.source], d.nodes[e.target]
        if 'route:arc-top' in e.hint:
            return None
        twin = (par_idx, par_n) if par_n > 1 else None
        # id(e), not e.id: e.id is author data (an Edges sheet row can leave
        # it blank, or a pasted CSV can repeat one by mistake) — fine for the
        # externally-visible data-edge-id attribute, but every internal
        # per-edge tracking key in this renderer (lane planning here, geoms/
        # _edge_segs below) needs one that's actually guaranteed unique for
        # this render, which only the Python object identity is.
        pts = self._anchor_pts(s, t, e.hint, d, e.sport, e.tport, fan=fan, twin=twin,
                               conv=conv, div=div, eid=id(e))
        # SZ-12 old parallel offset: only needed when the newer fan/twin spread
        # above didn't already separate these edges (e.g. non-hub same-pair
        # edges elsewhere in the diagram); skip it here to avoid double-shifting.
        if par_n > 1 and not (e.sport or e.tport) and not fan:
            off = SZ.PAR_OFF * (par_idx - (par_n - 1) / 2) * 2
            # Which way the whole run shifts is decided by the faces the ends sit
            # on, not by the run's overall aspect: an end on a top/bottom face can
            # only slide sideways, one on a left/right face only up and down.
            # Deciding this per-point (as an earlier version did) let an endpoint
            # and its neighbour move on different axes, bending the last segment
            # into a diagonal.
            ax_s, ax_t = _face_axis(pts[0], s), _face_axis(pts[-1], t)
            axis = ax_s or ax_t
            if axis and (ax_t is None or ax_s is None or ax_s == ax_t):
                shift = ((off, 0.0) if axis == "x" else (0.0, off))
                mid = [(px + shift[0], py + shift[1]) for px, py in pts[1:-1]]
                pts = ([_slide_on_face(pts[0], s, off)] + mid
                       + [_slide_on_face(pts[-1], t, off)])
        if l.routing == 'straight' and 'route:' not in e.hint:
            pts = [pts[0], pts[-1]]
        else:
            # Obstacle-avoiding pass runs last, on the final geometry — an
            # earlier pass would have its work undone by the offset above.
            routed = self._route_around(pts, s, t, e)
            if routed:
                pts = routed
        return l, pts

    def _edge_svg(self, e: Edge, l, pts):
        """Returns (svg_fragment, label_box). label_box is the rectangle the
        caption ended up in (None if this edge has no label) — the caller
        uses it to seed the router so edges routed afterward steer clear of
        it (see SZ-12d / avoid_rect in routing.py)."""
        path = 'M' + ' L'.join(f'{px:.0f},{py:.0f}' for px, py in pts)
        dash = DASH.get(l.style)
        attrs = f'stroke="{_attr(l.color)}" stroke-width="{l.width}" fill="none"'
        if dash:
            attrs += f' stroke-dasharray="{dash}"'
        ms = self._marker(l.source_end, l.color)
        mt = self._marker(l.target_end, l.color)
        if ms:
            attrs += f' marker-start="url(#{ms})"'
        if mt:
            attrs += f' marker-end="url(#{mt})"'
        out = [f'<path d="{path}" {attrs}/>']
        label_box = None
        if e.label:
            # A label on a vertical connector is turned to match it, so it takes a
            # narrow column instead of a wide bar straddling the line.
            if 'near source' in l.label_pos:
                vertical, lines = False, [e.label]
                lx, ly = self._place_label(pts[0][0] + 18, pts[0][1] + 14, len(e.label) * 6 + 8)
            else:
                lx, ly, lines, vertical, label_box = self._place_edge_label(pts, e.label, id(e))
            out.append(self._text(lx, ly, lines, 10.5, 'normal', 'middle', '#555555',
                                  halo=True, rotate=-90 if vertical else 0, line_h=13))
        return ''.join(out), label_box

    def _edge_svg_arc(self, e: Edge, l, s: Node, t: Node) -> str:
        """Smooth arc over the top of both boxes. Reserved for waypoint_hint
        'route:arc-top' — used for a feedback/"return request" edge running
        opposite the main flow (e.g. a downstream stage calling back to an
        upstream one), so it reads as a distinct loop rather than tangling
        through the ordinary forward-flow lines underneath the same row."""
        p1 = (s.cx, s.y)
        p2 = (t.cx, t.y)
        arc_h = max(36, abs(p1[0] - p2[0]) * 0.16)
        top = min(p1[1], p2[1]) - arc_h
        cx = (p1[0] + p2[0]) / 2
        path = f'M{p1[0]:.0f},{p1[1]:.0f} Q{cx:.0f},{top:.0f} {p2[0]:.0f},{p2[1]:.0f}'
        dash = DASH.get(l.style)
        attrs = f'stroke="{_attr(l.color)}" stroke-width="{l.width}" fill="none"'
        if dash:
            attrs += f' stroke-dasharray="{dash}"'
        ms = self._marker(l.source_end, l.color)
        mt = self._marker(l.target_end, l.color)
        if ms:
            attrs += f' marker-start="url(#{ms})"'
        if mt:
            attrs += f' marker-end="url(#{mt})"'
        out = [f'<path d="{path}" {attrs}/>']
        if e.label:
            lx, ly = cx, top + 13
            wpx = len(e.label) * 6 + 8
            lx, ly = self._place_label(lx, ly, wpx)
            out.append(self._text(lx, ly, [e.label], 10.5, 'normal', 'middle', '#555555',
                                  halo=True))
        return ''.join(out)

    # ---------- label collision avoidance ----------
    def _place_edge_label(self, pts, text, own_id=None):
        """Choose where a connector's label goes, and how to shape it.

        A label belongs at the middle of its line. When the middle happens to be
        a corner there is no straight run to sit on, so the search walks outward
        to the nearest straight stretch that is long enough — candidates too
        close to a bend are skipped rather than allowed to straddle it.

        The text is wrapped rather than set as one long bar: a two- or three-line
        block is a fraction of the width, which is what actually lets several
        captions share a crowded area instead of covering each other.

        Returns (x, y, lines, vertical, box) — box is the final placed
        rectangle, handed back so the caller can reserve it against edges
        not yet routed (see SZ-12d).
        """
        seglen = [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(pts, pts[1:])]
        total = sum(seglen) or 1.0
        longest = max(seglen, default=0.0)

        # Wrap to something near the run it has to sit on, within sane bounds.
        target = min(max(longest * 0.85, LABEL_WRAP_MIN), LABEL_WRAP_MAX)
        lines = SZ.wrap(text, target)
        if len(lines) > LABEL_MAX_LINES:
            # Too tall — set it wider rather than dropping words. Truncating here
            # would silently lose part of what the diagram is meant to say.
            wide = SZ.wrap(text, target * 1.7)
            # ...but only when the wider block still fits the run it has to sit
            # on. Between two boxes a hundred pixels apart, widening pushed the
            # caption out over the shapes on either side; there a taller,
            # narrower block is what keeps it inside the corridor.
            if max(len(s) for s in wide) * 6 + 8 <= max(longest, LABEL_WRAP_MIN):
                lines = wide
        bw = max(len(s) for s in lines) * 6 + 8
        bh = len(lines) * 13 + 4

        # Work in whole straight runs. A label centred on the middle of a straight
        # stretch reads as belonging to it; the same label parked at one end of
        # that stretch drifts towards the neighbouring line's text instead. So
        # each segment contributes its own centre first, and only if that exact
        # spot is taken do we edge along the segment (never past its corners).
        segs = []            # (rank, mid_x, mid_y, ux, uy, half_room, vertical)
        walked = 0.0
        for (a, b), L in zip(zip(pts, pts[1:]), seglen):
            if L < 1:
                walked += L
                continue
            # The caption is turned a flat -90°, so it only lines up with a
            # segment that is genuinely vertical. "Taller than it is wide" was
            # too loose: a 45° straight link satisfied it and got a caption
            # running straight down across a diagonal line.
            dxs, dys = abs(b[0] - a[0]), abs(b[1] - a[1])
            vertical = dxs < dys and dxs <= max(8.0, 0.25 * dys)
            # A rotated caption runs *along* a vertical segment, so the room it
            # needs there is the text's length (bw), not the block height —
            # measuring bh let a full-width caption rotate onto a ~20px elbow
            # and overhang every box above and below it.
            vert_ok = vertical and L >= bw * 0.95
            need = bh if (vertical and not vert_ok) else bw
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            # how far the centre may shift before the block overhangs a corner
            half_room = max(0.0, (L - need) / 2)
            centre_pos = (walked + L / 2) / total
            segs.append((abs(centre_pos - 0.5), mx, my, ux, uy, half_room,
                         vert_ok, L, need))
            walked += L
        if not segs:
            mx, my = _mid(pts)
            segs = [(0.0, mx, my, 1.0, 0.0, 0.0, False, 0.0, 0.0)]
        # the straight run whose own centre is nearest the middle of the whole
        # connector wins; ties and crowding fall through to the next one
        segs.sort(key=lambda s: (s[0], -s[7]))

        def overlaps(p, q):
            return p[0] < q[2] and p[2] > q[0] and p[1] < q[3] and p[3] > q[1]

        pad = 3

        def box_for(cx, cy, vert):
            w, h = (bh, bw) if vert else (bw, bh)
            return [cx - w / 2 - pad, cy - h / 2 - pad, cx + w / 2 + pad, cy + h / 2 + pad]

        def area(p, q):
            return (max(0.0, min(p[2], q[2]) - max(p[0], q[0]))
                    * max(0.0, min(p[3], q[3]) - max(p[1], q[1])))

        def crossings(box):
            """How many *other* connectors run under this block.

            A caption sitting across four unrelated lines is the single worst
            kind of clutter, and it is invisible to an overlap-only test because
            a stroke has no rectangle of its own.
            """
            n = 0
            for (eid, sx1, sy1, sx2, sy2) in self._edge_segs:
                if eid == own_id:
                    continue
                if box[0] < sx2 and box[2] > sx1 and box[1] < sy2 and box[3] > sy1:
                    n += 1
            return n

        # Score every candidate rather than taking the first clear one and, on a
        # crowded diagram, giving up and stacking the caption on a node box.
        # Weights are ordered so the search will always trade a long slide along
        # its own line for not covering a shape or another caption.
        best = None
        for rank, (_, mx, my, ux, uy, half_room, vert, L, need) in enumerate(segs):
            if L < need * 0.55:
                continue                     # this run is far too short for the block
            reach = max(half_room, L / 2)
            slides = [0.0]
            step = 14.0
            k = 1
            while step * k <= reach:
                slides += [step * k, -step * k]
                k += 1
            for off in (0.0, 15.0, -15.0, 27.0, -27.0, 40.0, -40.0):
                for s in slides:
                    cx = mx + ux * s + (off if vert else 0.0)
                    cy = my + uy * s + (0.0 if vert else off)
                    box = box_for(cx, cy, vert)
                    # Covering a shape or another caption makes text unreadable,
                    # so it has to outrank everything else by a wide margin. A
                    # line crossing under a haloed caption is only untidy, and
                    # its weight is capped so a congested area can never make
                    # "sit on top of that box" look like the cheaper option.
                    cost = (4000.0 * sum(1 for r in self.label_rects if overlaps(box, r))
                            + 0.2 * sum(area(box, r) for r in self.label_rects)
                            + 9.0 * min(crossings(box), 8)
                            + 1.5 * abs(s) + 2.5 * abs(off)
                            + 25.0 * rank
                            + (0.0 if abs(s) <= half_room else 45.0))
                    if best is None or cost < best[0]:
                        best = (cost, cx, cy, vert, box)
                    if cost == 0.0:
                        break
                if best and best[0] == 0.0:
                    break
            if best and best[0] == 0.0:
                break
        if best is None:
            _, mx, my, _, _, _, vert, _, _ = segs[0]
            best = (0.0, mx, my, vert, box_for(mx, my, vert))
        _, cx, cy, vert, box = best
        self.label_rects.append(box)
        return cx, cy, lines, vert, box

    def _place_label(self, lx, ly, w, h=16, pad=3, along="x", slide=None):
        """Nudge a label off its neighbours, without letting it leave its line.

        The nudge steps used to be derived from the label's own width, so a long
        caption stepped hundreds of pixels at a time and could be flung right
        across the drawing, ending up nowhere near the connector it names. Steps
        are now small and fixed, and the total displacement is hard-capped: if
        nothing clear is found nearby the label simply stays put. Since labels
        are drawn with a halo rather than an opaque panel, a slight overlap
        reads far better than a caption parked next to the wrong line.
        """
        def overlaps(a, b):
            return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]

        def box_at(cx, cy):
            return [cx - w / 2 - pad, cy - h / 2 - pad, cx + w / 2 + pad, cy + h / 2 + pad]

        # Sliding a label *along* its own connector keeps it obviously attached to
        # it, so there is plenty of room to move that way; stepping away from the
        # line is what makes a caption look orphaned, so that stays tight.
        step = 11.0
        n_along = int(min(LABEL_SLIDE if slide is None else slide, LABEL_SLIDE) / step)
        n_off = int(LABEL_MAX_DRIFT / step)
        pairs = [(a, o) for a in range(-n_along, n_along + 1) for o in range(-n_off, n_off + 1)]
        # nearest first, and strongly preferring movement along the line
        pairs.sort(key=lambda p: p[0] * p[0] + p[1] * p[1] * 9)
        for a, o in pairs:
            dx, dy = (a, o) if along == "x" else (o, a)
            cx, cy = lx + dx * step, ly + dy * step
            box = box_at(cx, cy)
            if not any(overlaps(box, r) for r in self.label_rects):
                self.label_rects.append(box)
                return cx, cy
        # Nowhere clear within reach — keep it on its own line and accept the overlap.
        self.label_rects.append(box_at(lx, ly))
        return lx, ly

    # ---------- diagram ----------
    def render(self, d: Diagram, canvas_w: float, canvas_h: float) -> str:
        self.defs = {}
        # Route planning state is per-render: obstacle boxes for this diagram,
        # and the running list of horizontal runs already committed to.
        self._obst = None
        self._lanes_used = []
        self._router = None
        self._edge_segs = []
        # Seed with every leaf node's box (shrunk slightly) so edge labels steer
        # clear of boxes too, not just other labels. Containers are excluded —
        # they're just background panels, labels are expected to sit on them.
        self.label_rects = [[n.x + 4, n.y + 4, n.x + n.w - 4, n.y + n.h - 4]
                             for n in d.nodes.values() if not self.spec.shape_of(n).is_container]
        # also protect each container's own title text (top-left corner) so
        # edge labels don't get drawn right over "TAKSY" / "VPM A-D" etc.
        self.label_rects += [[n.x + 6, n.y + 4, n.x + 16 + len(n.label) * 7, n.y + 24]
                              for n in d.nodes.values() if self.spec.shape_of(n).is_container]
        containers, leaves = [], []

        def collect(n: Node, depth=0):
            (containers if self.spec.shape_of(n).is_container else leaves).append((depth, n))
            for c in n.children:
                collect(c, depth + 1)
        for n in d.top_level():
            collect(n)
        body = []
        for _, n in sorted(containers, key=lambda p: p[0]):
            body.append(f'<g data-node-id="{escape(n.id)}">' + self._node_svg(n) + '</g>')
        pairs = {}
        for e in d.edges:
            pairs.setdefault(frozenset((e.source, e.target)), []).append(e)
        # SZ-12b: group edges that fan out from the same hub node (e.g. a bus
        # lane feeding many different targets) so their risers can be spread
        # across a band instead of colliding on the same midpoint line.
        fan_groups = {}
        for e in d.edges:
            s, t = d.nodes.get(e.source), d.nodes.get(e.target)
            if s and t and abs(t.cy - s.cy) >= 10:
                fan_groups.setdefault(e.source, []).append(e)
        for grp in fan_groups.values():
            grp.sort(key=lambda e: d.nodes[e.target].cx)

        def fan_of(e):
            s, t = d.nodes.get(e.source), d.nodes.get(e.target)
            # only look this edge up in its source's fan group if it actually
            # qualifies for one itself (same abs(dy)>=10 test used to build the
            # group) — a same-source edge that lands in a *different* row band
            # (e.g. a near-horizontal feedback loop next to mostly-vertical
            # siblings) must not be searched for in a list it was never put in.
            if s and t and abs(t.cy - s.cy) >= 10:
                fgrp = fan_groups.get(e.source)
                if fgrp and len(fgrp) > 1:
                    return (fgrp.index(e), len(fgrp))
            return None

        # Horizontal-branch counterpart of fan/twin above: fan/twin only
        # spread edges that share a source (fan) or the exact same source+
        # target pair (twin), both gated on the *vertical* branch. A hub fed
        # by several different single-edge sources side-on (e.g. three boxes
        # to its left, each with one arrow in) hits neither, and nothing in
        # the horizontal branch (`else:` below) spreads arrivals/departures
        # at all — every such edge computes its own shared_y independently,
        # which clusters arrowheads when those sources/targets sit close
        # together instead of fanning them across the shared face.
        # A near-zero |dy| means source and target sit almost side by side at
        # the same height — a plain, direct "neighbour" link, not competing
        # with anything for a lane. Folding one into a group over|t.cy-s.cy|
        # was a mistake even at n=2: it jogs what should be a single long
        # straight run into two short segments, which then starves that
        # edge's own label of wrap width (narrow segments force many short
        # wrapped lines, which is its own source of overlap) for no benefit —
        # nothing was actually competing with it for a lane. Same |dy|>=10
        # gate fan_groups above already uses, for the same reason.
        conv_groups = {}   # target.id -> horizontal-branch edges arriving at it
        div_groups = {}    # source.id -> horizontal-branch edges leaving it
        for e in d.edges:
            s, t = d.nodes.get(e.source), d.nodes.get(e.target)
            if s and t and not _prefer_vertical(s, t) and abs(t.cy - s.cy) >= 10:
                conv_groups.setdefault(e.target, []).append(e)
                div_groups.setdefault(e.source, []).append(e)
        for grp in conv_groups.values():
            grp.sort(key=lambda e: d.nodes[e.source].cy)   # top source -> top arrival, no crossings
        for grp in div_groups.values():
            grp.sort(key=lambda e: d.nodes[e.target].cy)

        def conv_of(e):
            s, t = d.nodes.get(e.source), d.nodes.get(e.target)
            if s and t and not _prefer_vertical(s, t) and abs(t.cy - s.cy) >= 10:
                cgrp = conv_groups.get(e.target)
                if cgrp and len(cgrp) > 1:
                    return (cgrp.index(e), len(cgrp))
            return None

        def div_of(e):
            s, t = d.nodes.get(e.source), d.nodes.get(e.target)
            if s and t and not _prefer_vertical(s, t) and abs(t.cy - s.cy) >= 10:
                dgrp = div_groups.get(e.source)
                if dgrp and len(dgrp) > 1:
                    return (dgrp.index(e), len(dgrp))
            return None

        # Dry pass: work out where every edge starts and ends so the router's
        # grid can include those points once, instead of being rebuilt (and
        # re-masked) for each edge in turn.
        router = Router(self._obstacles(d), canvas_w, canvas_h)
        terminals = []
        for e in d.edges:
            s, t = d.nodes.get(e.source), d.nodes.get(e.target)
            if not s or not t or 'route:arc-top' in e.hint:
                continue
            grp = pairs[frozenset((e.source, e.target))]
            twin = (grp.index(e), len(grp)) if len(grp) > 1 else None
            pts = self._anchor_pts(s, t, e.hint, d, e.sport, e.tport,
                                   fan=fan_of(e), twin=twin, conv=conv_of(e), div=div_of(e),
                                   eid=id(e), plan=False)
            terminals.append(pts[0])
            terminals.append(pts[-1])
            # the stubs the router actually searches between must be on the grid too
            for anchor, node in ((pts[0], s), (pts[-1], t)):
                st = _stub(anchor, node)
                if st is not None:
                    terminals.append(st)
        router.set_terminals(terminals)
        # A very dense diagram makes the channel grid too big to A* quickly;
        # there the simple routes stand on their own rather than stalling.
        self._router = router if router.usable() else None

        # SZ-12d: settle geometry AND place each caption one edge at a time,
        # in order of how constrained the edge is (shortest source-target
        # span first), instead of routing every edge first and only then
        # placing labels against the finished picture. That older order
        # meant a short, tight hop (e.g. two directly-connected shapes
        # sitting close together — nowhere to put its label but right where
        # it is) had already lost the chance to protect its spot by the
        # time any label was placed, so whichever longer edge got routed
        # through that same corridor drew straight over it. Settling a tight
        # edge's own geometry and caption first, then immediately reserving
        # that caption's footprint in the router (avoid_rect) before the
        # next edge is even routed, lets every edge after it steer clear
        # instead of silently overshadowing it. A label can still only see
        # — and avoid — lines/captions already settled when its own turn
        # comes, same trade every ranking-based pass makes.
        #
        # Keyed by id(e), not e.id: see the comment in _edge_geom. A plain
        # e.id key here previously meant every edge whose author data left
        # edge_id blank (or a pasted CSV repeated one) collapsed onto the
        # same dict entry — each overwriting the last, so EVERY such edge in
        # the diagram silently rendered as a copy of whichever one happened
        # to be computed last, instead of its own geometry.
        def _tightness(e):
            s, t = d.nodes.get(e.source), d.nodes.get(e.target)
            return abs(s.cx - t.cx) + abs(s.cy - t.cy) if s and t else 0.0
        processing_order = sorted(d.edges, key=_tightness)

        geoms = {}
        inners = {}
        label_boxes = {}
        self._edge_segs = []
        for e in processing_order:
            grp = pairs[frozenset((e.source, e.target))]
            g = self._edge_geom(e, d, grp.index(e), len(grp), fan=fan_of(e),
                                conv=conv_of(e), div=div_of(e))
            geoms[id(e)] = g
            if g is None:
                inners[id(e)] = self._edge_svg_arc(e, self.spec.line_of(e),
                                                    d.nodes[e.source], d.nodes[e.target])
                continue
            for (p, q) in zip(g[1], g[1][1:]):
                self._edge_segs.append((id(e), min(p[0], q[0]) - 1, min(p[1], q[1]) - 1,
                                        max(p[0], q[0]) + 1, max(p[1], q[1]) + 1))
            inner, label_box = self._edge_svg(e, g[0], g[1])
            inners[id(e)] = inner
            if label_box:
                label_boxes[id(e)] = label_box
                if self._router is not None:
                    self._router.avoid_rect(*label_box)

        # SZ-12d lever 1 (reroute) has now had every chance it's going to
        # get — whatever's still sitting under another line at this point
        # genuinely has nowhere clear to go by routing alone. Surfaced for
        # the caller (layout.py's content-aware spacing pass) to try lever
        # 2: widen the gap between the two shapes a short, direct edge like
        # this connects, so there's actually room next render.
        self.overshadowed_edges = []
        for e in d.edges:
            box = label_boxes.get(id(e))
            if box is None:
                continue
            crossed = any(
                other_id != id(e) and box[0] < sx2 and box[2] > sx1 and box[1] < sy2 and box[3] > sy1
                for other_id, sx1, sy1, sx2, sy2 in self._edge_segs
            )
            if crossed:
                self.overshadowed_edges.append(e)

        # Draw in the diagram's own edge order — processing order above is
        # purely an internal scheduling detail and shouldn't reorder the
        # output (DOM order affects paint order and the frontend's click
        # targets).
        for e in d.edges:
            body.append(f'<g data-edge-id="{escape(e.id)}" data-source="{escape(e.source)}" '
                        f'data-target="{escape(e.target)}">' + inners[id(e)] + '</g>')
        for _, n in leaves:
            body.append(f'<g data-node-id="{escape(n.id)}">' + self._node_svg(n) + '</g>')
        title = (f'<text x="{SZ.MARGIN}" y="{SZ.MARGIN - 8}" font-family="{FONT}" font-size="16" '
                 f'font-weight="bold" fill="#222222">{escape(d.title)}</text>')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:.0f}" '
                f'height="{canvas_h:.0f}" viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}" '
                f'font-family="{FONT}">'
                f'<defs>{"".join(self.defs.values())}</defs>'
                f'<rect width="100%" height="100%" fill="white"/>'
                + title + ''.join(body) + '</svg>')
