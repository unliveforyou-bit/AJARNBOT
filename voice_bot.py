"""
VoiceLog Bot — Cloud version (Railway)
ไม่มี pystray / plyer / Windows-specific code
ใช้ environment variables สำหรับ token และ channel ID
"""
APP_VERSION = '3.2.0'
APP_BUILD_DATE = '2026-05-18'
import discord
from discord.ext import tasks
from discord.ext import commands as _commands
from discord import app_commands
import random, os, sys, asyncio, threading, json, secrets, urllib.request, urllib.parse, re, hmac, tempfile, time
import logging
import logging.handlers
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, Response, redirect, session as flask_session, render_template
from flask_wtf.csrf import CSRFProtect, validate_csrf, ValidationError
from functools import wraps
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _limiter_available = True
except ImportError:
    _limiter_available = False

# ===== Thread-safety Locks =====
_lock_stats   = threading.Lock()
_lock_history = threading.Lock()
_lock_votes   = threading.Lock()
_lock_config  = threading.Lock()
_lock_guild   = threading.Lock()
_lock_hourly  = threading.Lock()
_lock_log     = threading.Lock()
_lock_daily           = threading.Lock()
_lock_user_daily      = threading.Lock()
_lock_trivia          = threading.Lock()
_lock_event_counts    = threading.Lock()
_lock_active_sessions = threading.Lock()
_lock_spam            = threading.Lock()
_lock_mute_cooldown   = threading.Lock()
# ================================

THAI_TZ = ZoneInfo('Asia/Bangkok')

# ===== Environment Variables =====
TOKEN                = os.environ['DISCORD_TOKEN']           # required
VOICE_LOG_CHANNEL_ID = int(os.environ['VOICE_LOG_CHANNEL_ID'])  # required
DASHBOARD_PORT       = int(os.environ.get('PORT', 5000))
DASHBOARD_PASSWORD   = os.environ.get('DASHBOARD_PASSWORD', '')  # emergency owner access
OUTBOUND_WEBHOOK_URL = os.environ.get('OUTBOUND_WEBHOOK_URL', '')
DASHBOARD_API_KEY    = os.environ.get('DASHBOARD_API_KEY', '')
DISCORD_CLIENT_ID    = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')
DISCORD_REDIRECT_URI = os.environ.get('DISCORD_REDIRECT_URI', '')
DASHBOARD_BASE_URL   = os.environ.get('DASHBOARD_BASE_URL', 'https://ajarnbot.up.railway.app')
# OWNER_IDS: comma-separated Discord user IDs who have full access (global config)
OWNER_IDS = {uid.strip() for uid in os.environ.get('OWNER_IDS', '').split(',') if uid.strip()}
GOOGLE_SHEET_ID           = os.environ.get('GOOGLE_SHEET_ID', '')
GOOGLE_SHEETS_CREDENTIALS = os.environ.get('GOOGLE_SHEETS_CREDENTIALS', '')  # JSON string
SHEETS_OWNER_EMAIL        = os.environ.get('SHEETS_OWNER_EMAIL', '')  # Gmail to share sheet with
GOOGLE_CREDENTIALS        = os.environ.get('GOOGLE_CREDENTIALS', '')  # service-account JSON for form sheet
FORM_SHEET_ID             = os.environ.get('FORM_SHEET_ID', '1Vjz2MhuUnQOhna79EtWJhwvLOg8TebZb27RccSlQcbE')
NOTION_TOKEN       = os.environ.get('NOTION_TOKEN', '')        # Notion Integration token
NOTION_DATABASE_ID = os.environ.get('NOTION_DATABASE_ID', '')  # Notion Database ID

# ===== Startup config validation =====
_FLASK_SECRET_RAW = os.environ.get('FLASK_SECRET', '')
if not _FLASK_SECRET_RAW:
    raise RuntimeError(
        'FLASK_SECRET env var is not set.\n'
        'Generate one with:  openssl rand -hex 32\n'
        'Then add it to Railway Variables.'
    )
if OUTBOUND_WEBHOOK_URL and not OUTBOUND_WEBHOOK_URL.startswith('https://'):
    raise ValueError(
        f'OUTBOUND_WEBHOOK_URL must start with https:// to prevent SSRF. Got: {OUTBOUND_WEBHOOK_URL!r}'
    )
# =====================================
# =================================

# ===== Paths =====
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') or os.path.join(BASE_DIR, 'data')
_vol = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
print(f'[DATA] storage → {DATA_DIR}  ({"persistent volume ✓" if _vol else "⚠ ephemeral — set RAILWAY_VOLUME_MOUNT_PATH"})')
JOKES_FILE   = os.path.join(BASE_DIR, 'jokes.txt')
TRIVIA_FILE  = os.path.join(BASE_DIR, 'trivia.txt')
STATS_FILE   = os.path.join(DATA_DIR, 'voice_stats.json')
CONFIG_FILE  = os.path.join(DATA_DIR, 'bot_config.json')
HOURLY_FILE  = os.path.join(DATA_DIR, 'hourly_activity.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'session_history.json')
VOTES_FILE   = os.path.join(DATA_DIR, 'joke_votes.json')
LOG_FILE     = os.path.join(DATA_DIR, 'bot.log')
TRIVIA_SCORES_FILE  = os.path.join(DATA_DIR, 'trivia_scores.json')
GUILD_CONFIGS_FILE  = os.path.join(DATA_DIR, 'guild_configs.json')
EVENT_COUNTS_FILE        = os.path.join(DATA_DIR, 'event_counts.json')
ACTIVE_SESSIONS_FILE     = os.path.join(DATA_DIR, 'active_voice_sessions.json')
DAILY_FILE           = os.path.join(DATA_DIR, 'daily_activity.json')
USER_DAILY_FILE      = os.path.join(DATA_DIR, 'user_daily.json')
MILESTONES_FILE      = os.path.join(DATA_DIR, 'milestones.json')
CHANNEL_ACTIVITY_FILE = os.path.join(DATA_DIR, 'channel_activity.json')
os.makedirs(DATA_DIR, exist_ok=True)

def _atomic_json_dump(data: object, filepath: str, **kwargs) -> None:
    """Write JSON atomically — temp file + os.replace to prevent corrupt files on crash."""
    dir_ = os.path.dirname(filepath) or '.'
    with tempfile.NamedTemporaryFile('w', dir=dir_, delete=False, suffix='.tmp',
                                    encoding='utf-8') as tmp:
        json.dump(data, tmp, **kwargs)
        tmp_path = tmp.name
    os.replace(tmp_path, filepath)

# Warn early if no Railway persistent volume is configured
if not os.environ.get('RAILWAY_VOLUME_MOUNT_PATH'):
    print('⚠️  WARNING: RAILWAY_VOLUME_MOUNT_PATH not set — data is stored in ephemeral container storage.')
    print('⚠️  All stats/history/config WILL BE LOST on every Railway deploy!')
    print('⚠️  Fix: Railway dashboard → your service → Volumes → Add Volume → mount at /data')
# =================

MAX_HISTORY      = 200
MAX_ACTIVE_JOKES = 50

# ===== Config =====
bot_config = {
    'announce_join':            True,
    'announce_leave':           True,
    'announce_move':            True,
    'announce_mute':            True,
    'announce_deaf':            True,
    'announce_stream':          True,
    'announce_video':           True,
    'send_content':             True,
    'send_jokes':               False,
    'send_trivia':              False,
    'send_ready_message':       True,
    'joke_delay':               15,
    'trivia_delay':             15,
    'mute_cooldown_sec':        3,
    'content_interval':         30,
    'summary_hour':             9,
    'joke_downvote_threshold':  3,
    'channel_voice':   VOICE_LOG_CHANNEL_ID,
    'channel_content': VOICE_LOG_CHANNEL_ID,
    'channel_stats':   VOICE_LOG_CHANNEL_ID,
    'spam_max_events': 5,
    'spam_window_sec': 60,
}

def load_config():
    with _lock_config:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, encoding='utf-8') as f:
                bot_config.update(json.load(f))

def save_config():
    with _lock_config:
        _atomic_json_dump(bot_config, CONFIG_FILE, ensure_ascii=False, indent=2)
# ==================

# ===== Per-guild Config =====
# guild_configs[guild_id_str] stores per-guild overrides.
# Any key not set here falls back to the global bot_config default.
# Guild admins can override: channels, announce toggles, content settings, spam params.
# Owner-only global settings (via /api/config) serve as defaults for all guilds.
guild_configs = {}

# Keys that guild admins are allowed to set (non-owner users)
GUILD_ADMIN_KEYS = {
    'channel_voice', 'channel_content', 'channel_stats',
    'announce_join', 'announce_leave', 'announce_move',
    'announce_mute', 'announce_deaf', 'announce_stream', 'announce_video',
    'send_content', 'send_jokes', 'send_trivia', 'send_ready_message',
    'joke_delay', 'trivia_delay', 'content_interval',
    'summary_hour', 'joke_downvote_threshold',
    'spam_max_events', 'spam_window_sec', 'mute_cooldown_sec',
}

def get_gc(guild_id, key, default=None):
    """Get per-guild config value, falling back to global bot_config, then default."""
    gid = str(guild_id) if guild_id else ''
    val = guild_configs.get(gid, {}).get(key)
    if val is None:
        val = bot_config.get(key, default)
    return val

def load_guild_configs():
    global guild_configs
    with _lock_guild:
        if os.path.exists(GUILD_CONFIGS_FILE):
            with open(GUILD_CONFIGS_FILE, encoding='utf-8') as f:
                guild_configs = json.load(f)

def save_guild_configs():
    with _lock_guild:
        _atomic_json_dump(guild_configs, GUILD_CONFIGS_FILE, ensure_ascii=False, indent=2)
# ============================

# ===== Jokes / Trivia =====
JOKES_FALLBACK = [
    "ทำไมปลาถึงไม่เล่น Facebook? เพราะกลัวติดแหอินเทอร์เน็ต",
    "ทำไมโปรแกรมเมอร์ถึงชอบ dark mode? เพราะ light attracts bugs",
]

def load_jokes(include_filtered=False, guild_id=None):
    threshold   = get_gc(guild_id, 'joke_downvote_threshold', 3) if guild_id else bot_config.get('joke_downvote_threshold', 3)
    jokes       = []
    current_cat = 'มุขทั่วไป'
    if os.path.exists(JOKES_FILE):
        with open(JOKES_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('# [') and line.endswith(']'):
                    current_cat = line[3:-1]
                elif len(line) > 10:
                    v = joke_votes.get(line, {})
                    if include_filtered or v.get('down', 0) < threshold:
                        jokes.append((current_cat, line))
    return jokes if jokes else [('มุขทั่วไป', j) for j in JOKES_FALLBACK]

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002500-\U00002BFF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+", flags=re.UNICODE
)
def strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub('', text).strip()

def load_trivia():
    if os.path.exists(TRIVIA_FILE):
        items = []
        with open(TRIVIA_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '|' not in line or line.startswith('#'):
                    continue
                q, a = line.split('|', 1)
                q = strip_emoji(q).strip()
                a = strip_emoji(a).strip()
                if q and a:
                    items.append(f'{q}|{a}')
        return items
    return []
# ==========================

# ===== Voice Stats (Multi-guild) =====
voice_join_times  = {}   # {(guild_id, member_id): (display_name, join_time, channel_name)}
weekly_stats      = {}   # {guild_id: {user_id: {'name': str, 'seconds': int}}}
summary_sent      = {}   # {guild_id_str: bool} — tracks if summary already sent this week per guild
daily_digest_sent = {}   # {guild_id_str: str} — date string "YYYY-MM-DD" of last digest sent

def load_stats():
    global weekly_stats
    with _lock_stats:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, encoding='utf-8') as f:
                weekly_stats = json.load(f)

def save_stats():
    with _lock_stats:
        _atomic_json_dump(weekly_stats, STATS_FILE, ensure_ascii=False, indent=2)

from bot_utils import format_duration  # pure function — tested in tests/
# =====================================

# ===== Heatmap (Multi-guild) =====
hourly_activity = {}   # {guild_id: {hour_str: int}}

def load_hourly():
    global hourly_activity
    with _lock_hourly:
        if os.path.exists(HOURLY_FILE):
            with open(HOURLY_FILE, encoding='utf-8') as f:
                hourly_activity = json.load(f)

def save_hourly():
    with _lock_hourly:
        _atomic_json_dump(hourly_activity, HOURLY_FILE)
# =================================

# ===== Session History =====
session_history = []

def load_history():
    global session_history
    with _lock_history:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, encoding='utf-8') as f:
                session_history = json.load(f)

def save_history():
    with _lock_history:
        _atomic_json_dump(session_history[-MAX_HISTORY:], HISTORY_FILE, ensure_ascii=False, indent=2)
# ===========================

# ===== Joke Votes =====
joke_votes          = {}
active_joke_msgs    = {}
active_joke_channels = set()   # channel_ids ที่กำลัง deliver joke อยู่ (ป้องกันซ้อน)

def load_votes():
    global joke_votes
    with _lock_votes:
        if os.path.exists(VOTES_FILE):
            with open(VOTES_FILE, encoding='utf-8') as f:
                joke_votes = json.load(f)

def save_votes():
    with _lock_votes:
        _atomic_json_dump(joke_votes, VOTES_FILE, ensure_ascii=False, indent=2)

def register_joke_msg(msg_id, joke_text):
    active_joke_msgs[msg_id] = joke_text
    if len(active_joke_msgs) > MAX_ACTIVE_JOKES:
        active_joke_msgs.pop(next(iter(active_joke_msgs)))
# ======================

# ===== Trivia Scores =====
trivia_scores = {}       # {guild_id: {user_id: {'name': str, 'score': int}}}
active_trivia = {}       # {channel_id: {'answer': str, 'question': str, 'expires': datetime isoformat}}
TRIVIA_ANSWER_WINDOW = 30  # วินาที

def load_trivia_scores():
    global trivia_scores
    with _lock_trivia:
        if os.path.exists(TRIVIA_SCORES_FILE):
            with open(TRIVIA_SCORES_FILE, encoding='utf-8') as f:
                trivia_scores = json.load(f)

def save_trivia_scores():
    with _lock_trivia:
        _atomic_json_dump(trivia_scores, TRIVIA_SCORES_FILE, ensure_ascii=False, indent=2)
# =========================

# ===== Anti-spam =====
voice_spam_tracker = {}  # {(guild_id, member_id): [timestamps]}
SPAM_WINDOW_SEC = 60
SPAM_MAX_EVENTS = 5

def fire_outbound_webhook(event, payload):
    """ส่ง event ไปยัง OUTBOUND_WEBHOOK_URL แบบ non-blocking"""
    if not OUTBOUND_WEBHOOK_URL:
        return
    def _send():
        try:
            body = json.dumps({'event': event, **payload, 'timestamp': datetime.now(THAI_TZ).isoformat()}).encode()
            req = urllib.request.Request(OUTBOUND_WEBHOOK_URL, data=body,
                                         headers={'Content-Type': 'application/json'}, method='POST')
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            log(f'Webhook error: {e}')
    threading.Thread(target=_send, daemon=True).start()

def record_voice_event(guild_id, member_id):
    """Record a voice join/leave event for spam tracking. Call once per event."""
    key = (guild_id, member_id)
    now = datetime.now(THAI_TZ)
    spam_window = get_gc(guild_id, 'spam_window_sec', SPAM_WINDOW_SEC)
    with _lock_spam:
        events = voice_spam_tracker.get(key, [])
        events = [t for t in events if (now - t).total_seconds() < spam_window]
        events.append(now)
        voice_spam_tracker[key] = events

def check_voice_spam(guild_id, member_id):
    """Check if this member is spamming voice. Call AFTER record_voice_event."""
    key = (guild_id, member_id)
    now = datetime.now(THAI_TZ)
    spam_window = get_gc(guild_id, 'spam_window_sec', SPAM_WINDOW_SEC)
    spam_max    = get_gc(guild_id, 'spam_max_events', SPAM_MAX_EVENTS)
    with _lock_spam:
        events = [t for t in voice_spam_tracker.get(key, []) if (now - t).total_seconds() < spam_window]
        return len(events) >= spam_max
# =====================

# ===== Avatar persistence helpers =====
def _build_avatar_url(member) -> str | None:
    """Return a stable CDN URL for member's avatar (128px), or None."""
    try:
        return str(member.display_avatar.with_size(128).url)
    except Exception:
        return None

def _default_avatar_url(uid_str: str) -> str:
    """Discord's coloured default avatar based on user ID (no hash needed)."""
    idx = (int(uid_str) >> 22) % 6
    return f'https://cdn.discordapp.com/embed/avatars/{idx}.png'

def _persist_avatar(gid: str, uid_str: str, member) -> None:
    """Store current avatar URL in user_daily so it survives offline periods."""
    url = _build_avatar_url(member)
    if not url:
        return
    if gid not in user_daily:
        user_daily[gid] = {}
    entry = user_daily[gid].setdefault(uid_str, {'name': member.display_name, 'dates': {}})
    entry['avatar_url'] = url
    entry['name'] = member.display_name  # keep name fresh too

# ===== record join/leave (Multi-guild) =====
def record_join(guild_id, member_id, display_name, channel_name=''):
    voice_join_times[(guild_id, member_id)] = (display_name, datetime.now(THAI_TZ), channel_name)
    gid = str(guild_id)
    hour = str(datetime.now(THAI_TZ).hour)
    if gid not in hourly_activity:
        hourly_activity[gid] = {str(h): 0 for h in range(24)}
    hourly_activity[gid][hour] = hourly_activity[gid].get(hour, 0) + 1
    save_hourly()
    # Daily activity
    date_str = datetime.now(THAI_TZ).strftime('%Y-%m-%d')
    if gid not in daily_activity:
        daily_activity[gid] = {}
    daily_activity[gid][date_str] = daily_activity[gid].get(date_str, 0) + 1
    save_daily()
    # User daily attendance (count joins per day per user)
    uid_str = str(member_id)
    if gid not in user_daily:
        user_daily[gid] = {}
    if uid_str not in user_daily[gid]:
        user_daily[gid][uid_str] = {'name': display_name, 'dates': {}}
    uentry = user_daily[gid][uid_str]
    uentry['name'] = display_name
    uentry['dates'][date_str] = uentry['dates'].get(date_str, 0) + 1
    now_iso = datetime.now(THAI_TZ).isoformat()
    if 'first_seen' not in uentry:
        uentry['first_seen'] = now_iso
    uentry['last_seen'] = now_iso
    save_user_daily()
    # DAU: track unique users per day — hold lock for atomic check+append
    with _lock_daily_unique:
        if gid not in daily_unique:
            daily_unique[gid] = {}
        if date_str not in daily_unique[gid]:
            daily_unique[gid][date_str] = []
        if uid_str not in daily_unique[gid][date_str]:
            daily_unique[gid][date_str].append(uid_str)
            _atomic_json_dump(daily_unique, DAILY_UNIQUE_FILE, ensure_ascii=False)
    save_active_sessions()   # ← persist immediately so restart restores correctly

def record_leave(guild_id, member_id) -> list:
    """Record voice leave. Returns list of newly-hit milestone hours (empty if none)."""
    key = (guild_id, member_id)
    if key not in voice_join_times:
        return []
    display_name, join_time, channel_name = voice_join_times.pop(key)
    save_active_sessions()   # ← remove this user from the active-sessions snapshot
    leave_time = datetime.now(THAI_TZ)
    elapsed    = int((leave_time - join_time).total_seconds())
    gid = str(guild_id)
    uid = str(member_id)
    with _lock_stats:
        if gid not in weekly_stats:
            weekly_stats[gid] = {}
        if uid not in weekly_stats[gid]:
            weekly_stats[gid][uid] = {'name': display_name, 'seconds': 0}
        weekly_stats[gid][uid]['name']    = display_name
        weekly_stats[gid][uid]['seconds'] += elapsed
    save_stats()
    with _lock_history:
        session_history.append({
            'guild_id': gid,
            'uid':      uid,
            'name':     display_name,
            'channel':  channel_name,
            'join':     join_time.strftime('%Y-%m-%d %H:%M'),
            'leave':    leave_time.strftime('%Y-%m-%d %H:%M'),
            'duration': format_duration(elapsed),
            'seconds':  elapsed,
        })
    save_history()
    # Feature 6: update channel activity
    if gid not in channel_activity:
        channel_activity[gid] = {}
    channel_activity[gid][channel_name] = channel_activity[gid].get(channel_name, 0) + elapsed
    save_channel_activity()
    # Enrich user_daily with per-session analytics
    if gid in user_daily and uid in user_daily[gid]:
        uentry = user_daily[gid][uid]
        uentry['last_seen'] = leave_time.isoformat()
        uentry['session_count'] = uentry.get('session_count', 0) + 1
        uentry['alltime_seconds'] = uentry.get('alltime_seconds', 0) + elapsed
        # Track per-channel seconds per user
        ch_map = uentry.setdefault('channel_seconds', {})
        ch_map[channel_name] = ch_map.get(channel_name, 0) + elapsed
        # Update max streak
        current_streak = compute_streak(uentry.get('dates', {}))
        uentry['streak_max'] = max(uentry.get('streak_max', 0), current_streak)
        save_user_daily()
    # Feature 5: check milestones (only for sessions >= 1 min to avoid spam on micro-joins)
    if elapsed >= 60:
        return check_and_award_milestones(gid, uid)
    return []
# ==========================================

# ===== Cooldown =====
mute_cooldown = {}

def check_cooldown(member_id, event, guild_id=None):
    key = (member_id, event)
    now = datetime.now(THAI_TZ)
    cooldown_sec = get_gc(guild_id, 'mute_cooldown_sec', 3) if guild_id else bot_config.get('mute_cooldown_sec', 3)
    with _lock_mute_cooldown:
        if key in mute_cooldown and (now - mute_cooldown[key]).total_seconds() < cooldown_sec:
            return False
        mute_cooldown[key] = now
        return True

command_rate_limit = {}  # {(user_id, cmd): last_used_timestamp}
COMMAND_COOLDOWN_SEC = 30

def check_command_rate(user_id, cmd):
    key = (user_id, cmd)
    now = datetime.now(THAI_TZ)
    last = command_rate_limit.get(key)
    if last and (now - last).total_seconds() < COMMAND_COOLDOWN_SEC:
        return False
    command_rate_limit[key] = now
    return True
# ====================

# ===== Feature 4: Streak helper ==========================================
def compute_streak(dates_dict: dict) -> int:
    """
    คำนวณ streak (วันต่อเนื่องที่เข้า Voice) จาก {YYYY-MM-DD: count}
    นับจากวันนี้หรือเมื่อวานย้อนหลัง
    """
    if not dates_dict:
        return 0
    today = datetime.now(THAI_TZ).date()
    streak = 0
    check = today
    # ถ้าวันนี้ยังไม่มีข้อมูล ลองเริ่มจากเมื่อวาน
    if check.isoformat() not in dates_dict:
        check = today - timedelta(days=1)
    while check.isoformat() in dates_dict:
        streak += 1
        check -= timedelta(days=1)
    return streak
# =========================================================================

# ===== Feature 5: Milestone helpers ======================================
def get_user_alltime_seconds(guild_id: str, user_id: str) -> int:
    """คำนวณเวลา Voice รวมทุกเวลาของ user ใน guild นั้น.
    Uses pre-aggregated user_daily cache (O(1)); falls back to session_history scan.
    """
    cached = user_daily.get(str(guild_id), {}).get(str(user_id), {}).get('alltime_seconds')
    if cached is not None:
        return int(cached)
    return sum(
        s.get('seconds', 0) for s in session_history
        if s.get('guild_id') == str(guild_id) and s.get('uid') == str(user_id)
    )

def check_and_award_milestones(guild_id: str, user_id: str) -> list:
    """
    ตรวจว่า user ถึง milestone ใหม่หรือไม่
    คืน list ของ milestone hours ที่เพิ่งผ่าน (empty ถ้าไม่มี)
    """
    gid, uid = str(guild_id), str(user_id)
    total_sec = get_user_alltime_seconds(gid, uid)
    total_hours = total_sec / 3600
    awarded = milestones_awarded.get(gid, {}).get(uid, [])
    new_hits = [h for h in VOICE_MILESTONES if h <= total_hours and h not in awarded]
    if new_hits:
        milestones_awarded.setdefault(gid, {}).setdefault(uid, [])
        milestones_awarded[gid][uid].extend(new_hits)
        save_milestones()
    return new_hits
# =========================================================================

# ===== Uptime + event counter =====
start_time   = datetime.now(THAI_TZ)
event_counts = {'join': 0, 'leave': 0, 'mute': 0, 'deaf': 0, 'stream': 0, 'video': 0}

def load_event_counts():
    """Load persisted event_counts from disk (survives bot restart)."""
    if os.path.exists(EVENT_COUNTS_FILE):
        try:
            with open(EVENT_COUNTS_FILE, encoding='utf-8') as f:
                saved = json.load(f)
            for k in event_counts:
                if k in saved:
                    event_counts[k] = int(saved[k])
        except Exception as e:
            print(f'[WARN] load_event_counts failed: {e}')

def save_event_counts():
    """Persist current event_counts to disk."""
    with _lock_event_counts:
        try:
            _atomic_json_dump(event_counts, EVENT_COUNTS_FILE, ensure_ascii=False)
        except Exception as e:
            print(f'[WARN] save_event_counts failed: {e}')

