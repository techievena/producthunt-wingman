"""
Database layer for ProductHunt Wingman.
SQLite via aiosqlite — async CRUD for prospects, groups, config, activity log.
"""
import json
import aiosqlite
from datetime import datetime
from pathlib import Path
from config import config

DB_PATH = config.DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS prospects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL DEFAULT 'manual',
    ph_username     TEXT,
    linkedin_url    TEXT    UNIQUE NOT NULL,
    twitter_handle  TEXT,
    display_name    TEXT,
    first_name      TEXT,
    headline        TEXT,
    location        TEXT,
    company         TEXT,
    ph_streak_days  INTEGER DEFAULT 0,
    enrichment_data TEXT,           -- JSON blob from Crustdata /person/enrich
    skills          TEXT,           -- comma-separated skills from enrichment
    post_snippet    TEXT,           -- most recent LinkedIn post text (from enrichment)
    outreach_message TEXT,          -- final personalised DM text
    status          TEXT    NOT NULL DEFAULT 'discovered',
    -- status flow: discovered → queued → sending → sent → accepted → messaging → messaged → replied → skipped
    priority        INTEGER NOT NULL DEFAULT 0,  -- higher = send sooner
    scheduled_date  TEXT,           -- ISO YYYY-MM-DD
    sent_at         TEXT,
    accepted_at     TEXT,
    messaged_at     TEXT,
    cooldown_until  TEXT,
    error_message   TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS linkedin_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT    UNIQUE NOT NULL,
    name        TEXT,
    last_scraped TEXT,
    member_count INTEGER DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS config (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT    NOT NULL,
    prospect_id INTEGER REFERENCES prospects(id),
    linkedin_url TEXT,
    status      TEXT    NOT NULL DEFAULT 'ok',   -- ok | error | warn
    detail      TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_prospects_status        ON prospects(status);
CREATE INDEX IF NOT EXISTS idx_prospects_scheduled     ON prospects(scheduled_date, status);
CREATE INDEX IF NOT EXISTS idx_activity_log_created    ON activity_log(created_at DESC);
"""


# Valid column names for dynamic updates (SQL injection guard)
_ALLOWED_EXTRA_COLUMNS = {
    "scheduled_date", "sent_at", "accepted_at", "messaged_at",
    "cooldown_until", "error_message", "outreach_message",
}


async def _migrate_db():
    """Add columns introduced after initial release to existing DBs."""
    new_columns = [
        ("skills",       "TEXT"),
        ("post_snippet", "TEXT"),
    ]
    async with aiosqlite.connect(DB_PATH) as db:
        for col, col_def in new_columns:
            try:
                await db.execute(f"ALTER TABLE prospects ADD COLUMN {col} {col_def}")
                await db.commit()
            except Exception:
                pass  # column already exists


async def init_db():
    """Create all tables, run migrations, and seed default config values."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(SCHEMA)
        await db.commit()
    await _migrate_db()

    # Seed default config if not already present
    defaults = {
        "launch_date":             config.LAUNCH_DATE,
        "daily_budget":            str(config.DAILY_CONNECTION_BUDGET),
        "message_template":        config.DEFAULT_MESSAGE_TEMPLATE,
        "ph_launch_url":           config.PH_LAUNCH_URL,
        "scheduler_running":       "false",
        "scanner_running":         "false",
        "credits_used":            "0",
    }
    for key, value in defaults.items():
        await upsert_config(key, value, skip_if_exists=True)

    # Seed LinkedIn groups from config.py
    for url in config.LINKEDIN_GROUPS:
        await add_linkedin_group(url)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

async def get_config(key: str, default=None) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT value FROM config WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row["value"] if row else default


async def upsert_config(key: str, value: str, skip_if_exists: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if skip_if_exists:
            await db.execute(
                "INSERT OR IGNORE INTO config(key,value) VALUES(?,?)", (key, value)
            )
        else:
            await db.execute(
                "INSERT INTO config(key,value,updated_at) VALUES(?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value),
            )
        await db.commit()


# ---------------------------------------------------------------------------
# Prospect CRUD
# ---------------------------------------------------------------------------

async def upsert_prospect(data: dict) -> int:
    """Insert or update a prospect by linkedin_url. Returns row id."""
    now = datetime.utcnow().isoformat() + "Z"
    enrichment = data.get("enrichment_data")
    if isinstance(enrichment, dict):
        enrichment = json.dumps(enrichment)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """INSERT INTO prospects
               (source, ph_username, linkedin_url, twitter_handle,
                display_name, first_name, headline, location, company,
                ph_streak_days, enrichment_data, skills, post_snippet,
                outreach_message, status, priority, scheduled_date, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(linkedin_url) DO UPDATE SET
                   source          = COALESCE(excluded.source, source),
                   ph_username     = COALESCE(excluded.ph_username, ph_username),
                   twitter_handle  = COALESCE(excluded.twitter_handle, twitter_handle),
                   display_name    = COALESCE(excluded.display_name, display_name),
                   first_name      = COALESCE(excluded.first_name, first_name),
                   headline        = COALESCE(excluded.headline, headline),
                   location        = COALESCE(excluded.location, location),
                   company         = COALESCE(excluded.company, company),
                   ph_streak_days  = MAX(excluded.ph_streak_days, ph_streak_days),
                   enrichment_data = COALESCE(excluded.enrichment_data, enrichment_data),
                   skills          = COALESCE(excluded.skills, skills),
                   post_snippet    = COALESCE(excluded.post_snippet, post_snippet),
                   priority        = MAX(excluded.priority, priority),
                   updated_at      = excluded.updated_at""",
            (
                data.get("source", "manual"),
                data.get("ph_username"),
                data["linkedin_url"],
                data.get("twitter_handle"),
                data.get("display_name"),
                data.get("first_name"),
                data.get("headline"),
                data.get("location"),
                data.get("company"),
                data.get("ph_streak_days", 0),
                enrichment,
                data.get("skills"),
                data.get("post_snippet"),
                data.get("outreach_message"),
                data.get("status", "discovered"),
                data.get("priority", 0),
                data.get("scheduled_date"),
                now,
            ),
        )
        await db.commit()
        async with db.execute(
            "SELECT id FROM prospects WHERE linkedin_url=?", (data["linkedin_url"],)
        ) as cur:
            row = await cur.fetchone()
            return row["id"]


async def get_prospect_by_url(linkedin_url: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM prospects WHERE linkedin_url=?", (linkedin_url,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_prospect_status(
    linkedin_url: str,
    status: str,
    extra: dict | None = None,
):
    """Update prospect status and optional timestamp fields."""
    now = datetime.utcnow().isoformat() + "Z"
    parts = ["status=?", "updated_at=?"]
    vals = [status, now]
    if extra:
        for k, v in extra.items():
            if k not in _ALLOWED_EXTRA_COLUMNS:
                raise ValueError(f"Column '{k}' not in allowed update columns")
            parts.append(f"{k}=?")
            vals.append(v)
    vals.append(linkedin_url)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            f"UPDATE prospects SET {', '.join(parts)} WHERE linkedin_url=?",
            vals,
        )
        await db.commit()


