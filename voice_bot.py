"""
VoiceLog Bot — Cloud version (Railway)
ไม่มี pystray / plyer / Windows-specific code
ใช้ environment variables สำหรับ token และ channel ID
"""
import discord
from discord.ext import tasks
from discord.ext import commands as _commands
from discord import app_commands
import random, os, sys, asyncio, threading, json, secrets
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, request, Response, redirect, session as flask_session
from functools import wraps

THAI_TZ = ZoneInfo('Asia/Bangkok')

# ===== Environment Variables =====
TOKEN                = os.environ['DISCORD_TOKEN']           # required
VOICE_LOG_CHANNEL_ID = int(os.environ['VOICE_LOG_CHANNEL_ID'])  # required
DASHBOARD_PORT       = int(os.environ.get('PORT', 5000))
DASHBOARD_PASSWORD   = os.environ.get('DASHBOARD_PASSWORD', '')  # optional basic auth
# =================================

# ===== Paths =====
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') or os.path.join(BASE_DIR, 'data')
JOKES_FILE   = os.path.join(BASE_DIR, 'jokes.txt')
TRIVIA_FILE  = os.path.join(BASE_DIR, 'trivia.txt')
STATS_FILE   = os.path.join(DATA_DIR, 'voice_stats.json')
CONFIG_FILE  = os.path.join(DATA_DIR, 'bot_config.json')
HOURLY_FILE  = os.path.join(DATA_DIR, 'hourly_activity.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'session_history.json')
VOTES_FILE   = os.path.join(DATA_DIR, 'joke_votes.json')
LOG_FILE     = os.path.join(DATA_DIR, 'bot.log')
os.makedirs(DATA_DIR, exist_ok=True)
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
    'joke_delay':               15,
    'trivia_delay':             15,
    'mute_cooldown_sec':        3,
    'content_interval':         30,
    'summary_hour':             9,
    'joke_downvote_threshold':  3,
    'channel_voice':   VOICE_LOG_CHANNEL_ID,
    'channel_content': VOICE_LOG_CHANNEL_ID,
    'channel_stats':   VOICE_LOG_CHANNEL_ID,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding='utf-8') as f:
            bot_config.update(json.load(f))

def save_config():
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(bot_config, f, ensure_ascii=False, indent=2)
# ==================

# ===== Jokes / Trivia =====
JOKES_FALLBACK = [
    "ทำไมปลาถึงไม่เล่น Facebook? เพราะกลัวติดแหอินเทอร์เน็ต",
    "ทำไมโปรแกรมเมอร์ถึงชอบ dark mode? เพราะ light attracts bugs",
]

def load_jokes(include_filtered=False):
    threshold   = bot_config.get('joke_downvote_threshold', 3)
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

def load_trivia():
    if os.path.exists(TRIVIA_FILE):
        with open(TRIVIA_FILE, encoding='utf-8') as f:
            return [l.strip() for l in f if '|' in l and not l.startswith('#')]
    return []
# ==========================

# ===== Voice Stats =====
voice_join_times = {}
weekly_stats     = {}
summary_sent     = False

def load_stats():
    global weekly_stats
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, encoding='utf-8') as f:
            weekly_stats = json.load(f)

def save_stats():
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(weekly_stats, f, ensure_ascii=False, indent=2)

def format_duration(seconds):
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    if d > 0:
        return f'{d} วัน {h} ชม. {m} นาที'
    if h > 0:
        return f'{h} ชม. {m} นาที'
    return f'{m} นาที'
# =======================

# ===== Heatmap =====
hourly_activity = {str(h): 0 for h in range(24)}

def load_hourly():
    if os.path.exists(HOURLY_FILE):
        with open(HOURLY_FILE, encoding='utf-8') as f:
            hourly_activity.update(json.load(f))

def save_hourly():
    with open(HOURLY_FILE, 'w', encoding='utf-8') as f:
        json.dump(hourly_activity, f)
# ===================

# ===== Session History =====
session_history = []

def load_history():
    global session_history
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding='utf-8') as f:
            session_history = json.load(f)

def save_history():
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(session_history[-MAX_HISTORY:], f, ensure_ascii=False, indent=2)
# ===========================

# ===== Joke Votes =====
joke_votes       = {}
active_joke_msgs = {}

def load_votes():
    global joke_votes
    if os.path.exists(VOTES_FILE):
        with open(VOTES_FILE, encoding='utf-8') as f:
            joke_votes = json.load(f)

def save_votes():
    with open(VOTES_FILE, 'w', encoding='utf-8') as f:
        json.dump(joke_votes, f, ensure_ascii=False, indent=2)

def register_joke_msg(msg_id, joke_text):
    active_joke_msgs[msg_id] = joke_text
    if len(active_joke_msgs) > MAX_ACTIVE_JOKES:
        active_joke_msgs.pop(next(iter(active_joke_msgs)))
# ======================

# ===== record join/leave =====
def record_join(member_id, display_name, channel_name=''):
    voice_join_times[member_id] = (display_name, datetime.now(THAI_TZ), channel_name)
    hour = str(datetime.now(THAI_TZ).hour)
    hourly_activity[hour] = hourly_activity.get(hour, 0) + 1
    save_hourly()

def record_leave(member_id):
    if member_id not in voice_join_times:
        return
    display_name, join_time, channel_name = voice_join_times.pop(member_id)
    leave_time = datetime.now(THAI_TZ)
    elapsed    = int((leave_time - join_time).total_seconds())
    key = str(member_id)
    if key not in weekly_stats:
        weekly_stats[key] = {'name': display_name, 'seconds': 0}
    weekly_stats[key]['name']    = display_name
    weekly_stats[key]['seconds'] += elapsed
    save_stats()
    session_history.append({
        'uid':      str(member_id),
        'name':     display_name,
        'channel':  channel_name,
        'join':     join_time.strftime('%Y-%m-%d %H:%M'),
        'leave':    leave_time.strftime('%Y-%m-%d %H:%M'),
        'duration': format_duration(elapsed),
        'seconds':  elapsed,
    })
    save_history()
