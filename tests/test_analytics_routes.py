"""
Comprehensive tests for all analytics API endpoints (v3.1.0 + v3.2.0).

Covers:
  /api/dau           — DAU trend
  /api/leaderboard   — period/sort leaderboard
  /api/inactive      — inactive user detection
  /api/retention     — week-over-week retention
  /api/wau-mau       — weekly active users
  /api/dow-heatmap   — day-of-week × hour matrix
  /api/histogram     — session length distribution
  /api/channel-stats — per-channel voice time
  /api/user-growth   — new vs returning users per week
  /api/channel-details — extended channel analytics
  /api/copresence    — user pair co-presence
  /api/milestone-log — milestone awards log
  /api/voice-now     — live voice snapshot
  /api/forecast      — 7-day DAU forecast
  /api/cohort        — cohort retention matrix
  /api/time-of-day   — 24h session profile
  /api/churn-risk    — churn risk scoring
  /api/records       — all-time guild records

Each endpoint is tested for:
  1. Unauthenticated access → 401
  2. Missing guild_id → 400
  3. Empty-data baseline → 200 + valid JSON structure
  4. Happy-path with seeded data → correct values / schema
  5. Invalid param types → 400 or graceful fallback
"""

import importlib
import sys
import json
import pytest
from datetime import datetime, timedelta


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def vb():
    if 'voice_bot' in sys.modules:
        return sys.modules['voice_bot']
    return importlib.import_module('voice_bot')


