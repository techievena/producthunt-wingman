
import asyncio
import sys
import os
from pathlib import Path

# Add server dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from linkedin_agent import LinkedInAgent
from config import config

async def check_login():
    agent = LinkedInAgent()
    try:
        await agent.start()
        
        print("🚀 Checking if logged into LinkedIn...")
        task = "Go to https://www.linkedin.com/feed/ and tell me if you see a LinkedIn feed with posts. Return 'LOGGED_IN' or 'NOT_LOGGED_IN'."
        
        result = await agent._run_agent(task, max_steps=5)
        print(f"\n📊 Result: {result}")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        await agent.stop()

if __name__ == "__main__":
    asyncio.run(check_login())
