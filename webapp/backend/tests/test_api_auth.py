"""Auth endpoints + the middleware gating /api/* behind a token."""
from __future__ import annotations


def test_health_is_public(client):
    r = client.get('/api/health')
    assert r.status_code == 200


def test_protected_endpoint_requires_token(client):
    r = client.get('/api/projects')
    assert r.status_code == 401


def test_bogus_token_rejected(client):
    r = client.get('/api/projects', headers={'Authorization': 'Bearer not-a-real-token'})
    assert r.status_code == 401


def test_signup_then_me(client):
    r = client.post('/api/auth/signup', json={'username': 'alice', 'password': 'correcthorse1'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['username'] == 'alice'
    token = body['token']

    r = client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200
    assert r.json() == {'username': 'alice'}


def test_signup_duplicate_username_conflicts(client):
    client.post('/api/auth/signup', json={'username': 'alice', 'password': 'correcthorse1'})
    r = client.post('/api/auth/signup', json={'username': 'alice', 'password': 'somethingelse1'})
    assert r.status_code == 409


def test_signup_rejects_short_password(client):
    r = client.post('/api/auth/signup', json={'username': 'bob', 'password': 'short'})
    assert r.status_code == 400


def test_signup_rejects_bad_username(client):
    r = client.post('/api/auth/signup', json={'username': 'a b!', 'password': 'correcthorse1'})
    assert r.status_code == 400


def test_login_round_trip(client):
    client.post('/api/auth/signup', json={'username': 'carol', 'password': 'correcthorse1'})
    r = client.post('/api/auth/login', json={'username': 'carol', 'password': 'correcthorse1'})
    assert r.status_code == 200
    assert r.json()['username'] == 'carol'


def test_login_wrong_password(client):
    client.post('/api/auth/signup', json={'username': 'dave', 'password': 'correcthorse1'})
    r = client.post('/api/auth/login', json={'username': 'dave', 'password': 'wrongpassword'})
    assert r.status_code == 401


def test_login_unknown_user_same_error_as_wrong_password(client):
    """Doesn't leak whether a username exists — both cases are a plain 401
    with the same message."""
    r = client.post('/api/auth/login', json={'username': 'nobody', 'password': 'whatever1'})
    assert r.status_code == 401
    assert r.json()['detail'] == 'Wrong username or password'


def test_logout_invalidates_existing_token(client):
    r = client.post('/api/auth/signup', json={'username': 'erin', 'password': 'correcthorse1'})
    headers = {'Authorization': f"Bearer {r.json()['token']}"}

    r = client.post('/api/auth/logout', headers=headers)
    assert r.status_code == 200

    r = client.get('/api/auth/me', headers=headers)
    assert r.status_code == 401


def test_login_after_logout_issues_a_working_token(client):
    client.post('/api/auth/signup', json={'username': 'frank', 'password': 'correcthorse1'})
    old_token = client.post(
        '/api/auth/login', json={'username': 'frank', 'password': 'correcthorse1'}
    ).json()['token']
    client.post('/api/auth/logout', headers={'Authorization': f'Bearer {old_token}'})

    r = client.post('/api/auth/login', json={'username': 'frank', 'password': 'correcthorse1'})
    new_token = r.json()['token']
    assert new_token != old_token

    r = client.get('/api/auth/me', headers={'Authorization': f'Bearer {new_token}'})
    assert r.status_code == 200
    assert r.json() == {'username': 'frank'}
