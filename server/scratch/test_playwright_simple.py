
import asyncio
from playwright.async_api import async_playwright

async def test_playwright():
    print("🚀 Starting Playwright test...")
    async with async_playwright() as p:
        print("🌐 Launching browser...")
        browser = await p.chromium.launch(headless=True)
        print("📄 Opening page...")
        page = await browser.new_page()
        print("🔗 Navigating to google.com...")
        await page.goto("https://www.google.com")
        print(f"✅ Success! Page title: {await page.title()}")
        await browser.close()

if __name__ == "__main__":
    try:
        asyncio.run(test_playwright())
    except Exception as e:
        print(f"❌ Playwright failed: {e}")
