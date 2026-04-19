
from browser_use.browser.profile import BrowserProfile
import pydantic

try:
    profile = BrowserProfile(
        headless=True,
        user_data_dir="./test_profile",
        args=["--no-sandbox"],
        viewport={"width": 1280, "height": 900}
    )
    print("✅ BrowserProfile initialized successfully with current kwargs.")
    print("Fields:", profile.model_dump())
except Exception as e:
    print(f"❌ BrowserProfile initialization failed: {e}")
    # Inspect fields
    print("Available fields in BrowserProfile:")
    try:
        from pydantic import ValidationError
        print(BrowserProfile.__fields__.keys())
    except:
        print("Could not inspect fields via __fields__")