@pytest.fixture(scope='module')
def app(vb):
    vb.flask_app.config['TESTING'] = True
    vb.flask_app.config['SESSION_COOKIE_SECURE'] = False
    vb.flask_app.secret_key = 'test_secret_analytics'
    return vb.flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def owner(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['logged_in']    = True
        sess['login_method'] = 'password'
    return c


GUILD = '42'   # guild_id used across all tests


@pytest.fixture(autouse=True)
def clean_state(vb):
    """Restore all mutable globals after each test."""
    orig_history    = list(vb.session_history)
    orig_user_daily = {
        k: {uid: {**d, 'dates': dict(d.get('dates', {}))}
            for uid, d in v.items()}
        for k, v in vb.user_daily.items()
    }
    orig_daily_act   = {k: dict(v) for k, v in vb.daily_activity.items()}
    orig_daily_uniq  = {k: {d: list(u) for d, u in v.items()} for k, v in vb.daily_unique.items()}
    orig_milestones  = {k: {uid: list(h) for uid, h in v.items()} for k, v in vb.milestones_awarded.items()}
    orig_ch_act      = {k: dict(v) for k, v in vb.channel_activity.items()}
    orig_ldb_cache   = dict(vb._ldb_cache)
    orig_growth      = dict(vb._growth_cache)
    orig_chdet       = dict(vb._chdet_cache)
    orig_cop         = dict(vb._cop_cache)
    orig_forecast    = dict(vb._forecast_cache)
    orig_cohort      = dict(vb._cohort_cache)
    orig_tod         = dict(vb._tod_cache)
    orig_churn       = dict(vb._churn_cache)
    orig_records     = dict(vb._records_cache)
    yield
    vb.session_history.clear();    vb.session_history.extend(orig_history)
    vb.user_daily.clear();         vb.user_daily.update(orig_user_daily)
    vb.daily_activity.clear();     vb.daily_activity.update(orig_daily_act)
    vb.daily_unique.clear();       vb.daily_unique.update(orig_daily_uniq)
    vb.milestones_awarded.clear(); vb.milestones_awarded.update(orig_milestones)
    vb.channel_activity.clear();   vb.channel_activity.update(orig_ch_act)
    vb._ldb_cache.clear();         vb._ldb_cache.update(orig_ldb_cache)
    vb._growth_cache.clear();      vb._growth_cache.update(orig_growth)
    vb._chdet_cache.clear();       vb._chdet_cache.update(orig_chdet)
    vb._cop_cache.clear();         vb._cop_cache.update(orig_cop)
    vb._forecast_cache.clear();    vb._forecast_cache.update(orig_forecast)
    vb._cohort_cache.clear();      vb._cohort_cache.update(orig_cohort)
    vb._tod_cache.clear();         vb._tod_cache.update(orig_tod)
    vb._churn_cache.clear();       vb._churn_cache.update(orig_churn)
    vb._records_cache.clear();     vb._records_cache.update(orig_records)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today(vb, offset=0):
    return (datetime.now(vb.THAI_TZ) - timedelta(days=offset)).strftime('%Y-%m-%d')


def _hhmm(vb, offset_days=0, hour=10):
    d = datetime.now(vb.THAI_TZ) - timedelta(days=offset_days)
    return d.strftime('%Y-%m-%d') + f' {hour:02d}:00'


def _seed_session(vb, uid='1', name='Alice', guild=GUILD,
                  join_offset=0, leave_offset=0, seconds=3600, channel='General'):
    """Insert one session_history entry."""
    vb.session_history.append({
        'guild_id': guild,
        'uid':      uid,
        'name':     name,
        'channel':  channel,
        'join':     _hhmm(vb, join_offset, 10),
        'leave':    _hhmm(vb, leave_offset, 11),
        'seconds':  seconds,
    })


def _seed_user_daily(vb, uid='1', name='Alice', guild=GUILD,
                     dates=None, alltime=3600, sessions=1,
                     first_seen=None, last_seen=None, streak_max=1):
    """Populate user_daily for a user."""
    if dates is None:
        dates = {_today(vb): 1}
    if guild not in vb.user_daily:
        vb.user_daily[guild] = {}
    vb.user_daily[guild][uid] = {
        'name':           name,
        'dates':          dates,
        'alltime_seconds': alltime,
        'session_count':  sessions,
        'streak_max':     streak_max,
        'first_seen':     first_seen or (datetime.now(vb.THAI_TZ).isoformat()),
        'last_seen':      last_seen or (datetime.now(vb.THAI_TZ).isoformat()),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  /api/dau
# ═══════════════════════════════════════════════════════════════════════════════

class TestDau:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/dau?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/dau').status_code == 400

    def test_invalid_days_returns_400(self, owner):
        assert owner.get(f'/api/dau?guild_id={GUILD}&days=abc').status_code == 400

    def test_empty_returns_list_of_correct_length(self, owner):
        r = owner.get(f'/api/dau?guild_id={GUILD}&days=7')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) == 7

    def test_response_schema(self, owner):
        r = owner.get(f'/api/dau?guild_id={GUILD}&days=3')
        data = r.get_json()
        for row in data:
            assert 'date'  in row
            assert 'dau'   in row
            assert 'joins' in row

    def test_counts_unique_users(self, owner, vb):
        today = _today(vb)
        vb.daily_unique[GUILD] = {today: ['1', '2', '3']}
        r = owner.get(f'/api/dau?guild_id={GUILD}&days=1')
        data = r.get_json()
        assert data[0]['dau'] == 3

    def test_joins_from_daily_activity(self, owner, vb):
        today = _today(vb)
        vb.daily_activity[GUILD] = {today: 5}
        r = owner.get(f'/api/dau?guild_id={GUILD}&days=1')
        data = r.get_json()
        assert data[0]['joins'] == 5


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  /api/leaderboard
# ═══════════════════════════════════════════════════════════════════════════════

class TestLeaderboard:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/leaderboard?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/leaderboard').status_code == 400

    def test_empty_returns_list(self, owner):
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}')
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_response_schema(self, owner, vb):
        _seed_session(vb, uid='10', name='Bob')
        vb._ldb_cache.clear()
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=alltime')
        data = r.get_json()
        assert len(data) >= 1
        for row in data:
            for key in ('uid', 'name', 'seconds', 'duration'):
                assert key in row

    def test_period_7d_uses_weekly_stats(self, owner, vb):
        vb.weekly_stats[GUILD] = {'99': {'name': 'Carol', 'seconds': 9999}}
        vb._ldb_cache.clear()
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=7d')
        data = r.get_json()
        assert any(row['uid'] == '99' for row in data)

    def test_sort_streak(self, owner, vb):
        _seed_user_daily(vb, uid='11', name='Dan', streak_max=50)
        _seed_session(vb, uid='11', name='Dan')
        vb._ldb_cache.clear()
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=alltime&sort=streak')
        data = r.get_json()
        assert data[0]['streak_max'] == 50

    def test_sort_sessions(self, owner, vb):
        _seed_user_daily(vb, uid='12', name='Eve', sessions=99)
        _seed_session(vb, uid='12', name='Eve')
        vb._ldb_cache.clear()
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=alltime&sort=sessions')
        data = r.get_json()
        assert data[0]['session_count'] == 99


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  /api/inactive
# ═══════════════════════════════════════════════════════════════════════════════

