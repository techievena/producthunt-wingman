"""
LinkedIn automation agent using browser-use v0.12.x.

Handles:
  - send_connection_request(linkedin_url)  → send a connection request
  - scan_accepted_connections(urls)         → check which prospects accepted
  - send_dm(linkedin_url, message)          → send a direct message
  - scrape_group_members(group_url)         → extract member profile URLs

Uses a persistent BrowserSession (keep_alive=True) so Chrome stays open
between tasks — the login session is maintained and per-call startup cost
is eliminated.
"""
import asyncio
import os
import signal
import subprocess
import random
import re
import json
from pathlib import Path
from typing import Optional

from rich import print as rprint

from config import config
import db

try:
    from browser_use import Agent
    from browser_use.browser.profile import BrowserProfile
    from browser_use.browser.session import BrowserSession
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False
    rprint("[yellow]⚠️ browser-use not installed. Run: pip install browser-use && playwright install chromium[/yellow]")

USER_DATA_DIR = str(Path(__file__).parent / ".browser_profile")


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
    raise RuntimeError(
        "No LLM API key found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY in server/.env"
    )


class LinkedInAgent:
    """
    Wrapper around browser-use Agent with a persistent BrowserSession.

    keep_alive=True keeps Chrome running between tasks so the LinkedIn login
    session is never lost. All _run_agent calls are serialized via _lock.
    """

    def __init__(self):
        if not BROWSER_USE_AVAILABLE:
            raise RuntimeError("browser-use library not installed")
        self._llm = _get_llm()
        self._session: Optional[BrowserSession] = None
        self._lock = asyncio.Lock()

    def _kill_orphaned_chrome(self):
        """Kill any Chrome processes still holding our user_data_dir."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", USER_DATA_DIR],
                capture_output=True, text=True
            )
            for pid_str in result.stdout.strip().splitlines():
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
        except Exception:
            pass

    async def start(self):
        """Create a persistent BrowserSession and optionally auto-login."""
        self._kill_orphaned_chrome()
        await asyncio.sleep(1)
        rprint("[blue]🌐 Starting browser-use LinkedIn agent...[/blue]")
        profile = BrowserProfile(
            headless=False,
            user_data_dir=USER_DATA_DIR,
            args=[
                "--no-first-run",
                "--disable-blink-features=AutomationControlled",
            ],
            viewport={"width": 1280, "height": 900},
        )
        self._session = BrowserSession(browser_profile=profile, keep_alive=True)
        await self._session.start()
        rprint("[green]✅ Browser session started (Chrome is alive between tasks)[/green]")

        if not self.is_linkedin_session_saved():
            rprint("[blue]🔐 No saved session — please log in...[/blue]")
            if not await self.login():
                raise RuntimeError("LinkedIn login failed — cannot proceed")
        else:
            rprint("[green]✅ LinkedIn session found — agent ready[/green]")
        self._session_verified = True

    def is_linkedin_session_saved(self) -> bool:
        profile_dir = Path(USER_DATA_DIR)
        for cookies_file in profile_dir.rglob("Cookies"):
            if cookies_file.stat().st_size > 0:
                return True
        return False

    async def stop(self):
        # Leave Chrome running — the persistent profile keeps the session alive for
        # the next start(). _kill_orphaned_chrome() will clean up on the next run.
        self._session = None
        rprint("[dim]LinkedIn agent stopped.[/dim]")

    async def login(self) -> bool:
        """Open LinkedIn login page and poll until the user logs in manually."""
        rprint("[blue]🔐 Opening LinkedIn login page — please log in in the browser window.[/blue]")
        try:
            page = await self._session.get_current_page()
            await page.goto("https://www.linkedin.com/login")
            rprint("[yellow]⏳ Waiting for you to log in... (up to 3 minutes)[/yellow]")
            for _ in range(180):
                await asyncio.sleep(1)
                url = await page.get_url()
                if url and ("linkedin.com/feed" in url or "/mynetwork" in url or "/messaging" in url):
                    rprint("[green]✅ LinkedIn login detected — session saved[/green]")
                    return True
            rprint("[red]❌ Timed out waiting for login[/red]")
            return False
        except Exception as e:
            rprint(f"[red]❌ Login wait failed: {e}[/red]")
            return False

    async def ensure_logged_in(self) -> bool:
        """Verify session is active; if not, prompt user to log in again."""
        if getattr(self, "_session_verified", False):
            return True

        rprint("[blue]🔍 Verifying LinkedIn session...[/blue]")
        try:
            page = await self._session.get_current_page()
            await page.goto("https://www.linkedin.com/feed/")
            await asyncio.sleep(3)
            url = await page.get_url()
            if url and "linkedin.com/feed" in url:
                rprint("[green]✅ Session verified[/green]")
                self._session_verified = True
                return True
        except Exception:
            pass

        success = await self.login()
        if success:
            self._session_verified = True
        return success

    async def _run_agent(self, task: str, max_steps: int = 15) -> str:
        """
        Run a browser-use Agent for one task, serialized via lock.
        Reuses the persistent BrowserSession — no new Chrome process per call.
        """
        async with self._lock:
            agent = Agent(
                task=task,
                llm=self._llm,
                browser_session=self._session,
                max_actions_per_step=5,
            )
            result = await agent.run(max_steps=max_steps)
            if hasattr(result, "final_result"):
                return result.final_result() or ""
            return str(result)

    # -----------------------------------------------------------------------
    # Public actions
    # -----------------------------------------------------------------------

    async def send_connection_request(self, linkedin_url: str) -> bool:
        """Send a connection request (no note). Returns True on success."""
        rprint(f"[blue]🔗 Connecting to:[/blue] {linkedin_url}")

        if not await self.ensure_logged_in():
            return False

        page = await self._session.get_current_page()
        await page.goto(linkedin_url)
        await asyncio.sleep(random.uniform(3, 8))

        task = """
