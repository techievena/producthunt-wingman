"""
Scheduler for ProductHunt Wingman.

Handles:
1. Distributing prospects across the send window [D-20, D-3]
2. Daily budget enforcement (default 13/day)
3. Priority ordering (higher streak = earlier dates)
4. APScheduler jobs that run while the server is alive:
   - connection_sender_job  — sends today's connection requests (runs 9am-6pm)
   - acceptance_scanner_job — scans for accepted connections (every 45-90 min)
   - dm_sender_job          — sends DMs to newly accepted connections
   - enrichment_job         — enriches newly discovered prospects
   - group_scraper_job      — scrapes LinkedIn groups for new members (every 6h)
"""
import asyncio
import random
from datetime import date, datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from rich import print as rprint

import db
from config import config
from linkedin_agent import LinkedInAgent

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None
_agent: Optional[LinkedInAgent] = None


def _parse_date(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


async def allocate_schedule(force: bool = False) -> int:
    """
    Distribute all 'discovered' or unscheduled 'queued' prospects across
    the send window, respecting daily budget.

    Call this once after new prospects are ingested, or when launch date changes.
    Returns count of prospects scheduled.
    """
    launch_date_str = await db.get_config("launch_date") or config.LAUNCH_DATE
    daily_budget = int(await db.get_config("daily_budget") or config.DAILY_CONNECTION_BUDGET)

    try:
        launch_date = _parse_date(launch_date_str)
    except ValueError:
        rprint(f"[red]❌ Invalid launch_date: {launch_date_str}[/red]")
        return 0

    today = date.today()
    send_start = launch_date - timedelta(days=20)
    send_end   = launch_date - timedelta(days=3)   # Stop 3 days before launch

    if today > send_end:
        rprint("[yellow]⚠️ Send window has passed. No scheduling needed.[/yellow]")
        return 0

    # Only schedule from today (or start of window, whichever is later)
    window_start = max(today, send_start)
    days_remaining = (send_end - window_start).days + 1

    if days_remaining <= 0:
        rprint("[yellow]⚠️ No days remaining in send window.[/yellow]")
        return 0

    # Get unscheduled prospects (only those with outreach_message ready)
    all_prospects = await db.get_all_prospects(limit=2000)
    unscheduled = [
        p for p in all_prospects
        if p["status"] == "discovered" or (p["status"] == "queued" and not p["scheduled_date"] and force)
    ]

    if not unscheduled:
        rprint("[dim]No unscheduled prospects found.[/dim]")
        return 0

    # Sort by priority descending (high-streak PH users first)
    unscheduled.sort(key=lambda p: p.get("priority", 0), reverse=True)

    # Cap to what we can send in the window
    max_sendable = days_remaining * daily_budget
    to_schedule = unscheduled[:max_sendable]

    rprint(
        f"[blue]📅 Scheduling:[/blue] {len(to_schedule)} prospects over {days_remaining} days "
        f"({daily_budget}/day) | Window: {window_start} → {send_end}"
    )

    # Build a randomized daily allocation
    # Each day gets a budget drawn from [budget-3, budget+3] to look human
    day_allocations: list[tuple[date, int]] = []
    remaining_budget = len(to_schedule)
    cur_day = window_start
    while cur_day <= send_end and remaining_budget > 0:
        day_budget = min(
            random.randint(max(5, daily_budget - 3), daily_budget + 3),
            remaining_budget,
        )
        day_allocations.append((cur_day, day_budget))
        remaining_budget -= day_budget
        cur_day += timedelta(days=1)

    # Assign dates to prospects
    scheduled = 0
    idx = 0
    for (send_date, day_budget) in day_allocations:
        for _ in range(day_budget):
            if idx >= len(to_schedule):
                break
            p = to_schedule[idx]
            await db.update_prospect_status(
                p["linkedin_url"],
                "queued",
                extra={"scheduled_date": send_date.strftime("%Y-%m-%d")},
            )
            idx += 1
            scheduled += 1

    rprint(f"[bold green]✅ Scheduled {scheduled} prospects[/bold green]")
    return scheduled


async def run_connection_sender():
    """
    Send connection requests for prospects due today.
    Called by APScheduler every ~20 min during business hours.
    Enforces daily budget: if we've already hit today's budget, skip.
    """
    if not _agent:
        rprint("[yellow]⚠️ LinkedIn agent not initialized[/yellow]")
        return

    # Check if paused
    running = await db.get_config("scheduler_running")
    if running != "true":
        return

    daily_budget = int(await db.get_config("daily_budget") or config.DAILY_CONNECTION_BUDGET)

    # Efficient SQL count instead of loading all prospects
    sent_today = await db.get_sent_count_today()

    if sent_today >= daily_budget:
        rprint(f"[dim]📅 Daily budget hit ({sent_today}/{daily_budget}). Skipping.[/dim]")
        return

    due = await db.get_prospects_due_today()
    remaining_budget = daily_budget - sent_today
    to_send = due[:remaining_budget]

    if not to_send:
        today = date.today().strftime("%Y-%m-%d")
        rprint(f"[dim]📅 No prospects due today ({today}).[/dim]")
        return

    rprint(f"[blue]🔗 Sending {len(to_send)} connection requests...[/blue]")

    for prospect in to_send:
        url = prospect["linkedin_url"]
        try:
            await db.update_prospect_status(url, "sending")
            success = await _agent.send_connection_request(url)
            if success:
                await db.update_prospect_status(
                    url, "sent",
                    extra={"sent_at": datetime.utcnow().isoformat() + "Z"},
                )
                await db.log_action("connection_sent", "ok", linkedin_url=url)
                rprint(f"[green]✅ Connection sent:[/green] {url}")
            else:
                await db.update_prospect_status(url, "queued")  # retry tomorrow
                await db.log_action("connection_sent", "error", linkedin_url=url, detail="Send failed")
        except Exception as e:
            await db.update_prospect_status(url, "queued")
            await db.log_action("connection_sent", "error", linkedin_url=url, detail=str(e))
            rprint(f"[red]❌ Connection error:[/red] {url} — {e}")

        # Human-like random delay between sends
        delay = random.uniform(
            config.MIN_DELAY_BETWEEN_ACTIONS_SEC,
            config.MAX_DELAY_BETWEEN_ACTIONS_SEC,
        )
        rprint(f"[dim]  ⏳ Waiting {delay:.0f}s before next action[/dim]")
        await asyncio.sleep(delay)


async def run_acceptance_scanner():
    """
    Scan LinkedIn sent invitations to detect newly accepted connections.
    Called every 45-90 minutes by APScheduler.
    """
    if not _agent:
        return

    running = await db.get_config("scanner_running")
    if running != "true":
        return

    rprint("[blue]🔍 Scanning for accepted connections...[/blue]")
    sent_prospects = await db.get_sent_not_accepted()
    if not sent_prospects:
        rprint("[dim]No pending sent connections to check.[/dim]")
        return

    sent_urls = [p["linkedin_url"] for p in sent_prospects]

    try:
        accepted_urls = await _agent.scan_accepted_connections(sent_urls)
        for url in accepted_urls:
            await db.update_prospect_status(
                url, "accepted",
                extra={"accepted_at": datetime.utcnow().isoformat() + "Z"},
            )
            await db.log_action("connection_accepted", "ok", linkedin_url=url)
            rprint(f"[green]🎉 Connection accepted:[/green] {url}")
    except Exception as e:
        rprint(f"[red]❌ Scanner error:[/red] {e}")
        await db.log_action("scan_acceptances", "error", detail=str(e))


async def run_dm_sender():
    """
    Send DMs to all prospects who accepted the connection but haven't been messaged yet.
    Only sends on or after D-1 (one day before launch).
    """
    if not _agent:
        return

    # Check pause state
    running = await db.get_config("scheduler_running")
    if running != "true":
        return

    # Only send DMs on or after launch day
    launch_date_str = await db.get_config("launch_date") or config.LAUNCH_DATE
    try:
        launch_date = _parse_date(launch_date_str)
    except ValueError:
        return

    today = date.today()
    if today < launch_date - timedelta(days=1):
        # Before D-1, don't send DMs yet (save them for launch day)
        return

    accepted = await db.get_accepted_not_messaged()
    if not accepted:
        return

    rprint(f"[blue]💬 Sending {len(accepted)} DMs...[/blue]")

    for prospect in accepted:
        url = prospect["linkedin_url"]
        message = prospect.get("outreach_message")
        if not message:
            rprint(f"[yellow]  ⚠️ No message for {url}, skipping[/yellow]")
            continue

        try:
            await db.update_prospect_status(url, "messaging")
            success = await _agent.send_dm(url, message)
            if success:
                await db.update_prospect_status(
                    url, "messaged",
                    extra={"messaged_at": datetime.utcnow().isoformat() + "Z"},
                )
                await db.log_action("dm_sent", "ok", linkedin_url=url)
                rprint(f"[green]✉️ DM sent:[/green] {url}")
            else:
                await db.update_prospect_status(url, "accepted")
                await db.log_action("dm_sent", "error", linkedin_url=url)
        except Exception as e:
            await db.update_prospect_status(url, "accepted")
            await db.log_action("dm_sent", "error", linkedin_url=url, detail=str(e))
            rprint(f"[red]❌ DM error:[/red] {url} — {e}")

        delay = random.uniform(30, 90)
        await asyncio.sleep(delay)



async def run_personalize_and_schedule_job():
    """
    Pick up 'discovered' prospects that have no outreach message yet,
    generate personalized messages via LLM, then allocate them to the
    send schedule. Runs every 30 minutes.
    """
    running = await db.get_config("scheduler_running")
    if running != "true":
        return

    import personalizer
    all_prospects = await db.get_all_prospects(limit=10000)

    # 1. Enrich
    to_enrich = [
        p for p in all_prospects
        if p["status"] == "discovered" and not p.get("headline")
    ]
    if to_enrich:
        rprint(f"[blue]🧬 Auto-enriching {len(to_enrich)} prospects...[/blue]")
        for p in to_enrich:
            try:
                data = await _agent.enrich_profile(p["linkedin_url"])
                if data:
                    await db.upsert_prospect({**p, **data})
            except Exception:
                pass

    # 2. Personalize
    unpersonalized = [
        p for p in all_prospects
        if p["status"] == "discovered" and not p.get("outreach_message")
    ]
    if unpersonalized:
        rprint(f"[blue]✍️ Auto-personalizing {len(unpersonalized)} prospects...[/blue]")
        await personalizer.personalize_batch(unpersonalized)

    # 3. Schedule
    await allocate_schedule()




async def run_group_scraper_job():
    """
    Scrape member lists from active LinkedIn groups and ingest new members.
    Called every 6 hours.
    """
    if not _agent:
        return

    running = await db.get_config("scheduler_running")
    if running != "true":
        return

    groups = await db.get_active_groups()
    if not groups:
        return

    from ph_scraper import ingest_linkedin_urls

    for group in groups:
        url = group["url"]
        rprint(f"[blue]👥 Auto-scraping group:[/blue] {url}")
        try:
            member_urls = await _agent.scrape_group_members(url)
            added = await ingest_linkedin_urls(member_urls, source="linkedin_group")
            await db.mark_group_scraped(group["id"], member_count=len(member_urls))
            await db.log_action("group_auto_scraped", "ok", detail=f"{url} → {added} new profiles")
            rprint(f"[green]✅ Group scraped: {added} new profiles[/green]")
        except Exception as e:
            await db.log_action("group_auto_scraped", "error", detail=f"{url} → {e}")
            rprint(f"[red]❌ Group scrape error: {e}[/red]")

        # Delay between groups
        await asyncio.sleep(random.uniform(30, 60))


def init_scheduler(agent: LinkedInAgent) -> AsyncIOScheduler:
    """
    Initialize and return the APScheduler instance with all jobs configured.
    Call this once on server startup.
    """
    global _scheduler, _agent
    _agent = agent

    _scheduler = AsyncIOScheduler(timezone="UTC")

    # Connection sender: every 20 minutes between 9am-6pm IST (3:30am-12:30pm UTC)
    _scheduler.add_job(
        run_connection_sender,
        CronTrigger(minute="*/20", hour="3-12"),
        id="connection_sender",
        name="Send Connection Requests",
        max_instances=1,
        coalesce=True,
    )

    # Acceptance scanner: every 60 minutes (±15 min jitter)
    _scheduler.add_job(
        run_acceptance_scanner,
        IntervalTrigger(minutes=60, jitter=900),
        id="acceptance_scanner",
        name="Scan Acceptances",
        max_instances=1,
        coalesce=True,
    )

    # DM sender: every 30 minutes
    _scheduler.add_job(
        run_dm_sender,
        IntervalTrigger(minutes=30, jitter=300),
        id="dm_sender",
        name="Send DMs",
        max_instances=1,
        coalesce=True,
    )


    # LinkedIn group scraper: every 6 hours
    _scheduler.add_job(
        run_group_scraper_job,
        IntervalTrigger(hours=6, jitter=1800),
        id="group_scraper",
        name="Scrape LinkedIn Groups",
        max_instances=1,
        coalesce=True,
    )

    # Personalize + schedule: every 30 minutes (catches any newly discovered prospects)
    _scheduler.add_job(
        run_personalize_and_schedule_job,
        IntervalTrigger(minutes=30, jitter=120),
        id="personalize_schedule",
        name="Personalize & Schedule",
        max_instances=1,
        coalesce=True,
    )

    return _scheduler


def get_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler
