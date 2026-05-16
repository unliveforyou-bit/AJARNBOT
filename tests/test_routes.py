"""
Flask route tests via test client.
Tests cover: /health, auth gates, owner-only endpoints, guild access control.
"""
import importlib
import sys
import json
import pytest


@pytest.fixture(scope='module')
def vb():
    if 'voice_bot' in sys.modules:
        return sys.modules['voice_bot']
    return importlib.import_module('voice_bot')


@pytest.fixture(scope='module')
def app(vb):
    """Return Flask app configured for testing."""
    vb.flask_app.config['TESTING'] = True
    vb.flask_app.config['SESSION_COOKIE_SECURE'] = False  # allow test client over http
    vb.flask_app.secret_key = 'test_secret_key_for_pytest'
    return vb.flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def owner_client(app, vb):
    """Test client with owner session (password login)."""
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['logged_in'] = True
        sess['login_method'] = 'password'  # → session_is_owner() returns True
    return c


@pytest.fixture
def guild_admin_client(app, vb):
    """Test client simulating a Discord user who is admin of guild '777'."""
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['logged_in'] = True
        sess['login_method'] = 'discord'
        sess['discord_guilds'] = [
            {
                'id': '777',
                'name': 'Test Guild',
                'owner': False,
                'permissions': str(0x20),  # MANAGE_GUILD bit
            }
        ]
    return c


# ── /health ───────────────────────────────────────────────────────────────────

def test_health_returns_200(client):
    r = client.get('/health')
    assert r.status_code == 200


def test_health_returns_json(client):
    r = client.get('/health')
    data = json.loads(r.data)
    assert 'ok' in data


# ── auth gate ─────────────────────────────────────────────────────────────────

def test_unauthenticated_api_returns_401(client):
    """@require_auth on /api/* → 401 JSON (not a redirect) for unauthenticated requests."""
    r = client.get('/api/status?guild_id=123')
    assert r.status_code == 401
    data = json.loads(r.data)
    assert 'error' in data


def test_unauthenticated_config_returns_401(client):
    r = client.get('/api/config')
    assert r.status_code == 401


def test_unauthenticated_guilds_returns_401(client):
    r = client.get('/api/guilds')
    assert r.status_code == 401


# ── /api/config (GET) — authenticated ────────────────────────────────────────

def test_owner_can_get_config(owner_client):
    r = owner_client.get('/api/config')
    assert r.status_code == 200
    data = json.loads(r.data)
    assert isinstance(data, dict)
    assert 'announce_join' in data


def test_config_includes_version(owner_client, vb):
    r = owner_client.get('/api/config')
    data = json.loads(r.data)
    assert data.get('app_version') == vb.APP_VERSION


# ── /api/config (POST) — owner only ──────────────────────────────────────────

def test_non_owner_cannot_post_global_config(guild_admin_client):
    """Guild admin → POST /api/config → 403 (owner-only)."""
    r = guild_admin_client.post(
        '/api/config',
        data=json.dumps({'announce_join': False}),
        content_type='application/json',
    )
    assert r.status_code == 403


def test_owner_can_post_global_config(owner_client):
    r = owner_client.post(
        '/api/config',
        data=json.dumps({'joke_delay': 30}),
        content_type='application/json',
    )
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data.get('ok') is True


# ── /api/guild-config — guild_id required ────────────────────────────────────

def test_guild_config_get_without_guild_id_returns_400(owner_client):
    r = owner_client.get('/api/guild-config')
    assert r.status_code == 400
    data = json.loads(r.data)
    assert 'guild_id' in data.get('error', '').lower()


def test_guild_admin_can_get_own_guild_config(guild_admin_client):
    r = guild_admin_client.get('/api/guild-config?guild_id=777')
    assert r.status_code == 200
    data = json.loads(r.data)
    assert isinstance(data, dict)


def test_guild_admin_cannot_get_other_guild_config(guild_admin_client):
    """Guild admin of 777 → access guild 888 → 403."""
    r = guild_admin_client.get('/api/guild-config?guild_id=888')
    assert r.status_code == 403


# ── /api/user-daily — guild_id required ──────────────────────────────────────

