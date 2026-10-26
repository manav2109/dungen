"""Tests for diagen/clusters.py: connected-components grouping of a single
Diagram's nodes into the separate logical diagrams a user may have
arranged on one canvas, plus best-effort orphan-to-cluster suggestions."""
from __future__ import annotations
from diagen.model import Diagram, Node, Edge
from diagen.clusters import find_clusters


def _node(id, x, y, w=100.0, h=50.0, parent='', label=None):
    return Node(id=id, diagram='D1', parent=parent, type='task', label=label or id, x=x, y=y, w=w, h=h)


def _edge(src, tgt, id=None):
    return Edge(id=id or f'{src}_{tgt}', diagram='D1', source=src, target=tgt, relation='association')


def _diagram(nodes, edges):
    d = Diagram(id='D1', scenario='', title='t')
    for n in nodes:
        d.nodes[n.id] = n
    d.edges = edges
    return d


def test_two_disconnected_clusters_separated():
    # A-B far left, C-D far right, no edges between the two pairs.
    d = _diagram(
        [_node('A', 0, 0), _node('B', 0, 200), _node('C', 2000, 0), _node('D', 2000, 200)],
        [_edge('A', 'B'), _edge('C', 'D')],
    )
    result = find_clusters(d)
    assert len(result['clusters']) == 2
    assert result['orphans'] == []
    groups = {frozenset(c['top_level_ids']) for c in result['clusters']}
    assert frozenset({'A', 'B'}) in groups
    assert frozenset({'C', 'D'}) in groups


def test_orphan_close_to_one_cluster_is_confident():
    d = _diagram(
        [_node('A', 0, 0), _node('B', 200, 0), _node('X', 100, 150)],
        [_edge('A', 'B')],
    )
    result = find_clusters(d)
    assert len(result['clusters']) == 1
    assert len(result['orphans']) == 1
    orphan = result['orphans'][0]
    assert orphan['node_id'] == 'X'
    assert orphan['suggested_cluster_id'] == result['clusters'][0]['id']
    assert orphan['confident'] is True


def test_orphan_equidistant_between_two_clusters_is_not_confident():
    d = _diagram(
        [
            _node('A', 0, 0), _node('B', 100, 0),       # cluster 1, around x=0-200
            _node('C', 2000, 0), _node('D', 2100, 0),   # cluster 2, around x=2000-2200
            _node('X', 1050, 500),                       # dead centre between them
        ],
        [_edge('A', 'B'), _edge('C', 'D')],
    )
    result = find_clusters(d)
    assert len(result['clusters']) == 2
    orphan = next(o for o in result['orphans'] if o['node_id'] == 'X')
    assert orphan['confident'] is False, 'equidistant orphan must not be silently assigned'


def test_orphan_far_from_everything_is_not_confident():
    d = _diagram(
        [_node('A', 0, 0), _node('B', 100, 0), _node('X', 50_000, 50_000)],
        [_edge('A', 'B')],
    )
    result = find_clusters(d)
    orphan = result['orphans'][0]
    assert orphan['confident'] is False


def test_single_connected_diagram_no_orphans():
    d = _diagram(
        [_node('A', 0, 0), _node('B', 200, 0), _node('C', 400, 0)],
        [_edge('A', 'B'), _edge('B', 'C')],
    )
    result = find_clusters(d)
    assert len(result['clusters']) == 1
    assert result['orphans'] == []
    assert set(result['clusters'][0]['top_level_ids']) == {'A', 'B', 'C'}


def test_nested_children_fold_into_their_top_level_ancestor():
    """A child's own edges still count toward connectivity, but the child
    itself is never a separate cluster member or orphan — same top-level-
    only boundary the rest of the layout code uses."""
    parent1 = _node('P1', 0, 0, w=300, h=200)
    child1 = _node('C1', 10, 10, parent='P1')
    parent2 = _node('P2', 1000, 0, w=300, h=200)
    child2 = _node('C2', 1010, 10, parent='P2')
    parent1.children = [child1]
    parent2.children = [child2]
    d = _diagram([parent1, child1, parent2, child2], [_edge('C1', 'C2')])
    result = find_clusters(d)
    # The child-to-child edge should have joined P1 and P2 into one cluster.
    assert len(result['clusters']) == 1
    cluster = result['clusters'][0]
    assert set(cluster['top_level_ids']) == {'P1', 'P2'}
    assert set(cluster['node_ids']) == {'P1', 'C1', 'P2', 'C2'}
    assert result['orphans'] == []


def test_fully_disconnected_nodes_are_all_orphans_with_no_clusters():
    d = _diagram([_node('A', 0, 0), _node('B', 500, 0)], [])
    result = find_clusters(d)
    assert result['clusters'] == []
    assert {o['node_id'] for o in result['orphans']} == {'A', 'B'}
    assert all(o['suggested_cluster_id'] is None and o['confident'] is False for o in result['orphans'])


def test_empty_diagram_returns_empty():
    d = _diagram([], [])
    assert find_clusters(d) == {'clusters': [], 'orphans': []}
