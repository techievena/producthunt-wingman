"""
Configuration management for ProductHunt Wingman.
Loads from .env file with sensible defaults.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from server directory
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    # Try .env.example as fallback for structure reference
    load_dotenv(Path(__file__).parent / ".env.example")


class Config:
    """Central configuration singleton."""

    # Crustdata
    CRUSTDATA_API_KEY: str = os.getenv("CRUSTDATA_API_KEY", "")

    # LLM
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # ProductHunt
    PRODUCTHUNT_API_TOKEN: str = os.getenv("PRODUCTHUNT_API_TOKEN", "")
    PRODUCTHUNT_API_KEY: str = os.getenv("PRODUCTHUNT_API_KEY", "")
    PRODUCTHUNT_API_SECRET: str = os.getenv("PRODUCTHUNT_API_SECRET", "")

    # Campaign
    LAUNCH_DATE: str = os.getenv("LAUNCH_DATE", "2026-05-10")
    DAILY_CONNECTION_BUDGET: int = int(os.getenv("DAILY_CONNECTION_BUDGET", "13"))
    PH_LAUNCH_URL: str = os.getenv("PH_LAUNCH_URL", "")

    # Message template (default — will be personalized per prospect)
    DEFAULT_MESSAGE_TEMPLATE: str = """Hey {first_name},

Big day for me today 🙌

We just launched on Product Hunt.

{personalization_hook}

Would really appreciate your support if you get a minute to upvote it and share your thoughts:
👉 {launch_url}

Thanks a ton ❤️ Means a lot."""

    # Server — default 0.0.0.0 so Railway/Render can route traffic;
    # set HOST=127.0.0.1 in .env for local-only binding
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "3847"))

    # Database — override DB_PATH in env to persist across deploys
    # (e.g. Railway volume at /data/wingman.db)
    DB_PATH: str = os.getenv(
        "DB_PATH", str(Path(__file__).parent / "wingman.db")
    )

    # Rate limits (safety margins)
    MIN_DELAY_BETWEEN_ACTIONS_SEC: int = 45  # Minimum seconds between LinkedIn actions
    MAX_DELAY_BETWEEN_ACTIONS_SEC: int = 120  # Maximum seconds
    SCAN_INTERVAL_MIN_MINUTES: int = 45  # Min interval between acceptance scans
    SCAN_INTERVAL_MAX_MINUTES: int = 90  # Max interval

    # LinkedIn Groups — PH community groups to scrape for prospects
    LINKEDIN_GROUPS: list = [
        "https://www.linkedin.com/groups/9274220/",
        "https://www.linkedin.com/groups/14044386/",
        "https://www.linkedin.com/groups/14009305/",
        "https://www.linkedin.com/groups/14341020/",
        "https://www.linkedin.com/groups/9244713/",
        "https://www.linkedin.com/groups/4810106/",
        "https://www.linkedin.com/groups/3746827/",
        "https://www.linkedin.com/groups/9357376/",
        "https://www.linkedin.com/groups/10539551/",
        "https://www.linkedin.com/groups/9560070/",
        "https://www.linkedin.com/groups/9510024/",
        "https://www.linkedin.com/groups/14409074/",
        "https://www.linkedin.com/groups/14284154/",
        "https://www.linkedin.com/groups/9511205/",
        "https://www.linkedin.com/groups/9184645/",
        "https://www.linkedin.com/groups/12966775/",
        "https://www.linkedin.com/groups/14306622/",
        "https://www.linkedin.com/groups/14270483/",
        "https://www.linkedin.com/groups/14309368/",
        "https://www.linkedin.com/groups/14314914/",
        "https://www.linkedin.com/groups/12135377/",
        "https://www.linkedin.com/groups/9355156/",
        "https://www.linkedin.com/groups/9153860/",
    ]


config = Config()