You are already on a LinkedIn profile page.

Find the "Connect" button and click it.

If a dialog appears asking to add a note, click "Send without a note" or "Send now".
If the button says "Message" instead of "Connect", this person is already connected — return "ALREADY_CONNECTED".
If the button says "Follow" only (no Connect), try clicking the "More" dropdown to find Connect.
If you cannot connect (button not found, rate limited), return "FAILED".

Return "SUCCESS" if the connection request was sent, or describe the issue.
"""
        try:
            result = await self._run_agent(task, max_steps=10)
            result_upper = result.upper()
            if "SUCCESS" in result_upper:
                rprint("[green]  ✅ Connection sent[/green]")
                return True
            elif "ALREADY_CONNECTED" in result_upper:
                rprint("[yellow]  ↩️ Already connected[/yellow]")
                await db.update_prospect_status(
                    linkedin_url, "accepted",
                    extra={"accepted_at": "already_connected"}
                )
                return False
            else:
                rprint(f"[red]  ❌ Connect failed: {result[:100]}[/red]")
                return False
        except Exception as e:
            rprint(f"[red]  ❌ Agent error: {e}[/red]")
            return False

    async def scan_accepted_connections(self, sent_urls: list[str]) -> list[str]:
        """
        Visit the sent invitations page, read pending list,
        return URLs that are no longer pending (= accepted).
        """
        rprint("[blue]🔍 Scanning sent invitations page...[/blue]")
        if not await self.ensure_logged_in():
            return []

        page = await self._session.get_current_page()
        await page.goto("https://www.linkedin.com/mynetwork/invitation-manager/sent/")
        await asyncio.sleep(3)

        task = """
You are already on the LinkedIn sent invitations page.

List all the LinkedIn profile URLs visible in the pending sent invitations.
Scroll down to load more if there are more than what's visible.

Return a JSON array of the profile URLs (e.g., ["https://www.linkedin.com/in/johndoe", ...]).
If none are found, return an empty array [].
"""
        try:
            result = await self._run_agent(task, max_steps=12)
            match = re.search(r'\[.*?\]', result, re.DOTALL)
            if match:
                pending_urls = json.loads(match.group(0))
                pending_set = {u.split("?")[0].rstrip("/").lower() for u in pending_urls}
                accepted = [
                    u for u in sent_urls
                    if u.split("?")[0].rstrip("/").lower() not in pending_set
                ]
                rprint(f"[green]  ✅ {len(accepted)} accepted out of {len(sent_urls)} sent[/green]")
                return accepted
            else:
                rprint("[yellow]  ⚠️ Could not parse pending invitations list[/yellow]")
                return []
        except Exception as e:
            rprint(f"[red]  ❌ Scanner error: {e}[/red]")
            return []

    async def send_dm(self, linkedin_url: str, message: str) -> bool:
        """Send a DM to a 1st-degree connection. Returns True on success."""
        rprint(f"[blue]💬 Sending DM to:[/blue] {linkedin_url}")
        if not await self.ensure_logged_in():
            return False

        page = await self._session.get_current_page()
        await page.goto(linkedin_url)
        await asyncio.sleep(random.uniform(5, 15))

        task = f"""
