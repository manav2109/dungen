"""Tests for render_svg.py: valid SVG output, labels present, edges drawn."""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from diagen.layout import layout
from diagen.model import Diagram, Edge, Node
from diagen.render_svg import SvgRenderer


def _render(spec, diagram_id):
    d = spec.diagrams[diagram_id]
    w, h = layout(d, spec)
    return SvgRenderer(spec).render(d, w, h), d


def _edge_path_points(svg: str, edge_id: str) -> list[tuple[float, float]]:
    g = re.search(rf'data-edge-id="{re.escape(edge_id)}"[^>]*>(.*?)</g>', svg, re.DOTALL)
    assert g, f'edge {edge_id} not found in svg'
    path = re.search(r'<path d="([^"]+)"', g.group(1))
    assert path, f'no path drawn for edge {edge_id}'
    return [(float(x), float(y)) for x, y in re.findall(r'(-?[\d.]+),(-?[\d.]+)', path.group(1))]


def test_render_produces_well_formed_xml(spec):
    svg, _ = _render(spec, 'D2')
    root = ET.fromstring(svg)  # raises if not well-formed
    assert root.tag.endswith('svg')


def test_render_includes_every_node_label(spec):
    svg, d = _render(spec, 'D2')
    for n in d.nodes.values():
        assert n.label in svg or all(part in svg for part in n.lines), \
            f'label for {n.id} missing from SVG output'


def test_render_escapes_special_characters(spec):
    d = spec.diagrams['D2']
    n = next(iter(d.nodes.values()))
    n.label = 'A & B <script>'
    n.lines = [n.label]
    svg = SvgRenderer(spec).render(d, 800, 600)
    assert '<script>' not in svg
    assert '&amp;' in svg


def test_render_draws_a_path_per_edge(spec):
    svg, d = _render(spec, 'D2')
    assert svg.count('<path') >= len(d.edges)


def test_render_title_present(spec):
    svg, d = _render(spec, 'D2')
    assert d.title in svg


def test_render_erd_diagram_shows_row_lists(spec):
    """D5 is the ERD scenario - row-list shapes must render each attribute row."""
    if 'D5' not in spec.diagrams or not spec.diagrams['D5'].nodes:
        return  # sample data optional in some spec workbook variants
    svg, d = _render(spec, 'D5')
    row_nodes = [n for n in d.nodes.values() if spec.shape_of(n).auto == 'rows']
    assert row_nodes
    for n in row_nodes:
        for r in n.rows():
            assert r.split('(')[0].strip() in svg


def test_converging_edges_from_different_sources_spread_across_target_face(spec):
    """SZ-12c: two different (single-edge) sources landing on the same side
    of one target must not have their arrowheads clustering near the same
    point. Both sources are sized here to individually overlap the target's
    *entire* vertical span, so each edge's own shared_y computation would
    independently land at the target's centre — reproducing the clustering
    bug — unless the horizontal branch spreads them apart."""
    d = Diagram(id='CONV', scenario='', title='Convergence test')
    src_top = Node(id='S1', diagram='CONV', parent='', type='business_actor', label='Top source',
                   x=0, y=0, w=120, h=400)
    src_bot = Node(id='S2', diagram='CONV', parent='', type='business_actor', label='Bottom source',
                   x=0, y=20, w=120, h=300)
    target = Node(id='T', diagram='CONV', parent='', type='application_component', label='Hub',
                  x=400, y=50, w=150, h=150)
    for n in (src_top, src_bot, target):
        d.nodes[n.id] = n
    d.edges.append(Edge(id='e1', diagram='CONV', source='S1', target='T', relation='association'))
    d.edges.append(Edge(id='e2', diagram='CONV', source='S2', target='T', relation='association'))

    svg = SvgRenderer(spec).render(d, 700, 500)

    e1_arrival_y = _edge_path_points(svg, 'e1')[-1][1]
    e2_arrival_y = _edge_path_points(svg, 'e2')[-1][1]
    assert abs(e1_arrival_y - e2_arrival_y) > 30, (
        f'arrowheads landed within {abs(e1_arrival_y - e2_arrival_y):.0f}px of each other '
        f'({e1_arrival_y=}, {e2_arrival_y=}) instead of spreading across the target face'
    )


