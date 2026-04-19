"""
FastAPI dashboard for ProductHunt Wingman.
Clean single-page UI: scope → discover → outreach.
"""
import re
import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, BackgroundTasks, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
from config import config

_scheduler = None
_agent = None

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="PH Wingman")
_static_dir = BASE_DIR / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


def set_dependencies(scheduler, agent):
    global _scheduler, _agent
    _scheduler = scheduler
    _agent = agent


# ---------------------------------------------------------------------------
# Scope pipeline state
# ---------------------------------------------------------------------------

_RICH_RE = re.compile(r'\[/?[^\]]+\]')

_scope = {
    "running": False,
    "phases": [
        {"id": "crustdata", "name": "Crustdata Search",
         "desc": "Find founders & makers via API filters",
         "status": "idle", "count": 0},
        {"id": "linkedin",  "name": "LinkedIn Groups",
         "desc": f"Scrape {len(config.LINKEDIN_GROUPS)} PH community groups",
         "status": "idle", "count": 0},
        {"id": "ph",        "name": "ProductHunt Streaks",
         "desc": "Extract LinkedIn URLs from top streak members",
         "status": "idle", "count": 0},
    ],
    "log": [],
    "scheduler_active": False,
    "total": 0,
}


def _log(msg: str):
    clean = _RICH_RE.sub("", msg).strip()
    if not clean:
        return
    print(clean)
    _scope["log"].append({"ts": datetime.now().strftime("%H:%M:%S"), "msg": clean})
    if len(_scope["log"]) > 300:
        _scope["log"] = _scope["log"][-300:]


async def _run_scope():
    global _scope
    _scope["running"] = True
    _scope["log"] = []
    _scope["scheduler_active"] = False
    for p in _scope["phases"]:
        p["status"] = "idle"
        p["count"] = 0

    # ── Phase 1: Crustdata ──────────────────────────────────────────────
    _scope["phases"][0]["status"] = "running"
    _log("→ Starting Crustdata discovery...")
    try:
        from scheduler import run_crustdata_discovery_job
        count = await run_crustdata_discovery_job()
        _scope["phases"][0]["count"] = count or 0
        _scope["phases"][0]["status"] = "done"
        _log(f"✓ Crustdata: {_scope['phases'][0]['count']} prospects added")
    except Exception as e:
        _scope["phases"][0]["status"] = "error"
        _log(f"✗ Crustdata failed: {e}")

    # ── Phase 2: LinkedIn Groups ────────────────────────────────────────
    _scope["phases"][1]["status"] = "running"
    _log(f"→ Scraping {len(config.LINKEDIN_GROUPS)} LinkedIn groups...")
    total_li = 0
    if not _agent:
        _log("✗ LinkedIn agent not available — skipping")
        _scope["phases"][1]["status"] = "error"
    else:
        from ph_scraper import ingest_linkedin_urls
        for group_url in config.LINKEDIN_GROUPS:
            _log(f"  {group_url}")
            try:
                urls = await _agent.scrape_group_members(group_url)
                added = await ingest_linkedin_urls(urls, source="linkedin_group")
                total_li += added
                _log(f"  + {added} new profiles")
            except Exception as e:
                _log(f"  ✗ {e}")
            await asyncio.sleep(2)
        _scope["phases"][1]["count"] = total_li
        _scope["phases"][1]["status"] = "done"
        _log(f"✓ LinkedIn groups: {total_li} profiles added")

    # ── Phase 3: PH Streaks ─────────────────────────────────────────────
    _scope["phases"][2]["status"] = "running"
    _log("→ Scraping ProductHunt streak leaderboard...")
    try:
        from ph_scraper import ingest_ph_users_to_db
        count = await ingest_ph_users_to_db(max_users=50)
        _scope["phases"][2]["count"] = count or 0
        _scope["phases"][2]["status"] = "done"
        _log(f"✓ PH Streaks: {count} profiles added")
    except Exception as e:
        _scope["phases"][2]["status"] = "error"
        _log(f"✗ PH Streaks failed: {e}")

    # ── Activate scheduler ──────────────────────────────────────────────
    await db.upsert_config("scheduler_running", "true")
    await db.upsert_config("scanner_running", "true")
    _scope["scheduler_active"] = True
    _scope["total"] = sum(p["count"] for p in _scope["phases"])
    _log(f"✓ Scheduler activated — {_scope['total']} total prospects queued for outreach")
    _scope["running"] = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    scheduler_active = await db.get_config("scheduler_running") or "false"
    _scope["scheduler_active"] = scheduler_active == "true"
    stats = await db.get_pipeline_stats()
    return templates.TemplateResponse(request, "index.html", {
        "scope": _scope,
        "stats": stats,
    })


@app.post("/api/scope/start")
async def start_scope(background_tasks: BackgroundTasks):
    if _scope["running"]:
        return JSONResponse({"error": "already running"}, status_code=409)
    background_tasks.add_task(_run_scope)
    return {"status": "started"}


@app.get("/api/scope/status")
async def scope_status():
    stats = await db.get_pipeline_stats()
    return {
        "running": _scope["running"],
        "phases": _scope["phases"],
        "log": _scope["log"][-80:],          # last 80 lines for the UI
        "scheduler_active": _scope["scheduler_active"],
        "total": _scope["total"],
        "stats": stats,
    }


@app.get("/api/prospects/list")
async def list_prospects(limit: int = 100, offset: int = 0):
    rows = await db.get_all_prospects(limit=limit, offset=offset)
    return {"prospects": rows, "count": len(rows)}


# Keep config page for settings
@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    launch_date   = await db.get_config("launch_date")   or config.LAUNCH_DATE
    daily_budget  = await db.get_config("daily_budget")  or str(config.DAILY_CONNECTION_BUDGET)
    ph_launch_url = await db.get_config("ph_launch_url") or config.PH_LAUNCH_URL
    message_template = await db.get_config("message_template") or config.DEFAULT_MESSAGE_TEMPLATE
    groups = await db.get_active_groups()
    return templates.TemplateResponse(request, "config.html", {
        "launch_date": launch_date,
        "daily_budget": daily_budget,
        "ph_launch_url": ph_launch_url,
        "message_template": message_template,
        "groups": groups,
    })


@app.post("/config/save")
async def save_config(
    launch_date: str = Form(...),
    daily_budget: str = Form(...),
    ph_launch_url: str = Form(...),
    message_template: str = Form(...),
):
    await db.upsert_config("launch_date", launch_date)
    await db.upsert_config("daily_budget", daily_budget)
    await db.upsert_config("ph_launch_url", ph_launch_url)
    await db.upsert_config("message_template", message_template)
    return RedirectResponse("/config?saved=1", status_code=303)


@app.post("/api/scheduler/pause")
async def pause_scheduler():
    await db.upsert_config("scheduler_running", "false")
    _scope["scheduler_active"] = False
    return {"status": "paused"}
