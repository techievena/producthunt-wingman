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
        {"id": "linkedin",     "name": "LinkedIn Groups",
         "desc": f"Scrape {len(config.LINKEDIN_GROUPS)} PH community groups",
         "status": "idle", "count": 0},
        {"id": "ph",          "name": "ProductHunt Streaks",
         "desc": "Extract LinkedIn URLs from top streak members",
         "status": "idle", "count": 0},
        {"id": "enrich",      "name": "Enrichment",
         "desc": "Extract rich profile data (headline, skills, posts)",
         "status": "idle", "count": 0},
         {"id": "personalize", "name": "Personalize",
         "desc": "LLM generates tailored outreach messages",
         "status": "idle", "count": 0},
         {"id": "schedule",    "name": "Schedule",
         "desc": "Allocate prospects across send window",
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

    # ── Phase 1: LinkedIn Groups ────────────────────────────────────────
    _scope["phases"][0]["status"] = "running"
    _log(f"→ Scraping {len(config.LINKEDIN_GROUPS)} LinkedIn groups...")
    total_li = 0
    if not _agent:
        _log("✗ LinkedIn agent not available — skipping")
        _scope["phases"][0]["status"] = "error"
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
        _scope["phases"][0]["count"] = total_li
        _scope["phases"][0]["status"] = "done"
        _log(f"✓ LinkedIn groups: {total_li} profiles added")

    # ── Phase 2: PH Streaks ─────────────────────────────────────────────
    _scope["phases"][1]["status"] = "running"
    _log("→ Scraping ProductHunt streak leaderboard...")
    try:
        from ph_scraper import ingest_ph_users_to_db
        count = await ingest_ph_users_to_db(max_users=1000)
        _scope["phases"][1]["count"] = count or 0
        _scope["phases"][1]["status"] = "done"
        _log(f"✓ PH Streaks: {count} profiles added")
    except Exception as e:
        _scope["phases"][1]["status"] = "error"
        _log(f"✗ PH Streaks failed: {e}")

    # ── Phase 3: Enrichment ─────────────────────────────────────────────
    _scope["phases"][2]["status"] = "running"
    _log("→ Enriching newly discovered profiles...")
    if not _agent:
        _log("✗ LinkedIn agent not available — skipping")
        _scope["phases"][2]["status"] = "error"
    else:
        all_prospects = await db.get_all_prospects(limit=10000)
        to_enrich = [
            p for p in all_prospects
            if p["status"] == "discovered" and not p.get("headline")
        ]
        if to_enrich:
            _log(f"  Enriching {len(to_enrich)} prospects...")
            enriched_count = 0
            for p in to_enrich:
                try:
                    data = await _agent.enrich_profile(p["linkedin_url"])
                    if data:
                        await db.upsert_prospect({**p, **data})
                        enriched_count += 1
                except Exception as e:
                    _log(f"  ✗ {p['linkedin_url']}: {e}")
            _scope["phases"][2]["count"] = enriched_count
            _log(f"✓ Enrichment: {enriched_count} profiles updated")
        else:
            _log("✓ No enrichment needed")
        _scope["phases"][2]["status"] = "done"

    # ── Phase 4: Personalize ────────────────────────────────────────────
    _scope["phases"][3]["status"] = "running"
    _log("→ Generating personalized outreach messages...")
    try:
        import personalizer
        all_prospects = await db.get_all_prospects(limit=10000)
        unpersonalized = [
            p for p in all_prospects
            if p["status"] == "discovered" and not p.get("outreach_message")
        ]
        if unpersonalized:
            _log(f"  Personalizing {len(unpersonalized)} prospects...")
            msg_count = await personalizer.personalize_batch(unpersonalized)
            _scope["phases"][3]["count"] = msg_count
            _log(f"✓ Personalized {msg_count} messages")
        else:
            _scope["phases"][3]["count"] = 0
            _log("✓ All prospects already have messages")
        _scope["phases"][3]["status"] = "done"
    except Exception as e:
        _scope["phases"][3]["status"] = "error"
        _log(f"✗ Personalization failed: {e}")

    # ── Phase 5: Schedule ───────────────────────────────────────────────
    _scope["phases"][4]["status"] = "running"
    _log("→ Allocating send schedule...")
    try:
        from scheduler import allocate_schedule
        scheduled = await allocate_schedule()
        _scope["phases"][4]["count"] = scheduled
        _scope["phases"][4]["status"] = "done"
        _log(f"✓ Scheduled {scheduled} prospects across send window")
    except Exception as e:
        _scope["phases"][4]["status"] = "error"
        _log(f"✗ Scheduling failed: {e}")

    # ── Activate scheduler ──────────────────────────────────────────────
    await db.upsert_config("scheduler_running", "true")
    await db.upsert_config("scanner_running", "true")
    _scope["scheduler_active"] = True
    stats = await db.get_pipeline_stats()
    _scope["total"] = stats.get("total", 0)
    _log(f"✓ Scheduler activated — {_scope['total']} total prospects in pipeline")
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
async def list_prospects(limit: int = 5000, offset: int = 0):
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


@app.get("/api/status")
async def api_status():
    stats = await db.get_pipeline_stats()
    scheduler_active = await db.get_config("scheduler_running") == "true"
    launch_date = await db.get_config("launch_date") or config.LAUNCH_DATE
    return {
        "status": "running" if scheduler_active else "idle",
        "scheduler_active": scheduler_active,
        "launch_date": launch_date,
        "stats": stats,
    }


@app.post("/api/pipeline/personalize")
async def api_personalize(background_tasks: BackgroundTasks):
    """Manually trigger personalization for all un-messaged discovered prospects."""
    async def _do():
        import personalizer
        all_prospects = await db.get_all_prospects(limit=10000)
        targets = [
            p for p in all_prospects
            if p["status"] == "discovered" and not p.get("outreach_message")
        ]
        if targets:
            await personalizer.personalize_batch(targets)
    background_tasks.add_task(_do)
    return {"status": "started"}


@app.post("/api/pipeline/allocate")
async def api_allocate():
    """Manually trigger schedule allocation."""
    from scheduler import allocate_schedule
    count = await allocate_schedule()
    return {"status": "ok", "scheduled": count}


@app.get("/api/prospects/{id}")
async def api_prospect_detail(id: int):
    """Fetch detailed data for a single prospect."""
    async with aiosqlite.connect(db.DB_PATH) as _db:
        _db.row_factory = aiosqlite.Row
        async with _db.execute("SELECT * FROM prospects WHERE id=?", (id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return {"error": "Prospect not found"}
            return dict(row)


@app.post("/api/prospects/{id}/update")
async def api_prospect_update(id: int, data: dict):
    """Update prospect fields (message, status, etc.)"""
    async with aiosqlite.connect(db.DB_PATH) as _db:
        _db.row_factory = aiosqlite.Row
        async with _db.execute("SELECT linkedin_url FROM prospects WHERE id=?", (id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return {"error": "Prospect not found"}
            url = row["linkedin_url"]

    # Use existing helper for status/timestamp updates
    if "status" in data:
        await db.update_prospect_status(url, data["status"])

    # For other fields, we need a manual update here as update_prospect_status is restricted
    update_fields = []
    vals = []
    allowed = ["outreach_message", "display_name", "headline", "location", "company", "priority"]
    for k in allowed:
        if k in data:
            update_fields.append(f"{k}=?")
            vals.append(data[k])

    if update_fields:
        vals.append(id)
        async with aiosqlite.connect(db.DB_PATH) as _db:
            await _db.execute(
                f"UPDATE prospects SET {', '.join(update_fields)}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                vals
            )
            await _db.commit()

    return {"status": "ok"}


@app.post("/api/scheduler/pause")
async def pause_scheduler():
    await db.upsert_config("scheduler_running", "false")
    _scope["scheduler_active"] = False
    return {"status": "paused"}
