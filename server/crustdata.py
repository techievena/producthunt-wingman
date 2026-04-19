"""
Crustdata API client for ProductHunt Wingman.

Confirmed working endpoints (verified against live API):
  GET  /screener/person/enrich   → full profile from LinkedIn URL  (~1 credit)
  POST /screener/person/search   → find people by filters          (0.03/result)

Auth: "Authorization: Token <key>"

Filter notes (from live API testing):
  - Most filters: {"filter_type": "...", "type": "in", "value": [...]}
  - Boolean filters (POSTED_ON_LINKEDIN, RECENTLY_CHANGED_JOBS, IN_THE_NEWS):
    just {"filter_type": "..."} — no type or value fields allowed
  - KEYWORD filter: {"filter_type": "KEYWORD", "type": "in", "value": ["..."]}
    searches profile text/bio

Discovery strategy (all via person search):
  1. KEYWORD "Product Hunt" + POSTED_ON_LINKEDIN — PH community members who post
  2. KEYWORD "indie hacker" OR "maker" + POSTED_ON_LINKEDIN + small company
  3. Founders + RECENTLY_CHANGED_JOBS + small company — actively launching
  4. Founders + POSTED_ON_LINKEDIN + small company — active builders
"""
import httpx
import json
from typing import Optional
from rich import print as rprint

from config import config
import db

BASE_URL = "https://api.crustdata.com"


def _headers() -> dict:
    key = config.CRUSTDATA_API_KEY
    if not key:
        raise ValueError("CRUSTDATA_API_KEY not set. Add it to server/.env")
    return {
        "Authorization": f"Token {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def _check_budget(cost: int = 1) -> bool:
    try:
        current = int(await db.get_config("credits_used") or "0")
        if current + cost > 5000:
            rprint(f"[red]🚫 Credit budget exceeded ({current}/5000). Skipping.[/red]")
            return False
        return True
    except Exception:
        return True


async def _track_credits(endpoint: str, count: int = 1):
    try:
        current = int(await db.get_config("credits_used") or "0")
        await db.upsert_config("credits_used", str(current + count))
        rprint(f"[dim]💳 Crustdata: ~{count} credit(s) on {endpoint}. Total: {current+count}/5000[/dim]")
    except Exception:
        pass


def _extract_linkedin_url(obj: dict) -> str:
    return (
        obj.get("linkedin_flagship_url")
        or obj.get("linkedin_profile_url")
        or obj.get("linkedin_url")
        or ""
    )


# ---------------------------------------------------------------------------
# /screener/person/enrich  (~1 credit/person)
# ---------------------------------------------------------------------------

async def enrich_person(linkedin_url: str) -> Optional[dict]:
    if not await _check_budget(1):
        return None

    rprint(f"[blue]🔍 Enriching:[/blue] {linkedin_url}")
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                f"{BASE_URL}/screener/person/enrich",
                headers=_headers(),
                params={"linkedin_profile_url": linkedin_url},
            )
            resp.raise_for_status()
            data = resp.json()
            await _track_credits("/screener/person/enrich", 1)
            if isinstance(data, list) and data:
                return data[0]
            elif isinstance(data, dict):
                return data
            return None
        except httpx.HTTPStatusError as e:
            rprint(f"[red]❌ Enrich {e.response.status_code}:[/red] {e.response.text[:200]}")
            return None
        except Exception as e:
            rprint(f"[red]❌ Enrich error:[/red] {e}")
            return None


async def enrich_person_batch(linkedin_urls: list[str]) -> list[dict]:
    results = []
    for i, url in enumerate(linkedin_urls):
        rprint(f"[blue]🔍 Enriching [{i+1}/{len(linkedin_urls)}]:[/blue] {url}")
        person = await enrich_person(url)
        if person:
            results.append(person)
    return results