def test_diverging_edges_to_same_side_targets_use_separate_jog_lanes(spec):
    """SZ-12c continued: spreading the entry/exit point isn't enough on its
    own — a hub feeding several targets that all sit at roughly the same x
    (e.g. a stack of destination boxes on the diagram's right edge) still had
    every one of those edges jog at the same (p1.x+p2.x)/2, since p1.x (the
    shared source's own exit face) is identical for all of them. The risers
    then ran on top of each other for most of their length even though the
    endpoints themselves were spread. Each edge's jog must land in its own
    lane, not just its own entry/exit point."""
    d = Diagram(id='DIV', scenario='', title='Divergence test')
    hub = Node(id='HUB', diagram='DIV', parent='', type='application_component', label='Hub',
               x=0, y=0, w=120, h=300)
    t1 = Node(id='T1', diagram='DIV', parent='', type='business_actor', label='Target 1',
              x=400, y=0, w=120, h=40)
    t2 = Node(id='T2', diagram='DIV', parent='', type='business_actor', label='Target 2',
              x=400, y=150, w=120, h=40)
    t3 = Node(id='T3', diagram='DIV', parent='', type='business_actor', label='Target 3',
              x=400, y=300, w=120, h=40)
    for n in (hub, t1, t2, t3):
        d.nodes[n.id] = n
    # orthogonal routing, not 'association' (which routes straight line-to-point
    # and would collapse the jog this test is checking for by design)
    for i, t in enumerate((t1, t2, t3), start=1):
        d.edges.append(Edge(id=f'e{i}', diagram='DIV', source='HUB', target=t.id, relation='data_flow'))

    svg = SvgRenderer(spec).render(d, 700, 500)

    jog_xs = []
    for eid in ('e1', 'e2', 'e3'):
        pts = _edge_path_points(svg, eid)
        assert len(pts) >= 3, f'{eid}: expected a jogged path, got a straight line {pts}'
        jog_xs.append(pts[1][0])
    assert len(set(jog_xs)) == 3 and max(jog_xs) - min(jog_xs) > 40, (
        f'jogs landed at {jog_xs} instead of three separate lanes'
    )


def test_same_height_neighbour_is_not_pulled_into_a_far_hub_fan(spec):
    """A hub with both a close same-height "neighbour" link and genuine
    long-range fan-out edges must not fold the neighbour link into the fan
    group just because they share a source. That forced a short, simple
    connection into a jog — splitting one long segment into two short ones,
    which starves whatever label is on it of wrap width (the actual bug
    behind a 'two adjacent boxes with a long edge label between them' case:
    the label was fine once the edge stopped being jogged). A near-zero
    source/target height difference means there's nothing to fan away from —
    it should render as the plain straight line it would without any other
    edges in the picture."""
    d = Diagram(id='MIX', scenario='', title='Mixed neighbour + fan test')
    hub = Node(id='HUB', diagram='MIX', parent='', type='application_component', label='Hub',
               x=0, y=0, w=120, h=20)
    near = Node(id='NEAR', diagram='MIX', parent='', type='business_actor', label='Neighbour',
                x=300, y=0, w=120, h=20)
    far1 = Node(id='FAR1', diagram='MIX', parent='', type='business_actor', label='Far 1',
                x=300, y=300, w=120, h=20)
    far2 = Node(id='FAR2', diagram='MIX', parent='', type='business_actor', label='Far 2',
                x=300, y=600, w=120, h=20)
    for n in (hub, near, far1, far2):
        d.nodes[n.id] = n
    d.edges.append(Edge(id='e_near', diagram='MIX', source='HUB', target='NEAR', relation='data_flow'))
    d.edges.append(Edge(id='e_far1', diagram='MIX', source='HUB', target='FAR1', relation='data_flow'))
    d.edges.append(Edge(id='e_far2', diagram='MIX', source='HUB', target='FAR2', relation='data_flow'))

    svg = SvgRenderer(spec).render(d, 700, 800)

    near_pts = _edge_path_points(svg, 'e_near')
    assert len(near_pts) == 2, (
        f'the same-height neighbour link got jogged into the far hub fan: {near_pts}'
    )
    far1_pts = _edge_path_points(svg, 'e_far1')
    far2_pts = _edge_path_points(svg, 'e_far2')
    assert len(far1_pts) >= 3 and len(far2_pts) >= 3, 'the genuine fan-out edges should still jog'