async def get_sent_count_today() -> int:
    """Efficient count of connections sent today (SQL, not Python)."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM prospects WHERE sent_at LIKE ?",
            (today + "%",),
        ) as cur:
            row = await cur.fetchone()
            return row["cnt"] if row else 0


async def get_prospects_due_today() -> list[dict]:
    """Return queued prospects whose scheduled_date <= today."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM prospects WHERE status='queued' AND scheduled_date<=? ORDER BY priority DESC, id ASC",
            (today,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_accepted_not_messaged() -> list[dict]:
    """Return prospects who accepted the connection but haven't been DM'd yet."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM prospects WHERE status='accepted' ORDER BY accepted_at ASC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_sent_not_accepted() -> list[dict]:
    """Return prospects we sent a connection to but haven't heard back yet."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM prospects WHERE status='sent' ORDER BY sent_at ASC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_all_prospects(
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            async with db.execute(
                "SELECT * FROM prospects WHERE status=? ORDER BY priority DESC, id ASC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT * FROM prospects ORDER BY priority DESC, id ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_pipeline_stats() -> dict:
    """Return counts per status for the dashboard funnel."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT status, COUNT(*) as cnt FROM prospects GROUP BY status"
        ) as cur:
            rows = await cur.fetchall()
        stats = {r["status"]: r["cnt"] for r in rows}
        async with db.execute("SELECT COUNT(*) as total FROM prospects") as cur:
            row = await cur.fetchone()
            stats["total"] = row["total"]
        return stats


# ---------------------------------------------------------------------------
# LinkedIn Groups CRUD
# ---------------------------------------------------------------------------

async def add_linkedin_group(url: str, name: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT OR IGNORE INTO linkedin_groups(url,name) VALUES(?,?)", (url, name)
        )
        await db.commit()
        async with db.execute(
            "SELECT id FROM linkedin_groups WHERE url=?", (url,)
        ) as cur:
            row = await cur.fetchone()
            return row["id"]


async def get_active_groups() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM linkedin_groups WHERE active=1"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def mark_group_scraped(group_id: int, member_count: int = 0):
    now = datetime.utcnow().isoformat() + "Z"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE linkedin_groups SET last_scraped=?, member_count=? WHERE id=?",
            (now, member_count, group_id),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Activity Log
# ---------------------------------------------------------------------------

async def log_action(
    action: str,
    status: str = "ok",
    linkedin_url: str | None = None,
    prospect_id: int | None = None,
    detail: str | None = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT INTO activity_log(action,prospect_id,linkedin_url,status,detail) VALUES(?,?,?,?,?)",
            (action, prospect_id, linkedin_url, status, detail),
        )
        await db.commit()


async def get_recent_activity(limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
