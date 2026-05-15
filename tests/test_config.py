"""
Tests for get_gc() config inheritance and GUILD_ADMIN_KEYS.
"""
import importlib
import sys
import pytest


@pytest.fixture(scope='module')
def vb():
    """Import voice_bot once per module (env vars already set by conftest.py)."""
    if 'voice_bot' in sys.modules:
        return sys.modules['voice_bot']
    return importlib.import_module('voice_bot')


@pytest.fixture(autouse=True)
def clean_configs(vb):
    """Reset guild_configs and bot_config between tests."""
    original_gc = dict(vb.guild_configs)
    original_bc = dict(vb.bot_config)
    yield
    vb.guild_configs.clear()
    vb.guild_configs.update(original_gc)
    vb.bot_config.clear()
    vb.bot_config.update(original_bc)


# ── get_gc() inheritance ──────────────────────────────────────────────────────

def test_get_gc_returns_global_when_no_guild_config(vb):
    """No guild override → returns bot_config value."""
    vb.bot_config['announce_join'] = True
    assert vb.get_gc('999', 'announce_join') is True


def test_get_gc_guild_override_takes_priority(vb):
    """Per-guild value shadows bot_config."""
    vb.bot_config['announce_join'] = True
    vb.guild_configs['123'] = {'announce_join': False}
    assert vb.get_gc('123', 'announce_join') is False


def test_get_gc_int_guild_id_converted(vb):
    """int guild_id should work (converted to str internally)."""
    vb.guild_configs['456'] = {'joke_delay': 99}
    assert vb.get_gc(456, 'joke_delay') == 99


def test_get_gc_partial_override_falls_back(vb):
    """Key not in guild override → falls back to bot_config."""
    vb.bot_config['trivia_delay'] = 20
    vb.guild_configs['789'] = {'joke_delay': 5}   # trivia_delay not set
    assert vb.get_gc('789', 'trivia_delay') == 20
    assert vb.get_gc('789', 'joke_delay') == 5


def test_get_gc_default_when_missing_everywhere(vb):
    """Key absent from both guild and bot_config → returns provided default."""
    vb.bot_config.pop('nonexistent_key', None)
    assert vb.get_gc('000', 'nonexistent_key', default='fallback') == 'fallback'


def test_get_gc_none_guild_id_uses_global(vb):
    """Passing guild_id=None → uses bot_config only."""
    vb.bot_config['spam_max_events'] = 7
    assert vb.get_gc(None, 'spam_max_events') == 7


# ── GUILD_ADMIN_KEYS contents ─────────────────────────────────────────────────

def test_guild_admin_keys_contains_channel_keys(vb):
    for key in ('channel_voice', 'channel_content', 'channel_stats'):
        assert key in vb.GUILD_ADMIN_KEYS, f'{key} missing from GUILD_ADMIN_KEYS'


def test_guild_admin_keys_contains_announce_toggles(vb):
    for key in ('announce_join', 'announce_leave', 'announce_move',
                'announce_mute', 'announce_deaf', 'announce_stream', 'announce_video'):
        assert key in vb.GUILD_ADMIN_KEYS


def test_guild_admin_keys_contains_spam_params(vb):
    for key in ('spam_max_events', 'spam_window_sec', 'mute_cooldown_sec'):
        assert key in vb.GUILD_ADMIN_KEYS


def test_guild_admin_keys_contains_delay_params(vb):
    for key in ('joke_delay', 'trivia_delay', 'content_interval'):
        assert key in vb.GUILD_ADMIN_KEYS