def test_fanned_arrival_stays_clear_of_a_rounded_corner(spec):
    """A proportional fan/div/conv spread places group members evenly across
    a target's (or source's) whole face, including right up to its very
    ends - but a rounded shape's visible border curves away from the
    bounding box before the box's own edge ends there. An extreme member
    (index 0, or the last index) can land inside that curve's reach: on the
    box's face mathematically, but in the gap before the actual drawn
    border, so the connector looks like it stops short instead of touching
    the shape. TGT is tall enough, and the group large enough, that both
    extremes would fall inside an 8px corner radius without the clamp."""
    d = Diagram(id='CORNER', scenario='', title='Corner clearance test')
    tgt = Node(id='TGT', diagram='CORNER', parent='', type='application_component', label='Target',
               x=400, y=150, w=200, h=200)
    d.nodes['TGT'] = tgt
    n = 30
    for i in range(n):
        sid = f'S{i}'
        d.nodes[sid] = Node(id=sid, diagram='CORNER', parent='', type='business_actor', label=sid,
                             x=0, y=150 + i * 7, w=120, h=5)
        d.edges.append(Edge(id=f'e{i}', diagram='CORNER', source=sid, target='TGT', relation='data_flow'))

    svg = SvgRenderer(spec).render(d, 700, 700)

    for eid in ('e0', f'e{n - 1}'):
        pts = _edge_path_points(svg, eid)
        arrival_y = pts[-1][1]
        dist_from_top = arrival_y - tgt.y
        dist_from_bottom = (tgt.y + tgt.h) - arrival_y
        assert min(dist_from_top, dist_from_bottom) >= 8, (
            f'{eid} arrives at y={arrival_y}, only '
            f'{min(dist_from_top, dist_from_bottom):.1f}px from a corner - inside the '
            f'rounded-corner cutout, where the line would miss the visible border'
        )


def test_arrowhead_gets_a_real_straight_run_not_an_elbow_on_top_of_it(spec):
    """An edge whose route dips under an obstacle (down, across, back up,
    then a short hop into the target) used to pin that last hop at exactly
    8px - the router's fixed stub clearance - landing the arrowhead right on
    top of the elbow that precedes it instead of a clean approach. OBST sits
    squarely between SRC and DST at the same height, forcing exactly that
    dip. The final leg into DST must now read as a real straight run."""
    d = Diagram(id='APPR', scenario='', title='Approach length test')
    src = Node(id='SRC', diagram='APPR', parent='', type='application_component', label='Src',
               x=0, y=100, w=100, h=50)
    obst = Node(id='OBST', diagram='APPR', parent='', type='application_component', label='Obstacle',
                x=200, y=80, w=100, h=90)
    dst = Node(id='DST', diagram='APPR', parent='', type='application_component', label='Dst',
               x=400, y=100, w=100, h=50)
    for n in (src, obst, dst):
        d.nodes[n.id] = n
    d.edges.append(Edge(id='e1', diagram='APPR', source='SRC', target='DST', relation='data_flow', label='x'))

    svg = SvgRenderer(spec).render(d, 600, 300)

    pts = _edge_path_points(svg, 'e1')
    assert len(pts) >= 3, f'expected a dip-under route, got {pts}'
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    final_len = abs(x2 - x1) + abs(y2 - y1)
    assert final_len >= 20, (
        f'arrowhead approach is only {final_len:.0f}px - too short to read as a clean '
        f'arrival instead of sitting on top of the elbow before it: {pts}'
    )


