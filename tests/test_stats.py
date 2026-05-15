"""
Unit Tests — AjarnBot  (bot_utils.py)
รัน: python -m pytest tests/ -v
"""
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# import เฉพาะ pure functions — ไม่ต้องแตะ Discord/Flask เลย
from bot_utils import format_duration, get_stats_for_period, register_joke_msg, MAX_ACTIVE_JOKES

THAI_TZ = ZoneInfo('Asia/Bangkok')


# ===========================================================================
# 1. format_duration
# ===========================================================================
class TestFormatDuration(unittest.TestCase):
    """ทดสอบการแปลงวินาที → ข้อความ"""

    def test_zero_seconds(self):
        self.assertEqual(format_duration(0), '0 นาที')

    def test_minutes_only(self):
        self.assertEqual(format_duration(60),   '1 นาที')
        self.assertEqual(format_duration(3599), '59 นาที')

    def test_minutes_floor(self):
        """30 วินาที → 0 นาที  (floor division)"""
        self.assertEqual(format_duration(30), '0 นาที')

    def test_hours_and_minutes(self):
        result = format_duration(3600)       # 1h 0m
        self.assertIn('1 ชม.', result)
        self.assertIn('0 นาที', result)
        self.assertNotIn('วัน', result)

        result = format_duration(3661)       # 1h 1m
        self.assertIn('1 ชม.', result)
        self.assertIn('1 นาที', result)

        result = format_duration(7320)       # 2h 2m
        self.assertIn('2 ชม.', result)
        self.assertIn('2 นาที', result)

    def test_days(self):
        result = format_duration(86400)      # 1d 0h 0m
        self.assertIn('1 วัน', result)

        result = format_duration(86400 + 3661)  # 1d 1h 1m
        self.assertIn('1 วัน', result)
        self.assertIn('1 ชม.', result)
        self.assertIn('1 นาที', result)

    def test_large_value(self):
        secs = 7 * 86400 + 2 * 3600 + 5 * 60   # 7d 2h 5m
        result = format_duration(secs)
        self.assertIn('7 วัน', result)
        self.assertIn('2 ชม.', result)
        self.assertIn('5 นาที', result)

    def test_no_day_label_when_hours(self):
        self.assertNotIn('วัน', format_duration(3600))

    def test_no_hour_label_when_minutes_only(self):
        self.assertNotIn('ชม.', format_duration(300))