# ── Active voice session persistence ──────────────────────────────────────────
# Saves voice_join_times to disk so users who are already in voice don't reset
# to 0 minutes after a bot restart/Railway redeploy.

def save_active_sessions():
    """Snapshot current voice_join_times → disk."""
    with _lock_active_sessions:
        try:
            data = {}
            for (gid, mid), (name, join_time, channel) in list(voice_join_times.items()):
                key = f'{gid},{mid}'
                data[key] = {
                    'name':    name,
                    'join':    join_time.isoformat(),
                    'channel': channel,
                }
            _atomic_json_dump(data, ACTIVE_SESSIONS_FILE, ensure_ascii=False)
        except Exception as e:
            print(f'[WARN] save_active_sessions failed: {e}')

def load_active_sessions() -> dict:
    """Load saved voice sessions → {(gid, mid): (name, join_time, channel)}."""
    result = {}
    if not os.path.exists(ACTIVE_SESSIONS_FILE):
        return result
    try:
        with open(ACTIVE_SESSIONS_FILE, encoding='utf-8') as f:
            data = json.load(f)
        for key, v in data.items():
            gid_str, mid_str = key.split(',', 1)
            join_time = datetime.fromisoformat(v['join'])
            if join_time.tzinfo is None:
                join_time = join_time.replace(tzinfo=THAI_TZ)
            result[(int(gid_str), int(mid_str))] = (v['name'], join_time, v['channel'])
    except Exception as e:
        print(f'[WARN] load_active_sessions failed: {e}')
    return result
# ──────────────────────────────────────────────────────────────────────────────
# ==================================

# ===== Daily Activity =====
daily_activity = {}   # {guild_id: {"YYYY-MM-DD": int}}

def load_daily():
    global daily_activity
    if os.path.exists(DAILY_FILE):
        try:
            with open(DAILY_FILE, encoding='utf-8') as f:
                daily_activity = json.load(f)
        except Exception as e:
            print(f'[WARN] load_daily failed: {e}')

def save_daily():
    with _lock_daily:
        _atomic_json_dump(daily_activity, DAILY_FILE, ensure_ascii=False)

# ===== User Daily Attendance =====
user_daily = {}   # {guild_id: {uid: {"name": str, "dates": {"YYYY-MM-DD": int}}}}

def load_user_daily():
    global user_daily
    if os.path.exists(USER_DAILY_FILE):
        try:
            with open(USER_DAILY_FILE, encoding='utf-8') as f:
                user_daily = json.load(f)
        except Exception as e:
            print(f'[WARN] load_user_daily failed: {e}')

def save_user_daily():
    with _lock_user_daily:
        _atomic_json_dump(user_daily, USER_DAILY_FILE, ensure_ascii=False)

# ===== Daily Unique Users (DAU) =====
daily_unique = {}   # {guild_id: {date_str: [uid, ...]}}
DAILY_UNIQUE_FILE  = os.path.join(DATA_DIR, 'daily_unique.json')
_lock_daily_unique = threading.Lock()

def load_daily_unique():
    global daily_unique
    if os.path.exists(DAILY_UNIQUE_FILE):
        try:
            with open(DAILY_UNIQUE_FILE, encoding='utf-8') as f:
                daily_unique = json.load(f)
        except Exception as e:
            print(f'[WARN] load_daily_unique failed: {e}')

def save_daily_unique():
    with _lock_daily_unique:
        _atomic_json_dump(daily_unique, DAILY_UNIQUE_FILE, ensure_ascii=False)

# ===== Milestones (Feature 5) =====
# milestones_awarded[guild_id][uid] = [hours_int, ...]  — milestones already announced
VOICE_MILESTONES = [1, 5, 10, 25, 50, 100, 250, 500]
milestones_awarded = {}
_lock_milestones   = threading.Lock()

def load_milestones():
    global milestones_awarded
    if os.path.exists(MILESTONES_FILE):
        try:
            with open(MILESTONES_FILE, encoding='utf-8') as f:
                milestones_awarded = json.load(f)
        except Exception as e:
            print(f'[WARN] load_milestones failed: {e}')

def save_milestones():
    with _lock_milestones:
        _atomic_json_dump(milestones_awarded, MILESTONES_FILE, ensure_ascii=False)

# ===== Channel Activity (Feature 6) =====
# channel_activity[guild_id][channel_name] = total_seconds
channel_activity = {}
_lock_channel_activity = threading.Lock()

def load_channel_activity():
    global channel_activity
    if os.path.exists(CHANNEL_ACTIVITY_FILE):
        try:
            with open(CHANNEL_ACTIVITY_FILE, encoding='utf-8') as f:
                channel_activity = json.load(f)
        except Exception as e:
            print(f'[WARN] load_channel_activity failed: {e}')

def save_channel_activity():
    with _lock_channel_activity:
        _atomic_json_dump(channel_activity, CHANNEL_ACTIVITY_FILE, ensure_ascii=False)
# =========================================

# ===== Logging =====
def _setup_file_logger() -> logging.Logger:
    """Configure a module-level logger with RotatingFileHandler (10 MB × 5 files)."""
    logger = logging.getLogger('voicebot')
    if logger.handlers:
        return logger  # already configured
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    # Stdout handler (Railway captures stdout)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    # Rotating file handler — safe against large files
    try:
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        print(f'[LOG SETUP ERROR] {e}', flush=True)
    return logger

_logger = _setup_file_logger()

def log(msg: str) -> None:
    _logger.info(msg)
# ===================

# ===== Time-range stats helper =====
import bot_utils as _bu

def get_stats_for_period(period='week', guild_id=None):
    """Wrapper — delegates pure logic to bot_utils (testable independently)"""
    return _bu.get_stats_for_period(session_history, voice_join_times,
                                    period=period, guild_id=guild_id)
# ===================================

# ===== Discord Bot =====
intents                 = discord.Intents.default()
intents.voice_states    = True
intents.messages        = True
intents.message_content = True
intents.members         = True   # privileged — enable in Discord Dev Portal → Bot → Privileged Gateway Intents
intents.presences       = True   # privileged — same page, needed for online status

class VoiceBot(discord.ext.commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

client   = VoiceBot()
bot_loop = None

def get_guild_ch(guild_id, ch_type):
    """Get channel for a specific guild — 3-tier fallback:
    1. Per-guild config (guild_configs[gid][channel_X])
    2. Global default (bot_config[channel_X]) — only if channel is in same guild
    3. First writable text channel in the guild (automatic fallback)
    Always validates the returned channel belongs to the requested guild.
    """
    gid = str(guild_id) if guild_id else ''
    # Tier 1: Per-guild config
    cid = guild_configs.get(gid, {}).get(f'channel_{ch_type}')
    # Tier 2: Global fallback — allowed only when channel belongs to same guild
    if cid is None:
        if not guild_id:
            cid = bot_config.get(f'channel_{ch_type}')
        else:
            global_cid = bot_config.get(f'channel_{ch_type}')
            if global_cid:
                try:
                    ch_check = client.get_channel(int(global_cid))
                    if ch_check and hasattr(ch_check, 'guild') and str(ch_check.guild.id) == gid:
                        cid = global_cid
                except (ValueError, TypeError):
                    pass
    if cid:
        try:
            ch = client.get_channel(int(cid))
        except (ValueError, TypeError):
            ch = None
        if ch and guild_id and hasattr(ch, 'guild') and str(ch.guild.id) != gid:
            log(f'get_guild_ch: channel {cid} is in guild {ch.guild.id}, not {gid} — skipping')
            ch = None
        if ch:
            return ch
    # Tier 3: Auto-detect — first writable text channel in the guild
    if guild_id and client.is_ready():
        try:
            guild = client.get_guild(int(guild_id))
            if guild and guild.me:
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        log(f'get_guild_ch: no channel_{ch_type} configured for guild {gid} — using #{ch.name} as fallback')
                        return ch
        except (ValueError, TypeError):
            pass
    return None

async def send_joke_with_vote(channel, category, joke):
    # ป้องกันส่ง joke ซ้อนกันใน channel เดียวกัน
    if channel.id in active_joke_channels:
        log(f'send_joke_with_vote: skipped — joke already in progress in channel {channel.id}')
        return
    active_joke_channels.add(channel.id)
    sent_msgs = []
    try:
        if '?' in joke:
            parts = joke.split('?', 1)
            setup_msg = await channel.send(f'[{category}] {parts[0].strip()}?')
            sent_msgs.append(setup_msg)
            await asyncio.sleep(get_gc(channel.guild.id if channel.guild else None, 'joke_delay', 15))
            msg = await channel.send(parts[1].strip())
        else:
            msg = await channel.send(f'[{category}] {joke}')
        sent_msgs.append(msg)
        await msg.add_reaction('👍')
        await msg.add_reaction('👎')
        register_joke_msg(msg.id, joke)
    finally:
        active_joke_channels.discard(channel.id)
    # ลบข้อความทั้งหมดหลัง 30 วินาที
    await asyncio.sleep(30)
    for m in sent_msgs:
        try:
            await m.delete()
        except discord.HTTPException:
            pass

async def send_leaderboard(channel, combined=None, guild_id=None):
    if combined is None:
        combined = get_stats_for_period('week', guild_id=str(channel.guild.id) if channel.guild else None)
    if not combined:
        await channel.send('ยังไม่มีข้อมูล Voice ในสัปดาห์นี้')
        return
    sorted_stats = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)
    medals = ['1.', '2.', '3.']
    lines  = ['--- อันดับ Voice สัปดาห์นี้ ---']
    for i, (uid, data) in enumerate(sorted_stats[:10]):
        prefix = medals[i] if i < 3 else f'{i + 1}.'
        lines.append(f'{prefix} {data["name"]}  {format_duration(data["seconds"])}')
    lines.append('------------------------------')
    await channel.send('\n'.join(lines))

async def send_weekly_summary(channel=None):
    if channel is None:
        channel = ch_stats()
    if not channel:
        return
    guild_id = str(channel.guild.id) if channel.guild else None
    combined = get_stats_for_period('week', guild_id=guild_id)
    if not combined:
        await channel.send('สัปดาห์นี้ไม่มีใครเข้าห้อง Voice เลย')
        return
    sorted_stats = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)
    medals = ['1.', '2.', '3.']
    lines  = ['--- สรุปเวลาห้อง Voice ประจำสัปดาห์ ---']
    for i, (uid, data) in enumerate(sorted_stats[:10]):
        prefix = medals[i] if i < 3 else f'{i + 1}.'
        lines.append(f'{prefix} {data["name"]}  {format_duration(data["seconds"])}')
    lines.append('------------------------------------')
    await channel.send('\n'.join(lines))

async def _post_trivia(channel, trivia_list=None):
    # ป้องกันส่ง trivia ซ้อนกันใน channel เดียวกัน
    if channel.id in active_trivia:
        log(f'_post_trivia: skipped — trivia already active in channel {channel.id}')
        return
    if channel.id in active_joke_channels:
        log(f'_post_trivia: skipped — joke in progress in channel {channel.id}')
        return
    if trivia_list is None:
        trivia_list = load_trivia()
    if not trivia_list:
        return
    item = random.choice(trivia_list)
    question, answer = item.split('|', 1)
    question = question.strip()
    answer = answer.strip()
    expires = datetime.now(THAI_TZ) + timedelta(seconds=TRIVIA_ANSWER_WINDOW)
    q_msg = await channel.send(f'🤔 **คำถาม:** {question}\n_(ตอบภายใน {TRIVIA_ANSWER_WINDOW} วินาที)_')
    active_trivia[channel.id] = {
        'answer': answer.lower(), 'question': question,
        'expires': expires.isoformat(), 'q_msg_id': q_msg.id,
    }
    await asyncio.sleep(TRIVIA_ANSWER_WINDOW)
    a_msg = None
    if channel.id in active_trivia:
        active_trivia.pop(channel.id, None)
        a_msg = await channel.send(f'✅ **เฉลย:** {answer}')
    # ลบข้อความทั้งหมดหลัง 30 วินาที
    await asyncio.sleep(30)
    for m in [q_msg, a_msg]:
        if m:
            try:
                await m.delete()
            except discord.HTTPException:
                pass

@tasks.loop(minutes=30)
async def send_content():
    # ไม่ส่งถ้าไม่มีใครอยู่ใน Voice channel เลย
    if not voice_join_times:
        return
    # Trivia is shared (not filtered by votes) — load once
    all_trivia = load_trivia()
    # ส่งแยกแต่ละ guild ที่มีคนใน voice
    active_guilds = set(str(gid) for (gid, _) in voice_join_times.keys())
    for gid in active_guilds:
        # Per-guild content toggles
        if not get_gc(gid, 'send_content', True):
            continue
        channel = get_guild_ch(gid, 'content')
        if not channel:
            continue
        trivia_list = all_trivia if get_gc(gid, 'send_trivia', True) else []
        jokes       = load_jokes(guild_id=gid) if get_gc(gid, 'send_jokes', True) else []
        if not trivia_list and not jokes:
            continue
        if trivia_list and jokes:
            if random.random() < 0.5:
                await _post_trivia(channel, trivia_list)
            else:
                category, joke = random.choice(jokes)
                await send_joke_with_vote(channel, category, joke)
        elif trivia_list:
            await _post_trivia(channel, trivia_list)
        else:
            category, joke = random.choice(jokes)
            await send_joke_with_vote(channel, category, joke)

@tasks.loop(hours=1)
async def weekly_summary_task():
    now = datetime.now(THAI_TZ)
    for guild in client.guilds:
        gid = str(guild.id)
        summary_hour = get_gc(guild.id, 'summary_hour', 9)
        if now.weekday() == 0 and now.hour == summary_hour:
            if not summary_sent.get(gid, False):
                channel = get_guild_ch(guild.id, 'stats')
                if channel:
                    await send_weekly_summary(channel)
                weekly_stats.pop(gid, None)
                save_stats()
                summary_sent[gid] = True
        else:
            summary_sent[gid] = False

# ── Feature 4: Daily digest — ส่ง embed สรุปประจำวันตอนเที่ยงคืน ──────────────
@tasks.loop(hours=1)
async def daily_backup_task():
    now = datetime.now(THAI_TZ)
    if now.hour != 0:
        return
    today_str = now.strftime('%Y-%m-%d')
    yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    for guild in client.guilds:
        gid = str(guild.id)
        channel = get_guild_ch(guild.id, 'stats')
        if not channel:
            continue
        # ป้องกันส่งซ้ำถ้า task loop fire มากกว่า 1 ครั้งในชั่วโมงเดียวกัน
        if daily_digest_sent.get(gid) == today_str:
            continue
        daily_digest_sent[gid] = today_str

        # ── ข้อมูลวันที่ผ่านมา (yesterday) ──
        today_sessions = [
            s for s in session_history
            if s.get('guild_id') == gid and s.get('join', '').startswith(yesterday_str)
        ]
        # ผู้ใช้ที่อยู่ voice วันนี้ + live sessions
        combined_today = get_stats_for_period('today', guild_id=gid)
        # ใช้ combined_today ถ้ามี ไม่งั้น fallback ไป session_history
        if combined_today:
            top5 = sorted(combined_today.items(), key=lambda x: x[1]['seconds'], reverse=True)[:5]
            total_sec = sum(v['seconds'] for v in combined_today.values())
        else:
            # คำนวณจาก session_history
            user_secs: dict = {}
            for s in today_sessions:
                uid = str(s.get('user_id', ''))
                name = s.get('name', uid)
                user_secs.setdefault(uid, {'name': name, 'seconds': 0})
                user_secs[uid]['seconds'] += s.get('seconds', 0)
            top5 = sorted(user_secs.items(), key=lambda x: x[1]['seconds'], reverse=True)[:5]
            total_sec = sum(v['seconds'] for v in user_secs.values())

        # ── ชั่วโมงที่คึกคักที่สุด (จาก hourly_activity) ──
        guild_hourly = hourly_activity.get(gid, {})
        peak_hour = max(guild_hourly, key=guild_hourly.get) if guild_hourly else None

        # ── สร้างข้อความ ──
        medals = ['1.', '2.', '3.']
        lines = [
            f'**สรุปประจำวัน {yesterday_str} — {guild.name}**',
            f'เวลา Voice รวม: **{format_duration(total_sec)}**  |  Sessions: **{len(today_sessions)}**',
        ]
        if peak_hour is not None:
            lines.append(f'ชั่วโมงคึกคักที่สุด: **{peak_hour}:00**')
        if top5:
            lines.append('\nTop Voice วันนี้:')
            for i, (uid, d) in enumerate(top5):
                prefix = medals[i] if i < 3 else f'{i+1}.'
                lines.append(f'{prefix} {d["name"]}  {format_duration(d["seconds"])}')
        else:
            lines.append('ไม่มีใครเข้าห้อง Voice วันนี้')
        lines.append(f'\nดูรายละเอียด: {DASHBOARD_BASE_URL}')
        try:
            await channel.send('\n'.join(lines))
        except discord.HTTPException as e:
            log(f'daily_backup_task: send failed for {guild.name}: {e}')

    log('Daily digest sent to all guilds')

    # Auto-purge sessions older than 90 days (ทุกจันทร์)
    if now.weekday() == 0:
        cutoff = now - timedelta(days=90)
        with _lock_history:
            before = len(session_history)
            session_history[:] = [
                s for s in session_history
                if datetime.strptime(s.get('join', '2000-01-01 00:00'), '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ) >= cutoff
            ]
            purged = before - len(session_history)
        if purged > 0:
            save_history()
            log(f'Auto-purged {purged} sessions older than 90 days')
# ─────────────────────────────────────────────────────────────────────────────

# ===== Feature 6: Periodic event_counts save =====
@tasks.loop(minutes=5)
async def save_event_counts_task():
    """Save event_counts + active sessions + heatmap data every 5 minutes."""
    save_event_counts()
    save_active_sessions()
    save_hourly()
    save_daily()
    save_user_daily()
    save_channel_activity()
# ==================================================

# ===== Periodic eviction of in-memory rate-limit dicts =====
@tasks.loop(minutes=10)
async def evict_stale_trackers():
    """Remove stale entries from unbounded dicts to prevent memory leaks."""
    now = datetime.now(THAI_TZ)
    # Use largest possible window across guilds so we don't evict too aggressively
    max_spam_window = max(
        (get_gc(g.id, 'spam_window_sec', SPAM_WINDOW_SEC) for g in client.guilds),
        default=SPAM_WINDOW_SEC
    )
    max_mute_ttl = max(
        (get_gc(g.id, 'mute_cooldown_sec', 3) for g in client.guilds),
        default=3
    )

    # voice_spam_tracker — keep only entries with at least one event in the window
    stale_spam = [k for k, ts in list(voice_spam_tracker.items())
                  if not any((now - t).total_seconds() < max_spam_window for t in ts)]
    for k in stale_spam:
        voice_spam_tracker.pop(k, None)

    # mute_cooldown — keep entries younger than 10× the max cooldown
    stale_mute = [k for k, t in list(mute_cooldown.items())
                  if (now - t).total_seconds() > max_mute_ttl * 10]
    for k in stale_mute:
        mute_cooldown.pop(k, None)

    # command_rate_limit — keep entries younger than 10× the command cooldown
    stale_cmd = [k for k, t in list(command_rate_limit.items())
                 if (now - t).total_seconds() > COMMAND_COOLDOWN_SEC * 10]
    for k in stale_cmd:
        command_rate_limit.pop(k, None)
# ============================================================

# ===== Feature 6: Bot status rotation =====
_status_index = 0

@tasks.loop(minutes=30)
async def rotate_status():
    global _status_index
    if not client.is_ready():
        return
    combined = get_stats_for_period('week')
    sorted_stats = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)
    uptime_sec = int((datetime.now(THAI_TZ) - start_time).total_seconds())
    statuses = [
        discord.Activity(type=discord.ActivityType.watching, name=f'Voice {len(voice_join_times)} คน'),
        discord.Activity(type=discord.ActivityType.playing, name=f'Uptime {format_duration(uptime_sec)}'),
    ]
    if sorted_stats:
        top_name = sorted_stats[0][1]['name']
        statuses.append(discord.Activity(type=discord.ActivityType.listening, name=f'🏆 {top_name}'))
    status = statuses[_status_index % len(statuses)]
    _status_index += 1
    await client.change_presence(activity=status)
# ==========================================

@client.event
async def on_ready():
    load_stats()
    load_config()
    load_guild_configs()
    load_hourly()
    load_history()
    load_votes()
    load_trivia_scores()
    load_daily()
    load_user_daily()
    load_daily_unique()
    load_milestones()
    load_channel_activity()
    load_event_counts()   # ← restore persisted event counters
    log(f'Bot ready: {client.user}')
    log(f'DATA_DIR: {DATA_DIR} ({"persistent volume" if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") else "⚠️ ephemeral — data will be lost on redeploy!"})')
    # Scan all voice channels — populate voice_join_times for members already in voice
    # (bot restart clears in-memory state, so we need to rebuild it)
    # Restore join times for users who were in voice before restart.
    # This prevents their duration from resetting to 0 after a redeploy.
    saved_sessions = load_active_sessions()
    restored = 0
    for guild in client.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    key = (guild.id, member.id)
                    if key not in voice_join_times:
                        if key in saved_sessions:
                            # Restore original join time — duration continues from before restart
                            voice_join_times[key] = saved_sessions[key]
                            restored += 1
                        else:
                            # New user (joined while bot was offline) — use now as fallback
                            voice_join_times[key] = (member.display_name, datetime.now(THAI_TZ), vc.name)
    log(f'Voice snapshot: {len(voice_join_times)} members tracked ({restored} sessions restored from disk)')
    # Persist avatar URLs for all cached guild members so dashboard shows avatars
    # even when members are offline
    avatar_saved = 0
    for guild in client.guilds:
        gid_str = str(guild.id)
        for member in guild.members:
            if not member.bot:
                _persist_avatar(gid_str, str(member.id), member)
                avatar_saved += 1
    if avatar_saved:
        save_user_daily()
        log(f'Avatar cache: {avatar_saved} member avatars saved to user_daily')
    send_content.start()
    weekly_summary_task.start()
    daily_backup_task.start()
    rotate_status.start()
    save_event_counts_task.start()   # ← save event_counts every 5 min
    evict_stale_trackers.start()     # ← evict stale rate-limit dicts every 10 min
    await client.tree.sync()
    # ── Ready message ──────────────────────────────────────────────────────────
    for guild in client.guilds:
        if get_gc(guild.id, 'send_ready_message', True):
            ch = get_guild_ch(str(guild.id), 'voice')
            if ch:
                try:
                    await ch.send(
                        f'🤖 **AjarnBot พร้อมใช้งานแล้ว!** (v{APP_VERSION})\n'
                        f'ระบบออนไลน์และพร้อมบันทึก Voice Activity แล้ว'
                    )
                except Exception:
                    pass

# ── Feature 2: Welcome message เมื่อ bot เข้า server ใหม่ ─────────────────────
@client.event
async def on_guild_join(guild: discord.Guild):
    log(f'Joined new guild: {guild.name} ({guild.id})')
    # หาช่องที่ส่งได้: system_channel ก่อน ไม่งั้นใช้ช่องแรกที่ bot พิมพ์ได้
    target = guild.system_channel
    if not target or not target.permissions_for(guild.me).send_messages:
        target = next(
            (ch for ch in guild.text_channels
             if ch.permissions_for(guild.me).send_messages),
            None
        )
    if not target:
        return
    invite_url = discord.utils.oauth_url(
        str(client.user.id),
        permissions=discord.Permissions(
            send_messages=True, read_messages=True,
            embed_links=True, read_message_history=True,
            connect=True, view_channel=True,
        ),
    )
    msg = (
        f'**AjarnBot เข้าร่วม {guild.name} แล้ว!**\n'
        f'บันทึกเวลาห้อง Voice อัตโนมัติ + ส่งมุข/Trivia + สรุปรายสัปดาห์\n\n'
        f'**ขั้นตอนแรก:**\n'
        f'1. ตั้งค่าช่องใน Dashboard → `/api/guild-config`\n'
        f'2. เปิด Dashboard: {DASHBOARD_BASE_URL}\n'
        f'3. `/rank` — ดูอันดับ Voice  |  `/stats` — สถิติตัวเอง\n\n'
        f'หากต้องการเชิญไปเซิร์ฟเวอร์อื่น: {invite_url}'
    )
    try:
        await target.send(msg)
    except discord.HTTPException as e:
        log(f'on_guild_join: failed to send welcome to {guild.name}: {e}')
# ─────────────────────────────────────────────────────────────────────────────

# ===== Slash Command UI Helpers =====
PERIOD_LABELS = {"today": "วันนี้", "week": "สัปดาห์นี้", "month": "เดือนนี้"}
PERIOD_EMOJIS = {"today": "📅", "week": "📆", "month": "🗓️"}
CMD_COLORS = {
    "rank":     0x5865F2,
    "stats":    0x23A559,
    "compare":  0xF0B132,
    "timeline": 0x00B8D4,
    "trivia":   0xE67E22,
    "help":     0x5865F2,
    "error":    0xED4245,
}

def _bar(val: int, total: int, width: int = 12) -> str:
    """Unicode progress bar: ██████░░░░░░"""
    if total <= 0:
        return '░' * width
    pct = min(val / total, 1.0)
    filled = round(pct * width)
    return '█' * filled + '░' * (width - filled)

def _footer(embed: discord.Embed) -> discord.Embed:
    embed.set_footer(text=f"AjarnBot  •  {datetime.now(THAI_TZ).strftime('%d/%m %H:%M')}")
    return embed

