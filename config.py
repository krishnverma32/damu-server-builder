"""Bot configuration — reads from .env and exposes typed constants."""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Core ──────────────────────────────────────────────────────────────────────
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
GIPHY_API_KEY: str = os.getenv("GIPHY_API_KEY", "")
MONGO_URI: str = os.getenv("MONGO_URI", "")
YOUTUBE_OAUTH_TOKEN_JSON: str = os.getenv("YOUTUBE_OAUTH_TOKEN_JSON", "")

# ── Channel / Role IDs ───────────────────────────────────────────────────────
MOD_LOG_CHANNEL_ID: int = int(os.getenv("MOD_LOG_CHANNEL_ID", "0"))
TICKET_LOG_CHANNEL_ID: int = int(os.getenv("TICKET_LOG_CHANNEL_ID", "0"))
SUPPORT_ROLE_ID: int = int(os.getenv("SUPPORT_ROLE_ID", "0"))

# ── Developer IDs ─────────────────────────────────────────────────────────
DEV_IDS: list[int] = [
    int(i.strip()) for i in os.getenv("DEV_IDS", "").split(",") if i.strip()
]
SERVER_BUILD_OWNER_ID: int = int(os.getenv("SERVER_BUILD_OWNER_ID", "486555340670894080"))
BOT_OWNER_ID: int = int(os.getenv("BOT_OWNER_ID", str(SERVER_BUILD_OWNER_ID)))
SERVER_BUILD_BYPASS_IDS: list[int] = [
    int(i.strip()) for i in os.getenv("SERVER_BUILD_BYPASS_IDS", "").split(",") if i.strip()
]

# ── AI Settings ───────────────────────────────────────────────────────────
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL: str = "nvidia/nemotron-nano-9b-v2:free"
AI_FALLBACK_MODELS: list[str] = [
    "nvidia/nemotron-nano-9b-v2:free",     # NVIDIA 9B — fast & reliable
    "arcee-ai/trinity-large-preview:free", # Arcee 400B MoE — smart
    "stepfun/step-3.5-flash:free",         # StepFun 196B MoE — reasoning
    "google/gemma-3-27b-it:free",          # Google Gemma — backup
    "arcee-ai/trinity-mini:free",          # Arcee Mini — last resort
]
AI_MAX_RETRIES: int = 2
AI_MAX_HISTORY: int = 10
AI_RATE_LIMIT: int = 5          # requests per minute per user
AI_RATE_WINDOW: float = 60.0    # seconds


# ── Leveling ──────────────────────────────────────────────────────────────
XP_PER_MESSAGE_MIN: int = 15
XP_PER_MESSAGE_MAX: int = 25
XP_COOLDOWN: int = 60           # seconds between XP gains
LEVEL_ROLES: dict[int, int] = {
    # level: role_id  — configure via .env or here
    # 5: 123456789,
    # 10: 987654321,
}

# ── Paths ─────────────────────────────────────────────────────────────────
DATA_DIR: str = "data"
DATABASE_FILE: str = os.getenv("DATABASE_FILE", f"{DATA_DIR}/bot.db")
MEMORY_FILE: str = f"{DATA_DIR}/memory/user_memory.json"
XP_FILE: str = f"{DATA_DIR}/levels/xp_data.json"
TICKET_LOG_FILE: str = f"{DATA_DIR}/tickets/ticket_log.json"
WARNINGS_FILE: str = f"{DATA_DIR}/warnings.json"
ANALYTICS_FILE: str = f"{DATA_DIR}/analytics.json"
DASHBOARD_CONFIG_FILE: str = f"{DATA_DIR}/dashboard_config.json"
VERIFICATION_CONFIG_FILE: str = f"{DATA_DIR}/verification_config.json"
AUTOMOD_FILE: str = f"{DATA_DIR}/automod/offenses.json"

# ── Bot Meta ──────────────────────────────────────────────────────────────
BOT_NAME: str = "ServerBot"
BOT_VERSION: str = "2.0.0"
BOT_COLOR: int = 0x5865F2       # blurple
