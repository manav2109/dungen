"""Tests for the PPTX export endpoints (app/main.py): cluster detection,
settings round-tripping through project save/load, and generating an
actual .pptx file from client-supplied PNG bytes."""
from __future__ import annotations
import base64
import io
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


# 1x1 transparent PNG — a real, minimal, valid PNG, not a placeholder string.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


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


def test_detect_finds_two_clusters(client, auth_headers):
    headers = auth_headers
    session_id = _blank_session(client, headers)
    a = _create_node(client, headers, session_id, 0, 0, 'A')
    b = _create_node(client, headers, session_id, 200, 0, 'B')
    c = _create_node(client, headers, session_id, 3000, 0, 'C')
    r = client.post(
        '/api/edge/create',
        json={'session_id': session_id, 'source_id': a['id'], 'target_id': b['id'], 'relation_type': 'association'},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    r = client.post('/api/export/pptx/detect', json={'session_id': session_id}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body['clusters']) == 1
    assert set(body['clusters'][0]['top_level_ids']) == {a['id'], b['id']}
    assert len(body['orphans']) == 1
    assert body['orphans'][0]['node_id'] == c['id']


def test_generate_returns_a_valid_pptx_with_embedded_image(client, auth_headers):
    headers = auth_headers
    payload = {
        'filename': 'My Diagram',
        'slides': [
            {
                'slide_number': 1,
                'placements': [
                    {'image_png_base64': _TINY_PNG_B64, 'x': 1.0, 'y': 1.0, 'w': 4.0, 'h': 3.0},
                ],
            },
        ],
    }
    r = client.post('/api/export/pptx/generate', json=payload, headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers['content-type'] == (
        'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    )
    assert 'My Diagram.pptx' in r.headers['content-disposition']

    prs = Presentation(io.BytesIO(r.content))
    slides = list(prs.slides)
    assert len(slides) == 1
    pictures = [s for s in slides[0].shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert len(pictures) == 1
    # Embedded, not linked: the image bytes live inside the pptx's own
    # media part, round-trippable without any external file reference.
    image_part = pictures[0].image
    assert image_part.blob == base64.b64decode(_TINY_PNG_B64)


def test_generate_places_diagrams_on_requested_slide_numbers(client, auth_headers):
    headers = auth_headers
    payload = {
        'filename': 'multi',
        'slides': [
            {'slide_number': 3, 'placements': [
                {'image_png_base64': _TINY_PNG_B64, 'x': 0.5, 'y': 0.5, 'w': 2.0, 'h': 2.0},
            ]},
            {'slide_number': 1, 'placements': [
                {'image_png_base64': _TINY_PNG_B64, 'x': 0.5, 'y': 0.5, 'w': 2.0, 'h': 2.0},
            ]},
        ],
    }
    r = client.post('/api/export/pptx/generate', json=payload, headers=headers)
    assert r.status_code == 200, r.text
    prs = Presentation(io.BytesIO(r.content))
    slides = list(prs.slides)
    assert len(slides) == 3  # slide 2 created blank, in between
    pics = lambda s: len([sh for sh in s.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE])
    assert pics(slides[0]) == 1
    assert pics(slides[1]) == 0
    assert pics(slides[2]) == 1


def test_generate_rejects_invalid_base64(client, auth_headers):
    headers = auth_headers
    payload = {
        'filename': 'bad',
        'slides': [
            {'slide_number': 1, 'placements': [
                {'image_png_base64': 'not-valid-base64!!', 'x': 0.0, 'y': 0.0, 'w': 1.0, 'h': 1.0},
            ]},
        ],
    }
    r = client.post('/api/export/pptx/generate', json=payload, headers=headers)
    assert r.status_code == 400


def test_filename_with_unsafe_characters_is_sanitized(client, auth_headers):
    headers = auth_headers
    payload = {
        'filename': 'weird/name:with*chars?',
        'slides': [
            {'slide_number': 1, 'placements': [
                {'image_png_base64': _TINY_PNG_B64, 'x': 0.0, 'y': 0.0, 'w': 1.0, 'h': 1.0},
            ]},
        ],
    }
    r = client.post('/api/export/pptx/generate', json=payload, headers=headers)
    assert r.status_code == 200, r.text
    disposition = r.headers['content-disposition']
    assert '/' not in disposition.split('filename=')[1]
    assert ':' not in disposition.split('filename=')[1]


def test_export_settings_round_trip_through_project_save_and_load(client, auth_headers):
    headers = auth_headers
    session_id = _blank_session(client, headers)
    settings = {'slides': [{'slide_number': 1, 'cluster_ids': ['cluster_1']}]}
    r = client.post(
        '/api/export/settings',
        json={'session_id': session_id, 'settings': settings},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    r = client.post(
        '/api/projects/save',
        json={'session_id': session_id, 'name': 'export settings test project'},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    project_id = r.json()['id']

    r = client.post('/api/projects/load', json={'project_id': project_id}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()['export_settings'] == settings


def test_old_format_saved_project_still_loads(client, auth_headers):
    """A project saved before export_settings existed stored the bare spec
    dict at the top level (no "spec" key) — projects_load must still open
    it instead of trying to interpret the whole thing as one node's data."""
    from app import projects as project_store

    headers = auth_headers
    session_id = _blank_session(client, headers)
    _create_node(client, headers, session_id, 0, 0, 'Legacy')

    # Simulate a pre-export-panel row by writing the bare spec dict
    # directly, bypassing the endpoint's new wrapping.
    import app.main as app_main
    session = app_main.store.get(session_id)
    bare_spec_dict = project_store.spec_to_dict(session.spec)
    project_id = project_store.save_project('legacy row', bare_spec_dict, headers_user_id(client, headers))

    r = client.post('/api/projects/load', json={'project_id': project_id}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(n['label'] == 'Legacy' for n in body['nodes'])
    assert body['export_settings'] == {}


def headers_user_id(client, headers):
    r = client.get('/api/auth/me', headers=headers)
    assert r.status_code == 200, r.text
    # /api/auth/me only returns username, not user_id — look it up the same
    # way auth_middleware does, via the token itself.
    from app import auth as auth_store
    token = headers['Authorization'][len('Bearer '):]
    payload = auth_store.verify_token(token)
    return payload['user_id']