def _error_embed(msg: str) -> discord.Embed:
    e = discord.Embed(description=f"❌  {msg}", color=CMD_COLORS["error"])
    return _footer(e)

def _cooldown_embed(retry_after: float) -> discord.Embed:
    e = discord.Embed(description=f"⏳  รออีก **{retry_after:.0f} วินาที**", color=0x949BA4)
    return _footer(e)


class PeriodView(discord.ui.View):
    """3 period buttons that re-run a command function and edit the original message."""

    def __init__(self, fn, current: str, **kwargs):
        super().__init__(timeout=120)
        self._fn = fn
        self._kwargs = kwargs
        for value, label in [("today", "📅 วันนี้"), ("week", "📆 สัปดาห์"), ("month", "🗓️ เดือน")]:
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary if value == current else discord.ButtonStyle.secondary,
                custom_id=value,
            )
            btn.callback = self._make_callback(value)
            self.add_item(btn)

    def _make_callback(self, period: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            embed, view = await self._fn(interaction, period, **self._kwargs)
            await interaction.edit_original_response(embed=embed, view=view)
        return callback
# =======================================


async def _build_rank_embed(interaction: discord.Interaction, period: str):
    guild_id = str(interaction.guild_id) if interaction.guild_id else None
    combined = get_stats_for_period(period, guild_id=guild_id)
    label    = PERIOD_LABELS.get(period, "สัปดาห์นี้")
    emoji    = PERIOD_EMOJIS.get(period, "📆")

    embed = discord.Embed(
        title=f"🏆  Voice Leaderboard — {label}",
        color=CMD_COLORS["rank"],
    )

    if not combined:
        embed.description = "ยังไม่มีข้อมูล Voice ในช่วงนี้"
        return _footer(embed), PeriodView(_build_rank_embed, period)

    sorted_stats = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)[:10]
    top_sec      = sorted_stats[0][1]['seconds'] if sorted_stats else 1
    medals       = ['🥇', '🥈', '🥉']

    rows = []
    for i, (uid, data) in enumerate(sorted_stats):
        prefix = medals[i] if i < 3 else f'`{i+1}.`'
        bar    = _bar(data['seconds'], top_sec, 10)
        rows.append(f"{prefix} **{data['name']}**\n`{bar}` {format_duration(data['seconds'])}")

    embed.description = "\n\n".join(rows)
    embed.set_footer(
        text=f"AjarnBot  •  {datetime.now(THAI_TZ).strftime('%d/%m %H:%M')}  •  {len(sorted_stats)} คน"
    )
    return embed, PeriodView(_build_rank_embed, period)


@client.tree.command(name="rank", description="อันดับ Voice ของ server")
@app_commands.describe(period="ช่วงเวลา")
@app_commands.choices(period=[
    app_commands.Choice(name="📅 วันนี้",     value="today"),
    app_commands.Choice(name="📆 สัปดาห์นี้", value="week"),
    app_commands.Choice(name="🗓️ เดือนนี้",  value="month"),
])
@app_commands.checks.cooldown(1, 30.0)
async def slash_rank(interaction: discord.Interaction, period: str = "week"):
    await interaction.response.defer()
    embed, view = await _build_rank_embed(interaction, period)
    await interaction.followup.send(embed=embed, view=view)

@client.tree.command(name="joke", description="รับมุขสุ่ม")
@app_commands.checks.cooldown(1, 15.0)
async def slash_joke(interaction: discord.Interaction):
    jokes = load_jokes()
    if not jokes:
        await interaction.response.send_message('ไม่มีมุขในระบบ', ephemeral=True)
        return
    category, joke = random.choice(jokes)
    await interaction.response.defer()
    await send_joke_with_vote(interaction.channel, category, joke)

@client.tree.command(name="trivia", description="รับคำถาม Trivia")
@app_commands.checks.cooldown(1, 15.0)
async def slash_trivia(interaction: discord.Interaction):
    trivia_list = load_trivia()
    if not trivia_list:
        await interaction.response.send_message('ไม่มี Trivia ในระบบ', ephemeral=True)
        return
    await interaction.response.defer()
    await _post_trivia(interaction.channel, trivia_list)

@client.tree.command(name="trivia-rank", description="อันดับคะแนน Trivia")
async def slash_trivia_rank(interaction: discord.Interaction):
    gid    = str(interaction.guild_id) if interaction.guild_id else 'dm'
    scores = trivia_scores.get(gid, {})
    embed  = discord.Embed(title="🧠  Trivia Leaderboard", color=CMD_COLORS["trivia"])

    if not scores:
        embed.description = "ยังไม่มีคะแนน Trivia ในเซิร์ฟเวอร์นี้"
        _footer(embed)
        await interaction.response.send_message(embed=embed)
        return

    sorted_scores = sorted(scores.items(), key=lambda x: x[1]['score'], reverse=True)[:10]
    medals = ['🥇', '🥈', '🥉']
    top_score = sorted_scores[0][1]['score'] if sorted_scores else 1

    rows = []
    for i, (uid, data) in enumerate(sorted_scores):
        prefix = medals[i] if i < 3 else f'`{i+1}.`'
        bar    = _bar(data['score'], top_score, 8)
        rows.append(f"{prefix} **{data['name']}**  `{bar}`  **{data['score']}** คะแนน")

    embed.description = "\n".join(rows)
    _footer(embed)
    await interaction.response.send_message(embed=embed)

# ── Feature 1: /stats — ดูสถิติ Voice ของตัวเอง ─────────────────────────────
async def _build_stats_embed(interaction: discord.Interaction, period: str):
    gid  = str(interaction.guild_id) if interaction.guild_id else None
    uid  = str(interaction.user.id)
    label = PERIOD_LABELS.get(period, "สัปดาห์นี้")

    combined = get_stats_for_period(period, guild_id=gid)
    user_data = combined.get(uid)

    embed = discord.Embed(
        title=f"📊  สถิติ Voice ของ {interaction.user.display_name}",
        color=CMD_COLORS["stats"],
    )
    # Avatar thumbnail
    if interaction.user.display_avatar:
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

    if not user_data:
        embed.description = f"ยังไม่มีข้อมูล Voice ช่วง **{label}**"
        return _footer(embed), PeriodView(_build_stats_embed, period)

    sorted_all    = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)
    rank          = next((i + 1 for i, (k, _) in enumerate(sorted_all) if k == uid), None)
    total_srv_sec = sum(v['seconds'] for v in combined.values())
    pct           = (user_data['seconds'] / total_srv_sec * 100) if total_srv_sec else 0
    bar           = _bar(user_data['seconds'], total_srv_sec)

    embed.add_field(
        name=f"{PERIOD_EMOJIS.get(period,'📆')}  {label}",
        value=f"**{format_duration(user_data['seconds'])}**\n`{bar}` {pct:.1f}% ของ server",
        inline=True,
    )
    embed.add_field(
        name="🏅  อันดับ",
        value=f"**#{rank}** / {len(combined)} คน",
        inline=True,
    )

    ud     = (user_daily.get(gid) or {}).get(uid, {})
    streak = compute_streak(ud.get('dates', {}))
    alltime = ud.get('alltime_seconds', 0)

    embed.add_field(
        name="🔥  Streak",
        value=f"**{streak} วัน**" + ("  " + "🔥" * min(streak, 5) if streak > 0 else ""),
        inline=True,
    )
    embed.add_field(
        name="⏱️  รวมทั้งหมด",
        value=f"**{format_duration(alltime)}**",
        inline=True,
    )
    embed.add_field(
        name="🗓️  Sessions",
        value=f"**{ud.get('session_count', 0)}**",
        inline=True,
    )
    embed.add_field(
        name="📅  ครั้งล่าสุด",
        value=ud.get('last_seen', '-') or '-',
        inline=True,
    )

    # Live session
    live_key = (interaction.guild_id, interaction.user.id) if interaction.guild_id else None
    if live_key and live_key in voice_join_times:
        _, join_t, ch_name = voice_join_times[live_key]
        elapsed = int((datetime.now(THAI_TZ) - join_t).total_seconds())
        embed.add_field(
            name="🔴  กำลังอยู่ใน Voice",
            value=f"**{ch_name}** — {format_duration(elapsed)}",
            inline=False,
        )

    embed.set_footer(
        text=f"AjarnBot  •  {datetime.now(THAI_TZ).strftime('%d/%m %H:%M')}  •  ดูเพิ่มเติม: {DASHBOARD_BASE_URL}/profile/{uid}"
    )
    return embed, PeriodView(_build_stats_embed, period)


@client.tree.command(name="stats", description="ดูเวลา Voice ของตัวเอง")
@app_commands.describe(period="ช่วงเวลา")
@app_commands.choices(period=[
    app_commands.Choice(name="📅 วันนี้",     value="today"),
    app_commands.Choice(name="📆 สัปดาห์นี้", value="week"),
    app_commands.Choice(name="🗓️ เดือนนี้",  value="month"),
])
@app_commands.checks.cooldown(1, 15.0)
async def slash_stats(interaction: discord.Interaction, period: str = "week"):
    await interaction.response.defer(ephemeral=True)
    embed, view = await _build_stats_embed(interaction, period)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
# ─────────────────────────────────────────────────────────────────────────────

# ── Feature 1: /help ──────────────────────────────────────────────────────────
@client.tree.command(name="help", description="แสดงคำสั่งทั้งหมดของ bot")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖  AjarnBot — คำสั่งทั้งหมด",
        description="bot สำหรับ track กิจกรรม Voice Channel",
        color=CMD_COLORS["help"],
    )
    embed.add_field(
        name="📊  Voice Stats",
        value=(
            "`/rank [ช่วงเวลา]` — อันดับ Voice ของ server\n"
            "`/stats [ช่วงเวลา]` — สถิติ Voice ส่วนตัว\n"
            "`/compare @user [ช่วงเวลา]` — เปรียบสถิติกับคนอื่น\n"
            "`/timeline [@user] [วันที่]` — ดู Voice timeline รายชั่วโมง"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎮  Entertainment",
        value=(
            "`/joke` — รับมุขสุ่ม (พร้อมโหวต 👍👎)\n"
            "`/trivia` — รับคำถามแบบทดสอบ (30 วินาที)\n"
            "`/trivia-rank` — อันดับคะแนน Trivia"
        ),
        inline=False,
    )
    embed.add_field(
        name="💡  เคล็ดลับ",
        value=(
            "• `/rank` และ `/stats` มีปุ่มสลับช่วงเวลาได้เลย ไม่ต้องพิมพ์ใหม่\n"
            "• `/stats` แสดงแค่คุณเห็น (ephemeral)\n"
            f"• [เปิด Dashboard]({DASHBOARD_BASE_URL}) — ดูกราฟ, heatmap, leaderboard เต็ม"
        ),
        inline=False,
    )
    if interaction.guild and interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    _footer(embed)
    await interaction.response.send_message(embed=embed, ephemeral=True)
# ─────────────────────────────────────────────────────────────────────────────

# ── Feature 2: /compare @user ────────────────────────────────────────────────
@client.tree.command(name="compare", description="เปรียบ Voice stats กับสมาชิกอื่น")
@app_commands.describe(
    member="สมาชิกที่อยากเปรียบ",
    period="ช่วงเวลา",
)
@app_commands.choices(period=[
    app_commands.Choice(name="📅 วันนี้",     value="today"),
    app_commands.Choice(name="📆 สัปดาห์นี้", value="week"),
    app_commands.Choice(name="🗓️ เดือนนี้",  value="month"),
])
@app_commands.checks.cooldown(1, 15.0)
async def slash_compare(interaction: discord.Interaction,
                        member: discord.Member,
                        period: str = "week"):
    await interaction.response.defer()
    gid   = str(interaction.guild_id) if interaction.guild_id else None
    me_id = str(interaction.user.id)
    th_id = str(member.id)
    label = PERIOD_LABELS.get(period, "สัปดาห์นี้")

    if me_id == th_id:
        await interaction.followup.send(embed=_error_embed("ไม่สามารถเปรียบกับตัวเองได้"), ephemeral=True)
        return

    combined   = get_stats_for_period(period, guild_id=gid)
    sorted_all = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)
    rank_map   = {uid: i + 1 for i, (uid, _) in enumerate(sorted_all)}

    me_sec = (combined.get(me_id) or {}).get('seconds', 0)
    th_sec = (combined.get(th_id) or {}).get('seconds', 0)
    total  = me_sec + th_sec or 1

    me_ud = (user_daily.get(gid) or {}).get(me_id, {})
    th_ud = (user_daily.get(gid) or {}).get(th_id, {})

    embed = discord.Embed(
        title=f"⚔️  เปรียบ Voice — {label}",
        color=CMD_COLORS["compare"],
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)

    def _user_field(uid, display, sec, ud):
        r    = rank_map.get(uid, '?')
        bar  = _bar(sec, total, 12)
        strk = compute_streak(ud.get('dates', {}))
        val  = f"`{bar}`\n**{format_duration(sec)}** · อันดับ #{r}"
        if strk:
            val += f" · 🔥{strk}d"
        return display, val

    me_name,  me_val  = _user_field(me_id, interaction.user.display_name, me_sec, me_ud)
    them_name, th_val = _user_field(th_id, member.display_name,            th_sec, th_ud)

    embed.add_field(name=f"👤 {me_name}",   value=me_val,  inline=True)
    embed.add_field(name="​",           value="​",inline=True)   # spacer
    embed.add_field(name=f"👤 {them_name}", value=th_val,  inline=True)

    diff = abs(me_sec - th_sec)
    if me_sec > th_sec:
        verdict = f"🟢  **{interaction.user.display_name}** นำอยู่ {format_duration(diff)}"
    elif th_sec > me_sec:
        verdict = f"🟢  **{member.display_name}** นำอยู่ {format_duration(diff)}"
    else:
        verdict = "🤝  เท่ากันพอดี!"

    embed.add_field(name="ผลลัพธ์", value=verdict, inline=False)
    _footer(embed)
    await interaction.followup.send(embed=embed)
# ─────────────────────────────────────────────────────────────────────────────

# ── /timeline ────────────────────────────────────────────────────────────────
@client.tree.command(name="timeline", description="ดู Voice timeline ของวันนี้")
@app_commands.describe(
    member="สมาชิกที่ต้องการดู (ค่าเริ่มต้น: ตัวเอง)",
    date="วันที่ในรูปแบบ YYYY-MM-DD (ค่าเริ่มต้น: วันนี้)",
)
@app_commands.checks.cooldown(1, 15.0)
async def slash_timeline(interaction: discord.Interaction,
                         member: discord.Member | None = None,
                         date: str | None = None):
    await interaction.response.defer(ephemeral=True)
    gid     = str(interaction.guild_id) if interaction.guild_id else None
    target  = member or interaction.user
    uid     = str(target.id)
    date_str = date or datetime.now(THAI_TZ).strftime('%Y-%m-%d')

    # Validate date format
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        await interaction.followup.send('รูปแบบวันที่ไม่ถูกต้อง ใช้ YYYY-MM-DD', ephemeral=True)
        return

    # Filter sessions
    day_sessions = [
        s for s in session_history
        if s.get('guild_id') == gid
        and s.get('uid') == uid
        and s.get('join', '').startswith(date_str)
    ]

    # Add live session
    live_info = None
    now = datetime.now(THAI_TZ)
    if now.strftime('%Y-%m-%d') == date_str:
        for (g, m), (_, jt, ch) in list(voice_join_times.items()):
            if str(m) == uid and str(g) == gid:
                elapsed = int((now - jt).total_seconds())
                live_info = (ch, jt, elapsed)

    day_sessions.sort(key=lambda x: x.get('join', ''))
    total_sec = sum(s.get('seconds', 0) for s in day_sessions)
    if live_info:
        total_sec += live_info[2]

    embed = discord.Embed(
        title=f"🕐  Voice Timeline — {target.display_name}",
        color=CMD_COLORS["timeline"],
    )
    if target.display_avatar:
        embed.set_thumbnail(url=target.display_avatar.url)

    if not day_sessions and not live_info:
        embed.description = f"ไม่มีข้อมูล Voice ในวันที่ **{date_str}**"
        _footer(embed)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    session_count = len(day_sessions) + (1 if live_info else 0)

    # Build ASCII 24h bar (each char = 1 hour)
    hour_map = ['░'] * 24
    for s in day_sessions:
        try:
            jh = int(s.get('join', '00:00 ').split(' ')[1].split(':')[0])
            dur_h = max(1, round(s.get('seconds', 0) / 3600))
            for h in range(jh, min(jh + dur_h, 24)):
                hour_map[h] = '█'
        except Exception:
            pass
    if live_info:
        _, jt_live, _ = live_info
        for h in range(jt_live.hour, 24):
            hour_map[h] = '▓'

    ascii_bar = '`00 ' + ''.join(hour_map) + ' 24`'
    embed.description = (
        f"📅 **{date_str}**  ·  ⏱️ รวม **{format_duration(total_sec)}**  ·  {session_count} sessions\n"
        f"{ascii_bar}\n`{''.join(str(h//10) if h%6==0 else ' ' for h in range(24))}`"
    )

    session_rows = []
    for i, s in enumerate(day_sessions, 1):
        leave_t = s.get('leave', '')
        leave_str = leave_t[11:16] if leave_t else '—'
        session_rows.append(
            f"`{i}.` **#{s.get('channel','?')}**  {s['join'][11:16]} → {leave_str}  `{format_duration(s.get('seconds',0))}`"
        )
    if live_info:
        ch, jt_live, elapsed = live_info
        session_rows.append(
            f"`🔴` **#{ch}**  {jt_live.strftime('%H:%M')} → ตอนนี้  `{format_duration(elapsed)}`  *(live)*"
        )

    if session_rows:
        embed.add_field(name="Sessions", value="\n".join(session_rows), inline=False)

    embed.set_footer(
        text=f"AjarnBot  •  {datetime.now(THAI_TZ).strftime('%d/%m %H:%M')}  •  {DASHBOARD_BASE_URL}/profile/{uid}"
    )
    await interaction.followup.send(embed=embed, ephemeral=True)
# ─────────────────────────────────────────────────────────────────────────────

@slash_rank.error
@slash_joke.error
@slash_trivia.error
@slash_stats.error
@slash_compare.error
@slash_timeline.error
@slash_trivia_rank.error
async def on_slash_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        try:
            await interaction.response.send_message(
                embed=_cooldown_embed(error.retry_after), ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send(
                embed=_cooldown_embed(error.retry_after), ephemeral=True)
    else:
        try:
            await interaction.response.send_message(
                embed=_error_embed("เกิดข้อผิดพลาด กรุณาลองใหม่"), ephemeral=True)
        except discord.InteractionResponded:
            pass

@client.event
async def on_message(message):
    if message.author.bot:
        return

    # Check trivia answer
    if message.channel.id in active_trivia:
        trivia_data = active_trivia[message.channel.id]
        try:
            _exp = datetime.fromisoformat(trivia_data['expires'])
            # If naive datetime, localize; if already aware, convert to THAI_TZ
            expires = _exp.replace(tzinfo=THAI_TZ) if _exp.tzinfo is None else _exp.astimezone(THAI_TZ)
        except Exception:
            expires = datetime.now(THAI_TZ)
        if datetime.now(THAI_TZ) <= expires:
            user_ans = message.content.strip().lower()
            correct_ans = trivia_data['answer']
            if user_ans == correct_ans or correct_ans in user_ans:
                q_msg_id = trivia_data.get('q_msg_id')
                active_trivia.pop(message.channel.id, None)
                gid = str(message.guild.id) if message.guild else 'dm'
                uid = str(message.author.id)
                if gid not in trivia_scores:
                    trivia_scores[gid] = {}
                if uid not in trivia_scores[gid]:
                    trivia_scores[gid][uid] = {'name': message.author.display_name, 'score': 0}
                trivia_scores[gid][uid]['score'] += 1
                trivia_scores[gid][uid]['name'] = message.author.display_name
                save_trivia_scores()
                reply_msg = await message.reply(f'🎉 ถูกต้อง! +1 คะแนน (รวม {trivia_scores[gid][uid]["score"]} คะแนน)')
                # ลบข้อความคำถาม + reply หลัง 30 วินาที
                async def _cleanup_trivia(r=reply_msg, qid=q_msg_id, ch=message.channel):
                    await asyncio.sleep(30)
                    for del_target in [r]:
                        try: await del_target.delete()
                        except discord.HTTPException: pass
                    if qid:
                        try:
                            q = await ch.fetch_message(qid)
                            await q.delete()
                        except discord.HTTPException: pass
                asyncio.create_task(_cleanup_trivia())

    if message.content.strip().lower().startswith('!rank'):
        parts = message.content.strip().lower().split()
        period = parts[1] if len(parts) > 1 and parts[1] in ('today', 'week', 'month') else 'week'
        if check_command_rate(message.author.id, 'rank'):
            guild_id = str(message.guild.id) if message.guild else None
            combined = get_stats_for_period(period, guild_id=guild_id)
            await send_leaderboard(message.channel, combined=combined)
        else:
            await message.reply(f'⏳ รอ {COMMAND_COOLDOWN_SEC} วินาทีก่อนใช้คำสั่งนี้อีกครั้ง', delete_after=5)

@client.event
async def on_raw_reaction_add(payload):
    if payload.user_id == client.user.id:
        return
    joke = active_joke_msgs.get(payload.message_id)
    if not joke:
        return
    emoji = str(payload.emoji)
    if emoji not in ('👍', '👎'):
        return
    joke_votes.setdefault(joke, {'up': 0, 'down': 0})
    if emoji == '👍':
        joke_votes[joke]['up'] += 1
    else:
        joke_votes[joke]['down'] += 1
    save_votes()
    threshold = get_gc(payload.guild_id, 'joke_downvote_threshold', 3)
    if emoji == '👎' and joke_votes[joke]['down'] >= threshold:
        channel = client.get_channel(payload.channel_id)
        if channel:
            await channel.send(f'🚫 มุขนี้โดน 👎 ครบ {threshold} ครั้ง — จะไม่ส่งอีกแล้ว')
        active_joke_msgs.pop(payload.message_id, None)

@client.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == client.user.id:
        return
    joke = active_joke_msgs.get(payload.message_id)
    if not joke or joke not in joke_votes:
        return
    emoji = str(payload.emoji)
    if emoji == '👍':
        joke_votes[joke]['up'] = max(0, joke_votes[joke]['up'] - 1)
    elif emoji == '👎':
        joke_votes[joke]['down'] = max(0, joke_votes[joke]['down'] - 1)
    else:
        return
    save_votes()

async def _handle_voice_join(member, after, channel, gid):
    """Handle a member joining a voice channel."""
    record_join(gid, member.id, member.display_name, after.channel.name)
    _persist_avatar(str(gid), str(member.id), member)
    record_voice_event(gid, member.id)
    with _lock_event_counts:
        event_counts['join'] += 1
    if get_gc(gid, 'announce_join', True):
        await channel.send(f'{member.display_name} เข้าห้อง {after.channel.name}')
    fire_outbound_webhook('voice_join', {'user': member.display_name, 'channel': after.channel.name, 'guild': member.guild.name})
    if check_voice_spam(gid, member.id):
        spam_max = get_gc(gid, 'spam_max_events', SPAM_MAX_EVENTS)
        spam_win = get_gc(gid, 'spam_window_sec', SPAM_WINDOW_SEC)
        await channel.send(f'⚠️ {member.display_name} เข้า-ออกห้อง Voice ถี่เกินไป ({spam_max} ครั้งใน {spam_win} วินาที)')


async def _handle_voice_leave(member, before, channel, gid):
    """Handle a member leaving a voice channel."""
    new_milestones = record_leave(gid, member.id)
    record_voice_event(gid, member.id)
    with _lock_event_counts:
        event_counts['leave'] += 1
    if get_gc(gid, 'announce_leave', True):
        await channel.send(f'{member.display_name} ออกจากห้อง {before.channel.name}')
    fire_outbound_webhook('voice_leave', {'user': member.display_name, 'channel': before.channel.name, 'guild': member.guild.name})
    if check_voice_spam(gid, member.id):
        spam_max = get_gc(gid, 'spam_max_events', SPAM_MAX_EVENTS)
        spam_win = get_gc(gid, 'spam_window_sec', SPAM_WINDOW_SEC)
        await channel.send(f'⚠️ {member.display_name} เข้า-ออกห้อง Voice ถี่เกินไป ({spam_max} ครั้งใน {spam_win} วินาที)')
    if new_milestones:
        stats_ch = get_guild_ch(gid, 'stats') or channel
        for hours in sorted(new_milestones):
            await stats_ch.send(
                f'🎉 **{member.display_name}** ใช้เวลา Voice รวมครบ **{hours} ชั่วโมง** แล้ว! ยอดเยี่ยม!')


async def _handle_voice_move(member, before, after, channel, gid):
    """Handle a member moving between voice channels."""
    new_milestones = record_leave(gid, member.id)
    record_join(gid, member.id, member.display_name, after.channel.name)
    if new_milestones:
        stats_ch = get_guild_ch(gid, 'stats') or channel
        for hours in sorted(new_milestones):
            await stats_ch.send(
                f'🎉 **{member.display_name}** ใช้เวลา Voice รวมครบ **{hours} ชั่วโมง** แล้ว! ยอดเยี่ยม!')
    if get_gc(gid, 'announce_move', True):
        await channel.send(f'{member.display_name} ย้ายจาก {before.channel.name} ไป {after.channel.name}')
    fire_outbound_webhook('voice_move', {'user': member.display_name, 'from': before.channel.name, 'to': after.channel.name, 'guild': member.guild.name})


@client.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    channel = get_guild_ch(member.guild.id, 'voice')
    if channel is None:
        return

    gid = member.guild.id

    if before.channel is None and after.channel is not None:
        await _handle_voice_join(member, after, channel, gid)
    elif before.channel is not None and after.channel is None:
        await _handle_voice_leave(member, before, channel, gid)
    elif before.channel != after.channel:
        await _handle_voice_move(member, before, after, channel, gid)

    if before.self_mute != after.self_mute and get_gc(gid, 'announce_mute', True) and check_cooldown(member.id, 'mute', guild_id=gid):
        with _lock_event_counts:
            event_counts['mute'] += 1
        await channel.send(f'{member.display_name} {"ปิดไมค์" if after.self_mute else "เปิดไมค์"}')

    if before.self_deaf != after.self_deaf and get_gc(gid, 'announce_deaf', True) and check_cooldown(member.id, 'deaf', guild_id=gid):
        with _lock_event_counts:
            event_counts['deaf'] += 1
        await channel.send(f'{member.display_name} {"ปิดหู" if after.self_deaf else "เปิดหู"}')

    log(f'stream: {before.self_stream}->{after.self_stream} | video: {before.self_video}->{after.self_video}')
    if before.self_stream != after.self_stream and get_gc(gid, 'announce_stream', True):
        with _lock_event_counts:
            event_counts['stream'] += 1
        await channel.send(f'{member.display_name} {"เริ่ม stream" if after.self_stream else "หยุด stream"}')

    if before.self_video != after.self_video and get_gc(gid, 'announce_video', True):
        with _lock_event_counts:
            event_counts['video'] += 1
        await channel.send(f'{member.display_name} {"เปิดกล้อง" if after.self_video else "ปิดกล้อง"}')
# =======================

# ===== Flask Dashboard =====
flask_app = Flask(__name__)
flask_app.secret_key = _FLASK_SECRET_RAW
flask_app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
flask_app.config['SESSION_COOKIE_SECURE'] = True
flask_app.config['SESSION_COOKIE_HTTPONLY'] = True
flask_app.config['WTF_CSRF_TIME_LIMIT'] = 3600   # CSRF token expires after 1h
flask_app.config['WTF_CSRF_CHECK_DEFAULT'] = False  # validate manually per route
flask_app.config['WTF_CSRF_HEADERS'] = ['X-CSRFToken']   # accept CSRF token from AJAX header
flask_app.permanent_session_lifetime = timedelta(hours=24)  # sessions expire after 24h

csrf = CSRFProtect(flask_app)  # sets up csrf_token() Jinja2 helper + token infrastructure

# Rate limiter — 5 login attempts per minute per IP to prevent brute-force
if _limiter_available:
    _limiter = Limiter(key_func=get_remote_address, app=flask_app,
                       default_limits=[], storage_uri='memory://')
else:
    _limiter = None  # graceful fallback if flask-limiter not installed

@flask_app.after_request
def _set_security_headers(response):
    """Add security headers to every response."""
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://cdn.discordapp.com; "
        "connect-src 'self';"
    )
    return response

