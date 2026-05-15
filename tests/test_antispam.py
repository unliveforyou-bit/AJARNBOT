"""
Tests for anti-spam and cooldown systems:
  record_voice_event / check_voice_spam
  check_cooldown
  check_command_rate
"""
import importlib
import sys
import pytest
from datetime import datetime, timedelta


@pytest.fixture(scope='module')
def vb():
    if 'voice_bot' in sys.modules:
        return sys.modules['voice_bot']
    return importlib.import_module('voice_bot')


@pytest.fixture(autouse=True)
def reset_trackers(vb):
    """Clear all spam/cooldown state before each test."""
    vb.voice_spam_tracker.clear()
    vb.mute_cooldown.clear()
    vb.command_rate_limit.clear()
    yield
    vb.voice_spam_tracker.clear()
    vb.mute_cooldown.clear()
    vb.command_rate_limit.clear()


# ── record_voice_event + check_voice_spam ────────────────────────────────────

def test_no_spam_on_first_events(vb):
    """Below threshold → not spam."""
    guild_id, member_id = '100', 1
    for _ in range(vb.SPAM_MAX_EVENTS - 1):
        vb.record_voice_event(guild_id, member_id)
    assert vb.check_voice_spam(guild_id, member_id) is False


def test_spam_detected_at_threshold(vb):
    """Exactly at SPAM_MAX_EVENTS → spam detected."""
    guild_id, member_id = '100', 2
    for _ in range(vb.SPAM_MAX_EVENTS):
        vb.record_voice_event(guild_id, member_id)
    assert vb.check_voice_spam(guild_id, member_id) is True


def test_spam_detected_above_threshold(vb):
    """More than threshold → still spam."""
    guild_id, member_id = '100', 3
    for _ in range(vb.SPAM_MAX_EVENTS + 3):
        vb.record_voice_event(guild_id, member_id)
    assert vb.check_voice_spam(guild_id, member_id) is True


def test_different_members_are_independent(vb):
    """Spam tracker is per (guild, member) — one member spamming doesn't flag another."""
    guild_id = '200'
    spammer, innocent = 10, 20
    for _ in range(vb.SPAM_MAX_EVENTS):
        vb.record_voice_event(guild_id, spammer)
    assert vb.check_voice_spam(guild_id, spammer) is True
    assert vb.check_voice_spam(guild_id, innocent) is False


def test_different_guilds_are_independent(vb):
    """Spam is scoped per guild — events in guild A don't affect guild B."""
    member_id = 99
    for _ in range(vb.SPAM_MAX_EVENTS):
        vb.record_voice_event('GUILD_A', member_id)
    assert vb.check_voice_spam('GUILD_A', member_id) is True
    assert vb.check_voice_spam('GUILD_B', member_id) is False


def test_old_events_expire_from_window(vb):
    """Events older than spam_window_sec should not count."""
    guild_id, member_id = '300', 5
    now = datetime.now(vb.THAI_TZ)
    old = now - timedelta(seconds=vb.SPAM_WINDOW_SEC + 5)
    # Manually plant old timestamps
    vb.voice_spam_tracker[(guild_id, member_id)] = [old] * vb.SPAM_MAX_EVENTS
    # record_voice_event prunes stale entries → old ones removed → counter resets
    vb.record_voice_event(guild_id, member_id)
    assert vb.check_voice_spam(guild_id, member_id) is False


# ── check_cooldown ────────────────────────────────────────────────────────────

def test_cooldown_allows_first_event(vb):
    """First call for a member/event → allowed (True)."""
    assert vb.check_cooldown(member_id=1, event='mute') is True


def test_cooldown_blocks_immediate_repeat(vb):
    """Second call within cooldown period → blocked (False)."""
    vb.check_cooldown(member_id=2, event='mute')
    assert vb.check_cooldown(member_id=2, event='mute') is False


def test_cooldown_independent_per_event_type(vb):
    """Cooldown is per (member, event) — different events don't interfere."""
    vb.check_cooldown(member_id=3, event='mute')
    # 'deaf' is a different event → should be allowed immediately
    assert vb.check_cooldown(member_id=3, event='deaf') is True


def test_cooldown_independent_per_member(vb):
    """Cooldown is per member — one member blocked doesn't affect another."""
    vb.check_cooldown(member_id=4, event='mute')
    assert vb.check_cooldown(member_id=4, event='mute') is False
    assert vb.check_cooldown(member_id=5, event='mute') is True


def test_cooldown_expires_after_window(vb):
    """After cooldown period passes, the same event is allowed again."""
    mid = 6
    vb.check_cooldown(mid, 'stream')
    # Manually backdate the cooldown entry
    key = (mid, 'stream')
    vb.mute_cooldown[key] = datetime.now(vb.THAI_TZ) - timedelta(seconds=10)
    assert vb.check_cooldown(mid, 'stream') is True


# ── check_command_rate ────────────────────────────────────────────────────────

def test_command_rate_allows_first_call(vb):
    assert vb.check_command_rate(user_id=10, cmd='joke') is True


def test_command_rate_blocks_immediate_repeat(vb):
    vb.check_command_rate(user_id=11, cmd='trivia')
    assert vb.check_command_rate(user_id=11, cmd='trivia') is False


def test_command_rate_independent_per_command(vb):
    """Different commands have separate rate limits."""
    vb.check_command_rate(user_id=12, cmd='joke')
    assert vb.check_command_rate(user_id=12, cmd='trivia') is True


def test_command_rate_independent_per_user(vb):
    """Rate limit per user — one blocked user doesn't block others."""
    vb.check_command_rate(user_id=13, cmd='joke')
    assert vb.check_command_rate(user_id=13, cmd='joke') is False
    assert vb.check_command_rate(user_id=14, cmd='joke') is True


def test_command_rate_expires(vb):
    """After COMMAND_COOLDOWN_SEC passes, command is allowed again."""
    uid = 15
    vb.check_command_rate(uid, 'rank')
    key = (uid, 'rank')
    vb.command_rate_limit[key] = datetime.now(vb.THAI_TZ) - timedelta(seconds=vb.COMMAND_COOLDOWN_SEC + 1)
    assert vb.check_command_rate(uid, 'rank') is True
