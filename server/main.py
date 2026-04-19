"""
ProductHunt Wingman — Main entry point.

Starts:
  1. Database (init schema + seed defaults)
  2. LinkedIn browser-use agent
  3. APScheduler (all background jobs)
  4. FastAPI server (dashboard + API)

Run with:
  python main.py

Or for development:
  uvicorn main:app --reload --port 3847
"""
import sys
import os
from contextlib import asynccontextmanager

import uvicorn
from rich import print as rprint
from rich.panel import Panel
from rich.console import Console

console = Console()

# Add server dir to path
sys.path.insert(0, os.path.dirname(__file__))

import db
from config import config
from dashboard import app, set_dependencies
from linkedin_agent import LinkedInAgent, BROWSER_USE_AVAILABLE
from scheduler import init_scheduler


@asynccontextmanager
async def lifespan(fastapi_app):
    """FastAPI lifespan: startup → yield → shutdown."""
    # ── Startup ────────────────────────────────────────────────────────────
    console.print(Panel.fit(
        "[bold cyan]🚀 ProductHunt Wingman[/bold cyan]\n"
        "[dim]AI-powered launch outreach agent[/dim]",
        border_style="cyan",
    ))

    # 1. Initialize database
    rprint("[blue]📦 Initializing database...[/blue]")
    await db.init_db()
    rprint("[green]✅ Database ready[/green]")

    # 2. Initialize LinkedIn agent
    agent = None
    if BROWSER_USE_AVAILABLE:
        try:
            agent = LinkedInAgent()
            await agent.start()
        except Exception as e:
            rprint(f"[yellow]⚠️ Browser agent init failed: {e}[/yellow]")
            rprint("[yellow]Running in scrape-only mode (no LinkedIn actions).[/yellow]")
            agent = None
    else:
        rprint(
            "[yellow]⚠️  browser-use not installed. "
            "LinkedIn automation disabled. Run: pip install browser-use && playwright install chromium[/yellow]"
        )

    # 3. Initialize and start scheduler
    scheduler = init_scheduler(agent)
    scheduler.start()
    rprint("[green]✅ Scheduler started[/green]")

    # 4. Inject dependencies into dashboard
    set_dependencies(scheduler, agent)

    # 5. Print dashboard URL
    rprint("")
    console.print(Panel.fit(
        f"[bold green]✅ Wingman is running![/bold green]\n\n"
        f"[cyan]Dashboard:[/cyan]  http://{config.HOST}:{config.PORT}\n"
        f"[cyan]Launch date:[/cyan] {config.LAUNCH_DATE}\n"
        f"[cyan]Daily budget:[/cyan] {config.DAILY_CONNECTION_BUDGET} connections/day",
        border_style="green",
    ))

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    rprint("[blue]👋 Shutting down...[/blue]")
    scheduler.shutdown(wait=False)
    if agent:
        await agent.stop()
    rprint("[green]Done.[/green]")


# Attach lifespan to FastAPI app
app.router.lifespan_context = lifespan


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info",
    )
