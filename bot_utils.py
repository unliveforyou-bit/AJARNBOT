"""
bot_utils.py — Pure business-logic functions (no Discord / Flask dependency)
Testable independently with: python -m pytest tests/ -v
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

THAI_TZ = ZoneInfo('Asia/Bangkok')
MAX_ACTIVE_JOKES = 50


def format_duration(seconds: int) -> str:
    """แปลงจำนวนวินาทีเป็นข้อความภาษาไทย เช่น '2 ชม. 30 นาที'"""
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    if d > 0:
        return f'{d} วัน {h} ชม. {m} นาที'
    if h > 0:
        return f'{h} ชม. {m} นาที'
    return f'{m} นาที'


def get_stats_for_period(session_history: list, voice_join_times: dict,
                         period: str = 'week', guild_id: str | None = None) -> dict:
    """
    รวบรวมสถิติ voice จาก session_history + live voice_join_times

    Parameters
    ----------
    session_history : list[dict]  — ประวัติ session ที่บันทึกไว้
    voice_join_times : dict       — {(guild_id, member_id): (name, join_dt, channel)}
    period : 'today' | 'week' | 'month'
    guild_id : str | None         — กรองเฉพาะ guild นี้ (None = ทุก guild)

    Returns
    -------
    dict  — {user_id_str: {'name': str, 'seconds': int}}
    """
    now = datetime.now(THAI_TZ)
    combined: dict = {}

    for s in session_history:
        if guild_id and s.get('guild_id') != guild_id:
            continue
        try:
            join_dt = datetime.strptime(s['join'], '%Y-%m-%d %H:%M').replace(tzinfo=THAI_TZ)
        except (KeyError, ValueError):
            continue  # skip malformed records

        if period == 'today' and join_dt.date() != now.date():
            continue
        if period == 'week':
            week_start = now - timedelta(days=now.weekday())
            if join_dt.date() < week_start.date():
                continue
        if period == 'month' and (join_dt.year != now.year or join_dt.month != now.month):
            continue

        uid = s.get('uid', '')
        name = s.get('name', '')
        if uid not in combined:
            combined[uid] = {'name': name, 'seconds': 0}
        combined[uid]['seconds'] += s.get('seconds', 0)

    # รวม live users ที่อยู่ใน voice ตอนนี้
    for (gid, mid), (name, join_time, _) in voice_join_times.items():
        if guild_id and str(gid) != guild_id:
            continue
        elapsed = int((datetime.now(THAI_TZ) - join_time).total_seconds())
        key = str(mid)
        if key not in combined:
            combined[key] = {'name': name, 'seconds': 0}
        combined[key]['seconds'] += elapsed

    return combined


def register_joke_msg(active_joke_msgs: dict, msg_id: int, joke_text: str) -> None:
    """เก็บ message_id → joke_text ใน LRU-style cache (จำกัด MAX_ACTIVE_JOKES)"""
    active_joke_msgs[msg_id] = joke_text
    if len(active_joke_msgs) > MAX_ACTIVE_JOKES:
        active_joke_msgs.pop(next(iter(active_joke_msgs)))