# ===========================================================================
# 2. get_stats_for_period
# ===========================================================================
class TestGetStatsForPeriod(unittest.TestCase):
    """ทดสอบการรวมสถิติ voice ตามช่วงเวลา"""

    def _session(self, join_dt, seconds=600, uid='u1',
                 name='TestUser', guild_id='g1'):
        return {
            'uid': uid, 'name': name,
            'join': join_dt.strftime('%Y-%m-%d %H:%M'),
            'seconds': seconds, 'guild_id': guild_id,
        }

    # ---- today -------------------------------------------------------

    def test_today_includes_today(self):
        now = datetime.now(THAI_TZ)
        history = [self._session(now, seconds=300)]
        result = get_stats_for_period(history, {}, 'today')
        self.assertIn('u1', result)
        self.assertEqual(result['u1']['seconds'], 300)

    def test_today_excludes_yesterday(self):
        yesterday = datetime.now(THAI_TZ) - timedelta(days=1)
        history = [self._session(yesterday)]
        result = get_stats_for_period(history, {}, 'today')
        self.assertNotIn('u1', result)

    # ---- week --------------------------------------------------------

    def test_week_includes_monday(self):
        now = datetime.now(THAI_TZ)
        monday = now - timedelta(days=now.weekday())
        history = [self._session(monday, seconds=1000)]
        result = get_stats_for_period(history, {}, 'week')
        self.assertIn('u1', result)
        self.assertEqual(result['u1']['seconds'], 1000)

    def test_week_excludes_last_monday(self):
        now = datetime.now(THAI_TZ)
        last_monday = now - timedelta(days=now.weekday() + 7)
        history = [self._session(last_monday)]
        result = get_stats_for_period(history, {}, 'week')
        self.assertNotIn('u1', result)

    # ---- month -------------------------------------------------------

    def test_month_includes_first_of_month(self):
        now = datetime.now(THAI_TZ)
        first = now.replace(day=1, hour=10, minute=0)
        history = [self._session(first, seconds=500)]
        result = get_stats_for_period(history, {}, 'month')
        self.assertIn('u1', result)

    def test_month_excludes_last_month(self):
        now = datetime.now(THAI_TZ)
        last_month = now.replace(day=1) - timedelta(days=1)
        history = [self._session(last_month)]
        result = get_stats_for_period(history, {}, 'month')
        self.assertNotIn('u1', result)

    # ---- guild filter ------------------------------------------------

    def test_guild_filter_includes_match(self):
        now = datetime.now(THAI_TZ)
        history = [self._session(now, uid='u1', guild_id='g1'),
                   self._session(now, uid='u2', guild_id='g2')]
        result = get_stats_for_period(history, {}, 'week', guild_id='g1')
        self.assertIn('u1', result)
        self.assertNotIn('u2', result)

    def test_no_filter_returns_all_guilds(self):
        now = datetime.now(THAI_TZ)
        history = [self._session(now, uid='u1', guild_id='g1'),
                   self._session(now, uid='u2', guild_id='g2')]
        result = get_stats_for_period(history, {}, 'week')
        self.assertIn('u1', result)
        self.assertIn('u2', result)

    # ---- accumulation ------------------------------------------------

    def test_accumulates_multiple_sessions(self):
        now = datetime.now(THAI_TZ)
        history = [self._session(now, uid='u1', seconds=300),
                   self._session(now, uid='u1', seconds=700)]
        result = get_stats_for_period(history, {}, 'week')
        self.assertEqual(result['u1']['seconds'], 1000)

    def test_multiple_users_independent(self):
        now = datetime.now(THAI_TZ)
        history = [self._session(now, uid='u1', seconds=200),
                   self._session(now, uid='u2', seconds=400)]
        result = get_stats_for_period(history, {}, 'week')
        self.assertEqual(result['u1']['seconds'], 200)
        self.assertEqual(result['u2']['seconds'], 400)

    # ---- edge / bad data ---------------------------------------------

    def test_bad_join_format_is_skipped(self):
        bad = {'uid': 'u1', 'name': 'X', 'join': 'NOT-A-DATE', 'seconds': 100, 'guild_id': 'g1'}
        result = get_stats_for_period([bad], {}, 'week')
        self.assertNotIn('u1', result)

    def test_missing_join_key_is_skipped(self):
        bad = {'uid': 'u1', 'name': 'X', 'seconds': 100, 'guild_id': 'g1'}
        result = get_stats_for_period([bad], {}, 'week')
        self.assertNotIn('u1', result)

    def test_empty_history_returns_empty(self):
        self.assertEqual(get_stats_for_period([], {}, 'week'), {})

    # ---- live voice users --------------------------------------------

    def test_live_user_adds_elapsed(self):
        join_time = datetime.now(THAI_TZ) - timedelta(seconds=120)
        vjt = {(1, 999): ('LiveUser', join_time, 'General')}
        result = get_stats_for_period([], vjt, 'week')
        self.assertIn('999', result)
        self.assertGreaterEqual(result['999']['seconds'], 120)

    def test_live_user_guild_filter(self):
        join_time = datetime.now(THAI_TZ) - timedelta(seconds=60)
        vjt = {(2, 888): ('OtherGuild', join_time, 'General')}
        result = get_stats_for_period([], vjt, 'week', guild_id='1')
        self.assertNotIn('888', result)

    def test_live_user_combines_with_history(self):
        now = datetime.now(THAI_TZ)
        history = [self._session(now, uid='u1', seconds=300)]
        join_time = now - timedelta(seconds=100)
        vjt = {(1, 'u1'): ('TestUser', join_time, 'General')}
        result = get_stats_for_period(history, vjt, 'week')
        self.assertGreaterEqual(result['u1']['seconds'], 400)


# ===========================================================================
# 3. register_joke_msg
# ===========================================================================
class TestRegisterJokeMsg(unittest.TestCase):
    """ทดสอบ LRU-style joke cache"""

    def setUp(self):
        self.cache: dict = {}

    def test_stores_joke(self):
        register_joke_msg(self.cache, 1, 'joke text')
        self.assertEqual(self.cache[1], 'joke text')

    def test_multiple_jokes(self):
        register_joke_msg(self.cache, 1, 'joke 1')
        register_joke_msg(self.cache, 2, 'joke 2')
        self.assertEqual(len(self.cache), 2)

    def test_evicts_oldest_at_limit(self):
        for i in range(MAX_ACTIVE_JOKES):
            register_joke_msg(self.cache, i, f'joke {i}')
        self.assertEqual(len(self.cache), MAX_ACTIVE_JOKES)

        # ตัวที่ MAX+1 → key=0 ถูกลบ
        register_joke_msg(self.cache, MAX_ACTIVE_JOKES, 'overflow')
        self.assertNotIn(0, self.cache)
        self.assertEqual(len(self.cache), MAX_ACTIVE_JOKES)

    def test_overwrites_existing_key(self):
        register_joke_msg(self.cache, 1, 'old')
        register_joke_msg(self.cache, 1, 'new')
        self.assertEqual(self.cache[1], 'new')

    def test_does_not_evict_below_limit(self):
        for i in range(MAX_ACTIVE_JOKES - 1):
            register_joke_msg(self.cache, i, f'joke {i}')
        self.assertEqual(len(self.cache), MAX_ACTIVE_JOKES - 1)
        self.assertIn(0, self.cache)


if __name__ == '__main__':
    unittest.main(verbosity=2)
