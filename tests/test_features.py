"""
Tests for new features:
  compute_streak (F4)
  get_user_alltime_seconds + check_and_award_milestones (F5)
  channel_activity via record_leave (F6)
  /api/channel-stats Flask route (F6)
"""
import importlib
import sys
import json
import pytest
from datetime import datetime, timedelta


@pytest.fixture(scope='module')
def vb():
    if 'voice_bot' in sys.modules:
        return sys.modules['voice_bot']
    return importlib.import_module('voice_bot')


@pytest.fixture(autouse=True)
def clean_state(vb):
    orig_history    = list(vb.session_history)
    orig_milestones = {k: dict(v) for k, v in vb.milestones_awarded.items()}
    orig_ch_act     = {k: dict(v) for k, v in vb.channel_activity.items()}
    orig_user_daily = {k: {u: dict(d) for u, d in v.items()} for k, v in vb.user_daily.items()}
    yield
    vb.session_history.clear()
    vb.session_history.extend(orig_history)
    vb.milestones_awarded.clear()
    vb.milestones_awarded.update(orig_milestones)
    vb.channel_activity.clear()
    vb.channel_activity.update(orig_ch_act)
    vb.user_daily.clear()
    vb.user_daily.update(orig_user_daily)


# ── compute_streak (F4) ───────────────────────────────────────────────────────

def test_streak_empty(vb):
    assert vb.compute_streak({}) == 0


def test_streak_only_today(vb):
    today = datetime.now(vb.THAI_TZ).date().isoformat()
    assert vb.compute_streak({today: 1}) == 1


def test_streak_consecutive_days(vb):
    today = datetime.now(vb.THAI_TZ).date()
    dates = {(today - timedelta(days=i)).isoformat(): 1 for i in range(4)}
    assert vb.compute_streak(dates) == 4


def test_streak_broken_gap(vb):
    """Gap 2 days ago → streak counts only from yesterday onwards."""
    today = datetime.now(vb.THAI_TZ).date()
    # today and yesterday present; 2 days ago missing; 3 days ago present
    dates = {
        today.isoformat(): 1,
        (today - timedelta(days=1)).isoformat(): 1,
        (today - timedelta(days=3)).isoformat(): 1,  # gap at -2
    }
    assert vb.compute_streak(dates) == 2


def test_streak_starts_from_yesterday_if_today_missing(vb):
    """If today has no entry, streak starts counting from yesterday."""
    today = datetime.now(vb.THAI_TZ).date()
    dates = {
        (today - timedelta(days=1)).isoformat(): 1,
        (today - timedelta(days=2)).isoformat(): 1,
    }
    assert vb.compute_streak(dates) == 2


def test_streak_old_dates_only(vb):
    """Only old dates (no today/yesterday) → streak 0."""
    dates = {'2020-01-01': 1, '2020-01-02': 1}
    assert vb.compute_streak(dates) == 0


# ── get_user_alltime_seconds (F5) ─────────────────────────────────────────────

def test_alltime_empty_history(vb):
    assert vb.get_user_alltime_seconds('100', '1') == 0


def test_alltime_sums_sessions(vb):
    vb.session_history.extend([
        {'guild_id': '100', 'uid': '1', 'seconds': 3600},
        {'guild_id': '100', 'uid': '1', 'seconds': 1800},
        {'guild_id': '100', 'uid': '2', 'seconds': 9999},  # different user
    ])
    assert vb.get_user_alltime_seconds('100', '1') == 5400


def test_alltime_filters_guild(vb):
    vb.session_history.extend([
        {'guild_id': '100', 'uid': '1', 'seconds': 1000},
        {'guild_id': '999', 'uid': '1', 'seconds': 5000},  # different guild
    ])
    assert vb.get_user_alltime_seconds('100', '1') == 1000


# ── check_and_award_milestones (F5) ──────────────────────────────────────────

def _add_history(vb, guild_id, uid, seconds):
    vb.session_history.append({'guild_id': guild_id, 'uid': uid, 'seconds': seconds})


def test_milestone_no_hit(vb):
    _add_history(vb, '200', '10', 1800)   # 30 min — below 1h milestone
    result = vb.check_and_award_milestones('200', '10')
    assert result == []


def test_milestone_hits_1h(vb):
    _add_history(vb, '200', '11', 3600)   # exactly 1 hour
    result = vb.check_and_award_milestones('200', '11')
    assert 1 in result