# =============================

# ===== Cooldown =====
mute_cooldown = {}

def check_cooldown(member_id, event):
    key = (member_id, event)
    now = datetime.now(THAI_TZ)
    if key in mute_cooldown and (now - mute_cooldown[key]).total_seconds() < bot_config['mute_cooldown_sec']:
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

# ===== Uptime + event counter =====
start_time   = datetime.now(THAI_TZ)
event_counts = {'join': 0, 'leave': 0, 'mute': 0, 'deaf': 0, 'stream': 0, 'video': 0}
# ==================================

# ===== Logging =====
def log(msg):
    line = f'[{datetime.now(THAI_TZ).strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n'
    print(line, end='')   # Railway logs → stdout
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass
# ===================

# ===== Discord Bot =====
intents                 = discord.Intents.default()
intents.voice_states    = True
intents.messages        = True
intents.message_content = True

class VoiceBot(discord.ext.commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

client   = VoiceBot()
bot_loop = None

def ch_voice():   return client.get_channel(int(bot_config['channel_voice']))
def ch_content(): return client.get_channel(int(bot_config['channel_content']))
def ch_stats():   return client.get_channel(int(bot_config['channel_stats']))

async def send_joke_with_vote(channel, category, joke):
    if '?' in joke:
        parts = joke.split('?', 1)
        await channel.send(f'[{category}] {parts[0].strip()}?')
        await asyncio.sleep(bot_config['joke_delay'])
        msg = await channel.send(parts[1].strip())
    else:
        msg = await channel.send(f'[{category}] {joke}')
    await msg.add_reaction('👍')
    await msg.add_reaction('👎')
    register_joke_msg(msg.id, joke)

async def send_leaderboard(channel):
    combined = {k: dict(v) for k, v in weekly_stats.items()}
    for mid, (name, join_time, _) in voice_join_times.items():
        elapsed = int((datetime.now(THAI_TZ) - join_time).total_seconds())
        key = str(mid)
        if key not in combined:
            combined[key] = {'name': name, 'seconds': 0}
        combined[key]['seconds'] += elapsed
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
    combined = {k: dict(v) for k, v in weekly_stats.items()}
    for mid, (name, join_time, _) in voice_join_times.items():
        elapsed = int((datetime.now(THAI_TZ) - join_time).total_seconds())
        key = str(mid)
        if key not in combined:
            combined[key] = {'name': name, 'seconds': 0}
        combined[key]['seconds'] += elapsed
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

@tasks.loop(minutes=30)
async def send_content():
    if not bot_config['send_content']:
        return
    channel = ch_content()
    if not channel:
        return
    trivia_list = load_trivia()
    if trivia_list and random.random() < 0.5:
        item             = random.choice(trivia_list)
        question, answer = item.split('|', 1)
        await channel.send(f'ทดสอบความรู้: {question.strip()}')
        await asyncio.sleep(bot_config['trivia_delay'])
        await channel.send(f'เฉลย: {answer.strip()}')
    else:
        jokes = load_jokes()
        if jokes:
            category, joke = random.choice(jokes)
            await send_joke_with_vote(channel, category, joke)

@tasks.loop(hours=1)
async def weekly_summary_task():
    global summary_sent
    now = datetime.now(THAI_TZ)
    if now.weekday() == 0 and now.hour == bot_config['summary_hour']:
        if not summary_sent:
            channel = ch_stats()
            if channel:
                await send_weekly_summary(channel)
            weekly_stats.clear()
            save_stats()
            summary_sent = True
    else:
        summary_sent = False

@tasks.loop(hours=1)
async def daily_backup_task():
    now = datetime.now(THAI_TZ)
    if now.hour != 0:
        return
    channel = ch_stats()
    if not channel:
        return
    combined = {k: dict(v) for k, v in weekly_stats.items()}
    total_sessions = len(session_history)
    top3 = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)[:3]
    lines = [f'📊 **Backup รายวัน** — {now.strftime("%Y-%m-%d")}',
             f'Sessions รวม: {total_sessions}']
    for i, (uid, d) in enumerate(top3):
        lines.append(f'{i+1}. {d["name"]} — {format_duration(d["seconds"])}')
    await channel.send('\n'.join(lines))
    log('Daily backup sent to Discord')

@client.event
async def on_ready():
    load_stats()
    load_config()
    load_hourly()
    load_history()
    load_votes()
    log(f'Bot ready: {client.user}')
    send_content.start()
    weekly_summary_task.start()
    daily_backup_task.start()
    await client.tree.sync()

@client.tree.command(name="rank", description="แสดงอันดับ Voice สัปดาห์นี้")
@app_commands.checks.cooldown(1, 30.0)
async def slash_rank(interaction: discord.Interaction):
    await interaction.response.defer()
    combined = {k: dict(v) for k, v in weekly_stats.items()}
    for mid, (name, join_time, _) in voice_join_times.items():
        elapsed = int((datetime.now(THAI_TZ) - join_time).total_seconds())
        key = str(mid)
        if key not in combined:
            combined[key] = {'name': name, 'seconds': 0}
        combined[key]['seconds'] += elapsed
    if not combined:
        await interaction.followup.send('ยังไม่มีข้อมูล Voice ในสัปดาห์นี้')
        return
    sorted_stats = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)
    medals = ['🥇', '🥈', '🥉']
    lines = ['--- อันดับ Voice สัปดาห์นี้ ---']
    for i, (uid, data) in enumerate(sorted_stats[:10]):
        prefix = medals[i] if i < 3 else f'{i+1}.'
        lines.append(f'{prefix} {data["name"]}  {format_duration(data["seconds"])}')
    lines.append('------------------------------')
    await interaction.followup.send('\n'.join(lines))

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
    item = random.choice(trivia_list)
    question, answer = item.split('|', 1)
    await interaction.response.send_message(f'🤔 {question.strip()}')
    await asyncio.sleep(bot_config['trivia_delay'])
    await interaction.channel.send(f'✅ เฉลย: {answer.strip()}')

