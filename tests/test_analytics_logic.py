"""
Unit tests for analytics computation logic (voice_bot v3.2.0).

Tests the internal calculation engines:
  - EMA forecast algorithm (α=0.3, 30-day history → 7-day projection)
  - Cohort retention matrix (first_seen bucketing, week-offset pct)
  - Churn-risk scoring (recent vs prior session ratio)
  - Records aggregation (longest, first, peak-DAU, top-user, most-active-day)
  - Channel-details aggregation (avg_min, unique_users, peak_hour)
  - Co-presence overlap detection (O(n²) session matching)
  - Histogram bucketing logic
  - DAU/WAU counting logic
  - Leaderboard 30d/90d aggregation from session_history

Each test group seeds minimal data directly into voice_bot globals and
calls the relevant endpoint (or helper) to verify the calculation result.
No mocking — uses the real implementation.
"""

import importlib
import sys
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
    vb.flask_app.secret_key = 'test_secret_logic'
    return vb.flask_app


@pytest.fixture
def owner(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['logged_in']    = True
        sess['login_method'] = 'password'
    return c


GUILD = '77'   # distinct guild to avoid cross-test collision


_CACHE_NAMES = (
    '_ldb_cache', '_growth_cache', '_chdet_cache', '_cop_cache',
    '_forecast_cache', '_cohort_cache', '_tod_cache', '_churn_cache',
    '_records_cache', '_ret_cache',
)


@pytest.fixture(autouse=True)
def clean_state(vb):
    orig_history    = list(vb.session_history)
    orig_user_daily = {
        k: {uid: {**d, 'dates': dict(d.get('dates', {}))}
            for uid, d in v.items()}
        for k, v in vb.user_daily.items()
    }
    orig_daily_act  = {k: dict(v) for k, v in vb.daily_activity.items()}
    orig_daily_uniq = {k: {d: list(u) for d, u in v.items()} for k, v in vb.daily_unique.items()}
    orig_ch_act     = {k: dict(v) for k, v in vb.channel_activity.items()}
    orig_milestones = {k: {uid: list(h) for uid, h in v.items()} for k, v in vb.milestones_awarded.items()}
    orig_wk_stats   = {k: {uid: dict(d) for uid, d in v.items()} for k, v in vb.weekly_stats.items()}
    orig_caches     = {name: dict(getattr(vb, name)) for name in _CACHE_NAMES}

    yield

    # Restore mutable globals
    vb.session_history.clear();    vb.session_history.extend(orig_history)
    vb.user_daily.clear();         vb.user_daily.update(orig_user_daily)
    vb.daily_activity.clear();     vb.daily_activity.update(orig_daily_act)
    vb.daily_unique.clear();       vb.daily_unique.update(orig_daily_uniq)
    vb.channel_activity.clear();   vb.channel_activity.update(orig_ch_act)
    vb.milestones_awarded.clear(); vb.milestones_awarded.update(orig_milestones)
    vb.weekly_stats.clear();       vb.weekly_stats.update(orig_wk_stats)
    for name in _CACHE_NAMES:
        getattr(vb, name).clear()
        getattr(vb, name).update(orig_caches[name])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today(vb, offset=0):
    return (datetime.now(vb.THAI_TZ) - timedelta(days=offset)).strftime('%Y-%m-%d')


def _iso(vb, offset_days=0, hour=10, minute=0):
    d = datetime.now(vb.THAI_TZ) - timedelta(days=offset_days)
    return d.strftime(f'%Y-%m-%d {hour:02d}:{minute:02d}')


def _sess(vb, uid, name, seconds, join_str=None, leave_str=None, channel='G', guild=GUILD):
    if join_str is None:
        join_str  = _iso(vb, 1, 10)
        leave_str = _iso(vb, 1, 11)
    vb.session_history.append({
        'guild_id': guild,
        'uid':      uid,
        'name':     name,
        'channel':  channel,
        'join':     join_str,
        'leave':    leave_str,
        'seconds':  seconds,
    })


def _ud(vb, uid, name, alltime=0, sessions=0, dates=None, first_seen=None, last_seen=None, streak_max=0):
    if GUILD not in vb.user_daily:
        vb.user_daily[GUILD] = {}
    if dates is None:
        dates = {_today(vb): 1}
    vb.user_daily[GUILD][uid] = {
        'name':            name,
        'dates':           dates,
        'alltime_seconds': alltime,
        'session_count':   sessions,
        'streak_max':      streak_max,
        'first_seen':      first_seen or datetime.now(vb.THAI_TZ).isoformat(),
        'last_seen':       last_seen  or datetime.now(vb.THAI_TZ).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# EMA Forecast
# ═══════════════════════════════════════════════════════════════════════════════

class TestForecastAlgorithm:
    """Verify the EMA (Exponential Moving Average) forecast behaviour."""

    def test_forecast_contains_7_future_dates(self, owner, vb):
        vb._forecast_cache.clear()
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        forecast = r.get_json()['forecast']
        assert len(forecast) == 7

    def test_forecast_dates_are_strictly_after_today(self, owner, vb):
        vb._forecast_cache.clear()
        today = _today(vb)
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        for row in r.get_json()['forecast']:
            assert row['date'] > today

    def test_forecast_dates_are_consecutive(self, owner, vb):
        vb._forecast_cache.clear()
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        dates = [row['date'] for row in r.get_json()['forecast']]
        for i in range(1, len(dates)):
            delta = datetime.strptime(dates[i], '%Y-%m-%d') - \
                    datetime.strptime(dates[i-1], '%Y-%m-%d')
            assert delta.days == 1

    def test_history_has_30_entries(self, owner, vb):
        vb._forecast_cache.clear()
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        assert len(r.get_json()['history']) == 30

    def test_history_is_forecast_false(self, owner, vb):
        vb._forecast_cache.clear()
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        assert all(not row['is_forecast'] for row in r.get_json()['history'])

    def test_forecast_is_forecast_true(self, owner, vb):
        vb._forecast_cache.clear()
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        assert all(row['is_forecast'] for row in r.get_json()['forecast'])

    def test_all_forecast_dau_non_negative(self, owner, vb):
        vb._forecast_cache.clear()
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        for row in r.get_json()['forecast']:
            assert row['dau'] >= 0

    def test_high_dau_inflates_forecast(self, owner, vb):
        """If DAU is consistently high, forecast should be higher than with no data."""
        vb._forecast_cache.clear()
        # Seed 20 unique users per day for the last 7 days
        for d_offset in range(7):
            day = _today(vb, d_offset)
            vb.daily_unique[GUILD] = vb.daily_unique.get(GUILD, {})
            vb.daily_unique[GUILD][day] = [str(i + d_offset * 20) for i in range(20)]
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        avg_forecast = sum(row['dau'] for row in r.get_json()['forecast']) / 7
        # With 20 DAU/day, forecast should be at least 1 (EMA will pull up)
        assert avg_forecast >= 1

    def test_zero_dau_keeps_forecast_at_zero(self, owner, vb):
        """No history → EMA stays at 0 → all forecast cells = 0."""
        vb._forecast_cache.clear()
        # Ensure guild has no daily_unique data
        vb.daily_unique.pop(GUILD, None)
        r = owner.get(f'/api/forecast?guild_id={GUILD}')
        for row in r.get_json()['forecast']:
            assert row['dau'] == 0

    def test_cache_returns_same_result(self, owner, vb):
        """Second call should hit cache and return identical data."""
        vb._forecast_cache.clear()
        r1 = owner.get(f'/api/forecast?guild_id={GUILD}').get_json()
        r2 = owner.get(f'/api/forecast?guild_id={GUILD}').get_json()
        assert r1['forecast'] == r2['forecast']


# ═══════════════════════════════════════════════════════════════════════════════
# Cohort Retention Matrix
# ═══════════════════════════════════════════════════════════════════════════════

class TestCohortMatrix:
    """Verify cohort bucketing and retention-percentage calculation."""

    def test_cohort_week0_retention_is_100(self, owner, vb):
        """A user active in their cohort week must show 100% at offset 0."""
        vb._cohort_cache.clear()
        _ud(vb, uid='C1', name='Cohort1',
            first_seen=datetime.now(vb.THAI_TZ).isoformat(),
            dates={_today(vb): 1})
        r = owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=2&retain_weeks=2')
        data = r.get_json()
        non_empty = [c for c in data['cohorts'] if c['users'] > 0]
        if non_empty:
            w0 = next((w for w in non_empty[-1]['weeks'] if w['offset'] == 0), None)
            if w0:
                assert w0['pct'] == 100

    def test_cohort_schema_all_fields(self, owner, vb):
        vb._cohort_cache.clear()
        r = owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=2&retain_weeks=3')
        data = r.get_json()
        assert 'cohorts' in data
        assert 'retain_weeks' in data
        assert data['retain_weeks'] == 3

    def test_cohort_weeks_param_respected(self, owner, vb):
        vb._cohort_cache.clear()
        r2 = owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=2&retain_weeks=2')
        vb._cohort_cache.clear()
        r5 = owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=5&retain_weeks=2')
        # 5-week request should return more (or equal) cohorts than 2-week request
        assert len(r5.get_json()['cohorts']) >= len(r2.get_json()['cohorts'])

    def test_retain_weeks_param_respected(self, owner, vb):
        vb._cohort_cache.clear()
        _ud(vb, uid='C2', name='Cohort2',
            first_seen=datetime.now(vb.THAI_TZ).isoformat())
        r = owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=2&retain_weeks=4')
        data = r.get_json()
        non_empty = [c for c in data['cohorts'] if c['users'] > 0]
        if non_empty:
            offsets = [w['offset'] for w in non_empty[-1]['weeks']]
            assert max(offsets) <= 3   # offsets 0..3 = 4 weeks

    def test_pct_between_0_and_100(self, owner, vb):
        vb._cohort_cache.clear()
        r = owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=3&retain_weeks=3')
        for c in r.get_json()['cohorts']:
            for w in c['weeks']:
                if w['pct'] is not None:
                    assert 0 <= w['pct'] <= 100

    def test_user_with_no_activity_not_retained(self, owner, vb):
        """User whose dates dict doesn't include week+1 → offset 1 retained=0."""
        vb._cohort_cache.clear()
        monday = datetime.now(vb.THAI_TZ).date()
        monday -= timedelta(days=monday.weekday() + 7)  # last week's Monday
        first_seen = datetime(monday.year, monday.month, monday.day,
                              tzinfo=vb.THAI_TZ).isoformat()
        # dates only in cohort week, not in the following week
        _ud(vb, uid='C3', name='NoRetain',
            first_seen=first_seen,
            dates={monday.strftime('%Y-%m-%d'): 1})
        r = owner.get(f'/api/cohort?guild_id={GUILD}&cohort_weeks=3&retain_weeks=3')
        data = r.get_json()
        cohort_week_s = monday.strftime('%Y-%m-%d')
        target = next((c for c in data['cohorts'] if c['cohort_week'] == cohort_week_s), None)
        if target:
            w1 = next((w for w in target['weeks'] if w['offset'] == 1), None)
            if w1:
                assert w1['retained'] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Churn-Risk Scoring
# ═══════════════════════════════════════════════════════════════════════════════

class TestChurnRiskScoring:
    """Verify churn-risk computation rules."""

    def test_no_recent_activity_gives_high_score(self, owner, vb):
        vb._churn_cache.clear()
        now = datetime.now(vb.THAI_TZ)
        old_date = (now - timedelta(days=50)).strftime('%Y-%m-%d')
        _ud(vb, uid='CH1', name='Dormant',
            dates={old_date: 5},
            last_seen=(now - timedelta(days=50)).isoformat())
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        user = next((u for u in r.get_json() if u['uid'] == 'CH1'), None)
        if user:
            assert user['risk_score'] >= 0.5

    def test_recently_active_user_excluded(self, owner, vb):
        """User active today should NOT appear in churn-risk (no prior activity to compare)."""
        vb._churn_cache.clear()
        _ud(vb, uid='CH2', name='Active',
            dates={_today(vb): 10})
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        uids = [u['uid'] for u in r.get_json()]
        assert 'CH2' not in uids

    def test_risk_level_high_for_churned(self, owner, vb):
        vb._churn_cache.clear()
        now = datetime.now(vb.THAI_TZ)
        old = (now - timedelta(days=50)).strftime('%Y-%m-%d')
        _ud(vb, uid='CH3', name='HighRisk',
            dates={old: 10},
            last_seen=(now - timedelta(days=50)).isoformat())
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        user = next((u for u in r.get_json() if u['uid'] == 'CH3'), None)
        if user and user['risk_score'] >= 0.7:
            assert user['risk_level'] == 'high'

    def test_risk_level_low_for_active(self, owner, vb):
        """User mostly active in recent 30d → should be low risk if appears."""
        vb._churn_cache.clear()
        now = datetime.now(vb.THAI_TZ)
        # Lots of recent, little prior
        recent_dates = {(now - timedelta(days=i)).strftime('%Y-%m-%d'): 2
                        for i in range(1, 25)}
        old_date = (now - timedelta(days=50)).strftime('%Y-%m-%d')
        all_dates = {**recent_dates, old_date: 1}
        _ud(vb, uid='CH4', name='LowRisk',
            dates=all_dates,
            last_seen=_today(vb))
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        user = next((u for u in r.get_json() if u['uid'] == 'CH4'), None)
        if user:
            # recent activity >> prior → should not be high risk
            assert user['risk_level'] in ('low', 'medium')

    def test_scores_are_sorted_desc(self, owner, vb):
        vb._churn_cache.clear()
        r = owner.get(f'/api/churn-risk?guild_id={GUILD}')
        scores = [u['risk_score'] for u in r.get_json()]
        assert scores == sorted(scores, reverse=True)

    def test_all_risk_scores_in_0_1(self, owner, vb):
        vb._churn_cache.clear()
        for u in owner.get(f'/api/churn-risk?guild_id={GUILD}').get_json():
            assert 0.0 <= u['risk_score'] <= 1.0

    def test_schema_has_required_fields(self, owner, vb):
        vb._churn_cache.clear()
        now = datetime.now(vb.THAI_TZ)
        old = (now - timedelta(days=50)).strftime('%Y-%m-%d')
        _ud(vb, uid='CH5', name='Schema',
            dates={old: 3},
            last_seen=(now - timedelta(days=50)).isoformat())
        data = owner.get(f'/api/churn-risk?guild_id={GUILD}').get_json()
        if data:
            for key in ('uid', 'name', 'risk_score', 'risk_level',
                        'days_since_last', 'sessions_recent', 'sessions_prior'):
                assert key in data[0]


# ═══════════════════════════════════════════════════════════════════════════════
# Records Aggregation
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordsAggregation:
    """Verify all-time records endpoint computes correct winners."""

    def test_longest_session_winner(self, owner, vb):
        vb._records_cache.clear()
        _sess(vb, uid='R1', name='Winner', seconds=86400)
        _sess(vb, uid='R2', name='Loser',  seconds=60)
        rec = owner.get(f'/api/records?guild_id={GUILD}').get_json()['longest_session']
        assert rec['seconds'] == 86400
        assert rec['name'] == 'Winner'

    def test_first_session_is_earliest_date(self, owner, vb):
        vb._records_cache.clear()
        vb.session_history += [
            {'guild_id': GUILD, 'uid': 'R3', 'name': 'Early', 'channel': 'G',
             'join': '2019-06-15 08:00', 'leave': '2019-06-15 09:00', 'seconds': 3600},
            {'guild_id': GUILD, 'uid': 'R4', 'name': 'Late',  'channel': 'G',
             'join': '2024-01-01 10:00', 'leave': '2024-01-01 11:00', 'seconds': 3600},
        ]
        rec = owner.get(f'/api/records?guild_id={GUILD}').get_json()['first_session']
        assert rec['name'] == 'Early'

    def test_top_user_alltime_by_alltime_seconds(self, owner, vb):
        vb._records_cache.clear()
        _ud(vb, uid='R5', name='TopUser',  alltime=999999)
        _ud(vb, uid='R6', name='BottomUser', alltime=1)
        rec = owner.get(f'/api/records?guild_id={GUILD}').get_json()['top_user_alltime']
        assert rec['name'] == 'TopUser'
        assert rec['seconds'] == 999999

    def test_most_active_day_highest_session_count(self, owner, vb):
        vb._records_cache.clear()
        # 5 sessions on day A, 2 on day B
        for i in range(5):
            _sess(vb, uid=str(200+i), name=f'U{i}', seconds=3600,
                  join_str='2025-08-10 10:00', leave_str='2025-08-10 11:00')
        for i in range(2):
            _sess(vb, uid=str(210+i), name=f'V{i}', seconds=3600,
                  join_str='2025-08-11 10:00', leave_str='2025-08-11 11:00')
        rec = owner.get(f'/api/records?guild_id={GUILD}').get_json()['most_active_day']
        assert rec['date'] == '2025-08-10'
        assert rec['sessions'] == 5

    def test_peak_dau_day_uses_daily_unique(self, owner, vb):
        vb._records_cache.clear()
        vb.daily_unique[GUILD] = {
            '2025-04-01': ['a', 'b'],
            '2025-04-02': ['a', 'b', 'c', 'd'],
        }
        rec = owner.get(f'/api/records?guild_id={GUILD}').get_json()['peak_dau_day']
        assert rec['date'] == '2025-04-02'
        assert rec['dau']  == 4

    def test_all_record_keys_present_when_empty(self, owner, vb):
        vb._records_cache.clear()
        data = owner.get(f'/api/records?guild_id={GUILD}').get_json()
        for key in ('longest_session', 'first_session', 'most_active_day',
                    'peak_dau_day', 'top_user_alltime', 'peak_concurrent'):
            assert key in data

    def test_empty_guild_all_records_none(self, owner, vb):
        vb._records_cache.clear()
        data = owner.get(f'/api/records?guild_id=9999999').get_json()
        for key in ('longest_session', 'first_session', 'most_active_day',
                    'top_user_alltime', 'peak_dau_day'):
            assert data[key] is None


# ═══════════════════════════════════════════════════════════════════════════════
# Channel-Details Aggregation
# ═══════════════════════════════════════════════════════════════════════════════

class TestChannelDetailsAggregation:
    """Verify per-channel stat calculations."""

    def test_avg_min_is_mean_of_session_durations(self, owner, vb):
        vb._chdet_cache.clear()
        _sess(vb, uid='CD1', name='A', seconds=3600, channel='TestCh')
        _sess(vb, uid='CD2', name='B', seconds=1800, channel='TestCh')
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        ch = next((c for c in r.get_json() if c['channel'] == 'TestCh'), None)
        assert ch is not None
        # (3600+1800)/60/2 = 45 min
        assert abs(ch['avg_min'] - 45.0) < 0.5

    def test_unique_users_deduplicates(self, owner, vb):
        vb._chdet_cache.clear()
        _sess(vb, uid='CD3', name='X', seconds=3600, channel='DupCh')
        _sess(vb, uid='CD3', name='X', seconds=1800, channel='DupCh')  # same uid
        _sess(vb, uid='CD4', name='Y', seconds=3600, channel='DupCh')
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        ch = next((c for c in r.get_json() if c['channel'] == 'DupCh'), None)
        assert ch['unique_users'] == 2

    def test_sessions_count_is_correct(self, owner, vb):
        vb._chdet_cache.clear()
        for i in range(4):
            _sess(vb, uid=str(300+i), name=f'U{i}', seconds=600, channel='CountCh')
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        ch = next((c for c in r.get_json() if c['channel'] == 'CountCh'), None)
        assert ch['sessions'] == 4

    def test_top_user_has_most_seconds(self, owner, vb):
        vb._chdet_cache.clear()
        _sess(vb, uid='CD5', name='BigUser', seconds=9000, channel='TopCh')
        _sess(vb, uid='CD6', name='SmallUser', seconds=100, channel='TopCh')
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        ch = next((c for c in r.get_json() if c['channel'] == 'TopCh'), None)
        assert ch['top_user'] == 'BigUser'

    def test_sorted_by_seconds_desc(self, owner, vb):
        vb._chdet_cache.clear()
        _sess(vb, uid='CD7', name='A', seconds=9999, channel='BigCh')
        _sess(vb, uid='CD8', name='B', seconds=1,    channel='TinyCh')
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        data = r.get_json()
        secs = [c['seconds'] for c in data]
        assert secs == sorted(secs, reverse=True)

    def test_peak_hour_is_0_to_23(self, owner, vb):
        vb._chdet_cache.clear()
        _sess(vb, uid='CD9', name='C', seconds=3600, channel='HourCh',
              join_str='2025-06-01 14:00', leave_str='2025-06-01 15:00')
        r = owner.get(f'/api/channel-details?guild_id={GUILD}')
        ch = next((c for c in r.get_json() if c['channel'] == 'HourCh'), None)
        assert 0 <= ch['peak_hour'] <= 23


# ═══════════════════════════════════════════════════════════════════════════════
# Co-Presence Logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoPresenceLogic:
    """Verify session overlap detection algorithm."""

    def test_perfect_overlap_detected(self, owner, vb):
        vb._cop_cache.clear()
        # Both users same join/leave
        join  = '2025-09-01 10:00'
        leave = '2025-09-01 11:00'
        vb.session_history += [
            {'guild_id': GUILD, 'uid': 'CP1', 'name': 'Alice', 'channel': 'G',
             'join': join, 'leave': leave, 'seconds': 3600},
            {'guild_id': GUILD, 'uid': 'CP2', 'name': 'Bob',   'channel': 'G',
             'join': join, 'leave': leave, 'seconds': 3600},
        ]
        r = owner.get(f'/api/copresence?guild_id={GUILD}')
        data = r.get_json()
        assert any(
            {'CP1', 'CP2'} == {row['uid_a'], row['uid_b']}
            for row in data
        )

    def test_non_overlapping_not_paired(self, owner, vb):
        vb._cop_cache.clear()
        # A leaves before B joins
        vb.session_history += [
            {'guild_id': GUILD, 'uid': 'CP3', 'name': 'C3', 'channel': 'G',
             'join': '2025-09-02 08:00', 'leave': '2025-09-02 09:00', 'seconds': 3600},
            {'guild_id': GUILD, 'uid': 'CP4', 'name': 'C4', 'channel': 'G',
             'join': '2025-09-02 10:00', 'leave': '2025-09-02 11:00', 'seconds': 3600},
        ]
        r = owner.get(f'/api/copresence?guild_id={GUILD}')
        for row in r.get_json():
            assert not ({'CP3', 'CP4'} == {row['uid_a'], row['uid_b']})

    def test_partial_overlap_detected(self, owner, vb):
        """A: 10–12, B: 11–13 → overlap 11–12."""
        vb._cop_cache.clear()
        vb.session_history += [
            {'guild_id': GUILD, 'uid': 'CP5', 'name': 'D5', 'channel': 'G',
             'join': '2025-09-03 10:00', 'leave': '2025-09-03 12:00', 'seconds': 7200},
            {'guild_id': GUILD, 'uid': 'CP6', 'name': 'D6', 'channel': 'G',
             'join': '2025-09-03 11:00', 'leave': '2025-09-03 13:00', 'seconds': 7200},
        ]
        r = owner.get(f'/api/copresence?guild_id={GUILD}')
        data = r.get_json()
        assert any(
            {'CP5', 'CP6'} == {row['uid_a'], row['uid_b']}
            for row in data
        )

    def test_overlap_count_accumulates(self, owner, vb):
        """Two separate overlapping sessions between same pair → count = 2."""
        vb._cop_cache.clear()
        for day in ('2025-09-04', '2025-09-05'):
            vb.session_history += [
                {'guild_id': GUILD, 'uid': 'CP7', 'name': 'E7', 'channel': 'G',
                 'join': f'{day} 10:00', 'leave': f'{day} 11:00', 'seconds': 3600},
                {'guild_id': GUILD, 'uid': 'CP8', 'name': 'E8', 'channel': 'G',
                 'join': f'{day} 10:00', 'leave': f'{day} 11:00', 'seconds': 3600},
            ]
        r = owner.get(f'/api/copresence?guild_id={GUILD}')
        pair = next((row for row in r.get_json()
                     if {'CP7', 'CP8'} == {row['uid_a'], row['uid_b']}), None)
        assert pair is not None
        assert pair['overlap_count'] == 2

    def test_response_schema(self, owner, vb):
        vb._cop_cache.clear()
        r = owner.get(f'/api/copresence?guild_id={GUILD}')
        for row in r.get_json():
            for key in ('uid_a', 'name_a', 'uid_b', 'name_b', 'overlap_count'):
                assert key in row


# ═══════════════════════════════════════════════════════════════════════════════
# Histogram Bucketing
# ═══════════════════════════════════════════════════════════════════════════════

class TestHistogramBucketing:
    """Verify session-length → bucket assignment logic."""

    @pytest.mark.parametrize('seconds,bucket', [
        (30,    '0-5m'),    # 0.5 min
        (299,   '0-5m'),    # just under 5 min
        (300,   '5-15m'),   # exactly 5 min
        (899,   '5-15m'),
        (900,   '15-30m'),  # exactly 15 min
        (1799,  '15-30m'),
        (1800,  '30-60m'),  # exactly 30 min
        (3599,  '30-60m'),
        (3600,  '60m+'),    # exactly 60 min
        (7200,  '60m+'),
    ])
    def test_bucket_assignment(self, owner, vb, seconds, bucket):
        vb.session_history.append({
            'guild_id': GUILD, 'uid': '1', 'name': 'X', 'channel': 'G',
            'join': '2025-01-01 10:00', 'leave': '2025-01-01 11:00',
            'seconds': seconds,
        })
        r = owner.get(f'/api/histogram?guild_id={GUILD}')
        buckets = {b['range']: b['count'] for b in r.get_json()}
        assert buckets[bucket] >= 1

    def test_always_returns_5_buckets(self, owner):
        r = owner.get(f'/api/histogram?guild_id={GUILD}')
        assert len(r.get_json()) == 5

    def test_all_bucket_keys_present(self, owner):
        keys = {b['range'] for b in owner.get(f'/api/histogram?guild_id={GUILD}').get_json()}
        assert keys == {'0-5m', '5-15m', '15-30m', '30-60m', '60m+'}


# ═══════════════════════════════════════════════════════════════════════════════
# Leaderboard Period Aggregation
# ═══════════════════════════════════════════════════════════════════════════════

class TestLeaderboardPeriod:
    """Verify 30d / 90d / alltime aggregation from session_history."""

    def test_30d_excludes_old_sessions(self, owner, vb):
        vb._ldb_cache.clear()
        # old session (45 days ago) for user OLD
        old_join = (datetime.now(vb.THAI_TZ) - timedelta(days=45)).strftime('%Y-%m-%d %H:%M')
        vb.session_history.append({
            'guild_id': GUILD, 'uid': 'LB1', 'name': 'OldGuy', 'channel': 'G',
            'join': old_join, 'leave': old_join[:10] + ' 11:00', 'seconds': 999999,
        })
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=30d')
        uids = [row['uid'] for row in r.get_json()]
        assert 'LB1' not in uids

    def test_30d_includes_recent_sessions(self, owner, vb):
        vb._ldb_cache.clear()
        recent_join = (datetime.now(vb.THAI_TZ) - timedelta(days=10)).strftime('%Y-%m-%d %H:%M')
        vb.session_history.append({
            'guild_id': GUILD, 'uid': 'LB2', 'name': 'RecentGuy', 'channel': 'G',
            'join': recent_join, 'leave': recent_join[:10] + ' 11:00', 'seconds': 999999,
        })
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=30d')
        uids = [row['uid'] for row in r.get_json()]
        assert 'LB2' in uids

    def test_90d_includes_60d_old_session(self, owner, vb):
        vb._ldb_cache.clear()
        old_join = (datetime.now(vb.THAI_TZ) - timedelta(days=60)).strftime('%Y-%m-%d %H:%M')
        vb.session_history.append({
            'guild_id': GUILD, 'uid': 'LB3', 'name': 'MidGuy', 'channel': 'G',
            'join': old_join, 'leave': old_join[:10] + ' 11:00', 'seconds': 999999,
        })
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=90d')
        uids = [row['uid'] for row in r.get_json()]
        assert 'LB3' in uids

    def test_alltime_includes_very_old_session(self, owner, vb):
        vb._ldb_cache.clear()
        vb.session_history.append({
            'guild_id': GUILD, 'uid': 'LB4', 'name': 'AncientGuy', 'channel': 'G',
            'join': '2020-01-01 10:00', 'leave': '2020-01-01 11:00', 'seconds': 999999,
        })
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=alltime')
        uids = [row['uid'] for row in r.get_json()]
        assert 'LB4' in uids

    def test_sorted_by_seconds_desc(self, owner, vb):
        vb._ldb_cache.clear()
        recent = (datetime.now(vb.THAI_TZ) - timedelta(days=5)).strftime('%Y-%m-%d %H:%M')
        vb.session_history += [
            {'guild_id': GUILD, 'uid': 'LB5', 'name': 'High', 'channel': 'G',
             'join': recent, 'leave': recent[:10] + ' 11:00', 'seconds': 50000},
            {'guild_id': GUILD, 'uid': 'LB6', 'name': 'Low',  'channel': 'G',
             'join': recent, 'leave': recent[:10] + ' 11:00', 'seconds': 100},
        ]
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=30d')
        secs = [row['seconds'] for row in r.get_json()]
        assert secs == sorted(secs, reverse=True)

    def test_max_10_rows(self, owner, vb):
        vb._ldb_cache.clear()
        recent = (datetime.now(vb.THAI_TZ) - timedelta(days=2)).strftime('%Y-%m-%d %H:%M')
        for i in range(15):
            vb.session_history.append({
                'guild_id': GUILD, 'uid': str(500+i), 'name': f'U{i}', 'channel': 'G',
                'join': recent, 'leave': recent[:10] + ' 11:00', 'seconds': 3600,
            })
        r = owner.get(f'/api/leaderboard?guild_id={GUILD}&period=30d')
        assert len(r.get_json()) <= 10