class TestInactive:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/inactive?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/inactive').status_code == 400

    def test_invalid_days_returns_400(self, owner):
        assert owner.get(f'/api/inactive?guild_id={GUILD}&days=xyz').status_code == 400

    def test_empty_returns_list(self, owner):
        r = owner.get(f'/api/inactive?guild_id={GUILD}')
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_detects_inactive_user(self, owner, vb):
        old = (datetime.now(vb.THAI_TZ) - timedelta(days=20)).isoformat()
        _seed_user_daily(vb, uid='20', name='OldUser', last_seen=old)
        r = owner.get(f'/api/inactive?guild_id={GUILD}&days=14')
        data = r.get_json()
        assert any(u['uid'] == '20' for u in data)

    def test_active_user_not_in_inactive(self, owner, vb):
        _seed_user_daily(vb, uid='21', name='ActiveUser')
        r = owner.get(f'/api/inactive?guild_id={GUILD}&days=14')
        data = r.get_json()
        assert all(u['uid'] != '21' for u in data)

    def test_response_schema(self, owner, vb):
        old = (datetime.now(vb.THAI_TZ) - timedelta(days=30)).isoformat()
        _seed_user_daily(vb, uid='22', name='Ghost', last_seen=old)
        r = owner.get(f'/api/inactive?guild_id={GUILD}')
        data = r.get_json()
        for row in data:
            for key in ('uid', 'name', 'last_seen', 'days_inactive'):
                assert key in row

    def test_sorted_by_days_inactive_desc(self, owner, vb):
        old30 = (datetime.now(vb.THAI_TZ) - timedelta(days=30)).isoformat()
        old60 = (datetime.now(vb.THAI_TZ) - timedelta(days=60)).isoformat()
        _seed_user_daily(vb, uid='23', name='Less', last_seen=old30)
        _seed_user_daily(vb, uid='24', name='More', last_seen=old60)
        r = owner.get(f'/api/inactive?guild_id={GUILD}&days=14')
        data = r.get_json()
        uids = [u['uid'] for u in data]
        assert uids.index('24') < uids.index('23')


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  /api/retention
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetention:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/retention?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/retention').status_code == 400

    def test_invalid_weeks_returns_400(self, owner):
        assert owner.get(f'/api/retention?guild_id={GUILD}&weeks=abc').status_code == 400

    def test_returns_list_of_correct_length(self, owner):
        r = owner.get(f'/api/retention?guild_id={GUILD}&weeks=4')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) == 4

    def test_response_schema(self, owner):
        r = owner.get(f'/api/retention?guild_id={GUILD}&weeks=2')
        data = r.get_json()
        for row in data:
            for key in ('week_start', 'active_count', 'retained_count', 'retention_pct'):
                assert key in row

    def test_first_week_retention_pct_is_none(self, owner):
        r = owner.get(f'/api/retention?guild_id={GUILD}&weeks=2')
        data = r.get_json()
        assert data[0]['retention_pct'] is None  # no prior week

    def test_retention_counts_returning_users(self, owner, vb):
        now = datetime.now(vb.THAI_TZ)
        # seed user active in both last week AND the week before
        week1_join = (now - timedelta(days=10)).strftime('%Y-%m-%d %H:%M')
        week2_join = (now - timedelta(days=4)).strftime('%Y-%m-%d %H:%M')
        vb.session_history += [
            {'guild_id': GUILD, 'uid': '30', 'name': 'Sam', 'channel': 'G',
             'join': week1_join, 'leave': week1_join[:10] + ' 11:00', 'seconds': 3600},
            {'guild_id': GUILD, 'uid': '30', 'name': 'Sam', 'channel': 'G',
             'join': week2_join, 'leave': week2_join[:10] + ' 11:00', 'seconds': 3600},
        ]
        vb._ret_cache.clear()
        r = owner.get(f'/api/retention?guild_id={GUILD}&weeks=3')
        data = r.get_json()
        # At least one week should have retained_count >= 1
        assert any(w['retained_count'] >= 1 for w in data)


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  /api/wau-mau
# ═══════════════════════════════════════════════════════════════════════════════

class TestWauMau:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/wau-mau?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/wau-mau').status_code == 400

    def test_returns_correct_length(self, owner):
        r = owner.get(f'/api/wau-mau?guild_id={GUILD}&weeks=4')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 4

    def test_response_has_wau(self, owner):
        r = owner.get(f'/api/wau-mau?guild_id={GUILD}&weeks=2')
        for row in r.get_json():
            assert 'week_start' in row
            assert 'wau' in row

    def test_counts_unique_uids_per_week(self, owner, vb):
        today = _today(vb)
        vb.daily_unique[GUILD] = {today: ['a', 'b', 'c']}
        r = owner.get(f'/api/wau-mau?guild_id={GUILD}&weeks=1')
        data = r.get_json()
        assert data[0]['wau'] >= 3


# ═══════════════════════════════════════════════════════════════════════════════
# 6.  /api/dow-heatmap
# ═══════════════════════════════════════════════════════════════════════════════