@slash_rank.error
@slash_joke.error
@slash_trivia.error
async def on_slash_cooldown(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f'⏳ รอ {error.retry_after:.0f} วินาทีก่อน', ephemeral=True)

@client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.content.strip().lower() == '!rank':
        if check_command_rate(message.author.id, 'rank'):
            await send_leaderboard(message.channel)
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
    threshold = bot_config.get('joke_downvote_threshold', 3)
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

@client.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    channel = ch_voice()
    if channel is None:
        return

    if before.channel is None and after.channel is not None:
        record_join(member.id, member.display_name, after.channel.name)
        event_counts['join'] += 1
        if bot_config['announce_join']:
            await channel.send(f'{member.display_name} เข้าห้อง {after.channel.name}')
    elif before.channel is not None and after.channel is None:
        record_leave(member.id)
        event_counts['leave'] += 1
        if bot_config['announce_leave']:
            await channel.send(f'{member.display_name} ออกจากห้อง {before.channel.name}')
    elif before.channel != after.channel:
        record_leave(member.id)
        record_join(member.id, member.display_name, after.channel.name)
        if bot_config['announce_move']:
            await channel.send(f'{member.display_name} ย้ายจาก {before.channel.name} ไป {after.channel.name}')

    if before.self_mute != after.self_mute and bot_config['announce_mute'] and check_cooldown(member.id, 'mute'):
        event_counts['mute'] += 1
        await channel.send(f'{member.display_name} {"ปิดไมค์" if after.self_mute else "เปิดไมค์"}')

    if before.self_deaf != after.self_deaf and bot_config['announce_deaf'] and check_cooldown(member.id, 'deaf'):
        event_counts['deaf'] += 1
        await channel.send(f'{member.display_name} {"ปิดหู" if after.self_deaf else "เปิดหู"}')

    log(f'stream: {before.self_stream}->{after.self_stream} | video: {before.self_video}->{after.self_video}')
    if before.self_stream != after.self_stream and bot_config['announce_stream']:
        event_counts['stream'] += 1
        await channel.send(f'{member.display_name} {"เริ่ม stream" if after.self_stream else "หยุด stream"}')

    if before.self_video != after.self_video and bot_config['announce_video']:
        event_counts['video'] += 1
        await channel.send(f'{member.display_name} {"เปิดกล้อง" if after.self_video else "ปิดกล้อง"}')
# =======================

# ===== Flask Dashboard =====
flask_app = Flask(__name__)
flask_app.secret_key = os.environ.get('FLASK_SECRET', secrets.token_hex(32))

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_PASSWORD:
            return f(*args, **kwargs)
        if not flask_session.get('logged_in'):
            if request.path.startswith('/api/'):
                return Response('Unauthorized', 401)
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

LOGIN_HTML = """<!DOCTYPE html>
<html lang="th">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login — VoiceLog Bot</title>
<style>
  body{background:#1e1f22;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;font-family:'Segoe UI',sans-serif;}
  .box{background:#2b2d31;border:1px solid #3f4147;border-radius:12px;padding:40px;width:320px;}
  h2{color:#dbdee1;margin-bottom:24px;font-size:20px;text-align:center;}
  input{width:100%;background:#1e1f22;border:1px solid #3f4147;border-radius:6px;color:#dbdee1;padding:10px 14px;font-size:14px;box-sizing:border-box;margin-bottom:12px;}
  input:focus{outline:none;border-color:#5865f2;}
  button{width:100%;background:#5865f2;color:white;border:none;border-radius:6px;padding:10px;font-size:14px;font-weight:600;cursor:pointer;}
  button:hover{background:#4752c4;}
  .err{color:#da373c;font-size:13px;text-align:center;margin-top:8px;}
  .logo{text-align:center;font-size:36px;margin-bottom:16px;}
</style>
</head>
<body><div class="box">
  <div class="logo">🎙️</div>
  <h2>VoiceLog Bot</h2>
  <form method="post">
    <input name="password" type="password" placeholder="รหัสผ่าน" autofocus>
    <button type="submit">เข้าสู่ระบบ</button>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
  </form>
</div></body></html>"""

@flask_app.route('/login', methods=['GET', 'POST'])
def login():
    from flask import render_template_string
    if not DASHBOARD_PASSWORD:
        return redirect('/')
    error = None
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            flask_session['logged_in'] = True
            flask_session.permanent = True
            return redirect('/')
        error = 'รหัสผ่านไม่ถูกต้อง'
    return render_template_string(LOGIN_HTML, error=error)

@flask_app.route('/logout')
def logout():
    flask_session.clear()
    return redirect('/login')

