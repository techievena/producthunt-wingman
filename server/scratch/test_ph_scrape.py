
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ph_scraper import scrape_streak_leaderboard


async def test_ph_scrape():
    users = await scrape_streak_leaderboard(max_users=10)

    print(f"\n📊 Results: {len(users)} profiles scraped")
    print(f"  With LinkedIn: {sum(1 for u in users if u.get('linkedin_url'))}")
    print()
    for u in users:
        li = u.get("linkedin_url") or "—"
        tw = u.get("twitter_handle") or "—"
        print(f"  @{u['ph_username']} ({u.get('streak_days', 0)}d streak)")
        print(f"    LinkedIn: {li}")
        print(f"    Twitter:  {tw}")


if __name__ == "__main__":
    asyncio.run(test_ph_scrape())
