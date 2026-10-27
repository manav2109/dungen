"""Tests for the minimum-connector-gap nudge (app/main.py): dragging a node
close to one it's directly linked to, or linking two nodes that already sit
close together, must leave at least MIN_EDGE_GAP of clearance so the edge
router never has to fall back to its dip-under reroute."""
from __future__ import annotations

from app.main import MIN_EDGE_GAP


def _blank_session(client, headers) -> str:
    r = client.post('/api/blank', json={}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()['session_id']


def _create_node(client, headers, session_id, x, y, label):
    r = client.post(
        '/api/node/create',
        json={'session_id': session_id, 'entity_type': 'process', 'label': label, 'x': x, 'y': y},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return next(n for n in r.json()['nodes'] if n['label'] == label)


def _gap(a, b):
    """Face-to-face clearance along whichever axis currently separates them
    (negative if they overlap on both)."""
    hgap = max(a['x'] - (b['x'] + b['w']), b['x'] - (a['x'] + a['w']))
    vgap = max(a['y'] - (b['y'] + b['h']), b['y'] - (a['y'] + a['h']))
    return max(hgap, vgap)


def test_get_diagram_returns_current_state_without_relayout(client, auth_headers):
    """GET /api/diagram/{session_id} must return exactly what's there — it's
    what restores the canvas after a page reload — not run a fresh layout
    pass that would discard a manually dragged position."""
    headers = auth_headers
    session_id = _blank_session(client, headers)
    a = _create_node(client, headers, session_id, 100, 100, 'A')
    r = client.post(
        '/api/reposition',
        json={'session_id': session_id, 'node_id': a['id'], 'x': 777, 'y': 888},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    r = client.get(f'/api/diagram/{session_id}', headers=headers)
    assert r.status_code == 200, r.text
    node = next(n for n in r.json()['nodes'] if n['id'] == a['id'])
    assert node['x'] == 777
    assert node['y'] == 888


def test_get_diagram_404s_for_unknown_session(client, auth_headers):
    r = client.get('/api/diagram/not-a-real-session', headers=auth_headers)
    assert r.status_code == 404


def test_reposition_near_connected_node_keeps_minimum_gap(client, auth_headers):
    headers = auth_headers
    session_id = _blank_session(client, headers)
    a = _create_node(client, headers, session_id, 100, 100, 'A')
    b = _create_node(client, headers, session_id, 500, 100, 'B')
    r = client.post(
        '/api/edge/create',
        json={'session_id': session_id, 'source_id': a['id'], 'target_id': b['id'], 'relation_type': 'association'},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    # drag B in right next to A
    r = client.post(
        '/api/reposition',
        json={'session_id': session_id, 'node_id': b['id'], 'x': a['x'] + a['w'] + 5, 'y': a['y']},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    nodes = {n['id']: n for n in r.json()['nodes']}
    assert _gap(nodes[a['id']], nodes[b['id']]) >= MIN_EDGE_GAP - 1e-6


def test_reposition_onto_connected_node_keeps_minimum_gap(client, auth_headers):
    """Dragging B to fully overlap A (the reproduced bug) still ends with a
    clean gap, not just "not technically overlapping"."""
    headers = auth_headers
    session_id = _blank_session(client, headers)
    a = _create_node(client, headers, session_id, 100, 100, 'A')
    b = _create_node(client, headers, session_id, 500, 100, 'B')
    client.post(
        '/api/edge/create',
        json={'session_id': session_id, 'source_id': a['id'], 'target_id': b['id'], 'relation_type': 'association'},
        headers=headers,
    )

    r = client.post(
        '/api/reposition',
        json={'session_id': session_id, 'node_id': b['id'], 'x': a['x'] + 10, 'y': a['y']},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    nodes = {n['id']: n for n in r.json()['nodes']}
    assert _gap(nodes[a['id']], nodes[b['id']]) >= MIN_EDGE_GAP - 1e-6


def test_reposition_unconnected_node_is_left_alone(client, auth_headers):
    """No edge between A and B -> free to sit as close as the user wants."""
    headers = auth_headers
    session_id = _blank_session(client, headers)
    a = _create_node(client, headers, session_id, 100, 100, 'A')
    b = _create_node(client, headers, session_id, 500, 100, 'B')

    target_x, target_y = a['x'] + 5, a['y']
    r = client.post(
        '/api/reposition',
        json={'session_id': session_id, 'node_id': b['id'], 'x': target_x, 'y': target_y},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    moved = next(n for n in r.json()['nodes'] if n['id'] == b['id'])
    assert (moved['x'], moved['y']) == (target_x, target_y)


def test_connecting_two_close_nodes_pushes_target_clear(client, auth_headers):
    """The gap can also start out too small at connect-time, not just from a
    later drag — e.g. the user draws two shapes close, then wires them up."""
    headers = auth_headers
    session_id = _blank_session(client, headers)
    a = _create_node(client, headers, session_id, 100, 100, 'A')
    b = _create_node(client, headers, session_id, a['x'] + a['w'] + 5, a['y'], 'B')

    r = client.post(
        '/api/edge/create',
        json={'session_id': session_id, 'source_id': a['id'], 'target_id': b['id'], 'relation_type': 'association'},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    nodes = {n['id']: n for n in r.json()['nodes']}
    assert _gap(nodes[a['id']], nodes[b['id']]) >= MIN_EDGE_GAP - 1e-6


def test_loading_a_workbook_keeps_nested_children_inside_their_container(client, auth_headers):
    """Regression: the initial-layout spacing pass (_space_connected_nodes,
    run right after /api/sample's layout() call) must not touch nested
    children — it once did, and on a workbook with lots of cross-container
    edges (S1: 6 domains of ~16 systems each, 98 of its 118 edges connect
    children of *different* domains) that pushed children around in
    absolute coordinates without their container resizing to match, so
    they ended up partly outside it — every sample that wasn't a handful of
    unparented boxes came out visibly broken."""
    r = client.post('/api/sample', json={'name': 'S1_integration_landscape.xlsx'}, headers=auth_headers)
    assert r.status_code == 200, r.text
    nodes = {n['id']: n for n in r.json()['nodes']}
    assert any(n['parent'] for n in nodes.values()), 'fixture expected to have nested nodes'
    for n in nodes.values():
        if not n['parent']:
            continue
        p = nodes[n['parent']]
        assert n['x'] >= p['x'] - 1e-6, f"{n['id']} left edge outside {n['parent']}"
        assert n['y'] >= p['y'] - 1e-6, f"{n['id']} top edge outside {n['parent']}"
        assert n['x'] + n['w'] <= p['x'] + p['w'] + 1e-6, f"{n['id']} right edge outside {n['parent']}"
        assert n['y'] + n['h'] <= p['y'] + p['h'] + 1e-6, f"{n['id']} bottom edge outside {n['parent']}"
