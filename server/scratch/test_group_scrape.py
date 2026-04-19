
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from linkedin_agent import LinkedInAgent
from config import config


async def test_group_scrape():
    agent = LinkedInAgent()
    try:
        await agent.start()

        group_url = config.LINKEDIN_GROUPS[0]
        print(f"\n🚀 Scraping members from: {group_url}")
        members = await agent.scrape_group_members(group_url)

        print(f"\n📊 Results: {len(members)} unique profiles")
        for m in members[:5]:
            print(f"  {m}")

    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(test_group_scrape())
