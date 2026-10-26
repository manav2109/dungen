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


def test_layout_container_children_unaffected_by_a_repositioned_container():
    """Every node's (x, y) is local to its own IMMEDIATE parent until
    layout()'s later absolutize() pass cascades each level's position down
    - that's the whole reason absolutize() exists, one level at a time,
    instead of each node already carrying its full ancestry's offset. So
    when OUTER positions INNER as one of its own children, INNER's
    grandchildren (A, B) - expressed relative to INNER, not to OUTER -
    must NOT move at all; only INNER itself does. Regression test for a
    double-counted PAD_C/HEADER_H offset in _layout_container: shifting a
    container's immediate children used the recursive _shift(), which also
    walks into grandchildren - so moving INNER into place as OUTER's child
    ALSO dragged A and B along by that same (PAD_C, HEADER_H), corrupting
    their local-to-INNER coordinates by exactly OUTER's own padding
    amount. Invisible with only one level of nesting - recursing into a
    leaf's empty children list is a no-op - which is exactly why this
    stayed latent until a two-level case surfaced it (a real diagram's
    TAKSY/VPM sub-groups inside its top-level AD container: their own
    children ended up pushed HEADER_H past the sub-group's own,
    correctly-sized box)."""
    from diagen.spec import Spec
    from diagen.layout import _layout_container
    spec = Spec.blank(use_defaults=True)

    def _inner_with_children(parent):
        inner = _node('INNER', parent=parent, type='group', label='Inner')
        a = _node('A', parent='INNER', rank=1, order=1, label='A')
        b = _node('B', parent='INNER', rank=2, order=1, label='B')
        for n in (a, b):
            n.w, n.h = 100.0, 40.0
        inner.children = [a, b]
        return inner, a, b

    # INNER laid out standalone (parent=''), so it's never repositioned by
    # anything above it - this is exactly the computation
    # _layout_container(outer, ...) performs for INNER internally, one
    # recursion level before OUTER ever touches INNER's own (x, y). Since
    # it's deterministic from the same rank/order/w/h inputs, A and B's
    # positions here double as "INNER's children right before OUTER moves
    # INNER" for the nested run below - without needing to call
    # _layout_container on the same nodes twice (which would double-apply
    # the PAD_C/HEADER_H shift itself, independent of the bug under test).
    inner0, a0, b0 = _inner_with_children('')
    d0 = Diagram(id='D1', scenario='', title='t')
    for n in (inner0, a0, b0):
        d0.nodes[n.id] = n
    _layout_container(inner0, spec, False, d0)
    assert (inner0.x, inner0.y) == (0.0, 0.0), 'a standalone container should never reposition itself'

    # Same INNER, now nested one level inside OUTER - single call.
    outer = _node('OUTER', type='group', label='Outer')
    inner, a, b = _inner_with_children('OUTER')
    outer.children = [inner]
    d = Diagram(id='D1', scenario='', title='t')
    for n in (outer, inner, a, b):
        d.nodes[n.id] = n
    _layout_container(outer, spec, False, d)

    # INNER's own movement, purely from OUTER positioning it as a child.
    inner_dx, inner_dy = inner.x - inner0.x, inner.y - inner0.y
    assert inner_dx or inner_dy, 'test is only meaningful if OUTER actually moved INNER'
    for moved, baseline, nid in ((a, a0, 'A'), (b, b0, 'B')):
        dx, dy = moved.x - baseline.x, moved.y - baseline.y
        assert (dx, dy) == (0.0, 0.0), (
            f"{nid} moved by ({dx}, {dy}) just because its container INNER "
            f'moved by ({inner_dx}, {inner_dy}) as OUTER\'s own child - '
            f"it's stored relative to INNER, so it should not have moved at all"
        )


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


def _nested_overshadow_case():
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
    return spec, d, container, hub, nbr


def test_fit_label_space_widens_a_gap_between_contained_siblings():
    """A label squeezed between two shapes that share one immediate parent
    container needs the same fix a top-level pair gets — just with the
    container kept honest about its own size (SZ-15 / `_grow_room`), not
    left untouched the way an ambiguous cross-container pair still is (see
    test_fit_label_space_leaves_different_containers_alone). Without this,
    a label like this one has nowhere to go but overlapping its own two
    shapes (nodes paint over edges, so the overlap shows as missing text,
    not as two things visibly fighting for the same pixels) — exactly the
    'content isn't visible' case a direct top-level pair never has, because
    nothing before this stopped it from ever happening to a contained one."""
    spec, d, container, hub, nbr = _nested_overshadow_case()
    before_w = container.w

    w, h = _fit_label_space(d, spec, 620, 300)

    assert hub.x + hub.w <= nbr.x + 1e-6, 'widening must not just swap which shape overlaps the other'
    assert container.w >= before_w, 'the gap only has room to grow if its container grew too'
    max_child_right = max(c.x + c.w for c in container.children)
    assert container.w >= max_child_right - container.x - 1, \
        'container no longer actually contains the sibling it just helped make room for'

    renderer = SvgRenderer(spec)
    renderer.render(d, w, h)
    assert renderer.overshadowed_edges == [], (
        f'still overshadowed after lever 2: {[e.id for e in renderer.overshadowed_edges]}'
    )


def test_fit_label_space_leaves_different_containers_alone():
    """A pair split across two different containers is left for a human (or
    a future, more ambitious pass) rather than guessed at: unlike a shared
    immediate parent, there's no single obviously-right container for
    `_grow_room` to resize here, so lever 2 stays out of it entirely."""
    spec, d, container, hub, nbr = _nested_overshadow_case()
    other_box = Node(id='BOX2', diagram='OS', parent='', type='group', label='Box 2',
                      x=640, y=0, w=300, h=300)
    d.nodes['BOX2'] = other_box
    nbr.parent = 'BOX2'
    container.children = [hub]
    other_box.children = [nbr]

    before = (hub.x, hub.w, nbr.x, nbr.w, container.w, other_box.w)
    _fit_label_space(d, spec, 940, 300)
    after = (hub.x, hub.w, nbr.x, nbr.w, container.w, other_box.w)

    assert before == after, 'lever 2 touched a pair split across two different containers'