_CSRF_SKIP_PATHS = frozenset([
    '/health', '/login', '/callback', '/manifest.json', '/sw.js', '/invite', '/logout',
])

@flask_app.before_request
def _validate_csrf_on_mutating_requests():
    """Validate CSRF token on POST/PUT/PATCH/DELETE — exempt API key + safe paths."""
    if flask_app.testing:
        return   # skip CSRF in unit-test mode — tests use authenticated sessions directly
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    if request.path in _CSRF_SKIP_PATHS:
        return
    # API key = machine-to-machine, exempt from browser CSRF check
    received_key = request.headers.get('X-API-Key', '')
    if DASHBOARD_API_KEY and hmac.compare_digest(received_key, DASHBOARD_API_KEY):
        return
    # Check X-CSRFToken header (AJAX) or csrf_token form field (HTML forms)
    token = request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', '')
    try:
        validate_csrf(token)
    except ValidationError:
        if request.path.startswith('/api/'):
            return jsonify({'error': 'CSRF validation failed — include X-CSRFToken header'}), 403
        return redirect('/login')

# ===== Auth helpers =====
def session_is_owner() -> bool:
    """Owner = password login OR Discord user ID in OWNER_IDS env var"""
    if flask_session.get('login_method') == 'password':
        return True
    uid = (flask_session.get('discord_user') or {}).get('id', '')
    return uid in OWNER_IDS

def session_admin_guild_ids() -> set:
    """Discord guilds where current user has ADMINISTRATOR or MANAGE_GUILD"""
    guilds = flask_session.get('discord_guilds', [])
    return {g['id'] for g in guilds
            if g.get('owner') or (int(g.get('permissions', 0)) & 0x28) != 0}

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # API key bypass (external integrations)
        received_key = request.headers.get('X-API-Key', '')
        if DASHBOARD_API_KEY and hmac.compare_digest(received_key, DASHBOARD_API_KEY):
            return f(*args, **kwargs)
        if not flask_session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