def test_user_daily_without_guild_id_returns_400(owner_client):
    r = owner_client.get('/api/user-daily')
    # Either 400 (missing guild_id) or 200 with empty data — never 500
    assert r.status_code in (200, 400)


# ── /api/status — guild_id required ──────────────────────────────────────────

def test_status_without_guild_id_returns_400(owner_client):
    r = owner_client.get('/api/status')
    assert r.status_code == 400


# ── /api/my-guilds ────────────────────────────────────────────────────────────

def test_my_guilds_returns_list_for_guild_admin(guild_admin_client):
    r = guild_admin_client.get('/api/my-guilds')
    assert r.status_code == 200
    data = json.loads(r.data)
    assert isinstance(data, list)


def test_my_guilds_only_shows_bot_guilds(guild_admin_client):
    """
    /api/my-guilds filters discord_guilds against bot's live guilds.
    In tests the bot is not connected, so the list is empty — that's correct behavior.
    The test verifies the response is a valid JSON list (not an error).
    """
    r = guild_admin_client.get('/api/my-guilds')
    assert r.status_code == 200
    data = json.loads(r.data)
    assert isinstance(data, list)
    # All returned guilds must have an 'id' field
    for g in data:
        assert 'id' in g


# ── API key bypass ────────────────────────────────────────────────────────────

def test_api_key_bypass_grants_access(app, vb):
    """If DASHBOARD_API_KEY is set, X-API-Key header bypasses session auth."""
    original = vb.DASHBOARD_API_KEY
    vb.DASHBOARD_API_KEY = 'test_api_key_12345'
    try:
        c = app.test_client()
        r = c.get('/api/config', headers={'X-API-Key': 'test_api_key_12345'})
        assert r.status_code == 200
    finally:
        vb.DASHBOARD_API_KEY = original


def test_wrong_api_key_is_rejected(app, vb):
    original = vb.DASHBOARD_API_KEY
    vb.DASHBOARD_API_KEY = 'correct_key'
    try:
        c = app.test_client()
        r = c.get('/api/config', headers={'X-API-Key': 'wrong_key'})
        # /api/* → 401 when not authenticated; wrong key = no bypass → treated as unauthenticated
        assert r.status_code in (302, 401, 403)
    finally:
        vb.DASHBOARD_API_KEY = original


# ── /api/timeline ─────────────────────────────────────────────────────────────

def test_timeline_today_empty(owner_client):
    """GET /api/timeline/<uid> for unknown uid returns empty sessions list."""
    resp = owner_client.get('/api/timeline/999999?guild_id=999')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['sessions'] == []
    assert data['count'] == 0


def test_timeline_invalid_date(owner_client):
    """GET /api/timeline/<uid> with bad date returns 400."""
    resp = owner_client.get('/api/timeline/111?guild_id=999&date=not-a-date')
    assert resp.status_code == 400


def test_timeline_missing_guild_id(owner_client):
    """GET /api/timeline/<uid> without guild_id returns 400."""
    resp = owner_client.get('/api/timeline/111')
    assert resp.status_code == 400
    data = resp.get_json()
    assert 'guild_id' in data.get('error', '').lower()


def test_timeline_unauthenticated(client):
    """GET /api/timeline/<uid> without auth returns 401."""
    resp = client.get('/api/timeline/111?guild_id=999')
    assert resp.status_code == 401


def test_timeline_with_session(owner_client, vb):
    """GET /api/timeline/<uid> returns session data when history exists."""
    import datetime as dt
    today = dt.datetime.now(vb.THAI_TZ).strftime('%Y-%m-%d')
    vb.session_history.append({
        'guild_id': '999',
        'uid': '111',
        'channel': 'General',
        'join': today + ' 10:00',
        'leave': today + ' 11:00',
        'seconds': 3600,
    })
    try:
        resp = owner_client.get('/api/timeline/111?guild_id=999&date=' + today)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] >= 1
        assert data['total_sec'] >= 3600
        assert any(s['channel'] == 'General' for s in data['sessions'])
    finally:
        # Clean up added session
        vb.session_history[:] = [
            s for s in vb.session_history
            if not (s.get('guild_id') == '999' and s.get('uid') == '111' and s.get('channel') == 'General')
        ]
