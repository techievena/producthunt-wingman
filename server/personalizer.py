"""
LLM-powered message personalizer for ProductHunt Wingman.

Takes an enriched prospect record and generates a personalized outreach DM.
Uses ALL available Crustdata enrichment fields — headline, company, skills,
recent LinkedIn post snippet, PH streak, and discovery source — to craft
messages that feel genuinely hand-written.
"""
import json
from rich import print as rprint

from config import config
import db


def _get_llm():
    if config.OPENAI_API_KEY:
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model="gpt-4o-mini",
                api_key=config.OPENAI_API_KEY,
                temperature=0.7,
                max_tokens=300,
            )
        except ImportError:
            rprint("[yellow]langchain-openai not installed[/yellow]")

    if config.ANTHROPIC_API_KEY:
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model="claude-3-haiku-20240307",
                api_key=config.ANTHROPIC_API_KEY,
                temperature=0.7,
                max_tokens=300,
            )
        except ImportError:
            rprint("[yellow]langchain-anthropic not installed[/yellow]")

    return None


def _parse_enrichment(prospect: dict) -> dict:
    """
    Extract the raw enrichment JSON into a usable dict.
    Returns {} if not available.
    """
    raw = prospect.get("enrichment_data")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _build_context_block(prospect: dict) -> str:
    """
    Build a rich context block from all available enrichment fields.
    This goes into the LLM prompt so it can write genuinely specific messages.
    """
    enrichment = _parse_enrichment(prospect)
    lines = []

    name = prospect.get("display_name") or prospect.get("first_name", "")
    if name:
        lines.append(f"Name: {name}")

    headline = prospect.get("headline") or enrichment.get("headline", "")
    if headline:
        lines.append(f"Headline: {headline}")

    company = prospect.get("company") or enrichment.get("company", "")
    if not company:
        employers = enrichment.get("all_employers", [])
        company = employers[0] if isinstance(employers, list) and employers else ""
    if company:
        lines.append(f"Current company: {company}")

    location = prospect.get("location") or enrichment.get("location", "")
    if location:
        lines.append(f"Location: {location}")

    skills = prospect.get("skills") or enrichment.get("skills", "")
    if isinstance(skills, list):
        skills = ", ".join(skills[:6])
    if skills:
        lines.append(f"Skills: {skills}")

    streak = prospect.get("ph_streak_days", 0)
    if streak and int(streak) > 0:
        lines.append(f"Product Hunt streak: {streak} days")

    source = prospect.get("source", "")
    source_labels = {
        "ph_streak":              "Found on PH streak leaderboard",
        "ph_post_engager":        "Engaged with ProductHunt's LinkedIn posts",
        "ph_launch_post_author":  "Publicly posted about a PH launch on LinkedIn",
        "crustdata_search":       "Active maker/founder found via LinkedIn",
        "linkedin_group":         "Member of a PH-related LinkedIn group",
        "crustdata_discovery":    "Discovered via Crustdata",
    }
    source_desc = source_labels.get(source, "")
    if source_desc:
        lines.append(f"How we found them: {source_desc}")

    post_snippet = prospect.get("post_snippet") or enrichment.get("post_snippet", "")
    if not post_snippet:
        recent_posts = enrichment.get("recent_posts") or enrichment.get("posts", [])
        if isinstance(recent_posts, list) and recent_posts:
            first = recent_posts[0]
            if isinstance(first, dict):
                post_snippet = (first.get("text") or first.get("content", ""))[:250]
            elif isinstance(first, str):
                post_snippet = first[:250]
    if post_snippet:
        lines.append(f"Their most recent LinkedIn post: \"{post_snippet.strip()}\"")

    summary = enrichment.get("summary", "")
    if summary:
        lines.append(f"LinkedIn summary: {summary[:200]}")

    return "\n".join(lines) if lines else "No enrichment data available."