def require_owner(f):
    """เฉพาะ owner เท่านั้น (global config, sensitive ops)"""
    @wraps(f)
    def decorated(*args, **kwargs):
        received_key = request.headers.get('X-API-Key', '')
        if DASHBOARD_API_KEY and hmac.compare_digest(received_key, DASHBOARD_API_KEY):
            return f(*args, **kwargs)
        if not flask_session.get('logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        if not session_is_owner():
            return jsonify({'error': 'Forbidden — owner only'}), 403
        return f(*args, **kwargs)
    return decorated

def require_guild_access(guild_id: str):
    """ตรวจว่า current user มีสิทธิ์ใน guild นี้ (owner หรือ admin ของ guild)"""
    if session_is_owner():
        return True
    return guild_id in session_admin_guild_ids()

_SNOWFLAKE_RE = re.compile(r'^\d{1,20}$')

def _validate_snowflake(value: str) -> bool:
    """Validate that a guild_id is a positive integer string (Discord snowflake format)."""
    return bool(_SNOWFLAKE_RE.match(value))

def _guild_id_or_error():
    """
    ดึง guild_id จาก request.args และตรวจ access.
    คืน (guild_id_str, None) ถ้าโอเค
    คืน (None, Response) ถ้า error — caller ต้อง return response ทันที
    """
    guild_id = request.args.get('guild_id', '').strip()
    if not guild_id:
        return None, (jsonify({'error': 'guild_id is required'}), 400)
    if not _validate_snowflake(guild_id):
        return None, (jsonify({'error': 'invalid guild_id format'}), 400)
    if not require_guild_access(guild_id):
        return None, (jsonify({'error': 'Forbidden'}), 403)
    return guild_id, None

@flask_app.route('/api/csrf-token')
@require_auth
def api_csrf_token():
    """Return a fresh CSRF token for use in AJAX POST requests."""
    from flask_wtf.csrf import generate_csrf
    return jsonify({'token': generate_csrf()})
# ========================

def _login_route(f):
    """Apply rate-limit decorator when flask-limiter is available."""
    if _limiter is not None:
        return _limiter.limit('5 per minute')(f)
    return f


@flask_app.route('/login', methods=['GET', 'POST'])
@_login_route
def login():
    # Password login is owner-only emergency access.
    # Hide the form if no password is configured, or if Discord login is available
    # (Discord login is the preferred method for all users including the owner).
    show_pw    = bool(DASHBOARD_PASSWORD)
    has_invite = bool(DISCORD_CLIENT_ID)
    if request.method == 'POST':
        try:
            validate_csrf(request.form.get('csrf_token'))
        except ValidationError:
            return render_template('login.html', discord_client_id=DISCORD_CLIENT_ID,
                                   show_pw=show_pw, has_invite=has_invite,
                                   error_msg='Session หมดอายุ กรุณาลองใหม่')
        pw = request.form.get('password', '')
        if DASHBOARD_PASSWORD and hmac.compare_digest(pw, DASHBOARD_PASSWORD):
            flask_session['logged_in'] = True
            flask_session['login_method'] = 'password'
            flask_session['is_owner'] = True   # password login always = owner
            flask_session.permanent = True
            return redirect('/')
        log(f'Failed password login attempt from {request.remote_addr}')
        return render_template('login.html', discord_client_id=DISCORD_CLIENT_ID,
                               show_pw=show_pw, has_invite=has_invite,
                               error_msg='รหัสผ่านไม่ถูกต้อง')
    return render_template('login.html', discord_client_id=DISCORD_CLIENT_ID,
                           show_pw=show_pw, has_invite=has_invite, error_msg='')

@flask_app.route('/login/discord')
def login_discord():
    if not DISCORD_CLIENT_ID:
        return redirect('/login')
    state = secrets.token_hex(16)
    flask_session['oauth_state'] = state
    params = urllib.parse.urlencode({
        'client_id': DISCORD_CLIENT_ID,
        'redirect_uri': DISCORD_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'identify guilds',
        'state': state,
    })
    return redirect(f'https://discord.com/api/oauth2/authorize?{params}')

@flask_app.route('/callback')
def oauth_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    if error:
        log(f'Discord OAuth denied: {error} — {request.args.get("error_description", "")}')
        return redirect('/login')
    if not code:
        log('Discord OAuth callback: no code received')
        return redirect('/login')
    # State check — always enforce to prevent CSRF
    expected_state = flask_session.get('oauth_state')
    if not expected_state or state != expected_state:
        log(f'Discord OAuth state mismatch: got {state}, expected {expected_state}')
        return redirect('/login')
    flask_session.pop('oauth_state', None)  # consume state — prevent replay
    try:
        # Exchange code for token
        data = urllib.parse.urlencode({
            'client_id': DISCORD_CLIENT_ID,
            'client_secret': DISCORD_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': DISCORD_REDIRECT_URI,
        }).encode()
        UA = 'AjarnBot/1.0 (https://ajarnbot.up.railway.app)'
        req = urllib.request.Request('https://discord.com/api/oauth2/token', data=data,
                                      headers={'Content-Type': 'application/x-www-form-urlencoded',
                                               'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_data = json.loads(resp.read().decode())
        access_token = token_data['access_token']
        # Get user info
        req2 = urllib.request.Request('https://discord.com/api/v10/users/@me',
                                       headers={'Authorization': f'Bearer {access_token}',
                                                'User-Agent': UA})
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            user = json.loads(resp2.read().decode())
        # Get user guilds
        req3 = urllib.request.Request('https://discord.com/api/v10/users/@me/guilds',
                                       headers={'Authorization': f'Bearer {access_token}',
                                                'User-Agent': UA})
        with urllib.request.urlopen(req3, timeout=10) as resp3:
            all_guilds = json.loads(resp3.read().decode())
        # Filter to guilds where: bot is present AND user has ADMINISTRATOR or MANAGE_GUILD
        bot_guild_ids = {str(g.id) for g in client.guilds}
        ADMIN_PERMS = 0x8 | 0x20   # ADMINISTRATOR | MANAGE_GUILD
        user_guilds = [
            g for g in all_guilds
            if g['id'] in bot_guild_ids
            and (g.get('owner') or (int(g.get('permissions', 0)) & ADMIN_PERMS) != 0)
        ]
        flask_session['discord_user'] = user
        flask_session['discord_guilds'] = user_guilds
        flask_session['logged_in'] = True
        flask_session['current_guild_id'] = ''   # always force guild selection
        return redirect('/select-server')
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, Exception) as e:
        import traceback
        log(f'Discord OAuth error: {e}\n{traceback.format_exc()}')
        return redirect('/login?oauth_error=1')

@flask_app.route('/select-server')
def select_server():
    if not flask_session.get('logged_in'):
        return redirect('/login')
    user = flask_session.get('discord_user', {})
    raw_guilds = flask_session.get('discord_guilds', [])
    username = user.get('global_name') or user.get('username', 'User')
    uid = user.get('id', '')
    avatar = user.get('avatar', '')
    avatar_url = f'https://cdn.discordapp.com/avatars/{uid}/{avatar}.png' if avatar else None
    avatar_initial = (username[0].upper() if username else '?')
    guilds_data = []
    for g in raw_guilds:
        gid = g['id']
        name = g.get('name', gid)
        icon = g.get('icon', '')
        bot_g = client.get_guild(int(gid))
        guilds_data.append({
            'id':           gid,
            'name':         name,
            'icon_url':     f'https://cdn.discordapp.com/icons/{gid}/{icon}.png' if icon else None,
            'initial':      name[0].upper() if name else '?',
            'member_count': bot_g.member_count if bot_g else None,
        })
    return render_template('select_server.html',
                           username=username,
                           avatar_url=avatar_url,
                           avatar_initial=avatar_initial,
                           guilds=guilds_data)

@flask_app.route('/set-guild/<guild_id>')
def set_guild(guild_id):
    if not flask_session.get('logged_in'):
        return redirect('/login')
    guilds = flask_session.get('discord_guilds', [])
    guild_ids = [g['id'] for g in guilds]
    if guilds and guild_id not in guild_ids:
        return redirect('/select-server')
    flask_session['current_guild_id'] = guild_id
    return redirect('/')

@flask_app.route('/api/set-guild', methods=['POST'])
@require_auth
def api_set_guild():
    """Switch current guild without full page reload — used by dashboard guild switcher"""
    data = request.get_json(silent=True) or {}
    guild_id = str(data.get('guild_id', ''))
    guilds = flask_session.get('discord_guilds', [])
    guild_ids = [g['id'] for g in guilds]
    if guilds and guild_id not in guild_ids:
        return jsonify({'error': 'Forbidden'}), 403
    flask_session['current_guild_id'] = guild_id
    return jsonify({'ok': True, 'guild_id': guild_id})

@flask_app.route('/invite')
def bot_invite():
    """Redirect to Discord bot invite URL"""
    if not DISCORD_CLIENT_ID:
        return 'DISCORD_CLIENT_ID ยังไม่ได้ตั้งค่า', 503
    # Permissions: VIEW_CHANNEL + SEND_MESSAGES + MANAGE_MESSAGES + READ_MESSAGE_HISTORY + ADD_REACTIONS + USE_APPLICATION_COMMANDS
    # MANAGE_MESSAGES (8192) required for deleting bot's own messages after trivia/joke
    perms = 1024 + 2048 + 8192 + 65536 + 64 + 2147483648
    url = (f'https://discord.com/oauth2/authorize'
           f'?client_id={DISCORD_CLIENT_ID}'
           f'&scope=bot+applications.commands'
           f'&permissions={perms}')
    return redirect(url)

@flask_app.route('/logout')
def logout():
    flask_session.clear()
    return redirect('/login')

# ===== Feature 7: PWA manifest & service worker =====
MANIFEST_JSON = '''{
  "name": "VoiceLog Bot",
  "short_name": "VoiceLog",
  "description": "Discord VoiceLog Bot Dashboard",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#1e1f22",
  "theme_color": "#5865f2",
  "icons": [
    {"src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎙️</text></svg>", "sizes": "any", "type": "image/svg+xml"}
  ]
}'''

SERVICE_WORKER_JS = """
const CACHE = 'voicelog-v1';
const OFFLINE = ['/'];
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(OFFLINE))));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
"""

@flask_app.route('/manifest.json')
def manifest():
    return MANIFEST_JSON, 200, {'Content-Type': 'application/json'}

@flask_app.route('/sw.js')
def service_worker():
    return SERVICE_WORKER_JS, 200, {'Content-Type': 'application/javascript'}
# ====================================================

@flask_app.route('/')
@require_auth
def dashboard():
    guild_id = flask_session.get('current_guild_id', '')
    login_method = flask_session.get('login_method', '')
    # Discord login — must pick a guild first
    if login_method != 'password' and not guild_id:
        guilds = flask_session.get('discord_guilds', [])
        if not guilds:
            return redirect('/no-bot')    # bot not in any of their servers
        return redirect('/select-server')
    return render_template('dashboard.html', current_guild_id=guild_id)

@flask_app.route('/no-bot')
def no_bot():
    if not flask_session.get('logged_in'):
        return redirect('/login')
    user = flask_session.get('discord_user', {})
    username = user.get('global_name') or user.get('username', 'User')
    uid = user.get('id', '')
    avatar = user.get('avatar', '')
    avatar_url = f'https://cdn.discordapp.com/avatars/{uid}/{avatar}.png' if avatar else None
    avatar_initial = username[0].upper() if username else '?'
    return render_template('no_bot.html', username=username,
                           avatar_url=avatar_url, avatar_initial=avatar_initial,
                           invite_url='/invite')

@flask_app.route('/profile/<uid>')
@require_auth
def profile_page(uid):
    return render_template('profile.html')

@flask_app.route('/api/status')
@require_auth
def api_status():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    online     = client.is_ready()
    uptime_sec = int((datetime.now(THAI_TZ) - start_time).total_seconds())
    voice_users = []
    for (gid, mid), (name, join_time, ch) in voice_join_times.items():
        if str(gid) != guild_id:
            continue
        elapsed = int((datetime.now(THAI_TZ) - join_time).total_seconds())
        guild_obj = client.get_guild(gid)
        member_obj = guild_obj.get_member(mid) if guild_obj else None
        avatar_url = str(member_obj.display_avatar.url) if member_obj and member_obj.display_avatar else None
        voice_users.append({'name': name, 'duration': format_duration(elapsed), 'channel': ch, 'guild_id': str(gid), 'avatar': avatar_url})
    combined = get_stats_for_period('week', guild_id=guild_id)
    stats_sorted   = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)
    weekly_display = [{'uid': k, 'name': v['name'], 'time': format_duration(v['seconds'])} for k, v in stats_sorted[:10]]
    # Avg / median session duration — cached 60s to avoid O(n) scan on every poll
    _sc = _status_sess_cache.get(guild_id)
    if _sc and time.monotonic() < _sc[3]:
        total_sessions, avg_secs, median_secs = _sc[0], _sc[1], _sc[2]
    else:
        with _lock_history:
            guild_secs = [s['seconds'] for s in session_history
                          if s.get('guild_id') == guild_id and s.get('seconds', 0) > 0]
        total_sessions = len(guild_secs)
        if guild_secs:
            avg_secs    = int(sum(guild_secs) / total_sessions)
            sorted_secs = sorted(guild_secs)
            mid = total_sessions // 2
            median_secs = sorted_secs[mid] if total_sessions % 2 else (sorted_secs[mid - 1] + sorted_secs[mid]) // 2
        else:
            avg_secs = median_secs = 0
        _status_sess_cache[guild_id] = (total_sessions, avg_secs, median_secs, time.monotonic() + _STATUS_SESS_TTL)
    # event_counts is global — expose only guild-relevant subset
    ec = event_counts
    return jsonify({
        'online': online, 'uptime': format_duration(uptime_sec),
        'voice_users': voice_users, 'weekly_stats': weekly_display,
        'total_sessions': total_sessions,
        'avg_session_min': round(avg_secs / 60, 1),
        'median_session_min': round(median_secs / 60, 1),
        'avg_session_fmt': format_duration(avg_secs),
        'event_counts': ec,
    })

@flask_app.route('/api/my-guilds')
@require_auth
def api_my_guilds():
    """
    Return guilds where:
    - bot is present, AND
    - current user is admin/owner of that guild (from Discord OAuth session)
    Owners (password login or OWNER_IDS) see all guilds the bot is in.
    """
    if session_is_owner():
        guilds = [
            {'id': str(g.id), 'name': g.name,
             'member_count': g.member_count,
             'icon': None}
            for g in client.guilds
        ]
        return jsonify(guilds)
    # Discord login — filter to guilds user has admin access
    discord_guilds = flask_session.get('discord_guilds', [])
    bot_guild_ids = {str(g.id) for g in client.guilds}
    guilds = []
    for dg in discord_guilds:
        gid = dg['id']
        if gid not in bot_guild_ids:
            continue
        bot_g = client.get_guild(int(gid))
        guilds.append({
            'id': gid,
            'name': dg.get('name', gid),
            'member_count': bot_g.member_count if bot_g else None,
            'icon': dg.get('icon'),
        })
    return jsonify(guilds)

@flask_app.route('/api/stats/<period>')
@require_auth
def api_stats_period(period):
    if period not in ('today', 'week', 'month'):
        return jsonify({'error': 'period must be today, week, or month'}), 400
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    data = get_stats_for_period(period, guild_id=guild_id)
    return jsonify(data)

@flask_app.route('/api/guilds')
@require_auth
def api_guilds():
    # If logged in via Discord, filter to guilds where user has admin perms
    discord_guilds = flask_session.get('discord_guilds')
    ADMIN_PERMS = 0x8 | 0x20  # ADMINISTRATOR | MANAGE_GUILD
    if discord_guilds:
        admin_ids = {g['id'] for g in discord_guilds
                     if g.get('owner') or (int(g.get('permissions', 0)) & ADMIN_PERMS) != 0}
        guilds = [{'id': str(g.id), 'name': g.name, 'member_count': g.member_count}
                  for g in client.guilds if str(g.id) in admin_ids]
    elif session_is_owner():
        # Password-login owner: may see all guilds
        guilds = [{'id': str(g.id), 'name': g.name, 'member_count': g.member_count}
                  for g in client.guilds]
    else:
        guilds = []
    return jsonify(guilds)

@flask_app.route('/api/channels')
@require_auth
def api_channels():
    guild_id = request.args.get('guild_id', '').strip()
    if not guild_id:
        return jsonify([])
    if not require_guild_access(guild_id):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        g = client.get_guild(int(guild_id))
    except ValueError:
        return jsonify({'error': 'invalid guild_id'}), 400
    if not g:
        return jsonify([])
    channels = [{'id': str(c.id), 'name': c.name}
                for c in sorted(g.text_channels, key=lambda c: c.position)]
    return jsonify(channels)

@flask_app.route('/api/config', methods=['GET'])
@require_auth
def api_config_get():
    data = dict(bot_config)
    data['is_owner'] = session_is_owner()   # ส่งสถานะให้ frontend ปรับ UI
    data['app_version'] = APP_VERSION
    data['app_build_date'] = APP_BUILD_DATE
    return jsonify(data)

_INT_RANGES = {
    'joke_delay':               (1,   1440),
    'trivia_delay':             (1,   1440),
    'content_interval':         (5,   1440),
    'summary_hour':             (0,   23),
    'joke_downvote_threshold':  (1,   100),
    'spam_max_events':          (2,   100),
    'spam_window_sec':          (10,  3600),
    'mute_cooldown_sec':        (1,   300),
}

@flask_app.route('/api/config', methods=['POST'])
@require_owner   # global config = owner only
def api_config_post():
    data = request.json or {}
    errors = {}
    for key in bot_config:
        if key not in data:
            continue
        val = data[key]
        if key.startswith('channel_') and val:
            try:
                bot_config[key] = int(val)
            except (ValueError, TypeError):
                errors[key] = 'must be a valid channel ID integer'
        elif key in _INT_RANGES:
            try:
                v = int(val)
                lo, hi = _INT_RANGES[key]
                if not (lo <= v <= hi):
                    errors[key] = f'must be between {lo} and {hi}'
                else:
                    bot_config[key] = v
            except (ValueError, TypeError):
                errors[key] = 'must be an integer'
        else:
            bot_config[key] = val
    if errors:
        return jsonify({'ok': False, 'errors': errors}), 400
    save_config()
    if 'content_interval' in data and send_content.is_running():
        try:
            send_content.change_interval(minutes=int(bot_config['content_interval']))
        except Exception:
            pass
    return jsonify({'ok': True})

@flask_app.route('/api/guild-config', methods=['GET'])
@require_auth
def api_guild_config_get():
    guild_id = request.args.get('guild_id', '').strip()
    if not guild_id:
        return jsonify({'error': 'guild_id required'}), 400
    if not require_guild_access(guild_id):
        return jsonify({'error': 'Forbidden'}), 403
    # Return effective config: per-guild overrides merged on top of global defaults
    # NOTE: channel fields use per-guild value ONLY — no global fallback.
    # Global VOICE_LOG_CHANNEL_ID belongs to a different guild so it would
    # never match any option in the current guild's dropdown.
    CHANNEL_KEYS = {'channel_voice', 'channel_content', 'channel_stats'}
    per_guild = guild_configs.get(str(guild_id), {})
    effective = {}
    for key in GUILD_ADMIN_KEYS:
        if key in CHANNEL_KEYS:
            # Return explicitly saved value or None (not global fallback)
            effective[key] = per_guild.get(key)
        else:
            effective[key] = get_gc(guild_id, key)
    # Also include raw per-guild overrides so frontend can show what's customised
    effective['_overrides'] = per_guild
    return jsonify(effective)

@flask_app.route('/api/guild-config', methods=['POST'])
@require_auth
def api_guild_config_post():
    data = request.json or {}
    guild_id = str(data.get('guild_id', '')).strip()
    if not guild_id:
        return jsonify({'ok': False, 'error': 'guild_id required'}), 400
    if not require_guild_access(guild_id):
        return jsonify({'error': 'Forbidden'}), 403
    # Re-verify bot is still in this guild (prevents stale session entitlements)
    if not session_is_owner():
        try:
            _bot_guild = client.get_guild(int(guild_id))
        except (ValueError, OverflowError):
            _bot_guild = None
        if _bot_guild is None:
            return jsonify({'error': 'Guild not found — bot may have left the server'}), 403
    if guild_id not in guild_configs:
        guild_configs[guild_id] = {}
    channel_keys = {'channel_voice', 'channel_content', 'channel_stats'}
    bool_keys    = {k for k in GUILD_ADMIN_KEYS if k.startswith('announce_') or k.startswith('send_')}
    int_keys     = GUILD_ADMIN_KEYS - channel_keys - bool_keys
    for key in GUILD_ADMIN_KEYS:
        if key not in data:
            continue
        val = data[key]
        if val is None or val == '':
            # Empty → remove override (revert to global default)
            guild_configs[guild_id].pop(key, None)
        elif key in channel_keys:
            try:
                guild_configs[guild_id][key] = int(val)
            except (ValueError, TypeError):
                pass
        elif key in bool_keys:
            guild_configs[guild_id][key] = bool(val)
        elif key in int_keys:
            try:
                guild_configs[guild_id][key] = int(val)
            except (ValueError, TypeError):
                pass
    save_guild_configs()
    return jsonify({'ok': True})

@flask_app.route('/api/heatmap')
@require_auth
def api_heatmap():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    return jsonify({guild_id: hourly_activity.get(guild_id, {str(h): 0 for h in range(24)})})

@flask_app.route('/api/history')
@require_auth
def api_history():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    with _lock_history:
        filtered = [s for s in session_history if s.get('guild_id') == guild_id]
    return jsonify(filtered[-50:])

@flask_app.route('/api/profile/<uid>')
@require_auth
def api_profile(uid):
    if not _validate_snowflake(uid):
        return jsonify({'error': 'invalid uid'}), 400
    # Accept guild_id from query param OR fall back to session (for direct URL access)
    guild_id = request.args.get('guild_id', '').strip()
    if not guild_id:
        guild_id = str(flask_session.get('current_guild_id', '')).strip()
    if not guild_id:
        return jsonify({'error': 'guild_id is required'}), 400
    if not require_guild_access(guild_id):
        return jsonify({'error': 'Forbidden'}), 403
    # Scope to the requested guild only
    seconds = 0
    name = 'Unknown'
    gdata = weekly_stats.get(str(guild_id), {})
    if uid in gdata:
        seconds += gdata[uid].get('seconds', 0)
        name = gdata[uid].get('name', name)
    # Add live time if member is currently in voice in this guild
    for (gid, mid), (n, jt, _) in voice_join_times.items():
        if str(mid) == uid and str(gid) == guild_id:
            seconds += int((datetime.now(THAI_TZ) - jt).total_seconds())
            name = n
    with _lock_history:
        sessions = [s for s in session_history
                    if s.get('guild_id') == guild_id and s.get('uid') == uid]
    hour_counts = {}
    for s in sessions:
        try:
            h = str(int(s['join'].split(' ')[1].split(':')[0]))
            hour_counts[h] = hour_counts.get(h, 0) + 1
        except Exception as e:
            log(f'profile hour_counts: bad join format: {e}')
    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None
    avg_sec   = (sum(s['seconds'] for s in sessions) // len(sessions)) if sessions else 0
    # Enrich from user_daily if available
    ud = user_daily.get(str(guild_id), {}).get(uid, {})
    # Avatar from bot cache
    avatar_url = None
    try:
        guild_obj = client.get_guild(int(guild_id))
        if guild_obj:
            member_obj = guild_obj.get_member(int(uid))
            if member_obj and member_obj.display_avatar:
                avatar_url = str(member_obj.display_avatar.url)
    except Exception:
        pass
    return jsonify({'uid': uid, 'name': name, 'total_seconds': seconds,
                    'total_duration': format_duration(seconds), 'session_count': len(sessions),
                    'avg_duration': format_duration(avg_sec) if avg_sec else '-',
                    'peak_hour': peak_hour,
                    'hour_counts': {str(h): hour_counts.get(str(h), 0) for h in range(24)},
                    'sessions': list(reversed(sessions[-20:])),
                    'alltime_seconds':  ud.get('alltime_seconds', seconds),
                    'streak_max':       ud.get('streak_max', 0),
                    'channel_seconds':  ud.get('channel_seconds', {}),
                    'first_seen':       ud.get('first_seen'),
                    'last_seen':        ud.get('last_seen'),
                    'avatar_url':       avatar_url,
                    'note':             _sheets_notes.get(str(guild_id), {}).get(uid, ''),
                    })

@flask_app.route('/api/timeline/<uid>')
@require_auth
def api_timeline(uid: str):
    """Return all sessions for a user on a given date (default: today).
    ?guild_id=X&date=YYYY-MM-DD
    """
    guild_id = request.args.get('guild_id', '').strip()
    if not guild_id:
        guild_id = str(flask_session.get('current_guild_id', '')).strip()
    if not guild_id:
        return jsonify({'error': 'guild_id is required'}), 400
    if not require_guild_access(guild_id):
        return jsonify({'error': 'Forbidden'}), 403

    date_str = request.args.get('date', '').strip()
    if date_str:
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({'error': 'invalid date format, use YYYY-MM-DD'}), 400
    else:
        date_str = datetime.now(THAI_TZ).strftime('%Y-%m-%d')

    # Filter sessions for this user + guild on the requested date
    day_sessions = []
    for s in session_history:
        if s.get('guild_id') != guild_id or s.get('uid') != uid:
            continue
        join_str = s.get('join', '')
        if not join_str.startswith(date_str):
            continue
        day_sessions.append({
            'channel':  s.get('channel', '?'),
            'join':     join_str,
            'leave':    s.get('leave', ''),
            'seconds':  s.get('seconds', 0),
            'duration': format_duration(s.get('seconds', 0)),
        })

    # Add ongoing live session if user is currently in voice today
    now = datetime.now(THAI_TZ)
    if now.strftime('%Y-%m-%d') == date_str:
        for (gid, mid), (dname, jt, ch_name) in list(voice_join_times.items()):
            if str(mid) == uid and str(gid) == guild_id:
                elapsed = int((now - jt).total_seconds())
                day_sessions.append({
                    'channel':  ch_name,
                    'join':     jt.strftime('%Y-%m-%d %H:%M'),
                    'leave':    '',          # ongoing
                    'seconds':  elapsed,
                    'duration': format_duration(elapsed) + ' (กำลังอยู่)',
                    'live':     True,
                })

    day_sessions.sort(key=lambda x: x['join'])

    total_sec = sum(s['seconds'] for s in day_sessions)
    return jsonify({
        'uid':        uid,
        'date':       date_str,
        'sessions':   day_sessions,
        'total_sec':  total_sec,
        'total_dur':  format_duration(total_sec) if total_sec else '0',
        'count':      len(day_sessions),
    })

@flask_app.route('/api/members')
@require_auth
def api_members():
    """คืน list สมาชิกทั้งหมดใน guild พร้อม stats + avatar_url"""
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    guild_obj = client.get_guild(int(guild_id))
    ud = user_daily.get(str(guild_id), {})
    ws = weekly_stats.get(str(guild_id), {})
    gid_str = str(guild_id)
    # UIDs currently in voice for this guild
    in_voice_uids: set[str] = {
        str(mid) for (gid_k, mid) in voice_join_times if str(gid_k) == gid_str
    }
    # Start with tracked users (from voice sessions)
    seen = set(ud.keys()) | set(ws.keys())
    result_map: dict = {}
    for uid_str in seen:
        udata = ud.get(uid_str, {})
        wdata = ws.get(uid_str, {})
        stored_avatar = udata.get('avatar_url') or _default_avatar_url(uid_str)
        in_voice = uid_str in in_voice_uids
        result_map[uid_str] = {
            'uid':              uid_str,
            'name':             udata.get('name') or wdata.get('name') or 'Unknown',
            'alltime_seconds':  udata.get('alltime_seconds', wdata.get('seconds', 0)),
            'alltime_duration': format_duration(udata.get('alltime_seconds', wdata.get('seconds', 0))),
            'session_count':    udata.get('session_count', 0),
            'last_seen':        udata.get('last_seen', ''),
            'streak_max':       udata.get('streak_max', 0),
            'avatar_url':       stored_avatar,
            'in_voice':         in_voice,
            'status':           'voice' if in_voice else 'offline',
        }
    # Also include / enrich from cached guild members (live presence data)
    _dirty = False
    if guild_obj:
        for member in guild_obj.members:
            if member.bot:
                continue
            uid_str = str(member.id)
            live_url = _build_avatar_url(member) or _default_avatar_url(uid_str)
            in_voice = uid_str in in_voice_uids
            # Resolve presence status
            try:
                raw_status = str(member.status.value)   # 'online'|'idle'|'dnd'|'offline'
            except Exception:
                raw_status = 'offline'
            status_str = 'voice' if in_voice else raw_status
            if uid_str not in result_map:
                result_map[uid_str] = {
                    'uid':              uid_str,
                    'name':             member.display_name,
                    'alltime_seconds':  0,
                    'alltime_duration': '-',
                    'session_count':    0,
                    'last_seen':        '',
                    'streak_max':       0,
                    'avatar_url':       live_url,
                    'in_voice':         in_voice,
                    'status':           status_str,
                }
            else:
                result_map[uid_str]['avatar_url'] = live_url
                result_map[uid_str]['in_voice']   = in_voice
                result_map[uid_str]['status']     = status_str
                if result_map[uid_str]['name'] in ('Unknown', ''):
                    result_map[uid_str]['name'] = member.display_name
            # Keep user_daily avatar fresh
            ud_entry = ud.get(uid_str)
            if ud_entry and ud_entry.get('avatar_url') != live_url:
                ud_entry['avatar_url'] = live_url
                _dirty = True
    if _dirty:
        save_user_daily()
    # Sort priority: voice > online > idle > dnd > offline
    _status_order = {'voice': 0, 'online': 1, 'idle': 2, 'dnd': 3, 'offline': 4}
    result = sorted(
        result_map.values(),
        key=lambda x: (_status_order.get(x.get('status', 'offline'), 4),
                       -x.get('alltime_seconds', 0)),
    )
    return jsonify(result)

@flask_app.route('/api/votes')
@require_auth
def api_votes():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    threshold = get_gc(guild_id, 'joke_downvote_threshold', 3)
    result = []
    for joke, v in joke_votes.items():
        result.append({'joke': joke[:80]+('…' if len(joke)>80 else ''),
                       'up': v.get('up',0), 'down': v.get('down',0),
                       'score': v.get('up',0)-v.get('down',0),
                       'filtered': v.get('down',0)>=threshold})
    result.sort(key=lambda x: x['score'], reverse=True)
    return jsonify(result)

@flask_app.route('/api/votes/reset', methods=['POST'])
@require_auth
def api_votes_reset():
    # Guild admins can reset votes for their own guild; owners can always reset
    data = request.get_json(silent=True) or {}
    guild_id = str(data.get('guild_id', '') or flask_session.get('current_guild_id', '')).strip()
    if guild_id and not require_guild_access(guild_id):
        return jsonify({'error': 'Forbidden'}), 403
    if not guild_id and not session_is_owner():
        return jsonify({'error': 'Forbidden — guild_id required or owner login'}), 403
    joke_votes.clear()
    save_votes()
    return jsonify({'ok': True})

# ── Google Sheets Integration ─────────────────────────────────────────────────
_sheets_lock      = threading.Lock()
_sheets_last_sync = None    # datetime string of last successful sync
_sheets_last_err  = None    # last error message
_sheets_notes     = {}      # {guild_id: {uid: note}} — imported from Members tab

def _get_gspread():
    """Return authenticated gspread client or None if not configured."""
    if not GOOGLE_SHEET_ID or not GOOGLE_SHEETS_CREDENTIALS:
        return None, 'Google Sheets not configured (GOOGLE_SHEET_ID / GOOGLE_SHEETS_CREDENTIALS missing)'
    try:
        import gspread
        from google.oauth2.service_account import Credentials as SACredentials
        creds_dict = json.loads(GOOGLE_SHEETS_CREDENTIALS)
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
        ]
        creds = SACredentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        return gc, None
    except Exception as e:
        return None, str(e)

def _ensure_tab(ss, title, header):
    """Get or create a worksheet tab with the given header row."""
    try:
        ws = ss.worksheet(title)
    except Exception:
        ws = ss.add_worksheet(title=title, rows=5000, cols=max(len(header), 10))
    current_header = ws.row_values(1)
    if current_header != header:
        ws.update('A1', [header])
    return ws

def _guild_display_name(gid):
    """Return readable guild name for use as sheet tab suffix."""
    guild_obj = client.get_guild(int(gid)) if gid.isdigit() else None
    return guild_obj.name if guild_obj else gid

def _rgb(r, g, b):
    """Convert 0-255 RGB to Sheets API float format."""
    return {'red': r/255, 'green': g/255, 'blue': b/255}

def _format_tab(ss, ws, tab_color_rgb, num_data_rows=0):
    """
    Apply beautiful formatting to a worksheet:
    - Bold + colored header row with white text
    - Freeze header row
    - Alternating row colors
    - Tab color
    - Auto-resize columns
    """
    sid      = ws.id
    num_cols = ws.col_count
    end_row  = max(num_data_rows + 1, 2)

    # Build base requests (always safe to run)
    requests = [
        # Freeze row 1
        {'updateSheetProperties': {
            'properties': {'sheetId': sid, 'gridProperties': {'frozenRowCount': 1}},
            'fields': 'gridProperties.frozenRowCount',
        }},
        # Tab color
        {'updateSheetProperties': {
            'properties': {'sheetId': sid, 'tabColor': tab_color_rgb},
            'fields': 'tabColor',
        }},
        # Header: bold, colored background, white text, center-aligned
        {'repeatCell': {
            'range': {'sheetId': sid, 'startRowIndex': 0, 'endRowIndex': 1,
                      'startColumnIndex': 0, 'endColumnIndex': num_cols},
            'cell': {'userEnteredFormat': {
                'backgroundColor': tab_color_rgb,
                'textFormat': {
                    'bold': True, 'fontSize': 11,
                    'foregroundColor': {'red': 1, 'green': 1, 'blue': 1},
                },
                'horizontalAlignment': 'CENTER',
                'verticalAlignment': 'MIDDLE',
            }},
            'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)',
        }},
        # Auto-resize all columns
        {'autoResizeDimensions': {
            'dimensions': {'sheetId': sid, 'dimension': 'COLUMNS',
                           'startIndex': 0, 'endIndex': num_cols},
        }},
    ]

    # Banding (alternating rows) — skip if fails (already exists)
    banding_req = {'addBanding': {
        'bandedRange': {
            'sheetId': sid,
            'range': {'sheetId': sid, 'startRowIndex': 1, 'endRowIndex': end_row,
                      'startColumnIndex': 0, 'endColumnIndex': num_cols},
            'rowProperties': {
                'firstBandColor':  {'red': 1.0, 'green': 1.0, 'blue': 1.0},
                'secondBandColor': {'red': 0.94, 'green': 0.97, 'blue': 1.0},
            },
        },
    }}
    try:
        ss.batch_update({'requests': requests + [banding_req]})
    except Exception:
        # Banding already exists on this sheet — run without it
        try:
            ss.batch_update({'requests': requests})
        except Exception as e:
            log(f'sheets: format warning: {e}')

def _sheets_sync_sessions(ss, gid: str, sfx: str, session_history) -> int:
    """Write Sessions tab. Returns row count."""
    tab = _ensure_tab(ss, f'📋 Sessions{sfx}',
        ['Guild', 'Member', 'Channel', 'Join', 'Leave', 'Duration (min)', 'Seconds'])
    rows = [
        [s.get('guild_id',''), s.get('name',''), s.get('channel',''),
         s.get('join',''), s.get('leave',''),
         round(s.get('seconds', 0) / 60, 1), s.get('seconds', 0)]
        for s in session_history if s.get('guild_id') == gid
    ]
    if rows:
        tab.resize(rows=len(rows) + 1)
        tab.update('A2', rows)
    _format_tab(ss, tab, _rgb(66, 133, 244), len(rows))
    return len(rows)


def _sheets_sync_leaderboard(ss, gid: str, sfx: str, ud: dict, ws_: dict) -> tuple[list, int]:
    """Write Leaderboard tab. Returns (lb_data, row_count)."""
    tab = _ensure_tab(ss, f'🏆 Leaderboard{sfx}',
        ['Rank', 'Name', 'Total Hours', 'Total Seconds', 'Sessions',
         'Streak Max', 'First Seen', 'Last Seen'])
    all_uids = set(ud.keys()) | set(ws_.keys())
    lb_data: list = []
    for uid_str in all_uids:
        udata = ud.get(uid_str, {})
        wdata = ws_.get(uid_str, {})
        alltime_sec = udata.get('alltime_seconds', wdata.get('seconds', 0))
        lb_data.append({
            'name':       udata.get('name') or wdata.get('name') or 'Unknown',
            'hours':      round(alltime_sec / 3600, 2),
            'seconds':    alltime_sec,
            'sessions':   udata.get('session_count', 0),
            'streak':     udata.get('streak_max', 0),
            'first_seen': udata.get('first_seen', ''),
            'last_seen':  udata.get('last_seen', ''),
        })
    lb_data.sort(key=lambda x: x['seconds'], reverse=True)
    lb_rows = [[i+1, d['name'], d['hours'], d['seconds'],
                 d['sessions'], d['streak'], d['first_seen'], d['last_seen']]
               for i, d in enumerate(lb_data)]
    if lb_rows:
        tab.resize(rows=len(lb_rows) + 1)
        tab.update('A2', lb_rows)
    _format_tab(ss, tab, _rgb(251, 188, 4), len(lb_rows))
    return lb_data, len(lb_rows)


def _sheets_sync_dau(ss, gid: str, sfx: str, du: dict, da: dict) -> int:
    """Write DAU tab. Returns row count."""
    if not du:
        return 0
    tab = _ensure_tab(ss, f'📈 DAU{sfx}', ['Date', 'DAU', 'Total Joins'])
    dates = sorted(du.keys())
    rows  = [[d, len(du.get(d, [])), da.get(d, 0)] for d in dates]
    tab.resize(rows=len(rows) + 1)
    tab.update('A2', rows)
    _format_tab(ss, tab, _rgb(52, 168, 83), len(rows))
    return len(rows)


def _sheets_sync_members(ss, gid: str, sfx: str, ud: dict) -> int:
    """Write Members tab. Returns row count."""
    tab = _ensure_tab(ss, f'👥 Members{sfx}',
        ['Member ID', 'Name', 'Total Hours', 'Sessions',
         'Streak Max', 'Active Days', 'First Seen', 'Last Seen', 'Note'])
    notes_g = _sheets_notes.get(gid, {})
    rows = []
    for uid_str, udata in ud.items():
        alltime_sec = udata.get('alltime_seconds', 0)
        rows.append([
            uid_str,
            udata.get('name', ''),
            round(alltime_sec / 3600, 2),
            udata.get('session_count', 0),
            udata.get('streak_max', 0),
            len(udata.get('dates', {})),
            udata.get('first_seen', ''),
            udata.get('last_seen', ''),
            notes_g.get(uid_str, ''),
        ])
    if rows:
        tab.resize(rows=len(rows) + 1)
        tab.update('A2', rows)
    _format_tab(ss, tab, _rgb(154, 109, 234), len(rows))
    return len(rows)


def _sheets_sync_summary(ss, gid: str, sfx: str, gname: str, ud: dict, lb_data: list,
                          session_history, du: dict, da: dict) -> None:
    """Write Summary tab."""
    tab = _ensure_tab(ss, f'⭐ Summary{sfx}', ['Metric', 'Value'])
    now_str    = datetime.now(THAI_TZ).strftime('%Y-%m-%d %H:%M')
    total_hours = round(sum(ud.get(u, {}).get('alltime_seconds', 0) for u in ud) / 3600, 1)
    guild_sess  = [s for s in session_history if s.get('guild_id') == gid]
    avg_sess_sec = (sum(s.get('seconds', 0) for s in guild_sess)
                    // max(len(guild_sess), 1))
    dau_today   = len(du.get(datetime.now(THAI_TZ).strftime('%Y-%m-%d'), []))
    rows = [
        ['Server', gname],
        ['Last Sync', now_str],
        [''],
        ['Total Members', len(set(ud.keys()))],
        ['Total Sessions', len(guild_sess)],
        ['Total Voice Hours', total_hours],
        ['Avg Session (min)', round(avg_sess_sec / 60, 1)],
        ['DAU Today', dau_today],
        [''],
        ['🥇 #1 All-time', lb_data[0]['name'] + f' ({lb_data[0]["hours"]}h)' if lb_data else '-'],
        ['🥈 #2 All-time', lb_data[1]['name'] + f' ({lb_data[1]["hours"]}h)' if len(lb_data) > 1 else '-'],
        ['🥉 #3 All-time', lb_data[2]['name'] + f' ({lb_data[2]["hours"]}h)' if len(lb_data) > 2 else '-'],
    ]
    tab.resize(rows=len(rows) + 1)
    tab.update('A2', rows)
    _format_tab(ss, tab, _rgb(234, 67, 53), len(rows))


def sync_to_sheets(target_guild_id=None):
    """Push bot data to Google Sheets (all tabs + formatting). Returns result dict."""
    global _sheets_last_sync, _sheets_last_err
    with _sheets_lock:
        gc, err = _get_gspread()
        if err:
            _sheets_last_err = err
            return {'ok': False, 'error': err}
        try:
            import gspread as _gspread_mod
            # Open existing sheet or create new one if not found / ID missing
            ss = None
            created_new = False
            if GOOGLE_SHEET_ID:
                try:
                    ss = gc.open_by_key(GOOGLE_SHEET_ID)
                except Exception:
                    ss = None
            if ss is None:
                ss = gc.create('AjarnBot Analytics')
                created_new = True
                log(f'sheets: created new spreadsheet id={ss.id}')

            # Auto-share with owner email (writer so they can see + Looker Studio)
            if SHEETS_OWNER_EMAIL:
                try:
                    ss.share(SHEETS_OWNER_EMAIL, perm_type='user', role='writer', notify=created_new)
                except Exception:
                    pass  # Already shared — ignore

            if target_guild_id:
                guild_ids = [str(target_guild_id)]
            else:
                guild_ids = sorted(set(
                    list(user_daily.keys()) +
                    list(weekly_stats.keys()) +
                    list(daily_unique.keys())
                ))

            total_rows = 0
            for gid in guild_ids:
                gname = _guild_display_name(gid)
                sfx = f' — {gname}' if len(guild_ids) > 1 else ''

                ud  = user_daily.get(gid, {})
                ws_ = weekly_stats.get(gid, {})
                du  = daily_unique.get(gid, {})
                da  = daily_activity.get(gid, {})

                total_rows += _sheets_sync_sessions(ss, gid, sfx, session_history)
                lb_data, lb_rows = _sheets_sync_leaderboard(ss, gid, sfx, ud, ws_)
                total_rows += lb_rows
                total_rows += _sheets_sync_dau(ss, gid, sfx, du, da)
                total_rows += _sheets_sync_members(ss, gid, sfx, ud)
                _sheets_sync_summary(ss, gid, sfx, gname, ud, lb_data, session_history, du, da)

            _sheets_last_sync = datetime.now(THAI_TZ).strftime('%Y-%m-%d %H:%M')
            _sheets_last_err  = None
            log(f'sheets: sync ok — {total_rows} rows across {len(guild_ids)} guild(s)')
            return {'ok': True, 'synced_at': _sheets_last_sync,
                    'rows': total_rows, 'guilds': len(guild_ids)}

        except Exception as e:
            _sheets_last_err = str(e)
            log(f'sheets: sync error: {e}')
            return {'ok': False, 'error': str(e)}

def import_from_sheets(target_guild_id=None):
    """Read Notes tab from Google Sheets → _sheets_notes dict."""
    global _sheets_notes
    with _sheets_lock:
        gc, err = _get_gspread()
        if err:
            return {'ok': False, 'error': err}
        try:
            import gspread
            ss = gc.open_by_key(GOOGLE_SHEET_ID)

            guild_ids = [str(target_guild_id)] if target_guild_id else sorted(set(
                list(user_daily.keys()) + list(weekly_stats.keys())
            ))
            imported = 0
            for gid in guild_ids:
                sfx   = f' — {_guild_display_name(gid)}' if len(guild_ids) > 1 else ''
                title = f'Members{sfx}'
                try:
                    ws = ss.worksheet(title)
                except Exception:
                    continue
                rows = ws.get_all_values()
                if len(rows) < 2:
                    continue
                header = rows[0]
                try:
                    id_col   = header.index('Member ID')
                    note_col = header.index('Note')
                except ValueError:
                    continue
                notes_g = {}
                for row in rows[1:]:
                    uid_str = row[id_col].strip() if id_col < len(row) else ''
                    note    = row[note_col].strip() if note_col < len(row) else ''
                    if uid_str and note:
                        notes_g[uid_str] = note
                        imported += 1
                _sheets_notes[gid] = notes_g
            return {'ok': True, 'imported_notes': imported}
        except Exception as e:
            log(f'sheets: import error: {e}')
            return {'ok': False, 'error': str(e)}

def _sheets_bg_sync():
    """Background thread: sync to sheets every 6 hours."""
    import time
    while True:
        time.sleep(6 * 3600)
        if GOOGLE_SHEET_ID and GOOGLE_SHEETS_CREDENTIALS:
            try:
                sync_to_sheets()
            except Exception as e:
                log(f'sheets: bg sync error: {e}')

_sheets_bg_thread = threading.Thread(target=_sheets_bg_sync, daemon=True)
_sheets_bg_thread.start()

# ── Sheets API endpoints ──────────────────────────────────────────────────────
@flask_app.route('/api/sheets/status')
@require_auth
def api_sheets_status():
    configured = bool(GOOGLE_SHEET_ID and GOOGLE_SHEETS_CREDENTIALS)
    sheet_url  = f'https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}' if GOOGLE_SHEET_ID else ''
    return jsonify({
        'configured':  configured,
        'sheet_id':    GOOGLE_SHEET_ID if configured else '',
        'sheet_url':   sheet_url,
        'last_sync':   _sheets_last_sync,
        'last_error':  _sheets_last_err,
    })

@flask_app.route('/api/sheets/info')
@require_auth
def api_sheets_info():
    """Return service account email + real spreadsheet ID (useful for sharing)."""
    sa_email = ''
    if GOOGLE_SHEETS_CREDENTIALS:
        try:
            import json as _json
            creds_dict = _json.loads(GOOGLE_SHEETS_CREDENTIALS)
            sa_email = creds_dict.get('client_email', '')
        except Exception:
            pass
    return jsonify({
        'service_account_email': sa_email,
        'sheet_id': GOOGLE_SHEET_ID,
        'sheets_owner_email': SHEETS_OWNER_EMAIL,
    })

@flask_app.route('/api/sheets/sync', methods=['POST'])
@require_auth
def api_sheets_sync():
    data     = request.get_json(silent=True) or {}
    guild_id = str(data.get('guild_id') or flask_session.get('current_guild_id') or '').strip()
    result   = sync_to_sheets(guild_id or None)
    return jsonify(result), (200 if result['ok'] else 500)

@flask_app.route('/api/sheets/import', methods=['POST'])
@require_auth
def api_sheets_import():
    data     = request.get_json(silent=True) or {}
    guild_id = str(data.get('guild_id') or flask_session.get('current_guild_id') or '').strip()
    result   = import_from_sheets(guild_id or None)
    return jsonify(result), (200 if result['ok'] else 500)


# ── Form Registrations (read-only from FORM_SHEET_ID) ────────────────────────
_form_cache: dict = {}          # {ts: float, rows: list}
_form_cache_ttl = 300           # 5 min cache

def _get_form_gspread():
    """Return gspread client using GOOGLE_CREDENTIALS env var."""
    creds_json = GOOGLE_CREDENTIALS or GOOGLE_SHEETS_CREDENTIALS
    if not creds_json:
        return None, 'GOOGLE_CREDENTIALS not set'
    try:
        import gspread
        from google.oauth2.service_account import Credentials as SACredentials
        creds_dict = json.loads(creds_json)
        scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly',
                  'https://www.googleapis.com/auth/drive.readonly']
        creds = SACredentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds), None
    except Exception as e:
        return None, str(e)