PROFILE_HTML = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Member Profile</title>
<style>
  :root{--bg:#1e1f22;--surface:#2b2d31;--card:#313338;--border:#3f4147;
        --text:#dbdee1;--muted:#949ba4;--accent:#5865f2;--green:#23a559;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',sans-serif;font-size:14px;}
  header{background:var(--surface);border-bottom:1px solid var(--border);
         padding:16px 24px;display:flex;align-items:center;gap:12px;}
  .back{color:var(--accent);text-decoration:none;font-size:13px;}
  .back:hover{text-decoration:underline;}
  header h1{font-size:17px;font-weight:700;}
  main{max-width:800px;margin:0 auto;padding:24px 16px;display:grid;gap:16px;}
  .card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:20px;}
  .card-title{font-size:11px;font-weight:700;text-transform:uppercase;
              letter-spacing:.6px;color:var(--muted);margin-bottom:14px;}
  .hero{display:flex;align-items:center;gap:20px;}
  .avatar{width:64px;height:64px;border-radius:50%;background:var(--accent);
          display:flex;align-items:center;justify-content:center;font-size:28px;}
  .hero-info h2{font-size:22px;font-weight:700;}
  .hero-info .sub{color:var(--muted);font-size:13px;margin-top:4px;}
  .stat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;}
  .stat-box{background:var(--surface);border-radius:6px;padding:14px;display:flex;flex-direction:column;gap:4px;}
  .stat-box .val{font-size:20px;font-weight:700;color:var(--accent);}
  .stat-box .lbl{font-size:11px;color:var(--muted);}
  .heatmap-wrap{display:flex;align-items:flex-end;gap:3px;height:80px;}
  .heatmap-bar{flex:1;border-radius:3px 3px 0 0;min-height:2px;}
  .heatmap-labels{display:flex;justify-content:space-between;margin-top:4px;color:var(--muted);font-size:10px;}
  table{width:100%;border-collapse:collapse;font-size:13px;}
  th{color:var(--muted);text-align:left;padding:6px 10px;border-bottom:1px solid var(--border);font-weight:600;}
  td{padding:7px 10px;border-bottom:1px solid var(--border);}
  tr:last-child td{border-bottom:none;}
  tr:hover td{background:var(--surface);}
  .empty{color:var(--muted);font-size:13px;}
</style>
</head>
<body>
<header>
  <a class="back" href="/">&#8592; Dashboard</a>
  <h1 id="pageTitle">Member Profile</h1>
  <a href="/logout" style="color:var(--muted);font-size:12px;text-decoration:none;margin-left:auto">ออกจากระบบ</a>
</header>
<main>
  <div class="card"><div class="hero">
    <div class="avatar">&#127908;</div>
    <div class="hero-info"><h2 id="memberName">...</h2><div class="sub" id="memberSub"></div></div>
  </div></div>
  <div class="card"><div class="card-title">สถิติสัปดาห์นี้</div><div class="stat-grid" id="statGrid"></div></div>
  <div class="card">
    <div class="card-title">ชั่วโมง Active มากสุด</div>
    <div class="heatmap-wrap" id="heatChart"></div>
    <div class="heatmap-labels"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:00</span></div>
  </div>
  <div class="card"><div class="card-title">Session History</div>
    <table><thead><tr><th>ห้อง</th><th>เข้า</th><th>ออก</th><th>นาน</th></tr></thead>
    <tbody id="sessBody"><tr><td colspan="4" class="empty">กำลังโหลด...</td></tr></tbody></table>
  </div>