# ---------------------------------------------------------------------------
# /screener/person/search  (0.03 credits/result)
#
# Filter rules (verified against live API):
#   Regular filters:  {"filter_type": "X", "type": "in", "value": [...]}
#   Boolean filters:  {"filter_type": "X"}   ← no type or value
#     Boolean types: POSTED_ON_LINKEDIN, RECENTLY_CHANGED_JOBS, IN_THE_NEWS
# ---------------------------------------------------------------------------

async def search_people(filters: list[dict], limit: int = 25) -> list[dict]:
    if not await _check_budget(1):
        return []

    rprint(f"[blue]🔎 Person search:[/blue] {len(filters)} filter(s), limit={limit}")
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                f"{BASE_URL}/screener/person/search",
                headers=_headers(),
                json={"filters": filters, "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            profiles = data.get("profiles", [])
            cost = max(1, int(len(profiles) * 0.03 + 0.5))
            await _track_credits("/screener/person/search", cost)
            rprint(f"[green]✅ Found {len(profiles)} people[/green]")
            return profiles
        except httpx.HTTPStatusError as e:
            rprint(f"[red]❌ Person search {e.response.status_code}:[/red] {e.response.text[:300]}")
            return []
        except Exception as e:
            rprint(f"[red]❌ Person search error:[/red] {e}")
            return []


# ---------------------------------------------------------------------------
# Targeted PH community discovery via person search
# ---------------------------------------------------------------------------

# Filter sets ordered by signal quality
_PH_DISCOVERY_FILTER_SETS = [
    # 1. People who mention "Product Hunt" in their profile AND recently posted on LI
    #    → these are active PH community members, highest signal
    (
        "PH profile mention + active poster",
        [
            {"filter_type": "KEYWORD", "type": "in", "value": ["Product Hunt"]},
            {"filter_type": "POSTED_ON_LINKEDIN"},
        ],
        50,
    ),
    # 2. Indie hackers / makers / solopreneurs who recently posted
    (
        "Indie hackers + active on LinkedIn",
        [
            {"filter_type": "CURRENT_TITLE", "type": "in",
             "value": ["Indie Hacker", "Maker", "Solopreneur", "Solo Founder", "Bootstrapper"]},
            {"filter_type": "POSTED_ON_LINKEDIN"},
        ],
        50,
    ),
    # 3. Founders at tiny companies who recently changed jobs (actively launching)
    (
        "Founders recently changed jobs",
        [
            {"filter_type": "CURRENT_TITLE", "type": "in",
             "value": ["Founder", "Co-Founder", "CEO"]},
            {"filter_type": "RECENTLY_CHANGED_JOBS"},
            {"filter_type": "COMPANY_HEADCOUNT", "type": "in", "value": ["1-10"]},
        ],
        50,
    ),
    # 4. Founders at small companies who post on LinkedIn
    (
        "Founders at small companies + active on LinkedIn",
        [
            {"filter_type": "CURRENT_TITLE", "type": "in",
             "value": ["Founder", "Co-Founder", "CTO", "CEO"]},
            {"filter_type": "POSTED_ON_LINKEDIN"},
            {"filter_type": "COMPANY_HEADCOUNT", "type": "in", "value": ["1-10", "11-50"]},
        ],
        50,
    ),
    # 5. Product people at startups who post
    (
        "Product managers at startups + active on LinkedIn",
        [
            {"filter_type": "CURRENT_TITLE", "type": "in",
             "value": ["Head of Product", "Product Manager", "CPO", "VP Product"]},
            {"filter_type": "POSTED_ON_LINKEDIN"},
            {"filter_type": "COMPANY_HEADCOUNT", "type": "in", "value": ["1-10", "11-50"]},
        ],
        25,
    ),
    # 6. People in the news (launches, funding) + posting
    (
        "Startup founders in the news",
        [
            {"filter_type": "CURRENT_TITLE", "type": "in",
             "value": ["Founder", "Co-Founder", "CEO"]},
            {"filter_type": "IN_THE_NEWS"},
            {"filter_type": "COMPANY_HEADCOUNT", "type": "in", "value": ["1-10", "11-50"]},
        ],
        25,
    ),
]


async def discover_all_ph_prospects() -> list[dict]:
    """
    Discover PH community prospects via all working Crustdata person search filters.
    Returns deduplicated list with _discovery_source set on each profile.
    Estimated credit cost: ~3–5 credits total (0.03/result × ~100 results).
    """
    rprint("[bold cyan]🚀 Running Crustdata PH community discovery...[/bold cyan]")
    all_profiles: list[dict] = []
    seen: set[str] = set()

    for label, filters, limit in _PH_DISCOVERY_FILTER_SETS:
        rprint(f"[dim]  → {label}[/dim]")
        try:
            profiles = await search_people(filters, limit=limit)
            added = 0
            for p in profiles:
                url = _extract_linkedin_url(p)
                if url and url not in seen:
                    seen.add(url)
                    p["_discovery_source"] = label
                    all_profiles.append(p)
                    added += 1
            rprint(f"[dim]    +{added} new ({len(all_profiles)} total)[/dim]")
        except Exception as e:
            rprint(f"[yellow]⚠️ Filter set '{label}' failed: {e}[/yellow]")

    rprint(f"[bold green]📊 Discovery complete: {len(all_profiles)} unique prospects[/bold green]")
    return all_profiles


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------

def extract_profile_fields(enrichment_data: dict) -> dict:
    """
    Flatten a Crustdata /screener/person/enrich response into prospect fields.
    Extracts ALL useful fields for personalisation: skills, post snippet, summary.
    """
    name = enrichment_data.get("name", "")
    first_name = name.split()[0] if name else ""

    linkedin_url = (
        enrichment_data.get("linkedin_flagship_url")
        or enrichment_data.get("linkedin_profile_url", "")
    )

    employers = enrichment_data.get("all_employers", [])
    current_company = (
        employers[0] if isinstance(employers, list) and employers
        else enrichment_data.get("company", "")
    )

    skills = enrichment_data.get("skills", [])
    skills_str = ", ".join(skills[:6]) if isinstance(skills, list) else str(skills)[:100]

    # Pull most recent LinkedIn post text for the personalizer
    post_snippet = ""
    for posts_key in ("recent_posts", "posts", "linkedin_posts"):
        posts = enrichment_data.get(posts_key, [])
        if isinstance(posts, list) and posts:
            first = posts[0]
            if isinstance(first, dict):
                post_snippet = (first.get("text") or first.get("content", ""))[:250]
            elif isinstance(first, str):
                post_snippet = first[:250]
            if post_snippet:
                break

    return {
        "display_name":    name,
        "first_name":      first_name,
        "headline":        enrichment_data.get("headline", ""),
        "location":        enrichment_data.get("location", ""),
        "company":         current_company,
        "skills":          skills_str,
        "post_snippet":    post_snippet,
        "linkedin_url":    linkedin_url,
        "twitter_handle":  enrichment_data.get("twitter_handle", ""),
        "enrichment_data": json.dumps(enrichment_data),
    }


def extract_discovery_profile_fields(profile: dict) -> dict:
    """
    Flatten a /screener/person/search result into prospect fields.
    Preserves _discovery_source for prioritization and personalization hook selection.
    """
    name = profile.get("name", "") or profile.get("full_name", "")
    first_name = name.split()[0] if name else ""
    linkedin_url = _extract_linkedin_url(profile)
    source = profile.pop("_discovery_source", "crustdata_search")

    return {
        "display_name":  name,
        "first_name":    first_name,
        "headline":      profile.get("headline", "") or profile.get("default_position_title", ""),
        "location":      profile.get("location", ""),
        "company":       profile.get("company", "") or profile.get("default_position_company_name", ""),
        "linkedin_url":  linkedin_url,
        "source":        source,
    }
