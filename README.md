# 🎙️ AjarnBot

**Discord bot สำหรับ log กิจกรรม Voice Channel พร้อม Web Dashboard พร้อม Analytics**  
Deploy บน [Railway](https://railway.app) — รันตลอด 24/7 ไม่ต้องเปิดคอมทิ้งไว้  
🌐 Dashboard: [ajarnbot.up.railway.app](https://ajarnbot.up.railway.app)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.3+-5865F2?style=flat&logo=discord&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0+-000000?style=flat&logo=flask&logoColor=white)
![Railway](https://img.shields.io/badge/Deploy-Railway-0B0D0E?style=flat&logo=railway&logoColor=white)
![Version](https://img.shields.io/badge/Version-2.7.0-58a6ff?style=flat)
![Tests](https://img.shields.io/badge/Tests-93%20passed-3fb950?style=flat)

---

## ✨ Features

### 🔊 Voice Channel Tracking
- แจ้งเตือนเมื่อมีคนเข้า / ออก / ย้ายห้อง Voice
- แจ้งเตือน mute, deaf, stream, กล้อง แยกต่างหาก
- ตรวจจับ **anti-spam**: เตือนเมื่อมีคนเข้า-ออกถี่เกิน 5 ครั้ง/นาที
- รองรับหลาย Discord Server พร้อมกัน (Multi-guild)

### 📊 Analytics & Stats
| Command | คำอธิบาย |
|---------|----------|
| `/rank` | อันดับ Voice สัปดาห์นี้ |
| `/rank วันนี้` | อันดับเฉพาะวันนี้ |
| `/rank สัปดาห์นี้` | อันดับ 7 วันล่าสุด |
| `/rank เดือนนี้` | อันดับเดือนนี้ |
| `/stats` | สถิติส่วนตัว (เวลาสะสม, streak, sessions) |
| `/compare @user` | เปรียบเทียบสถิติกับเพื่อน |
| `!rank [today\|week\|month]` | prefix command เดียวกัน |

### 🏅 Engagement Features
| Command | คำอธิบาย |
|---------|----------|
| `/help` | คำสั่งทั้งหมดของบอท |
| `/joke` | รับมุขสุ่ม พร้อม 👍👎 vote |
| `/trivia` | รับคำถาม มีเวลา 30 วินาทีตอบ |
| `/trivia-rank` | อันดับคะแนน Trivia |

- **Streak tracking** — นับ streak วันที่ active ต่อเนื่อง
- **Milestones** — แจ้งเตือนเมื่อถึงเป้าหมาย (1h, 10h, 100h, streak 7/30 วัน ฯลฯ)
- **Channel stats** — สถิติแยกตาม voice channel
- Welcome message สำหรับสมาชิกใหม่

### 🌐 Web Dashboard — Data Analytics
- **KPI Bar** — DAU วันนี้, ออนไลน์ตอนนี้, เฉลี่ย/session, sessions สัปดาห์นี้
- **DAU Trend** — กราฟ line chart 30 วัน + 7-day rolling average + WAU summary
- **7×24 Activity Pattern** — heatmap วันในสัปดาห์ × ชั่วโมง (Mon–Sun × 00:00–23:00)
- **Leaderboard** — เรียงได้ 4 แบบ (เวลา / sessions / streak / วัน active) × 4 period (7d/30d/90d/All)
- **Contribution Graph** — GitHub-style 1 ปีย้อนหลัง ต่อ user พร้อม badges (เวลาสะสม, streak, sessions)
- **Voice Activity Heatmap** — peak hour รายชั่วโมง 24h
- **Session Histogram** — การกระจายความยาว session (0-5m, 5-15m, 15-30m, 30-60m, 60m+)
- **Retention** — week-over-week retention chart
- **Inactive Users** — รายชื่อสมาชิกที่ไม่ active 14+ วัน พร้อม badge ระดับ
- **Channel Activity** — ranking channels ตามเวลาใช้งาน
- **Session History** — ล่าสุด 200 รายการ พร้อม live search filter
- **Member Profile** — หน้าโปรไฟล์ส่วนตัวพร้อม stat boxes, peak hour chart, channel breakdown
- **Export CSV** — ดาวน์โหลด session history เป็นไฟล์ CSV
- **Dark / Light mode** toggle + PWA support
- Log viewer แสดง bot log ล่าสุด 100 บรรทัด

### 🔒 Security & Auth — Multi-user

| Role | เงื่อนไข | สิทธิ์ |
|------|----------|--------|
| 👑 **Owner** | Discord ID อยู่ใน `OWNER_IDS` หรือ password login | ทุกอย่าง — global config, anti-spam, announcements, ทุก guild |
| 🛡️ **Guild Admin** | Discord login + มีสิทธิ์ ADMINISTRATOR/MANAGE_GUILD | channel routing ของ guild ตัวเองเท่านั้น |

- **Discord OAuth2** — ทางหลัก ทุกคนใช้ Discord account login ได้
- **Password fallback** — สำหรับ owner เท่านั้น (ตั้ง `DASHBOARD_PASSWORD`)
- **API Key** support — `X-API-Key` header สำหรับ external/programmatic access
- XSS protection — `escHTML()` ทุก user-controlled innerHTML
- CSRF state validation บน OAuth2 flow
- Rate limiting บน Discord commands (30 วินาที cooldown)

### ⚙️ System
- `/health` endpoint สำหรับ uptime monitoring (UptimeRobot, BetterStack)
- Outbound Webhook — ส่ง event join/leave/move ไปยัง external URL (n8n, Make, Zapier)
- Auto-purge session history เก่ากว่า 90 วัน ทุกวันจันทร์
- Daily digest สรุปสถิติไปยัง Discord ทุกเที่ยงคืน
- Bot status rotation ทุก 30 นาที (voice count / uptime / top user)
- Thread-safe file I/O (threading.Lock ทุก data structure)

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
| `OWNER_IDS` | แนะนำ | Discord User ID ของ owner คั่นด้วย `,` เช่น `123456,789012` |
| `DASHBOARD_PASSWORD` | ไม่บังคับ | Password emergency สำหรับ owner login โดยไม่ใช้ Discord |
| `DASHBOARD_API_KEY` | ไม่บังคับ | API Key สำหรับ external access ผ่าน `X-API-Key` header |
| `OUTBOUND_WEBHOOK_URL` | ไม่บังคับ | URL รับ event join/leave (n8n, Make ฯลฯ) — ต้องขึ้นต้นด้วย `https://` |

> **วิธีหา Discord User ID:** Discord Settings → Advanced → เปิด Developer Mode → คลิกขวาที่ชื่อตัวเอง → Copy User ID

### 4. เปิด Bot Intents + Public Bot

ไปที่ Discord Developer Portal → Bot:
- ✅ **Public Bot** — เปิด (สำคัญ! ถ้าปิดอยู่ คนอื่นจะ invite bot ไม่ได้เลย)
- ✅ Server Members Intent
- ✅ Message Content Intent
- ✅ Presence Intent

### 5. เชิญ Bot เข้า Server

ไปที่ OAuth2 → URL Generator:
- Scopes: `bot`, `applications.commands`
- Permissions: `Send Messages`, `Read Message History`, `Add Reactions`, `Connect`, `Speak`, `Manage Messages`

หรือกด **Invite Bot** จากหน้า login ของ dashboard โดยตรง

### 6. เพิ่ม Railway Volume (สำคัญ!)

เพื่อให้ข้อมูลไม่หายเมื่อ redeploy:  
Railway dashboard → service → **Volumes** → Add Volume → mount path = `/data`

---

## 📁 โครงสร้างไฟล์

```
AJARNBOT/
├── voice_bot.py              # Bot หลัก + Flask routes
├── templates/
│   ├── dashboard.html        # หน้า dashboard หลัก
│   ├── login.html            # หน้า login (Discord OAuth + password)
│   ├── select_server.html    # หน้าเลือก server
│   ├── no_bot.html           # หน้าชวน invite bot
│   └── profile.html          # หน้าโปรไฟล์ member
├── static/
│   ├── style.css             # CSS (dark/light mode, all components)
│   └── script.js             # JavaScript (charts, polling, analytics)
├── jokes.txt                 # ไฟล์มุข
├── trivia.txt                # ไฟล์คำถาม Trivia
├── requirements.txt
├── Procfile
├── .env.example
└── data/                     # runtime data (gitignored)
    ├── voice_stats.json
    ├── session_history.json
    ├── hourly_activity.json
    ├── daily_activity.json       # joins per day per guild
    ├── daily_unique.json         # unique UIDs per day per guild (DAU)
    ├── user_daily.json           # per-user analytics (streak, alltime, etc.)
    ├── channel_activity.json     # time per voice channel
    ├── joke_votes.json
    ├── trivia_scores.json
    ├── milestones.json
    ├── bot_config.json
    ├── guild_configs.json
    ├── event_counts.json
    └── active_voice_sessions.json
```

---

## 📡 API Endpoints

| Endpoint | Auth | คำอธิบาย |
|----------|------|----------|
| `GET /health` | ❌ | Bot health check สำหรับ uptime monitor |
| `GET /api/status` | ✅ | สถานะ bot, voice users, avg session, event counts |
| `GET /api/dau` | ✅ | Daily Active Users 30 วัน (`?guild_id=X&days=N`) |
| `GET /api/wau-mau` | ✅ | Weekly Active Users (`?guild_id=X&weeks=N`) |
| `GET /api/leaderboard` | ✅ | Leaderboard (`?guild_id=X&period=7d\|30d\|90d\|alltime&sort=time\|sessions\|streak\|days`) |
| `GET /api/retention` | ✅ | Week-over-week retention (`?guild_id=X&weeks=N`) |
| `GET /api/inactive` | ✅ | Inactive users (`?guild_id=X&days=N`) |
| `GET /api/dow-heatmap` | ✅ | 7×24 day-of-week × hour matrix |
| `GET /api/histogram` | ✅ | Session length distribution (5 buckets) |
| `GET /api/heatmap` | ✅ | Voice activity รายชั่วโมง 24h |
| `GET /api/history` | ✅ | Session history ล่าสุด |
| `GET /api/user-daily` | ✅ | Contribution graph data ต่อ user |
| `GET /api/profile/<uid>` | ✅ | Member profile (stats, channel breakdown, sessions) |
| `GET /api/channel-stats` | ✅ | Time per voice channel |
| `GET /api/channels` | ✅ | Text channels ใน guild |
| `GET /api/guilds` | ✅ | รายชื่อ Discord servers |
| `GET /api/my-guilds` | ✅ | Guilds ที่ user เป็น admin + bot อยู่ |
| `GET /api/export/csv` | ✅ | ดาวน์โหลด session history เป็น CSV |
| `GET /api/logs` | ✅ | Log ล่าสุด 100 บรรทัด |
| `GET /api/config` | ✅ | Global bot config |
| `POST /api/config` | 👑 | แก้ global config (owner only) |
| `GET /api/guild-config` | ✅ | Per-guild config |
| `POST /api/guild-config` | ✅ | แก้ per-guild config |
| `GET /api/votes` | ✅ | คะแนนมุข |
| `POST /api/votes/reset` | ✅ | รีเซ็ตคะแนน |
| `GET /api/trivia-scores` | ✅ | คะแนน Trivia |
| `GET /api/stats/<period>` | ✅ | Stats: today/week/month |
| `POST /api/action/joke` | ✅ | ส่งมุขทันที |
| `POST /api/action/trivia` | ✅ | ส่ง Trivia ทันที |
| `POST /api/action/rank` | ✅ | ส่ง leaderboard ทันที |
| `POST /api/action/summary` | ✅ | ส่งสรุปสัปดาห์ทันที |
| `POST /api/set-guild` | ✅ | สลับ guild ปัจจุบัน |
| `GET /invite` | ❌ | Redirect ไป Discord bot invite URL |

**Auth:** Login ผ่าน `/login` (Discord OAuth2) หรือส่ง header `X-API-Key: <your-key>`

---

## 📦 Dependencies

```
discord.py>=2.3.0
flask>=3.0.0
tzdata>=2024.1
```

ไม่มี dependency ภายนอกอื่นนอกจากนี้ — ใช้ Python stdlib ทั้งหมด

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

## 📋 Changelog

### v2.7.0 — Advanced Analytics Dashboard
> `ffa00a3` · 2026-05-16

**P1 — ข้อมูลหลัก**
- 📈 **WAU (Weekly Active Users)** — `/api/wau-mau` รวม unique users รายสัปดาห์จาก `daily_unique`; แสดงใน DAU summary bar
- 🟦 **7×24 Activity Pattern** — `/api/dow-heatmap` matrix วัน×ชั่วโมงจาก session history; card ใหม่ "Active Pattern"
- 📊 **Session Length Histogram** — `/api/histogram` แบ่ง session 5 bucket (0-5m, 5-15m, 15-30m, 30-60m, 60m+)

**P2 — UI Improvements**
- 🎯 **KPI Summary Bar** — 4 ตัวเลขบนสุด: DAU วันนี้ / ออนไลน์ตอนนี้ / เฉลี่ย/session / sessions สัปดาห์นี้
- 🔀 **Leaderboard Sort Tabs** — เรียงได้ 4 แบบ: เวลา / sessions / streak / วัน active (ส่ง `sort=` param)
- 〰️ **7-day Rolling Average** — เส้น dotted สีเขียวในกราฟ DAU

**P3 — Nice to Have**
- 🔍 **History Search** — live filter ใน session history (client-side ไม่ต้อง fetch ใหม่) แสดง 200 รายการ

---

### v2.6.0 — DAU Tracking & Analytics Endpoints
> `c56b329` · 2026-05-15

- 📊 **DAU tracking** — `daily_unique.json` เก็บ unique UIDs ต่อวันต่อ guild (ถูกต้องกว่าการนับ joins)
- 📈 **DAU SVG Chart** — line chart 30 วัน (DAU solid + Joins dashed) render ด้วย SVG ล้วน ไม่มี lib
- 🏆 **Leaderboard periods** — `/api/leaderboard?period=7d|30d|90d|alltime` fast path 7d จาก weekly_stats
- 🔄 **Retention chart** — week-over-week retention mini bar chart
- 😴 **Inactive users** — `/api/inactive` scan last_seen; badges 3 ระดับ (warn/danger/gone)

---

### v2.5.4 — Security Hardening & Analytics Enrichment
> `464fcea` · 2026-05-14

- 🔒 **XSS protection** — `escHTML()` ทุก `innerHTML` ที่รับ user-controlled data
- 🔒 **`response.ok` checks** — ทุก `fetch()` เช็ค status ก่อนใช้งาน
- ⏱️ **`debounce(fn, 300ms)`** — wrap `toggleConfig` ป้องกัน spam API call
- 👁️ **Visibility API** — `_poll()` หยุดเมื่อ tab ซ่อน ประหยัด request
- 📊 **Analytics enrichment** — `user_daily` เพิ่ม fields: `first_seen`, `last_seen`, `alltime_seconds`, `session_count`, `streak_max`, `channel_seconds`
- 📋 **Channel Activity card** — bar chart แสดง top channels
- 📥 **Export CSV** — `/api/export/csv` download session history
- 📱 **Mobile header** — ซ่อน clock บนมือถือ, cap guild switcher width

---

### v2.5.3 — Slash Commands: Help, Compare, Streak, Milestones
> `35c1989` · 2026-05-13

- ❓ **`/help`** — embed แสดงทุก command พร้อมคำอธิบาย
- ⚖️ **`/compare @user`** — เปรียบ Voice time / streak / sessions ระหว่าง 2 คน
- 🔥 **Streak tracking** — นับวันที่ active ต่อเนื่อง; `streak_max` เก็บสถิติสูงสุด
- 🏅 **Milestones system** — แจ้งเตือนช่อง voice เมื่อถึงเป้าหมาย (1h/10h/100h, streak 7/30/100 วัน)
- 📢 **`/channel-stats`** — สถิติแยกตาม voice channel (top 10 ตามเวลา)

---

### v2.5.2 — Slash Commands: Stats, Welcome, Daily Digest, CSV
> `36d4908` · 2026-05-12

- 📊 **`/stats`** — สถิติส่วนตัวของผู้ใช้ (เวลาสะสม, sessions, streak, อันดับ)
- 👋 **Welcome message** — DM สมาชิกใหม่ที่เข้า voice ครั้งแรก
- 📅 **Daily digest** — สรุปสถิติรายวันอัตโนมัติตามเวลาที่ตั้ง (`summary_hour`)
- 📥 **CSV Export API** — `/api/export/csv` พร้อม header ภาษาไทย

---

### v2.5.1 — Cross-guild Bug Fixes
> `ec6c62c` · 2026-05-11

- 🐛 **Cross-guild channel leak** — API endpoints ที่ขาด `guild_id` filter แสดงข้อมูล guild อื่น → เพิ่ม filter ครบทุก endpoint
- 🔄 **Guild switch reload** — `switchGuild()` reload ทุก panel รวมถึง heatmap, contrib graph
- 🎨 **Heatmap UX v2** — peak glow effect, hour labels, summary bar

---

### v2.5.0 — Multi-tenant System + Dashboard Redesign
> `17aa753` · 2026-05-10

**Multi-tenant**
- 🌐 Discord OAuth2 login สำหรับ guild admin ทุกคน
- 🔀 Guild switcher ใน sidebar
- 🔒 Per-guild data isolation — `require_guild_access()` ทุก endpoint
- 🧬 `get_gc()` inheritance — guild config → global fallback
- 📋 `/api/my-guilds` — ส่งคืนเฉพาะ guild ที่ user เป็น admin + bot อยู่

**Dashboard Redesign**
- 📊 GitHub-style contribution graph per user (53 สัปดาห์)
- 🎨 Heatmap color gradient + peak glow
- 🏷️ Badges ใน contrib graph (alltime time, streak, sessions)
- 🔒 Security: CSRF state validation, SSRF check, bounded params

---

### v2.4.0 — GitHub Contribution Graph + Avatars
> `0ff2b59` · 2026-05-01

- 📊 GitHub-style contribution graph per user
- 🖼️ Discord CDN avatars ใน voice live list
- 💾 `user_daily.json` — daily activity persistence ข้ามวัน
- 📈 `/api/user-daily` endpoint

---

### v2.3.3 — Design System (Phosphor Icons)
> Phosphor Bold SVG icons แทน emoji, touch targets 44px, loading states, tabular nums

---

### v2.3.2 — Fix Voice Session Duration After Restart
> `voice_join_times` persist ใน `active_voice_sessions.json` → ต่อเวลาจากเดิมหลัง redeploy

---

### v2.3.1 — Fix Data Loss on Redeploy
> `event_counts` persist ใน `event_counts.json` → counters ไม่ reset หลัง restart

---

### v2.3.0 — Dashboard Redesign (GitHub Dark + Sidebar)
> CSS custom properties, Geist font, fixed 220px sidebar, glassmorphism header, PWA

---

### v2.2.0 — Accessibility Round 2 (29 WCAG 2.1 AA fixes)
> Heading structure `<h2>`, landmarks, labels, live regions, touch targets, contrast

---

### v2.1.0 — Accessibility Round 1 (18 WCAG 2.1 AA fixes)
> Color contrast, focus indicators, screen reader, form labels, ARIA

---

### v2.0.5 — Security & Code Quality
> `hmac.compare_digest()`, specific exceptions, static files (CSS/JS แยกจาก Python)

---

### v2.0.2 — Auto-delete Messages + Emoji Strip
> Auto-delete joke/trivia messages 30s, strip emoji จาก trivia answers

---

### v2.0.0 — Public Multi-guild & Bot Invite
> `/invite` redirect, guild switcher ใน header, forced guild selection, no-bot page

---

### v1.x — Early Versions (v1.0–v1.8)

| Version | Highlight |
|---------|-----------|
| v1.8.0 | Fix action buttons, voice snapshot on ready, no-overlap jokes |
| v1.7.0 | Role-based access control, OWNER_IDS, require_owner decorator |
| v1.6.0 | Thread safety (threading.Lock), Flask templates, unit tests (29) |
| v1.5.0 | Discord OAuth2 login, per-guild channel config, admin filter |
| v1.4.0 | API Key auth, log viewer |
| v1.3.0 | /health endpoint, outbound webhook, auto-purge, dark mode |
| v1.2.0 | Multi-guild, anti-spam, time-range leaderboard, Trivia scoring, PWA |
| v1.1.0 | Slash commands, session auth, rate limiting, Railway Volume |
| v1.0.0 | Initial release — Voice tracking, leaderboard, jokes, trivia, dashboard |

---

## ⚠️ Known Issues

| ปัญหา | สาเหตุ | สถานะ |
|-------|--------|--------|
| Dashboard ไม่แสดงข้อมูล | `FLASK_SECRET` สุ่มใหม่ทุก deploy | ✅ แก้แล้ว — ตั้ง `FLASK_SECRET` env var |
| OAuth callback 403 | `urllib.request` ไม่ส่ง `User-Agent` | ✅ แก้แล้ว |
| OAuth เด้งกลับ login | SameSite cookie / session loss | ✅ แก้แล้ว |
| Race condition JSON corrupt | หลาย thread เขียนไฟล์พร้อมกัน | ✅ แก้แล้ว — `threading.Lock` |
| คนอื่น invite bot ไม่ได้ | **Public Bot** ปิดอยู่ | ✅ เปิด Public Bot ใน Developer Portal |
| weekly_stats clear ทุก guild | `weekly_stats.clear()` ลบทุก guild | ✅ แก้แล้ว (v2.5.0) |
| Dashboard แสดงข้อมูล server อื่น | ขาด `guild_id` filter | ✅ แก้แล้ว (v2.5.1) |
| DAU นับ joins แทน unique users | ใช้ `daily_activity` ผิด | ✅ แก้แล้ว — `daily_unique.json` (v2.6.0) |

---

## 🧪 Tests

```bash
python -m pytest tests/ -q
# 93 passed
```

Test coverage: config validation, anti-spam, Flask routes, data persistence, analytics endpoints

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

**AjarnBot v2.7.0** · Built with discord.py + Flask · Deployed on Railway

</div>
