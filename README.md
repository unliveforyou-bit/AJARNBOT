# 🎙️ AjarnBot

**Discord bot สำหรับ log กิจกรรม Voice Channel พร้อม Web Dashboard**  
Deploy บน [Railway](https://railway.app) — รันตลอด 24/7 ไม่ต้องเปิดคอมทิ้งไว้  
🌐 Dashboard: [ajarnbot.up.railway.app](https://ajarnbot.up.railway.app)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.3+-5865F2?style=flat&logo=discord&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0+-000000?style=flat&logo=flask&logoColor=white)
![Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?style=flat&logo=railway&logoColor=white)

---

## ✨ Features

### 🔊 Voice Channel Tracking
- แจ้งเตือนเมื่อมีคนเข้า / ออก / ย้ายห้อง Voice
- แจ้งเตือน mute, deaf, stream, กล้อง แยกต่างหาก
- ตรวจจับ **anti-spam**: เตือนเมื่อมีคนเข้า-ออกถี่เกิน 5 ครั้ง/นาที
- รองรับหลาย Discord Server พร้อมกัน (Multi-guild)

### 📊 Leaderboard & Stats
| Command | คำอธิบาย |
|---------|----------|
| `/rank` | อันดับ Voice สัปดาห์นี้ |
| `/rank วันนี้` | อันดับเฉพาะวันนี้ |
| `/rank สัปดาห์นี้` | อันดับ 7 วันล่าสุด |
| `/rank เดือนนี้` | อันดับเดือนนี้ |
| `!rank [today\|week\|month]` | prefix command เดียวกัน |

### 🎭 มุข & Trivia
| Command | คำอธิบาย |
|---------|----------|
| `/joke` | รับมุขสุ่ม พร้อม 👍👎 vote |
| `/trivia` | รับคำถาม มีเวลา 30 วินาทีตอบ |
| `/trivia-rank` | อันดับคะแนน Trivia |

- มุขที่โดน 👎 เกินกำหนด → ถูกกรองออกอัตโนมัติ
- ส่งมุข/Trivia อัตโนมัติทุก 30 นาที (ปรับได้)
- เพิ่ม/แก้มุขได้ที่ไฟล์ `jokes.txt` และ `trivia.txt`

### 🌐 Web Dashboard
- ดูสถานะ bot, uptime, event counts แบบ real-time
- ดู leaderboard, voice activity heatmap, session history
- ดู profile ส่วนตัวของแต่ละ member
- ตั้งค่า channel routing, toggle announcements ได้ทุก feature
- **Dark / Light mode** toggle (persist ใน localStorage)
- รองรับ **PWA** — กด "Add to Home Screen" บนมือถือได้
- Log viewer แสดง bot log ล่าสุด 100 บรรทัด (auto-refresh 30s)

### 🔒 Security & Auth — Multi-user

| Role | เงื่อนไข | สิทธิ์ |
|------|----------|--------|
| 👑 **Owner** | Discord ID อยู่ใน `OWNER_IDS` หรือ password login | ทุกอย่าง — global config, anti-spam, announcements, ทุก guild |
| 🛡️ **Guild Admin** | Discord login + มีสิทธิ์ ADMINISTRATOR/MANAGE_GUILD | channel routing ของ guild ตัวเองเท่านั้น |

- **Discord OAuth2** — ทางหลัก, ทุกคนใช้ Discord account login ได้
- **Password fallback** — สำหรับ owner เท่านั้น (ตั้ง `DASHBOARD_PASSWORD`)
- **API Key** support — `X-API-Key` header สำหรับ external/programmatic access
- Role badge แสดงใน header (👑 Owner / 🛡️ Guild Admin)
- Rate limiting บน Discord commands (30 วินาที cooldown)

### ⚙️ System
- `/health` endpoint สำหรับ uptime monitoring (UptimeRobot, BetterStack)
- Outbound Webhook — ส่ง event join/leave/move ไปยัง external URL (n8n, Make, Zapier)
- Auto-purge session history เก่ากว่า 90 วัน ทุกวันจันทร์
- Daily backup สรุปสถิติไปยัง Discord ทุกเที่ยงคืน
- Bot status rotation ทุก 30 นาที (voice count / uptime / top user)
- Graceful data save ทุกครั้งที่มีการเปลี่ยนแปลง

---

## 🚀 Deploy บน Railway

### 1. Fork หรือ Clone repo นี้

```bash
git clone https://github.com/unliveforyou-bit/AJARNBOT.git
cd AJARNBOT
```

### 2. สร้างโปรเจกต์บน Railway

1. ไปที่ [railway.app](https://railway.app) → New Project → GitHub Repository
2. เลือก repo นี้
3. Railway จะ detect `Procfile` และ deploy อัตโนมัติ

### 3. ตั้งค่า Environment Variables

ไปที่ **Service → Variables** แล้วเพิ่ม:

| Variable | จำเป็น | คำอธิบาย |
|----------|--------|----------|
| `DISCORD_TOKEN` | ✅ | Bot token จาก [Discord Developer Portal](https://discord.com/developers) |
| `VOICE_LOG_CHANNEL_ID` | ✅ | Channel ID สำหรับส่ง log |
| `FLASK_SECRET` | ✅ | Secret key สำหรับ Flask session (ใช้ค่า hex 32 ตัว fixed ไม่เปลี่ยน) |
| `DISCORD_CLIENT_ID` | แนะนำ | Application ID จาก Discord Developer Portal (สำหรับ OAuth login) |
| `DISCORD_CLIENT_SECRET` | แนะนำ | Client Secret จาก Discord Developer Portal |
| `DISCORD_REDIRECT_URI` | แนะนำ | `https://ajarnbot.up.railway.app/callback` |
| `OWNER_IDS` | แนะนำ | Discord User ID ของ owner คั่นด้วย `,` เช่น `123456,789012` — ได้รับสิทธิ์ full access |
| `DASHBOARD_PASSWORD` | ไม่บังคับ | Password emergency สำหรับ owner login โดยไม่ใช้ Discord |
| `DASHBOARD_API_KEY` | ไม่บังคับ | API Key สำหรับ external access ผ่าน `X-API-Key` header |
| `OUTBOUND_WEBHOOK_URL` | ไม่บังคับ | URL รับ event join/leave (n8n, Make ฯลฯ) |

> **วิธีหา Discord User ID:** Discord Settings → Advanced → เปิด Developer Mode → คลิกขวาที่ชื่อตัวเอง → Copy User ID

### 4. เปิด Bot Intents

ไปที่ Discord Developer Portal → Bot → เปิด:
- ✅ Server Members Intent
- ✅ Message Content Intent
- ✅ Presence Intent

### 5. เชิญ Bot เข้า Server

ไปที่ OAuth2 → URL Generator:
- Scopes: `bot`, `applications.commands`
- Permissions: `Send Messages`, `Read Message History`, `Add Reactions`, `Connect`, `Speak`

---

## 📁 โครงสร้างไฟล์

```
AJARNBOT/
├── voice_bot.py          # Bot หลัก + Flask routes (Python only)
├── templates/            # Flask HTML templates (Jinja2)
│   ├── dashboard.html    # หน้า dashboard หลัก
│   ├── login.html        # หน้า login (Discord OAuth + password)
│   ├── select_server.html # หน้าเลือก server (แสดงหลัง OAuth เสมอ)
│   ├── no_bot.html       # หน้าชวน invite bot (เมื่อ bot ยังไม่อยู่ใน server)
│   └── profile.html      # หน้าโปรไฟล์ member
├── jokes.txt             # ไฟล์มุข (แก้เพิ่มได้เลย)
├── trivia.txt            # ไฟล์คำถาม Trivia
├── requirements.txt      # Python dependencies
├── Procfile              # Railway start command
├── .env.example          # ตัวอย่าง environment variables
└── data/                 # ข้อมูล runtime (gitignored)
    ├── voice_stats.json
    ├── session_history.json
    ├── hourly_activity.json
    ├── joke_votes.json
    ├── trivia_scores.json
    ├── bot_config.json
    └── guild_configs.json  # Per-guild channel settings
```

---

## ✏️ แก้มุขและ Trivia

**jokes.txt** — บรรทัดละมุข จัดหมวดด้วย `# [ชื่อหมวด]`
```
# [มุขทั่วไป]
ทำไมโปรแกรมเมอร์ถึงชอบ dark mode? เพราะ light attracts bugs
# [มุขถามตอบ]
ทำไมปลาถึงไม่เล่น Facebook? เพราะกลัวติดแหอินเทอร์เน็ต
```
> มุขที่มี `?` จะแยกเป็น 2 ข้อความอัตโนมัติ (setup + punchline)

**trivia.txt** — รูปแบบ `คำถาม|คำตอบ`
```
เมืองหลวงของญี่ปุ่นคือที่ไหน|โตเกียว
Python ถูกสร้างโดยใคร|Guido van Rossum
```

แก้ไขได้โดยตรงบน GitHub → กดปุ่ม ✏️ → Commit → Railway deploy อัตโนมัติ

---

## 📡 API Endpoints

| Endpoint | Auth | คำอธิบาย |
|----------|------|----------|
| `GET /health` | ไม่ต้อง | Bot health check สำหรับ uptime monitor |
| `GET /api/status` | ✅ | สถานะ bot, voice users, leaderboard |
| `GET /api/logs` | ✅ | Log ล่าสุด 100 บรรทัด |
| `GET /api/heatmap` | ✅ | Voice activity รายชั่วโมง |
| `GET /api/history` | ✅ | Session history ล่าสุด |
| `GET /api/guilds` | ✅ | รายชื่อ Discord servers |
| `GET /api/stats/<period>` | ✅ | Stats ตาม period: today/week/month |
| `GET /api/trivia-scores` | ✅ | คะแนน Trivia แยกต่อ guild |
| `POST /api/action/joke` | ✅ | ส่งมุขทันที |
| `POST /api/action/trivia` | ✅ | ส่ง Trivia ทันที |
| `POST /api/action/rank` | ✅ | ส่ง leaderboard ทันที |
| `POST /api/set-guild` | ✅ | สลับ guild ปัจจุบันใน session (guild switcher) |
| `GET /invite` | ❌ | Redirect ไป Discord bot invite URL |

**Auth:** Login ผ่าน `/login` หรือส่ง header `X-API-Key: <your-key>`

---

## 📦 Dependencies

```
discord.py>=2.3.0
flask>=3.0.0
tzdata>=2024.1
```

ไม่มี dependency ภายนอกอื่นนอกจากนี้ — ใช้ Python stdlib ทั้งหมด

---

## 📋 Changelog

### v1.0.0 — Initial Release
> `33c04f5` · Railway-ready deployment

- Voice join/leave/move/mute/deaf/stream/video tracking
- Leaderboard (`!rank`) และสถิติรายสัปดาห์
- ระบบมุขพร้อม 👍👎 voting และ auto-filter
- Trivia ถาม-ตอบอัตโนมัติ
- Web dashboard (Flask) พร้อม heatmap, session history, profile
- Voice activity heatmap รายชั่วโมง
- Weekly summary อัตโนมัติ
- Channel routing ตั้งค่าได้
- Basic auth สำหรับ dashboard

### v1.1.0 — Cloud Features
> `fd66dfc` · Slash commands, Session auth, Rate limiting

- ✨ Slash commands: `/rank`, `/joke`, `/trivia`
- 🔒 Session-based login/logout แทน Basic auth
- ⏱️ Rate limiting บน commands (30s cooldown)
- 💾 Railway Volume support (`RAILWAY_VOLUME_MOUNT_PATH`)
- 📤 Daily backup สรุปสถิติไปยัง Discord ทุกเที่ยงคืน

### v1.2.0 — Multi-guild & Trivia Scoring
> `9f2aba1` · Multi-guild, Anti-spam, PWA

- 🌐 **Multi-guild support** — รองรับหลาย server พร้อมกัน
- 🚫 Anti-spam detection — เตือนเมื่อ join/leave ถี่เกินไป
- 📅 Time-range leaderboard — `/rank วันนี้/สัปดาห์/เดือน`
- 🏆 Trivia scoring system — ตอบถูก +1 คะแนน, `/trivia-rank`
- 🔄 Bot status rotation ทุก 30 นาที
- 📱 PWA support — Add to Home Screen บนมือถือได้

### v1.3.0 — Monitoring & Integrations
> `66edae2` · Health endpoint, Webhooks, Dark mode

- 💚 `/health` endpoint สำหรับ UptimeRobot / BetterStack
- 🔗 Outbound Webhook ส่ง event ไปยัง n8n, Make, Zapier
- 🗑️ Auto-purge sessions เก่ากว่า 90 วัน อัตโนมัติ
- 🌙 Dark / Light mode toggle บน dashboard

### v1.4.0 — API & Developer Tools
> `dba8f92` · API Key auth, Log viewer

- 🔑 **API Key authentication** — `X-API-Key` header สำหรับ external access
- 📋 **Log viewer** บน dashboard — ดู bot log ล่าสุด 100 บรรทัด real-time
- 🔍 `/api/apikey` endpoint ตรวจสอบสถานะ API key

### v1.5.0 — Multi-guild & Discord OAuth
> `dde0f72` · Discord OAuth2 login, Server selector, Per-guild config

- 🔐 **Discord OAuth2 login** — เข้าสู่ระบบด้วย Discord account (scopes: `identify guilds`)
- 🖥️ **Server selector page** — เลือก server ก่อนเข้า dashboard
- 🌐 **Per-guild channel config** — ตั้ง channel แยกต่อ server ผ่าน `guild_configs.json`
- 🔇 **Skip content เมื่อไม่มีคนใน voice** — บอทไม่ส่งมุข/trivia เมื่อห้องว่าง
- 🃏 **แยก toggle มุข/trivia** — เปิด/ปิดอิสระจากกันใน dashboard
- ⏰ **Real-time clock** และ anti-spam settings บน dashboard
- 🔒 `FLASK_SECRET` env var — session key คงที่ข้ามการ deploy
- 🌐 Domain เปลี่ยนเป็น `ajarnbot.up.railway.app`
- 📋 **Channel routing dropdown** — เลือก channel ชื่อจริงแทนพิมพ์ ID
- 🔐 **Admin-only server filter** — dropdown แสดงเฉพาะ server ที่มีสิทธิ์ Admin
- ➕ `/api/channels` endpoint — ดึง text channels จาก bot

### v1.6.0 — Code Quality (Gemini Review)
> `21c3e7f` · Thread safety, Templates, Logging

- 🔒 **Thread safety** — เพิ่ม `threading.Lock()` ทุก file write operation ป้องกัน race condition
- 📁 **Flask Templates** — แยก HTML ออกจาก Python เป็น `templates/*.html` (Jinja2)
- ⚠️ **Startup validation** — แจ้งเตือนทันทีถ้าไม่ตั้งค่า `FLASK_SECRET`
- 🐛 **Fix silent exceptions** — `except: pass` → `except as e: log(...)` ทุกจุด
- 🧪 **Unit Tests** — 29 tests สำหรับ `format_duration`, `get_stats_for_period`, `register_joke_msg`
- 📦 `bot_utils.py` — แยก pure functions ออกจาก Discord/Flask dependencies

### v1.7.0 — Multi-user Access Control
> `a32b032` · Role-based access, OWNER_IDS, Permission enforcement

- 👑 **Role system** — Owner vs Guild Admin สิทธิ์แยกกันชัดเจน
- 🆔 **`OWNER_IDS` env var** — ระบุ Discord User ID ของ owner (full access)
- 🔐 **`require_owner` decorator** — global config API ถูก block สำหรับ non-owner
- 🛡️ **Guild permission check** — `/api/guild-config` POST ตรวจ ADMINISTRATOR/MANAGE_GUILD
- 🏷️ **Role badge** ใน header — แสดง 👑 Owner หรือ 🛡️ Guild Admin
- 👁️ **Owner-only UI sections** — การแจ้งเตือน, มุข/Trivia, Anti-Spam ซ่อนสำหรับ guild admin
- 🔑 Password login จำกัดเฉพาะ owner (ซ่อน form ถ้าไม่ตั้ง `DASHBOARD_PASSWORD`)

### v1.8.0 — Bug Fixes & Voice Improvements
> `db21650` · Action buttons, Voice snapshot, No-overlap jokes

- 🐛 **Fix action buttons** — `_test_joke()` / `_test_trivia()` / `api_action_rank` เรียก `ch_content()` / `ch_stats()` ที่ถูกลบไปแล้ว → เปลี่ยนเป็น `get_guild_ch(guild_id, type)` พร้อมส่ง `guild_id` จาก dashboard
- 📸 **Voice snapshot on ready** — `on_ready` scan ทุก voice channel ทุก guild เพื่อ populate `voice_join_times` สำหรับคนที่นั่งอยู่ก่อน bot restart
- 🚫 **No-overlap jokes/trivia** — เพิ่ม `active_joke_channels` set ป้องกันส่ง joke/trivia ซ้อนกันใน channel เดียวกัน (`try/finally` ป้องกัน lock ค้าง)
- 🎙️ **Voice list UI** — แสดง `# ชื่อห้อง` badge ต่อ user + section ลำดับห้องยอดนิยมตามจำนวนคน (computed client-side)

### v2.0.0 — Public Multi-guild & App Version
> `278a662` · Invite link, Guild switcher, Forced guild selection, Version footer

- 🌐 **Bot invite link** — `GET /invite` redirect ไป Discord OAuth2 bot invite URL พร้อม permission ครบ
- 🔄 **Dashboard guild switcher** — dropdown ใน header เปลี่ยน server ได้ทันทีโดยไม่ reload หน้า (ใช้ `POST /api/set-guild`)
- ➕ **"+ เพิ่ม Server" button** — ปุ่ม invite ใน dashboard header และ select_server page
- 🔒 **Forced guild selection** — OAuth callback selects always ไป `/select-server` (ไม่ข้ามถ้า guild เดียว) — filter เฉพาะ guild ที่ user เป็น admin + bot อยู่
- 🚫 **No-bot page** — `/no-bot` หน้าใหม่พร้อม step-by-step invite guide เมื่อ user login แต่ bot ยังไม่อยู่ใน server ใดเลย
- 🏷️ **App version footer** — แสดง version + build date ที่ล่างสุดของ dashboard (ดึงจาก `/api/config`)

---

## ⚠️ Known Issues / ปัญหาที่พบ

| ปัญหา | สาเหตุ | สถานะ |
|-------|--------|--------|
| Dashboard ไม่แสดงข้อมูล | `FLASK_SECRET` สุ่มใหม่ทุก deploy → session invalid | ✅ แก้แล้ว (ใช้ env var) |
| `DISCORD_CLIENT_ID` ผิด | Railway ใส่ค่าเป็น `Client ID` ตัวอักษรแทน ID จริง | ✅ แก้แล้ว |
| OAuth callback 403 Forbidden | `urllib.request` ไม่ส่ง `User-Agent` → Discord block | ✅ แก้แล้ว |
| OAuth เด้งกลับ login | State mismatch เพราะ SameSite cookie / session loss | ✅ แก้แล้ว (SESSION_COOKIE_SAMESITE=Lax) |
| Race condition JSON corrupt | หลาย thread เขียนไฟล์พร้อมกัน | ✅ แก้แล้ว (threading.Lock) |
| OAuth DISCORD_CLIENT_SECRET | ยังไม่ได้ verify ว่าตรงกับ Developer Portal | 🔄 ตรวจสอบ |

---

## 🤝 Contributing

1. Fork repo นี้
2. สร้าง branch ใหม่: `git checkout -b feature/your-feature`
3. Commit: `git commit -m "feat: add your feature"`
4. Push: `git push origin feature/your-feature`
5. เปิด Pull Request

---

## 📄 License

MIT License — ใช้ได้เสรี ดัดแปลงได้ แต่ขอให้ credit ด้วย

---

<div align="center">
Made with ❤️ · Deployed on Railway · Built with discord.py + Flask
</div>