</main>
<script>
const uid=location.pathname.split('/').pop();
async function load(){
  const r=await fetch('/api/profile/'+uid);const d=await r.json();
  document.getElementById('pageTitle').textContent=d.name;
  document.getElementById('memberName').textContent=d.name;
  document.getElementById('memberSub').textContent='UID: '+d.uid;
  document.getElementById('statGrid').innerHTML=[
    {val:d.total_duration,lbl:'เวลารวมสัปดาห์นี้'},
    {val:d.session_count,lbl:'Sessions ทั้งหมด'},
    {val:d.peak_hour!==null?String(d.peak_hour).padStart(2,'0')+':00':'-',lbl:'ชั่วโมง Active สุด'},
    {val:d.avg_duration||'-',lbl:'เฉลี่ยต่อ session'},
  ].map(s=>'<div class="stat-box"><div class="val">'+s.val+'</div><div class="lbl">'+s.lbl+'</div></div>').join('');
  const hc=d.hour_counts;const max=Math.max(...Object.values(hc).map(Number),1);
  const chart=document.getElementById('heatChart');chart.innerHTML='';
  for(let h=0;h<24;h++){const count=Number(hc[String(h)]||0);const pct=Math.round((count/max)*100);
    const bar=document.createElement('div');bar.className='heatmap-bar';
    bar.style.cssText='background:rgba(88,101,242,'+(0.15+(pct/100)*0.85).toFixed(2)+');height:'+Math.max(pct,2)+'%';
    bar.title=String(h).padStart(2,'0')+':00 — '+count+' sessions';chart.appendChild(bar);}
  const body=document.getElementById('sessBody');
  if(!d.sessions.length){body.innerHTML='<tr><td colspan="4" class="empty">ยังไม่มีข้อมูล</td></tr>';return;}
  body.innerHTML=d.sessions.map(s=>'<tr><td>'+s.channel+'</td><td style="color:var(--muted)">'+s.join+'</td><td style="color:var(--muted)">'+s.leave+'</td><td>'+s.duration+'</td></tr>').join('');
}
load();
</script>
</body></html>"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>VoiceLog Bot Dashboard</title>
<style>
  :root{--bg:#1e1f22;--surface:#2b2d31;--card:#313338;--border:#3f4147;
        --text:#dbdee1;--muted:#949ba4;--accent:#5865f2;--green:#23a559;--red:#da373c;--yellow:#f0b232;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',sans-serif;font-size:14px;}
  header{background:var(--surface);border-bottom:1px solid var(--border);
         padding:16px 24px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:10;}
  .logo{width:36px;height:36px;border-radius:50%;background:var(--accent);
        display:flex;align-items:center;justify-content:center;font-size:18px;}
  header h1{font-size:18px;font-weight:700;flex:1;}
  .status-dot{width:10px;height:10px;border-radius:50%;background:var(--red);transition:background .3s;}
  .status-dot.online{background:var(--green);}
  .status-label{font-size:12px;color:var(--muted);}
  main{max-width:960px;margin:0 auto;padding:24px 16px;display:grid;gap:16px;}
  .card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:20px;}
  .card-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);margin-bottom:14px;}
  .toggle-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:10px;}
  .toggle-item{display:flex;align-items:center;justify-content:space-between;
               background:var(--surface);border-radius:6px;padding:10px 12px;}
  .toggle-label{font-size:13px;}
  .switch{position:relative;width:36px;height:20px;flex-shrink:0;}
  .switch input{opacity:0;width:0;height:0;}
  .slider{position:absolute;inset:0;background:var(--border);border-radius:20px;cursor:pointer;transition:.2s;}
  .slider:before{content:'';position:absolute;width:14px;height:14px;left:3px;bottom:3px;background:white;border-radius:50%;transition:.2s;}
  input:checked+.slider{background:var(--accent);}
  input:checked+.slider:before{transform:translateX(16px);}
  .config-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:12px;}
  .config-item{display:flex;flex-direction:column;gap:6px;}
  .config-item label{font-size:12px;color:var(--muted);}
  .config-item input{background:var(--surface);border:1px solid var(--border);
    border-radius:6px;color:var(--text);padding:8px 10px;font-size:14px;width:100%;}
  .config-item input:focus{outline:none;border-color:var(--accent);}
  input[type=number]::-webkit-inner-spin-button{opacity:.5;}
  .btn-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;}
  .btn{padding:8px 16px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600;transition:filter .15s;}
  .btn:hover{filter:brightness(1.15);}
  .btn-primary{background:var(--accent);color:white;}
  .btn-success{background:var(--green);color:white;}
  .btn-warn{background:var(--yellow);color:#111;}
  .btn-danger{background:var(--red);color:white;}
  .action-grid{display:flex;flex-wrap:wrap;gap:10px;}
  .uptime-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:10px;}
  .uptime-box{background:var(--surface);border-radius:6px;padding:12px;display:flex;flex-direction:column;gap:4px;}
  .uptime-box .val{font-size:18px;font-weight:700;color:var(--accent);}
  .uptime-box .lbl{font-size:11px;color:var(--muted);}
  .stat-list{display:flex;flex-direction:column;gap:6px;}
  .stat-row{display:flex;align-items:center;background:var(--surface);border-radius:6px;padding:8px 12px;gap:8px;}
  .stat-rank{font-size:11px;color:var(--accent);min-width:22px;}
  .stat-name{flex:1;font-size:13px;}
  .stat-name a{color:inherit;text-decoration:none;}
  .stat-name a:hover{color:var(--accent);}
  .stat-time{font-size:12px;color:var(--muted);}
  .empty-msg{color:var(--muted);font-size:13px;}
  .heatmap-wrap{display:flex;align-items:flex-end;gap:3px;height:100px;}
  .heatmap-bar{flex:1;border-radius:3px 3px 0 0;min-height:2px;transition:height .3s;cursor:default;}
  .heatmap-labels{display:flex;justify-content:space-between;margin-top:4px;color:var(--muted);font-size:10px;}
  .history-wrap{overflow-x:auto;max-height:320px;overflow-y:auto;}
  table{width:100%;border-collapse:collapse;font-size:13px;}
  th{position:sticky;top:0;background:var(--card);color:var(--muted);text-align:left;
     padding:6px 10px;border-bottom:1px solid var(--border);font-weight:600;}
  td{padding:7px 10px;border-bottom:1px solid var(--border);}
  tr:last-child td{border-bottom:none;}
  tr:hover td{background:var(--surface);}
  .two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
  .toast{position:fixed;bottom:20px;right:20px;background:var(--green);color:white;
         padding:10px 18px;border-radius:8px;font-size:13px;
         opacity:0;transform:translateY(10px);transition:all .25s;pointer-events:none;z-index:100;}
  .toast.show{opacity:1;transform:translateY(0);}
  .toast.err{background:var(--red);}
  @media(max-width:640px){.two-col{grid-template-columns:1fr;}}
</style>
</head>
<body>
<header>
  <div class="logo">&#127908;</div>
  <h1>VoiceLog Bot</h1>
  <div class="status-dot" id="statusDot"></div>
  <span class="status-label" id="statusLabel">กำลังเชื่อมต่อ...</span>
  <a href="/logout" style="color:var(--muted);font-size:12px;text-decoration:none;margin-left:auto">ออกจากระบบ</a>
</header>
<main>
<div class="card">
  <div class="card-title">สถานะ Bot</div>
  <div class="uptime-grid">
    <div class="uptime-box"><div class="val" id="upVal">-</div><div class="lbl">Uptime</div></div>
    <div class="uptime-box"><div class="val" id="evJoin">0</div><div class="lbl">เข้าห้อง</div></div>
    <div class="uptime-box"><div class="val" id="evLeave">0</div><div class="lbl">ออกห้อง</div></div>
    <div class="uptime-box"><div class="val" id="evMute">0</div><div class="lbl">Mute</div></div>
    <div class="uptime-box"><div class="val" id="evDeaf">0</div><div class="lbl">Deaf</div></div>
    <div class="uptime-box"><div class="val" id="evStream">0</div><div class="lbl">Stream</div></div>
    <div class="uptime-box"><div class="val" id="evVideo">0</div><div class="lbl">กล้อง</div></div>
  </div>
</div>
<div class="card">
  <div class="card-title">การแจ้งเตือน</div>
  <div class="toggle-grid" id="toggleGrid"></div>
</div>
<div class="card">
  <div class="card-title">ส่งมุขและ Trivia</div>
  <div class="toggle-grid" style="margin-bottom:14px">
    <div class="toggle-item">
      <span class="toggle-label">เปิดใช้งาน</span>
      <label class="switch">
        <input type="checkbox" id="toggle_send_content" onchange="toggleConfig('send_content',this.checked)">
        <span class="slider"></span>
      </label>
    </div>
  </div>
  <div class="config-grid" id="numGrid"></div>
  <div class="btn-row"><button class="btn btn-primary" onclick="saveNums()">บันทึก</button></div>