You are already on a LinkedIn profile page.

Find the "Message" button and click it.

Once the message compose box opens, type the following message EXACTLY:

---
{message}
---

After typing, click the Send button.

Return "SUCCESS" if the message was sent, or describe any issue.
"""
        try:
            result = await self._run_agent(task, max_steps=12)
            if "SUCCESS" in result.upper():
                rprint("[green]  ✉️ DM sent[/green]")
                return True
            else:
                rprint(f"[red]  ❌ DM failed: {result[:100]}[/red]")
                return False
        except Exception as e:
            rprint(f"[red]  ❌ DM agent error: {e}[/red]")
            return False

    async def get_joined_groups(self) -> list[str]:
        """Return LinkedIn group URLs the current user has joined."""
        rprint("[blue]🔍 Fetching your LinkedIn groups...[/blue]")
        if not await self.ensure_logged_in():
            return []

        page = await self._session.get_current_page()
        await page.goto("https://www.linkedin.com/groups/")
        await asyncio.sleep(3)

        raw = await page.evaluate("""() => {
            const links = document.querySelectorAll('a[href*="/groups/"]');
            const urls = new Set();
            links.forEach(a => {
                const m = a.href.match(/linkedin\\.com\\/groups\\/(\\d+)/);
                if (m) urls.add('https://www.linkedin.com/groups/' + m[1] + '/');
            });
            return JSON.stringify([...urls]);
        }""")
        try:
            urls = json.loads(raw)
            rprint(f"[green]  ✅ Found {len(urls)} joined groups[/green]")
            return urls
        except Exception as e:
            rprint(f"[red]  ❌ get_joined_groups error: {e}[/red]")
            return []

    async def scrape_group_members(self, group_url: str) -> list[str]:
        """Scrape member profile URLs from a LinkedIn group. Returns list of URLs."""
        rprint(f"[blue]👥 Scraping group members:[/blue] {group_url}")
        if not await self.ensure_logged_in():
            return []

        page = await self._session.get_current_page()

        # Phase 1: use the LLM only to navigate to the /members/ page
        await page.goto(group_url)
        await asyncio.sleep(3)

        current_url = await page.get_url() or ""
        if "/members/" not in current_url:
            nav_task = """
You are on a LinkedIn group page.
Find and click the "Members" tab, "Show all members" link, or any link that leads to the full member list.
The URL should change to end in /members/.
Return "DONE" once you are on the members page, or "FAILED" if you cannot get there.
"""
            await self._run_agent(nav_task, max_steps=5)
            await asyncio.sleep(2)
            current_url = await page.get_url() or ""

        if "/members/" not in current_url:
            # Fall back to direct URL
            await page.goto(group_url.rstrip("/") + "/members/")
            await asyncio.sleep(3)
            current_url = await page.get_url() or ""

        if "/members/" not in current_url:
            rprint("[yellow]  ⚠️ Could not reach members page[/yellow]")
            return []

        # Phase 2: scroll directly via JS — no LLM involved
        rprint("[dim]  ↕️ Scrolling to load members...[/dim]")
        for i in range(15):
            await page.evaluate("() => window.scrollBy(0, 1200)")
            await asyncio.sleep(1.5)
            if i % 5 == 4:
                await asyncio.sleep(2)

        # Phase 3: extract all /in/ links directly from the DOM
        raw = await page.evaluate("""() => {
            const links = document.querySelectorAll('a[href*="/in/"]');
            const urls = new Set();
            links.forEach(a => {
                const href = a.href;
                if (href && href.includes('linkedin.com/in/')) urls.add(href);
            });
            return JSON.stringify([...urls]);
        }""")

        try:
            urls = json.loads(raw)
            clean_urls = list({
                u.split("?")[0].rstrip("/")
                for u in urls
                if "linkedin.com/in/" in u
            })
            rprint(f"[green]  ✅ Found {len(clean_urls)} member profiles[/green]")
            return clean_urls
        except Exception as e:
            rprint(f"[red]  ❌ Link extraction error: {e}[/red]")
            return []
