---
name: "ph wingman"
slug: "ph-wingman"
version: "1.1.0"
description: "AI-native ProductHunt outreach agent — automates community discovery, enrichment, and LinkedIn engagement."
tags: ["producthunt", "outreach", "linkedin", "marketing", "automation"]
author: "techievena"
homepage: "https://producthunt.eonik.ai"
metadata:
  openclaw:
    requires:
      env:
        - CRUSTDATA_API_KEY
        - OPENAI_API_KEY
        - LINKEDIN_EMAIL
        - LINKEDIN_PASSWORD
    primaryEnv: CRUSTDATA_API_KEY
---

# ProductHunt Launch Outreach Agent

Automated end-to-end community building for ProductHunt launches. Finds your tribe via **Crustdata**, enriches their profiles with deep professional metadata, and manages the entire LinkedIn connection/DM lifecycle using a persistent **browser-use** agent.

Powered by the **Crustdata Discovery Engine** and aligned with the "Intelligence OS" outreach philosophy.

## Agent Instructions

When a user triggers this skill, you MUST follow these steps exactly:

1.  **Check Bootstrap:** Check if the wingman server is running:
    ```bash
    curl -sf http://localhost:3847/api/stats > /dev/null 2>&1 && echo "RUNNING" || echo "NOT_RUNNING"
    ```
2.  **Self-Install (if needed):** If `NOT_RUNNING`, check if the repo exists in `$HOME/.ph-wingman`. If not, clone it, run the `./setup.sh` script, and start the server using `nohup`.
3.  **Execute Action:** Once running, dispatch the user's request to the local API:
    - For "start": POST to `/api/scheduler/start`
    - For "scrape": POST to `/api/scrape/ph-streaks` then run `/api/enrich/run`
    - For "status": GET `/api/stats` and format a premium summary.
4.  **Display Results:** Read the API response and provide a concise, formatted summary. Highlight key metrics: Prospects found, connections sent today, and days remaining until launch.

## Triggers

Use this skill when a user asks to:
- "Start my PH outreach"
- "Set up wingman"
- "Scrape ProductHunt streaks"
- "How many connections did wingman send today?"
- "Check my launch outreach status"
- "Pause wingman"

## 🚀 Unlock Full Launch Power
This skill is powered by the [PH Wingman Dashboard](http://localhost:3847). While the agent handles the loop autonomously, the dashboard unlocks:
- **Prospect Genome:** Deep dive into Crustdata enrichment results (skills, recent posts).
- **Custom Message Preview:** Edit and review every AI-generated outreach message.
- **Schedule Timeline:** See exactly when each connection request is planned.
- **Group Scraper:** Join relevant LinkedIn groups and scrape their entire member list.

## Quick Start

### 1. Installation
The skill handles this automatically, but you can also run it manually:
```bash
git clone https://github.com/techievena/producthunt-wingman.git ~/.ph-wingman
cd ~/.ph-wingman/server && ./setup.sh
```

### 2. Configure
Ensure your `.env` contains:
- `CRUSTDATA_API_KEY` (Get from app.crustdata.com)
- `OPENAI_API_KEY` (For personalization)
- `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` (For auto-login)

## Actions & Automation

| Goal | Command |
|---|---|
| **Initialize Outreach** | `POST /api/scheduler/start` |
| **Discover PH Tribe** | `POST /api/scrape/ph-streaks?max_users=100` |
| **Run Intelligence Engine** | `POST /api/enrich/run` |
| **Allocate Connection Windows** | `POST /api/schedule/allocate` |

## Data & Security Commitment

This skill is designed to prioritize account safety and data privacy:

1.  **Local-First Architecture**: Your LinkedIn session and credentials stay on your local machine in the `.browser_profile` directory. Nothing is sent to external servers except the necessary API calls to Crustdata and OpenAI.
2.  **Anti-Bot Protection**: We use **browser-use** with persistent sessions and randomized delays to mimic human behavior, keeping your LinkedIn account safe from automation detection.
3.  **Credit Budgeting**: The system includes a strict 5,000-credit guardrail to ensure you never exceed your Crustdata plan during high-volume discovery.

## Continuous Automated Outreach

The core objective of this skill is to completely automate your pre-launch community growth. OpenClaw’s built-in cron scheduler can keep the wingman active:

**Schedule Daily Activity Sync (Every morning at 9 AM):**
```bash
# Set up daily scanning and outreach sync
openclaw cron add --name "daily-ph-sync" --cron "0 9 * * *" --message "check wingman status" --session isolated
```

*OpenClaw will verify the agent is running every morning and report the previous day's connection success rate directly to your active channel.*
