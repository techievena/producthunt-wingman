# ProductHunt Wingman 🪃

> AI-native LinkedIn outreach agent for ProductHunt launches.  
> Powered by **browser-use** + **APScheduler** + **LLM personalization**.

## What it does

1. **Discovers** PH community members from the PH streak leaderboard and 23 PH-related LinkedIn groups
2. **Personalises** outreach messages per-prospect using LLM + profile context
3. **Schedules** connection requests across a 20-day window (D-20 → D-3) at 13/day
4. **Sends** connection requests via browser-use (a real Chrome session, no extension fingerprinting)
5. **Scans** for accepted connections every 45-90 minutes
6. **DMs** accepted connections with the personalised message on launch day

## Quick Start

1. **Setup**: Run the setup script to create a fresh virtual environment and install dependencies.
   ```bash
   cd server
   ./setup.sh
   ```
2. **Activate**:
   ```bash
   source .venv/bin/activate
   ```


### 2. Configure

```bash
cp .env.example .env
# Edit .env with your keys:
#   OPENAI_API_KEY      → for LLM personalization
#   LAUNCH_DATE         → your PH launch date (YYYY-MM-DD)
#   PH_LAUNCH_URL       → your product's PH URL
```

### 3. Run

Make sure the venv is active (step 1), then:

```bash
python main.py
```

Or without activating the venv:

```bash
# from the repo root
server/.venv/bin/python server/main.py

# or from inside server/
.venv/bin/python main.py
```

The dashboard opens at **http://localhost:3847**

First run: A browser window will open. **Log into LinkedIn manually.** The session is saved in `.browser_profile/` — you only do this once.

### 4. Start your campaign

From the dashboard:
1. Click **"Scrape PH"** → imports streak leaderboard users with LinkedIn profiles
2. Go to **Settings** → add your LinkedIn group URLs (PH-related groups you're in)
3. Click **"Run Enrichment"** → LLM generates personalized messages from profile data
4. Click **"Allocate Schedule"** → distributes prospects across your send window
5. Click **▶ Start Agent** → scheduler begins sending connections automatically

## Architecture

```
server/
├── main.py           ← Entry point (FastAPI + APScheduler + browser-use)
├── config.py         ← Environment config
├── db.py             ← SQLite (prospects, groups, config, activity log)
├── ph_scraper.py     ← PH leaderboard scraper + LinkedIn group ingestion
├── linkedin_agent.py ← browser-use LinkedIn automation
├── scheduler.py      ← Rate-limited scheduling engine
├── personalizer.py   ← LLM message generation
├── dashboard.py      ← FastAPI routes + templates
└── templates/        ← Jinja2 HTML dashboards
    ├── index.html
    ├── prospects.html
    └── config.html

openclaw/
└── SKILL.md          ← OpenClaw skill wrapper
```

## Rate Limits (LinkedIn Safety)

| Action | Limit | What Wingman does |
|---|---|---|
| Connection requests | ~100/week | Sends max 13–15/day |
| Send window | D-20 → D-3 | Stops 3 days before launch |
| DMs | No hard limit (1st-degree) | Sends after acceptance |
| Acceptance scanning | Human cadence | Randomized 45-90 min intervals |

## OpenClaw Integration

PH Wingman is fully compatible with **OpenClaw**. You can manage your entire launch campaign via voice or chat.

### Install the Skill
Copy `openclaw/SKILL.md` into your OpenClaw skills directory.

### Voice/Chat Commands
- *"Start my PH outreach"*
- *"Scrape ProductHunt streaks"*
- *"How many connections did wingman send today?"*
- *"Pause wingman"*
- *"Check my launch outreach status"*

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | ✅ Yes (or Anthropic) | For LLM personalization |
| `ANTHROPIC_API_KEY` | Alternative | Claude instead of GPT |
| `LAUNCH_DATE` | ✅ Yes | `YYYY-MM-DD` |
| `PH_LAUNCH_URL` | Recommended | Your product's PH launch URL |
| `DAILY_CONNECTION_BUDGET` | Optional | Default: 13 |
| `PORT` | Optional | Default: 3847 |

## Hackathon Demo Script

1. Open `http://localhost:3847`
2. Show the countdown banner (D-N days to launch)
3. Click **"Scrape PH"** → watch profiles populate in real-time
4. Go to Prospects → show profile and message data
5. Click Preview on a prospect's message → show AI-personalized DM
6. Show the scheduler timeline with daily allocation
7. Start the agent → demo 1 live connection request via browser-use
8. Show the acceptance scanner detecting a connection
9. Show the DM being prepared for launch day