</div>
<div class="card">
  <div class="card-title">Channel Routing — Channel IDs</div>
  <div class="config-grid">
    <div class="config-item"><label>Voice Events</label><input type="text" id="ch_voice" placeholder="Channel ID"></div>
    <div class="config-item"><label>มุขและ Trivia</label><input type="text" id="ch_content" placeholder="Channel ID"></div>
    <div class="config-item"><label>Stats (!rank, สรุป)</label><input type="text" id="ch_stats" placeholder="Channel ID"></div>
  </div>
  <div class="btn-row"><button class="btn btn-primary" onclick="saveChannels()">บันทึก</button></div>
</div>
<div class="card">
  <div class="card-title">การกระทำ</div>
  <div class="action-grid">
    <button class="btn btn-success" onclick="action('joke')">&#127917; ส่งมุขเทส</button>
    <button class="btn btn-success" onclick="action('trivia')">&#129300; ส่ง Trivia เทส</button>
    <button class="btn btn-primary" onclick="action('rank')">&#128200; ส่ง !rank ทันที</button>
    <button class="btn btn-warn"    onclick="action('summary')">&#128202; ส่งสรุปสัปดาห์</button>
  </div>
</div>
<div class="card">
  <div class="card-title">Voice Activity Heatmap — รายชั่วโมง</div>
  <div class="heatmap-wrap" id="heatmapChart"></div>
  <div class="heatmap-labels"><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:00</span></div>
</div>
<div class="two-col">
  <div class="card">
    <div class="card-title">ผู้ใช้ใน Voice ตอนนี้</div>
    <div class="stat-list" id="voiceList"><span class="empty-msg">ไม่มีใครอยู่</span></div>
  </div>
  <div class="card">
    <div class="card-title">สถิติสัปดาห์นี้ — คลิกชื่อดูโปรไฟล์</div>
    <div class="stat-list" id="statsList"><span class="empty-msg">ยังไม่มีข้อมูล</span></div>
  </div>
</div>
<div class="card">
  <div class="card-title">คะแนนมุข — 👍👎</div>
  <div id="votesList" style="display:grid;gap:6px"></div>
  <div class="btn-row"><button class="btn btn-danger" onclick="resetVotes()">รีเซ็ตคะแนนทั้งหมด</button></div>
</div>
<div class="card">
  <div class="card-title">Session History — ล่าสุด 50 รายการ</div>
  <div class="history-wrap">
    <table>
      <thead><tr><th>ชื่อ</th><th>ห้อง</th><th>เข้า</th><th>ออก</th><th>นาน</th></tr></thead>
      <tbody id="historyBody"><tr><td colspan="5" style="color:var(--muted)">ยังไม่มีข้อมูล</td></tr></tbody>
    </table>
  </div>