def _template_fallback(prospect: dict, launch_url: str, template: str) -> str:
    """
    Rule-based fallback when no LLM is available.
    Picks the most specific hook available from enrichment fields.
    """
    enrichment = _parse_enrichment(prospect)
    first_name = (
        prospect.get("first_name")
        or (prospect.get("display_name") or "").split()[0]
        or "there"
    )

    streak = int(prospect.get("ph_streak_days") or 0)
    source = prospect.get("source", "")
    headline = (prospect.get("headline") or enrichment.get("headline", "")).lower()
    company = prospect.get("company") or enrichment.get("company", "")
    post_snippet = prospect.get("post_snippet") or ""

    # Priority order: most specific → most generic
    if source == "ph_launch_post_author":
        hook = (
            "I saw you recently posted about Product Hunt — "
            "you clearly know the community and what it takes to get visibility on launch day."
        )
    elif source == "ph_post_engager":
        hook = (
            "I noticed you actively engage with Product Hunt content on LinkedIn — "
            "you're exactly the kind of person whose support means a lot on launch day."
        )
    elif streak and streak > 30:
        hook = (
            f"Your {streak}-day streak on Product Hunt puts you among the most dedicated "
            f"supporters in the community — that kind of consistency is rare and I respect it."
        )
    elif streak and streak > 5:
        hook = (
            f"Saw your {streak}-day streak on Product Hunt — "
            f"you're clearly someone who genuinely supports new products."
        )
    elif post_snippet:
        hook = f"I came across your recent LinkedIn post — {post_snippet[:120].strip()}..."
    elif company and ("found" in headline or "build" in headline or "maker" in headline):
        hook = (
            f"As a fellow builder{' at ' + company if company else ''}, "
            f"I know how much a strong launch day matters."
        )
    elif source == "linkedin_group":
        hook = (
            "We're in the same Product Hunt community group on LinkedIn, "
            "and I'd rather reach out directly than blast a post."
        )
    else:
        hook = (
            "You're part of the Product Hunt community, "
            "and your support would mean the world to an indie builder."
        )

    return template.format(
        first_name=first_name,
        personalization_hook=hook,
        launch_url=launch_url or "https://www.producthunt.com",
    )


async def generate_message(prospect: dict) -> str:
    """
    Generate a personalized outreach DM for this prospect.
    Uses LLM with full enrichment context; falls back to rule-based template.
    """
    launch_url = await db.get_config("ph_launch_url") or config.PH_LAUNCH_URL
    template = await db.get_config("message_template") or config.DEFAULT_MESSAGE_TEMPLATE

    first_name = (
        prospect.get("first_name")
        or (prospect.get("display_name") or "").split()[0]
        or "there"
    )

    context_block = _build_context_block(prospect)
    llm = _get_llm()

    if llm:
        prompt = f"""You are writing a warm, genuine LinkedIn DM for a Product Hunt launch.
The goal is to get an upvote. Write it like a real person reaching out — not a marketer.

Everything you know about the recipient:
{context_block}

Product Hunt launch URL: {launch_url}

Rules:
- Open with their first name ({first_name}) and a casual greeting
- One specific sentence that shows you actually know something about them (use the context above — their post, their role, their PH streak, how you found them)
- One sentence about the launch: "We just launched on Product Hunt today"
- A simple, non-pushy ask: upvote + the URL
- Warm close, ≤ 5 words
- Total: max 100 words
- No bold, no bullet points, no hashtags, no emojis (one is ok if natural)
- Sound like a human, not a template

Return ONLY the message text."""

        try:
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            message = response.content.strip()
            rprint(f"[green]✨ LLM personalized message for {first_name}[/green]")
            return message
        except Exception as e:
            rprint(f"[yellow]⚠️ LLM failed ({e}), falling back to template[/yellow]")

    return _template_fallback(prospect, launch_url, template)


async def personalize_batch(prospects: list[dict]) -> int:
    """
    Generate and store outreach messages for a list of prospects.
    Returns count of messages generated.
    """
    count = 0
    for p in prospects:
        message = await generate_message(p)
        await db.upsert_prospect({**p, "outreach_message": message})
        count += 1
    rprint(f"[bold green]✅ Personalized {count} messages[/bold green]")
    return count