def test_reroute_alone_cannot_clear_a_label_with_nowhere_to_go(spec):
    """SZ-12d lever 1 (reroute): when a labeled edge's own two shapes leave
    no slack anywhere - no room to jog sideways, nothing above/below to
    detour through - re-routing the *other* edge that crosses it can't
    help, because there's no alternative corridor to route into. HUB and
    NEIGHBOR span the entire canvas width with only a 30px gap between
    them, so TOP->BOT (pinned to that same gap, boxed in on both sides)
    has no detour available at any cost. This is the case lever 2 (space,
    tested in test_layout.py) exists for - this test pins down that lever
    1 genuinely cannot resolve it alone, so a future change can't silently
    make lever 2 look unnecessary by fixing this geometry via reroute."""
    d = Diagram(id='OS', scenario='', title='Overshadow test')
    hub = Node(id='HUB', diagram='OS', parent='', type='application_component', label='Hub',
               x=0, y=200, w=280, h=50)
    nbr = Node(id='NEIGHBOR', diagram='OS', parent='', type='application_component', label='Neighbor',
               x=310, y=200, w=280, h=50)
    top = Node(id='TOP', diagram='OS', parent='', type='application_component', label='Top',
               x=280, y=0, w=30, h=40)
    bot = Node(id='BOT', diagram='OS', parent='', type='application_component', label='Bottom',
               x=280, y=450, w=30, h=40)
    for n in (hub, nbr, top, bot):
        d.nodes[n.id] = n
    d.edges.append(Edge(id='e_local', diagram='OS', source='HUB', target='NEIGHBOR',
                         relation='data_flow', label='Local sync data between hub and neighbor'))
    d.edges.append(Edge(id='e_vert', diagram='OS', source='TOP', target='BOT',
                         relation='data_flow', label='V'))

    renderer = SvgRenderer(spec)
    renderer.render(d, 590, 500)   # canvas matches HUB..NEIGHBOR exactly - zero slack to detour into

    assert any(e.id == 'e_local' for e in renderer.overshadowed_edges), (
        'expected this tight-gap case to still be overshadowed after reroute alone - '
        'if it is not, either the geometry no longer reproduces the no-detour-room case, '
        'or reroute has started resolving something it structurally cannot'
    )


def test_edges_sharing_an_id_still_render_their_own_distinct_geometry(spec):
    """Regression: author data can't be trusted to give every edge a unique
    (or even non-empty) id — an Edges sheet with no edge_id column leaves
    every row id=''. Internally this renderer used e.id as a dict key for
    per-edge geometry (geoms) and crossing-detection (_edge_segs); with
    several edges sharing one id, each one computed just overwrote the
    previous entry, so EVERY edge in the diagram rendered as a copy of
    whichever was processed last — not just the colliding ones. All four
    edges here share id='' on purpose; each must still end up with its own
    path connecting its own actual source and target."""
    d = Diagram(id='DUP', scenario='', title='Duplicate id test')
    positions = {'A': (0, 0), 'B': (300, 0), 'C': (0, 300), 'D': (300, 300),
                 'E': (0, 600), 'F': (300, 600)}
    for nid, (x, y) in positions.items():
        d.nodes[nid] = Node(id=nid, diagram='DUP', parent='', type='business_actor', label=nid,
                             x=x, y=y, w=120, h=40)
    pairs = [('A', 'B'), ('C', 'D'), ('E', 'F')]
    for src, tgt in pairs:
        d.edges.append(Edge(id='', diagram='DUP', source=src, target=tgt, relation='data_flow'))

    svg = SvgRenderer(spec).render(d, 700, 800)

    groups = re.findall(r'<g data-edge-id="[^"]*" data-source="([^"]*)" data-target="([^"]*)">(.*?)</g>',
                         svg, re.DOTALL)
    assert len(groups) == len(pairs)
    seen_paths = set()
    for (src, tgt, inner), (want_src, want_tgt) in zip(groups, pairs):
        assert (src, tgt) == (want_src, want_tgt)
        path = re.search(r'<path d="([^"]+)"', inner).group(1)
        seen_paths.add(path)
        sx, sy = positions[src]
        # the path must actually start near its own source box, not some
        # other edge's — this is what silently broke before the fix
        first_x, first_y = map(float, re.match(r'M(-?[\d.]+),(-?[\d.]+)', path).groups())
        assert abs(first_x - sx) < 150 and abs(first_y - sy) < 150, (
            f'{src}->{tgt} path {path} does not start near its own source box ({sx},{sy})'
        )
    assert len(seen_paths) == len(pairs), f'expected {len(pairs)} distinct paths, got {seen_paths}'
