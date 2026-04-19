"""
ProductHunt scraper — persistent BrowserSession approach.

Step 1: Navigate to streak leaderboard, scroll via JS, extract user cards via JS.
Step 2: Visit each profile directly, extract LinkedIn URL via JS querySelector.

LLM is only used as a fallback if JS extraction yields nothing on the leaderboard.
"""
import asyncio
import re
import json
import os
import signal
import subprocess
from pathlib import Path

from rich import print as rprint

from config import config
import db

LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9\-_%]+/?")
PH_LEADERBOARD_URL = "https://www.producthunt.com/visit-streaks?ref=header_nav"
PH_BROWSER_PROFILE_DIR = str(Path(__file__).parent / ".ph_browser_profile")


def _get_llm():
    if config.OPENAI_API_KEY:
        from browser_use.llm.openai.chat import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", api_key=config.OPENAI_API_KEY, temperature=0)
    if config.ANTHROPIC_API_KEY:
        from browser_use.llm.anthropic.chat import ChatAnthropic
        return ChatAnthropic(
            model="claude-3-5-sonnet-20241022",
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0,
        )
    raise RuntimeError("Set OPENAI_API_KEY or ANTHROPIC_API_KEY in server/.env")


def _kill_orphaned_browser(profile_dir: str):
    try:
        result = subprocess.run(["pgrep", "-f", profile_dir], capture_output=True, text=True)
        for pid_str in result.stdout.strip().splitlines():
            try:
                os.kill(int(pid_str), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
    except Exception:
        pass


async def _make_session():
    from browser_use.browser.profile import BrowserProfile
    from browser_use.browser.session import BrowserSession

    _kill_orphaned_browser(PH_BROWSER_PROFILE_DIR)
    await asyncio.sleep(1)

    profile = BrowserProfile(
        headless=False,
        user_data_dir=PH_BROWSER_PROFILE_DIR,
        args=["--no-first-run", "--disable-blink-features=AutomationControlled"],
        viewport={"width": 1280, "height": 900},
    )
    session = BrowserSession(browser_profile=profile, keep_alive=True)
    await session.start()
    return session


async def scrape_streak_leaderboard(max_users: int = 40) -> list[dict]:
    """
    Scrape PH streak leaderboard and visit each profile to get LinkedIn URLs.
    Returns list of dicts with ph_username, display_name, streak_days, linkedin_url.
    """
    try:
        from browser_use import Agent
    except ImportError:
        rprint("[red]❌ browser-use not installed[/red]")
        return []

    llm = _get_llm()
    session = await _make_session()

    async def run_agent(task: str, max_steps: int = 5) -> str:
        """Navigate via Agent — the only stable way to drive browser-use navigation."""
        agent = Agent(task=task, llm=llm, browser_session=session, max_actions_per_step=3)
        res = await agent.run(max_steps=max_steps)
        return res.final_result() if hasattr(res, "final_result") else str(res)

    async def evaluate(js: str) -> str:
        page = await session.get_current_page()
        return await page.evaluate(js)

    # ── Step 1: Navigate to leaderboard via Agent, then extract via JS ────
    rprint("[bold blue]🚀 Scraping PH streak leaderboard...[/bold blue]")
    await run_agent(
        f"Go to {PH_LEADERBOARD_URL} and wait for the page to fully load. Return DONE.",
        max_steps=4,
    )
    await asyncio.sleep(2)

    # Scroll to load more entries — pure JS after Agent has navigated
    for i in range(12):
        await evaluate("() => window.scrollBy(0, 1200)")
        await asyncio.sleep(1.2)
        if i % 4 == 3:
            await asyncio.sleep(1.5)

    raw = await evaluate(f"""() => {{
        const seen = new Set();
        const users = [];
        document.querySelectorAll('a[href*="/@"]').forEach(a => {{
            const m = a.href.match(/producthunt\\.com\\/@([a-zA-Z0-9_-]+)/);
            if (!m) return;
            const username = m[1];
            if (seen.has(username)) return;
            seen.add(username);
            let el = a;
            let streak = 0;
            for (let i = 0; i < 6; i++) {{
                el = el.parentElement;
                if (!el) break;
                const sm = el.textContent.match(/(\\d+)\\s*day/i);
                if (sm) {{ streak = parseInt(sm[1]); break; }}
            }}
            const name = a.textContent.trim() || username;
            if (name && name.length < 80)
                users.push({{ ph_username: username, display_name: name, streak_days: streak }});
        }});
        return JSON.stringify(users.slice(0, {max_users}));
    }}""")

    users = []
    try:
        users = json.loads(raw or "[]")
    except Exception:
        pass

    # Fallback: LLM if JS got nothing
    if not users:
        rprint("[yellow]⚠️ JS extraction empty — falling back to LLM for leaderboard[/yellow]")
        try:
            raw2 = await run_agent(f"""
You are already on the ProductHunt streak leaderboard page.
Extract up to {max_users} user entries. For each find:
  - ph_username  (from the /@username URL)
  - display_name
  - streak_days  (the number before "day streak")
Return ONLY a JSON array, no other text.
""", max_steps=15)
            m = re.search(r'\[.*\]', raw2, re.DOTALL)
            if m:
                users = json.loads(m.group(0))
        except Exception as e:
            rprint(f"[red]❌ LLM leaderboard fallback failed: {e}[/red]")
            return []

    rprint(f"[green]✅ Found {len(users)} users on leaderboard[/green]")
    if not users:
        return []

    # ── Step 2: Visit each profile, extract LinkedIn via JS ───────────────
    rprint("[blue]🔗 Extracting LinkedIn URLs from profiles...[/blue]")
    enriched = []
    for i, user in enumerate(users):
        uname = user.get("ph_username", "")
        if not uname:
            continue
        profile_url = f"https://www.producthunt.com/@{uname}"
        rprint(f"[dim]  [{i+1}/{len(users)}] {profile_url}[/dim]")
        try:
            await run_agent(f"Go to {profile_url} and return DONE when loaded.", max_steps=3)

            li_raw = await evaluate("""() => {
                const a = document.querySelector('a[href*="linkedin.com/in/"]');
                return a ? a.href : null;
            }""")

            tw_raw = await evaluate("""() => {
                const a = document.querySelector('a[href*="twitter.com/"], a[href*="x.com/"]');
                if (!a) return null;
                const m = a.href.match(/(?:twitter|x)\\.com\\/([^/?]+)/);
                return m ? m[1] : null;
            }""")

            linkedin_url = None
            if li_raw and LINKEDIN_RE.match(li_raw):
                linkedin_url = li_raw.split("?")[0].rstrip("/")

            user["linkedin_url"] = linkedin_url
            user["twitter_handle"] = tw_raw or None

            if linkedin_url:
                rprint(f"[green]    ✅ {linkedin_url}[/green]")
            else:
                rprint(f"[dim]    – no LinkedIn[/dim]")

            enriched.append(user)
        except Exception as e:
            rprint(f"[yellow]  ⚠️ {uname}: {e}[/yellow]")
            continue

        await asyncio.sleep(1)

    with_li = [u for u in enriched if u.get("linkedin_url")]
    rprint(
        f"[bold green]📊 PH scrape complete:[/bold green] "
        f"{len(with_li)}/{len(enriched)} profiles have LinkedIn"
    )
    return enriched


async def ingest_ph_users_to_db(max_users: int = 40) -> int:
    """Scrape PH leaderboard and upsert results into the prospects table."""
    users = await scrape_streak_leaderboard(max_users=max_users)
    added = 0
    for user in users:
        if not user.get("linkedin_url"):
            continue
        await db.upsert_prospect({
            "source":         "ph_streak",
            "ph_username":    user["ph_username"],
            "linkedin_url":   user["linkedin_url"],
            "twitter_handle": user.get("twitter_handle"),
            "display_name":   user.get("display_name", ""),
            "ph_streak_days": user.get("streak_days", 0),
            "status":         "discovered",
            "priority":       min(int(user.get("streak_days") or 0), 100),
        })
        await db.log_action(
            "ph_scrape_ingested",
            linkedin_url=user["linkedin_url"],
            detail=f"@{user['ph_username']} streak={user.get('streak_days', 0)}",
        )
        added += 1

    rprint(f"[bold green]✅ Ingested {added} PH users into database[/bold green]")
    return added


async def ingest_linkedin_urls(urls: list[str], source: str = "manual") -> int:
    """Directly import a list of LinkedIn URLs."""
    added = 0
    for url in urls:
        clean = url.split("?")[0].rstrip("/")
        if "linkedin.com/in/" not in clean:
            continue
        await db.upsert_prospect({
            "source":       source,
            "linkedin_url": clean,
            "status":       "discovered",
            "priority":     0,
        })
        added += 1
    rprint(f"[green]✅ Ingested {added} LinkedIn URLs (source={source})[/green]")
    return added
