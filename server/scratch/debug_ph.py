
import asyncio
from playwright.async_api import async_playwright

async def debug_ph():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        url = "https://www.producthunt.com/leaderboards/streaks"
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        
        # Take screenshot to see what's happening
        await page.screenshot(path="ph_debug.png")
        print("Screenshot saved to ph_debug.png")
        
        # Check for profile links
        links = await page.eval_on_selector_all("a[href^='/@']", "els => els.map(el => el.href)")
        print(f"Found {len(links)} profile links.")
        if links:
            print("First 5 links:", links[:5])
        
        # Print some text to see if we are on a login page or something
        content = await page.content()
        print("Page title:", await page.title())
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_ph())