</div>
</main>
<div class="toast" id="toast"></div>
<script>
const TOGGLES=[
  {key:'announce_join',label:'เข้าห้อง'},{key:'announce_leave',label:'ออกห้อง'},
  {key:'announce_move',label:'ย้ายห้อง'},{key:'announce_mute',label:'ปิด/เปิดไมค์'},
  {key:'announce_deaf',label:'ปิด/เปิดหู'},{key:'announce_stream',label:'Stream'},
  {key:'announce_video',label:'กล้อง'},
];
const NUMBERS=[
  {key:'content_interval',label:'ส่งทุก (นาที)',min:5,max:240},
  {key:'joke_delay',label:'หน่วงมุข (วินาที)',min:0,max:60},
  {key:'trivia_delay',label:'หน่วง Trivia (วินาที)',min:0,max:60},
  {key:'mute_cooldown_sec',label:'Cooldown Mute (วิ)',min:0,max:30},
  {key:'summary_hour',label:'ส่งสรุป (ชั่วโมง)',min:0,max:23},
  {key:'joke_downvote_threshold',label:'👎 เพื่อกรองมุข',min:1,max:20},
];
function showToast(msg,err=false){
  const t=document.getElementById('toast');t.textContent=msg;
  t.className='toast show'+(err?' err':'');setTimeout(()=>t.className='toast',2200);
}
function buildUI(){
  document.getElementById('toggleGrid').innerHTML=TOGGLES.map(t=>`
    <div class="toggle-item"><span class="toggle-label">${t.label}</span>
    <label class="switch"><input type="checkbox" id="toggle_${t.key}" onchange="toggleConfig('${t.key}',this.checked)">
    <span class="slider"></span></label></div>`).join('');
  document.getElementById('numGrid').innerHTML=NUMBERS.map(n=>`
    <div class="config-item"><label>${n.label}</label>
    <input type="number" id="num_${n.key}" min="${n.min}" max="${n.max}" value="0"></div>`).join('');
}
function applyConfig(c){
  TOGGLES.forEach(t=>{const el=document.getElementById('toggle_'+t.key);if(el)el.checked=!!c[t.key];});
  const sc=document.getElementById('toggle_send_content');if(sc)sc.checked=!!c.send_content;
  NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)el.value=c[n.key]??0;});
  const cv=document.getElementById('ch_voice');const cc=document.getElementById('ch_content');const cs=document.getElementById('ch_stats');
  if(cv)cv.value=c.channel_voice||'';if(cc)cc.value=c.channel_content||'';if(cs)cs.value=c.channel_stats||'';
}
async function loadConfig(){const r=await fetch('/api/config');applyConfig(await r.json());}
async function toggleConfig(key,val){
  const p={};p[key]=val;
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  showToast('บันทึกแล้ว');
}
async function saveNums(){
  const p={};NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)p[n.key]=Number(el.value);});
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  showToast('บันทึกแล้ว');
}
async function saveChannels(){
  const p={channel_voice:document.getElementById('ch_voice').value.trim(),
           channel_content:document.getElementById('ch_content').value.trim(),
           channel_stats:document.getElementById('ch_stats').value.trim()};
  if(Object.values(p).some(v=>v&&isNaN(v))){showToast('Channel ID ต้องเป็นตัวเลข',true);return;}
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  showToast('บันทึก Channel Routing แล้ว');
}
async function action(type){
  const r=await fetch('/api/action/'+type,{method:'POST'});
  const d=await r.json();showToast(d.ok?'ส่งแล้ว!':'เกิดข้อผิดพลาด',!d.ok);
}
async function refreshStatus(){
  try{
    const r=await fetch('/api/status');const d=await r.json();
    document.getElementById('statusDot').className='status-dot'+(d.online?' online':'');
    document.getElementById('statusLabel').textContent=d.online?'ออนไลน์':'ออฟไลน์';
    document.getElementById('upVal').textContent=d.uptime||'-';
    document.getElementById('evJoin').textContent=d.event_counts.join||0;
    document.getElementById('evLeave').textContent=d.event_counts.leave||0;
    document.getElementById('evMute').textContent=d.event_counts.mute||0;
    document.getElementById('evDeaf').textContent=d.event_counts.deaf||0;
    document.getElementById('evStream').textContent=d.event_counts.stream||0;
    document.getElementById('evVideo').textContent=d.event_counts.video||0;
    const vl=document.getElementById('voiceList');
    vl.innerHTML=d.voice_users.length===0?'<span class="empty-msg">ไม่มีใครอยู่</span>'
      :d.voice_users.map(u=>'<div class="stat-row"><span class="stat-name">'+u.name+'</span><span class="stat-time">'+u.duration+'</span></div>').join('');
    const medals=['🥇','🥈','🥉'];const sl=document.getElementById('statsList');
    sl.innerHTML=d.weekly_stats.length===0?'<span class="empty-msg">ยังไม่มีข้อมูล</span>'
      :d.weekly_stats.map((s,i)=>'<div class="stat-row"><span class="stat-rank">'+(medals[i]||(i+1)+'.')+'</span>'
        +'<span class="stat-name"><a href="/profile/'+s.uid+'" target="_blank">'+s.name+'</a></span>'
        +'<span class="stat-time">'+s.time+'</span></div>').join('');
  }catch(e){document.getElementById('statusLabel').textContent='กำลังเชื่อมต่อ...';}
}
async function loadHeatmap(){
  const r=await fetch('/api/heatmap');const d=await r.json();
  const max=Math.max(...Object.values(d).map(Number),1);
  const chart=document.getElementById('heatmapChart');chart.innerHTML='';
  for(let h=0;h<24;h++){
    const count=Number(d[String(h)]||0);const pct=Math.round((count/max)*100);
    const bar=document.createElement('div');bar.className='heatmap-bar';
    bar.style.cssText='background:rgba(88,101,242,'+(0.15+(pct/100)*0.85).toFixed(2)+');height:'+Math.max(pct,2)+'%';
    bar.title=String(h).padStart(2,'0')+':00 — '+count+' joins';chart.appendChild(bar);}
}
async function loadHistory(){
  const r=await fetch('/api/history');const d=await r.json();
  const body=document.getElementById('historyBody');
  if(!d.length){body.innerHTML='<tr><td colspan="5" style="color:var(--muted);padding:12px">ยังไม่มีข้อมูล</td></tr>';return;}
  body.innerHTML=d.slice().reverse().slice(0,50).map(s=>
    '<tr><td>'+s.name+'</td><td style="color:var(--muted)">'+s.channel+'</td>'
    +'<td style="color:var(--muted)">'+s.join+'</td><td style="color:var(--muted)">'+s.leave+'</td>'
    +'<td>'+s.duration+'</td></tr>').join('');
}
async function loadVotes(){
  const r=await fetch('/api/votes');const d=await r.json();
  const el=document.getElementById('votesList');
  if(!d.length){el.innerHTML='<span class="empty-msg">ยังไม่มีคะแนน</span>';return;}
  el.innerHTML=d.slice(0,20).map(v=>
    '<div class="stat-row" style="gap:10px">'
    +'<span style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'+(v.filtered?';color:var(--red)':'')+'" title="'+v.joke+'">'+v.joke+'</span>'
    +'<span style="color:var(--green);font-size:13px;min-width:36px;text-align:right">👍 '+v.up+'</span>'
    +'<span style="color:var(--red);font-size:13px;min-width:36px;text-align:right">👎 '+v.down+'</span>'
    +(v.filtered?'<span style="font-size:11px;color:var(--red);min-width:40px">กรองแล้ว</span>':'<span style="min-width:40px"></span>')
    +'</div>').join('');
}
async function resetVotes(){
  if(!confirm('รีเซ็ตคะแนนมุขทั้งหมด?'))return;
  await fetch('/api/votes/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
  showToast('รีเซ็ตแล้ว');loadVotes();
}
buildUI();loadConfig();refreshStatus();loadHeatmap();loadHistory();loadVotes();
setInterval(refreshStatus,8000);setInterval(loadHeatmap,30000);setInterval(loadHistory,15000);setInterval(loadVotes,20000);
</script>
</body></html>"""

@flask_app.route('/')
@require_auth
def dashboard():
    return DASHBOARD_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}

@flask_app.route('/profile/<uid>')
@require_auth
def profile_page(uid):
    return PROFILE_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}

@flask_app.route('/api/status')
@require_auth
def api_status():
    online     = client.is_ready()
    uptime_sec = int((datetime.now(THAI_TZ) - start_time).total_seconds())
    voice_users = []
    for mid, (name, join_time, ch) in voice_join_times.items():
        elapsed = int((datetime.now(THAI_TZ) - join_time).total_seconds())
        voice_users.append({'name': name, 'duration': format_duration(elapsed), 'channel': ch})
    combined = {k: dict(v) for k, v in weekly_stats.items()}
    for mid, (name, join_time, _) in voice_join_times.items():
        elapsed = int((datetime.now(THAI_TZ) - join_time).total_seconds())
        key = str(mid)
        if key not in combined:
            combined[key] = {'name': name, 'seconds': 0}
        combined[key]['seconds'] += elapsed
    stats_sorted   = sorted(combined.items(), key=lambda x: x[1]['seconds'], reverse=True)
    weekly_display = [{'uid': k, 'name': v['name'], 'time': format_duration(v['seconds'])} for k, v in stats_sorted[:10]]
    return jsonify({'online': online, 'uptime': format_duration(uptime_sec),
                    'event_counts': event_counts, 'voice_users': voice_users, 'weekly_stats': weekly_display})

@flask_app.route('/api/config', methods=['GET'])
@require_auth
def api_config_get():
    return jsonify(bot_config)

@flask_app.route('/api/config', methods=['POST'])
@require_auth
def api_config_post():
    data = request.json or {}
    for key in bot_config:
        if key in data:
            if key.startswith('channel_') and data[key]:
                try:
                    bot_config[key] = int(data[key])
                except ValueError:
                    pass
            else:
                bot_config[key] = data[key]
    save_config()
    if 'content_interval' in data and send_content.is_running():
        send_content.change_interval(minutes=int(bot_config['content_interval']))
    return jsonify({'ok': True})

@flask_app.route('/api/heatmap')
@require_auth
def api_heatmap():
    return jsonify(hourly_activity)

@flask_app.route('/api/history')
@require_auth
def api_history():
    return jsonify(session_history[-50:])

@flask_app.route('/api/profile/<uid>')
@require_auth
def api_profile(uid):
    data    = weekly_stats.get(uid, {})
    name    = data.get('name', 'Unknown')
    seconds = data.get('seconds', 0)
    try:
        mid_int = int(uid)
        if mid_int in voice_join_times:
            _, jt, _ = voice_join_times[mid_int]
            seconds += int((datetime.now(THAI_TZ) - jt).total_seconds())
    except Exception:
        pass
    sessions    = [s for s in session_history if s.get('uid') == uid or s.get('name') == name]
    hour_counts = {}
    for s in sessions:
        try:
            h = str(int(s['join'].split(' ')[1].split(':')[0]))
            hour_counts[h] = hour_counts.get(h, 0) + 1
        except Exception:
            pass
    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None
    avg_sec   = (sum(s['seconds'] for s in sessions) // len(sessions)) if sessions else 0
    return jsonify({'uid': uid, 'name': name, 'total_seconds': seconds,
                    'total_duration': format_duration(seconds), 'session_count': len(sessions),
                    'avg_duration': format_duration(avg_sec) if avg_sec else '-',
                    'peak_hour': peak_hour,
                    'hour_counts': {str(h): hour_counts.get(str(h), 0) for h in range(24)},
                    'sessions': list(reversed(sessions[-20:]))})

@flask_app.route('/api/votes')
@require_auth
def api_votes():
    threshold = bot_config.get('joke_downvote_threshold', 3)
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
    joke_votes.clear()
    save_votes()
    return jsonify({'ok': True})

@flask_app.route('/api/action/joke', methods=['POST'])
@require_auth
def api_action_joke():
    if bot_loop:
        asyncio.run_coroutine_threadsafe(_test_joke(), bot_loop)
    return jsonify({'ok': True})

@flask_app.route('/api/action/trivia', methods=['POST'])
@require_auth
def api_action_trivia():
    if bot_loop:
        asyncio.run_coroutine_threadsafe(_test_trivia(), bot_loop)
    return jsonify({'ok': True})

@flask_app.route('/api/action/summary', methods=['POST'])
@require_auth
def api_action_summary():
    if bot_loop:
        asyncio.run_coroutine_threadsafe(send_weekly_summary(), bot_loop)
    return jsonify({'ok': True})

@flask_app.route('/api/action/rank', methods=['POST'])
@require_auth
def api_action_rank():
    if bot_loop:
        async def _do():
            ch = ch_stats()
            if ch:
                await send_leaderboard(ch)
        asyncio.run_coroutine_threadsafe(_do(), bot_loop)
    return jsonify({'ok': True})

async def _test_joke():
    channel = ch_content()
    if not channel:
        return
    jokes = load_jokes()
    if not jokes:
        await channel.send('ไม่มีมุขเลย — ถูกกรองออกหมดแล้ว!')
        return
    category, joke = random.choice(jokes)
    await send_joke_with_vote(channel, category, joke)

async def _test_trivia():
    channel     = ch_content()
    trivia_list = load_trivia()
    if not channel or not trivia_list:
        return
    item             = random.choice(trivia_list)
    question, answer = item.split('|', 1)
    await channel.send(f'ทดสอบความรู้: {question.strip()}')
    await asyncio.sleep(bot_config['trivia_delay'])
    await channel.send(f'เฉลย: {answer.strip()}')
# ===========================

# ===== Start =====
def run_discord():
    global bot_loop
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_until_complete(client.start(TOKEN))

def run_flask():
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    flask_app.run(host='0.0.0.0', port=DASHBOARD_PORT, debug=False, use_reloader=False)

log(f'Starting VoiceLog Bot on port {DASHBOARD_PORT}...')
bot_thread   = threading.Thread(target=run_discord, daemon=True)
flask_thread = threading.Thread(target=run_flask,   daemon=True)
bot_thread.start()
flask_thread.start()
threading.Event().wait()   # block main thread — ไม่มี pystray แล้ว