def _fetch_form_rows() -> tuple[list, str | None]:
    """Fetch rows from the form response sheet. Returns (rows, error)."""
    now = time.time()
    if _form_cache.get('ts', 0) + _form_cache_ttl > now:
        return _form_cache.get('rows', []), None
    gc, err = _get_form_gspread()
    if err:
        return [], err
    try:
        ss = gc.open_by_key(FORM_SHEET_ID)
        ws = ss.worksheet('การตอบแบบฟอร์ม 1')
        all_rows = ws.get_all_records()
        _form_cache['ts'] = now
        _form_cache['rows'] = all_rows
        return all_rows, None
    except Exception as e:
        return [], str(e)


@flask_app.route('/api/form-registrations')
@require_auth
def api_form_registrations():
    """Return form registration stats from the Google Form response sheet."""
    rows, err = _fetch_form_rows()
    if err and not rows:
        return jsonify({'ok': False, 'error': err}), 500

    # Column names from sheet: Timestamp, Email, ชื่อ (or similar), อาชีพ(หลัก), อาชีพ(รอง),
    # วันที่ลงทะเบียน, ช่วงเวลา Guild War
    total = len(rows)

    # Count by primary job (อาชีพหลัก)
    job_counts: dict[str, int] = {}
    gw_counts:  dict[str, int] = {}
    for r in rows:
        job = str(r.get('อาชีพ(หลัก)', r.get('อาชีพ (หลัก)', ''))).strip()
        if job:
            job_counts[job] = job_counts.get(job, 0) + 1
        gw = str(r.get('ช่วงเวลา Guild War', '')).strip()
        if gw:
            gw_counts[gw] = gw_counts.get(gw, 0) + 1

    top_jobs = sorted(job_counts.items(), key=lambda x: -x[1])[:8]
    top_gw   = sorted(gw_counts.items(),  key=lambda x: -x[1])[:6]

    # Recent 10 registrants (name + timestamp)
    recent = []
    for r in rows[-10:][::-1]:
        name = str(r.get('ชื่อ', r.get('Name', r.get('ชื่อ-สกุล', '')))).strip()
        ts   = str(r.get('Timestamp', '')).strip()
        if name:
            recent.append({'name': name, 'timestamp': ts})

    return jsonify({
        'ok':       True,
        'total':    total,
        'jobs':     [{'label': k, 'count': v} for k, v in top_jobs],
        'gw_slots': [{'label': k, 'count': v} for k, v in top_gw],
        'recent':   recent,
        'error':    err,
    })


# ── Notion Integration ───────────────────────────────────────────────────────
_NOTION_API   = 'https://api.notion.com/v1'
_NOTION_VER   = '2022-06-28'
_notion_lock      = threading.Lock()
_notion_last_sync: str | None = None
_notion_last_err:  str | None = None

# Required database property schema (name → type config sent to Notion)
_NOTION_SCHEMA = {
    'Discord ID':    {'rich_text': {}},
    'Server':        {'select': {}},
    'Weekly Minutes':{'number': {'format': 'number'}},
    'Total Hours':   {'number': {'format': 'number'}},
    'Streak (days)': {'number': {'format': 'number'}},
    'Sessions':      {'number': {'format': 'number'}},
    'Last Seen':     {'date': {}},
}

def _notion_req(method: str, path: str, body=None):
    """Notion REST helper. Returns (parsed_json | None, error_str | None)."""
    if not NOTION_TOKEN:
        return None, 'NOTION_TOKEN not set'
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f'{_NOTION_API}{path}', data=data, method=method,
        headers={
            'Authorization': f'Bearer {NOTION_TOKEN}',
            'Notion-Version': _NOTION_VER,
            'Content-Type': 'application/json',
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f'HTTP {e.code}: {e.read().decode()[:300]}'
    except Exception as e:
        return None, str(e)

def _notion_ensure_schema() -> tuple[bool, str]:
    """Patch the database to add any missing properties. Returns (ok, msg)."""
    if not NOTION_DATABASE_ID:
        return False, 'NOTION_DATABASE_ID not set'
    result, err = _notion_req('PATCH', f'/databases/{NOTION_DATABASE_ID}',
                              {'properties': _NOTION_SCHEMA})
    if err:
        return False, err
    return True, 'Schema OK'

def _notion_bulk_find_pages(uids: list[str]) -> dict[str, str]:
    """
    Bulk-query Notion database for all given Discord UIDs.
    Returns {uid: page_id} for existing rows — single HTTP request per 100-item batch.
    """
    uid_to_page: dict[str, str] = {}
    if not uids:
        return uid_to_page
    # Batch into chunks of 100 (Notion OR filter limit)
    for i in range(0, len(uids), 100):
        chunk = uids[i:i + 100]
        body = {
            'filter': {
                'or': [
                    {'property': 'Discord ID', 'rich_text': {'equals': uid}}
                    for uid in chunk
                ]
            },
            'page_size': 100,
        }
        result, _ = _notion_req('POST', f'/databases/{NOTION_DATABASE_ID}/query', body)
        if result and result.get('results'):
            for page in result['results']:
                props = page.get('properties', {})
                did_prop = props.get('Discord ID', {}).get('rich_text', [])
                if did_prop:
                    uid_to_page[did_prop[0]['text']['content']] = page['id']
    return uid_to_page

def _notion_find_page(uid: str) -> str | None:
    """Return page_id of existing row for this Discord uid, or None."""
    result, _ = _notion_req('POST', f'/databases/{NOTION_DATABASE_ID}/query', {
        'filter': {'property': 'Discord ID', 'rich_text': {'equals': uid}},
        'page_size': 1,
    })
    if result and result.get('results'):
        return result['results'][0]['id']
    return None

def _notion_props(name: str, uid: str, guild_name: str,
                  weekly_min: int, total_hours: float,
                  streak: int, sessions: int, last_seen: str) -> dict:
    props: dict = {
        'Name':          {'title': [{'text': {'content': name[:100]}}]},
        'Discord ID':    {'rich_text': [{'text': {'content': uid}}]},
        'Server':        {'select': {'name': (guild_name or 'Unknown')[:100]}},
        'Weekly Minutes':{'number': weekly_min},
        'Total Hours':   {'number': round(total_hours, 2)},
        'Streak (days)': {'number': streak},
        'Sessions':      {'number': sessions},
    }
    if last_seen:
        try:
            datetime.strptime(last_seen, '%Y-%m-%d')
            props['Last Seen'] = {'date': {'start': last_seen}}
        except ValueError:
            pass
    return props

def sync_to_notion(target_guild_id: str | None = None) -> dict:
    """Push voice stats to Notion database. Returns result dict."""
    global _notion_last_sync, _notion_last_err
    with _notion_lock:
        if not NOTION_TOKEN or not NOTION_DATABASE_ID:
            err = 'Notion not configured (NOTION_TOKEN / NOTION_DATABASE_ID missing)'
            _notion_last_err = err
            return {'ok': False, 'error': err}

        # Ensure schema exists
        ok, schema_msg = _notion_ensure_schema()
        if not ok:
            _notion_last_err = schema_msg
            return {'ok': False, 'error': schema_msg}

        created = updated = errors = 0

        with _lock_stats:
            stats_snap = {k: dict(v) for k, v in weekly_stats.items()}
        with _lock_user_daily:
            daily_snap = {k: dict(v) for k, v in user_daily.items()}

        guild_ids = [target_guild_id] if target_guild_id else list(
            set(stats_snap.keys()) | set(daily_snap.keys()))

        for gid in guild_ids:
            guild_obj  = client.get_guild(int(gid)) if gid else None
            guild_name = guild_obj.name if guild_obj else str(gid)
            guild_w    = stats_snap.get(str(gid), {})
            guild_d    = daily_snap.get(str(gid), {})
            all_uids   = set(guild_w.keys()) | set(guild_d.keys())

            # Bulk-fetch all existing Notion pages for this guild in one HTTP round-trip
            uid_to_page = _notion_bulk_find_pages(list(all_uids))

            for uid in all_uids:
                w = guild_w.get(uid, {})
                d = guild_d.get(uid, {})
                name        = (w.get('name') or d.get('name') or uid)[:100]
                weekly_min  = w.get('seconds', 0) // 60
                total_hrs   = d.get('alltime_seconds', 0) / 3600
                streak      = d.get('streak', 0)
                sessions    = d.get('session_count', 0)
                last_seen   = d.get('last_seen', '')

                props    = _notion_props(name, uid, guild_name, weekly_min,
                                         total_hrs, streak, sessions, last_seen)
                page_id  = uid_to_page.get(uid)
                if page_id:
                    _, err = _notion_req('PATCH', f'/pages/{page_id}', {'properties': props})
                else:
                    _, err = _notion_req('POST', '/pages', {
                        'parent': {'database_id': NOTION_DATABASE_ID},
                        'properties': props,
                    })
                if err:
                    errors += 1
                    _notion_last_err = err
                    log(f'notion: error for uid={uid}: {err}')
                elif page_id:
                    updated += 1
                else:
                    created += 1

        now_str = datetime.now(THAI_TZ).strftime('%Y-%m-%d %H:%M')
        _notion_last_sync = now_str
        if errors == 0:
            _notion_last_err = None
        rows = created + updated
        return {'ok': errors == 0, 'created': created, 'updated': updated,
                'errors': errors, 'rows': rows, 'synced_at': now_str}

@flask_app.route('/api/notion/status')
@require_auth
def api_notion_status():
    return jsonify({
        'configured':  bool(NOTION_TOKEN and NOTION_DATABASE_ID),
        'database_id': (NOTION_DATABASE_ID[:8] + '...') if NOTION_DATABASE_ID else '',
        'last_sync':   _notion_last_sync,
        'last_error':  _notion_last_err,
    })

@flask_app.route('/api/notion/sync', methods=['POST'])
@require_auth
def api_notion_sync():
    data     = request.get_json(silent=True) or {}
    guild_id = str(data.get('guild_id') or flask_session.get('current_guild_id') or '').strip()
    result   = sync_to_notion(guild_id or None)
    return jsonify(result), (200 if result['ok'] else 500)

@flask_app.route('/api/notion/setup', methods=['POST'])
@require_auth
def api_notion_setup():
    """Patch database schema to add required properties."""
    ok, msg = _notion_ensure_schema()
    return jsonify({'ok': ok, 'message': msg}), (200 if ok else 500)

# ─────────────────────────────────────────────────────────────────────────────

# ── Feature 6: Export CSV ────────────────────────────────────────────────────
@flask_app.route('/api/export/csv')
@require_auth
def api_export_csv():
    """
    ดาวน์โหลด session_history เป็น CSV
    ?guild_id=... (required)  ?period=today|week|month|all  (default: all)
    """
    import csv, io
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    period = request.args.get('period', 'all').strip().lower()
    now = datetime.now(THAI_TZ)
    def _in_period(join_str):
        if period == 'all':
            return True
        try:
            dt = datetime.strptime(join_str, '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
        except Exception:
            return True
        if period == 'today':
            return dt.date() == now.date()
        if period == 'week':
            return dt >= now - timedelta(days=now.weekday(), hours=now.hour,
                                         minutes=now.minute, seconds=now.second)
        if period == 'month':
            return dt.year == now.year and dt.month == now.month
        return True

    rows = [
        s for s in session_history
        if s.get('guild_id') == guild_id and _in_period(s.get('join', ''))
    ]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['date', 'user_name', 'user_id', 'channel', 'duration_sec', 'duration_fmt'])
    for s in rows:
        join_str = s.get('join', '')
        date_only = join_str.split(' ')[0] if join_str else ''
        sec = s.get('seconds', 0)
        writer.writerow([
            date_only,
            s.get('name', ''),
            s.get('uid', ''),   # fixed: was 'user_id', correct key is 'uid'
            s.get('channel', ''),
            sec,
            format_duration(sec),
        ])

    filename = f'voice_history_{guild_id}_{period}_{now.strftime("%Y%m%d")}.csv'
    return Response(
        buf.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )

# ── Feature 6: Per-channel stats ─────────────────────────────────────────────
@flask_app.route('/api/channel-stats')
@require_auth
def api_channel_stats():
    """
    คืน voice time รวมแยกตาม channel สำหรับ guild นั้น
    ?guild_id=... (required)
    Response: [{"channel": str, "seconds": int, "duration": str}, ...]
              เรียงจากมากไปน้อย
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    ch_data = channel_activity.get(guild_id, {})
    result = [
        {'channel': ch, 'seconds': sec, 'duration': format_duration(sec)}
        for ch, sec in sorted(ch_data.items(), key=lambda x: x[1], reverse=True)
    ]
    return jsonify(result)
# ─────────────────────────────────────────────────────────────────────────────

# ── DAU (Daily Active Users) ──────────────────────────────────────────────────
@flask_app.route('/api/dau')
@require_auth
def api_dau():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    try:
        days = max(1, min(int(request.args.get('days', 30)), 365))
    except ValueError:
        return jsonify({'error': 'invalid days'}), 400
    gid = str(guild_id)
    now  = datetime.now(THAI_TZ)
    # Build DAU from user_daily (has full history) + daily_unique (new data)
    # user_daily[gid][uid]['dates'][date_str] → count
    gdata = user_daily.get(gid, {})
    result = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        # Count unique users who have any activity on this date
        dau_ud  = sum(1 for udata in gdata.values() if d in udata.get('dates', {}))
        dau_du  = len(daily_unique.get(gid, {}).get(d, []))
        dau     = max(dau_ud, dau_du)
        joins   = daily_activity.get(gid, {}).get(d, 0)
        result.append({'date': d, 'dau': dau, 'joins': joins})
    return jsonify(result)

# ── Simple TTL cache for expensive endpoints ──────────────────────────────────
_ldb_cache: dict    = {}   # {(gid, period, sort): (result_list, expires_at)}
_ret_cache: dict    = {}   # {(gid, num_weeks): (result_list, expires_at)}
_status_sess_cache: dict = {}  # {gid: (total, avg_secs, median_secs, expires_at)}
_LDB_TTL        = 60           # seconds
_RET_TTL        = 300          # 5 minutes
_STATUS_SESS_TTL = 60          # seconds — session stats updated at most once/min

# ── Leaderboard with period ───────────────────────────────────────────────────
@flask_app.route('/api/leaderboard')
@require_auth
def api_leaderboard():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid    = str(guild_id)
    period = request.args.get('period', '7d')
    sort   = request.args.get('sort', 'time')   # time | sessions | streak | days
    now    = datetime.now(THAI_TZ)
    _cache_key = (gid, period, sort)
    _cached = _ldb_cache.get(_cache_key)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    if period == '7d':
        # fast path — use weekly_stats in-memory
        combined = {
            uid: {'name': v['name'], 'seconds': v['seconds']}
            for uid, v in weekly_stats.get(gid, {}).items()
        }
    else:
        days_map = {'30d': 30, '90d': 90}
        cutoff   = now - timedelta(days=days_map.get(period, 36500))
        combined = {}
        with _lock_history:
            hist_snap = list(session_history)
        for s in hist_snap:
            if s.get('guild_id') != gid:
                continue
            try:
                jt = datetime.strptime(s['join'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
                if jt < cutoff:
                    continue
            except Exception:
                continue
            uid = s.get('uid', '')
            if uid not in combined:
                combined[uid] = {'name': s.get('name', 'Unknown'), 'seconds': 0}
            combined[uid]['seconds'] += s.get('seconds', 0)
            combined[uid]['name']     = s.get('name', combined[uid]['name'])
    # add active sessions
    for (gid2, mid2), (dname, jt, _) in list(voice_join_times.items()):
        if str(gid2) != gid:
            continue
        uid     = str(mid2)
        elapsed = int((now - jt).total_seconds())
        if uid not in combined:
            combined[uid] = {'name': dname, 'seconds': 0}
        combined[uid]['seconds'] += elapsed
    # Enrich from user_daily for alternative sort keys
    gdata = user_daily.get(gid, {})
    for uid, v in combined.items():
        ud = gdata.get(uid, {})
        v['session_count'] = ud.get('session_count', 0)
        v['streak_max']    = ud.get('streak_max', 0)
        v['active_days']   = len(ud.get('dates', {}))
    # Sort by requested metric
    if sort == 'sessions':
        ranked = sorted(combined.items(), key=lambda x: x[1].get('session_count', 0), reverse=True)[:10]
    elif sort == 'streak':
        ranked = sorted(combined.items(), key=lambda x: x[1].get('streak_max', 0), reverse=True)[:10]
    elif sort == 'days':
        ranked = sorted(combined.items(), key=lambda x: x[1].get('active_days', 0), reverse=True)[:10]
    else:  # time
        ranked = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)[:10]

    def _value_label(v):
        if sort == 'sessions': return str(v.get('session_count', 0)) + ' sess'
        if sort == 'streak':   return str(v.get('streak_max', 0)) + ' วัน'
        if sort == 'days':     return str(v.get('active_days', 0)) + ' วัน'
        return format_duration(v['seconds'])

    _result = [
        {'uid': uid, 'name': v['name'], 'seconds': v['seconds'], 'duration': _value_label(v),
         'session_count': v.get('session_count', 0), 'streak_max': v.get('streak_max', 0),
         'active_days': v.get('active_days', 0)}
        for uid, v in ranked
    ]
    _ldb_cache[_cache_key] = (_result, time.monotonic() + _LDB_TTL)
    return jsonify(_result)

# ── Inactive users ────────────────────────────────────────────────────────────
@flask_app.route('/api/inactive')
@require_auth
def api_inactive():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        threshold_days = max(1, min(int(request.args.get('days', 14)), 365))
    except ValueError:
        return jsonify({'error': 'invalid days'}), 400
    now     = datetime.now(THAI_TZ)
    cutoff  = now - timedelta(days=threshold_days)
    result  = []
    for uid, udata in user_daily.get(gid, {}).items():
        last_seen_str = udata.get('last_seen')
        if not last_seen_str:
            continue
        try:
            ls = datetime.fromisoformat(last_seen_str)
            if ls.tzinfo is None:
                ls = ls.replace(tzinfo=THAI_TZ)
            if ls < cutoff:
                days_inactive = (now - ls).days
                result.append({
                    'uid':          uid,
                    'name':         udata.get('name', 'Unknown'),
                    'last_seen':    ls.strftime('%Y-%m-%d'),
                    'days_inactive': days_inactive,
                })
        except Exception:
            continue
    result.sort(key=lambda x: x['days_inactive'], reverse=True)
    return jsonify(result[:20])

# ── Retention (week-over-week) ────────────────────────────────────────────────
@flask_app.route('/api/retention')
@require_auth
def api_retention():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        num_weeks = max(2, min(int(request.args.get('weeks', 8)), 26))
    except ValueError:
        return jsonify({'error': 'invalid weeks'}), 400
    _ret_key = (gid, num_weeks)
    _ret_cached = _ret_cache.get(_ret_key)
    if _ret_cached and time.monotonic() < _ret_cached[1]:
        return jsonify(_ret_cached[0])
    now = datetime.now(THAI_TZ)
    # Build weekly uid sets from session_history
    with _lock_history:
        hist_snap = list(session_history)
    weeks = []
    for w in range(num_weeks - 1, -1, -1):
        week_end   = now - timedelta(weeks=w)
        week_start = week_end - timedelta(weeks=1)
        uids = set()
        for s in hist_snap:
            if s.get('guild_id') != gid:
                continue
            try:
                jt = datetime.strptime(s['join'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
                if week_start <= jt < week_end:
                    uids.add(s.get('uid', ''))
            except Exception:
                continue
        weeks.append({'week_start': week_start.strftime('%Y-%m-%d'), 'uids': uids})
    result = []
    for i, w in enumerate(weeks):
        prev_uids = weeks[i - 1]['uids'] if i > 0 else set()
        retained  = len(w['uids'] & prev_uids) if prev_uids else 0
        pct       = round(retained / len(prev_uids) * 100) if prev_uids else None
        result.append({
            'week_start':     w['week_start'],
            'active_count':   len(w['uids']),
            'retained_count': retained,
            'retention_pct':  pct,
        })
    _ret_cache[_ret_key] = (result, time.monotonic() + _RET_TTL)
    return jsonify(result)

# ── WAU (Weekly Active Users) ─────────────────────────────────────────────────
@flask_app.route('/api/wau-mau')
@require_auth
def api_wau_mau():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        weeks = max(1, min(int(request.args.get('weeks', 12)), 52))
    except ValueError:
        return jsonify({'error': 'invalid weeks'}), 400
    now   = datetime.now(THAI_TZ)
    today = now.date()
    # Monday of current week
    current_monday = today - timedelta(days=today.weekday())
    result = []
    for w in range(weeks - 1, -1, -1):
        week_start = current_monday - timedelta(weeks=w)
        week_uids  = set()
        for day_offset in range(7):
            d_str = (week_start + timedelta(days=day_offset)).strftime('%Y-%m-%d')
            uids  = daily_unique.get(gid, {}).get(d_str, [])
            week_uids.update(uids)
        result.append({
            'week_start': week_start.strftime('%Y-%m-%d'),
            'wau': len(week_uids),
        })
    return jsonify(result)

# ── Day-of-Week × Hour Heatmap (7×24) ────────────────────────────────────────
@flask_app.route('/api/dow-heatmap')
@require_auth
def api_dow_heatmap():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid    = str(guild_id)
    matrix = [[0] * 24 for _ in range(7)]
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    for s in hist:
        try:
            jt = datetime.strptime(s['join'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
            matrix[jt.weekday()][jt.hour] += 1
        except Exception:
            pass
    return jsonify({
        'matrix': matrix,
        'days': ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา'],
    })

# ── Session length histogram ──────────────────────────────────────────────────
@flask_app.route('/api/histogram')
@require_auth
def api_histogram():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid  = str(guild_id)
    keys = ['0-5m', '5-15m', '15-30m', '30-60m', '60m+']
    cnts = {k: 0 for k in keys}
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    for s in hist:
        mins = (s.get('seconds', 0) or 0) / 60
        if   mins <  5: cnts['0-5m']   += 1
        elif mins < 15: cnts['5-15m']  += 1
        elif mins < 30: cnts['15-30m'] += 1
        elif mins < 60: cnts['30-60m'] += 1
        else:           cnts['60m+']   += 1
    return jsonify([{'range': k, 'count': cnts[k]} for k in keys])
# ─────────────────────────────────────────────────────────────────────────────

# ── User Growth: new vs returning users per week ──────────────────────────────
_growth_cache: dict = {}   # {(gid, weeks): (result, expires_at)}
_GROWTH_TTL = 300

@flask_app.route('/api/user-growth')
@require_auth
def api_user_growth():
    """
    New vs returning users per calendar week.
    ?guild_id=X&days=7|14|30  (preferred, default 7)
    ?guild_id=X&weeks=N        (legacy, still supported)
    Response: [{week_start, new_users, returning_users, total}]
    new = first_seen falls in that week; returning = seen before but active this week.
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        # 'days' takes priority; convert to whole weeks (ceil)
        if 'days' in request.args:
            days_val = max(7, min(int(request.args.get('days', 7)), 90))
            num_weeks = max(1, (days_val + 6) // 7)
        else:
            num_weeks = max(2, min(int(request.args.get('weeks', 2)), 52))
    except ValueError:
        return jsonify({'error': 'invalid parameter'}), 400
    _key = (gid, num_weeks)
    _cached = _growth_cache.get(_key)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    now   = datetime.now(THAI_TZ)
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    gdata  = user_daily.get(gid, {})
    result = []
    for w in range(num_weeks - 1, -1, -1):
        wk_start = monday - timedelta(weeks=w)
        wk_end   = wk_start + timedelta(days=7)
        wk_start_s = wk_start.strftime('%Y-%m-%d')
        wk_end_s   = wk_end.strftime('%Y-%m-%d')
        new_users       = 0
        returning_users = 0
        for uid, udata in gdata.items():
            dates = udata.get('dates', {})
            # active this week?
            active_this_week = any(wk_start_s <= d < wk_end_s for d in dates)
            if not active_this_week:
                continue
            fs = udata.get('first_seen', '')
            if fs:
                try:
                    fs_date = datetime.fromisoformat(fs).date()
                    if wk_start <= fs_date < wk_end:
                        new_users += 1
                    else:
                        returning_users += 1
                except Exception:
                    returning_users += 1
            else:
                returning_users += 1
        result.append({
            'week_start':      wk_start_s,
            'new_users':       new_users,
            'returning_users': returning_users,
            'total':           new_users + returning_users,
        })
    _growth_cache[_key] = (result, time.monotonic() + _GROWTH_TTL)
    return jsonify(result)

# ── Channel Details: extended per-channel analytics ───────────────────────────
_chdet_cache: dict = {}   # {gid: (result, expires_at)}
_CHDET_TTL = 120

@flask_app.route('/api/channel-details')
@require_auth
def api_channel_details():
    """
    Extended per-channel stats: unique_users, sessions, avg_session_min,
    peak_hour (0-23), top_user name, total_seconds.
    ?guild_id=X
    Response: [{channel, seconds, duration, sessions, unique_users, avg_min,
                peak_hour, top_user}]  sorted by seconds desc, top 15.
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    _cached = _chdet_cache.get(gid)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    # aggregate from session_history
    ch_data: dict = {}   # {channel: {seconds, sessions, users, hours}}
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    for s in hist:
        ch = s.get('channel') or 'Unknown'
        if ch not in ch_data:
            ch_data[ch] = {'seconds': 0, 'sessions': 0, 'users': {}, 'hours': [0]*24}
        secs = s.get('seconds', 0) or 0
        ch_data[ch]['seconds']   += secs
        ch_data[ch]['sessions']  += 1
        uid  = s.get('uid', '')
        name = s.get('name', 'Unknown')
        ch_data[ch]['users'][uid] = ch_data[ch]['users'].get(uid, {'name': name, 'seconds': 0})
        ch_data[ch]['users'][uid]['seconds'] += secs
        ch_data[ch]['users'][uid]['name']     = name
        try:
            jt = datetime.strptime(s['join'], '%Y-%m-%d %H:%M')
            ch_data[ch]['hours'][jt.hour] += 1
        except Exception:
            pass
    # Merge live channel_activity for channels not in history
    for ch, secs in channel_activity.get(gid, {}).items():
        if ch not in ch_data:
            ch_data[ch] = {'seconds': secs, 'sessions': 0, 'users': {}, 'hours': [0]*24}
        else:
            ch_data[ch]['seconds'] = max(ch_data[ch]['seconds'], secs)
    result = []
    for ch, v in sorted(ch_data.items(), key=lambda x: x[1]['seconds'], reverse=True)[:15]:
        sessions  = max(v['sessions'], 1)
        avg_min   = round(v['seconds'] / 60 / sessions, 1)
        peak_hour = v['hours'].index(max(v['hours'])) if any(v['hours']) else 0
        top_uid   = max(v['users'], key=lambda u: v['users'][u]['seconds'], default=None)
        top_name  = v['users'][top_uid]['name'] if top_uid else '-'
        result.append({
            'channel':      ch,
            'seconds':      v['seconds'],
            'duration':     format_duration(v['seconds']),
            'sessions':     v['sessions'],
            'unique_users': len(v['users']),
            'avg_min':      avg_min,
            'peak_hour':    peak_hour,
            'top_user':     top_name,
        })
    _chdet_cache[gid] = (result, time.monotonic() + _CHDET_TTL)
    return jsonify(result)

# ── Co-presence: top user pairs who were online together ─────────────────────
_cop_cache: dict = {}   # {gid: (result, expires_at)}
_COP_TTL = 600   # 10 min (expensive)

@flask_app.route('/api/copresence')
@require_auth
def api_copresence():
    """
    Find top user pairs who overlapped in voice (same guild, overlapping time windows).
    ?guild_id=X&top=10  (default top 10 pairs, max 30)
    Response: [{uid_a, name_a, uid_b, name_b, overlap_count}]
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        top_n = max(5, min(int(request.args.get('top', 10)), 30))
    except ValueError:
        return jsonify({'error': 'invalid top'}), 400
    _cached = _cop_cache.get(gid)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0][:top_n])
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    # Parse times once
    parsed = []
    for s in hist:
        try:
            jt = datetime.strptime(s['join'],  '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
            lt = datetime.strptime(s['leave'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
            if lt <= jt:
                continue
            parsed.append({'uid': s.get('uid', ''), 'name': s.get('name', 'Unknown'),
                           'jt': jt, 'lt': lt})
        except Exception:
            continue
    # Count pairwise overlaps — O(n²) but capped at 5000 sessions
    parsed = parsed[-5000:]
    pair_counts: dict = {}
    names: dict = {}
    for i in range(len(parsed)):
        a = parsed[i]
        names[a['uid']] = a['name']
        for j in range(i + 1, len(parsed)):
            b = parsed[j]
            if a['uid'] == b['uid']:
                continue
            # overlap check
            if a['jt'] < b['lt'] and b['jt'] < a['lt']:
                key = tuple(sorted([a['uid'], b['uid']]))
                pair_counts[key] = pair_counts.get(key, 0) + 1
    ranked = sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)[:30]
    result = [
        {
            'uid_a': k[0], 'name_a': names.get(k[0], 'Unknown'),
            'uid_b': k[1], 'name_b': names.get(k[1], 'Unknown'),
            'overlap_count': v,
        }
        for k, v in ranked
    ]
    _cop_cache[gid] = (result, time.monotonic() + _COP_TTL)
    return jsonify(result[:top_n])

# ── Milestone log: all awarded milestones sorted by recency ───────────────────
@flask_app.route('/api/milestone-log')
@require_auth
def api_milestone_log():
    """
    List all milestone awards for a guild.
    ?guild_id=X
    Response: [{uid, name, hours, awarded_at?}]
    sorted by hours desc then name.
    Note: milestones_awarded doesn't store timestamps; we return synthetic entries.
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid   = str(guild_id)
    gdata = user_daily.get(gid, {})
    awarded = milestones_awarded.get(gid, {})
    result  = []
    for uid, hours_list in awarded.items():
        name = gdata.get(uid, {}).get('name', 'Unknown')
        for h in sorted(hours_list):
            result.append({'uid': uid, 'name': name, 'hours': h})
    result.sort(key=lambda x: (-x['hours'], x['name']))
    return jsonify(result[:100])

# ── Live voice: who's in voice right now with elapsed time ───────────────────
@flask_app.route('/api/voice-now')
@require_auth
def api_voice_now():
    """
    Live snapshot of voice channel occupancy for a guild.
    ?guild_id=X
    Response: [{uid, name, channel, elapsed_sec, duration, avatar}]
              grouped by channel.
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    now = datetime.now(THAI_TZ)
    result = []
    for (gid2, mid), (name, join_time, ch) in list(voice_join_times.items()):
        if str(gid2) != gid:
            continue
        elapsed = int((now - join_time).total_seconds())
        guild_obj  = client.get_guild(gid2)
        member_obj = guild_obj.get_member(mid) if guild_obj else None
        avatar_url = str(member_obj.display_avatar.url) if member_obj and member_obj.display_avatar else None
        ud = user_daily.get(gid, {}).get(str(mid), {})
        result.append({
            'uid':         str(mid),
            'name':        name,
            'channel':     ch,
            'elapsed_sec': elapsed,
            'duration':    format_duration(elapsed),
            'avatar':      avatar_url,
            'alltime_fmt': format_duration(ud.get('alltime_seconds', 0)),
            'streak':      ud.get('streak_max', 0),
        })
    result.sort(key=lambda x: (x['channel'], -x['elapsed_sec']))
    return jsonify(result)

# ─────────────────────────────────────────────────────────────────────────────

# ── DAU Forecast: 7-day ahead using exponential moving average ────────────────
_forecast_cache: dict = {}   # {gid: (result, expires_at)}
_FORECAST_TTL = 600   # 10 min

@flask_app.route('/api/forecast')
@require_auth
def api_forecast():
    """
    Compute historical DAU (30 days) + 7-day forecast via EMA (alpha=0.3).
    ?guild_id=X
    Response: {
      history: [{date, dau}],          # last 30 days actual
      forecast: [{date, dau, is_forecast: true}]  # next 7 days predicted
    }
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    _cached = _forecast_cache.get(gid)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    now   = datetime.now(THAI_TZ)
    gdata = user_daily.get(gid, {})
    # Build 30-day actual DAU
    history = []
    for i in range(30 - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        dau_ud = sum(1 for udata in gdata.values() if d in udata.get('dates', {}))
        dau_du = len(daily_unique.get(gid, {}).get(d, []))
        dau    = max(dau_ud, dau_du)
        history.append({'date': d, 'dau': dau, 'is_forecast': False})
    # EMA forecast (alpha=0.3)
    alpha = 0.3
    ema   = history[-1]['dau'] if history else 0
    for h in history[-7:]:   # warm up on last 7 actual values
        ema = alpha * h['dau'] + (1 - alpha) * ema
    forecast = []
    for i in range(1, 8):
        fd  = (now + timedelta(days=i)).strftime('%Y-%m-%d')
        ema = max(0, round(ema))   # can't be negative
        forecast.append({'date': fd, 'dau': int(ema), 'is_forecast': True})
        ema = alpha * ema + (1 - alpha) * ema  # project forward (self-referential)
    result = {'history': history, 'forecast': forecast}
    _forecast_cache[gid] = (result, time.monotonic() + _FORECAST_TTL)
    return jsonify(result)

# ── Cohort retention matrix ───────────────────────────────────────────────────
_cohort_cache: dict = {}   # {(gid, cohort_weeks, retain_weeks): (result, expires_at)}
_COHORT_TTL = 600

@flask_app.route('/api/cohort')
@require_auth
def api_cohort():
    """
    Cohort retention matrix.
    ?guild_id=X&cohort_weeks=8&retain_weeks=6
    For each cohort week: what % of users came back in subsequent weeks.
    Response: {
      cohorts: [{cohort_week, users, weeks: [{offset, retained, pct}]}]
    }
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        cohort_weeks = max(2, min(int(request.args.get('cohort_weeks', 8)), 16))
        retain_weeks = max(2, min(int(request.args.get('retain_weeks', 6)), 8))
    except ValueError:
        return jsonify({'error': 'invalid params'}), 400
    _key = (gid, cohort_weeks, retain_weeks)
    _cached = _cohort_cache.get(_key)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    now    = datetime.now(THAI_TZ)
    today  = now.date()
    monday = today - timedelta(days=today.weekday())
    gdata  = user_daily.get(gid, {})
    # Build week-uid map from user_daily
    def week_of(date_str: str) -> str:
        try:
            d  = datetime.strptime(date_str, '%Y-%m-%d').date()
            wk = d - timedelta(days=d.weekday())
            return wk.strftime('%Y-%m-%d')
        except Exception:
            return ''
    cohorts = []
    for c in range(cohort_weeks - 1, -1, -1):
        cohort_monday = monday - timedelta(weeks=c)
        cohort_week_s = cohort_monday.strftime('%Y-%m-%d')
        cohort_monday_end = cohort_monday + timedelta(days=7)
        # users whose first_seen falls in this cohort week
        cohort_uids = set()
        for uid, udata in gdata.items():
            fs = udata.get('first_seen', '')
            if not fs:
                continue
            try:
                fs_d = datetime.fromisoformat(fs).date()
                if cohort_monday <= fs_d < cohort_monday_end:
                    cohort_uids.add(uid)
            except Exception:
                continue
        if not cohort_uids:
            continue
        # For each subsequent week, what % of cohort was active?
        weeks_data = []
        for offset in range(retain_weeks):
            tgt_monday = cohort_monday + timedelta(weeks=offset)
            tgt_end    = tgt_monday + timedelta(days=7)
            if tgt_monday > today:
                break
            tgt_s = tgt_monday.strftime('%Y-%m-%d')
            tgt_e = tgt_end.strftime('%Y-%m-%d')
            retained = sum(
                1 for uid in cohort_uids
                if any(tgt_s <= d < tgt_e for d in gdata.get(uid, {}).get('dates', {}))
            )
            pct = round(retained / len(cohort_uids) * 100) if cohort_uids else 0
            weeks_data.append({'offset': offset, 'retained': retained, 'pct': pct})
        cohorts.append({
            'cohort_week': cohort_week_s,
            'users':       len(cohort_uids),
            'weeks':       weeks_data,
        })
    result = {'cohorts': cohorts, 'retain_weeks': retain_weeks}
    _cohort_cache[_key] = (result, time.monotonic() + _COHORT_TTL)
    return jsonify(result)

# ── Time-of-day: avg sessions per hour (24h profile) ─────────────────────────
_tod_cache: dict = {}   # {gid: (result, expires_at)}
_TOD_TTL = 300

@flask_app.route('/api/time-of-day')
@require_auth
def api_time_of_day():
    """
    Average number of sessions starting per hour of day (0–23) across all history.
    ?guild_id=X
    Response: [{hour, avg_sessions, total_sessions}]  (24 entries)
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    _cached = _tod_cache.get(gid)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    counts  = [0] * 24   # raw session count per hour
    days_seen = set()
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    for s in hist:
        try:
            jt = datetime.strptime(s['join'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
            counts[jt.hour] += 1
            days_seen.add(jt.strftime('%Y-%m-%d'))
        except Exception:
            pass
    total_days = max(len(days_seen), 1)
    result = [
        {
            'hour':           h,
            'avg_sessions':   round(counts[h] / total_days, 2),
            'total_sessions': counts[h],
        }
        for h in range(24)
    ]
    _tod_cache[gid] = (result, time.monotonic() + _TOD_TTL)
    return jsonify(result)

# ── Churn risk: users with declining activity trend ───────────────────────────
_churn_cache: dict = {}   # {gid: (result, expires_at)}
_CHURN_TTL = 600

@flask_app.route('/api/churn-risk')
@require_auth
def api_churn_risk():
    """
    Score each user's churn risk based on activity ratio (recent 30d vs prior 30d).
    ?guild_id=X&limit=20
    risk_score: 0.0–1.0  (1.0 = highest risk)
    risk_level: 'low'|'medium'|'high'
    Response: [{uid, name, last_seen, sessions_recent, sessions_prior,
                risk_score, risk_level, days_since_last}]
    Only includes users who were active in prior 60d but declining.
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        limit = max(5, min(int(request.args.get('limit', 20)), 50))
    except ValueError:
        return jsonify({'error': 'invalid limit'}), 400
    _cached = _churn_cache.get(gid)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0][:limit])
    now     = datetime.now(THAI_TZ)
    today_s = now.strftime('%Y-%m-%d')
    d30_s   = (now - timedelta(days=30)).strftime('%Y-%m-%d')
    d60_s   = (now - timedelta(days=60)).strftime('%Y-%m-%d')
    result  = []
    for uid, udata in user_daily.get(gid, {}).items():
        dates = udata.get('dates', {})
        if not dates:
            continue
        # sessions in recent 30d vs prior 30d
        recent = sum(c for d, c in dates.items() if d30_s <= d <= today_s)
        prior  = sum(c for d, c in dates.items() if d60_s <= d <  d30_s)
        if prior == 0:   # no prior activity → skip (new or always absent)
            continue
        # risk = how much they dropped (0 = same, 1 = gone completely)
        risk_score = round(1 - min(recent / prior, 1), 3)
        if risk_score < 0.3:   # not concerning
            continue
        risk_level = 'high' if risk_score >= 0.7 else 'medium' if risk_score >= 0.5 else 'low'
        last_seen_str = udata.get('last_seen', '')
        try:
            ls      = datetime.fromisoformat(last_seen_str)
            days_off= (now - ls).days if ls.tzinfo else (now - ls.replace(tzinfo=THAI_TZ)).days
        except Exception:
            days_off = 0
        result.append({
            'uid':             uid,
            'name':            udata.get('name', 'Unknown'),
            'last_seen':       last_seen_str[:10],
            'sessions_recent': recent,
            'sessions_prior':  prior,
            'risk_score':      risk_score,
            'risk_level':      risk_level,
            'days_since_last': days_off,
        })
    result.sort(key=lambda x: (-x['risk_score'], -x['days_since_last']))
    _churn_cache[gid] = (result, time.monotonic() + _CHURN_TTL)
    return jsonify(result[:limit])