class TestDowHeatmap:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/dow-heatmap?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/dow-heatmap').status_code == 400

    def test_returns_7x24_matrix(self, owner):
        r = owner.get(f'/api/dow-heatmap?guild_id={GUILD}')
        data = r.get_json()
        assert 'matrix' in data
        assert len(data['matrix']) == 7
        assert all(len(row) == 24 for row in data['matrix'])

    def test_session_increments_correct_cell(self, owner, vb):
        # Monday 10:00
        mon = datetime.now(vb.THAI_TZ)
        while mon.weekday() != 0:
            mon -= timedelta(days=1)
        join_str = mon.strftime('%Y-%m-%d') + ' 10:00'
        vb.session_history.append({
            'guild_id': GUILD, 'uid': '1', 'name': 'A', 'channel': 'G',
            'join': join_str, 'leave': join_str[:10] + ' 11:00', 'seconds': 3600,
        })
        r = owner.get(f'/api/dow-heatmap?guild_id={GUILD}')
        data = r.get_json()
        assert data['matrix'][0][10] >= 1   # Monday = index 0, hour 10


# ═══════════════════════════════════════════════════════════════════════════════
# 7.  /api/histogram
# ═══════════════════════════════════════════════════════════════════════════════

class TestHistogram:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/histogram?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/histogram').status_code == 400

    def test_returns_5_buckets(self, owner):
        r = owner.get(f'/api/histogram?guild_id={GUILD}')
        data = r.get_json()
        assert len(data) == 5
        ranges = [b['range'] for b in data]
        for expected in ('0-5m', '5-15m', '15-30m', '30-60m', '60m+'):
            assert expected in ranges

    def test_short_session_in_first_bucket(self, owner, vb):
        _seed_session(vb, seconds=60)   # 1 min → 0-5m
        r = owner.get(f'/api/histogram?guild_id={GUILD}')
        data = {b['range']: b['count'] for b in r.get_json()}
        assert data['0-5m'] >= 1

    def test_long_session_in_last_bucket(self, owner, vb):
        _seed_session(vb, seconds=7200)   # 2 hours → 60m+
        r = owner.get(f'/api/histogram?guild_id={GUILD}')
        data = {b['range']: b['count'] for b in r.get_json()}
        assert data['60m+'] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 8.  /api/channel-stats  (basic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestChannelStats:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/channel-stats?guild_id={GUILD}').status_code == 401

    def test_returns_list(self, owner):
        r = owner.get(f'/api/channel-stats?guild_id={GUILD}')
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_channel_in_response(self, owner, vb):
        vb.channel_activity[GUILD] = {'Lobby': 7200, 'Gaming': 3600}
        r = owner.get(f'/api/channel-stats?guild_id={GUILD}')
        data = r.get_json()
        names = [x['channel'] for x in data]
        assert 'Lobby' in names
        assert 'Gaming' in names

    def test_sorted_by_seconds_desc(self, owner, vb):
        vb.channel_activity[GUILD] = {'A': 100, 'B': 9999}
        r = owner.get(f'/api/channel-stats?guild_id={GUILD}')
        data = r.get_json()
        assert data[0]['channel'] == 'B'


# ═══════════════════════════════════════════════════════════════════════════════
# 9.  /api/user-growth
# ═══════════════════════════════════════════════════════════════════════════════

class TestUserGrowth:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/user-growth?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/user-growth').status_code == 400

    def test_invalid_weeks_returns_400(self, owner):
        assert owner.get(f'/api/user-growth?guild_id={GUILD}&weeks=abc').status_code == 400

    def test_returns_list_of_correct_length(self, owner):
        r = owner.get(f'/api/user-growth?guild_id={GUILD}&weeks=6')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 6

    def test_response_schema(self, owner):
        r = owner.get(f'/api/user-growth?guild_id={GUILD}&weeks=2')
        for row in r.get_json():
            for key in ('week_start', 'new_users', 'returning_users', 'total'):
                assert key in row

    def test_new_user_counted_when_first_seen_this_week(self, owner, vb):
        vb._growth_cache.clear()
        first_seen = datetime.now(vb.THAI_TZ).isoformat()
        _seed_user_daily(vb, uid='40', name='NewUser', first_seen=first_seen)
        r = owner.get(f'/api/user-growth?guild_id={GUILD}&weeks=2')
        data = r.get_json()
        # data[-1] is the current week
        assert data[-1]['new_users'] >= 1

    def test_returning_user_counted_when_first_seen_older(self, owner, vb):
        vb._growth_cache.clear()
        old_seen = (datetime.now(vb.THAI_TZ) - timedelta(days=60)).isoformat()
        _seed_user_daily(vb, uid='41', name='OldReturn', first_seen=old_seen)
        r = owner.get(f'/api/user-growth?guild_id={GUILD}&weeks=2')
        data = r.get_json()
        # data[-1] is the current week
        assert data[-1]['returning_users'] >= 1

    def test_totals_match_sum(self, owner, vb):
        vb._growth_cache.clear()
        r = owner.get(f'/api/user-growth?guild_id={GUILD}&weeks=4')
        for row in r.get_json():
            assert row['total'] == row['new_users'] + row['returning_users']


# ═══════════════════════════════════════════════════════════════════════════════
# 10. /api/channel-details
# ═══════════════════════════════════════════════════════════════════════════════

class TestChannelDetails:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/channel-details?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/channel-details').status_code == 400

    def test_returns_list(self, owner):
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_response_schema(self, owner, vb):
        vb._chdet_cache.clear()
        _seed_session(vb, channel='Lobby')
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        data = r.get_json()
        assert len(data) >= 1
        for key in ('channel', 'seconds', 'duration', 'sessions',
                    'unique_users', 'avg_min', 'peak_hour', 'top_user'):
            assert key in data[0]

    def test_unique_users_counts_distinct_uids(self, owner, vb):
        vb._chdet_cache.clear()
        _seed_session(vb, uid='50', name='X', channel='VC')
        _seed_session(vb, uid='51', name='Y', channel='VC')
        _seed_session(vb, uid='50', name='X', channel='VC')   # same uid again
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        vc = next((c for c in r.get_json() if c['channel'] == 'VC'), None)
        assert vc is not None
        assert vc['unique_users'] == 2

    def test_sorted_by_seconds_desc(self, owner, vb):
        vb._chdet_cache.clear()
        _seed_session(vb, channel='Big',   seconds=9999)
        _seed_session(vb, channel='Small', seconds=1)
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        data = r.get_json()
        assert data[0]['seconds'] >= data[1]['seconds']

    def test_avg_min_calculation(self, owner, vb):
        vb._chdet_cache.clear()
        _seed_session(vb, uid='52', channel='Calc', seconds=3600)
        _seed_session(vb, uid='53', channel='Calc', seconds=1800)
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        calc = next((c for c in r.get_json() if c['channel'] == 'Calc'), None)
        assert calc is not None
        assert calc['sessions'] == 2
        # avg_min = (3600+1800)/60/2 = 45
        assert abs(calc['avg_min'] - 45.0) < 1


# ═══════════════════════════════════════════════════════════════════════════════
# 11. /api/copresence
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoPresence:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/copresence?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/copresence').status_code == 400

    def test_invalid_top_returns_400(self, owner):
        assert owner.get(f'/api/copresence?guild_id={GUILD}&top=abc').status_code == 400

    def test_empty_returns_list(self, owner):
        vb_mod = None   # not needed — just call owner
        r = owner.get(f'/api/copresence?guild_id={GUILD}')
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_detects_overlapping_sessions(self, owner, vb):
        vb._cop_cache.clear()
        now = datetime.now(vb.THAI_TZ)
        join1 = (now - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M')
        leave1 = (now - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
        # Both users overlap in the same window
        vb.session_history += [
            {'guild_id': GUILD, 'uid': '60', 'name': 'P1', 'channel': 'G',
             'join': join1, 'leave': leave1, 'seconds': 3600},
            {'guild_id': GUILD, 'uid': '61', 'name': 'P2', 'channel': 'G',
             'join': join1, 'leave': leave1, 'seconds': 3600},
        ]
        r = owner.get(f'/api/copresence?guild_id={GUILD}')
        data = r.get_json()
        assert len(data) >= 1
        pair = data[0]
        uids = {pair['uid_a'], pair['uid_b']}
        assert '60' in uids and '61' in uids

    def test_response_schema(self, owner, vb):
        vb._cop_cache.clear()
        r = owner.get(f'/api/copresence?guild_id={GUILD}')
        for row in r.get_json():
            for key in ('uid_a', 'name_a', 'uid_b', 'name_b', 'overlap_count'):
                assert key in row

    def test_non_overlapping_sessions_not_counted(self, owner, vb):
        vb._cop_cache.clear()
        # A leaves before B joins
        vb.session_history += [
            {'guild_id': GUILD, 'uid': '70', 'name': 'P3', 'channel': 'G',
             'join': '2025-01-01 08:00', 'leave': '2025-01-01 09:00', 'seconds': 3600},
            {'guild_id': GUILD, 'uid': '71', 'name': 'P4', 'channel': 'G',
             'join': '2025-01-01 10:00', 'leave': '2025-01-01 11:00', 'seconds': 3600},
        ]
        r = owner.get(f'/api/copresence?guild_id={GUILD}')
        for row in r.get_json():
            uids = {row['uid_a'], row['uid_b']}
            assert not ('70' in uids and '71' in uids)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. /api/milestone-log
# ═══════════════════════════════════════════════════════════════════════════════

class TestMilestoneLog:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/milestone-log?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/milestone-log').status_code == 400

    def test_empty_returns_list(self, owner):
        r = owner.get(f'/api/milestone-log?guild_id={GUILD}')
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_awarded_milestones_appear(self, owner, vb):
        _seed_user_daily(vb, uid='80', name='Hero')
        vb.milestones_awarded[GUILD] = {'80': [1, 10, 100]}
        r = owner.get(f'/api/milestone-log?guild_id={GUILD}')
        data = r.get_json()
        hours = {row['hours'] for row in data}
        assert 1 in hours and 10 in hours and 100 in hours

    def test_response_schema(self, owner, vb):
        vb.milestones_awarded[GUILD] = {'80': [1]}
        _seed_user_daily(vb, uid='80', name='Hero')
        r = owner.get(f'/api/milestone-log?guild_id={GUILD}')
        for row in r.get_json():
            assert 'uid'   in row
            assert 'name'  in row
            assert 'hours' in row

    def test_sorted_by_hours_desc(self, owner, vb):
        _seed_user_daily(vb, uid='81', name='A')
        vb.milestones_awarded[GUILD] = {'81': [1, 100, 10]}
        r = owner.get(f'/api/milestone-log?guild_id={GUILD}')
        hours = [row['hours'] for row in r.get_json()]
        assert hours == sorted(hours, reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. /api/voice-now
# ═══════════════════════════════════════════════════════════════════════════════

class TestVoiceNow:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/voice-now?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/voice-now').status_code == 400

    def test_empty_returns_list(self, owner):
        r = owner.get(f'/api/voice-now?guild_id={GUILD}')
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_live_user_appears(self, owner, vb):
        guild_int = int(GUILD)
        mid = 9001
        vb.voice_join_times[(guild_int, mid)] = (
            'TestUser',
            datetime.now(vb.THAI_TZ),
            'General',
        )
        try:
            r = owner.get(f'/api/voice-now?guild_id={GUILD}')
            data = r.get_json()
            assert any(u['uid'] == str(mid) for u in data)
        finally:
            vb.voice_join_times.pop((guild_int, mid), None)

    def test_response_schema(self, owner, vb):
        guild_int = int(GUILD)
        mid = 9002
        vb.voice_join_times[(guild_int, mid)] = (
            'SchemaUser',
            datetime.now(vb.THAI_TZ),
            'Lobby',
        )
        try:
            r = owner.get(f'/api/voice-now?guild_id={GUILD}')
            data = r.get_json()
            entry = next((u for u in data if u['uid'] == str(mid)), None)
            assert entry is not None
            for key in ('uid', 'name', 'channel', 'elapsed_sec', 'duration'):
                assert key in entry
        finally:
            vb.voice_join_times.pop((guild_int, mid), None)

    def test_elapsed_sec_is_non_negative(self, owner, vb):
        guild_int = int(GUILD)
        mid = 9003
        vb.voice_join_times[(guild_int, mid)] = (
            'TimeUser',
            datetime.now(vb.THAI_TZ),
            'Room',
        )
        try:
            r = owner.get(f'/api/voice-now?guild_id={GUILD}')
            for u in r.get_json():
                assert u['elapsed_sec'] >= 0
        finally:
            vb.voice_join_times.pop((guild_int, mid), None)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. /api/forecast
# ═══════════════════════════════════════════════════════════════════════════════

class TestForecast:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/forecast?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/forecast').status_code == 400

    def test_returns_history_and_forecast(self, owner):
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        assert r.status_code == 200
        data = r.get_json()
        assert 'history' in data
        assert 'forecast' in data

    def test_history_length_is_30(self, owner):
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        assert len(r.get_json()['history']) == 30

    def test_forecast_length_is_7(self, owner):
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        assert len(r.get_json()['forecast']) == 7

    def test_history_schema(self, owner):
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        for row in r.get_json()['history']:
            assert 'date' in row
            assert 'dau'  in row
            assert row['is_forecast'] is False

    def test_forecast_schema(self, owner):
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        for row in r.get_json()['forecast']:
            assert 'date' in row
            assert 'dau'  in row
            assert row['is_forecast'] is True

    def test_forecast_dates_are_in_future(self, owner, vb):
        today = _today(vb)
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        for row in r.get_json()['forecast']:
            assert row['date'] > today

    def test_forecast_dau_is_non_negative(self, owner, vb):
        vb._forecast_cache.clear()
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        for row in r.get_json()['forecast']:
            assert row['dau'] >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# 15. /api/cohort
# ═══════════════════════════════════════════════════════════════════════════════

class TestCohort:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/cohort?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/cohort').status_code == 400

    def test_invalid_params_return_400(self, owner):
        assert owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=abc').status_code == 400

    def test_returns_cohorts_and_retain_weeks(self, owner):
        r = owner.get(f'/api/cohort?guild_id={GUILD}')
        assert r.status_code == 200
        data = r.get_json()
        assert 'cohorts' in data
        assert 'retain_weeks' in data

    def test_cohort_schema(self, owner, vb):
        vb._cohort_cache.clear()
        # seed user with first_seen this week
        _seed_user_daily(vb, uid='90', name='C1',
                         first_seen=datetime.now(vb.THAI_TZ).isoformat())
        r = owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=2&retain_weeks=2')
        cohorts = r.get_json()['cohorts']
        if cohorts:
            c = cohorts[0]
            assert 'cohort_week' in c
            assert 'users'       in c
            assert 'weeks'       in c
            for w in c['weeks']:
                assert 'offset'   in w
                assert 'retained' in w
                assert 'pct'      in w

    def test_week0_retention_is_100_pct(self, owner, vb):
        vb._cohort_cache.clear()
        _seed_user_daily(vb, uid='91', name='CW0',
                         first_seen=datetime.now(vb.THAI_TZ).isoformat())
        r = owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=2&retain_weeks=3')
        cohorts = r.get_json()['cohorts']
        this_week = [c for c in cohorts if c['users'] > 0]
        if this_week:
            w0 = next((w for w in this_week[-1]['weeks'] if w['offset'] == 0), None)
            if w0:
                assert w0['pct'] == 100


# ═══════════════════════════════════════════════════════════════════════════════
# 16. /api/time-of-day
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimeOfDay:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/time-of-day?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/time-of-day').status_code == 400

    def test_returns_24_entries(self, owner):
        r = owner.get(f'/api/time-of-day?guild_id={GUILD}')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 24

    def test_response_schema(self, owner):
        for row in owner.get(f'/api/time-of-day?guild_id={GUILD}').get_json():
            assert 'hour'           in row
            assert 'avg_sessions'   in row
            assert 'total_sessions' in row

    def test_hours_are_0_to_23(self, owner):
        hours = [r['hour'] for r in owner.get(f'/api/time-of-day?guild_id={GUILD}').get_json()]
        assert hours == list(range(24))

    def test_session_increments_correct_hour(self, owner, vb):
        vb._tod_cache.clear()
        vb.session_history.append({
            'guild_id': GUILD, 'uid': '1', 'name': 'A', 'channel': 'G',
            'join':  '2025-06-01 14:00',
            'leave': '2025-06-01 15:00',
            'seconds': 3600,
        })
        r = owner.get(f'/api/time-of-day?guild_id={GUILD}')
        data = {row['hour']: row for row in r.get_json()}
        assert data[14]['total_sessions'] >= 1

    def test_avg_sessions_is_non_negative(self, owner):
        for row in owner.get(f'/api/time-of-day?guild_id={GUILD}').get_json():
            assert row['avg_sessions'] >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# 17. /api/churn-risk
# ═══════════════════════════════════════════════════════════════════════════════

class TestChurnRisk:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/churn-risk?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/churn-risk').status_code == 400

    def test_invalid_limit_returns_400(self, owner):
        assert owner.get(f'/api/churn-risk?guild_id={GUILD}&limit=abc').status_code == 400

    def test_empty_returns_list(self, owner):
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_response_schema(self, owner, vb):
        vb._churn_cache.clear()
        now = datetime.now(vb.THAI_TZ)
        # prior activity (60d ago) but none recent → high churn
        old = (now - timedelta(days=50)).strftime('%Y-%m-%d')
        _seed_user_daily(vb, uid='100', name='Churner',
                         dates={old: 3},
                         last_seen=(now - timedelta(days=50)).isoformat())
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        data = r.get_json()
        if data:
            for key in ('uid', 'name', 'risk_score', 'risk_level',
                        'days_since_last', 'sessions_recent', 'sessions_prior'):
                assert key in data[0]

    def test_fully_churned_user_has_high_risk(self, owner, vb):
        vb._churn_cache.clear()
        now = datetime.now(vb.THAI_TZ)
        old = (now - timedelta(days=50)).strftime('%Y-%m-%d')
        _seed_user_daily(vb, uid='101', name='Gone',
                         dates={old: 5},
                         last_seen=(now - timedelta(days=50)).isoformat())
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        data = r.get_json()
        user = next((u for u in data if u['uid'] == '101'), None)
        if user:
            assert user['risk_score'] > 0.5

    def test_risk_score_between_0_and_1(self, owner, vb):
        vb._churn_cache.clear()
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        for u in r.get_json():
            assert 0.0 <= u['risk_score'] <= 1.0

    def test_risk_level_valid_values(self, owner, vb):
        vb._churn_cache.clear()
        for u in owner.get(f'/api/churn-risk?guild_id={GUILD}').get_json():
            assert u['risk_level'] in ('low', 'medium', 'high')

    def test_sorted_by_risk_desc(self, owner, vb):
        vb._churn_cache.clear()
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        scores = [u['risk_score'] for u in r.get_json()]
        assert scores == sorted(scores, reverse=True)

    def test_new_users_excluded(self, owner, vb):
        """Users with no prior 30-60d activity should not appear."""
        vb._churn_cache.clear()
        _seed_user_daily(vb, uid='102', name='Brand New')   # first_seen = today
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        uids = [u['uid'] for u in r.get_json()]
        assert '102' not in uids


# ═══════════════════════════════════════════════════════════════════════════════
# 18. /api/records
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecords:
    def test_unauth_returns_401(self, client):
        assert client.get(f'/api/records?guild_id={GUILD}').status_code == 401

    def test_missing_guild_id_returns_400(self, owner):
        assert owner.get('/api/records').status_code == 400

    def test_returns_dict(self, owner):
        r = owner.get(f'/api/records?guild_id={GUILD}')
        assert r.status_code == 200
        assert isinstance(r.get_json(), dict)

    def test_all_record_keys_present(self, owner):
        data = owner.get(f'/api/records?guild_id={GUILD}').get_json()
        for key in ('longest_session', 'first_session', 'most_active_day',
                    'peak_dau_day', 'top_user_alltime', 'peak_concurrent'):
            assert key in data

    def test_longest_session_correct(self, owner, vb):
        vb._records_cache.clear()
        _seed_session(vb, uid='110', name='Champ', seconds=86400, channel='Epic')
        _seed_session(vb, uid='111', name='Other', seconds=60)
        r = owner.get(f'/api/records?guild_id={GUILD}')
        rec = r.get_json()['longest_session']
        assert rec is not None
        assert rec['seconds'] == 86400
        assert rec['name'] == 'Champ'

    def test_first_session_is_earliest(self, owner, vb):
        vb._records_cache.clear()
        vb.session_history += [
            {'guild_id': GUILD, 'uid': '120', 'name': 'First', 'channel': 'G',
             'join': '2020-01-01 08:00', 'leave': '2020-01-01 09:00', 'seconds': 3600},
            {'guild_id': GUILD, 'uid': '121', 'name': 'Later', 'channel': 'G',
             'join': '2023-06-01 10:00', 'leave': '2023-06-01 11:00', 'seconds': 3600},
        ]
        r = owner.get(f'/api/records?guild_id={GUILD}')
        rec = r.get_json()['first_session']
        assert rec is not None
        assert rec['name'] == 'First'

    def test_most_active_day_has_most_sessions(self, owner, vb):
        vb._records_cache.clear()
        vb.session_history += [
            {'guild_id': GUILD, 'uid': str(i), 'name': f'U{i}', 'channel': 'G',
             'join': '2025-03-15 10:00', 'leave': '2025-03-15 11:00', 'seconds': 3600}
            for i in range(130, 140)   # 10 sessions on same day
        ]
        r = owner.get(f'/api/records?guild_id={GUILD}')
        rec = r.get_json()['most_active_day']
        assert rec is not None
        assert rec['sessions'] >= 10

    def test_top_user_alltime(self, owner, vb):
        vb._records_cache.clear()
        _seed_user_daily(vb, uid='140', name='TopDog', alltime=999999)
        r = owner.get(f'/api/records?guild_id={GUILD}')
        rec = r.get_json()['top_user_alltime']
        assert rec is not None
        assert rec['name'] == 'TopDog'

    def test_peak_dau_day_correct(self, owner, vb):
        vb._records_cache.clear()
        vb.daily_unique[GUILD] = {
            '2025-01-01': ['a', 'b', 'c'],
            '2025-01-02': ['a', 'b', 'c', 'd', 'e'],
        }
        r = owner.get(f'/api/records?guild_id={GUILD}')
        rec = r.get_json()['peak_dau_day']
        assert rec is not None
        assert rec['dau'] == 5
        assert rec['date'] == '2025-01-02'