def test_milestone_not_double_awarded(vb):
    _add_history(vb, '200', '12', 3600 * 2)   # 2 hours → crosses 1h milestone
    vb.check_and_award_milestones('200', '12')   # first call — awards it
    # add more time but still under 5h
    _add_history(vb, '200', '12', 3600)          # now ~3h total
    result2 = vb.check_and_award_milestones('200', '12')
    assert 1 not in result2   # 1h already awarded


def test_milestone_multiple_hit_at_once(vb):
    """Large history → multiple milestones hit in one check."""
    _add_history(vb, '200', '13', 3600 * 11)   # 11 hours — crosses 1h, 5h, 10h
    result = vb.check_and_award_milestones('200', '13')
    assert 1 in result
    assert 5 in result
    assert 10 in result
    assert 25 not in result


# ── channel_activity via record_leave (F6) ────────────────────────────────────

def test_channel_activity_updated_on_leave(vb):
    """record_leave updates channel_activity with elapsed seconds."""
    now = datetime.now(vb.THAI_TZ)
    guild_id, member_id = 300, 50
    vb.voice_join_times[(guild_id, member_id)] = ('TestUser', now - timedelta(minutes=10), 'General')
    vb.record_leave(guild_id, member_id)
    ch_data = vb.channel_activity.get(str(guild_id), {})
    assert 'General' in ch_data
    assert ch_data['General'] >= 600   # at least 10 min


def test_channel_activity_accumulates(vb):
    """Two sessions in same channel accumulate seconds."""
    now = datetime.now(vb.THAI_TZ)
    gid, mid = 300, 51
    vb.voice_join_times[(gid, mid)] = ('UserA', now - timedelta(minutes=5), 'Gaming')
    vb.record_leave(gid, mid)
    first = vb.channel_activity.get(str(gid), {}).get('Gaming', 0)

    vb.voice_join_times[(gid, mid)] = ('UserA', now - timedelta(minutes=5), 'Gaming')
    vb.record_leave(gid, mid)
    second = vb.channel_activity.get(str(gid), {}).get('Gaming', 0)

    assert second > first


def test_channel_activity_separate_channels(vb):
    """Different channels tracked independently."""
    now = datetime.now(vb.THAI_TZ)
    gid = 300
    vb.voice_join_times[(gid, 52)] = ('UserB', now - timedelta(minutes=5), 'General')
    vb.voice_join_times[(gid, 53)] = ('UserC', now - timedelta(minutes=8), 'Gaming')
    vb.record_leave(gid, 52)
    vb.record_leave(gid, 53)
    ch = vb.channel_activity.get(str(gid), {})
    assert 'General' in ch
    assert 'Gaming' in ch


# ── /api/channel-stats (F6) ───────────────────────────────────────────────────

@pytest.fixture(scope='module')
def app(vb):
    vb.flask_app.config['TESTING'] = True
    vb.flask_app.config['SESSION_COOKIE_SECURE'] = False
    vb.flask_app.secret_key = 'test_secret_key_for_pytest'
    return vb.flask_app


@pytest.fixture
def owner_client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['logged_in'] = True
        sess['login_method'] = 'password'
    return c


def test_channel_stats_without_guild_id(owner_client):
    r = owner_client.get('/api/channel-stats')
    assert r.status_code == 400


def test_channel_stats_returns_list(owner_client, vb):
    vb.channel_activity['999'] = {'General': 3600, 'Gaming': 7200}
    r = owner_client.get('/api/channel-stats?guild_id=999')
    assert r.status_code == 200
    data = json.loads(r.data)
    assert isinstance(data, list)
    # Should be sorted descending by seconds
    if len(data) >= 2:
        assert data[0]['seconds'] >= data[1]['seconds']


def test_channel_stats_empty_guild(owner_client, vb):
    vb.channel_activity.pop('888', None)
    r = owner_client.get('/api/channel-stats?guild_id=888')
    assert r.status_code == 200
    assert json.loads(r.data) == []


def test_channel_stats_has_required_fields(owner_client, vb):
    vb.channel_activity['777'] = {'Lounge': 1800}
    r = owner_client.get('/api/channel-stats?guild_id=777')
    data = json.loads(r.data)
    assert len(data) == 1
    assert 'channel' in data[0]
    assert 'seconds' in data[0]
    assert 'duration' in data[0]
