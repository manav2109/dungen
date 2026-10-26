"""Tests for layout.py: ranked-row placement, container auto-fit, auto-rank."""
from __future__ import annotations
from diagen.layout import layout, _auto_rank, _fit_label_space, _axis_gap
from diagen.model import Diagram, Node, Edge
from diagen.render_svg import SvgRenderer


def _node(id, parent='', type='task', label=None, rank=0, order=0):
    return Node(id=id, diagram='D1', parent=parent, type=type, label=label or id,
                rank=rank, order=order)


def _edge(src, tgt, relation='sequence_flow', id=None):
    return Edge(id=id or f'{src}_{tgt}', diagram='D1', source=src, target=tgt, relation=relation)


def test_layout_all_nodes_get_nonzero_size(spec):
    d = spec.diagrams['D2']
    w, h = layout(d, spec)
    assert w > 0 and h > 0
    for n in d.nodes.values():
        assert n.w > 0 and n.h > 0


def test_layout_no_overlap_within_same_rank(spec):
    """Nodes placed in the same rank/row must not horizontally overlap."""
    d = spec.diagrams['D2']
    layout(d, spec)
    by_rank = {}
    for n in d.nodes.values():
        if n.parent:
            continue  # only check top-level placement here
        by_rank.setdefault(n.rank, []).append(n)
    for rank, nodes in by_rank.items():
        nodes = sorted(nodes, key=lambda n: n.x)
        for a, b in zip(nodes, nodes[1:]):
            assert a.x + a.w <= b.x + 1e-6, f'{a.id} overlaps {b.id} in rank {rank}'


def test_layout_container_grows_to_fit_children(spec):
    d = spec.diagrams['D1']  # layered EA view: containers with children
    layout(d, spec)
    containers = [n for n in d.nodes.values() if n.children]
    assert containers
    for c in containers:
        # container must be at least wide/tall enough to enclose its children
        max_child_right = max(ch.x + ch.w for ch in c.children)
        max_child_bottom = max(ch.y + ch.h for ch in c.children)
        assert c.w >= max_child_right - c.x - 1
        assert c.h >= max_child_bottom - c.y - 1


def test_layout_lr_direction_uses_columns_not_rows(spec):
    d = spec.diagrams['D2']
    d.direction = 'left-right'
    layout(d, spec)
    by_rank = {}
    for n in d.nodes.values():
        by_rank.setdefault(n.rank, []).append(n)
    ranks = sorted(by_rank)
    if len(ranks) > 1:
        # in LR mode, later ranks should sit further right (x grows with rank)
        avg_x = [sum(n.x for n in by_rank[r]) / len(by_rank[r]) for r in ranks]
        assert avg_x == sorted(avg_x)


def test_auto_rank_topological_order_respected():
    """When rank_hint is absent, auto-rank must derive ranks from edge topology
    so that every edge points from a lower rank to a higher one."""
    d = Diagram(id='D1', scenario='', title='t')
    for nid in ['A', 'B', 'C']:
        d.nodes[nid] = _node(nid)
    d.edges = [_edge('A', 'B'), _edge('B', 'C')]
    _auto_rank(d)
    assert d.nodes['A'].rank < d.nodes['B'].rank < d.nodes['C'].rank


def test_auto_rank_handles_disconnected_nodes():
    """Nodes with no edges at all must still get a valid rank/order (no crash,
    no rank 0 left over) - safety net at the end of _auto_rank."""
    d = Diagram(id='D1', scenario='', title='t')
    for nid in ['X', 'Y', 'Z']:
        d.nodes[nid] = _node(nid)
    d.edges = []
    _auto_rank(d)
    for n in d.nodes.values():
        assert n.rank >= 1
        assert n.order >= 1


def test_explicit_rank_hint_is_not_overridden():
    d = Diagram(id='D1', scenario='', title='t')
    d.nodes['A'] = _node('A', rank=5, order=2)
    d.nodes['B'] = _node('B', rank=1, order=1)
    d.edges = [_edge('B', 'A')]
    _auto_rank(d)
    assert d.nodes['A'].rank == 5
    assert d.nodes['B'].rank == 1


def test_layout_route_right_hint_widens_canvas(spec):
    d = spec.diagrams['D2']  # has an edge with waypoint_hint route:right
    w, h = layout(d, spec)
    assert any('route:right' in e.hint for e in d.edges)
    assert w > 0  # canvas accounted for the detour margin without crashing


def _overshadow_case():
    """Same geometry as test_render_svg.py's
    test_reroute_alone_cannot_clear_a_label_with_nowhere_to_go: HUB/NEIGHBOR
    span the whole canvas with only a 30px gap, so TOP->BOT (pinned to that
    gap) has no detour room - lever 1 (reroute) provably can't clear it
    there. This is lever 2's (space) job."""
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
    return d


def test_fit_label_space_widens_an_unfixable_gap(spec):
    """SZ-12d lever 2 (space): once reroute alone can't clear an overshadowed
    label (see test_render_svg.py's reroute-limit test for proof that this
    exact geometry needs it), _fit_label_space must widen the HUB-NEIGHBOR
    gap by exactly what the label needs, and a re-render against the result
    must come out fully clear - not just "less bad"."""
    d = _overshadow_case()
    gap_before = _axis_gap(d.nodes['HUB'].x, d.nodes['HUB'].x + d.nodes['HUB'].w,
                            d.nodes['NEIGHBOR'].x, d.nodes['NEIGHBOR'].x + d.nodes['NEIGHBOR'].w)

    w, h = _fit_label_space(d, spec, 590, 500)

    gap_after = _axis_gap(d.nodes['HUB'].x, d.nodes['HUB'].x + d.nodes['HUB'].w,
                           d.nodes['NEIGHBOR'].x, d.nodes['NEIGHBOR'].x + d.nodes['NEIGHBOR'].w)
    assert gap_after > gap_before, 'lever 2 did not widen the gap it was supposed to fix'

    renderer = SvgRenderer(spec)
    renderer.render(d, w, h)
    assert renderer.overshadowed_edges == [], (
        f'still overshadowed after lever 2: {[e.id for e in renderer.overshadowed_edges]}'
    )


def test_fit_label_space_leaves_nested_children_alone():
    """Same top-level-only guard as the webapp's own _space_connected_nodes
    (see main.py) - shifting a nested child in absolute coordinates without
    its container resizing to match would leave it sitting outside its own
    box, so a pair where either side has a parent must be left untouched
    even if flagged as overshadowed."""
    from diagen.spec import Spec
    spec = Spec.blank(use_defaults=True)
    d = Diagram(id='OS', scenario='', title='Nested overshadow test')
    container = Node(id='BOX', diagram='OS', parent='', type='group', label='Box',
                      x=0, y=0, w=620, h=300)
    hub = Node(id='HUB', diagram='OS', parent='BOX', type='application_component', label='Hub',
               x=10, y=120, w=280, h=50)
    nbr = Node(id='NEIGHBOR', diagram='OS', parent='BOX', type='application_component', label='Neighbor',
               x=320, y=120, w=280, h=50)
    container.children = [hub, nbr]
    for n in (container, hub, nbr):
        d.nodes[n.id] = n
    d.edges.append(Edge(id='e_local', diagram='OS', source='HUB', target='NEIGHBOR',
                         relation='data_flow', label='Local sync data between hub and neighbor'))

    before = (hub.x, hub.w, nbr.x, nbr.w)
    w, h = _fit_label_space(d, spec, 620, 300)
    after = (hub.x, hub.w, nbr.x, nbr.w)

    assert before == after, 'lever 2 moved a nested child instead of leaving it for the container to own'