# ── All-time records ──────────────────────────────────────────────────────────
_records_cache: dict = {}   # {gid: (result, expires_at)}
_RECORDS_TTL = 300

@flask_app.route('/api/records')
@require_auth
def api_records():
    """
    All-time records for a guild.
    ?guild_id=X
    Response: {
      longest_session: {name, seconds, duration, date, channel},
      peak_dau_day:    {date, dau},
      first_session:   {name, date, channel},
      most_active_day: {date, sessions},
      top_user_alltime:{name, seconds, duration},
      peak_concurrent: {count, date},
    }
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    _cached = _records_cache.get(gid)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    # Longest session
    longest = max(hist, key=lambda s: s.get('seconds', 0), default=None)
    longest_rec = None
    if longest:
        longest_rec = {
            'name':     longest.get('name', 'Unknown'),
            'seconds':  longest.get('seconds', 0),
            'duration': format_duration(longest.get('seconds', 0)),
            'date':     longest.get('join', '')[:10],
            'channel':  longest.get('channel', ''),
        }
    # First session ever
    first = min(hist, key=lambda s: s.get('join', '9999'), default=None)
    first_rec = None
    if first:
        first_rec = {
            'name':    first.get('name', 'Unknown'),
            'date':    first.get('join', '')[:10],
            'channel': first.get('channel', ''),
        }
    # Most active day (most sessions in one day)
    day_counts: dict = {}
    for s in hist:
        d = s.get('join', '')[:10]
        if d:
            day_counts[d] = day_counts.get(d, 0) + 1
    most_active = max(day_counts.items(), key=lambda x: x[1], default=(None, 0))
    most_active_rec = {'date': most_active[0], 'sessions': most_active[1]} if most_active[0] else None
    # Peak DAU day (from daily_unique)
    gdu    = daily_unique.get(gid, {})
    peak_day = max(gdu.items(), key=lambda x: len(x[1]), default=(None, []))
    peak_dau_rec = {'date': peak_day[0], 'dau': len(peak_day[1])} if peak_day[0] else None
    # Top user alltime (from user_daily)
    gdata = user_daily.get(gid, {})
    top_uid = max(gdata.items(), key=lambda x: x[1].get('alltime_seconds', 0), default=(None, {}))
    top_user_rec = None
    if top_uid[0]:
        secs = top_uid[1].get('alltime_seconds', 0)
        top_user_rec = {
            'name':     top_uid[1].get('name', 'Unknown'),
            'seconds':  secs,
            'duration': format_duration(secs),
        }
    # Peak concurrent (estimate from session_history — find the time slice with most overlaps)
    # Simplified: pick the hour with the most join events as proxy
    hour_counts: dict = {}
    for s in hist:
        try:
            jt = datetime.strptime(s['join'], '%Y-%m-%d %H:%M')
            key = jt.strftime('%Y-%m-%d %H')
            hour_counts[key] = hour_counts.get(key, 0) + 1
        except Exception:
            pass
    peak_hour_key = max(hour_counts.items(), key=lambda x: x[1], default=(None, 0))
    peak_conc_rec = {'count': peak_hour_key[1], 'date': peak_hour_key[0]} if peak_hour_key[0] else None
    result = {
        'longest_session':  longest_rec,
        'first_session':    first_rec,
        'most_active_day':  most_active_rec,
        'peak_dau_day':     peak_dau_rec,
        'top_user_alltime': top_user_rec,
        'peak_concurrent':  peak_conc_rec,
    }
    _records_cache[gid] = (result, time.monotonic() + _RECORDS_TTL)
    return jsonify(result)

# ── Guild health score ────────────────────────────────────────────────────────
_health_cache: dict = {}   # {gid: (result, expires_at)}
_HEALTH_TTL = 300

@flask_app.route('/api/guild-health')
@require_auth
def api_guild_health():
    """
    Guild health score 0-100 combining DAU trend, retention, churn, and growth.
    ?guild_id=X
    Response: {health_score, dau_trend, retention_score, churn_score, growth_score, label}
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    _cached = _health_cache.get(gid)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    now   = datetime.now(THAI_TZ)
    today = now.date()
    # DAU trend: last14d → last7 avg vs prev7 avg
    gdu   = daily_unique.get(gid, {})
    def _dau(offset_days):
        d = (today - timedelta(days=offset_days)).strftime('%Y-%m-%d')
        return len(gdu.get(d, []))
    last7  = sum(_dau(i) for i in range(0, 7))  / 7
    prev7  = sum(_dau(i) for i in range(7, 14)) / 7
    dau_trend = (last7 - prev7) / max(prev7, 1)
    dau_trend = max(-1.0, min(1.0, dau_trend))
    # Retention: users active last week who were also active the prior week
    this_week_start = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
    prev_week_start = (today - timedelta(days=today.weekday() + 7)).strftime('%Y-%m-%d')
    prev_week_end   = this_week_start
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    uids_this  = {s['uid'] for s in hist if s.get('join', '') >= this_week_start}
    uids_prev  = {s['uid'] for s in hist if prev_week_start <= s.get('join', '') < prev_week_end}
    retention_score = len(uids_this & uids_prev) / max(len(uids_prev), 1)
    retention_score = min(1.0, retention_score)
    # Churn score: fraction of users with high drop-off (recent 30d vs prior 30d)
    d30_s = (now - timedelta(days=30)).strftime('%Y-%m-%d')
    d60_s = (now - timedelta(days=60)).strftime('%Y-%m-%d')
    today_s = today.strftime('%Y-%m-%d')
    high_risk = 0
    total_eligible = 0
    for uid, udata in user_daily.get(gid, {}).items():
        dates = udata.get('dates', {})
        prior  = sum(c for d, c in dates.items() if d60_s <= d < d30_s)
        if prior == 0:
            continue
        recent = sum(c for d, c in dates.items() if d30_s <= d <= today_s)
        risk   = 1 - min(recent / prior, 1)
        total_eligible += 1
        if risk >= 0.7:
            high_risk += 1
    churn_score = high_risk / max(total_eligible, 1)
    # Growth: new users this week / total users ever
    gdata = user_daily.get(gid, {})
    new_this_week = sum(
        1 for udata in gdata.values()
        if udata.get('first_seen', '') >= this_week_start
    )
    growth_score = min(new_this_week / max(len(gdata), 1), 1.0)
    # Composite health score
    dau_norm = (dau_trend + 1) / 2
    health_score = round((0.35 * dau_norm + 0.35 * retention_score +
                          0.20 * (1 - churn_score) + 0.10 * growth_score) * 100)
    health_score = max(0, min(100, health_score))
    if   health_score >= 80: label = 'Excellent'
    elif health_score >= 60: label = 'Good'
    elif health_score >= 40: label = 'Fair'
    else:                    label = 'At Risk'
    result = {
        'health_score':     health_score,
        'dau_trend':        round(dau_trend, 3),
        'retention_score':  round(retention_score, 3),
        'churn_score':      round(churn_score, 3),
        'growth_score':     round(growth_score, 3),
        'label':            label,
    }
    _health_cache[gid] = (result, time.monotonic() + _HEALTH_TTL)
    return jsonify(result)

