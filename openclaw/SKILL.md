---
name: "ph wingman"
slug: "ph-wingman"
version: "1.3.0"
description: "AI-native ProductHunt outreach agent — automates community discovery and LinkedIn engagement."
tags: ["producthunt", "outreach", "linkedin", "marketing", "automation"]
author: "techievena"
homepage: "https://producthunt.eonik.ai"
metadata:
  openclaw:
    requires:
      env:
        - OPENAI_API_KEY
    primaryEnv: OPENAI_API_KEY
---

# ProductHunt Wingman: Autonomous Community Outreach

AI-native ProductHunt outreach agent. Automates community discovery from LinkedIn groups and PH streaks, hyper-personalizes DMs via LLM, and manages the entire outreach lifecycle on LinkedIn.

---

### 🛡️ Security & Privacy
- **Local-First Execution**: All code runs entirely on your local machine. No credentials or scraped data are ever sent to external servers (except to official APIs: LinkedIn, OpenAI).
- **Session-Based Auth**: **No LinkedIn password required.** The agent uses your local browser session. You log in once manually in the opened Chrome window, and the agent maintains the session in a persistent local profile.
- **Auditability**: All actions are logged to a local SQLite database (`wingman.db`) for your review.

### 📦 Setup & Prerequisites
1. **GitHub Repo**: `https://github.com/techievena/producthunt-wingman`
2. **Environment Variables**:
   - `OPENAI_API_KEY`: Required for message personalization.
   - `LAUNCH_DATE`: Your ProductHunt launch date (`YYYY-MM-DD`).

### 🛠️ Runtime Instructions
1. **Bootstrap**:
   - The agent checks if `http://localhost:3847/status` is reachable.
   - If not, it clones the repo to `$HOME/.ph-wingman` and runs `./setup.sh`.
   - The server starts locally via `./start.sh`.
2. **Initial Login**:
   - On first run, a Chrome window opens.
   - **Manually log in to LinkedIn** in this window.
   - Once the feed loads, the agent saves the session and proceeds autonomously.

### 🗣️ Voice/Chat Commands
- *"Start my PH outreach"* → Triggers discovery and enrichment.
- *"Scrape ProductHunt streaks"* → Ingests daily active users.
- *"How many connections did wingman send today?"* → Queries local DB for status.
- *"Check my launch status"* → Generates a campaign summary.

### 📅 Automatic Triggers
- **Daily Discovery**: Runs at 9 AM local time.
- **Outreach Loop**: Enforces connection budgets to protect your account.

---

### 🚀 Dashboard Features
The wingman also hosts a local dashboard at [http://localhost:3847](http://localhost:3847):
- **Prospect Genome:** Deep dive into each member's profile (headline, company, skills, recent posts).
- **Custom Message Preview:** Edit and review every AI-generated outreach message.
- **Schedule Timeline:** See exactly when each connection request is planned.
- **Group Scraper:** Join relevant LinkedIn groups and scrape their entire member list.