# ── User compare ──────────────────────────────────────────────────────────────
@flask_app.route('/api/user-compare')
@require_auth
def api_user_compare():
    """
    Side-by-side stats for two users.
    ?guild_id=X&uid_a=A&uid_b=B
    Response: {uid_a: {...stats}, uid_b: {...stats}}
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid   = str(guild_id)
    uid_a = request.args.get('uid_a', '').strip()
    uid_b = request.args.get('uid_b', '').strip()
    if not uid_a or not uid_b:
        return jsonify({'error': 'uid_a and uid_b required'}), 400
    if not _validate_snowflake(uid_a) or not _validate_snowflake(uid_b):
        return jsonify({'error': 'invalid uid format'}), 400
    now    = datetime.now(THAI_TZ)
    d7_s   = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    def _build_stats(uid):
        gdata = user_daily.get(gid, {})
        udata = gdata.get(uid, {})
        name  = udata.get('name', 'Unknown')
        secs  = udata.get('alltime_seconds', 0)
        sessions = udata.get('session_count', 0)
        streak   = udata.get('streak_max', 0)
        active_d = len(udata.get('dates', {}))
        first    = udata.get('first_seen', '')[:10]
        last     = udata.get('last_seen', '')[:10]
        # favorite channel
        ch_cnt: dict = {}
        last7  = 0
        for s in hist:
            if str(s.get('uid', '')) != uid:
                continue
            ch = s.get('channel', '')
            ch_cnt[ch] = ch_cnt.get(ch, 0) + 1
            if s.get('join', '') >= d7_s:
                last7 += 1
        fav_ch = max(ch_cnt, key=ch_cnt.get, default='—')
        return {
            'uid':              uid,
            'name':             name,
            'alltime_seconds':  secs,
            'duration':         format_duration(secs),
            'session_count':    sessions,
            'streak_max':       streak,
            'active_days':      active_d,
            'first_seen':       first,
            'last_seen':        last,
            'favorite_channel': fav_ch,
            'last_7d_sessions': last7,
        }
    return jsonify({'uid_a': _build_stats(uid_a), 'uid_b': _build_stats(uid_b)})

# ── Current streak leaderboard ────────────────────────────────────────────────
_strk_cache: dict = {}   # {(gid, limit): (result, expires_at)}
_STRK_TTL = 300

@flask_app.route('/api/streak-board')
@require_auth
def api_streak_board():
    """
    Leaderboard ranked by CURRENT active streak (consecutive days ending today or yesterday).
    ?guild_id=X&limit=10
    Response: [{uid, name, current_streak, last_seen, alltime_seconds, duration}]
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        limit = max(3, min(int(request.args.get('limit', 10)), 50))
    except ValueError:
        return jsonify({'error': 'invalid limit'}), 400
    _key = (gid, limit)
    _cached = _strk_cache.get(_key)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    today = datetime.now(THAI_TZ).date()
    result = []
    for uid, udata in user_daily.get(gid, {}).items():
        dates_sorted = sorted(udata.get('dates', {}).keys(), reverse=True)
        if not dates_sorted:
            continue
        streak = 0
        try:
            last_date = datetime.strptime(dates_sorted[0], '%Y-%m-%d').date()
        except Exception:
            continue
        # Only count if last active is today or yesterday
        if (today - last_date).days > 1:
            result.append({'uid': uid, 'name': udata.get('name', '?'), 'current_streak': 0,
                           'last_seen': dates_sorted[0],
                           'alltime_seconds': udata.get('alltime_seconds', 0),
                           'duration': format_duration(udata.get('alltime_seconds', 0))})
            continue
        streak = 1
        for i in range(1, len(dates_sorted)):
            try:
                d = datetime.strptime(dates_sorted[i], '%Y-%m-%d').date()
            except Exception:
                break
            expected = last_date - timedelta(days=1)
            if d == expected:
                streak += 1
                last_date = d
            else:
                break
        result.append({
            'uid':             uid,
            'name':            udata.get('name', '?'),
            'current_streak':  streak,
            'last_seen':       dates_sorted[0],
            'alltime_seconds': udata.get('alltime_seconds', 0),
            'duration':        format_duration(udata.get('alltime_seconds', 0)),
        })
    result.sort(key=lambda x: (-x['current_streak'], -x['alltime_seconds']))
    _strk_cache[_key] = (result[:limit], time.monotonic() + _STRK_TTL)
    return jsonify(result[:limit])

# ── Session-day timeline ──────────────────────────────────────────────────────
@flask_app.route('/api/session-day')
@require_auth
def api_session_day():
    """
    All voice sessions for a specific date.
    ?guild_id=X&date=YYYY-MM-DD
    Response: [{uid, name, channel, join, leave, seconds, duration}]
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid  = str(guild_id)
    date = request.args.get('date', '').strip()
    if not date:
        return jsonify({'error': 'date required'}), 400
    try:
        datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'invalid date format, use YYYY-MM-DD'}), 400
    with _lock_history:
        hist = [s for s in session_history
                if str(s.get('guild_id', '')) == gid and s.get('join', '').startswith(date)]
    hist.sort(key=lambda s: s.get('join', ''))
    return jsonify([{
        'uid':      s.get('uid', ''),
        'name':     s.get('name', 'Unknown'),
        'channel':  s.get('channel', ''),
        'join':     s.get('join', ''),
        'leave':    s.get('leave', ''),
        'seconds':  s.get('seconds', 0),
        'duration': format_duration(s.get('seconds', 0)),
    } for s in hist])

# ── Marathon sessions (≥3h) ───────────────────────────────────────────────────
_marathon_cache: dict = {}   # {(gid, limit): (result, expires_at)}
_MARATHON_TTL = 300

@flask_app.route('/api/marathon')
@require_auth
def api_marathon():
    """
    Sessions lasting 3+ hours, sorted longest first.
    ?guild_id=X&limit=20
    Response: [{uid, name, channel, date, join, leave, seconds, duration}]
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        limit = max(5, min(int(request.args.get('limit', 20)), 100))
    except ValueError:
        return jsonify({'error': 'invalid limit'}), 400
    _key = (gid, limit)
    _cached = _marathon_cache.get(_key)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    with _lock_history:
        hist = [s for s in session_history
                if str(s.get('guild_id', '')) == gid and s.get('seconds', 0) >= 10800]
    hist.sort(key=lambda s: s.get('seconds', 0), reverse=True)
    result = [{
        'uid':      s.get('uid', ''),
        'name':     s.get('name', 'Unknown'),
        'channel':  s.get('channel', ''),
        'date':     s.get('join', '')[:10],
        'join':     s.get('join', ''),
        'leave':    s.get('leave', ''),
        'seconds':  s.get('seconds', 0),
        'duration': format_duration(s.get('seconds', 0)),
    } for s in hist[:limit]]
    _marathon_cache[_key] = (result, time.monotonic() + _MARATHON_TTL)
    return jsonify(result)

# ── Engagement score ──────────────────────────────────────────────────────────
_engage_cache: dict = {}   # {(gid, limit): (result, expires_at)}
_ENGAGE_TTL = 300

@flask_app.route('/api/engagement-score')
@require_auth
def api_engagement_score():
    """
    Per-user engagement score (0-100) combining hours, sessions, streak, active days.
    ?guild_id=X&limit=20
    Response: [{uid, name, score, alltime_seconds, duration, session_count, streak_max, active_days}]
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        limit = max(5, min(int(request.args.get('limit', 20)), 100))
    except ValueError:
        return jsonify({'error': 'invalid limit'}), 400
    _key = (gid, limit)
    _cached = _engage_cache.get(_key)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    result = []
    for uid, udata in user_daily.get(gid, {}).items():
        secs     = udata.get('alltime_seconds', 0)
        sessions = udata.get('session_count', 0)
        streak   = udata.get('streak_max', 0)
        days     = len(udata.get('dates', {}))
        hours_n  = min(secs / 3600 / 100, 1.0)
        sess_n   = min(sessions / 200, 1.0)
        strk_n   = min(streak / 30, 1.0)
        days_n   = min(days / 90, 1.0)
        score    = round((0.35 * hours_n + 0.30 * sess_n + 0.20 * strk_n + 0.15 * days_n) * 100, 1)
        result.append({
            'uid':             uid,
            'name':            udata.get('name', '?'),
            'score':           score,
            'alltime_seconds': secs,
            'duration':        format_duration(secs),
            'session_count':   sessions,
            'streak_max':      streak,
            'active_days':     days,
        })
    result.sort(key=lambda x: -x['score'])
    _engage_cache[_key] = (result[:limit], time.monotonic() + _ENGAGE_TTL)
    return jsonify(result[:limit])

# ── Per-user DOW × hour heatmap ───────────────────────────────────────────────
_uheat_cache: dict = {}   # {(gid, uid): (result, expires_at)}
_UHEAT_TTL = 300

@flask_app.route('/api/user-heatmap')
@require_auth
def api_user_heatmap():
    """
    Day-of-week × hour heatmap for a specific user.
    ?guild_id=X&uid=UID
    Response: {uid, name, matrix: [[int]*24]*7, days, total_sessions}
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    uid = request.args.get('uid', '').strip()
    if not uid:
        return jsonify({'error': 'uid required'}), 400
    if not _validate_snowflake(uid):
        return jsonify({'error': 'invalid uid format'}), 400
    _key = (gid, uid)
    _cached = _uheat_cache.get(_key)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    matrix = [[0] * 24 for _ in range(7)]
    name   = user_daily.get(gid, {}).get(uid, {}).get('name', uid)
    total  = 0
    with _lock_history:
        hist = [s for s in session_history
                if str(s.get('guild_id', '')) == gid and str(s.get('uid', '')) == uid]
    for s in hist:
        try:
            jt  = datetime.strptime(s['join'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
            dow = jt.weekday()   # 0=Mon
            matrix[dow][jt.hour] += 1
            total += 1
        except Exception:
            pass
    result = {
        'uid':            uid,
        'name':           name,
        'matrix':         matrix,
        'days':           ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา'],
        'total_sessions': total,
    }
    _uheat_cache[_key] = (result, time.monotonic() + _UHEAT_TTL)
    return jsonify(result)

# ── New-user journey (onboarding funnel) ──────────────────────────────────────
_journey_cache: dict = {}   # {(gid, cohort_weeks): (result, expires_at)}
_JOURNEY_TTL = 600

@flask_app.route('/api/new-user-journey')
@require_auth
def api_new_user_journey():
    """
    Onboarding funnel for users who joined in the last N weeks.
    ?guild_id=X&cohort_weeks=8
    Response: [{uid, name, first_seen, first_session_date, days_to_second,
                sessions_in_first_30d, retained_week1}]
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    try:
        cohort_weeks = max(2, min(int(request.args.get('cohort_weeks', 8)), 52))
    except ValueError:
        return jsonify({'error': 'invalid cohort_weeks'}), 400
    _key = (gid, cohort_weeks)
    _cached = _journey_cache.get(_key)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    cutoff = (datetime.now(THAI_TZ) - timedelta(weeks=cohort_weeks)).strftime('%Y-%m-%d')
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    # Group sessions by uid
    uid_sessions: dict = {}
    for s in hist:
        u = str(s.get('uid', ''))
        uid_sessions.setdefault(u, []).append(s.get('join', ''))
    result = []
    for uid, udata in user_daily.get(gid, {}).items():
        fs = udata.get('first_seen', '')[:10]
        if not fs or fs < cutoff:
            continue
        joins = sorted(uid_sessions.get(uid, []))
        if not joins:
            continue
        first_sess = joins[0][:10]
        # days to second session (different day)
        unique_days = sorted({j[:10] for j in joins})
        days_to_second = None
        if len(unique_days) >= 2:
            try:
                d1 = datetime.strptime(unique_days[0], '%Y-%m-%d').date()
                d2 = datetime.strptime(unique_days[1], '%Y-%m-%d').date()
                days_to_second = (d2 - d1).days
            except Exception:
                pass
        # sessions in first 30 days
        try:
            d_first = datetime.strptime(first_sess, '%Y-%m-%d').date()
            d_30    = (d_first + timedelta(days=30)).strftime('%Y-%m-%d')
            sess_30 = sum(1 for j in joins if j[:10] <= d_30)
        except Exception:
            sess_30 = len(joins)
        # retained in week 1 (days 7-14 from first session)
        try:
            d_w1s = (d_first + timedelta(days=7)).strftime('%Y-%m-%d')
            d_w1e = (d_first + timedelta(days=14)).strftime('%Y-%m-%d')
            retained_w1 = any(d_w1s <= j[:10] <= d_w1e for j in joins)
        except Exception:
            retained_w1 = False
        result.append({
            'uid':                   uid,
            'name':                  udata.get('name', '?'),
            'first_seen':            fs,
            'first_session_date':    first_sess,
            'days_to_second':        days_to_second,
            'sessions_in_first_30d': sess_30,
            'retained_week1':        retained_w1,
        })
    result.sort(key=lambda x: x['first_seen'])
    _journey_cache[_key] = (result, time.monotonic() + _JOURNEY_TTL)
    return jsonify(result)

# ── Peak hours summary ────────────────────────────────────────────────────────
_peak_cache: dict = {}   # {gid: (result, expires_at)}
_PEAK_TTL = 300

@flask_app.route('/api/peak-summary')
@require_auth
def api_peak_summary():
    """
    Guild peak activity summary KPIs.
    ?guild_id=X
    Response: {busiest_hour, busiest_hour_count, quietest_hour, busiest_dow,
               busiest_dow_label, most_active_date, most_active_sessions,
               avg_session_min, total_sessions, total_users}
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid = str(guild_id)
    _cached = _peak_cache.get(gid)
    if _cached and time.monotonic() < _cached[1]:
        return jsonify(_cached[0])
    with _lock_history:
        hist = [s for s in session_history if str(s.get('guild_id', '')) == gid]
    hour_cnt = [0] * 24
    dow_cnt  = [0] * 7
    day_cnt: dict = {}
    total_sec = 0
    uids: set = set()
    for s in hist:
        try:
            jt = datetime.strptime(s['join'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
            hour_cnt[jt.hour]           += 1
            dow_cnt[jt.weekday()]       += 1
            d = jt.strftime('%Y-%m-%d')
            day_cnt[d] = day_cnt.get(d, 0) + 1
            total_sec += s.get('seconds', 0)
            uids.add(str(s.get('uid', '')))
        except Exception:
            pass
    busiest_hour  = int(hour_cnt.index(max(hour_cnt))) if any(hour_cnt) else 0
    quietest_hour = int(hour_cnt.index(min(hour_cnt))) if any(hour_cnt) else 0
    busiest_dow   = int(dow_cnt.index(max(dow_cnt)))   if any(dow_cnt)  else 0
    dow_labels    = ['จันทร์', 'อังคาร', 'พุธ', 'พฤหัส', 'ศุกร์', 'เสาร์', 'อาทิตย์']
    most_active_d = max(day_cnt.items(), key=lambda x: x[1], default=(None, 0))
    n = len(hist)
    result = {
        'busiest_hour':        busiest_hour,
        'busiest_hour_count':  hour_cnt[busiest_hour],
        'quietest_hour':       quietest_hour,
        'busiest_dow':         busiest_dow,
        'busiest_dow_label':   dow_labels[busiest_dow],
        'most_active_date':    most_active_d[0],
        'most_active_sessions':most_active_d[1],
        'avg_session_min':     round(total_sec / 60 / max(n, 1), 1),
        'total_sessions':      n,
        'total_users':         len(uids),
    }
    _peak_cache[gid] = (result, time.monotonic() + _PEAK_TTL)
    return jsonify(result)

# ── Voice overlap timeline (concurrent users per 15-min bucket) ───────────────
@flask_app.route('/api/voice-overlap-timeline')
@require_auth
def api_voice_overlap_timeline():
    """
    Concurrent user count per 15-minute bucket for a given date.
    ?guild_id=X&date=YYYY-MM-DD  (defaults to today)
    Response: {date, buckets: [{time, count}]}  (96 entries)
    """
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    gid  = str(guild_id)
    date = request.args.get('date', datetime.now(THAI_TZ).strftime('%Y-%m-%d')).strip()
    try:
        base_dt = datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'invalid date format, use YYYY-MM-DD'}), 400
    with _lock_history:
        hist = [s for s in session_history
                if str(s.get('guild_id', '')) == gid and s.get('join', '').startswith(date)]
    # Parse sessions into datetime pairs
    parsed = []
    for s in hist:
        try:
            j = datetime.strptime(s['join'],  '%Y-%m-%d %H:%M')
            l = datetime.strptime(s['leave'], '%Y-%m-%d %H:%M')
            if j <= l:
                parsed.append((j, l))
        except Exception:
            pass
    buckets = []
    for b in range(96):   # 0..95 → 00:00..23:45
        bstart = base_dt + timedelta(minutes=b * 15)
        bend   = bstart  + timedelta(minutes=15)
        count  = sum(1 for (j, l) in parsed if j < bend and l > bstart)
        buckets.append({'time': bstart.strftime('%H:%M'), 'count': count})
    return jsonify({'date': date, 'buckets': buckets})

# ─────────────────────────────────────────────────────────────────────────────

@flask_app.route('/api/trivia-scores')
@require_auth
def api_trivia_scores():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    return jsonify(trivia_scores.get(str(guild_id), {}))

@flask_app.route('/api/daily-heatmap')
@require_auth
def api_daily_heatmap():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    try:
        days = max(1, min(int(request.args.get('days', 365)), 3650))
    except ValueError:
        return jsonify({'error': 'invalid days'}), 400
    now = datetime.now(THAI_TZ)
    cutoff = now - timedelta(days=days)
    result = {}
    for s in session_history:
        if s.get('guild_id') != guild_id:
            continue
        try:
            join_date = datetime.strptime(s['join'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
            if join_date < cutoff:
                continue
            d = join_date.strftime('%Y-%m-%d')
            result[d] = result.get(d, 0) + 1
        except Exception:
            pass
    gdata = daily_activity.get(str(guild_id), {})
    for d, c in gdata.items():
        try:
            dt = datetime.strptime(d, '%Y-%m-%d').replace(tzinfo=THAI_TZ)
            if dt >= cutoff:
                result[d] = max(result.get(d, 0), c)
        except Exception:
            pass
    return jsonify(result)

@flask_app.route('/api/user-daily')
@require_auth
def api_user_daily():
    guild_id, err = _guild_id_or_error()
    if err:
        return err
    try:
        days = max(1, min(int(request.args.get('days', 365)), 3650))
    except ValueError:
        return jsonify({'error': 'invalid days'}), 400
    now = datetime.now(THAI_TZ)
    cutoff = now - timedelta(days=days)
    result = {}
    for s in session_history:
        if s.get('guild_id') != guild_id:
            continue
        try:
            join_date = datetime.strptime(s['join'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
            if join_date < cutoff:
                continue
            uid = s.get('uid', '')
            name = s.get('name', 'Unknown')
            d = join_date.strftime('%Y-%m-%d')
            if uid not in result:
                result[uid] = {'name': name, 'dates': {}}
            result[uid]['dates'][d] = result[uid]['dates'].get(d, 0) + 1
            result[uid]['name'] = name
        except Exception:
            pass
    gdata = user_daily.get(str(guild_id), {})
    for uid, udata in gdata.items():
        if uid not in result:
            result[uid] = {'name': udata['name'], 'dates': {}}
        for d, c in udata.get('dates', {}).items():
            try:
                dt = datetime.strptime(d, '%Y-%m-%d').replace(tzinfo=THAI_TZ)
                if dt >= cutoff:
                    result[uid]['dates'][d] = max(result[uid]['dates'].get(d, 0), c)
            except Exception:
                pass
        # Merge analytics fields from persistent store
        for field in ('first_seen', 'last_seen', 'alltime_seconds', 'session_count',
                      'streak_max', 'channel_seconds'):
            if field in udata:
                result[uid][field] = udata[field]
    sorted_result = dict(sorted(result.items(), key=lambda x: sum(x[1]['dates'].values()), reverse=True)[:15])
    return jsonify(sorted_result)

@flask_app.route('/health')
def health():
    """Public health check — minimal info only (no operational data)."""
    return jsonify({'ok': client.is_ready()})

@flask_app.route('/api/health')
@require_auth
def api_health():
    """Authenticated health check with operational details."""
    uptime_sec = int((datetime.now(THAI_TZ) - start_time).total_seconds())
    latency_ms = round(client.latency * 1000, 1) if client.is_ready() else None
    return jsonify({
        'ok': client.is_ready(),
        'uptime': format_duration(uptime_sec),
        'uptime_seconds': uptime_sec,
        'guilds': len(client.guilds) if client.is_ready() else 0,
        'latency_ms': latency_ms,
        'voice_users': len(voice_join_times),
        'timestamp': datetime.now(THAI_TZ).isoformat(),
    })

@flask_app.route('/api/logs')
@require_owner
def api_logs():
    lines = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    return jsonify({'lines': [l.rstrip() for l in lines[-100:]]})

@flask_app.route('/api/apikey')
@require_auth
def api_apikey():
    """Return masked API key info — ใช้สำหรับตรวจสอบว่า key ถูก set หรือไม่"""
    if not DASHBOARD_API_KEY:
        return jsonify({'enabled': False, 'message': 'Set DASHBOARD_API_KEY env var to enable API key auth'})
    masked = DASHBOARD_API_KEY[:4] + '*' * (len(DASHBOARD_API_KEY) - 8) + DASHBOARD_API_KEY[-4:]
    return jsonify({'enabled': True, 'key_preview': masked,
                    'usage': 'Add header: X-API-Key: <your-key>'})

def _action_guild_id_or_error():
    """Helper for action routes — extract guild_id from POST body and validate access."""
    data = request.get_json(silent=True) or {}
    guild_id = str(data.get('guild_id') or flask_session.get('current_guild_id') or '').strip()
    if not guild_id:
        # Only owner may act without specifying a guild (global fallback)
        if not session_is_owner():
            return None, (jsonify({'error': 'guild_id required'}), 400)
        return None, None
    if not require_guild_access(guild_id):
        return None, (jsonify({'error': 'Forbidden'}), 403)
    return guild_id, None

@flask_app.route('/api/action/joke', methods=['POST'])
@require_auth
def api_action_joke():
    guild_id, err = _action_guild_id_or_error()
    if err:
        return err
    if bot_loop:
        asyncio.run_coroutine_threadsafe(_test_joke(guild_id), bot_loop)
    return jsonify({'ok': True})

@flask_app.route('/api/action/trivia', methods=['POST'])
@require_auth
def api_action_trivia():
    guild_id, err = _action_guild_id_or_error()
    if err:
        return err
    if bot_loop:
        asyncio.run_coroutine_threadsafe(_test_trivia(guild_id), bot_loop)
    return jsonify({'ok': True})

@flask_app.route('/api/action/summary', methods=['POST'])
@require_auth
def api_action_summary():
    guild_id, err = _action_guild_id_or_error()
    if err:
        return err
    if bot_loop:
        asyncio.run_coroutine_threadsafe(send_weekly_summary(), bot_loop)
    return jsonify({'ok': True})

@flask_app.route('/api/action/rank', methods=['POST'])
@require_auth
def api_action_rank():
    guild_id, err = _action_guild_id_or_error()
    if err:
        return err
    if bot_loop:
        async def _do():
            ch = get_guild_ch(guild_id, 'stats')
            if ch:
                await send_leaderboard(ch)
        asyncio.run_coroutine_threadsafe(_do(), bot_loop)
    return jsonify({'ok': True})

@flask_app.route('/api/action/dm-user', methods=['POST'])
@require_auth
def api_action_dm_user():
    """Send a DM to a specific member via the Discord bot.
    Body: {guild_id, uid, message}
    """
    try:
        data      = request.get_json(force=True) or {}
        guild_id  = str(data.get('guild_id', '')).strip()
        uid       = str(data.get('uid', '')).strip()
        msg_text  = str(data.get('message', '')).strip()
    except Exception:
        return jsonify({'error': 'invalid body'}), 400
    if not guild_id or not uid or not msg_text:
        return jsonify({'error': 'guild_id, uid and message required'}), 400
    if not _validate_snowflake(uid):
        return jsonify({'error': 'invalid uid'}), 400
    if len(msg_text) > 1800:
        return jsonify({'error': 'message too long (max 1800 chars)'}), 400
    if not bot_loop:
        return jsonify({'error': 'bot not ready'}), 503

    async def _do_dm():
        try:
            g   = client.get_guild(int(guild_id))
            if g is None:
                return
            m = g.get_member(int(uid))
            if m is None:
                m = await g.fetch_member(int(uid))
            await m.send(msg_text)
        except Exception as exc:
            log(f'dm-user error uid={uid}: {exc}')

    asyncio.run_coroutine_threadsafe(_do_dm(), bot_loop)
    return jsonify({'ok': True})


async def _test_joke(guild_id=None):
    channel = get_guild_ch(guild_id, 'content')
    if not channel:
        log(f'_test_joke: no content channel found for guild_id={guild_id}')
        return
    jokes = load_jokes()
    if not jokes:
        await channel.send('ไม่มีมุขเลย — ถูกกรองออกหมดแล้ว!')
        return
    category, joke = random.choice(jokes)
    await send_joke_with_vote(channel, category, joke)

async def _test_trivia(guild_id=None):
    channel = get_guild_ch(guild_id, 'content')
    if not channel:
        log(f'_test_trivia: no content channel found for guild_id={guild_id}')
        return
    await _post_trivia(channel)
# ===========================

# ===== Start =====
def run_discord():
    """Run Discord bot with automatic restart on transient failures."""
    global bot_loop, client
    import time as _time
    while True:
        try:
            bot_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(bot_loop)
            bot_loop.run_until_complete(client.start(TOKEN))
            log('[Discord] bot exited cleanly — not restarting')
            break  # clean exit (e.g. ctrl+c)
        except Exception as e:
            log(f'[Discord] bot crashed: {e} — restarting in 10s')
            _time.sleep(10)
            client = VoiceBot()  # fresh client for reconnect

def run_flask():
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    flask_app.run(host='0.0.0.0', port=DASHBOARD_PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    log(f'Starting VoiceLog Bot on port {DASHBOARD_PORT}...')
    bot_thread   = threading.Thread(target=run_discord, daemon=True)
    flask_thread = threading.Thread(target=run_flask,   daemon=True)
    bot_thread.start()
    flask_thread.start()
    threading.Event().wait()   # block main thread — ไม่มี pystray แล้ว
